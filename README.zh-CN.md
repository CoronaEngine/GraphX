# Polaris

[English](README.md) | 简体中文

> 当前协议版本：`0.1.21`（开发中）；Workflow 版本：`0.1.3`

Polaris 是运行在 Coding Agent 宿主上的仓库原生工程工作流。它把需求、计划、实现、独立审查、验证和任务状态保存在 Git 仓库中，并通过确定性门禁防止需求漂移、证据过期和 Agent 自行宣布完成。

当前支持 Codex 与 Claude Code。完整产品与实现边界以 [plan.md](plan.md) 为准，操作细节见 [使用说明书](docs/USAGE.md)。

## 核心流程

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING → REVIEWING → VALIDATING
                                                     ├─ R0/R1 → CLOSED
                                                     └─ R2 → VERIFIED → CLOSED
```

- Work Item 冻结目标、范围和验收标准。
- 独立 Implementer 在一个 `IMPLEMENTING` 阶段内依据不可变 handoff 完成代码、测试和文档。
- 独立 Reviewer 审查需求符合性与工程质量。
- Validation 将每项验收标准绑定到可复现证据。
- `events.jsonl` 保存状态变更，`state.json` 是可重建投影。
- Review 和 Validation 绑定当前 Revision、Git commit 与 diff hash；内容变化会使旧证据失效。
- R0/R1 通过 `PASS_AND_CLOSE` 原子校验并关闭；R2 保留 `VERIFIED` 等待最终 Human approval。
- 实时 Implementation 进度只是 ignored 的可选遥测，不参与耐久门禁。
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

## 可选 CodeGraph 上下文

唯一正式的 Code Intelligence Provider 是 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)。它是可选能力，永远不是 Workflow 门禁。仓库所有者（而不是 Polaris）在目标仓库中自行安装和初始化：

```text
codegraph install
codegraph init
polaris code-intelligence add codegraph --repo .
```

`codegraph init` 创建 `.codegraph/` marker。只有目标仓库已经有这个 marker 且项目策略允许时，Polaris 才会使用 CodeGraph；没有 marker 时直接使用源码和 Git，不生成阶段 record。只有实际执行 Provider `status`、`sync` 或 `explore` 操作时才写 Code Intelligence record。Polaris 只会读取 `status`、查询 `explore`，以及只在声明的阶段边界至多执行一次有界 `codegraph sync`；它绝不安装、初始化、启动、配置、重新配置、等待或管理 CodeGraph、watcher、daemon 或 MCP 配置。

CodeGraph 的 watcher 和连接时 reconciliation 是正常情况下的实时更新机制。Polaris 只记录检查时的有限结论：`CURRENT_AT_CHECK`、`PARTIAL_STALE`、`INDEX_STALE`、`NOT_VERIFIED` 或 `UNAVAILABLE`，不会宣称与 Git commit 精确一致。`PARTIAL_STALE` 会精确列出待同步文件：当前普通文件必须直接读取并记录 `READ_SOURCE`；已删除文件必须检查注册 subject 的 Git diff 并记录 `INSPECT_GIT_DIFF`。`INDEX_STALE` 或 `NOT_VERIFIED` 时，图只能作为导航线索，Agent 必须通过仓库搜索和 Git 证据记录 `SEARCH_SOURCE`。Provider 不可用、status 不可读或 sync 失败都不阻断阶段；Validation 不调用 CodeGraph，仍以源码、Git、构建、测试、静态检查和 Human Check 为准。

协议 `0.1.21` 新增项目级 Polaris CodeGraph 代理、Host Adapter v3 注册和可审计的 Code Intelligence record v3，Workflow 仍为 `0.1.3`。record v1/v2 仅作为不可变历史证据读取；新证据必须由保留的代理 bundle 投影为 v3。

## v0.1 边界

Polaris v0.1 包含：

- 宿主原生 Skills 与声明式适配器；
- 仓库内 JSON Authority、Workflow 和恢复索引；
- 标准库实现的 Validator、handoff、迁移和恢复脚本；
- 只负责定位和分发脚本的薄 CLI；
- 可选、非阻断的 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) 上下文。

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
