# GraphX

GraphX 是一个面向 Codex 的严格 Task Graph Executor。

```text
Workflow Config owns control.
GraphX validates and advances the graph.
Codex tasks perform semantic work.
```

[English README](README.md)

## 状态

GraphX 正处于早期实施设计阶段。[plan.md](plan.md) 是产品范围、执行语义、实施顺序和发布门禁的唯一权威。

## GraphX 做什么

GraphX 负责：

- 校验声明式 Workflow Config；
- 编译不可变、带类型的 Workflow IR；
- 确定性地计算下一个 ready node；
- 派发节点并校验结构化结果；
- 将每个 Agent attempt 映射到独立、可见的 Codex task；
- 串行执行所有 workspace mutation；
- 在 SQLite 中持久化运行状态、attempt、thread ID 和 mutation lease；
- 只通过经过校验的 terminal node 结束运行。

GraphX 不负责：

- 发明或优化业务工作流；
- 亲自完成编码工作；
- 管理模型上下文、compaction 或对话历史；
- 重新实现 Codex 工具或 sandbox；
- 允许 Agent 改写 Graph 或宣布 Workflow 完成。

## 执行模型

```text
Codex 总控任务
    -> GraphX Skill
    -> 短事务 MCP 调用
    -> Python Graph Executor
    -> NodeDispatch
    -> Agent attempt 的独立可见 Codex task
    -> 经过校验的 NodeResult
    -> 下一次 Graph 状态转换
```

Codex 总控任务展示 Graph 总体进度。每个 `agent` attempt 都有自己的 Codex task 和持久化 thread ID。Retry 会创建新的 attempt 和新的 task。

`command`、`verifier`、`gate`、`terminal` 等机械节点不要求独立对话。

## Mutation 规则

任何声明为 `workspaceMutation` 的节点都必须取得持久化、workspace-scoped mutation lease。初始 Executor 每次只派发一个节点，因此 mutation Agent 和命令永远不会重叠。

前一个 mutation 未提交、未被证明没有执行或未得到明确裁决前，下一个 mutation 不能开始。不确定的 mutation 进入 `AMBIGUOUS`，绝不自动重放。

## 运行时校验

静态类型不能验证运行时数据。Workflow JSON、MCP 消息、Codex 结果、SQLite row 和恢复状态在检查前都不可信。

GraphX 使用四层防线：

1. JSON Schema 和严格边界模型；
2. Graph 语义校验；
3. 显式状态转换校验；
4. SQLite 约束和事务。

## Python 实现

初始实现使用：

- Python 3.12；
- Pyright strict；
- Ruff；
- pytest；
- strict Pydantic model 或等价 JSON Schema validator；
- 标准库 SQLite；
- Python MCP server 和 Codex Skill。

Python 包分为纯 `core`、负责编排用例的 `application`、不包含业务依赖的 wire `protocol` 和连接外部系统的 `adapters`。Service 依赖只能指向内层：Core 不执行 I/O，Application 不导入具体 Adapter，外部 Host 只依赖版本化 Protocol，只有 SQLite Adapter 可以打开连接或执行 SQL。

## 初始节点类型

- `agent`：派发一个独立、可见的 Codex task；
- `command`：要求 Host Adapter 执行声明的命令；
- `verifier`：产生结构化验证证据；
- `gate`：针对已持久化输出解释受限条件；
- `terminal`：提交声明的 Workflow 结果。

## 文档

- [plan.md](plan.md)：产品范围、架构、Python 实施计划和测试的权威文档。
- [AGENTS.md](AGENTS.md)：贡献者和编码 Agent 的仓库规则。
