# Polaris

Polaris 是一个面向概率型编码 Agent 的、确定性的 Task Graph Executor（任务图执行器）。

它执行作为数据提供的工作流。工作流定义节点、依赖、条件、重试和完成标准；Polaris 校验并落实这些规则，但不决定工作流应该是什么。

```text
Config owns control.
Polaris enforces control.
Nodes perform work.
```

[English README](README.md)

## 状态

Polaris 正处于早期设计和实现阶段。[plan.md](plan.md) 是实现范围的权威文档；[Polaris_Design_ZH_v0.2.md](Polaris_Design_ZH_v0.2.md) 包含更完整的设计论证。

## Polaris 做什么

```text
Workflow JSON
    -> 编译与静态校验
    -> 不可变、带类型的 Workflow IR
    -> 持久化图运行时
    -> 节点 Runners
    -> 经验证的 terminal 结果
```

Polaris 负责：

- 工作流编译和图校验；
- 确定性的 ready-node 计算与调度；
- 节点和运行状态转换；
- 带类型的输入、输出和内容寻址 Artifact；
- 有界重试、超时和保守恢复；
- 副作用前后的持久化 Action Boundary；
- 验证 Gate 和 terminal 状态约束；
- 根据节点声明输入确定性地物化上下文。

Polaris 不负责：

- 工作流的业务含义或推荐形态；
- 自动发明或优化工作流；
- Agent 节点内部的推理策略；
- token 级上下文压缩、对话垃圾回收或模型缓存；
- 分布式调度或通用企业工作流平台。

## 工作流无关，不等于不理解执行语义

Polaris 不需要知道一个节点是在制定计划、修改 Rust、运行测试还是评审补丁，但它必须理解图的执行语义：节点类型、依赖、带类型的数据流、条件、重试策略、副作用、持久化和 terminal 结果。

同一个运行时应该能执行任何合法的 v1 DAG，而不包含硬编码的阶段名或特定工作流分支。

## Workflow IR

IR 是 Intermediate Representation（中间表示）：位于用户配置与运行时执行之间的规范化、带类型、不可变内部表示。

```text
人工编写的配置
        |
        v
Compiler + Validator
        |
        v
Workflow IR
        |
        v
Graph Executor
```

Compiler 解析引用、展开默认值、检查输入输出类型、把条件编译为受限 AST、分析图结构并生成稳定 IR 哈希。运行状态单独保存，任何节点都不能修改 IR。

## v1 内置节点类型

- `agent`：使用结构化 Task Contract 调用 Codex 或其他兼容 Agent Runtime；
- `command`：以 argv 形式执行本地命令，并限制输出和超时；
- `verifier`：针对 Artifact 产生机械或概率验证证据；
- `gate`：基于已持久化数据解释受限条件；
- `terminal`：在前置条件满足时提交声明的工作流结果。

Node Runner 只执行局部工作并返回结构化结果。它不能改写图、直接提交运行状态或宣布整个运行完成。

## 可靠性模型

Polaris 持久化 Workflow IR、append-only 事件、物化 RunState、节点 attempts、日志和 Artifacts。每个有副作用的 attempt 开始前，都会记录持久化 Action Boundary。

崩溃后，Polaris 将每个未完成 attempt 对账为以下之一：

- 能证明未执行，因此策略可以允许重试；
- 能证明已成功，因此可以提交原结果；
- 无法判定，因此节点进入 `AMBIGUOUS`，后续副作用停止并等待介入。

底层 Runner 无法提供证据时，Polaris 不声称 exactly-once 执行。

## Agent 上下文边界

对于 `agent` 节点，Polaris 根据节点定义、声明的 Artifacts、工作区身份、输出 Schema 和 attempt 策略构建 Task Contract。默认不会重放整个工作流历史。

Codex 等底层 Agent Runtime 继续负责模型上下文窗口、compaction、工具协议和推理行为。Polaris 负责跨节点数据路由、Artifact 身份、Observation 新鲜度和恢复。

## v1 范围

首个版本有意保持收敛：

- 单个本地前台运行；
- JSON 配置和 JSON Schema；
- 不可变、带类型的 IR；
- 按稳定顺序串行执行无环图；
- 五类内置节点；
- 带类型的 Artifact 和受限条件；
- 有界 timeout 和 retry 策略；
- append-only 事件、原子 checkpoint 和崩溃恢复；
- `validate`、`run`、`resume`、`inspect` CLI。

循环、动态扩图、并行 join、分布式 Runner、外部副作用、可视化工作流编辑和插件系统都是后续候选，不是 v1 承诺。

## 设计不变量

1. 配置拥有工作流；运行时不发明业务控制流。
2. 非法图在执行前失败。
3. 权威状态独立于模型上下文。
4. 只有 Executor 可以提交状态转换。
5. 跨节点数据通过带类型且经过完整性校验的 Artifacts 传递。
6. 重试和超时显式且有限。
7. 不确定副作用必须暴露为 `AMBIGUOUS`，不得静默重放。
8. 工作流只有经过明确验证的 terminal 节点才能完成。

## 文档

- [plan.md](plan.md)：产品范围、执行语义、实施任务和测试门槛的权威文档。
- [Polaris_Design_ZH_v0.2.md](Polaris_Design_ZH_v0.2.md)：详细中文设计论证和架构探索。
- [AGENTS.md](AGENTS.md)：贡献者和编码 Agent 的仓库规则。
