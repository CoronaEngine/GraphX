# Polaris 设计文档

> 面向概率型软件工程 Agent 的确定性控制运行时。

**状态：** 草案 0.2  
**更新日期：** 2026-08-31  
**范围：** Task Graph 核心架构、工作流配置、控制语义、验证、持久化与恢复、Context Materialization，以及未来自我改进的边界。

---

## 1. 概述

Polaris 是一个面向**可靠、长时间运行的软件工程 Agent 执行**的框架。

它的核心假设很简单：

> 基于 LLM 的 Agent 是概率性的，但外层执行流程不必是概率性的。

因此，Polaris 将**控制权**与 **Agent 执行**分离，并把工作流建模为一个显式的 **Task Graph**：

```text
Task / Goal
    ↓
Workflow Configuration (JSON)
    ↓
Task Graph
    ↓
Polaris Runtime
    ↓
Deterministic Graph Execution / State Machine
    ↓
Agent / Tool / Command / Verifier
```

Agent 负责完成工作。Polaris 负责决定**哪些节点可以执行、何时可以执行、执行后是否允许继续，以及当前节点应该获得哪些持久化资源和上下文**。

可以用一句话概括：

> **Config owns control. Polaris enforces control. Agent performs work.**  
> **配置拥有控制语义，Polaris 负责强制执行，Agent 负责完成工作。**

Polaris 不应该变成另一个“不断询问 LLM 下一步该做什么”的自治 Agent。它更应该表现得像一个包裹在概率型 Worker 外部的 **Task Graph Runtime**、调度器、状态机与验证器。

从软件架构上，可以把它理解为：

> **RenderGraph / Task Graph for probabilistic software-engineering nodes.**

Graph 与控制语义是确定性的；Graph 中的 Agent Node 可以是概率性的。

---

## 2. 主要目标

Polaris 围绕以下目标体验设计：

> 人类只需要花有限时间描述目标、约束和工作流策略，之后 Agent 可以持续工作更长时间，同时整个过程仍然有边界、可观察、可恢复、可验证。

Polaris 的首要优化目标**不是最大自治性**。

首要优化目标是：

> **长时间、稳定、正确地执行任务。**

因此，Polaris 的优先级应当是：

1. 可恢复性（Recoverability）
2. 可观察性（Observability）
3. 可验证性（Verifiability）
4. 可逆性（Reversibility）
5. 确定性控制（Deterministic Control）
6. 最后才是更高自治性

---

## 3. 非目标

Polaris 不打算成为：

- 一门通用编程语言；
- LLM 本身的替代品；
- 通用的多 Agent 企业业务工作流平台；
- 一个允许 LLM 自由重写自身控制循环的系统；
- 一个把所有执行语义都隐藏在 Prompt 中的框架；
- 一个把 LLM 判断和机械保证视为等价的运行时。

---

## 4. 核心架构原则

Polaris 从概念上划分为三层。

### 4.1 稳定运行时（Stable Runtime）

Runtime 拥有那些应该很少变化的执行语义：

```text
Polaris Runtime
├── Configuration Loader
├── Schema Validator
├── Semantic Validator
├── Static Analyzer
├── State Machine
├── Scheduler
├── Persistence
├── Recovery
├── Retry / Timeout Enforcement
├── Permission / Action Boundary
├── Mechanical Verifier
├── Audit Log
└── Runtime Event System
```

Runtime 应当尽可能小、显式，并且很难被 Agent 绕过。

### 4.2 可演化的工作流配置（Evolvable Workflow Configuration）

工作流行为应当通过外部配置描述，而不是硬编码在 Runtime 中。

例如：

- 实现前必须先做规划；
- Plan 必须经过 Review；
- 测试通过后才能进入验证阶段；
- 完成前必须经过独立 Verifier；
- Retry 最多三次；
- 某些动作需要人工批准；
- 某个阶段必须采用特定 Context 策略。

修改这些策略时，通常应该**修改配置，而不是修改 Polaris 源码**。

### 4.3 概率型执行（Probabilistic Execution）

执行面包含可能非确定、甚至任意复杂的组件：

```text
Agent
Shell command
Compiler
Python tool
Build system
Static analyzer
Repository tools
External services
```

这些组件可以执行任意复杂的工作，但它们不拥有工作流的控制语义。

---

## 5. 控制面与执行面

这两者之间的分离属于硬性架构边界。

### 控制面（Control Plane）

控制面必须尽可能满足：

- 声明式；
- 在实际可行范围内有界；
- 控制表达式无副作用；
- 可静态分析；
- 显式；
- 可持久化；
- 可重放；
- 可机械强制执行。

### 执行面（Execution Plane）

执行面可以是：

- 图灵完备的；
- 概率性的；
- 高成本的；
- 有状态的；
- 与外部系统连接的；
- 可以执行任意计算的。

关键规则：

> **任意计算能力应该存在于叶子 Action 中，而不是存在于控制表达式中。**

---

## 6. Task Graph 是核心抽象

Polaris 的核心不是“Agent Loop”，而是 **Task Graph Execution**。

每一个 Workflow 都应被转换成显式 Graph：

```text
Inspect
   ↓
Plan
   ↓
Implement
   ↓
Test
   ↓
Verify
   ↓
Finish
```

Graph Node 可以是概率型 Agent，也可以是确定性 Command、Verifier、Gate 或 Terminal。

### 6.1 Graph 决定控制，Node 完成工作

Polaris 的基本不变量是：

```text
Graph owns control.
Node owns execution.
```

更具体地说：

- Graph 定义依赖；
- Graph 定义 Gate；
- Graph 定义哪些验证必须发生；
- Runtime 决定节点何时 Ready；
- Node 只负责生产声明的结果或 Artifact；
- Agent 不能自行重写 Graph 或直接跳转到任意节点。

因此，Polaris 可以机械保证：

> 某个节点只有在其依赖和 Gate 满足时才会执行。

但它不能机械保证：

> Agent Node 的输出一定正确。

### 6.2 Node Input / Output 是一等概念

Task Graph 不应只有控制边，还应允许节点声明数据依赖。

例如：

```json
{
  "id": "implement",
  "type": "agent",
  "inputs": [
    "task_contract",
    "plan",
    "active_constraints",
    "relevant_source_files"
  ],
  "outputs": [
    "code_changes",
    "implementation_observations"
  ]
}
```

这使 Polaris 可以区分：

```text
Control Dependency
A must finish before B

Data / Artifact Dependency
B consumes output produced by A
```

这与 RenderGraph 中 Pass 和 Resource 的关系类似。

### 6.3 Workflow Configuration 是 Graph Serialization

JSON 不承担执行能力，它只负责描述 Graph。

推荐处理流程：

```text
workflow.json
    ↓
Parse
    ↓
Workflow IR / Task Graph
    ↓
Validation
    ↓
Static Analysis
    ↓
Execution Plan
    ↓
Runtime
```

JSON、未来可能的 UI 或其他前端，都只是 Workflow Graph 的不同序列化 / 编辑方式。


---

## 7. 工作流表示

Polaris 初期不需要设计一套自定义文本 DSL。

推荐的表示方式是：

> **JSON + JSON Schema + Polaris 语义规则**

JSON 只是序列化层。真正的领域模型由 Polaris 定义。

例如：

```json
{
  "task": {
    "goal": "Implement resource migration"
  },
  "constraints": [
    "ABI cannot change",
    "Vulkan 1.2 only"
  ],
  "workflow": [
    {
      "id": "inspect",
      "type": "agent"
    },
    {
      "id": "plan",
      "type": "agent",
      "depends_on": ["inspect"]
    },
    {
      "id": "implement",
      "type": "agent",
      "depends_on": ["plan"]
    },
    {
      "id": "test",
      "type": "command",
      "depends_on": ["implement"],
      "command": "./tests RenderGraphTests"
    },
    {
      "id": "verify",
      "type": "verifier",
      "depends_on": ["test"]
    },
    {
      "id": "finish",
      "type": "terminal",
      "depends_on": ["verify"]
    }
  ]
}
```

---

## 8. 禁止任意 Eval

这是一个永久性的架构约束，而不仅仅是第一版的简化方案。

> **Polaris 不得在控制表达式中执行任意代码。**

以下形式不能被接受为控制逻辑：

```json
{
  "when": "eval(user_supplied_expression)"
}
```

Condition 也不应该通过直接调用 Python / JavaScript 的 `eval`、动态代码生成或等价机制实现。

### 原因

允许任意 eval 会破坏多个重要属性：

- 静态可分析性；
- 可预测的控制语义；
- 引用合法性检查；
- 类型检查；
- 可靠 Replay；
- 安全的自我修改边界；
- 对“必经 Verifier 路径”的证明能力；
- 控制面与执行面的清晰区分。

它还会把工作流配置隐式地变成另一门通用编程语言。

### 硬规则

控制表达式必须采用结构化表示，并且无副作用。

概念上：

```text
Condition : State → Bool
```

而不是：

```text
Condition : State → Bool + Side Effects + Graph Mutation
```

---

## 9. 条件表达式（Conditions）

第一版应该故意采用一个很小的 Condition 模型。

例如：

```json
{
  "condition": {
    "source": "test.exit_code",
    "op": "eq",
    "value": 0
  }
}
```

Polaris 将 `test.exit_code` 解析为 Runtime State 中的一个引用。

概念上：

```text
"test.exit_code"
      ↓
["test", "exit_code"]
      ↓
Runtime State Lookup
      ↓
0
      ↓
eq(0, 0)
      ↓
true
```

初始操作符可以包括：

- `eq`
- `ne`
- `gt`
- `ge`
- `lt`
- `le`
- `exists`
- `and`
- `or`
- `not`

复杂表达式应该表示为结构化表达式树，而不是任意源码字符串。

例如：

```json
{
  "condition": {
    "op": "and",
    "args": [
      {
        "op": "eq",
        "lhs": { "ref": "test.exit_code" },
        "rhs": { "const": 0 }
      },
      {
        "op": "eq",
        "lhs": { "ref": "verify.result" },
        "rhs": { "const": "passed" }
      }
    ]
  }
}
```

---

## 10. 类型化引用（Typed References）

工作流中的引用最终应该支持静态类型检查。

一个节点可以声明自身输出：

```json
{
  "id": "test",
  "type": "command",
  "outputs": {
    "exit_code": "integer",
    "stdout": "string",
    "stderr": "string"
  }
}
```

于是如下条件：

```json
{
  "source": "test.exit_code",
  "op": "eq",
  "value": 0
}
```

可以在执行前完成检查：

```text
test.exit_code : integer
0              : integer
eq(integer, integer) → valid
```

这样 Polaris 可以在 Agent 真正开始工作之前拒绝无效的工作流定义。

---

## 11. 校验流水线（Validation Pipeline）

配置加载应该分成多个明确阶段。

```text
JSON Input
   ↓
JSON Parsing
   ↓
JSON Schema Validation
   ↓
Semantic Validation
   ↓
Reference Resolution
   ↓
Type Validation
   ↓
Graph Construction
   ↓
Static Analysis
   ↓
Executable Workflow
```

### 11.1 JSON Schema Validation

负责检查结构是否合法：

- 必填字段；
- enum 值；
- 字段类型；
- 数值范围；
- 不支持的字段；
- 无效节点类型。

### 11.2 Semantic Validation

负责检查 JSON Schema 本身难以优雅表达的关系：

- 被引用节点是否存在；
- Node ID 是否唯一；
- 被引用 Output 是否存在；
- Transition Target 是否存在；
- 是否存在不兼容的节点组合；
- 是否存在不支持的执行策略。

### 11.3 Static Graph Analysis

负责检查工作流层面的属性：

- 不可达节点；
- 悬空 Transition；
- 无效环；
- 无界 Retry 路径；
- Terminal State 是否可达；
- Mandatory Verification 是否覆盖所有必要路径；
- 是否存在禁止的绕过路径；
- Dependency Graph 是否非法。

---

## 12. 工作流节点模型（Workflow Node Model）

Polaris 初始版本应该故意保持较小的节点集合。

候选节点类型：

### `agent`

调用由 LLM 驱动的 Worker。

### `command`

执行一个确定性的外部命令或工具。

### `verifier`

评估任务结果或 Artifact 的质量。

Verifier 可以是机械的、基于 LLM 的，或混合式的。

### `gate`

检查 Condition，并允许或拒绝 Transition。

### `human_approval`

阻塞执行，直到收到明确的人工授权。

### `parallel`

启动一个有界的子节点集合。

### `join`

等待所需的上游节点完成。

### `terminal`

标记成功、失败、取消或中止等终止状态。

除非存在明确用例，否则应该避免随意扩展 Node Model。

---

## 13. 硬保证与软判断（Hard vs Soft Guarantees）

Polaris 必须明确区分机械保证和概率型判断。

### 硬保证（Hard Guarantee）

例如：

```text
exit_code == 0
file exists
schema valid
required artifact exists
specific command executed
retry_count <= N
mandatory node visited
```

Polaris 可以机械保证这些规则确实被执行。

### 软判断（Soft Judgment）

例如：

```text
architecture is good
implementation is maintainable
requirements are fully understood
design has no conceptual regression
```

这些需要 LLM Verifier 或人类判断。

Polaris 可以保证：

> Verifier 按照 Workflow 要求被调用了。

Polaris 不能保证：

> Verifier 的判断在客观上一定正确。

这个区别必须始终在 Runtime State 和 Log 中保持可见。

---

## 14. Task Contract

每个任务都应该拥有一个明确的 Contract，描述执行过程中必须始终成立的条件。

示例字段：

```json
{
  "task_contract": {
    "goal": "Implement resource migration",
    "constraints": [
      "ABI cannot change",
      "Vulkan 1.2 only",
      "No breaking API"
    ],
    "required_verification": [
      "RenderGraphTests"
    ]
  }
}
```

Task Contract 表示的是持久化的任务意图，它应该能够跨越 Context 压缩、进程重启、Subagent 执行和恢复过程而继续存在。

Task Contract 不只是 Prompt 文本。Polaris 应将其视为一等 Runtime State。

---

## 15. Observation Ledger

Polaris 应维护一个以追加为主的 Observation Ledger，用于记录执行期间发现、且会影响后续工作的事实。

例如：

- 仓库事实；
- 已被证伪的假设；
- 测试结果；
- 已修改文件；
- 新发现的约束；
- 尚未解决的风险；
- Verifier 发现；
- 历史尝试；
- Recovery Checkpoint。

Observation Ledger 提供持久化的外部记忆，避免关键状态只存在于 LLM Context Window 中。

一个有用的概念划分是：

```text
Task Contract
= 什么必须始终成立

Observation Ledger
= 已经学到了什么

Working Set
= 模型当前真正需要看到什么
```

---

## 16. Context Materialization 与 Active Working Set

Polaris 不应该把模型 Context Window 当成永久数据库，也不应该把“如何压缩整个上下文窗口”作为自己的主要职责。

新的责任边界是：

> **Polaris 决定模型当前应该看到什么；底层 Agent Runtime / Model Harness 决定这些内容如何在实际 Context Window 中进行容量管理、压缩或内部维护。**

因此，Polaris 的 Context Management 更准确地说是：

> **Task-aware Context Materialization。**

而不是通用的 Token-level Context Manager。

### 16.1 Context 是 Cache，不是真源

核心不变量：

> **Context is a cache, not the source of truth.**  
> **Context 是缓存，不是真源。**

真正的持久状态应该存在于：

- Task Contract；
- Runtime State；
- Artifact Store；
- Observation Ledger；
- Repository；
- CodeGraph 或其他可恢复外部来源。

LLM 当前看到的 Prompt / Context，只是这些持久化数据为当前 Node materialize 出来的一个视图。

因此：

> **Persistence ≠ Visibility。**

并进一步得到：

> **Persistence ≠ Context。**

### 16.2 Working Set 优先从 Task Graph 依赖推导

过去一种可能的设计是：

```text
巨大 Context
    ↓
Context Manager 判断
哪些保留 / 哪些删除 / 哪些 fault-in
```

Polaris 应优先采用更确定的方式：

```text
Current Task Node
      ↓
Declared Inputs / Dependencies
      ↓
Resolve Artifacts / State
      ↓
Materialize Active Working Set
      ↓
Agent Execution
```

例如：

```json
{
  "id": "implement",
  "type": "agent",
  "inputs": [
    "task_contract",
    "plan",
    "active_constraints",
    "artifact:source_set"
  ]
}
```

Runtime 根据声明依赖加载：

- 当前 Goal；
- Active Constraints；
- Plan；
- 当前节点明确依赖的 Artifact；
- 必须可见的 Pinned State；
- 少量与当前节点直接相关的 Observation。

这样 Context Working Set 主要由 Graph Semantics 推导，而不是依赖 LLM 在大量历史消息中主动判断什么应该被删除。

### 16.3 Artifact Materialization

Artifact 是跨节点传递和恢复信息的主要媒介。

典型 Artifact 包括：

- `plan.json`
- 源文件集合；
- Patch / Diff；
- Test Result；
- Build Log；
- Static Analysis Result；
- Verifier Report；
- Repository Snapshot Reference；
- CodeGraph Query Result；
- Observation Slice。

概念上：

```text
Task A
   ↓ produces
Artifact X
   ↓ consumed by
Task B
```

Artifact 应拥有稳定 ID / Reference，而 Context 中只 materialize 当前节点真正需要的内容。

### 16.4 Context 生命周期可以类似 Resource Lifetime

Task Graph 已经提供依赖信息，因此 Polaris 可以逐步引入类似 RenderGraph 的 Context / Artifact Lifetime 分析。

```text
Artifact produced
      ↓
used by Node B
      ↓
used by Node C
      ↓
last use
      ↓
no longer materialized by default
```

注意：

> 不再 materialize 不等于删除持久化 Artifact。

这使得 Recoverability 与 Context 清理天然兼容。

### 16.5 Recoverability-Aware Context Management

Recoverability-Aware 原则仍然成立，但实现重点改变了。

如果某条信息已经持久化、有稳定 Reference，并且可以低成本重新 materialize，那么它无需长期占据当前模型可见 Context。

例如：

- 源文件；
- CodeGraph 关系；
- 已保存命令输出；
- Test Log；
- Observation Ledger 中的历史事实；
- 已生成的 Plan Artifact。

因此 Polaris 更关注：

```text
Can this information be deterministically recovered?
```

而不是：

```text
Should I permanently keep this message in the model transcript?
```

### 16.6 Attention-Aware 原则保留，但降为次级优化

即使 Context Window 尚未接近上限，低价值信息仍可能稀释有效注意力。

因此 Polaris 仍然应该控制 Working Set 大小，但优先级应该是：

```text
Declared dependency
    ↓
Task-aware materialization
    ↓
Pinned invariants
    ↓
必要时再做额外 attention-aware trimming
```

而不是先实现复杂的 Token-level eviction 策略。

### 16.7 Pinned Context

某些信息应该跨多个 Node 持续可见：

- Task Goal；
- Active Constraints；
- 当前阶段；
- 当前 Plan 的关键摘要；
- 不可违反的架构决策；
- 用户明确 Pin 的事实。

Pinned Context 仍然由 Polaris 管理，因为底层通用 Context Manager 并不知道当前软件工程任务中哪些语义属于不可丢失的不变量。

### 16.8 与 Codex / 底层 Agent Runtime 的责任边界

对于 Codex 或其他具备 Native Compaction / Context Lifecycle 的底层 Agent Runtime，Polaris 不应重复建设其容量级机制。

推荐边界：

```text
Polaris
  ├── Task-aware input selection
  ├── Artifact persistence
  ├── Working Set materialization
  ├── Pinned task semantics
  └── Recovery references
            ↓
Underlying Agent Runtime
  ├── Native context-window management
  ├── Compaction
  ├── Internal summarization
  └── Model-specific token handling
```

因此，以下方向不应成为 Polaris 当前主线：

- 自研通用 Compaction Engine；
- 与模型 Harness 竞争 Token-level eviction；
- 复杂 Transcript GC；
- 模拟底层模型自己的 Context Window 策略。

Polaris 应把精力放在模型底层无法自动知道的 **Task Semantics** 上。

---

## 17. Action Boundary

Polaris 应区分普通推理和会产生外部后果的 Action。

任何具有显著外部影响的动作，都应该跨越一个明确的 Action Boundary。

例如：

- 修改文件；
- 删除文件；
- 提交 Git 变更；
- 发布 Artifact；
- 网络侧变更；
- 修改外部服务；
- 修改持久化 Workflow Policy。

Runtime 应能够在该边界上施加更强规则：

- Mandatory Verification；
- 显式权限；
- 类事务式 Log；
- Approval Gate；
- Rollback Preparation；
- Precondition Check。

---

## 18. Runtime State

Runtime State 应该显式、可序列化。

例如：

```json
{
  "run_id": "...",
  "workflow_version": "...",
  "current_node": "test",
  "node_states": {
    "plan": {
      "status": "completed"
    },
    "implement": {
      "status": "completed"
    },
    "test": {
      "status": "running",
      "attempt": 2
    }
  },
  "task_contract": {},
  "observation_ledger_ref": "...",
  "working_set_ref": "..."
}
```

进程崩溃后，不应该依赖 LLM Transcript 来重建 Runtime State。

---

## 19. Recovery

Recovery 是一等设计要求。

Polaris 应能够在以下情况后从持久化状态恢复执行：

- 进程崩溃；
- 机器重启；
- 模型失败；
- 工具超时；
- Context 被替换；
- Agent 被中断；
- 显式 Pause / Resume。

因此，Workflow 应避免依赖隐藏的解释器状态。

恢复流程应类似：

```text
Load Runtime State
      ↓
Load Task Contract
      ↓
Load Observation Ledger
      ↓
Rebuild Current Working Set
      ↓
Check Last Action Boundary
      ↓
Resume Current / Next Node
```

这也是为什么控制表达式应该保持声明式、无副作用。

---

## 20. Retry 语义

Retry 必须显式且有界。

例如：

```json
{
  "retry": {
    "max_attempts": 3,
    "on": ["verification_failed", "tool_error"]
  }
}
```

Runtime 必须明确：

- 什么算一次 Attempt；
- 哪些 Failure 可以 Retry；
- 哪些 State 保留；
- 哪些 State 重置；
- Side Effect 是否必须回滚；
- Retry 耗尽后执行流转向哪里。

控制面不应该支持无界 Retry Loop。

---

## 21. Independent Verification

在实际可行的情况下，提出或执行变更的组件，不应该同时成为唯一决定该变更是否可接受的权威。

概念上：

```text
Executor
   ↓
Candidate Result
   ↓
Independent Verifier
   ↓
Accept / Reject
```

Verification 可以组合：

- 机械测试；
- 静态分析；
- Schema Validation；
- Repository Invariant；
- 独立 LLM Review；
- Human Review。

外部影响或 Blast Radius 越大，对 Verification 的要求就应该越强。

---

## 22. Runtime Invariants

以下内容可以作为 Polaris 的候选不变量。

### Invariant 1：禁止任意 Control Eval

Workflow Condition 或 Control Expression 中不得执行任意代码。

### Invariant 2：控制表达式无副作用

Condition 可以观察 State，但不能修改 State，也不能调用 Action。

### Invariant 3：Agent 输出不能直接修改控制流

Agent 可以产生 Proposal 或 Event。由 Runtime 判断该 Event 是否有效，以及之后应该发生什么 Transition。

### Invariant 4：Mandatory Gate 不能被 Agent 指令绕过

如果 Workflow 要求完成前必须测试或验证，那么 Agent 不能直接跳转到成功 Terminal State。

### Invariant 5：Runtime State 独立于 LLM Context

关键控制状态必须能够跨越模型替换或 Context 替换继续存在。

### Invariant 6：Retry 有界

Control Plane 中的 Loop 必须具有显式上限。

### Invariant 7：机械判断与概率型判断始终可区分

LLM Verifier 的成功判断，绝不能被记录成等价于机械证明。

### Invariant 8：执行前校验 Workflow 定义

只要可能，无效 Config 应该在昂贵的 Agent 执行开始前直接失败。

### Invariant 9：持久化数据与 Prompt 可见数据分离

Polaris 应独立决定什么需要持久化，以及什么当前需要暴露给模型。

### Invariant 10：Context 不是 Source of Truth

任何关键任务状态都不得只存在于当前 LLM Context 中。Context 必须能够从持久化 State、Artifact、Ledger 或 Repository 中重建。

### Invariant 11：控制权始终位于 Agent 之外

Agent 负责工作，但不拥有 Runtime State Machine。

---

## 23. Self-Improvement

Polaris 未来可以支持自我改进型 Workflow，但应该实现为**受控的配置演化**，而不是不受限制的 Runtime 自我修改。

推荐模型：

```text
Execution History
      ↓
Failure / Performance Analysis
      ↓
Improvement Proposal
      ↓
Candidate Workflow Config
      ↓
Schema + Static Validation
      ↓
Benchmark / Replay
      ↓
Independent Evaluation
      ↓
Promote or Reject
```

Agent 可以提出以下方面的修改：

- Retry Policy；
- Workflow 顺序；
- Verification Step；
- Context Strategy；
- Skill Selection；
- Task Decomposition Policy。

Agent 不应该直接修改：

- Runtime Permission Boundary；
- Audit Rule；
- Rollback Infrastructure；
- Core Verifier Authority；
- 决定“Agent 自身修改是否被接受”的策略。

一个有用的规则是：

> **一个组件不能被允许削弱用于评价该组件自身的机制。**

---

## 24. 不修改 Runtime 的 Workflow 演化

Polaris 的主要架构收益之一，是 Workflow 演化通常不应该要求修改 Runtime 代码。

初始 Workflow：

```text
Plan
 ↓
Execute
 ↓
Verify
```

后续 Workflow：

```text
Inspect
 ↓
Plan
 ↓
Plan Review
 ↓
Execute
 ↓
Mechanical Test
 ↓
Independent Verify
 ↓
Finish
```

这种变化应该只需要修改 Workflow Configuration，而不是在 Polaris 内部新增一条硬编码执行路径。

只有在真正引入了新的**执行原语（Execution Primitive）**或**控制语义（Control Semantic）**时，才应该修改 Runtime 代码。

---

## 25. Code、Config、Skill 与 Task 的关系

Polaris 应保持严格的概念分离。

### Code

定义**机器如何运行**。

例如：

- State Transition；
- Persistence；
- Retry Enforcement；
- Graph Execution；
- Static Validation。

### Config

定义**必须经过什么流程**。

例如：

- 必须规划；
- 必须经过 Verifier；
- Retry 次数；
- 执行顺序。

### Skill

定义**Agent 应该如何思考或执行某一类工作**。

例如：

- Debugging Methodology；
- Planning Methodology；
- Code Review Methodology；
- Repository Investigation Strategy。

### Task

定义**最终需要实现什么**。

例如：

- 实现 Resource Migration；
- 修复 Crash；
- 重构子系统 X。

概念上：

```text
Task
  ↓
Workflow Config
  ↓
Skill / Agent Policy
  ↓
Agent / Tool Execution

All of the above are controlled by:

Polaris Runtime
```

---

## 26. 建议的初始范围

第一版应该刻意保持较小范围。

### Phase 1：Task Graph / Control Semantics

实现：

- JSON Workflow Definition；
- JSON Schema Validation；
- Semantic Validation；
- Workflow IR / Task Graph；
- 基础 Graph Construction；
- Node Input / Output Declaration；
- 顺序依赖与数据依赖；
- Command Node；
- Agent Node；
- Verifier Node；
- Terminal Node；
- 有界 Retry；
- 机械 Transition Check；
- Audit Log。

目标：

> 先证明 Polaris 可以稳定地机械执行一个由概率型 Node 组成的确定性 Task Graph。

### Phase 2：持久化、Artifact 与 Recovery

加入：

- 持久化 Runtime State；
- Artifact Store / Artifact Reference；
- Task Contract；
- Observation Ledger；
- Recovery Checkpoint；
- Pause / Resume；
- Action Boundary；
- Side-effect Tracking。

目标：

> 让 Graph Execution 不依赖单次进程或单次 LLM Context 存活。

### Phase 3：Context Materialization

加入：

- Node Context Dependency；
- Active Context Working Set；
- Pinned Context；
- Artifact → Context Materialization；
- Repository State Awareness；
- CodeGraph Integration；
- Recoverability-aware Materialization；
- 必要的 Attention-aware Trimming；
- 与底层 Codex / Agent Runtime Native Context Management 的适配。

明确不优先实现：

- 自研通用 Compaction；
- Token-level eviction engine；
- 通用 Transcript GC。

### Phase 4：验证强化

加入：

- Independent Verifier；
- 更强的 Static Workflow Analysis；
- Mandatory Verification Path Analysis；
- Benchmark；
- Replay；
- Failure Taxonomy。

### Phase 5：自适应 Workflow

加入：

- Execution Telemetry；
- Improvement Proposal Generation；
- Candidate Workflow Generation；
- Replay / Benchmark Evaluation；
- 受控 Configuration Promotion；
- Rollback。
---

## 27. 架构审查问题

任何新 Feature 都应该用以下问题审查：

1. 这个能力应该属于 Runtime Code、Workflow Config、Skill，还是 Task State？
2. 它是否给 LLM 增加了新的控制权？
3. 它能否绕过已有 Gate？
4. 它是否可能引入无界执行？
5. 它是否会把隐藏 Side Effect 引入控制逻辑？
6. 它还能否被静态校验？
7. Runtime State 是否仍然能够持久化和恢复？
8. 执行是否仍然可以 Replay 或 Audit？
9. 它是否模糊了机械保证与 LLM 判断之间的边界？
10. 这是一个真正新的 Primitive，还是现有 Primitive 已经能通过 Config 表达？
11. 这个信息应该成为持久化 Artifact，还是仅仅属于当前 Context View？
12. 当前 Node 的 Context 是否可以直接从 Graph Input / Artifact Dependency 推导，而不是依赖 LLM 猜测？
13. 这个 Context 能力是否已经属于底层 Agent Runtime 的 Native Compaction / Context Lifecycle，Polaris 是否正在重复建设？

如果一个 Workflow 变化可以通过现有 Primitive 表达，默认选择应该是：

> **改 Config，不改 Runtime Code。**

---

## 28. 一句话定义

> **Polaris 是一个面向概率型软件工程节点的确定性 Task Graph Runtime，用于机械执行可配置、可验证、可恢复的长时间软件工程工作流。**

更短的版本：

> **A deterministic task-graph runtime for probabilistic coding agents.**  
> **面向概率型 Coding Agent 的确定性 Task Graph Runtime。**

一个便于工程类比的表达：

> **Polaris = RenderGraph for Agent Tasks.**

这里的类比只针对架构骨架：Graph、Dependency、Artifact、Lifetime、Validation、Scheduling 与 Execution；Agent Node 的概率性仍然是 Polaris 需要额外解决的问题。

---

## 29. 设计哲学总结

Polaris 应主动做出如下取舍：

```text
Less uncontrolled expressiveness
            ↓
More analyzability
More recoverability
More verification
More determinism
More auditability
```

也就是：

```text
减少不受控制的表达能力
            ↓
获得更强的可分析性
更强的可恢复性
更强的可验证性
更强的确定性
更强的可审计性
```

Polaris 不应该追求让控制面具备最大能力。

它应该让控制面**足够表达所需工作流，同时始终保持机械上可理解**。

因此，整个架构最核心的设计思想是：

> **Keep intelligence flexible. Keep control explicit.**  
> **让智能保持灵活，让控制保持显式。**

对于 Context，增加第二条同等级原则：

> **Context is a cache, not the source of truth.**  
> **上下文只是当前 Task Node 的工作缓存，持久化 State / Artifact 才是真源。**

因此 Polaris 不追求成为模型底层的通用 Context Window Manager，而是利用 Task Graph 的依赖信息，机械构造当前节点真正需要的 Working Set。
