# Polaris

[English](README.md) | 简体中文

> 当前版本：`0.1.18`（开发中）

Polaris 是运行在 Coding Agent 宿主上的仓库原生工程工作流。它把需求、计划、实现、独立审查、验证和任务状态保存在 Git 仓库中，并通过确定性门禁防止需求漂移、证据过期和 Agent 自行宣布完成。

当前支持 Codex 与 Claude Code。完整产品与实现边界以 [plan.md](plan.md) 为准，操作细节见 [使用说明书](docs/USAGE.md)。

## 核心流程

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING → IMPLEMENTED
      → DOCS_SYNCED → REVIEWING → REVIEWED
      → VALIDATING → VERIFIED → CLOSED
```

- Work Item 冻结目标、范围和验收标准。
- 独立 Implementer 依据不可变 handoff 完成代码、测试和文档。
- 独立 Reviewer 审查需求符合性与工程质量。
- Validation 将每项验收标准绑定到可复现证据。
- `events.jsonl` 保存状态变更，`state.json` 是可重建投影。
- Review 和 Validation 绑定当前 Revision、Git commit 与 diff hash；内容变化会使旧证据失效。
- 只有 `transition_task.py` 能通过合法门禁写入 `VERIFIED` 或 `CLOSED`。

任务默认采用 `R1`。低风险机械修改可使用 `R0`；公共接口、持久化格式、架构边界、并发、安全或资源生命周期变更使用 `R2`。

## 快速开始

要求：Git、Python 3.10+，以及 Codex 或 Claude Code。Polaris 运行时仅使用 Python 标准库。

在 Polaris 源仓库安装 CLI，并 vendoring 到目标仓库：

```powershell
python -m pip install .
polaris vendor C:\path\to\target-repo
```

进入目标仓库，安装项目锁定版本并初始化：

```powershell
cd C:\path\to\target-repo
python -m pip install ./tools/polaris
polaris init-project
polaris doctor --repo .
```

将生成的 `.agents/`、`.claude/`、`tools/polaris/` 和 `.polaris/` 耐久文件提交到 Git。

从目标仓库根目录显式启动任务：

```text
# Codex
$engineering-task 为订单创建接口增加幂等保护，补充测试和文档。

# Claude Code
/engineering-task 为订单创建接口增加幂等保护，补充测试和文档。
```

普通请求不会自动进入 Polaris。工作流会先整理并展示 Work Item；用户确认目标、范围和验收标准后才会开始实现。

## 常用命令

```powershell
polaris doctor --repo .
polaris validate-project --repo .
polaris validate-task TASK-0001 --repo .
polaris recover TASK-0001 --repo .
```

CLI 还提供 `vendor`、`init-project`、`init-task`、`migrate` 和可选的 `code-intelligence` 配置入口。运行 `polaris --help` 或 `polaris <command> --help` 查看参数。

状态文件不得手工推进。内部 Workflow Skill 必须通过项目锁定的转换脚本执行合法事件：

```powershell
python tools/polaris/scripts/transition_task.py TASK-0001 <EVENT> --repo .
```

## v0.1 边界

Polaris v0.1 包含：

- 宿主原生 Skills 与声明式适配器；
- 仓库内 JSON Authority、Workflow 和恢复索引；
- 标准库实现的 Validator、handoff、迁移和恢复脚本；
- 只负责定位和分发脚本的薄 CLI；
- 可选、非阻断的外部 Code Intelligence Provider。

v0.1 不包含：

- daemon、scheduler、队列或后台服务；
- Dashboard、TUI、IDE 或独立 App；
- 数据库、向量库或 Polaris 自建的代码图服务；
- 自定义 Agent Runtime 或模型适配层；
- Task DAG、自动归档或跨任务调度；
- 自动 merge、push、发布或远程 CI 编排。

## 仓库结构

```text
skills/       宿主无关的 Workflow Skills
hosts/        Codex、Claude Code 适配器与 worker 定义
scripts/      可执行脚本及 internal 协议实现
schemas/      Authority 与 Artifact JSON Schema
templates/    项目和任务模板
workflow/     默认 Workflow 与迁移注册表
tests/        规则、门禁和跨平台测试
```

## 开发与验证

```powershell
python tests/run_tests.py
python -m unittest discover -s tests -v
python -m compileall -q polaris_cli.py scripts tests
```

贡献时必须保持标准库运行时、四空格 JSON、跨平台行为，并为每个新增或修改的门禁、状态转换和 Validator 规则补充测试。任务目录结构只在 `scripts/internal/task_layout.py` 中定义；模板正文只修改 `templates/task-sources/`，随后运行：

```powershell
python scripts/materialize_task_layout.py
```

## 文档

- [使用说明书](docs/USAGE.md)：接入、任务执行、恢复、升级和故障处理。
- [v0.1 实施计划](plan.md)：产品范围、Authority、Workflow、协议与里程碑。

## License

当前仓库尚未添加开源许可证。在许可证明确之前，请勿假定代码可以按任意开源协议再分发。
