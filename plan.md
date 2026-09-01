# Polaris Task Graph Executor 实施计划

> 本文档是 Polaris 的实现与范围权威。概念设计与论证见
> `Polaris_Design_ZH_v0.2.md`；发生冲突时，以本文档为准。

## 1. 产品定义

Polaris 是一个面向概率型编码 Agent 的、确定性的 Task Graph Executor（任务图执行器）。

它接收声明式工作流配置，将其编译为带类型的 Workflow IR，完成静态校验，然后以可恢复、可审计的方式执行图中的节点：

```text
Workflow Config
    -> Compile to typed Workflow IR
    -> Validate graph and contracts
    -> Persist run state
    -> Execute ready nodes
    -> Verify outputs and transitions
    -> Reach an explicit terminal state
```

核心原则：

```text
Config owns control.
Polaris enforces control.
Nodes perform work.
```

- 工作流配置决定执行什么、依赖关系、条件、重试和完成条件。
- Polaris 只理解通用图语义，不硬编码“计划、实现、测试、修复”等业务流程。
- Agent、命令、验证器等节点负责完成局部工作，但无权绕过运行时改变图状态。
- 底层 Codex 或其他 Agent Runtime 负责单个 Agent 节点内的推理、工具调用与模型上下文管理。

### 1.1 “不关心流程是什么”的准确含义

Polaris 对工作流的领域含义无感，但对执行语义负责。

它不需要知道一个节点是在“写需求”“修改 Rust”还是“部署服务”，但必须知道：

- 节点类型与输入输出契约；
- 节点之间的依赖和条件；
- 节点是否就绪、成功、失败或需要人工介入；
- 重试、超时和副作用策略；
- 哪些产物可作为后续节点的输入；
- 运行如何持久化、恢复和终止。

因此 Polaris 不是业务流程生成器，也不是简单脚本包装器，而是通用的图执行内核。

### 1.2 核心不变量

1. **配置拥有控制权**：运行时不得自行增加、删除或重排业务节点。
2. **执行前完整校验**：非法图、悬空引用、类型不匹配和不可达终点不得进入运行态。
3. **状态独立于上下文**：权威运行状态必须持久化，不能只存在于模型对话中。
4. **确定性调度**：同一 IR 和同一权威状态应产生同一组 ready nodes；v1 采用稳定顺序串行执行。
5. **显式状态转换**：只有 Executor 可以提交节点和运行状态转换。
6. **产物可寻址**：跨节点数据通过带身份与完整性信息的 Artifact 传递。
7. **副作用受控**：可能修改工作区或外部世界的动作必须跨越持久化 Action Boundary。
8. **失败有界**：重试、超时和恢复策略必须显式且有限。
9. **完成可验证**：只有声明的 terminal 条件满足后，运行才能成功结束。
10. **不伪造 exactly-once**：无法确认副作用结果时进入 `AMBIGUOUS`，不得盲目重放。

## 2. v1 范围

v1 构建一个本地、前台、单运行实例的可靠 DAG 执行器。

### 2.1 包含

- JSON 工作流配置和 JSON Schema；
- Config 到不可变、带类型 Workflow IR 的编译；
- 引用、类型、图结构和 terminal 完整性校验；
- 稳定顺序的串行 DAG 调度；
- `agent`、`command`、`verifier`、`gate`、`terminal` 五类内置节点；
- 带类型的输入、输出和 Artifact 引用；
- 有限条件表达式；
- 每节点超时与有界重试；
- append-only 事件日志、物化 RunState 和原子 checkpoint；
- 节点 attempt、日志、输出与验证证据的持久化；
- Action Boundary 和崩溃后的保守恢复；
- 面向 Agent 节点的声明式上下文物化；
- Runner 协议与内置 Runner；
- Schema、编译器、状态机、恢复和端到端测试。

### 2.2 明确不包含

- 自动发明、改写或优化用户工作流；
- 硬编码的软件工程阶段；
- 任意代码执行式条件表达式（例如 `eval`）；
- 循环图、动态扩图和递归工作流；
- 分布式调度、多主协调和跨机器执行；
- 通用企业工作流平台、插件市场、可视化编排 UI；
- 并行节点与 join 语义；
- Polaris 自己实现通用 token 级压缩、对话 GC 或模型缓存策略；
- 对任意 Agent 工具调用提供虚假的 exactly-once 保证。

这些能力只有在 v1 语义和恢复模型稳定后，才能通过本文档变更进入范围。

## 3. 责任边界

| 组件 | 负责 | 不负责 |
|---|---|---|
| Workflow Config | 节点、边、参数、条件、重试、完成条件 | 执行状态、恢复决策 |
| Compiler / Validator | 生成 IR、解析引用、类型检查、图分析 | 执行节点、修改工作区 |
| Graph Executor | ready 计算、状态转换、持久化、重试、恢复、终止 | 理解业务领域、代替节点完成工作 |
| Node Runner | 执行一种通用节点类型并返回结构化结果 | 改图、直接提交 RunState、声明整个运行完成 |
| Agent Runtime | 单个 Agent 节点内的推理、工具使用、上下文窗口管理 | 跨节点调度、全局恢复和图完成判定 |

Codex 在该架构中是可替换的 `AgentRunner` 后端，而不是 Polaris 的控制平面。

## 4. Workflow Config 与 IR

### 4.1 配置示例

```json
{
    "version": 1,
    "workflow": {
        "id": "implement-and-verify",
        "entrypoints": ["implement"],
        "nodes": [
            {
                "id": "implement",
                "type": "agent",
                "inputs": {
                    "task": { "literal": "Implement the requested change" }
                },
                "outputs": {
                    "summary": "text",
                    "workspace": "workspace_snapshot"
                },
                "retry": { "maxAttempts": 2 },
                "timeoutSeconds": 1800
            },
            {
                "id": "test",
                "type": "command",
                "dependsOn": ["implement"],
                "inputs": {
                    "workspace": { "from": "implement.workspace" },
                    "command": { "literal": ["just", "test"] }
                },
                "outputs": {
                    "report": "test_report"
                },
                "timeoutSeconds": 1800
            },
            {
                "id": "accept",
                "type": "gate",
                "dependsOn": ["test"],
                "condition": {
                    "eq": [
                        { "from": "test.report.status" },
                        { "literal": "passed" }
                    ]
                }
            },
            {
                "id": "done",
                "type": "terminal",
                "dependsOn": ["accept"],
                "outcome": "success"
            }
        ]
    }
}
```

这只是一个输入示例，不是运行时内置流程。同一个 Executor 必须能执行任何通过校验的 DAG。

### 4.2 IR 的含义

IR（Intermediate Representation，中间表示）是配置与执行器之间的内部、规范化、带类型表示。

```text
Human-authored JSON
        |
        v
Compiler + Validator
        |
        v
Immutable Workflow IR
        |
        v
Graph Executor
```

IR 的目的不是再定义一种用户协议，而是消除执行期歧义：

- 所有默认值已经展开；
- 节点 ID、边和 Artifact 引用已经解析；
- 节点类型和输入输出类型已经确定；
- 条件表达式已经编译为受限 AST；
- 拓扑信息和稳定调度顺序已经计算；
- 重试、超时和副作用策略已经规范化；
- IR 一旦开始运行即不可变，并具有内容哈希。

### 4.3 三类数据必须分离

| 数据 | 含义 | 生命周期 |
|---|---|---|
| Config | 用户声明的工作流 | 可编辑，运行前编译 |
| Workflow IR | 规范化后的执行定义 | 单次运行期间不可变 |
| RunState | 该 IR 的一次具体执行状态 | 随事务化状态转换演进 |

不得把运行时状态回写进 Config，也不得让节点输出修改 IR。

## 5. 编译与静态校验

Executor 启动前必须一次性拒绝以下错误：

- Schema 不合法、未知字段或不支持的版本；
- 重复、空白或非法节点 ID；
- 缺失依赖、悬空输出引用或自依赖；
- 有环图；
- 不可达节点或不可达 terminal；
- 输入输出类型不兼容；
- 条件引用不存在的字段或不支持的运算符；
- 无界重试、非正超时或非法退避；
- 未声明副作用等级；
- terminal outcome 非法或成功终点不完整。

校验器输出稳定、可定位的诊断：错误码、JSON 路径、节点 ID 和说明。不得等到节点开始执行才发现结构错误。

## 6. 节点模型

### 6.1 通用 NodeSpec

每个节点至少包含：

- `id`：工作流内唯一、稳定的标识；
- `type`：内置节点类型；
- `dependsOn`：前驱集合；
- `inputs`：literal 或上游 Artifact 引用；
- `outputs`：命名输出及其类型；
- `condition`：可选受限表达式；
- `retry`：最大 attempt 数与可选退避；
- `timeoutSeconds`：单次 attempt 的上限；
- `sideEffect`：`readOnly`、`workspaceMutation` 或 `externalSideEffect`。

### 6.2 v1 节点类型

#### `agent`

调用 Codex 或兼容 Agent Runtime，传入 Task Contract 和声明的输入，返回结构化输出、日志和 workspace 结果。

#### `command`

通过 argv 形式执行本地命令，不经 shell 字符串拼接；捕获退出码、stdout、stderr、超时和工作目录信息。

#### `verifier`

消费候选 Artifact，产出机械验证或概率验证证据。它不直接声明全局成功。

#### `gate`

只解释受限条件 AST，根据已经持久化的输入选择通过、失败或阻塞；不执行任意代码。

#### `terminal`

在依赖和条件满足时，将运行提交为 `SUCCEEDED` 或声明的失败结果；不执行工作负载。

## 7. 执行语义

### 7.1 节点状态

```text
PENDING
READY
PREPARED
RUNNING
SUCCEEDED
FAILED
SKIPPED
BLOCKED
AMBIGUOUS
```

- `PENDING -> READY`：依赖满足，条件可求值且允许执行。
- `READY -> PREPARED`：attempt 和意图已持久化，尚未执行副作用。
- `PREPARED -> RUNNING`：Runner 已取得执行权。
- `RUNNING -> SUCCEEDED`：输出和证据已经持久化并通过契约检查。
- `RUNNING -> FAILED`：attempt 明确失败；若策略允许，可创建新 attempt。
- `PENDING -> SKIPPED`：条件明确为 false，且跳过在该位置合法。
- 任意非终态可因不可满足依赖进入 `BLOCKED`。
- 崩溃后无法判断副作用是否完成时进入 `AMBIGUOUS`。

终态为 `SUCCEEDED`、`FAILED`、`SKIPPED`、`BLOCKED`、`AMBIGUOUS`。终态不可原地回退；重试必须创建新的 attempt 记录。

### 7.2 运行状态

```text
CREATED -> VALIDATED -> RUNNING
RUNNING -> SUCCEEDED | FAILED | BLOCKED | AMBIGUOUS | CANCELLED
```

只有 Executor 可以提交这些转换。Runner 只能返回 `NodeResult`。

### 7.3 Ready 计算与调度

节点可进入 `READY`，当且仅当：

1. 它仍为 `PENDING`；
2. 所有依赖都处于该边允许的终态；
3. 所需 Artifact 均存在且完整性校验通过；
4. 条件可以只依赖权威状态求值；
5. 没有未处理的 `AMBIGUOUS` 副作用阻断运行。

v1 每次选择稳定排序后的最小 node ID，串行执行。顺序是可复现机制，不是业务语义。

### 7.4 NodeResult

Runner 返回结构化结果：

```text
NodeResult
    status: succeeded | failed | blocked
    outputs: map<name, ArtifactDraft>
    evidence: list<Evidence>
    diagnostics: list<Diagnostic>
    retry_class: never | transient | policy
```

Executor 校验结果、提交 Artifact，再转换节点状态。Runner 不得直接写 RunState。

## 8. 副作用与 Action Boundary

### 8.1 副作用等级

- `readOnly`：只读取固定输入，可安全重试。
- `workspaceMutation`：修改 Polaris 管理的工作区；只有具备隔离或可核验提交协议时才能自动恢复。
- `externalSideEffect`：修改远端系统或向外部人员发送信息；v1 默认拒绝。

### 8.2 持久化执行边界

对每个 attempt，Executor 必须：

1. 分配稳定 `attempt_id`；
2. 持久化输入引用、IR 哈希、策略和 `PREPARED` 事件；
3. 原子提交 checkpoint；
4. 调用 Runner；
5. 捕获结果、日志和产物；
6. 原子提交 Artifact 与终态事件；
7. 重新计算 ready nodes。

崩溃恢复时只能得到三种结论：

- 有证据表明未执行：可按策略重新开始；
- 有可核验结果表明已成功：提交原结果；
- 无法判定：标记 `AMBIGUOUS`，停止后续有副作用节点并要求人工裁决。

### 8.3 Agent 节点的现实边界

如果底层 Agent 可以不受控地修改工作区，Polaris 无法声称精确恢复。`AgentRunner` 至少采用一种可验证机制：

- 每个 attempt 使用隔离工作区/worktree，成功后由 Polaris 提交结果；或
- Agent 的写操作经过 Polaris 管理的工具网关并记录动作；或
- 明确把该节点标为不可自动重放，崩溃后进入 `AMBIGUOUS`。

v1 优先采用隔离工作区；不能隔离的外部副作用不进入自动重试路径。

## 9. 持久化、Artifact 与恢复

### 9.1 持久化布局

```text
.polaris/runs/<run_id>/
    workflow.json
    workflow.ir.json
    state.json
    events.jsonl
    attempts/<attempt_id>/
        request.json
        result.json
        stdout.log
        stderr.log
    artifacts/<artifact_id>/
        metadata.json
        payload
```

- `events.jsonl` 是 append-only 审计记录；
- `state.json` 是从事件物化出的原子 checkpoint；
- 启动恢复时验证两者一致性，并以已提交事件为权威；
- 临时文件写入后必须 flush、fsync，并通过原子 rename 提交。

### 9.2 Artifact 身份

每个 Artifact 至少包含：

- `artifact_id`、`run_id`、producer node 与 attempt；
- 声明类型和内容类型；
- 内容哈希、字节数和创建时间；
- 上游 Artifact 引用；
- 可选 workspace revision / snapshot identity；
- payload 的受控路径。

后续节点按 Artifact ID 读取，不按“最近一次同名文件”猜测。

### 9.3 恢复算法

1. 读取并验证 Workflow IR 哈希；
2. 重放事件并验证 checkpoint；
3. 检查 Artifact 元数据和内容哈希；
4. 对未完成 attempt 调用对应 Runner 的 reconcile；
5. 将可证实结果提交为终态；
6. 将不可判定副作用标为 `AMBIGUOUS`；
7. 重新计算 ready nodes；
8. 从下一个安全节点继续。

恢复不得依赖模型“回忆上次做到哪里”。

## 10. Task Contract、Observation 与上下文物化

### 10.1 Task Contract

Agent 节点接收结构化 Task Contract，而不是整段历史对话：

- 节点目标；
- 可用输入 Artifact；
- 工作区身份；
- 允许的工具和副作用；
- 输出 Schema；
- 完成与验证标准；
- timeout 和 attempt 信息。

### 10.2 Observation

Observation 是描述外部可变事实的特殊 Artifact，例如某文件内容、Git revision 或测试结果。它必须绑定：

- 来源；
- 观测时的版本身份；
- 内容哈希；
- producer attempt；
- 可选有效性条件。

Polaris 在物化下游输入时拒绝已知 stale observation。v1 只实现声明输入链上的局部版本校验，不构建全局知识图谱。

### 10.3 Context Materialization

Polaris 的上下文职责是路由，不是 token 管理：

```text
NodeSpec + declared Artifacts + current attempt metadata
    -> deterministic Task Contract / Context View
    -> AgentRunner
```

规则：

- 默认只注入节点显式声明的输入；
- 每项输入有大小上限，超限时传引用和摘要元数据；
- Materializer 输出稳定排序和内容哈希；
- 不把完整运行日志或历史对话自动注入每个节点；
- 不修改底层 Agent Runtime 的 compaction 或缓存策略；
- 模型窗口不足是 Runner 层错误，Executor 按显式策略处理。

## 11. 验证与完成语义

验证证据分为：

- **机械证据**：退出码、Schema、测试报告、哈希、静态检查；
- **概率证据**：Agent/模型评审，必须记录模型、输入 Artifact 和输出。

原则：

- 能机械验证的条件不得只依赖模型判断；
- Verifier 输出证据，Gate 解释条件，Terminal 提交运行结果；
- Agent 自报“完成”不是全局完成条件；
- 成功 terminal 必须消费配置中声明的全部必要证据；
- 缺失、过期或类型错误的证据导致阻塞或失败，不能静默通过。

## 12. 建议代码结构

```text
polaris/
    cli.py
    config/
        schema.py
        loader.py
    ir/
        model.py
        compiler.py
        expressions.py
    graph/
        analysis.py
        scheduler.py
    runtime/
        executor.py
        state.py
        transitions.py
        recovery.py
    runners/
        protocol.py
        agent.py
        command.py
        verifier.py
        gate.py
        terminal.py
    artifacts/
        model.py
        store.py
    persistence/
        events.py
        checkpoint.py
        atomic.py
    context/
        contract.py
        materializer.py
    diagnostics.py
tests/
    integration/
```

模块名不是公共 API 承诺，但责任边界必须保留。避免把编译、调度、执行和持久化集中在一个 Controller 大类中。

## 13. 实施任务

### 任务 1：Schema 与领域模型

交付：

- Workflow Config JSON Schema；
- Node、Input、Output、Retry、Timeout、SideEffect 模型；
- 稳定诊断格式；
- 合法/非法配置 fixture。

完成条件：Schema 能拒绝未知字段、非法版本、无界策略和所有结构性错误。

### 任务 2：Compiler、IR 与静态分析

交付：

- Config -> Workflow IR；
- 引用解析与类型检查；
- 环检测、可达性、terminal 完整性；
- 受限条件 AST；
- 稳定 IR 序列化与内容哈希。

完成条件：等价配置产生稳定 IR；任何非法图在执行前失败。

### 任务 3：内存 Executor 与 Runner 协议

交付：

- 节点/运行状态机；
- ready 计算和稳定串行调度；
- NodeRunner / NodeResult 协议；
- 重试分类和超时接口。

完成条件：使用 fake runners 可完整执行分支 DAG，并精确断言每个状态转换。

### 任务 4：内置 Runners

交付：

- `command`、`gate`、`terminal`；
- `verifier` 的机械验证基础；
- `agent` 适配 Codex 或兼容 runtime；
- argv、工作目录、环境和输出上限控制。

完成条件：节点不能直接改图或 RunState，所有结果经过 Executor 校验后提交。

### 任务 5：事件、Artifact 与持久状态

交付：

- append-only events；
- 原子 checkpoint；
- content-addressed Artifact store；
- attempt 目录和日志；
- 重放与一致性验证。

完成条件：在任一提交点杀死进程后，重启可恢复到最后一个完整状态。

### 任务 6：Action Boundary、重试与恢复

交付：

- `PREPARED/RUNNING` 协议；
- bounded retry/backoff；
- Runner reconcile；
- `AMBIGUOUS` 阻断语义；
- Agent 隔离工作区策略。

完成条件：未确认副作用不会自动重复；只读 transient failure 可安全重试。

### 任务 7：输入解析与 Context Materialization

交付：

- Artifact reference resolver；
- Task Contract；
- 稳定、受限的 Context View；
- Observation 版本校验与 stale rejection。

完成条件：Agent 节点仅看到声明输入；可检测并拒绝已知 stale observation。

### 任务 8：强制验证、端到端测试与发布门

交付：

- verifier/gate/terminal 组合语义；
- CLI `validate`、`run`、`resume`、`inspect`；
- 崩溃注入测试；
- 参考工作流和操作文档。

完成条件：参考工作流可以在多次故障注入后恢复并只由 terminal 提交最终结果。

## 14. 测试门槛

每次改变执行语义，至少覆盖：

- Schema 和版本兼容拒绝；
- 引用、类型、环、可达性和 terminal 分析；
- ready 计算与稳定调度；
- 所有合法及非法状态转换；
- 条件为 true、false、缺失和类型错误；
- timeout、可重试失败、永久失败和 attempt 上限；
- 崩溃发生在 Action Boundary 前、执行中、结果提交前后；
- Artifact 缺失、损坏和哈希不一致；
- Observation current/stale 判定；
- Runner 返回非法输出；
- `AMBIGUOUS` 阻止后续副作用；
- Agent 自报完成但 terminal 条件不满足；
- 从持久状态恢复后与未中断运行得到相同最终状态。

## 15. 里程碑

### Phase 1：图与控制语义

完成任务 1-4。目标是证明 Polaris 能以统一内核执行任意合法 v1 DAG，而不硬编码工作流。

### Phase 2：持久化、Artifact 与恢复

完成任务 5-6。目标是把执行从“可运行”提升为“崩溃后可安全判断和继续”。

### Phase 3：上下文物化与版本化 Observation

完成任务 7。目标是让 Agent 节点获得最小、可追踪、与当前状态一致的输入。

### Phase 4：验证闭环与发布

完成任务 8。目标是以明确证据和 terminal 条件结束长任务。

### Phase 5：后续候选

只有在 v1 基准和故障数据支持时考虑：

- 有界并行与 join；
- 动态扩图或子图；
- 人工审批节点；
- 分布式 Runner；
- 更丰富的 Observation 失效传播；
- UI 和可视化诊断；
- 工作流模板库。

## 16. 产品决策规则

新增能力必须回答：

1. 它是通用图执行语义，还是某个具体工作流的业务逻辑？
2. 它是否改变 Config、IR 或 RunState 的边界？
3. 它在崩溃后如何判定已发生、未发生或不确定？
4. 它如何被结构化验证，而不是依赖模型自报？
5. 它是否让相同输入的调度更难复现？
6. 它是否能先作为节点或 Runner 实现，而不污染 Executor 内核？

属于具体流程的逻辑应留在工作流配置或节点实现中；只有通用、可验证的执行语义才能进入内核。

## 17. 最终定义

Polaris 的目标不是替代 Codex 的模型上下文管理，也不是决定软件工程应该采用什么流程。

它提供的是一个窄而坚固的控制层：把外部声明的 Task Graph 编译成不可变 IR，以确定性调度、持久化状态、受控副作用、版本化 Artifact 和显式验证来执行，直到到达可证明的 terminal 状态。
