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
13. `gate`、`terminal` 和所有控制条件只能由 GraphX Core 求值。
14. Codex task 和 Host Adapter 只能通过 GraphX 的结构化接口访问运行状态，不能直接读取或写入 SQLite。

## 2. 初始范围

### 2.1 包含

- Python 3.12 本地进程中的 Config 校验、immutable IR 和纯 Core Executor；
- `agent`、`command`、`verifier`、`gate`、`terminal` 节点及确定性串行调度；
- Codex Skill、短事务 MCP 协议，以及每个 Agent attempt 对应的独立 Codex task；
- SQLite 权威状态、幂等事务、mutation lease、恢复与 `AMBIGUOUS` 裁决；
- 运行时边界校验、故障注入测试和发布门禁。

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
- 受控 child workflow；

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
GraphX Python Process
    ├── MCP Boundary
    ├── Application / Query Service
    ├── Config Validator
    ├── Workflow Compiler
    ├── Graph Analyzer
    ├── Deterministic Scheduler
    ├── Condition Evaluator
    ├── Transition Service
    └── Store -> private SQLite
```

Codex App 是用户界面和 Agent Host。GraphX Python Core 是无 UI 的 Graph 权威；SQLite 的访问与隔离规则见第 3.4 节。

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

`command` 和 `verifier` 不要求独立对话。Host Adapter 只执行 IR 已经声明的外部动作并返回结构化事实；它不能解释依赖、条件或完成语义。`gate` 和 `terminal` 不离开 GraphX Python Process，由 Condition Evaluator 和 Transition Service 根据不可变 IR 与权威 RunState 求值。

### 3.4 状态访问与执行隔离

#### 3.4.1 状态数据库边界

Codex 总控任务、Agent task 和 Host Adapter 都是不可信的外部参与者，只能调用 GraphX 暴露的结构化 MCP 操作。MCP 不提供原始 SQL、数据库连接、数据库文件路径、任意表查询或通用状态写入操作。

只有 Store 模块可以打开 SQLite 连接。Application Service 将读取交给只读 Query Service，将状态修改交给 Transition Service；其他模块不得绕过这两个服务访问 Store。Transition Service 在同一 transaction 中完成前置状态检查、约束校验、事件写入和状态提交。

#### 3.4.2 Host 执行隔离

SQLite 文件必须位于所有 Codex workspace 之外，并且不能挂载或暴露给总控任务、Agent task 或 Host Adapter 的执行环境。Host 启动 Run 时必须验证固定的执行隔离要求；无法保证状态目录隔离时，不得派发 Agent 节点。GraphX 不通过 prompt 中的行为要求声称实现数据库隔离。

GraphX Core 不实现通用 sandbox。文件系统隔离由 Host 提供，但“GraphX 私有状态目录对 Agent 不可见”是 Agent 执行的硬前置条件，而不是可降级选项。Run 必须冻结 Host identity、workspace identity、隔离模式和对应的规范化 snapshot/hash，恢复时重新验证；不一致时进入 `BLOCKED`，不能继续派发。

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
        "outputs": {"result": "agentResult"},
        "retry": {"maxAttempts": 2}
      },
      {
        "id": "verify-material-system",
        "type": "verifier",
        "dependsOn": ["develop-material-system"],
        "check": {
          "id": "material-system-tests",
          "kind": "command",
          "argv": ["pytest", "tests/material_system"],
          "successExitCodes": [0]
        },
        "inputs": {"candidate": {"from": "develop-material-system.result"}},
        "outputs": {"evidence": "verificationEvidence"}
      },
      {
        "id": "done",
        "type": "terminal",
        "dependsOn": ["verify-material-system"],
        "condition": {
          "eq": [
            {"from": "verify-material-system.evidence.status"},
            {"literal": "passed"}
          ]
        },
        "outcome": "success"
      }
    ]
  }
}
```

示例不是内置流程。GraphX 不包含 `develop-material-system` 的业务逻辑。

Agent Node 的 `task` 保持非空、有界的自由文本。GraphX Core 不从自然语言中推断依赖、分支、重试或完成条件；影响控制流的要求必须由结构化 `outputs`、显式节点、受限条件和 terminal 表达。Agent 的自然语言完成声明只能作为诊断，不能成为未经独立检查的成功依据。

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
- attempt ID 与结果类型对应的 execution identity 匹配；
- NodeResult 属于当前派发；
- retry 没有超过上限；
- terminal 的依赖和条件已经满足。

### 5.4 数据库约束

- 主键和外键；
- node attempt 唯一编号；
- request/result 幂等键唯一；
- 每个 workspace 至多一个 mutation lease；
- 每个 attempt 至多一个 ExecutionHandle，且 `(host_id, thread_id)` 在所有 Codex handle 中唯一；
- 已绑定 ExecutionHandle 的 thread ID 非空且不可变；未绑定的 `DISPATCHING` attempt 可以暂时没有 ExecutionHandle；
- 所有状态变化在单个事务中提交。

### 5.5 验证权威和保证边界

GraphX 必须区分“候选产物已经生成”和“Workflow 按 Config 验收了该产物”。验证层级由 Workflow Config 显式声明：

| 层级 | 作用 | 权威性 |
|---|---|---|
| Agent task-local 自检 | 尽早发现缺陷并降低返工 | Agent 提供的证据；不能冒充已声明的 Host Verifier |
| Host 执行的 `command` / `verifier` | 执行 IR 中固定的检查并采集退出码和输出 | 对“声明的检查确实在绑定 revision 上执行”提供机械证据 |
| 独立 Review Agent | 检查需求符合性和代码质量 | 独立但仍是概率性的语义判断 |
| Terminal | 汇总 Graph 中声明的必要条件 | 只有所有依赖和条件满足后才能提交 Run 成功 |

正式 Verifier 的 tagged check spec 来自 Workflow Config；Compiler 必须校验其 kind-specific 字段，并在不可变 Workflow IR 中保存稳定 check ID 和规范化 check hash，不能由被验证 Agent 在结果中临时指定。Verification Evidence 必须绑定 run、node、attempt、被验证 workspace revision、check ID/hash 和结构化结果；stale revision、错误身份、check hash 不匹配或仅有自然语言成功声明都必须拒绝。

GraphX 只保证声明的验证步骤被正确调度、执行、绑定和记录，不证明其语义完备性。

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

完整合法转换如下；未列出的转换一律拒绝：

| From | To | Guard / effect |
|---|---|---|
| `PENDING` | `READY` | 依赖成功且 Config 声明的适用条件成立 |
| `PENDING` | `SKIPPED` | 适用条件为假且节点允许跳过 |
| `PENDING` | `CANCELLED` | Run 取消，且节点尚未派发 |
| `READY` | `DISPATCHING` | 外部执行节点；原子创建 attempt/dispatch intent，mutation 同时获取 lease |
| `READY` | `VERIFYING` | Core 内部求值 `gate` 或 `terminal`，不创建 Host execution |
| `READY` | `BLOCKED` | 固定执行隔离或必需外部前置条件在派发前不满足，不创建 attempt/lease |
| `READY` | `CANCELLED` | Run 取消，且没有外部执行 |
| `DISPATCHING` | `RUNNING` | command 已确认启动，或 Agent activate 已提交 |
| `DISPATCHING` | `FAILED` | 已证明外部执行没有开始且本 attempt 创建失败 |
| `DISPATCHING` | `AMBIGUOUS` | 无法唯一确认 task identity 或外部执行是否开始；mutation lease 保留 |
| `DISPATCHING` | `CANCELLED` | 已证明执行没有开始且 Run 取消 |
| `RUNNING` | `VERIFYING` | 收到结果、失败、blocked 或取消证据，交由 Core 校验 |
| `RUNNING` | `AMBIGUOUS` | Host 丢失且无法确定执行或 mutation 结果；mutation lease 保留 |
| `VERIFYING` | `SUCCEEDED` | 身份、Schema、输出、revision 和 evidence 全部通过 |
| `VERIFYING` | `FAILED` | 已验证的失败，或成功结果不能满足声明的输出契约 |
| `VERIFYING` | `BLOCKED` | 已验证的外部前置条件缺失 |
| `VERIFYING` | `AMBIGUOUS` | mutation 结果或 workspace revision 无法对账 |
| `VERIFYING` | `CANCELLED` | 取消已经确认，且 mutation 已证明未发生或已完成对账 |
| `FAILED` | `READY` | retry policy 允许；下一次派发创建新 attempt |
| `BLOCKED` | `READY` | 显式 resume，并重新验证依赖、隔离和外部前置条件 |
| `AMBIGUOUS` | `DISPATCHING` | 找回唯一 bootstrap task，但尚未 activate |
| `AMBIGUOUS` | `RUNNING` | 找回并确认仍在执行的 attempt |
| `AMBIGUOUS` | `VERIFYING` | 找回结果或用户提供裁决证据，必须继续正常结果校验 |
| `AMBIGUOUS` | `FAILED` | 已证明执行未开始或失败；按第 7.3 节处理 lease |
| `AMBIGUOUS` | `CANCELLED` | 用户裁决取消，且按第 7.3 节完成 mutation 对账 |

`SUCCEEDED`、`SKIPPED` 和 `CANCELLED` 没有后续转换。所有转换只由 Transition Service 提交；Agent task、Host Adapter 和 Scheduler 只能提出结构化请求。

### 6.2 RunState

```text
VALIDATED
RUNNING
SUCCEEDED
FAILED
BLOCKED
AMBIGUOUS
CANCELLED
```

完整合法转换如下：

| From | To | Guard / effect |
|---|---|---|
| `VALIDATED` | `RUNNING` | 显式 start，Host binding 与恢复前置检查通过 |
| `VALIDATED` | `CANCELLED` | Run 在首次调度前取消 |
| `RUNNING` | `SUCCEEDED` | 仅 success terminal node 可以提交 |
| `RUNNING` | `FAILED` | failure terminal 提交，或 mandatory failure 使所有 terminal 不可达且 retry 已耗尽 |
| `RUNNING` | `BLOCKED` | 没有可调度节点，且至少一个必要节点为 `BLOCKED` |
| `RUNNING` | `AMBIGUOUS` | 存在未裁决的 ambiguous attempt |
| `RUNNING` | `CANCELLED` | 取消已提交，且所有活动 attempt 已完成安全对账 |
| `BLOCKED` | `RUNNING` | 显式 resume，所有阻塞前置条件重新验证通过 |
| `BLOCKED` | `CANCELLED` | 用户取消且没有未裁决 mutation |
| `AMBIGUOUS` | `RUNNING` | 所有 ambiguous attempt 已裁决且 Workflow 仍可继续 |
| `AMBIGUOUS` | `FAILED` | 裁决后 terminal 不可达且 retry 已耗尽 |
| `AMBIGUOUS` | `CANCELLED` | 所有 mutation 已裁决后用户取消 |

只有 Config 成功编译并持久化为 immutable IR 后才创建初始状态为 `VALIDATED` 的 Run；非法 Workflow 不产生 RunState。`SUCCEEDED`、`FAILED` 和 `CANCELLED` 是 Run terminal state，没有后续转换。所有 RunState 转换只由 Transition Service 提交。

### 6.3 确定性调度

初始版本每次只派发一个节点。ready node 按稳定 node ID 排序，选择第一个合法节点。

```text
same WorkflowIR + same RunState
    -> same SchedulingDecision
```

这避免把并发顺序、共享工作区和多 Agent 竞态引入初始实现。
串行 Scheduler 是 MVP 的吞吐策略，不能替代第 7 节由 SQLite 强制的持久化 mutation safety。

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

workspace revision 只描述 Workflow 声明的权威项目内容，不能把缓存、索引、日志或其他派生元数据的变化当成源码 mutation。revision provider 不得简单依赖 workspace 目录时间或无差别哈希所有文件；它必须覆盖 tracked 文件的修改和删除，以及 revision policy 声明为权威的 untracked 新文件，同时排除该 policy 声明的派生路径。revision policy 在 Run 开始前固定并随 IR 保存。GraphX 不理解任何具体派生工具；需要强一致性刷新时，由 Workflow Config 使用普通 Command Node 表达。

## 8. Codex task 映射

### 8.1 Codex ExecutionHandle

```text
ExecutionHandle
    run_id
    node_id
    attempt_id
    dispatch_token
    host_kind = codex
    thread_id
    host_id
    workspace_id
    activated_at
    created_at
```

Agent 派发使用两阶段协议：

1. GraphX 先持久化 attempt、dispatch intent 和不可猜测的 dispatch token；
2. Host 创建只包含 attempt identity 和 dispatch token 的 bootstrap task，不发送语义 Task Contract；
3. Host 调用 `bind(attempt_id, dispatch_token, host_id, thread_id)`；GraphX 在一个 transaction 中校验当前 attempt、token 和 bootstrap identity，强制 `(host_id, thread_id)` 唯一，然后创建不可变 ExecutionHandle；内容完全相同的重复 bind 才幂等成功；
4. Host 调用 activate；GraphX 在一个 transaction 中重新验证 attempt、thread、适用时的 lease、workspace revision 和执行隔离，持久化冻结的 Task Contract 与 activation event，将节点转换为 `RUNNING`，然后返回 Task Contract；
5. Host 把 Task Contract 发送给已绑定 task。重复 activate 返回完全相同的 Contract，不产生第二次状态转换。

task 创建后、bind 前发生故障时，恢复流程使用 dispatch token 对账 bootstrap task。无法唯一确认 task identity 时，node 和 Run 都进入 `AMBIGUOUS`，且不得创建新 attempt；mutation attempt 继续保留 lease。只有在找回并绑定原 task，或证明原 task 未创建/已终止后，才能按第 6.1 节继续或失败后 retry。activate 提交后、Contract 发送前发生故障时，Host 从 GraphX 重新取得同一份冻结 Contract 并幂等重发。标题只用于展示，不能参与对账。

### 8.2 Task Contract

Agent task 获得：

- 当前 node ID 和 attempt ID；
- 节点目标；
- Config 中原样冻结的用户执行指引；
- 声明输入；
- workspace 路径和基线 revision；
- side-effect class；
- 输出 Schema；
- 验收标准；
- retry/timeout 信息。

不自动注入整个 Workflow 对话历史。Codex 自己负责单个 task 的上下文管理。

Host Adapter 可以给 Task Contract 增加 GraphX 所需的身份、结果格式和“不允许推进 Graph”的固定边界说明，但不能改写 Config 声明的任务目标。Task Contract 必须包含当前 Run 冻结的 Host binding ID/hash 和执行隔离摘要，但不得包含 GraphX 状态目录、数据库路径、数据库凭证或内部 Store 标识。

### 8.3 NodeResult

```text
NodeResult = AgentNodeResult | MechanicalNodeResult

CommonNodeResult
    run_id
    node_id
    attempt_id
    status
    outputs
    evidence
    workspace_revision
    diagnostics

AgentNodeResult
    kind = agent
    common
    dispatch_token
    thread_id

MechanicalNodeResult
    kind = mechanical
    common
    execution_id
```

Agent result 必须匹配已绑定 Codex ExecutionHandle；`command` 和 `verifier` result 必须匹配 GraphX 派发并持久化的 mechanical execution ID，不需要 thread。`gate` 和 `terminal` 不接收外部 NodeResult。所有结果必须通过第 5.1–5.5 节的身份、状态、输出、revision 和 evidence 校验后才能 commit。

## 9. SQLite 权威状态

建议表：

```text
workflows
runs
run_host_bindings
run_nodes
attempts
execution_handles
mechanical_executions
node_outputs
events
mutation_leases
idempotency_keys
```

### 9.1 权威关系

- SQLite 是运行状态权威；
- Workflow IR 以规范 JSON 和内容哈希保存；
- `run_host_bindings` 以规范化 snapshot 和 hash 保存 Host identity、workspace identity 和固定执行隔离要求，创建后不可变；
- Codex 对话不是状态权威；task 标题只用于展示，thread ID 用于恢复和对账；
- 日志可以丢失，已提交状态不能依赖日志恢复。

### 9.2 事务规则

- 所有状态转换在 transaction 中完成；
- 读取当前状态与写入新状态必须处于同一 transaction；
- 每个提交带 expected previous state；
- 重复 request 通过 idempotency key 返回原结果；
- 数据库访问和模块依赖必须遵守第 3.4 节，任何越层访问都属于实现错误。

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
    application/
        service.py
        query.py
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
        transition_service.py
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

Application Service、Query Service、编译、Graph 分析、状态转换、存储和 Host Adapter 必须保持独立。Store 是唯一数据库边界，Condition Evaluator 和 Transition Service 是唯一控制求值边界。

## 11. MCP 操作

每次 MCP 调用应短小、事务化，不提供一个阻塞数小时的 `run` tool。

初始操作：

```text
graphx_validate_workflow
graphx_start_run
graphx_next
graphx_bind_task
graphx_activate_task
graphx_submit_result
graphx_fail_attempt
graphx_reconcile_attempt
graphx_inspect_run
graphx_resume_run
graphx_cancel_run
```

### 11.1 Host 循环

```text
start/resume
    -> next
    -> receive NodeDispatch
    -> create bootstrap Codex task when node.type == agent
    -> bind thread ID
    -> activate and receive Task Contract
    -> execute or wait
    -> submit NodeResult
    -> next
    -> repeat until terminal
```

Host Adapter 不能请求跳过 mandatory node，也不能提交不是当前 attempt 的结果。

## 12. 受控任务拆分

MVP 不包含 child workflow。Agent 可以在自己的 task 内拆分步骤，但这些步骤不成为 GraphX Node。

后续 child workflow 只能由 Config 显式授权，并编译为独立、不可变的 child IR；parent IR 不得修改，parent node 等待 child terminal，child 中每个 Agent attempt 仍对应独立 Codex task。

## 13. 实施阶段

前六个阶段构成初始 MVP。每个阶段都必须产生一条可执行、可测试的纵向链路，不能把本阶段依赖的安全语义推迟到后续阶段补充。

### Phase 1：语义冻结和工程骨架

交付：

- 第 10 节定义的 Python 包骨架和工具配置；
- Workflow Config、Workflow IR、RunState 的独立严格模型，以及完整状态转换表；
- MCP 请求、NodeDispatch、NodeResult 和错误响应的版本化 Schema；
- 第 3.4 节的模块依赖与固定执行隔离边界。

完成条件：所有公开数据结构、状态转换和模块所有权没有未决语义；边界测试能够拒绝未知字段、非法枚举和越层数据库访问。

### Phase 2：纯 Core Executor

交付：

- 第 4 节及第 5.1–5.3 节的 Config 校验、immutable IR Compiler 和 Graph 语义分析；
- verifier check identity/hash、稳定 IR 序列化和内容哈希；
- 第 6 节的 Condition Evaluator、显式 transition function 和状态语义；
- ready 计算和稳定串行 Scheduler。

完成条件：纯内存测试覆盖全部转换并满足第 6.3 节确定性；Host 无法参与 `gate` 或 `terminal` 求值。

### Phase 3：持久化机械工作流

交付：

- 第 9 节的 SQLite Schema、migration、Store transaction API 和持久化实体；
- Application Service、只读 Query Service 和结构化 MCP tools；
- 符合第 3.3–3.4 节边界的 `command -> verifier -> gate -> terminal` 链路；
- 每个 transaction 边界的启动恢复和一致性检查。

完成条件：机械 Workflow 能在进程重启后继续；第 3.4.1 节的状态数据库边界全部成立。

### Phase 4：只读 Codex Agent 链路

交付：

- GraphX Skill、Codex Host Adapter，以及第 3.4.2 节的不可变 Run Host binding；
- Agent NodeDispatch 和第 8 节的两阶段 task 协议；
- 第 5 节的 NodeResult 校验；
- task 生命周期故障对账及 inspect、resume、cancel 用户流程。

本阶段只允许非 mutation Agent 节点。这样可以先验证 task 生命周期和恢复协议，而不在尚未完成 mutation 对账前暴露 workspace 写入。

完成条件：每个 Agent attempt 对应一个可恢复、可见、身份明确的 Codex task；GraphX 在 bind 和 activate 完成前不发送语义 Task Contract；Agent 执行环境无法访问 GraphX 私有状态目录。

### Phase 5：安全 Workspace Mutation

交付：

- 第 7.4 节的 workspace revision policy 和结果绑定；
- 第 7.1–7.3 节的 mutation lease、激活复检和释放规则；
- mutation 故障对账、`AMBIGUOUS` 和显式裁决流程。

完成条件：在所有故障注入点都不会并行 mutation、自动重放不确定 mutation 或提前释放 lease；后续 mutation 在前一个 attempt 得到权威裁决前始终被阻止。

### Phase 6：MVP 加固和发布

交付：

- 第 5.5 节的 Verification Evidence 绑定和拒绝路径；
- 普通 Command Node 表达外部刷新屏障；
- 参考 Workflow、端到端故障矩阵、操作文档和恢复手册；
- 第 14 节发布门禁。

完成条件：参考 Workflow 在正常执行、进程重启、重复请求、Host 故障和 mutation 不确定场景下都满足第 1.2 节不变量，全部发布门禁通过。

### Phase 7：受控 Child Workflow（非 MVP）

仅在基础 Executor 稳定后实现第 12 节定义的嵌套拆分，不修改 parent IR，也不阻塞 MVP 发布。

## 14. 测试门槛

必须覆盖：

- Schema 接受和拒绝；
- 未知字段、版本和枚举；
- 重复 node ID、悬空引用和类型不匹配；
- 环、不可达节点和不可达 terminal；
- ready-node 稳定排序；
- 每个合法和非法状态转换；
- `gate` 和 `terminal` 只由 Core Condition Evaluator 求值，Host 提交对应控制结果会被拒绝；
- attempt 上限；
- dispatch token 唯一性和错误 token 拒绝；
- bind 前 attempt 可持久化且不要求 ExecutionHandle；bind 后 thread ID 非空且不可变；
- thread bind 幂等性、并发冲突，以及跨 attempt 复用 `(host_id, thread_id)` 被拒绝；
- activate-before-bind、重复 activate 和错误 thread activate；
- Task Contract 在 bind/activate 前不会发送；
- task 创建响应丢失和 bind 前重启的对账，包括非 mutation attempt 不得自动重建 task；
- Agent 与 mechanical NodeResult 的 tagged identity、stale、重复和错误身份拒绝；
- mutation lease 唯一性；
- 多个 mutation node 永不并行；
- mutation task 激活前重新校验 lease、workspace revision 和执行隔离；
- transaction 前后进程终止；
- 未确认 mutation 进入 `AMBIGUOUS`；
- Agent 自报完成但 terminal 条件不满足；
- 恢复前后得到相同调度决定；
- 每个 Agent attempt 对应独立 Codex task；
- 缺失或非法 verifier check spec 在创建 RunState 前被拒绝；
- Agent task-local 自检不能替代 Config 声明的正式 Verifier；
- 只有 Store 模块能够创建 SQLite connection、执行 SQL 或取得数据库路径；
- MCP Schema、Task Contract、NodeDispatch、inspect 和错误响应都不会泄露数据库路径或内部 Store 标识；
- SQLite 状态目录位于所有 Codex workspace 外且不对总控任务、Agent task 或 Host Adapter 暴露，隔离验证失败时在 attempt 和 lease 创建前进入 `BLOCKED`；
- Host binding 的 identity、workspace 和隔离 snapshot/hash 在 Run 中不可变，恢复时不一致会阻止派发；
- MCP、Host Adapter、Scheduler、Codex task 和其他 Core 模块不能绕过 Query/Transition Service 访问 Store；
- Verification Evidence 的 check ID/hash 和 workspace revision 绑定，以及 stale evidence 拒绝；
- tracked 修改、删除和权威 untracked 新文件会改变 revision，派生索引变化不会；
- 通用 Command Node 失败会阻止其依赖节点，且 Core 不包含外部工具专属逻辑。

发布门禁：

```text
pyright
ruff check
ruff format --check
pytest
```

全部必须成功。
