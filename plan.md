# GraphX Python Task Graph Executor 实施计划

本文档是 GraphX 产品范围、执行语义和实施顺序的规范性权威。README 和 AGENTS 只能摘要或引用本文档；发生冲突时以本文档为准。核心不变量使用稳定 requirement ID，详细语义由对应正文小节唯一拥有；实施阶段与测试必须引用 requirement ID 或权威小节，不得另行创造或覆盖语义。

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
- 为每个已绑定 AgentAttempt 记录独立 Codex task/thread；
- 强制 mutation 节点串行；
- 通过 SQLite 事务保存运行状态；
- 只有 terminal node 可以提交 Workflow Config 声明的业务结果；无法继续、取消或未裁决外部副作用可以终止或暂停 Run，但不能伪造 Workflow outcome。

GraphX 不负责：

- 决定工作流应该包含哪些业务阶段；
- 替 Agent 理解需求、编写代码或判断技术方案；
- 管理模型 token、compaction 或对话历史；
- 重新实现 Codex 的文件、Shell、Git 或 sandbox 工具；
- 让 Agent 自行修改 Graph 或宣布整个 Workflow 完成。

### 1.1 产品目标

给定相同的 Workflow IR 和权威 RunState，GraphX 必须产生相同的调度决定，并且在重启后能够继续从已经提交的状态执行。

### 1.2 核心不变量

1. **CTRL-01**：Config 决定控制流，GraphX 不发明业务流程；Run 创建后只使用该 Run 绑定的 immutable Workflow IR snapshot。
2. **CTRL-02**：Workflow 在创建 Run 前完成结构和语义校验。
3. **CTRL-03**：Workflow IR 在一次 Run 期间不可变且内容可寻址。
4. **STATE-01**：只有 Application StateCommitter 可以授权和编排 NodeState、RunState 提交；Pure Core 只决定合法转换，SQLite Adapter 只执行物理持久化。
5. **TASK-01**：每个已绑定的 Agent attempt 恰好对应一个独立、可见且身份不可变的 Codex task；bind 前只有 DispatchReservation，不是 Agent attempt。
6. **TASK-02**：Codex task 以持久化的 `(host_id, thread_id)` 标识，标题不是身份。
7. **SCHED-01**：初始 Scheduler 对每个 Run 同时最多允许一个 active external execution；ready node 按规范化 node ID 稳定排序。
8. **MUT-01**：在同一 GraphX coordination domain 内，同一 canonical workspace identity 同时最多有一个 mutation lease；owner 可以是 DispatchReservation、Agent/MechanicalAttempt，或等待 settlement verifier 的 settled mutation record。
9. **MUT-02**：前一个 mutation 未完成安全对账或未被明确裁决前，后一个 mutation 不能开始。
10. **RESULT-01**：NodeResult 必须经过运行时身份、Schema、revision 和 evidence 校验，不能依赖类型注解或 Agent 自报。
11. **IDEM-01**：重复请求和重复结果提交必须按 request identity 与 canonical payload digest 幂等；同 key 不同 payload 必须拒绝。
12. **MUT-03**：结果不确定的 mutation 进入 `ambiguous`，不能自动重放或仅因超时、进程退出、重启而释放 lease。
13. **OUTCOME-01**：只有 terminal node 可以设置 WorkflowOutcome；Run 的 operational failure 或 cancel 不产生 WorkflowOutcome；任何 Run terminal status 都要求 active external operation 已对账且 mutation lease 已结算释放。
14. **COND-01**：`when`、`gate`、`terminal` 和所有控制条件只能由 Pure Core 求值。
15. **BOUNDARY-01**：Codex task 和 Host Adapter 只能通过 GraphX 的版本化结构化接口访问控制面状态，不能直接读取或写入 SQLite。
16. **EXT-01**：SQLite transaction 与 Codex task、进程、文件系统或其他外部动作之间不存在跨系统原子提交；无法可靠查询或去重的未知外部结果必须 fail closed。

### 1.3 权威、信任与保证边界

GraphX 没有覆盖所有系统的单一“真源”。不同对象各有一个明确 authority；任何 authority 都不能越权替另一个对象证明事实。

| 对象 | 规范性 authority | 保证范围 |
|---|---|---|
| 产品范围、架构和执行语义 | 本 `plan.md` | 评审与实现的规范；不是运行时状态 |
| Run 创建前的控制意图 | 通过边界 Schema 的 Workflow Config | 只作为 Compiler 输入；不能在 Run 中动态控制 |
| 某个 Run 的控制定义 | 该 Run 绑定的 content-addressed Workflow IR snapshot | Run 期间唯一的 Graph、条件、重试、revision policy 和 terminal 定义 |
| GraphX 已提交的控制面状态 | 同一受支持、未损坏 SQLite store 中的 RunState | 对已成功提交的节点、reservation、attempt、handle、lease、output 和 idempotency receipt 权威 |
| Codex task 或外部进程是否实际存在、启动、结束 | 对应外部执行系统，经冻结 Host binding 观察 | SQLite 只保存 GraphX 的绑定与观察记录，不能单独证明外部事实 |
| workspace 的实际字节 | workspace 文件系统或不可变 snapshot | WorkspaceRevision 是按冻结 policy 得到的 Host 观察值，不是文件系统本身 |

在受支持的本地持久化文件系统、未损坏数据库、正确 Adapter、冻结且受信 Host binding、以及外部执行满足声明 capability 的前提下，GraphX 可以机械保证：

- Pure Core 对同一 IR 与同一 validated RunState snapshot 给出相同决定；
- 单个 SQLite transaction 内的状态提交、约束与幂等 receipt 原子一致；
- GraphX 自己不会在同一 Run 中并行派发两个 external execution，也不会在同一 coordination domain 中并行派发同一 canonical workspace identity 的 mutation；
- 无法确认的外部副作用会阻塞后续 mutation，而不是被猜测为成功、失败或未开始。

GraphX 不能仅凭 SQLite 或 Schema 保证外部动作 exactly-once、恶意 Host 报告真实、其他进程不修改 workspace、不同 state store 之间全局互斥，或数据库损坏后自动恢复事实。需要这些保证时，Host 必须提供可验证的幂等 create/query、不可变 workspace snapshot 或独占锁、受控进程域和独立 attestation；能力不存在时 GraphX 只能检测、进入 `blocked`/`ambiguous`，或拒绝派发。

## 2. 初始范围

### 2.1 包含

- Python 3.12 本地进程中的边界 Schema 校验、Application 用例编排、immutable IR 和 Pure Core Executor；
- `agent`、`command`、`verifier`、`gate`、`terminal` 节点，MVP 的 `none | workspaceMutation` side-effect class，以及确定性串行调度；
- Codex Skill、短事务 MCP 协议，以及每个已绑定 AgentAttempt 对应的独立 Codex task；
- SQLite 控制面 system of record、幂等 transaction、mutation lease、恢复与 `ambiguous` 裁决；
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
- 对 workspace 之外的网络、账号或其他不可逆外部副作用提供事务、回滚或 exactly-once 保证；这类动作不属于 MVP 可安全自动 retry 的执行范围。

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
GraphX Python Service
    ├── Inbound Adapters
    │   ├── MCP
    │   └── CLI
    ├── Application
    │   ├── Application Service
    │   ├── Query Service
    │   ├── StateCommitter
    │   └── Store Ports
    ├── Pure Core
    │   ├── Config / immutable IR
    │   ├── Compiler / Graph Analyzer
    │   ├── Scheduler / Condition Evaluator
    │   └── Transition / Result Validation
    └── SQLite Adapter -> private SQLite
```

Codex App 是用户界面和 Agent Host。GraphX Python Service 是无 UI 的执行控制面，各类运行时 authority 仍按第 1.3 节划分；其中 `core/` 只包含确定性规则，`application/` 负责编排用例和事务，Service 内的 Adapter 连接 MCP、CLI 与 SQLite。`adapters/host/` 虽与 Service 代码位于同一 Python package，但在 Host 环境中独立运行，只通过 MCP 与 Service 通信。源码依赖只能指向内层；SQLite 的访问与隔离规则见第 3.4 节。

### 3.1 总控任务

用户在一个 Codex 总控任务中启动或恢复 GraphX。总控任务：

- 调用 GraphX MCP tools；
- 显示 Graph 和节点状态；
- 通过 GraphX Skill 请求 Host Adapter 为 Agent 节点创建或查询可见 Codex task；
- 等待节点 task 完成；
- 把结构化结果提交给 GraphX；
- 不绕过 GraphX 自行推进 Graph。

总控 task 负责用户交互和调用顺序；只有 Host Adapter 可以调用 Codex create/query/send API、执行 mechanical command 或采集 workspace/隔离 observation。总控 task 不能直接伪造 Host observation、execution disposition 或 NodeResult。

### 3.2 Agent 节点任务

每个 Agent execution 先创建 DispatchReservation；Host 据此创建一个不含语义工作内容的独立 bootstrap Codex task。bind 成功后，GraphX 才创建 AgentAttempt 与不可变 ExecutionHandle：

```text
GraphX · <run-id> · <node-id> · attempt <reserved-n>
```

bootstrap task 在 bind/activate 前只接收 reservation identity 与 binding token；激活后才接收当前节点的冻结 Task Contract。它可以使用 Codex 原生工具完成工作，但不能直接修改 GraphX RunState。

语义执行 retry 创建新的 reservation、attempt 和 Codex task。未激活的 reservation 不算 Agent attempt，但必须保留审计记录并受有界 dispatch/reconcile policy 约束；失败或孤立的 bootstrap task 也保留为审计记录。

### 3.3 机械节点与内部控制节点

`command` 和 `verifier` 不要求独立对话。Host Adapter 只执行 IR 已经声明的外部动作并返回结构化事实；它不能解释依赖、条件或完成语义。`gate` 和 `terminal` 不离开 GraphX Python Service，由 Condition Evaluator 根据不可变 IR 与权威 RunState 求值，再由 StateCommitter 提交状态。

MVP 中的 `gate` 是纯条件节点，不表示人工审批。若未来需要人工批准，必须增加显式 approval node、principal 与绑定 revision 的 ApprovalEvidence；在此之前不得宣称 GraphX 提供 human gate。

#### 3.3.1 判定节点的职责与确定性边界

`verifier`、`gate` 和 `terminal` 的 GraphX 判定语义都是确定的：给定相同的不可变 Workflow IR、已验证的权威 RunState 快照和所需的已验证外部输入，Pure Core 必须产生相同的判定。这里的确定性是 GraphX 对输入的判定确定性，不是对外部环境每次都返回相同观测值的承诺。

| 节点 | 事实或条件来源 | GraphX 中的确定性语义 | 控制效果 |
|---|---|---|---|
| `verifier` | 受信 Host 执行 Config 声明并在 IR 中冻结的 tagged check spec，提交结构化结果 | 外部检查可能因环境、时间或 flaky test 产生不同结果；但给定相同的已验证结果、IR 和 RunState，证据校验与状态转换必须相同 | 产生正式 VerificationEvidence，记录 Host 对 EvidenceSubjectRevision 的检查结果；不设置 WorkflowOutcome |
| `gate` | Pure Core 对已持久化输出和状态求值受限条件 AST | 不执行 I/O，不接收 Host NodeResult；相同 IR 和 RunState 必须得到相同的中间判定 | 表达 Config 声明的中间准入、分支或共享复合条件；不提交 Run 最终结果 |
| `terminal` | Pure Core 对已持久化输出、依赖和状态求值受限条件 AST | 不执行 I/O，不接收 Host NodeResult；相同 IR 和 RunState 必须得到相同的最终判定 | condition 为真时唯一可设置 Config 声明的 WorkflowOutcome；不产生新的外部事实 |

`verifier` 产生事实，`gate` 作出中间决策，`terminal` 提交最终裁决。Gate 不应只重复前置节点的成功状态或 Terminal 已能直接表达的最终条件；它只用于 Workflow Config 需要显式命名、审计或复用的中间控制判定。

### 3.4 状态访问与执行隔离

#### 3.4.1 状态数据库边界

Codex 总控任务、Agent task 和 Host Adapter 都是不可信的外部参与者，只能调用 GraphX 暴露的结构化 MCP 操作。MCP 不提供原始 SQL、数据库连接、数据库文件路径、任意表查询或通用状态写入操作。

逻辑 authority 按第 1.3 节分配，持久化细节见第 9 节，源码 import boundary 见第 10.4 节。这里只规定访问能力：Query Service 只获得 read-only Port；StateCommitter 获得受限的 CommitTransaction Port，并在同一 snapshot 中读取、调用 Pure Core、写入状态与 receipt。状态修改禁止先经 Query Service 读取再另开 transaction 提交。只有 Service `bootstrap.py` 可把私有数据库路径直接交给 SQLite Adapter；其他组件不得取得该路径或具体 Store。

#### 3.4.2 Host 执行隔离

SQLite 文件必须位于所有 Codex workspace 之外，并且不能挂载或暴露给总控任务、Agent task 或 Host Adapter 的执行环境。Host 启动 Run 时必须验证固定的执行隔离要求；无法保证状态目录隔离时，不得派发 Agent 节点。GraphX 不通过 prompt 中的行为要求声称实现数据库隔离。

GraphX Python Service 不实现通用 sandbox。文件系统隔离由 Host 提供，但“GraphX 私有状态目录对 Agent 不可见”是 Agent 执行的硬前置条件，而不是可降级选项。Host Adapter 只负责观察并报告环境事实；Inbound Adapter 校验报告，Pure Core 比较固定隔离规则，Application StateCommitter 提交 `blocked` 或允许派发。Run 必须冻结 Host identity、workspace identity、隔离模式和对应的规范化 snapshot/hash，恢复时重新验证；首次 start 前不一致走 `validated -> blocked`，运行中不一致走 `running -> blocked`，不能继续派发。

Host Adapter 对 Graph 控制和状态提交没有信任权限，但初始本地版本必须信任已冻结 Host binding 对外部执行与 workspace 的测量。GraphX 会校验报告的 Schema、身份、revision 和 evidence 绑定，却不能仅靠 Schema 识别恶意 Host 的虚假测量；因此所有“检查已执行”“revision 已观测”的保证都以受信 Host binding 为前提。不信任 Host 测量时需要独立 attestation，这不在 MVP 范围内。私有状态目录隔离必须由进程权限和挂载边界实际强制，不能依赖 Host 自报。

`HostId` 必须来自已认证 transport principal，不能是调用方可任意填写的字符串。Inbound MCP transport 必须使用受限本地 socket/pipe ACL、进程间 capability、mTLS 或等价机制认证 Host，并在进入 StateCommitter 前与 Run 的 frozen Host binding 比较。`task_binding_token` 只用于 bootstrap task identity 对账，不授予 Host 控制面写权限。部署环境若不能认证 Host，只能把 Host 真实性列为显式部署假设，不能报告为已机械强制。

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
        "sideEffect": "none",
        "dependsOn": ["develop-material-system"],
        "settlesMutation": "develop-material-system",
        "settlementRecovery": {"maxAttempts": 2},
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
      },
      {
        "id": "verification-failed",
        "type": "terminal",
        "dependsOn": ["verify-material-system"],
        "condition": {
          "eq": [
            {"from": "verify-material-system.evidence.status"},
            {"literal": "failed"}
          ]
        },
        "outcome": "failure"
      }
    ]
  }
}
```

示例不是内置流程。GraphX 不包含 `develop-material-system` 的业务逻辑。

Agent Node 的 `task` 保持非空、有界的自由文本。Pure Core 不从自然语言中推断依赖、分支、重试或完成条件；影响控制流的要求必须由结构化 `outputs`、显式节点、受限条件和 terminal 表达。Agent 的自然语言完成声明只能作为诊断，不能成为未经独立检查的成功依据。

Config 中的控制字段必须结构化并区分两类条件：所有节点可选的 `when` 决定节点是否适用；`gate` 和 `terminal` 自己的 `condition` 决定该控制节点是否通过。`dependsOn` 是 success dependency：只有依赖节点 `succeeded` 才满足；依赖节点 `skipped` 时下游按 skip propagation 进入 `skipped`，依赖节点耗尽 retry 后 `failed` 时下游不运行。Compiler 必须把条件中的状态或输出引用解析为显式依赖，禁止通过自然语言或运行时猜测隐式顺序。

`sideEffect` 对 `agent`、`command` 和 `verifier` 是必填字段；`gate` 与 `terminal` 是内部节点，IR 将其固定为 `none`，Config 若为它们提供该字段则拒绝。不存在依赖默认值猜测副作用类别的路径。

`settlesMutation` 是 verifier-only 的可选 NodeId 字段。每个 workspaceMutation node 最多绑定一个 settlement verifier。该 verifier 必须为 `sideEffect = none`、不可带 `when`，并在 `dependsOn` 中直接包含目标 mutation；其他 success dependency 必须已经是该 mutation 的祖先，因此目标成功后 verifier 必然可进入 ready。它把 EvidenceSubjectRevision 绑定到目标的 SettledOutputRevision，且不能越过另一个 mutation。任何 dependency closure 包含该 mutation 的 terminal，其 closure 也必须包含 settlement verifier；除此之外，StateCommitter 仍须用“存在 pending-settlement lease 时禁止提交任何 Run terminal status”的运行时规则兜底。

每个 settlement verifier 还必须显式声明有界 `settlementRecovery.maxAttempts`，其正整数上限由产品 Schema 固定；Compiler 将 policy 与 verifier check 一并冻结进 IR digest。`settlementRecovery` 只允许出现在 verifier node 上，且必须与 `settlesMutation` 同时存在；任一字段单独出现都拒绝。它只授权在正常 verifier retry 耗尽或取消结算时重复执行完全相同的 frozen check，不允许用户替换 spec、revision、Host binding 或计数。每个 pending-settlement lease 的 recovery sequence 从 1 单调递增，数据库以 `(lease_id, recovery_sequence)` 唯一约束并拒绝超过上限；相同 idempotency request 只返回原 execution。上限耗尽后 lease 与 Run 保持 `blocked`，GraphX 明确不保证该 Run 能自动恢复可用性。

目标 mutation 成功后可释放 Run active slot，但继续持有 lease。StateCommitter 只在 settlement verifier 可靠执行并提交合法 evidence 的 transaction 中释放该 lease。evidence 的 `passed | failed` 都表示结算事实已经获得，业务分支由后续 terminal 决定；verifier 自身执行失败或结果未知时 lease 保留。没有 CancellationIntent 且 normal retry 尚可用时，可以按 Config retry policy 重试；retry 耗尽后只能使用第 7.3 节的 GraphX-issued recovery operation。CancellationIntent 已存在时不得创建新的普通 verifier retry，只能等待已在运行的 execution 安全完成，或使用该 recovery operation。期间 Run 保持非 terminal 的 `blocked` 或 `ambiguous`，不得通过直接覆盖状态或无证据裁决绕过 verifier。

### 4.2 数据层次

```text
Untrusted JSON
    -> Inbound Adapter Schema Validation
Validated WorkflowConfig
    -> Pure Core Semantic Compilation
Immutable WorkflowIR
    + Validated RunState Snapshot
        <- Application
        <- SQLite Adapter Row Validation
        <- SQLite Rows
    -> Pure Core Deterministic Scheduling Decision
    -> Application / StateCommitter
```

三类顶层数据必须分开；`RunStatus`、`NodeState`、DispatchReservation、attempt、output 和 lease 都是 RunState aggregate 的组成部分，而不是另一份权威状态：

| 类型 | 含义 | 可变性 |
|---|---|---|
| `WorkflowConfig` | 通过 Schema 的外部配置 | 运行前输入 |
| `WorkflowIR` | 引用和默认值已解析的内部执行定义 | 运行期间不可变 |
| `RunState` | 一次具体运行的 aggregate snapshot，包含 `RunStatus`、节点、reservation、attempt、output、lease、可选 CancellationIntent 和可选 WorkflowOutcome | 仅由 StateCommitter 事务化更新 |

### 4.3 IR 包含

- 稳定 workflow/node ID；
- 节点类型和 side-effect class；
- 已解析依赖和输出引用；
- 输入输出类型；
- verifier 的 tagged check spec、稳定 check ID 和规范化 check hash；
- 可选 settlement verifier 与其被结算 mutation node 的显式绑定；
- settlement verifier 的有界 recovery policy；
- Run 创建前编译进 IR 的 RevisionPolicy；
- 受限条件 AST；
- 有界 retry policy；
- 稳定调度顺序；
- terminal 定义；
- 内容哈希和 Schema 版本。

MVP 的 external-node `sideEffect` 只有 `none` 与 `workspaceMutation`。`none` 表示 Workflow 作者声明节点不会改变权威 workspace，GraphX 通过 input/output revision 相等进行有限验证；它不证明节点没有网络或其他 workspace 外部副作用。GraphX 不从 `task` 文本或 command argv 推断 side effect。MVP 不提供 workspace 外不可逆副作用的声明、对账或安全 retry capability：Compiler 只能拒绝显式请求该能力的 Config，不能识别被 Workflow 作者错误标为 `none` 的 command/task；误声明超出自动化保证边界。

## 5. 运行时校验

静态类型不能替代运行时校验。以下数据一律视为不可信：

- Workflow JSON；
- MCP 请求；
- Codex NodeResult；
- SQLite row；
- 恢复时读取的状态；
- WorkspaceRevision observation 和文件路径。

校验分为四层，并且每层有固定所有者：

### 5.1 Schema 校验

Inbound Adapter 负责 Workflow、MCP 和 CLI 的 transport Schema；SQLite Adapter 的 row codec 负责持久化 row 的 Schema。任何原始对象在转换为严格领域模型前都不能进入 Application 或 Pure Core。

- 版本受支持；
- 必填字段存在；
- 未知字段被拒绝；
- 枚举、整数和字符串格式正确；
- retry 和 timeout 有界；
- `settlementRecovery` 与 verifier-only `settlesMutation` 同时存在，policy 正数且不超过产品上限；任一单独出现均拒绝；
- verifier check spec 的 kind-specific 字段、命令参数和成功条件合法；
- NodeResult 的 wire version、tag、字段形状和大小限制正确。

### 5.2 Graph 语义校验

Pure Core 负责 Workflow 编译后的 Graph 与条件语义校验，不读取文件、MCP 或数据库。

- node ID 唯一；
- 依赖和输出引用存在；
- 类型兼容；
- Graph 无环；
- 至少一个 success terminal 结构可达，所有 terminal 的 outcome、依赖和条件引用合法；
- 条件与输出引用形成显式依赖，不能读取未来或被 skip 后不存在的输出；
- settlement verifier 满足第 4.1 节的唯一性、side-effect、无 `when`、直接依赖、ancestor、无跨 mutation、EvidenceSubjectRevision 与有界 recovery policy 约束；所有 dependency closure 包含目标 mutation 的 terminal 也包含该 verifier；
- 条件只使用受支持操作；
- side-effect class 明确；
- mutation 规则可执行。

### 5.3 状态转换校验

Pure Core 根据不可变 IR 和已验证状态快照返回 TransitionDecision；Application StateCommitter 在同一事务快照中重新验证并提交，Pure Core 本身不执行 I/O。

- 当前状态允许目标转换；
- RunState aggregate、RunStatus 与 WorkflowOutcome 的组合满足第 6.2 节不变量；
- AgentNodeResult 的 reservation/AgentAttempt/ExecutionHandle/TaskActivation identity，或 MechanicalNodeResult 的 reservation/MechanicalAttempt/MechanicalExecutionHandle/operation identity 全部匹配；DispatchReservation 不能单独接收 NodeResult；
- NodeResult 属于当前 active external execution；对 `gate` 或 `terminal` 的任何外部结果一律拒绝；
- NodeResult outputs 与 immutable IR 声明的节点输出 Schema 匹配；
- retry 没有超过上限；
- timeout 只触发对账，不能作为“外部执行未发生”或 lease 可释放的证明；
- ConditionDecision 只能由 Pure Core 根据 immutable IR 和 validated RunState snapshot 生成；
- terminal 只有在 ConditionDecision 为真时才能提交其声明的 WorkflowOutcome；普通节点失败和 terminal 条件为假不得写入 outcome；
- `graphx_next` 在同一 transaction 中验证 active slot、稳定排序决定、DispatchReservation、可选 mutation lease 与 NodeState 更新。

### 5.4 数据库约束

SQLite Adapter 负责下列物理约束和事务原子性，但不能自行发明状态转换：

- 主键和外键；
- 每个 node 的 DispatchReservation ID、AgentAttempt/MechanicalAttempt 编号和 execution ID 唯一；
- request/result idempotency identity 唯一，并保存 canonical request digest 与原始 canonical response；
- 每个 Run 至多一个 active external execution slot；
- active slot 使用 tagged owner identity 指向 DispatchReservation、AgentAttempt、MechanicalAttempt 或 SettlementCheckExecution，不能出现空 owner 或两个 owner；
- 在一个 coordination domain 内，每个 canonical workspace identity 至多一个 mutation lease；
- Run terminal status 不得关联 active slot、unresolved external operation 或 mutation lease；
- 每个 AgentAttempt 恰有一个 Codex ExecutionHandle，每个 MechanicalAttempt 恰有一个 MechanicalExecutionHandle，且 `(host_id, thread_id)` 在所有 Codex handle 中唯一；
- 每个 SettlementCheckExecution 不可变地引用目标 lease、frozen check/policy 和一个 ExternalOperation；创建时原子取得 active slot，非 terminal 期间恰好持有该 slot，terminal disposition 提交时按第 7.3 节释放；`(lease_id, recovery_sequence)` 唯一且不超过 IR 上限；
- AgentAttempt 与 ExecutionHandle 在 bind transaction 中一起创建；thread ID 非空且不可变；每个 AgentAttempt 至多一个 TaskActivation；未绑定的 `dispatching` 状态只持有 DispatchReservation；
- 所有状态变化在单个事务中提交。

### 5.5 验证权威和保证边界

GraphX 必须区分“候选产物已经生成”和“Workflow 按 Config 验收了该产物”。验证层级由 Workflow Config 显式声明：

| 层级 | 作用 | 权威性 |
|---|---|---|
| Agent task-local 自检 | 尽早发现缺陷并降低返工 | Agent 提供的证据；不能冒充已声明的 Host Verifier |
| Host 执行的 `command` / `verifier` | 执行 IR 中固定的检查并采集退出码和输出 | 在受信 Host binding 与声明 execution capability 前提下，对“Host 在绑定 revision 上执行了该检查”提供机械记录 |
| 独立 Review Agent | 检查需求符合性和代码质量 | 独立但仍是概率性的语义判断 |
| Terminal | 汇总 Graph 中声明的必要条件 | 只有所有依赖和条件满足后才能提交 Run 成功 |

正式 Verifier 的 tagged check spec 来自 Workflow Config；Compiler 必须校验其 kind-specific 字段，并在不可变 Workflow IR 中保存稳定 check ID 和规范化 check hash，不能由被验证 Agent 在结果中临时指定。VerificationEvidence 必须绑定 run、node、execution identity、EvidenceSubjectRevision、check ID/hash 和结构化结果；stale revision、错误身份、check hash 不匹配或仅有自然语言成功声明都必须拒绝。

在第 1.3 节的信任前提下，GraphX 只保证声明的验证步骤被正确调度、由绑定 Host 报告为执行、绑定并记录，不证明 Host 不会伪造事实，也不证明检查本身语义完备。

## 6. 节点和状态

### 6.1 NodeState

```text
pending
ready
dispatching
running
verifying
succeeded
failed
skipped
blocked
ambiguous
cancelled
```

完整合法转换如下；未列出的转换一律拒绝：

| From | To | Guard / effect |
|---|---|---|
| `pending` | `ready` | 所有 success dependency 均为 `succeeded`，且 common `when` 缺省或为真 |
| `pending` | `skipped` | common `when` 为假，或任一 success dependency 已是 `skipped`、`cancelled` 或 retry 耗尽的 `failed`；记录结构化原因并传播不可执行分支 |
| `pending` | `cancelled` | Run 取消，且节点尚未派发 |
| `ready` | `dispatching` | 外部执行节点；原子创建 DispatchReservation、dispatch intent 和 Run active slot，mutation 同时获取 lease；Agent dispatch 还创建 `taskCreate` ExternalOperation |
| `ready` | `verifying` | StateCommitter 在事务中调用 Pure Core 求值 `gate` 或 `terminal`，不创建 Host execution 或占用 external slot；terminal 还要求不存在 active external operation 或 pending-settlement mutation lease |
| `ready` | `blocked` | 固定执行隔离或必需外部前置条件在派发前不满足，不创建 reservation、attempt、slot 或 lease |
| `ready` | `cancelled` | Run 取消，且没有外部执行 |
| `dispatching` | `running` | 已绑定 AgentAttempt 的 TaskActivation，或 MechanicalAttempt/MechanicalExecutionHandle 的 activation 已提交；外部动作只可在提交后按 operation ID 启动 |
| `dispatching` | `ready` | 已证明外部对象未创建/未启动，尚未创建 AgentAttempt，且 bounded dispatch policy 允许再次 reservation；原子释放旧 slot/lease |
| `dispatching` | `blocked` | 已证明外部对象未创建/未启动，但 dispatch capability 不可用或 bounded dispatch policy 耗尽；原子释放 slot/lease |
| `dispatching` | `failed` | AgentAttempt 已成功 bind，但 activation 明确失败；bind 前 bootstrap create/query 失败仍按 reservation 走 `ready/blocked/ambiguous`；释放 active slot，并按第 7.3 节处理 lease |
| `dispatching` | `ambiguous` | 无法唯一确认 task identity、Contract delivery 或外部执行是否开始；active slot 与 mutation lease 保留 |
| `dispatching` | `cancelled` | 已证明执行没有开始且 Run 取消；在同一 transaction 释放 active slot，并按第 7.3 节处理 lease |
| `running` | `verifying` | Application 收到结果、失败、blocked 或取消证据，交由 Pure Core 校验 |
| `running` | `ambiguous` | Host 丢失且无法确定 execution 或 mutation 结果；active slot 与 mutation lease 保留 |
| `verifying` | `succeeded` | 外部节点的 NodeResult 通过适用于该 tag 的身份、Schema、输出、revision 和 evidence 校验并确认 execution terminal；mutation 记录 settled output，并按第 7.3 节释放或继续保留 lease；或内部 `gate`/`terminal` 的 ConditionDecision 为真 |
| `verifying` | `skipped` | 仅限内部 `gate`/`terminal` 的 ConditionDecision 为假；不接受 Host 提交此决定 |
| `verifying` | `failed` | 外部执行明确失败或结果不满足契约；external node 在同一 transaction 释放 active slot，并按第 7.3 节处理 lease |
| `verifying` | `blocked` | 已验证的外部前置条件缺失，且 external execution 已有 terminal disposition |
| `verifying` | `ambiguous` | mutation 结果或 workspace revision 无法对账 |
| `verifying` | `cancelled` | 取消已经确认、external execution 已有 terminal disposition，且 mutation 已证明未发生或已完成对账 |
| `failed` | `ready` | retry policy 允许；下一次派发创建新 reservation，下一次 bind 才创建新 AgentAttempt |
| `blocked` | `ready` | 显式 resume，并重新验证依赖、隔离和外部前置条件 |
| `blocked` | `cancelled` | 用户取消，且该节点没有未裁决的 external operation 或 mutation |
| `ambiguous` | `dispatching` | 找回唯一 bootstrap task，但尚未 activate |
| `ambiguous` | `running` | 找回并确认仍在执行的 attempt |
| `ambiguous` | `verifying` | 找回结果或用户提供裁决证据，必须继续正常结果校验 |
| `ambiguous` | `failed` | 已证明执行未开始或失败；按第 7.3 节处理 lease |
| `ambiguous` | `cancelled` | 用户裁决取消，且按第 7.3 节完成 mutation 对账 |

对于 external node，`verifying -> succeeded/failed/blocked/cancelled` 只有在 execution terminal disposition 已验证时才合法，并且必须在同一 transaction 释放 Run active slot；mutation lease 是否同时释放由第 7.3 节单独决定。`ambiguous` 始终保留 active slot，mutation 还保留 lease。内部 gate/terminal 从不持有 external slot。

`ambiguous -> dispatching/running/verifying` 继续持有原 active slot；`ambiguous -> failed/cancelled` 只有完成外部 disposition 与 mutation 对账后才释放 slot，并按第 7.3 节释放或保留 lease。

Terminal 不能取消、skip 或绕过持有 pending-settlement lease 所需的 verifier。若该 verifier 暂时不可执行或 retry 已耗尽，Run 进入 `blocked`；若其 operation/result 未知则进入 `ambiguous`。只有 lease 按第 7.3 节结算释放后，terminal 才是合法的内部调度候选。

#### 6.1.1 依赖、内部条件与 timeout

`dependsOn` 具有严格成功语义：只有依赖节点为 `succeeded`，其输出才可消费。`skipped` 不等于成功，不得提供隐式 `null` 或默认输出；`blocked` 或 `ambiguous` 依赖使下游保持 `pending`。Compiler 必须保证条件或输入引用的节点在 Graph 中形成显式、无环的先行关系。

`gate` 和 `terminal` 不接收外部 NodeResult。Pure Core 只基于 immutable IR 和 validated RunState snapshot 返回内部 tagged decision：

```text
ConditionDecision =
    satisfied(condition_hash, referenced_values_hash)
  | not_satisfied(condition_hash, referenced_values_hash)
```

StateCommitter 保存其审计摘要并提交转换。decision 为真时 gate/terminal node 为 `succeeded`；为假时为 `skipped`。terminal 为真时还必须在同一 transaction 中设置其 IR 声明的 WorkflowOutcome 和对应 RunStatus；Host 无权构造或提交 ConditionDecision。

可识别的 Store、row、IR digest 或引用完整性损坏不是 NodeState transition。Service 必须先进入 store-recovery fail-closed 模式，禁止使用该 aggregate 推进状态、释放 slot/lease、写 operational failure 或 retry；只能从验证备份恢复，再把无法与外部事实唯一对账的 operation 标为 `ambiguous`。

`succeeded`、`skipped` 和 `cancelled` 没有后续转换。耗尽 retry 的 `failed` 也不再转回 `ready`。Verifier 的检查可靠执行并产生合法 `VerificationEvidence(status = passed | failed)` 时，verifier node 本身为 `succeeded`；证据为 `failed` 是业务验证结果，不等于执行器失败，后续 terminal 可以据此选择声明的 failure outcome。只有检查未可靠执行或没有产生合法 evidence 时，verifier node 才为 `failed`。

timeout 只是外部观察事件，不证明执行已停止。只读 external execution 在 Host 确认终止后可以进入 `verifying -> failed/cancelled`；任何可能已发生且无法对账的 mutation 必须进入 `ambiguous`。`core/runtime/transitions.py` 只返回 TransitionDecision；所有转换只由 `application/state_committer.py` 提交。Agent task、Host Adapter 和 Scheduler 只能提出结构化请求或纯决定。

### 6.2 RunState、RunStatus 与 WorkflowOutcome

`RunState` 是第 4.2 节定义的 aggregate。`RunStatus` 是其中的生命周期枚举：

```text
validated
running
succeeded
failed
blocked
ambiguous
cancelled
```

`WorkflowOutcome` 在 MVP 中为 `success | failure`，初始值为 `None`。只有 Config 中 outcome 对应的 terminal node 条件为真时，StateCommitter 才能在同一 transaction 中写入该 outcome；operational failure 和 cancel 保持 `WorkflowOutcome = None`。

取消请求先持久化为不可撤销的 `CancellationIntent`，不是立即伪装成 `RunStatus.cancelled`；MVP 不提供 withdraw-cancel。若没有未结算外部动作，StateCommitter 可在同一 transaction 完成节点清理并提交 `cancelled`；若仍有 active/unknown execution 或 mutation lease，Run 保持或进入 `blocked`/`ambiguous`，只允许对账和第 7.3 节的结算恢复，完成后再提交 terminal cancel。存在 CancellationIntent 时，`graphx_next` 与 `graphx_resume_run` 不得派发普通节点或把 Run 恢复为 `running`。

RunStatus 的完整合法转换如下：

| From | To | Guard / effect |
|---|---|---|
| `validated` | `running` | 显式 start，Host binding 与恢复前置检查通过 |
| `validated` | `blocked` | 显式 start 时 Host binding、状态目录隔离或必需前置检查不满足；不创建 reservation、attempt 或 lease |
| `validated` | `cancelled` | Run 在首次调度前取消 |
| `running` | `succeeded` | success terminal node 条件为真，且没有 active/unresolved external operation 或 mutation lease；同一 transaction 写入 `WorkflowOutcome.success` |
| `running` | `failed` | 没有 active/unresolved external operation 或 mutation lease，且 failure terminal 条件为真时写入 `WorkflowOutcome.failure`；或 mandatory operational failure 使所有 terminal 不可达且 retry 已耗尽，此时 outcome 保持 `None` 并记录 failure reason |
| `running` | `blocked` | 没有可调度节点，且至少一个必要节点为 `blocked`，或 pending-settlement lease 因 verifier 暂时不可执行/retry 耗尽而不能释放 |
| `running` | `ambiguous` | 存在未裁决的 reservation、attempt 或其他 ExternalOperation |
| `running` | `cancelled` | 取消已提交，所有 external operation 已完成安全对账，且所有 mutation lease 已结算释放 |
| `blocked` | `running` | 不存在 CancellationIntent，显式 resume 且所有阻塞前置条件重新验证通过 |
| `blocked` | `ambiguous` | 恢复或对账发现未裁决 external operation |
| `blocked` | `failed` | 已证明所有 terminal 不可达且 retry 已耗尽，且不存在 unresolved external operation 或 mutation lease；outcome 保持 `None` |
| `blocked` | `cancelled` | 用户取消，且所有 external operation 与 mutation lease 已完成安全结算 |
| `ambiguous` | `running` | 不存在 CancellationIntent，所有 ambiguous external execution 已裁决且 Workflow 仍可继续 |
| `ambiguous` | `blocked` | 未知 external operation 已对账为 terminal，但仍缺少 settlement evidence 或其他可修复前置条件 |
| `ambiguous` | `failed` | 所有 external operation 与 mutation lease 已安全结算，且裁决后 terminal 不可达、retry 已耗尽；outcome 保持 `None` |
| `ambiguous` | `cancelled` | 所有 external operation 与 mutation lease 已安全结算后用户取消 |

只有 Config 成功编译并以 IR digest 持久化 immutable snapshot 后才创建初始 `RunStatus.validated` 的 Run；非法 Workflow 不产生 RunState。`succeeded`、`failed` 和 `cancelled` 是 Run terminal status，没有后续转换，三者都禁止携带 active slot、unresolved external operation 或 mutation lease。Run cancel 时，StateCommitter 只在安全结算完成后，把尚未执行且不负责 pending settlement 的 `pending`、`ready`、`blocked` 节点转为 `cancelled`；已完成节点保留原状态。Pure Core 只决定合法转换，所有 RunState 更新只由 Application StateCommitter 提交。

Terminal node 自身的 `succeeded` 表示其条件已通过并成功提交声明的 outcome；failure terminal 因此可以是 NodeState `succeeded`，同时使 RunStatus 为 `failed`、WorkflowOutcome 为 `failure`。条件为假的 terminal 进入 `skipped` 并允许其他 terminal 继续竞争；若所有 terminal 最终都不可达，Run 进入 operational `failed`，但不产生 WorkflowOutcome。

合法组合必须满足：`RunStatus.succeeded` 当且仅当 `WorkflowOutcome.success`；由 failure terminal 提交的 `RunStatus.failed` 携带 `WorkflowOutcome.failure`；operational `failed`、`validated`、`running`、`blocked`、`ambiguous` 和 `cancelled` 的 outcome 均为 `None`。任何 Run terminal status 与 active slot、unresolved external operation 或 mutation lease 的组合也非法。SQLite row codec 和 Pure Core 都必须拒绝其他组合。

### 6.3 确定性调度

初始版本对每个 Run 同时只允许一个 active external execution。Compiler 将 node ID 限制为规范化语法，Scheduler 按其 UTF-8 byte order 选择第一个合法 ready node。若任一外部节点处于 `dispatching`、`running` 或正在校验外部结果的 `verifying`，或存在 active SettlementCheckExecution，`graphx_next` 返回 `AwaitingActiveExecution`，不能派发另一个节点。存在 CancellationIntent 时返回 `RunNotRunnable`，只允许对账、settlement recovery 和最终 cancel。

```text
same WorkflowIR + same validated RunState snapshot
    -> same SchedulingDecision
```

Host isolation、workspace revision、时间或外部 operation 查询结果必须先成为版本化、已校验的显式输入，再由 Pure Core 产生 TransitionDecision；它们不属于上述纯 Scheduler 公式。StateCommitter 必须在同一 transaction 中验证 active slot 并提交 reservation，SQLite 用 per-Run 唯一约束抵御并发 `graphx_next`。

这避免把并发顺序、共享工作区和多 Agent 竞态引入 MVP。串行 Scheduler 是吞吐策略，不能替代第 7 节由 Pure Core 规则、StateCommitter 事务编排和 SQLite 约束共同保证的持久化 mutation safety。

## 7. Mutation 串行语义

### 7.1 全局规则

任何 `sideEffect = workspaceMutation` 的节点都必须获取 workspace-scoped mutation lease。规则适用于 Agent、Command 和任何未来节点类型。该保证以一个 GraphX coordination domain（共享同一 SQLite store）及经 Host binding 规范化的 canonical workspace identity 为边界；不同 state store、外部进程或未经同一 identity 归一化的路径不在此 lease 的互斥范围内。

```text
workspace
    -> zero or one mutation lease
       owner = reservation | attempt | pending-settlement mutation
```

### 7.2 获取 lease

StateCommitter 通过 `CommitTransaction` Port 发起一次原子提交，SQLite Adapter 必须用单个 SQLite transaction 完成：

1. 验证 node 为 `ready`，且 Run 没有 active external execution；
2. 验证 coordination domain 中该 canonical workspace identity 没有 lease；
3. 创建不可变 DispatchReservation 和 dispatch intent；AgentAttempt 此时尚不存在；
4. 获取以 reservation 为 owner 的 lease 和 Run active slot；
5. 将 node 转换为 `dispatching`；
6. 提交 transaction。

Host Adapter 只有在该事务成功后才能创建 Codex task 或执行 mutation。

Agent bind 成功时，StateCommitter 在同一 transaction 中创建 AgentAttempt 与 ExecutionHandle、消费 reservation，并把 active slot owner 以及适用的 lease owner 从 reservation 原子替换为 attempt；mechanical activation 对 active slot 执行等价转换，且仅在 node 自身为 mutation 时转换其 lease owner。mutation 输出结算但 settlement verifier 尚未完成时，lease owner 原子转为 settled mutation record。lease 在任何时刻都不得没有 owner；non-mutation settlement verifier 不接管目标 mutation 的 lease。

### 7.3 释放 lease

mutation lease 不是按时间失效的锁，而是未结算外部副作用的持久化排他权。mutation node 可以在候选输出已可靠结算后转为 `succeeded` 并释放 Run active slot，同时因 Config 声明的后续 settlement verifier 尚未完成而继续持有 workspace lease；这样 read-only verifier 可以运行，但任何后续 mutation 仍被阻止。只有 StateCommitter 在同一 transaction 中确认下列条件后才能释放 lease：

1. lease owner 对应的 external operation 已有可验证 disposition：`not_created`、`not_started`、`succeeded`、`failed` 或 `cancelled`；
2. 对已创建或启动的 execution，Host 已确认 terminal，且声明 capability 所覆盖的子进程/后台写入已终止或被受控执行域收割；对 `not_created`/`not_started`，provider 必须给出强一致的不存在或不可再启动证明，等价作为 terminal disposition；
3. 已按冻结 revision policy 完成 input/output revision 对账；声明未发生 mutation 时 output 必须等于 input，已发生 mutation 时必须保存 settled output revision；
4. mutation node 已 `succeeded` 且 Config 声明结算 verifier 时，其正常 evidence 或下述等价 recovery evidence 已绑定当前 SettlementTargetRevision；mutation node 为 `failed`/`cancelled` 时仍须满足 operation quiescence 与 revision 对账，但不要求执行只对成功候选生效的 settlement verifier；
5. disposition、revision/evidence、Node/RunState、active slot 与 lease release 在同一 transaction 提交。

缺少 terminal/quiescence capability 不是对上述条件的豁免，而是条件未满足：StateCommitter 必须保留 active slot 与 mutation lease，并保持或转为 `ambiguous`。用户裁决必须提交结构化 `MutationResolution`，绑定 run、node、reservation/attempt、canonical workspace identity、当前 observed revision、decision 和 rationale。`accepted_current_workspace` 只表示用户明确接受当前 revision 作为后续基线：StateCommitter 保留原 SettledOutputRevision，并另存新的 SettlementTargetRevision；它不证明历史上是谁造成了变化，也不能豁免 execution terminal、受控后代收割或未满足的 settlement evidence。证据不足时保持 `ambiguous` 和 lease。进程重启、timeout、task 消失或 Agent 自报完成本身都不能释放 lease。

若 settlement verifier 的执行 retry 耗尽或 Run 正在取消，`graphx_resolve_mutation` 可用两次短事务完成恢复：第一次以 action `requestSettlementCheck` 验证 Run 没有 active execution 和 IR recovery 次数尚未耗尽，校验当前 ExecutionInputRevision/目标 snapshot 与待验 SettlementTargetRevision 一致，原子创建第 8.3 节的 SettlementCheckExecution、取得 Run active slot，并创建 GraphX-issued `settlementCheck` ExternalOperation；其 contract 冻结原 verifier 的 check ID/hash/spec、目标 revision、Host binding、sequence 与 operation ID。受认证 Host 按 operation ID 执行/查询后，第二次提交带 terminal disposition 的 `MutationResolution.attachSettlementEvidence`。该 evidence 必须通过与正常 verifier 完全相同的 Schema、execution identity、input/output relation、check hash 和 EvidenceSubjectRevision 校验，才算满足条件 4；它不把原 verifier node 改为成功、不写 WorkflowOutcome，也不豁免条件 1–3。terminal recovery operation 总是释放 active slot：合法等价 evidence 同时结算 lease；明确失败或非法 evidence 保留 lease 并使 Run 保持/进入 `blocked`；启动或结果未知时保留 slot 与 lease 并进入 `ambiguous`。这样提供的是 Config 授权、有界的等价证据路径，不是人工跳过验证。

### 7.4 权威 workspace revision 与派生数据

workspace revision 只描述 Workflow 声明的权威项目内容，不能把缓存、索引、日志或其他派生元数据变化当成源码 mutation。必须区分：

| 类型 | 创建时机与归属 | 用途 |
|---|---|---|
| `RevisionPolicy` | Config 编译进 immutable IR，并进入 IR digest | 固定权威路径、派生排除、provider/version 与规范化算法 |
| `ExecutionInputRevision` | 任何 external execution 激活/创建前由 Host 观察并在 transaction 中绑定 AgentAttempt、MechanicalAttempt 或 SettlementCheckExecution | 证明 frozen execution contract 面向哪个输入观察值 |
| `SettledOutputRevision` | execution terminal 且工作区按 Host capability 静止后观察 | NodeResult 结算、后续节点基线与 mutation lease release |
| `SettlementTargetRevision` | 初始等于 mutation 的 SettledOutputRevision；仅 `accepted_current_workspace` 可另存新值，原值不可覆盖 | 指定 pending-settlement lease 当前必须由 evidence 检查的 revision |
| `EvidenceSubjectRevision` | Verifier evidence 生成时绑定 | 明确 evidence 检查的是哪个 SettlementTargetRevision，而不是未绑定的“当前目录” |

MVP 的 revision relation 固定为：`sideEffect = none` 必须满足 settled output 等于 input；`workspaceMutation` 允许相等或改变，但必须保存实际 settled output。MVP 不增加可配置的 output-revision DSL。正常 Verifier evidence 的 subject revision 等于被验证节点的 settled output revision；若发生显式 `accepted_current_workspace` 裁决，recovery evidence 改为绑定另存的 SettlementTargetRevision，同时保留原 revision 与裁决审计。两者都要记录 verifier 自身执行时的 workspace observation。任何 policy hash、provider version、identity 或 revision relation 不匹配都拒绝或进入 `ambiguous`，不能自动改绑到较新的 workspace。

Pure Core 只比较 policy 与已校验 revision value，不访问文件系统。`adapters/host/workspace.py` 负责观察 workspace，并通过版本化 MCP Contract 返回 `{policy_digest, provider_version, canonical_tree_digest}`；它不得依赖目录时间或无差别哈希，必须覆盖 tracked 文件的修改和删除及 policy 声明的权威 untracked 新文件，并排除明确的派生路径。若 Host 不能以不可变 snapshot、workspace lock 或等价方式消除测量与执行之间的 TOCTOU，GraphX 只能记录“Host 在某时刻观察到该 revision”，不能声称外部动作一定在该不可变快照上执行。GraphX 不理解具体派生工具；需要强一致性刷新时，由 Workflow Config 使用普通 Command Node 表达。

## 8. Codex task 映射

### 8.1 DispatchReservation、AgentAttempt 与 Codex ExecutionHandle

Agent 派发必须区分尚未确认外部 task identity 的 DispatchReservation 与已经绑定 task 的 AgentAttempt：

```python
@dataclass(frozen=True, slots=True)
class DispatchReservation:
    reservation_id: DispatchReservationId
    run_id: RunId
    node_id: NodeId
    reserved_attempt_number: int
    task_binding_token: TaskBindingToken
    request_digest: RequestDigest
```

DispatchReservation 是 `graphx_next` transaction 创建的派发意图，不是 AgentAttempt，不能接收 NodeResult，也不计入语义 retry attempt。它受独立、有界的 operational dispatch/reconcile policy 约束：policy ID/hash 冻结进 immutable RunHostBinding，reservation/reconcile 计数只在 RunState 中由 StateCommitter 事务化递增；二者共同作为 Pure Core 输入，使相同 snapshot 的决定保持确定。`task_binding_token` 必须具有足够熵、全局唯一，并进入外部 task 的可查询且不可变 metadata 或 bootstrap payload。

```python
@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    reservation_id: DispatchReservationId
    run_id: RunId
    node_id: NodeId
    attempt_id: AttemptId
    task_binding_token: TaskBindingToken
    host_kind: HostKind
    thread_id: ThreadId
    host_id: HostId
    workspace_id: WorkspaceId
    created_at: datetime
```

```python
@dataclass(frozen=True, slots=True)
class TaskActivation:
    activation_id: ActivationId
    attempt_id: AttemptId
    input_revision: ExecutionInputRevision
    contract_hash: ContractHash
    delivery_operation_id: ExternalOperationId
    activated_at: datetime
```

`host_kind` 在初始版本中固定为 `HostKind.CODEX`。ExecutionHandle 与 AgentAttempt 只在 bind 成功的同一 transaction 中创建，因此 attempt 从首次持久化起就具有非空、不可变 thread ID。activate 不修改 frozen ExecutionHandle，而是在同一 transaction 中创建至多一个不可变 TaskActivation；重复 activate 只返回该记录对应的相同 Contract。

Agent 派发使用两阶段协议：

1. GraphX 持久化 DispatchReservation、dispatch intent、request digest、`task_binding_token` 和 `taskCreate` ExternalOperation；适用时同时取得 active slot 与 reservation-owned mutation lease；
2. Host 只能使用 task-create operation ID、reservation identity 和 `task_binding_token` 幂等创建或查询 bootstrap task，不发送语义 Task Contract；
3. Host 调用 `bind(reservation_id, task_binding_token, host_id, thread_id)`；GraphX 在一个 transaction 中校验 reservation、token、bootstrap identity 和 `(host_id, thread_id)` 唯一性，同时创建 AgentAttempt 与不可变 ExecutionHandle、消费 reservation，并转移 active slot 与适用的 lease owner；完整请求 digest 相同的重复 bind 才幂等返回原结果；
4. Host 调用 activate；GraphX 在一个 transaction 中重新验证 attempt、thread、lease、ExecutionInputRevision 和执行隔离，持久化冻结 Task Contract、contract hash、activation ID、`contractDelivery` ExternalOperation 与 activation event，将节点转换为 `running`，然后返回 Contract 和 delivery operation ID；
5. Host 使用 delivery operation ID 幂等发送/查询完全相同的 Contract 字节序列，并把 activation ID 作为 task-visible identity。重复 activate 只返回同一 Contract 与 operation ID，不产生第二次状态转换。

bind 和 activate 请求都先由 Inbound MCP Adapter 校验，再进入 Application；涉及状态的读取、决定与写入由 StateCommitter 通过 Store Port 在一个 SQLite transaction 中提交。MCP handler 和 Host Adapter 都不能直接调用 Core transition 或 SQLite Adapter。

task 创建后、bind 前发生故障时，恢复流程必须先按 `task_binding_token` 查询 bootstrap task。无法唯一确认 task identity 时，reservation、node 和 Run 都进入 `ambiguous`，不得创建新 reservation、attempt 或 task；mutation lease 继续保留。只有找回并绑定原 task，或通过 provider 的强一致查询证明原 task 未创建/已终止，才能继续或重新派发。标题只用于展示，不能参与对账。

`ExternalOperation` 是 GraphX 对一次跨系统调用的持久化对账记录，使用 tagged kind `taskCreate | contractDelivery | mechanicalStart | settlementCheck`，并绑定唯一 operation ID、tagged parent identity、provider、request digest、observed disposition 与 evidence。`taskCreate` 的 parent 是 reservation，`contractDelivery` 的 parent 是 TaskActivation，`mechanicalStart` 的 parent 是 MechanicalAttempt，`settlementCheck` 的 parent 是 pending-settlement lease。ExternalOperation 不是 Workflow node，也不能自行改变 NodeState。

SQLite transaction 不能包围 Codex task 创建、Contract 发送或命令执行。每个 external operation 必须持久化稳定 operation ID、provider identity、idempotency key、canonical request digest、tagged parent identity、状态和 terminal evidence。Host 对网络 timeout、响应丢失或重启必须先按稳定 ID 查询，不能直接重新创建、重新发送或重新启动。若 provider 不支持幂等 create/send 与按 ID 查询，未知结果必须进入 `ambiguous`；尤其 Contract 是否已送达不明时，GraphX 不能把再次发送称为幂等，也不能允许 mutation 自动继续。GraphX 只保证自身状态效果 exactly-once，不保证外部副作用天然 exactly-once。

### 8.2 MechanicalAttempt 与 MechanicalExecutionHandle

`command` 和 `verifier` 也先由 `graphx_next` 创建 DispatchReservation，但此时不创建 mechanical operation 或 execution contract。Host 随后调用 `graphx_activate_mechanical(reservation_id, host_id, observed_input_revision)`；StateCommitter 在一个 transaction 中重新验证 Host binding、active slot、适用的 lease 与 revision，创建 MechanicalAttempt、不可变 MechanicalExecutionHandle 和 `mechanicalStart` ExternalOperation，消费 reservation，把 active slot owner 转给 MechanicalAttempt，冻结 execution contract，并把 node 转为 `running`。只有当该 mechanical node 本身为 `workspaceMutation` 时才把它取得的 reservation-owned lease 转给 MechanicalAttempt；`settlesMutation` verifier 为 `none`，目标 mutation 的 pending-settlement lease 始终由目标 settled record 持有，直到 verifier evidence 提交时释放。

```python
@dataclass(frozen=True, slots=True)
class MechanicalExecutionHandle:
    reservation_id: DispatchReservationId
    attempt_id: MechanicalAttemptId
    execution_id: MechanicalExecutionId
    operation_id: ExternalOperationId
    host_id: HostId
    input_revision: ExecutionInputRevision
    activated_at: datetime
```

`graphx_activate_mechanical` 返回 frozen contract、handle 与 `operation_id` 后，Host 才能按该 ID 幂等 start/query execution，不能自行生成 execution identity。若 activation 已提交但命令是否启动未知，按 external operation 对账，不能从 SQLite 状态推断已启动或未启动。

### 8.3 SettlementCheckExecution

`settlementCheck` 是安全恢复 execution，不是 Workflow node，也不改变原 verifier 的 attempt 计数或 NodeState。`requestSettlementCheck` 必须接收 authenticated Host identity 与按冻结 RevisionPolicy 得到的 observed input revision；StateCommitter 只在该 observation 等于 lease 当前 SettlementTargetRevision，或 Host 提供绑定该 revision 的不可变 snapshot identity 时，才可创建：

```python
@dataclass(frozen=True, slots=True)
class SettlementCheckExecution:
    recovery_execution_id: SettlementCheckExecutionId
    lease_id: MutationLeaseId
    recovery_sequence: int
    operation_id: ExternalOperationId
    host_id: HostId
    input_revision: ExecutionInputRevision
    evidence_subject_revision: EvidenceSubjectRevision
    check_hash: CheckHash
    contract_hash: ContractHash
    activated_at: datetime
```

创建 transaction 必须同时验证 recovery policy/sequence、冻结完全相同的 check contract、创建 `settlementCheck` ExternalOperation，并取得以 `recovery_execution_id` 为 owner 的 Run active slot。Host 只能在提交后按 operation ID 执行/query。提交 recovery result 时必须验证同一 execution 已 terminal、`sideEffect = none` 的 settled output 等于 input、EvidenceSubjectRevision 等于 lease 当前 SettlementTargetRevision，以及 evidence 的完整 identity/check hash；结果未知时 slot 与 lease 都保留。当前 workspace 已漂移且没有目标 revision snapshot 时不能把名义上的旧 revision 写进 evidence，必须先完成合法 revision 裁决或继续 `ambiguous`。

### 8.4 Task Contract

Agent task 获得：

- 当前 node ID 和 attempt ID；
- 节点目标；
- Config 中原样冻结的用户执行指引；
- 声明输入；
- workspace identity、路径和该 attempt 已冻结的 ExecutionInputRevision；
- side-effect class；
- 输出 Schema；
- 验收标准；
- retry/timeout 信息。

不自动注入整个 Workflow 对话历史。Codex 自己负责单个 task 的上下文管理。

Application 根据 immutable IR、当前 attempt 和版本化固定模板构造完整、规范化的 Task Contract；内容包括 GraphX 所需的身份、activation ID、结果格式和“不允许推进 Graph”的边界说明。StateCommitter 在 activate transaction 中冻结 Contract、canonical bytes 及其 hash。Host Adapter 只能原样传输，不能增加、删除或改写语义字段；transport envelope 不属于 Contract 且不能影响其 hash。Task Contract 必须包含当前 Run 冻结的 Host binding ID/hash、ExecutionInputRevision 和执行隔离摘要，但不得包含 GraphX 状态目录、数据库路径、数据库凭证或内部 Store 标识。

### 8.5 NodeResult

```text
NodeResult = AgentNodeResult | MechanicalNodeResult

CommonNodeResult
    run_id
    node_id
    status
    outputs
    evidence
    execution_disposition
    settled_output_revision
    diagnostics

AgentNodeResult
    kind = agent
    common
    reservation_id
    attempt_id
    task_binding_token
    thread_id
    activation_id

MechanicalNodeResult
    kind = mechanical
    common
    reservation_id
    attempt_id
    execution_id
    operation_id
```

Agent result 必须匹配已绑定 Codex ExecutionHandle、reservation 和 activation ID；`command` 和 `verifier` result 必须匹配持久化 MechanicalExecutionHandle 的 reservation、MechanicalAttempt ID、execution ID 与 operation ID，不需要 thread。`execution_disposition` 必须来自 Host 可验证的 terminal observation；`settled_output_revision` 必须满足第 7.4 节关系。VerificationEvidence 还必须显式携带 EvidenceSubjectRevision。`gate` 和 `terminal` 不接收外部 NodeResult。Inbound Adapter 先把外部 DTO 校验并转换为严格 tagged model，Pure Core 再检查身份、状态、输出、revision 和 evidence 语义，最后只能由 StateCommitter commit。

## 9. SQLite 控制面 system of record

这些表由 `adapters/store/sqlite/` 拥有；Pure Core 和 Application 只看领域模型与 Store Port，不看 SQLite row。建议表：

```text
workflow_configs
workflow_irs
runs
run_host_bindings
run_nodes
dispatch_reservations
agent_attempts
mechanical_attempts
execution_handles
task_activations
external_operations
mechanical_executions
settlement_check_executions
node_outputs
evidence_records
events
active_execution_slots
mutation_leases
idempotency_records
```

### 9.1 权威关系

- 在第 1.3 节的前提与 coordination domain 内，SQLite 是 GraphX 已提交控制面 RunState 的 system of record，而不是外部 task、进程或 workspace 字节的事实来源；
- SQLite Adapter 负责物理事务和数据库约束，StateCommitter 负责决定并校验状态语义；两者都不能越过对方的边界；
- Workflow IR 以 append-only、content-addressed 的规范 JSON 和 digest 保存；每个 Run 不可变地引用一个 IR digest，运行中不得重新读取当前 Config 生成控制语义；
- `run_host_bindings` 以规范化 snapshot 和 hash 保存 Host identity、workspace identity 和固定执行隔离要求，创建后不可变；
- Codex 对话不是状态权威；task 标题只用于展示，thread ID 用于恢复和对账；
- 日志可以丢失，已提交状态不能依赖日志恢复。

### 9.1.1 持久性、完整性与恢复前置条件

SQLite Adapter 必须显式设置并验证 durability profile，至少包括 foreign keys、crash-safe journal mode、`synchronous=FULL` 或经文档证明的等价设置、事务隔离与单 coordination domain writer/lock 规则，不能依赖 SQLite 默认值。数据库必须位于 SQLite 明确支持原子锁与持久化语义的本地文件系统；前置条件不满足时禁止派发。

`workflow_irs` 记录至少包含 Schema version、Compiler version、canonical JSON、IR digest 与创建时间。被 Run 引用的 IR 禁止 UPDATE/DELETE；加载时必须重算 digest。Run、Host binding、ExecutionHandle、冻结 Task Contract 和已提交 evidence 的不可变字段必须由 Store API 与数据库 constraint/trigger 共同保护。

恢复前必须校验 database/schema version、migration、SQLite integrity、IR digest、row codec、引用完整性、RunState 组合不变量、active slot、SettlementCheckExecution 与未结算 lease。能够识别的损坏一律 fail closed：禁止派发、释放 lease 或自动 retry。恢复来源只能是已验证备份；备份恢复后无法与 external operation 唯一对账的 reservation/attempt/recovery execution 必须进入 `ambiguous`。这套规则只检测可识别的损坏，不承诺从丢失或任意损坏数据库中自动重建事实。

### 9.2 事务规则

- 所有状态转换在 transaction 中完成；
- 读取当前状态与写入新状态必须处于同一 transaction；
- 每个提交带 expected previous state；
- `graphx_next` 的 scheduler decision、DispatchReservation、dispatch intent、Run active slot、可选 mutation lease、NodeState，以及 Agent dispatch 的 `taskCreate` ExternalOperation 必须在同一 transaction 中完成；Mechanical dispatch 的 start operation 只在 activation transaction 创建；
- terminal 满足时，必须先验证不存在 active/unresolved external operation 或 mutation lease，再把 terminal NodeState、RunStatus、WorkflowOutcome、未派发节点清理和 idempotency receipt 在同一 transaction 中完成；清理不得取消 pending-settlement verifier；
- idempotency identity 至少包含 operation kind、调用主体、run/node、reservation/attempt/execution identity 和 client key，并保存 canonical request digest 与 canonical response；同 key 同 digest 返回原结果，同 key 不同 digest 冲突拒绝；
- 结果、状态、output/evidence、active slot/lease 变化和 idempotency receipt 必须原子提交；未命中 receipt 的迟到结果再按当前 execution identity 判为 stale；
- idempotency record 的保留期不得短于其 Run 的恢复与审计生命周期；
- row codec 必须拒绝非法 RunStatus/WorkflowOutcome 组合、未知版本和不可能的 reservation/attempt/handle/lease 引用；
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
- Python MCP server 实现 Inbound MCP Adapter，向 Codex Host Adapter 提供结构化操作。

### 10.2 类型规则

所有生产目录：

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

### 10.4 初始代码目录与依赖边界

```text
src/graphx/
    __init__.py
    protocol/
        mcp_v1.py
    core/
        config/
            models.py
            semantic_validation.py
        ir/
            models.py
            compiler.py
        graph/
            analysis.py
            condition_evaluator.py
            scheduler.py
        runtime/
            models.py
            transitions.py
            result_validation.py
    application/
        ports/
            run_reader.py
            commit_transaction.py
        service.py
        state_committer.py
        query_service.py
    adapters/
        inbound/
            workflow/
                loader.py
                schemas.py
            mcp/
                tools.py
                server.py
            cli.py
        store/
            sqlite/
                store.py
                schema.py
                migrations.py
                row_codec.py
        host/
            codex.py
            command.py
            workspace.py
            main.py
    bootstrap.py
tests/
    unit/
        protocol/
        core/
        application/
        adapters/
    integration/
```

子目录中的 `__init__.py` 在图中省略。

依赖方向必须固定为：

```text
adapters/host --versioned MCP--> adapters/inbound/mcp -> application -> core
      |                                  |
      +---- imports protocol/mcp_v1 -----+

application -> application/ports <- adapters/store/sqlite
bootstrap.py -> adapters/inbound + application + adapters/store/sqlite
```

- `protocol/` 只定义 Host 与 Service 共同使用的版本化 wire DTO，不包含业务规则，也不能导入 `core/`、`application/` 或 `adapters/`。Host 与 Inbound MCP Adapter 必须使用同一份 Contract，禁止各自复制 Schema。
- `core/` 只包含领域模型和确定性规则，不执行 I/O，也不能导入 `application/` 或 `adapters/`。时间、随机值、外部结果和持久化状态必须作为已校验的显式输入传入。
- `application/` 编排用例和事务，只能依赖 `core/` 与自己定义的窄 Port，不能导入任何具体 Adapter。StateCommitter 位于这一层并拥有唯一状态提交权；纯状态转换函数仍位于 `core/runtime/transitions.py`。
- `adapters/inbound/` 使用 `protocol/` 校验外部 Workflow、MCP 和 CLI 输入，再映射为 Application 请求；它不能自行推进 Graph。
- `adapters/store/sqlite/` 实现 Application 定义的 Store Ports，是唯一允许导入 `sqlite3`、打开连接和执行 SQL 的目录；`bootstrap.py` 只能为装配传入私有数据库路径，不能读取数据库或把路径传给其他组件。数据库约束不能被内存实现替代。
- `adapters/host/` 在 Host 执行环境中连接 Codex、命令和 workspace revision，只能依赖 `protocol/` 与所需外部 API，并通过版本化 MCP Contract 与 GraphX Service 交互；它不能导入 `core/`、`application/`、Inbound Adapter、Store Adapter 或状态转换实现。`adapters/host/main.py` 是独立 Host 入口。
- `bootstrap.py` 是 GraphX Service 的唯一装配入口，只负责把 Inbound Adapter 和 SQLite Adapter 注入 Application；它不能导入或启动 Host Adapter。除这两个明确入口外，任何内层模块都不能反向导入具体实现。

Application Service、Query Service、编译、Graph 分析、状态转换、存储和 Host Adapter 必须保持独立。SQLite Adapter 是唯一数据库边界，Condition Evaluator 是唯一条件求值边界，StateCommitter 是唯一状态提交边界。

## 11. MCP 操作

每次 MCP 调用只映射到一个短小的 Application use case，不提供阻塞数小时的 `run` tool。MCP handler 不拥有事务；需要修改状态时，由 StateCommitter 通过 Store Port 开启并完成短事务。

初始操作：

```text
graphx_validate_workflow
graphx_start_run
graphx_next
graphx_bind_task
graphx_activate_task
graphx_activate_mechanical
graphx_submit_result
graphx_fail_attempt
graphx_reconcile_external_operation
graphx_resolve_mutation
graphx_inspect_run
graphx_resume_run
graphx_cancel_run
```

`graphx_inspect_run` 是只读操作，只能通过 Query Service 使用只读 Port。`graphx_next` 虽然名称包含“next”，但它可能创建 DispatchReservation、dispatch intent、active slot 和 mutation lease，因此不是查询；它和其他状态修改操作都必须由 Application Service 交给 StateCommitter，在一个 transaction 中完成读取、决策校验和提交。`graphx_resolve_mutation` 只接受第 7.3 节定义的 `requestSettlementCheck` 或结构化 MutationResolution；每次调用仅创建/返回 recovery operation 或提交其 evidence，不能阻塞等待检查，也不能充当任意状态写入接口。

`graphx_next` 返回严格 tagged union：

```text
NextDecision =
    AgentNodeDispatch(reservation_id, binding_token, task_create_operation_id, bootstrap_spec_ref)
  | MechanicalNodeDispatch(reservation_id, activation_spec_ref)
  | InternalNodeAdvanced(node_id, transition_digest)
  | AwaitingActiveExecution(execution_identity)
  | RunNotRunnable(run_status, diagnostics)
```

reservation 与各阶段 operation identity 只能由对应 GraphX transaction 生成，Host 不得自行构造。Agent 的 task-create operation 由 `graphx_next` 创建，contract-delivery operation 由 `graphx_activate_task` 创建；mechanical-start operation 与 frozen execution contract 由 `graphx_activate_mechanical` 创建。内部 `gate`/`terminal` 由 GraphX 在调用内求值并提交，只返回审计摘要，不返回可由 Host 执行的控制节点。

`graphx_resolve_mutation(action = requestSettlementCheck, ...)` 成功时返回 `SettlementCheckDispatch(recovery_execution_id, operation_id, recovery_sequence, frozen_contract)`；它不属于 NextDecision。Host 按 operation ID 执行/query 后，再以 `MutationResolution.attachSettlementEvidence` 提交 terminal disposition、settled output observation 和 evidence。两次调用间不得持有 SQLite transaction。

### 11.1 Agent 节点的 Host 调用流程

下面描述的是 Host 调用 GraphX 和 Codex 的先后顺序，不是 Workflow 节点之间的依赖关系。

启动一次 Run 时只执行一次：

```text
Host 调用 graphx_validate_workflow
    -> Host 调用 graphx_start_run
```

随后，每个 Agent 节点执行一次下面的循环：

```text
Host 调用 graphx_next
    -> GraphX 返回含 DispatchReservation 的 Agent NodeDispatch，或 AwaitingActiveExecution
    -> Host 按 task-create operation ID 与 reservation/token 幂等创建或查询 bootstrap Codex task，并取得 thread ID
    -> Host 调用 graphx_bind_task；GraphX 原子创建 AgentAttempt 与 ExecutionHandle
    -> Host 调用 graphx_activate_task，取得 Task Contract、activation ID 与 delivery operation ID
    -> Host 按 delivery operation ID 幂等发送或查询同一 Task Contract
    -> Host 等待 Codex 返回 NodeResult
    -> Host 调用 graphx_submit_result
    -> 回到 graphx_next，询问下一个节点
```

Run 从 `blocked` 恢复时，Host 先调用 `graphx_resume_run`，然后回到 `graphx_next`。Command 和 Verifier 节点不创建 Codex task，也不调用 task bind/activate；它们使用独立的 `graphx_activate_mechanical`。Host 必须按持久化 mechanical execution ID 幂等启动或查询声明动作，确认 terminal disposition 后再提交结构化结果。任何 create/send/start/query 返回未知状态时，Host 调用 `graphx_reconcile_external_operation`，不能自行重试副作用。

MechanicalNodeDispatch 只携带 reservation 与静态 activation reference。Host 调用 `graphx_activate_mechanical` 后才取得冻结 execution contract、MechanicalExecutionHandle 与 mechanical-start operation ID；随后按该 ID start/query command 或 verifier，最后提交 MechanicalNodeResult。activation transaction 成功而外部 start 结果未知时必须先对账。

Host Adapter 不能请求跳过 mandatory node，也不能提交不是当前 attempt 的结果。

## 12. 受控任务拆分

MVP 不包含 child workflow。Agent 可以在自己的 task 内拆分步骤，但这些步骤不成为 GraphX Node。

后续 child workflow 只能由 Config 显式授权，并编译为独立、不可变的 child IR；parent IR 不得修改，parent node 等待 child terminal，child 中每个已绑定 AgentAttempt 仍对应独立 Codex task。

## 13. 实施阶段

前六个阶段构成初始 MVP。每一阶段必须交付可执行、可测试的增量；从 Phase 3 开始形成端到端纵向链路。任何阶段都不得把本阶段依赖的 identity、revision、evidence、idempotency 或状态安全语义推迟到后续阶段。Phase 7 不属于 MVP。

在 Phase 5 的 mutation capability 交付前，Workflow Config 不得包含或派发 `sideEffect = workspaceMutation` 的节点；Phase 3 和 Phase 4 只允许 non-mutation external node，不能取得 mutation lease 或通过 Host 修改权威 workspace 内容。

### Phase 1：语义冻结和工程骨架

交付：

- 第 10 节定义的 Python 包骨架、工具配置、两个独立入口和依赖守卫；
- `WorkflowConfig`、immutable `WorkflowIR`、RunState aggregate、RunStatus、CancellationIntent、WorkflowOutcome、NodeState、DispatchReservation、AgentAttempt、MechanicalAttempt、各类 ExecutionHandle、TaskActivation、SettlementCheckExecution、ExternalOperation、MutationResolution 与 ConditionDecision 的独立严格模型；
- MCP request/response、NodeDispatch、NodeResult、ExternalOperation、WorkspaceRevision、VerificationEvidence 和错误响应的版本化 wire Schema；
- 第 1.3、3.4 和 10.4 节的 authority、信任、隔离与模块边界。

完成条件：公开模型、状态组合、转换、所有权和错误语义无未决项；未知字段、非法版本/枚举、越层访问及隔离前置条件缺失均可被拒绝。

### Phase 2：Pure Core 编译与调度

交付：

- Workflow Compiler、Graph 分析、immutable IR、稳定序列化与 IR digest；
- 冻结的 verifier check ID/hash、RevisionPolicy、条件 AST、retry/settlement-recovery policy、terminal outcome 和规范化 node-ID 顺序；
- Pure Core Condition Evaluator、全部 TransitionDecision、依赖/skip/timeout 语义、ready 计算和稳定串行 Scheduler；
- SCHED-01 的 active-execution guard 决策及 OUTCOME-01 的 RunStatus/WorkflowOutcome 不变量。

完成条件：Core 对相同 IR 与 validated RunState snapshot 产生相同决定；全部合法/非法转换均有纯内存测试；`core/` 不执行 I/O，也不导入外层实现。

### Phase 3：持久化机械验证链路

交付：

- Store Port、SQLite Adapter、migration、durability profile、完整性恢复、Application Service、StateCommitter、只读 Query Service 与 Inbound MCP Adapter；
- non-mutation 的 `command -> verifier -> gate -> terminal` 纵向链路；
- mechanical ExternalOperation 的稳定 operation ID、幂等 create/query、NodeResult identity、ExecutionInputRevision、SettledOutputRevision 与 VerificationEvidence 校验；
- verifier evidence 从本阶段起即绑定 run、node、execution、check ID/hash、EvidenceSubjectRevision 和结构化结果；
- `graphx_next` active slot、result receipt、恢复和 transaction 一致性。

完成条件：机械 Workflow 能在进程重启后继续；错误 evidence、revision、identity、idempotency digest 或 IR digest 不能提交成功；任何 `workspaceMutation` node 均在创建 reservation 前被拒绝。

### Phase 4：只读 Codex Agent 链路

交付：

- GraphX Skill、独立 Codex Host Adapter、不可变 Run Host binding；
- tagged NodeDispatch、DispatchReservation、bootstrap/create-query、bind、TaskActivation、Contract delivery-query 协议；
- Agent NodeResult 复用 Phase 3 的完整 identity、output、revision、evidence 与 idempotency 校验；
- inspect、resume、cancel，以及 task create response、Contract delivery 或 Host lifecycle 未知时的对账。

完成条件：每个 AgentAttempt 从创建起即有一个可恢复、可见、身份明确的 ExecutionHandle；bind/activate 前不发送语义 Task Contract，冻结 Contract 不可被 Host 改写；所有 Agent node 均为 non-mutation，无法幂等查询的外部未知结果进入 `ambiguous`。

### Phase 5：安全 Workspace Mutation

交付：

- `workspaceMutation` capability、canonical workspace identity、workspace-scoped mutation lease、激活前复检和唯一约束；
- 基于既有 revision binding 的 mutation input/output 对账、execution terminal/受控后代确认、故障恢复、`ambiguous` 和结构化 MutationResolution；
- StateCommitter、SQLite transaction、Host external operation 与实际 workspace 之间的故障边界；
- lease 只在第 7.3 节全部结算条件满足后释放，包括 verifier retry 耗尽/取消后的 GraphX-issued `settlementCheck` 恢复路径。

完成条件：任何故障注入点都不会让 GraphX 并行派发 mutation、自动重放未知 mutation 或因 timeout、退出、重启提前释放 lease；未裁决 mutation 始终阻塞后续 mutation。若 Host 不能证明 execution 静止，产品承诺明确降为“GraphX 不再派发另一个 mutation”，不能声称不存在外部延迟写入。

### Phase 6：MVP 加固和发布

交付：

- 参考 Workflow、端到端外部故障矩阵、SQLite 损坏/备份恢复演练、操作与恢复手册；
- 普通 Command Node 表达外部刷新屏障；
- 第 14 节全部验收矩阵和发布门禁；
- README、AGENTS 与其他摘要链接本计划的 requirement ID 或权威小节，不重新定义细节；必须复制的摘要片段由校验或生成流程保持同步。

完成条件：参考 Workflow 在正常执行、重启、重复请求、外部投递未知、Host 故障、数据库可识别损坏和 mutation 不确定场景下保持第 1.2 节不变量；超出第 1.3 节信任前提的情形明确 fail closed 或标注为不可保证。

### Phase 7：受控 Child Workflow（非 MVP）

仅在基础 Executor 稳定后实现第 12 节定义的 child workflow；不得修改 parent IR，也不得阻塞 MVP 发布。

## 14. 测试门槛

测试至少按以下组组织。每组同时覆盖接受、拒绝、恢复和幂等路径，并在测试名或 metadata 中引用对应 requirement ID 或权威小节。

### 14.1 Schema 与 IR

- Workflow、MCP、Task Contract、NodeDispatch、NodeResult、inspect 和 error response 的版本、未知字段、枚举、大小限制与 tagged identity；
- external node 缺失或非法 `sideEffect`、internal node 伪造 `sideEffect`、非法 `settlesMutation`，以及 `settlesMutation`/`settlementRecovery` 未同时出现必须拒绝；
- 重复 node ID、悬空引用、类型不匹配、环、不可达 node/terminal、非法 retry、非法 verifier check spec；
- check ID/hash、RevisionPolicy、条件 AST、terminal outcome、规范化 node-ID 顺序、稳定 IR serialization 和 immutable IR digest；
- IR 在创建 RunState 前冻结；持久化 IR/digest 损坏、不匹配、更新、删除或恢复后不一致必须拒绝；
- 原始 Config 的后续变化不能改变已创建 Run 的 IR。

### 14.2 状态与 Scheduler

- 每个合法和非法 NodeState/RunStatus 转换、RunStatus/WorkflowOutcome 组合、retry 上限、`ambiguous`、blocked/resume/cancel；
- `validated -> blocked`、`blocked node -> cancelled`、terminal condition false、failure terminal outcome 与 operational failure 无 outcome；
- CancellationIntent 与最终 `cancelled` 分离且 MVP 不可撤销；有 intent 时 resume/普通 next 拒绝，存在 active/unresolved external operation 或 mutation lease 时 Run 不得进入任何 terminal status；
- success dependency、skip propagation、缺失输出拒绝和 timeout 先对账语义；
- ready node 稳定排序、每个 Run 至多一个 active external execution、恢复前后相同调度决定；
- 并发或重复 `graphx_next` 只有一个调用可提交 reservation/slot；已有 active execution 时返回 `AwaitingActiveExecution`；
- `when`、`gate`、`terminal` 只由 Pure Core 求值；任何 Host ConditionDecision 或控制结果均拒绝。

### 14.3 Dispatch 与 Codex task

- DispatchReservation 不等于 AgentAttempt；bind 前不创建 attempt，bind transaction 原子创建 AgentAttempt、ExecutionHandle、消费 reservation，并转移 active slot 与适用的 lease owner；
- MechanicalNodeDispatch 之后必须先用 `graphx_activate_mechanical` 原子创建 MechanicalAttempt/MechanicalExecutionHandle/start operation、消费 reservation 并冻结 ExecutionInputRevision，Host 才能启动；active slot 必须从 reservation 转给 MechanicalAttempt，仅 mechanical mutation 转移自身 reservation-owned lease，settlement verifier 不接管目标 lease；
- binding token、reservation、attempt、activation ID、thread ID 唯一性，以及错误/重复/并发 bind、跨 attempt thread 复用；
- activate-before-bind、错误 thread activate、重复 activate、冻结 Contract canonical bytes/hash 和 Host 篡改拒绝；
- bootstrap task create response 丢失、bind 前重启、Contract delivery response 未知、按稳定 token/ID 查询和对账；
- task-create operation 只由 `graphx_next` 创建，contract-delivery operation 只由 Agent activation 创建，mechanical-start operation/contract 只由 mechanical activation 创建；提前、重复或跨父 identity 使用必须拒绝；
- provider 不支持幂等 create/send/query 时进入 `ambiguous`，不得创建第二个 reservation、attempt 或 task；
- 每个已绑定 AgentAttempt 恰有一个独立 Codex ExecutionHandle，孤立 bootstrap task 只关联 reservation，不被伪称为 attempt。

### 14.4 Store、幂等与恢复

- SQLite foreign key、唯一 constraint、active slot、lease、request identity 和 canonical payload digest；同 key 同 digest 返回 canonical response，同 key 异 digest 拒绝；
- transaction 任一点进程终止均完整提交或回滚，result/state/output/evidence/slot/lease/receipt 不出现部分状态；
- row codec 拒绝未知版本、非法状态组合和不可能引用；Application 不接收原始 row；
- 明确 durability profile 在每个 connection 生效；不支持的文件系统、配置或 writer/lock 状态禁止派发；
- integrity check、migration、IR digest、event/reference continuity、thread binding、未结算 lease 与备份恢复；
- 数据库可识别损坏时 fail closed，禁止派发、释放 lease 或自动 retry；恢复后未知 external operation 进入 `ambiguous`；
- idempotency record 生命周期覆盖 Run 恢复与审计生命周期，未命中 receipt 的迟到结果按 execution identity 拒绝。

### 14.5 Mutation 与 revision

- Phase 3/4 拒绝 `workspaceMutation`；Phase 5 前不得创建 mutation reservation 或 lease；
- canonical workspace identity、同一 coordination domain 的 mutation lease 唯一性、多个 Run 的 mutation 不并行；
- mutation activate 前复检 lease、ExecutionInputRevision、Host binding 和隔离；
- tracked 修改/删除及权威 untracked 新文件改变 digest，明确派生路径变化不改变 digest；provider version、policy digest、排序、大小写和符号链接规则稳定；
- read-only settled output 等于 input；mutation output relation、SettledOutputRevision/SettlementTargetRevision、Verifier EvidenceSubjectRevision 和后续 attempt input 正确绑定；
- settlement verifier 必须直接依赖目标 mutation，其他依赖必须是目标祖先；相关 terminal 缺少对 verifier 的传递依赖时 Config 拒绝，任何 pending-settlement lease 都使 terminal 非法；
- settlement verifier evidence 为 `passed` 或 `failed` 均可结算；normal execution retry 耗尽、取消、recovery operation 成功/失败/未知，以及等价 evidence identity/hash/revision 的接受与拒绝路径均覆盖；CancellationIntent 后新的普通 retry 必须拒绝；
- SettlementCheckExecution 获取/保留/释放 active slot，input/settled-output/subject revision 绑定，`(lease_id, recovery_sequence)` 唯一性、IR 次数上限、重复 request 幂等与上限耗尽永久 blocked 均覆盖；
- revision 测量/执行 TOCTOU、Host 丢失、进程退出、后台执行未确认静止或结果无法对账进入 `ambiguous`；
- MutationResolution 的 identity、workspace、observed revision、decision 和 rationale 校验；错误、陈旧或范围不符的裁决拒绝；
- execution disposition、revision/evidence、Node/RunState、active slot 与 lease release 原子提交；timeout、重启和 Agent 自报不能单独释放 lease。

### 14.6 Verification 与 terminal

- VerificationEvidence 绑定 run、node、execution、check ID/hash、EvidenceSubjectRevision 和结构化结果；错误 identity/hash、stale revision 或缺失 evidence 拒绝；
- verifier 检查完成但 evidence status 为 `failed` 时，verifier node 仍可 `succeeded`，由 Config terminal 决定 WorkflowOutcome；检查未可靠执行时 node 为 `failed`；
- Agent 自报完成或 task-local 自检不能替代 Config 声明的 Verifier；
- Agent/Mechanical NodeResult 的输出、identity、重复、stale、错误 reservation/attempt/execution 拒绝；
- terminal 是唯一可写 WorkflowOutcome 的节点；terminal NodeState、RunStatus、WorkflowOutcome 和未派发节点清理原子提交；
- terminal cleanup 不得取消或绕过 pending-settlement verifier，Run terminal status 不得残留 active slot、unresolved operation 或 mutation lease；
- 普通 Command 失败阻止其 success-dependent node，且 Pure Core 不包含外部工具专属逻辑。

### 14.7 架构与隔离边界

- `core/` 不导入 `application/` 或 `adapters/`；Application 不导入具体 Adapter；`protocol/` 不导入任何 GraphX 层；
- 只有 `adapters/store/sqlite/` 可导入 `sqlite3`、创建 connection 或执行 SQL；`bootstrap.py` 只为装配传递私有数据库路径；
- Host Adapter 只依赖 `protocol/` 和外部 API；MCP/CLI Adapter、Codex task、Host 不能绕过 Query Service/StateCommitter 访问 SQLite；
- Query Service 只持有 read-only Port，不能提交状态或返回原始 SQLite row；MCP handler 只做 Schema 和错误映射；
- database path、Store identity 和私有状态目录不泄露给 MCP、Task Contract、Host 或 Codex task；
- Host binding、workspace identity、隔离 snapshot/hash 在 Run 中不可变；恢复时不一致阻止派发；
- 无硬隔离能力时 Agent node 在 reservation/lease 创建前进入 `blocked`，不得用 prompt 声称隔离成功。

发布门禁：

```text
pyright
ruff check
ruff format --check
pytest
```

全部必须成功。
