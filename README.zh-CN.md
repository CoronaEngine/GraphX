# GraphX

GraphX 是一个面向 Codex 的严格 Task Graph Executor。

```text
Workflow Config owns control.
GraphX validates and advances the graph.
Codex tasks perform semantic work.
```

[English README](README.md)

## 状态

GraphX Phase 1（语义冻结与 Python 工程骨架）已经实现。仓库现已包含严格封闭的 v1 边界模型、不可变 Config/IR/RunState 类型、canonicalization golden vectors 和可执行架构守卫。Compiler、Scheduler、持久化、MCP Server 与 Host 执行仍按后续阶段实施。

[plan.md](plan.md) 仍是产品范围、执行语义、实施顺序和发布门禁的唯一权威。Phase 1 的详细施工记录提供[英文版](docs/superpowers/plans/2026-09-05-phase-1-semantics-and-scaffold.md)和[中文版](docs/superpowers/plans/2026-09-05-phase-1-semantics-and-scaffold.zh-CN.md)。

## 手动运行测试

**VS Code 一键运行：**打开根目录的 [run_tests.py](run_tests.py)，点击右上角的“运行 Python 文件”按钮。入口自动使用项目 `.venv`，无需手动激活环境或切换目录，运行结果显示在终端。

在仓库根目录运行：

```bash
.venv/bin/python tests/run_tests.py
```

入口按文件分组，显示中文场景、简短参数名、PASS/FAIL、耗时和中文汇总。失败时保留 pytest 的断言详情、堆栈和退出码。

```bash
# 只运行 Phase 1 验收
.venv/bin/python tests/run_tests.py tests/unit/test_phase1_acceptance.py

# 按测试名称或参数名筛选
.venv/bin/python tests/run_tests.py -k task-too-long

# 原生 pytest 简洁模式
.venv/bin/python -m pytest -q
```

首次安装依赖、完整质量检查及新增用例约定见 [tests/README.md](tests/README.md)。激活虚拟环境后，也可直接使用 `python tests/run_tests.py`。目前测试验证 Phase 1 模型、协议和架构约束；完整工作流执行按后续阶段实现。

## GraphX 做什么

GraphX 负责：

- 校验声明式 Workflow Config；
- 编译不可变、带类型的 Workflow IR；
- 确定性地计算下一个 ready node；
- 派发节点并校验结构化结果；
- 将每个已绑定的 Agent attempt 精确映射到一个独立、可见的 Codex task；
- 串行执行所有 workspace mutation；
- 在 SQLite 中持久化运行状态、attempt、thread ID 和 mutation lease；
- 只通过经过校验的 terminal node 提交业务结果；运行也可能因操作性失败或取消而在没有业务结果时结束。

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
    -> 持久化 DispatchReservation
    -> 独立可见 Codex task
    -> 已绑定的 AgentAttempt 与已激活的 Task Contract
    -> 经过校验的 NodeResult
    -> 下一次 Graph 状态转换
```

Codex 总控任务展示 Graph 总体进度。GraphX 会先持久化 dispatch reservation，再要求 Host 创建外部 task；绑定成功时原子创建 `AgentAttempt` 及其不可变 task handle，激活后才开始语义工作。Retry 会创建新的 reservation、attempt 和 task。

`command`、`verifier` 等外部机械节点使用持久化 mechanical attempt 和 execution handle，不需要 Codex 对话。纯 `gate` 与 `terminal` 条件由 GraphX 内部求值。

## Mutation 规则

任何声明为 `workspaceMutation` 的节点都必须取得持久化、workspace-scoped mutation lease。初始 Executor 对每个 Run 同时最多允许一个外部执行；在共享同一 SQLite 控制存储的 GraphX 协调域内，每个规范化 workspace identity 同时最多允许一个 mutation lease。这不会阻止绕过 GraphX 的外部写入者。

前一个 mutation 未确认执行已静止（或被强证明从未存在）、未完成 workspace revision 对账，或配置的 settlement 要求尚未由合法的正常证据或等价恢复证据满足时，下一个 mutation 不能开始。因此 mutation node 可以已经成功，但其 lease 仍为等待结算而保留。不确定的 mutation 进入 `ambiguous`，绝不自动重放。

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
