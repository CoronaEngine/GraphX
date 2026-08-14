# Polaris

完整的首次接入、日常提需求、独立 Review、恢复与升级流程见 [Polaris 使用说明书](docs/USAGE.md)。

Polaris 是一套运行在 Codex 之上的、以仓库为权威状态的软件工程工作流系统。

它将模糊需求转换为冻结的 Work Item，通过声明式 Workflow、独立对抗审查、可复现验证和文档同步，约束 AI 按可审计、可恢复的工程流程工作。

Polaris 采用显式启用：普通工程需求不会自动进入 Polaris；用户必须在请求中主动调用 `$engineering-task`。其他阶段 Skills 同样禁止隐式调用，只能由已启动的工作流在合法节点分派。

> 当前版本：`0.1.1`（开发中）

## 核心目标

Polaris 希望让 AI 从“生成代码”转向“可靠参与软件工程”：

```text
用户意图
  → 需求资格审查与 Work Item
  → 架构规划与最小 Working Set
  → 实现与证据
  → 文档同步
  → 独立对抗 Review
  → 机械 Validation
  → CLOSED
```

核心原则：

- Graph 决定合法流程，Agent 只负责节点内执行。
- 聊天记录不是项目事实来源，权威状态保存在仓库中。
- JSON 是机械判定依据，Markdown 只提供人类可读投影。
- Agent 不能自行宣布完成；只有门禁全部满足后，转换脚本才能写入 `VERIFIED` 或 `CLOSED`。
- Review、Validation 与 Work Item Revision、Git commit 和 diff hash 绑定。
- 新会话不依赖旧聊天，可以从仓库恢复任务状态。
- 每个暂停点和阶段结果都用固定对话检查点展示，状态始终来自转换后的仓库 Authority。

## v0.1 边界

v0.1 是 Repo-native Skill System，由以下部分组成：

```text
Codex Skills
+ Repository Authority State
+ Deterministic Python Scripts
+ Codex Agent Runtime
```

v0.1 明确不实现：

- `polaris` CLI 或 shell wrapper
- daemon、watchdog、scheduler、队列或后台服务
- Dashboard、TUI、IDE 或独立 App
- 数据库、向量库或知识图谱服务
- 自定义 Agent Runtime 或模型适配层
- Task DAG、自动归档和跨任务调度
- 自动 merge、push、发布或远程 CI 编排

## 当前实现状态

已经实现：

- v0.1 JSON Authority 模型、Schema 和四空格格式化规范
- 前进、返工、阻塞、取消和新 Revision 的 Workflow Graph
- `R0 / R1 / R2` 渐进式严谨度和高风险双 Reviewer 规则
- 七个 Codex Workflow Skills
- Skills 和协议实现的目标仓库 vendoring
- 项目、任务和 Work Item Revision 初始化
- 状态转换、项目/任务校验、事件账本和状态重建
- Git subject commit/diff hash 绑定
- Documentation impact 检查
- R1 Review → Validation → Result → CLOSED 的机械闭环
- 不可变 Reviewer handoff、独立会话声明和三轮 Review 上限
- Review Response 与跨 Attempt 的稳定 Finding 生命周期
- Fresh-session Recovery、项目索引和可刷新 Working Set
- Failed Exploration 的任务内记录、项目级提升和按模块检索
- 固定字段的对话检查点、带推荐选项的澄清问题、Work Item 预览确认和验收占位符门禁
- 25 个带场景日志的自动化测试

仍在建设：

- Codex 宿主对 vendored Skills 的实际发现验证
- Horizon 和 Vision 真实项目试点
- Adversarial Review Yield 评估

完整范围和里程碑见 [plan.md](plan.md)。

## 仓库结构

```text
Polaris/
├── skills/                 # 七个 Workflow Skills 的源文件
├── scripts/                # 标准库实现的确定性辅助脚本
├── schemas/                # 权威 JSON 数据结构
├── templates/              # 项目和任务模板
├── workflow/               # 默认声明式 Workflow Graph
├── tests/                  # Fixtures、规则测试和日志运行器
├── AGENTS.md               # 本仓库 AI 工程规则
├── VERSION
└── plan.md                 # v0.1 产品与实施权威文档
```

接入目标仓库后：

```text
target-repo/
├── .agents/skills/         # vendored Codex Skills
├── tools/polaris/          # vendored、版本锁定的协议实现
└── .polaris/               # 项目和任务 Authority State
```

## 环境要求

- Git
- Python 3.10 或更高版本
- 支持仓库级 Skills 的 Codex 宿主环境

Polaris v0.1 的 Python 代码只使用标准库，不需要安装第三方依赖。

## 开发与验证

运行完整测试：

```powershell
python tests/run_tests.py
```

测试运行器会为每个场景打印：

- 测试名称与中文验证目标
- `RUN / PASS / FAIL / ERROR`
- 单项耗时
- 失败位置和完整堆栈
- 最终测试数量与机械结论

使用原生 `unittest` 输出：

```powershell
python -m unittest discover -s tests -v
```

检查 Python 语法：

```powershell
python -m compileall -q scripts tests
```

## 接入一个目标仓库

以下命令均从 Polaris 源仓库运行。它们是直接执行的 Python 脚本，不是 Polaris CLI。

### 1. Vendor Polaris

```powershell
python scripts/vendor_project.py C:\path\to\target-repo
```

该操作复制：

- `skills/` → `.agents/skills/`
- `scripts/`、`schemas/`、`templates/`、`workflow/` 和 `VERSION` → `tools/polaris/`

目标仓库已经存在 vendored 文件时，显式使用 `--force` 才会更新：

```powershell
python scripts/vendor_project.py C:\path\to\target-repo --force
```

### 2. 初始化项目状态

在目标仓库中运行：

```powershell
python tools/polaris/scripts/init_project.py my-project --repo .
```

这会创建 `.polaris/project.json`、冻结的 `.polaris/workflow.json` 和恢复索引；目标仓库没有 `AGENTS.md` 时还会创建最小仓库规则。

### 3. 初始化任务

```powershell
python tools/polaris/scripts/init_task.py TASK-0001 --rigor R1 --repo .
```

任务初始状态为 `DRAFT`。填写并冻结 `.polaris/tasks/TASK-0001/revisions/work-item-r001.json` 后，才能进入资格审查和后续阶段。

### 4. 校验项目和任务

```powershell
python tools/polaris/scripts/validate_project.py --repo .
python tools/polaris/scripts/validate_task.py TASK-0001 --repo .
```

统一退出码：

- `0`：PASS
- `1`：规则或门禁失败
- `2`：输入、环境或系统错误

所有脚本都支持 `--json`，便于由 Agent 或自动化程序读取结果。

### 5. 从新会话恢复

```powershell
python tools/polaris/scripts/recover_task.py TASK-0001 --repo . --json
```

恢复脚本先校验项目和任务，再只返回当前 Revision、状态与 blocker、最后事件、下一动作和最小 Working Set。它不读取聊天历史。

刷新 Working Set 时可以保留已有条目，或用 `--force` 重建自动条目：

```powershell
python tools/polaris/scripts/build_working_set.py TASK-0001 --repo . --entry "Code|src/module.py|affected entry point|dependency from AC-01"
```

### 6. 交接独立 Review

完成 Documentation Sync 后，在实现者会话中生成 handoff：

```powershell
python tools/polaris/scripts/build_review_handoff.py TASK-0001 --repo . --implementer-session-id impl-20260813 --isolation fresh_session
python tools/polaris/scripts/transition_task.py TASK-0001 START_REVIEW --repo . --artifact review_handoff=reviews/r001/handoff-001.json
```

R1/R2 到这里必须停止实现者会话。新建 Codex 会话，或启动不继承实现聊天的隔离 reviewer agent，只向它提供已注册的 handoff 路径，再使用 `$adversarial-review`。Review JSON 必须绑定 handoff，并如实记录隔离模式、聊天继承声明和不同的 Reviewer session ID。

Review 被拒绝后，实现者必须使用 `review-response.json` 模板逐项回复所有 open Finding，并在下一次 `FINISH_IMPLEMENTATION` 同时注册该响应。后续 Reviewer 必须保留 Finding ID、复查完整新 Patch 并填写 Reviewer resolution。第三次 Review 仍为 `REJECT` 时，任务自动进入 Human-owned `BLOCKED`。

Session ID 是审计声明，不是身份认证。如果宿主没有公开 ID，应在每个会话开始时生成一个不复用的稳定标识。

### 7. 记录失败探索

```powershell
python tools/polaris/scripts/record_exploration.py TASK-0001 --repo . --module src/module --hypothesis "假设" --attempt "尝试" --evidence "命令与结果" --outcome rejected --failed-because "原因" --retry-when "重试条件"
```

任务内结论默认保留在任务目录。确认可跨任务复用后，由 Documentation Sync 提升到项目级：

```powershell
python tools/polaris/scripts/record_exploration.py TASK-0001 --repo . --promote EXP-0001
```

## 任务生命周期

默认主路径：

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING → IMPLEMENTED
      → DOCS_SYNCED → REVIEWING → REVIEWED
      → VALIDATING → VERIFIED → CLOSED
```

同时支持：

- Review Reject 返回 `IMPLEMENTING`
- 第三次 Review Reject 进入 Human-owned `BLOCKED`
- Validation 实现失败返回 `IMPLEMENTING`
- Validation 计划失败返回 `PLANNED`
- 需求变化通过新 Revision 返回 `QUALIFIED`
- 任意非终态进入 `BLOCKED`
- Blocker 解除后返回 `blocked_from`
- Human 可以将非终态任务置为 `CANCELLED`

状态不得直接编辑，必须通过：

```powershell
python tools/polaris/scripts/transition_task.py TASK-0001 <EVENT> --repo .
```

合法事件、依赖产物和门禁以 `.polaris/workflow.json` 为准。

## 贡献约束

- 保持 Python 标准库实现，不引入运行时第三方依赖。
- JSON 使用 UTF-8、LF 和四空格缩进。
- 新增或修改门禁时必须补充自动化测试。
- 不得让 Skill 或 Agent 直接写入任务完成状态。
- 不提交 `__pycache__/`、虚拟环境、`.vscode/` 或任务锁文件。
- v0.1 不扩建 CLI、UI、服务进程或自定义 Agent Runtime。

## License

当前仓库尚未添加开源许可证。在许可证明确之前，请勿假定代码可以按任意开源协议再分发。
