# GraphX Python Task Graph Executor 实施计划

本文档是 GraphX 的产品范围、执行语义和实施顺序的唯一权威。

## 1. 产品定义

GraphX 是一个严格执行声明式 Task Graph 的本地控制器。

```text
Workflow Config owns control.
GraphX validates and advances the graph.
Codex tasks perform semantic work.
```

GraphX 只负责：

- 读取和校验 Workflow Config；
- 编译不可变 Workflow IR；
- 根据权威状态计算 ready node；
- 派发节点、接收结果并执行合法状态转换；
- 为每个 Agent attempt 记录独立 Codex task/thread；
- 强制 mutation 节点串行；
- 通过 SQLite 事务保存运行状态；
- 只有满足 Graph 中声明的 terminal 条件才结束运行。

GraphX 不负责：

- 决定工作流应该包含哪些业务阶段；
- 替 Agent 理解需求、编写代码或判断技术方案；
- 管理模型 token、compaction 或对话历史；
- 重新实现 Codex 的文件、Shell、Git 或 sandbox 工具；
- 让 Agent 自行修改 Graph 或宣布整个 Workflow 完成。

### 1.1 产品目标

给定相同的 Workflow IR 和权威 RunState，GraphX 必须产生相同的调度决定，并且在重启后能够继续从已经提交的状态执行。

### 1.2 核心不变量

1. Config 决定控制流，GraphX 不发明业务流程。
2. Workflow 在执行前完成结构和语义校验。
3. Workflow IR 在一次运行期间不可变。
4. 只有 GraphX 可以提交 NodeState 和 RunState 转换。
5. 一个 Agent attempt 对应一个独立、可见的 Codex task。
6. Codex task 以持久化的 thread ID 标识，标题不是身份。
7. 同一 workspace 同时最多有一个 mutation attempt。
8. 前一个 mutation 未完成、未失败或未裁决前，后一个 mutation 不能开始。
9. NodeResult 必须经过运行时校验，不能依赖类型注解或 Agent 自报。
10. 重复请求和重复结果提交必须幂等。
11. 不确定的 mutation 进入 `AMBIGUOUS`，不能自动重放。
12. 只有 terminal node 可以提交 Workflow 最终结果。

## 2. 初始范围

### 2.1 包含

- Python 3.12 本地进程；
- JSON Workflow Config 和 JSON Schema；
- Config 到不可变 Workflow IR 的编译；
- DAG 引用、类型、环、可达性和 terminal 校验；
- 稳定、确定性的串行节点调度；
- `agent`、`command`、`verifier`、`gate`、`terminal` 节点；
- Codex Skill + MCP Host Adapter；
- 每个 Agent attempt 一个独立 Codex task；
- SQLite RunState、attempt、thread 映射和 mutation lease；
- 有界 retry、blocked、cancel 和 ambiguous 语义；
- `validate`、`start`、`next`、`inspect`、`resume`、`cancel` 操作；
- 状态机、事务、恢复和端到端测试。

### 2.2 不包含

- GraphX 自己调用模型或维护模型对话上下文；
- headless Codex Agent Runtime；
- 通用工具网关或自定义 sandbox；
- mutation 并行执行；
- 分布式调度、队列、daemon 或多主协调；
- Dashboard、Graph 编辑器或独立 UI；
- 任意 `eval`、动态 Python 控制表达式或动态 Runner 导入；
- 通用插件系统；
- 自动产生未经配置授权的业务流程。

## 3. 总体架构

```text
Codex App
    |
    | GraphX Skill
    v
Codex Host Adapter
    |
    | short MCP calls
    v
GraphX Python Core
    ├── Config Validator
    ├── Workflow Compiler
    ├── Graph Analyzer
    ├── Deterministic Scheduler
    ├── Transition Engine
    └── SQLite Store
```

Codex App 是用户界面和 Agent Host。GraphX Python Core 是无 UI 的 Graph 权威。

### 3.1 总控任务

用户在一个 Codex 总控任务中启动或恢复 GraphX。总控任务：

- 调用 GraphX MCP tools；
- 显示 Graph 和节点状态；
- 为 Agent 节点创建可见 Codex task；
- 等待节点 task 完成；
- 把结构化结果提交给 GraphX；
- 不绕过 GraphX 自行推进 Graph。

### 3.2 Agent 节点任务

每个 Agent attempt 创建一个独立 Codex task：

```text
GraphX · <run-id> · <node-id> · attempt <n>
```

该 task 只接收当前节点的 Task Contract。它可以使用 Codex 原生工具完成工作，但不能直接修改 GraphX RunState。

Retry 创建新的 attempt 和新的 Codex task。失败 task 保留为审计记录。

### 3.3 机械节点

`command`、`verifier`、`gate` 和 `terminal` 不要求独立对话。Host Adapter 按 NodeDispatch 执行或解释它们，并将结构化结果返回 GraphX。

### 3.4 与 Superpowers 的职责边界和交接

Superpowers 与 GraphX 处于不同层次：Superpowers 提供需求澄清、工程计划和单个任务内的软件工程方法；GraphX 提供跨节点的控制权、持久化状态、调度、恢复和完成门。二者的标准交接点是 Superpowers 的 implementation plan 已经获得用户批准之后、`executing-plans` 或 `subagent-driven-development` 开始之前。

```text
Superpowers brainstorming
    -> approved Spec
    -> Superpowers writing-plans
    -> approved Implementation Plan
    -> GraphX Skill drafts Workflow Config
    -> graphx_validate_workflow
    -> user confirms the compiled graph
    -> graphx_start_run
```

交接遵循以下规则：

- GraphX Skill 可以读取已批准的 Spec 和 Implementation Plan，辅助生成候选 Workflow Config；该 Config 仍是不可信输入，必须经过正常 Schema 和 Graph 编译校验，且不能未经用户确认自动启动。
- Implementation Plan 中的两到五分钟步骤通常进入 Agent Node 的 Task Contract，不要求每一步都成为 GraphX Node。只有需要独立状态、独立 attempt、独立审查、显式依赖或恢复边界的交付单元才成为 Node。
- GraphX 开始控制 Run 后，Agent Node 不能在内部再启动 `executing-plans`、`subagent-driven-development` 等顶层执行控制器，避免产生 GraphX 无法观察、恢复和裁决的隐藏子工作流。
- Agent Node 可以在环境提供时使用 task-local Superpowers 方法，例如 `test-driven-development`、`systematic-debugging` 和 `verification-before-completion`；这些方法不能修改 Workflow IR、RunState 或绕过后续 Verifier/Gate。
- 正式的测试、独立代码审查和用户批准若影响终态，必须在 Workflow Config 中表现为显式 `command`、`verifier`、独立 `agent` 或 `gate` 节点。Agent 内部自检只能作为提前反馈。
- Superpowers 风格的实现、测试、审查和修复流程可以作为可复用 Workflow 模板或 GraphX Skill 资产提供，但不能硬编码进 GraphX Core。

如果一个 Agent Node 需要在内部运行完整的多任务执行计划，通常说明该 Node 过大；应在 Run 启动前继续拆分 Config，或在后续版本使用第 12 节的受控 child workflow。

Superpowers 是可选集成而不是 GraphX 的运行时依赖；未安装 Superpowers 时，合法 Workflow 仍可由普通 Codex task 执行。

### 3.5 CodeGraph 支持边界

CodeGraph 是 Codex 工作环境中的代码导航能力，不是 GraphX Core 的子系统。是否为仓库创建 `.codegraph/` 索引由用户决定；仓库未建立索引时，GraphX 不自动初始化索引，也不改变 Agent 的普通文件导航行为。

默认更新流程完全由 CodeGraph 管理：

```text
source changes --------> watcher / debounced incremental sync --+
                                                               +-> refreshed graph
MCP start or reconnect -> stat/hash catch-up -------------------+
```

GraphX 不实现文件 watcher、不解析 CodeGraph 数据库、不维护 CodeGraph 新鲜度状态，也不增加专用 `CodeGraphNode`。Codex 是否优先使用 CodeGraph，由仓库 `AGENTS.md` 等项目指令和可用工具决定；Host Adapter 只需保证 Agent Node 在其声明的 workspace 中运行，并获得该环境原本可用的指令和工具。没有显式 CodeGraph Command Node 时，CodeGraph 不可用不得成为 GraphX Run 的隐式失败条件。

普通代码导航不需要额外 Workflow Node。只有后续节点对“刚完成 mutation 后的最新代码图”存在明确的强一致性前置条件时，Workflow Config 才显式加入一个普通 Command Node：

```text
workspace mutation
    -> command: codegraph sync --quiet
    -> graph-dependent analysis or verification
```

该节点只是用户配置的通用命令和依赖屏障。GraphX 只执行命令、记录退出状态和推进 Graph，不理解命令语义；Host Adapter 必须把命令工作目录设置为 Node 声明的 workspace，不能继承 Adapter 进程自己的当前目录。同步失败时后续依赖节点不得运行。禁止通过固定 `sleep` 猜测 watcher 已经完成。强制全量索引属于 CodeGraph 的异常恢复行为，不是每次节点执行的常规步骤。

每个 checkout 或 worktree 必须使用与 Agent 实际 workspace 对应的 CodeGraph 根和索引。索引的并发、锁和数据库恢复由 CodeGraph 自己负责。

## 4. Workflow Config 与 IR

### 4.1 配置示例

```json
{
    "version": 1,
    "workflow": {
        "id": "pt-renderer",
        "nodes": [
            {
                "id": "develop-material-system",
                "type": "agent",
                "sideEffect": "workspaceMutation",
                "task": "Develop the material system",
                "outputs": {
                    "result": "agentResult"
                },
                "retry": {
                    "maxAttempts": 2
                }
            },
            {
                "id": "verify-material-system",
                "type": "verifier",
                "dependsOn": [
                    "develop-material-system"
                ],
                "check": {
                    "id": "material-system-tests",
                    "kind": "command",
                    "argv": ["pytest", "tests/material_system"],
                    "successExitCodes": [0]
                },
                "inputs": {
                    "candidate": {
                        "from": "develop-material-system.result"
                    }
                },
                "outputs": {
                    "evidence": "verificationEvidence"
                }
            },
            {
                "id": "done",
                "type": "terminal",
                "dependsOn": [
                    "verify-material-system"
                ],
                "condition": {
                    "eq": [
                        {
                            "from": "verify-material-system.evidence.status"
                        },
                        {
                            "literal": "passed"
                        }
                    ]
                },
                "outcome": "success"
            }
        ]
    }
}
```

示例不是内置流程。GraphX 不包含 `develop-material-system` 的业务逻辑。

### 4.2 数据层次

```text
Untrusted JSON
    -> Runtime Schema Validation
Validated WorkflowConfig
    -> Semantic Compilation
Immutable WorkflowIR
    + RunState from SQLite
    -> Deterministic Scheduling Decision
```

三类数据必须分开：

| 类型 | 含义 | 可变性 |
|---|---|---|
| `WorkflowConfig` | 通过 Schema 的外部配置 | 运行前输入 |
| `WorkflowIR` | 引用和默认值已解析的内部执行定义 | 运行期间不可变 |
| `RunState` | 一次具体运行的节点和 attempt 状态 | 仅事务化更新 |

### 4.3 IR 包含

- 稳定 workflow/node ID；
- 节点类型和 side-effect class；
- 已解析依赖和输出引用；
- 输入输出类型；
- verifier 的 tagged check spec、稳定 check ID 和规范化 check hash；
- Run 开始前固定的 workspace revision policy；
- 受限条件 AST；
- 有界 retry policy；
- 稳定调度顺序；
- terminal 定义；
- 内容哈希和 Schema 版本。

## 5. 运行时校验

静态类型不能替代运行时校验。以下数据一律视为不可信：

- Workflow JSON；
- MCP 请求；
- Codex NodeResult；
- SQLite row；
- 恢复时读取的状态；
- workspace revision 和文件路径。

校验分为四层：

### 5.1 Schema 校验

- 版本受支持；
- 必填字段存在；
- 未知字段被拒绝；
- 枚举、整数和字符串格式正确；
- retry 和 timeout 有界；
- verifier check spec 的 kind-specific 字段、命令参数和成功条件合法；
- NodeResult 与节点输出 Schema 匹配。

### 5.2 Graph 语义校验

- node ID 唯一；
- 依赖和输出引用存在；
- 类型兼容；
- Graph 无环；
- terminal 可达；
- 条件只使用受支持操作；
- side-effect class 明确；
- mutation 规则可执行。

### 5.3 状态转换校验

- 当前状态允许目标转换；
- attempt ID 和 thread ID 匹配；
- NodeResult 属于当前派发；
- retry 没有超过上限；
- terminal 的依赖和条件已经满足。

### 5.4 数据库约束

- 主键和外键；
- node attempt 唯一编号；
- request/result 幂等键唯一；
- 每个 workspace 至多一个 mutation lease；
- 必填状态和 thread 映射非空；
- 所有状态变化在单个事务中提交。

### 5.5 验证权威和保证边界

Agent Node 内部运行的测试、自审或 Superpowers verification 属于 Agent 提供的候选证据，不具有独立的机械执行保证。是否要求正式 Verifier、独立 Review 或 Human Gate 由 Workflow Config 决定；Agent 自检不能冒充或替代 Config 已声明的这些节点。GraphX 必须区分“候选产物已经生成”和“Workflow 按其 Config 验收了该产物”。

```text
Agent Node
    -> candidate output + workspace revision + claimed evidence
    -> optional Host-executed Command/Verifier
    -> optional independent Review Agent
    -> optional Human Gate
    -> Terminal condition
```

各层保证如下：

| 层级 | 作用 | 权威性 |
|---|---|---|
| Agent task-local 自检 | 尽早发现缺陷并降低返工 | Agent 提供的证据；不能冒充已声明的 Host Verifier |
| Host 执行的 `command` / `verifier` | 执行 IR 中固定的检查并采集退出码和输出 | 对“声明的检查确实在绑定 revision 上执行”提供机械证据 |
| 独立 Review Agent | 检查需求符合性和代码质量 | 独立但仍是概率性的语义判断 |
| Human Gate | 记录需要人工负责的批准或裁决 | 对批准事件权威，不自动证明技术正确性 |
| Terminal | 汇总 Graph 中声明的必要条件 | 只有所有依赖和条件满足后才能提交 Run 成功 |

正式 Verifier 的 tagged check spec 来自 Workflow Config；Compiler 必须校验其 kind-specific 字段，并在不可变 Workflow IR 中保存稳定 check ID 和规范化 check hash，不能由被验证 Agent 在结果中临时指定。Verification Evidence 必须绑定 run、node、attempt、被验证 workspace revision、check ID/hash 和结构化结果；stale revision、错误身份、check hash 不匹配或仅有自然语言成功声明都必须拒绝。

GraphX 能机械保证 Config 声明的验证步骤被正确调度、执行、绑定和记录，但不能证明测试覆盖了全部需求、测试本身正确或 Agent 的语义判断必然正确。需要更高置信度时，Config 应组合受保护的验收命令、独立 Review Agent 和 Human Gate，而不是扩大 GraphX Core 的业务判断能力。

## 6. 节点和状态

### 6.1 NodeState

```text
PENDING
READY
DISPATCHING
RUNNING
VERIFYING
SUCCEEDED
FAILED
SKIPPED
BLOCKED
AMBIGUOUS
CANCELLED
```

关键转换：

```text
PENDING -> READY
READY -> DISPATCHING
DISPATCHING -> RUNNING
RUNNING -> VERIFYING
VERIFYING -> SUCCEEDED | FAILED | BLOCKED | AMBIGUOUS
FAILED -> READY                  only through a new attempt
```

状态不能由 Agent task 直接写入。

### 6.2 RunState

```text
CREATED
VALIDATED
RUNNING
SUCCEEDED
FAILED
BLOCKED
AMBIGUOUS
CANCELLED
```

只有 terminal node 可以把 `RUNNING` 转换为 `SUCCEEDED`。

### 6.3 确定性调度

初始版本每次只派发一个节点。ready node 按稳定 node ID 排序，选择第一个合法节点。

```text
same WorkflowIR + same RunState
    -> same SchedulingDecision
```

这避免把并发顺序、共享工作区和多 Agent 竞态引入初始实现。

## 7. Mutation 串行语义

### 7.1 全局规则

任何 `sideEffect = workspaceMutation` 的节点都必须获取 workspace-scoped mutation lease。规则适用于 Agent、Command 和任何未来节点类型。

```text
workspace
    -> zero or one active mutation attempt
```

### 7.2 获取 lease

单个 SQLite transaction 完成：

1. 验证 node 为 `READY`；
2. 验证 workspace 没有 lease；
3. 创建 attempt；
4. 写入 dispatch intent；
5. 获取 lease；
6. 将 node 转换为 `DISPATCHING`；
7. 提交事务。

Host Adapter 只有在该事务成功后才能创建 Codex task 或执行 mutation。

### 7.3 释放 lease

只有以下情况可以释放：

- NodeResult 已校验并提交为 `SUCCEEDED`；
- attempt 明确失败且 mutation 结果已经对账；
- 用户明确裁决 `AMBIGUOUS`；
- mutation 被证明没有开始。

进程重启或超时本身不能释放 lease。

### 7.4 权威 workspace revision 与派生数据

workspace revision 只描述 Workflow 声明的权威项目内容，不能把缓存、索引、日志或其他派生元数据的变化当成源码 mutation。revision provider 不得简单依赖 workspace 目录时间或无差别哈希所有文件；它必须覆盖 tracked 文件的修改和删除，以及 revision policy 声明为权威的 untracked 新文件，同时排除该 policy 声明的派生路径。revision policy 在 Run 开始前固定并随 IR 保存。

`.codegraph/` 是派生索引的一个例子。CodeGraph watcher 或显式 `codegraph sync` 对该目录的写入不得改变权威源码 revision，也不得单独触发 mutation 对账失败。排除规则必须通过通用 revision policy 实现，不能在 GraphX Core 中写入 CodeGraph 专属状态逻辑。

## 8. Codex task 映射

### 8.1 ExecutionHandle

```text
ExecutionHandle
    run_id
    node_id
    attempt_id
    host_kind = codex
    thread_id
    host_id
    workspace_id
    created_at
```

Host Adapter 创建 task 后，必须先调用 bind 操作保存 thread ID，再开始节点工作。重复 bind 只有在内容完全相同时才幂等成功。

### 8.2 Task Contract

Agent task 获得：

- 当前 node ID 和 attempt ID；
- 节点目标；
- 声明输入；
- workspace 路径和基线 revision；
- side-effect class；
- 输出 Schema；
- 验收标准；
- retry/timeout 信息。

不自动注入整个 Workflow 对话历史。Codex 自己负责单个 task 的上下文管理。

### 8.3 NodeResult

```text
NodeResult
    run_id
    node_id
    attempt_id
    thread_id
    status
    outputs
    evidence
    workspace_revision
    diagnostics
```

GraphX 必须验证身份、状态、Schema 和 revision 后才能提交。

## 9. SQLite 权威状态

建议表：

```text
workflows
runs
run_nodes
attempts
execution_handles
node_outputs
events
mutation_leases
idempotency_keys
```

### 9.1 权威关系

- SQLite 是运行状态权威；
- Workflow IR 以规范 JSON 和内容哈希保存；
- Codex 对话是执行记录，不是 Graph 状态权威；
- task 标题只用于展示；
- thread ID 用于恢复和对账；
- 日志可以丢失，已提交状态不能依赖日志恢复。

### 9.2 事务规则

- 所有状态转换在 transaction 中完成；
- 读取当前状态与写入新状态必须处于同一 transaction；
- 每个提交带 expected previous state；
- 重复 request 通过 idempotency key 返回原结果；
- 不允许模块绕过 Store 直接写数据库。

## 10. Python 实施规范

### 10.1 技术栈

- Python 3.12；
- `pyproject.toml` 管理项目；
- Pyright strict 作为强制静态检查；
- Ruff 负责 lint 和格式；
- pytest 负责测试；
- Pydantic strict model 或等价 JSON Schema validator 负责外部输入；
- 标准库 `sqlite3` 负责权威状态；
- Python MCP server 提供 Codex Host Adapter 工具。

### 10.2 类型规则

核心目录：

- 禁止 `Any` 和 `dict[str, Any]`；
- 禁止用 `cast()` 代替校验；
- 禁止无说明的 `# type: ignore`；
- 所有生产函数完整标注参数和返回值；
- ID 使用 `NewType` 或 frozen value object；
- 状态使用 `Enum` 和 tagged dataclass union；
- `assert_never()` 检查联合类型分支；
- Config、IR、RunState 使用不同类型；
- IR 使用 frozen dataclass、tuple 和不可变映射；
- 外部依赖返回值在 adapter 边界重新校验。

类型检查用于减少实现错误；运行时 Schema、Graph Validator 和数据库约束保护权威状态。

### 10.3 禁止的动态能力

- `eval`、`exec`；
- 从 Workflow 导入 Python module/class；
- monkey patch 核心状态机；
- 动态 `setattr()` 修改状态；
- pickle 作为持久协议；
- 通过异常文本猜测状态；
- 把未校验 JSON cast 成领域模型。

### 10.4 建议包结构

```text
src/graphx/
    config/
        models.py
        schema.py
        loader.py
    ir/
        models.py
        compiler.py
        conditions.py
    graph/
        validation.py
        scheduler.py
    runtime/
        models.py
        transitions.py
        service.py
    store/
        schema.py
        sqlite.py
        migrations.py
    host/
        protocol.py
        codex.py
    mcp/
        server.py
        tools.py
    cli.py
tests/
    unit/
    integration/
```

编译、Graph 分析、状态转换、存储和 Host Adapter 必须保持独立。

## 11. MCP 操作

每次 MCP 调用应短小、事务化，不提供一个阻塞数小时的 `run` tool。

初始操作：

```text
graphx_validate_workflow
graphx_start_run
graphx_next
graphx_bind_task
graphx_submit_result
graphx_fail_attempt
graphx_inspect_run
graphx_resume_run
graphx_cancel_run
```

### 11.1 Host 循环

```text
start/resume
    -> next
    -> receive NodeDispatch
    -> create visible Codex task when node.type == agent
    -> bind thread ID
    -> execute or wait
    -> submit NodeResult
    -> next
    -> repeat until terminal
```

Host Adapter 不能请求跳过 mandatory node，也不能提交不是当前 attempt 的结果。

## 12. 受控任务拆分

初始版本允许 Agent 在自己的 Codex task 内部拆分实施步骤，但这些步骤不成为 GraphX Node。

需要让子任务分别拥有独立对话时，使用后续的受控 child workflow：

- 只有 Config 明确允许的节点可以请求 child workflow；
- Agent 只能提出 child Workflow Config；
- GraphX 完整校验后生成独立、不可变的 child IR；
- parent node 等待 child run terminal；
- child 中的 Agent attempt 继续一一映射到独立 Codex task；
- 不允许原地修改正在执行的 parent IR。

Child workflow 在基础 Executor 稳定后实现，不阻塞初始版本。

## 13. 实施阶段

### Phase 1：Python 骨架和 Workflow Compiler

交付：

- `pyproject.toml`；
- Pyright/Ruff/pytest 配置；
- Config Schema 和严格边界模型；
- immutable IR；
- Graph 引用、类型、环、可达性和 terminal 校验；
- verifier tagged check spec、check identity/hash 和成功条件校验；
- workspace revision policy 的规范化和校验；
- 稳定 IR 序列化和哈希。

完成条件：任何非法 Workflow 在创建 RunState 前被拒绝。

### Phase 2：纯状态机和确定性 Scheduler

交付：

- NodeState/RunState；
- 显式 transition function；
- ready 计算；
- 稳定串行调度；
- retry、blocked、cancel 和 terminal；
- NodeDispatch/NodeResult 模型。

完成条件：纯内存测试覆盖所有合法和非法转换。

### Phase 3：SQLite Store 和 Mutation Lease

交付：

- 数据库 Schema；
- transaction API；
- attempt 和 event；
- idempotency key；
- workspace mutation lease；
- 启动恢复和一致性检查。

完成条件：进程在每个 transaction 边界终止后，恢复结果保持一致，mutation 不会重复派发。

### Phase 4：Codex Skill 和 MCP Host Adapter

交付：

- MCP tools；
- 总控 Skill；
- Agent NodeDispatch；
- 独立 Codex task 创建、bind、等待和结果提交协议；
- inspect/resume/cancel 用户流程；
- 在用户引导下通过模板把已批准 Superpowers Spec/Plan 映射为候选 Workflow Config、显示映射结果、调用校验并等待用户显式确认；
- Task Contract 中 task-local 方法与隐藏顶层执行控制器的边界；
- 保持节点实际 workspace、项目指令和原生工具环境，不自动初始化或管理 CodeGraph。

完成条件：一个多节点 Workflow 能在 Codex App 中为每个 Agent attempt 显示独立任务，并严格串行推进 mutation。

### Phase 5：验证和端到端故障测试

交付：

- NodeResult Schema 校验；
- workspace revision 对账；
- stale/duplicate result 拒绝；
- task 丢失、超时和 ambiguous 恢复；
- 参考 PT Renderer Workflow；
- 端到端测试和操作文档；
- Host 执行的 Verification Evidence 及其 check ID/hash 和 workspace revision 绑定；
- 权威 workspace revision policy 与派生数据排除；
- 通用 Command Node 可表达外部新鲜度屏障，无需专用集成节点。

完成条件：故障注入不会绕过节点、重复 mutation 或提前提交 terminal。

### Phase 6：受控 Child Workflow

在基础版本稳定后实现第 12 节定义的嵌套拆分，不修改 parent IR。

## 14. 测试门槛

必须覆盖：

- Schema 接受和拒绝；
- 未知字段、版本和枚举；
- 重复 node ID、悬空引用和类型不匹配；
- 环、不可达节点和不可达 terminal；
- ready-node 稳定排序；
- 每个合法和非法状态转换；
- attempt 上限；
- thread bind 幂等性和冲突；
- stale、重复和错误身份的 NodeResult；
- mutation lease 唯一性；
- 多个 mutation node 永不并行；
- transaction 前后进程终止；
- 未确认 mutation 进入 `AMBIGUOUS`；
- Agent 自报完成但 terminal 条件不满足；
- 恢复前后得到相同调度决定；
- 每个 Agent attempt 对应独立 Codex task；
- 缺失或非法 verifier check spec 在创建 RunState 前被拒绝；
- Agent task-local 自检不能替代 Config 声明的正式 Verifier；
- Verification Evidence 的 check ID/hash 和 workspace revision 绑定，以及 stale evidence 拒绝；
- tracked 修改、删除和权威 untracked 新文件会改变 revision，派生索引变化不会；
- 通用 Command Node 失败会阻止其依赖节点，且不需要 CodeGraph 专属逻辑。

发布门禁：

```text
pyright
ruff check
ruff format --check
pytest
```

全部必须成功。

## 15. 最终产品边界

GraphX 不是另一个 Coding Agent，也不是上下文管理器。

它是一个小型 Python Graph authority：严格校验并推进声明式 Workflow，把每个语义 Agent attempt 交给独立、可见的 Codex task，并通过 SQLite 事务确保状态、幂等性和 mutation 串行。

Superpowers 交接、task-local 工程方法和 CodeGraph 导航都位于 Skill、Workflow Config 或 Host 环境边界；它们可以增强 GraphX 的可用性，但不改变 GraphX Core 作为通用 Graph authority 的职责。
