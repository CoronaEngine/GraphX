# Polaris 使用说明书

本文面向希望在受支持 Coding Agent 宿主中使用 Polaris 管理软件工程任务的项目成员。当前内置 Codex 与 Claude Code 适配器；本文从首次接入讲到日常提出需求、独立 Implementation、进度查询、Review、验证、恢复与升级。

> 当前版本：v0.1.11。Polaris v0.1 是仓库原生的 Skills、宿主 worker 定义与 Python 脚本集合，不提供 `polaris` CLI、后台服务或图形界面。

## 1. 先理解 Polaris 保存什么

Polaris 把项目仓库作为权威事实来源：

- 宿主适配器声明的目录保存渲染后的 Polaris Skills 和可选 worker 定义；当前 Codex 使用 `.agents/skills/`，Claude Code 使用 `.claude/skills/` 与 `.claude/agents/`。
- `tools/polaris/` 保存当前项目锁定版本的协议、Schema、模板和 Python 脚本。
- `.polaris/` 保存项目配置、冻结工作流、任务状态、Work Item、计划、Review、Validation 和事件账本。
- 普通 Git 提交保存实际代码、测试和文档。

这些目录的耐久内容都应提交 Git。不要把 `.polaris/` 整体当作缓存，也不要只提交代码而漏掉任务记录。唯一例外是每个任务下的 `.polaris/tasks/<TASK>/runtime/`：它保存当前电脑上的实时 Implementation 进度，默认忽略，不参与阶段门禁。

Polaris 不保存以下瞬时状态：

- 未提交、未推送的文件修改；
- 编辑器窗口、断点和本地终端历史；
- Codex 或 Claude Code 完整聊天记录；
- 未写入任务产物的口头约定。
- `.polaris/tasks/<TASK>/runtime/` 中最后一次本机进度快照在其他电脑上的延续。

因此，“可恢复”是指从 Git 中恢复已提交的项目事实和任务状态，而不是还原另一台电脑上的整个桌面或聊天现场。

## 2. 环境要求

- Git；
- Python 3.10 或更高版本；
- Codex 或 Claude Code，并支持仓库级 Skills；
- 一个已经初始化 Git 的目标仓库；
- 能够从目标仓库根目录打开所选宿主。

Polaris v0.1 的运行时代码只使用 Python 标准库，不需要额外安装 Python 包。

## 3. 首次接入一个项目

### 3.1 将 Polaris vendoring 到目标仓库

在 Polaris 源仓库根目录运行：

```powershell
python scripts/vendor_project.py C:\path\to\target-repo
```

它会读取 `hosts/*/adapter.json` 并生成：

```text
target-repo/
├── .agents/skills/        # Polaris Skills
├── .claude/skills/        # Claude Code 语法的 Polaris Skills
├── .claude/agents/        # Claude Code Implementer/Reviewer
└── tools/polaris/         # 锁定版本的协议实现与 install-manifest.json
```

`skills/` 是宿主无关的单一来源。每个版本化适配器声明 Skill 目录、调用前缀、入口 frontmatter、可选 metadata/执行附录和宿主专用文件；vendoring、初始化与校验脚本遍历清单，不按 Codex 或 Claude Code 写分支。因而以后增加同类文件型宿主时，只需增加 `hosts/<host-id>/`，无需修改这三个核心流程。

如果目标仓库已经存在 vendored 文件，普通运行会拒绝覆盖。确认要升级后显式使用：

```powershell
python scripts/vendor_project.py C:\path\to\target-repo --force
```

首次安装会生成 `tools/polaris/install-manifest.json`。其中 `managed_files` 保存 Polaris 完全拥有的输出及其 SHA-256；`preserved_files` 保存由 Polaris 创建或要求存在、但内容归项目维护的文件，例如 `CLAUDE.md` 和 `.gitignore`。项目校验会拒绝受管文件缺失、内容漂移和必要输出未登记。

`--force` 会先按旧清单清除所有旧受管文件，因此新版已移除的 Skill、overlay、宿主文件或工具不会残留；它不会删除保留文件或清单外的项目配置。升级前应先确保工作区可识别，并在升级后查看 Git diff 和运行校验。旧安装没有清单时仍使用已知目标目录的兼容更新逻辑。

### 3.2 初始化项目 Authority State

进入目标仓库根目录：

```powershell
python tools/polaris/scripts/init_project.py my-project --repo .
```

该命令创建 `.polaris/project.json`、冻结的 `.polaris/workflow.json` 和结构化 `.polaris/project-index.json`；如果仓库没有 `AGENTS.md` 或 `CLAUDE.md`，还会创建对应的最小仓库规则。生成的 `CLAUDE.md` 通过 `@AGENTS.md` 导入共享规则，再补充 Claude Code 专用的 Skill 与非 fork worker 约束。初始化同时确保 `.gitignore` 包含 `.polaris/tasks/*/runtime/`。

校验初始化结果：

```powershell
python tools/polaris/scripts/validate_project.py --repo .
```

统一退出码为：

- `0`：PASS；
- `1`：规则或门禁失败；
- `2`：输入、环境或系统错误。

### 3.3 提交初始化结果

检查将要提交的文件：

```powershell
git status --short
```

通常应提交：

- 当前适配器生成的 `.agents/` 与 `.claude/` 内容；
- `tools/polaris/`；
- `.polaris/`；
- 初始化生成的 `AGENTS.md`、`CLAUDE.md`；
- 为 Polaris 补充的 `.gitignore` 规则。

示例：

```powershell
git add .agents .claude tools/polaris .polaris AGENTS.md CLAUDE.md .gitignore
git commit -m "Bootstrap Polaris workflow"
git push
```

如果某个列出的文件原本不存在，按实际情况从命令中删除。不要使用会覆盖未提交工作的清理命令。

建议忽略的只是瞬时文件，例如：

```gitignore
__pycache__/
*.py[cod]
.venv/
.vscode/
.pytest_cache/
.coverage
.transition.lock
.polaris/tasks/*/runtime/
```

### 3.4 让 Codex 发现 Skills

vendoring 和首次提交完成后，从目标仓库根目录新开一个 Codex 任务。仓库级 Skills 通常在任务启动时发现，因此不要假定一个在 vendoring 之前已打开的旧任务会自动刷新能力列表。

可用一个低风险请求验证发现，例如：

```text
请使用 $engineering-task 检查这个仓库是否已经正确接入 Polaris；只检查，不修改代码。
```

如果 Codex 能读取 `.agents/skills/engineering-task/SKILL.md` 并按 Polaris 状态恢复或说明当前没有任务，说明发现链路正常。

### 3.5 让 Claude Code 发现 Skills

从目标仓库根目录启动 Claude Code。项目 Skill 位于 `.claude/skills/<name>/SKILL.md`，通过 `/name` 调用；如果 vendoring 时 `.claude/skills/` 尚不存在，建议重启当前 Claude Code 会话以确保目录被监听。

可用同样的低风险请求验证：

```text
/engineering-task 检查这个仓库是否已经正确接入 Polaris；只检查，不修改代码。
```

Claude Code 应加载 `.claude/skills/engineering-task/SKILL.md`。R1/R2 Implementation 与 Review 分别使用 `.claude/agents/polaris-implementer.md` 和 `polaris-reviewer.md`；它们是非 fork subagent，共享当前 checkout，但不继承主聊天或实现聊天。

### 3.6 添加新的宿主适配器（维护者）

1. 新建 `hosts/<host-id>/adapter.json`，使用 `adapter_version: 2`，并按 `schemas/host-adapter.schema.json` 声明 Skill 目标、调用前缀、真实入口、能力、入口 frontmatter、overlay、appendix 与专用文件。
2. `capabilities` 必须显式声明 `structured_user_input / worker_create / worker_status / worker_resume / stable_worker_identity`。`worker_status` 和稳定身份依赖 worker 创建；续接同时依赖创建与稳定身份。声明可创建 worker 的宿主必须提供入口 Skill appendix，写清创建、身份、查询和续接机制。
3. 只把宿主能力差异放入该目录：metadata 放在 overlay，worker 创建/身份/等待/续接规则放在 `skill-appendices/engineering-task.md`，原生 agent 或仓库规则放在 `files` 清单中。
4. 不要在共享 `skills/`、Workflow、Authority schema 或三个生命周期脚本中新增宿主名分支。共享 Skill 引用另一 Skill 时使用 `{{skill:<name>}}`。
5. 运行完整测试，并在真实宿主中 smoke test 入口发现、显式触发边界、隔离 worker、handoff 拒绝和同一 Implementer 续接 Documentation Sync。

`entry_skill` 必须对应 canonical `skills/<name>/SKILL.md`。Overlay 只能在已知 Skill 下增加 canonical 源中不存在的普通文件，不能提供 `SKILL.md`、覆盖任何同路径内容或包含未知 Skill；appendix 也只能使用 `<installed-skill>.md`。适配器源树、manifest、overlay、appendix、专用源文件和目标写入路径都禁止 symlink，所有目标必须留在仓库内。不同宿主不能声明重叠目标。若新宿主无法用 v2 的“文件复制 + Skill 渲染 + 能力声明 + 执行附录”表达，应先升级适配器契约，而不是在核心脚本里写例外。

## 4. Polaris 仓库自举

Polaris 源仓库也可以选择用 Polaris 管理，但自举不是默认状态。只有仓库中存在宿主 Skills、`tools/polaris/` 和 `.polaris/` 时，才表示当前源仓库已经完成自举。

自举与普通目标项目的差别只有来源位置：

- 开发 vendoring 工具本身时，共享源文件位于 `skills/`、`scripts/`、`schemas/`、`templates/` 和 `workflow/`，宿主差异位于 `hosts/<host-id>/`；`scripts/internal/task_layout.py` 是任务相对路径的唯一权威，平铺的 `templates/task-sources/` 只保存模板正文，`templates/task/` 是 `scripts/materialize_task_layout.py` 生成的样例投影，禁止手改；
- 执行本仓库任务时，使用所选宿主已锁定的 Skills 与 `tools/polaris/`；
- 修改源实现后，需要按版本升级流程重新 vendoring，确认两份内容一致。

目录结构变更只修改 `scripts/internal/task_layout.py`，模板正文只修改平铺的
`templates/task-sources/`。开发仓库运行
`python scripts/materialize_task_layout.py` 后会重建并校验
`templates/task/`；任务初始化、新 Revision 和 vendoring 调用同一个物化模块，
因此模板目录与真实任务目录不会分别维护。

## 5. 每次提出需求之前

用户不需要手工创建任务 JSON。先把仓库准备到可判断状态，再显式调用 `$engineering-task`（Codex）或 `/engineering-task`（Claude Code）。普通自然语言工程请求不会自动进入 Polaris。

### 5.1 同步仓库

```powershell
git pull --ff-only
git status --short
```

目标不是强求工作区绝对干净，而是确保每一项已有修改都能说明来源：

- 如果是你希望保留的工作，先提交或明确告诉当前 Agent 这些文件不可覆盖；
- 如果是另一个任务的工作，不要与新需求混在同一工作区；
- 如果看到不认识的修改，先停下来确认，不要直接 reset 或删除；
- 确保当前分支和远端符合你的预期。

### 5.2 校验 Polaris

```powershell
python tools/polaris/scripts/validate_project.py --repo .
```

如果已有进行中的任务，再运行：

```powershell
python tools/polaris/scripts/recover_task.py TASK-0001 --repo . --json
```

恢复结果会给出当前 Revision、状态、blocker、最近事件、下一动作和来自 `working-set.json` 的最小 Working Set。先续办已有任务还是创建新任务，应根据恢复结果决定。

### 5.3 从正确位置打开 Agent 宿主

- 工作目录应是目标仓库根目录；
- 最好在 vendoring 后新开的 Codex 任务或 Claude Code 会话中工作；
- 确认宿主能发现 `engineering-task` 等仓库 Skills；
- 准备使用 Polaris 时，在 Codex 请求中明确写出 `$engineering-task`，或在 Claude Code 中调用 `/engineering-task`；
- 如果是 R1/R2 Review，不要复用 Implementer 会话，具体见第 10 节。

### 5.4 准备需求信息

提出需求前，尽量想清楚：

- 想得到什么结果，以及为什么；
- 哪些内容必须做，哪些明确不做；
- 兼容性、性能、安全、时间或技术限制；
- 怎样判断完成；
- 是否允许改公共接口、数据格式、依赖、部署或架构；
- 哪些产品取舍、风险接受或破坏性操作必须由人决定。

信息不完整也可以提出需求。Polaris 的 `requirement-analysis` 会把未知项显式化；但涉及产品取舍、不可逆迁移、权限扩大、风险接受等 Human-owned 决策时，Agent 不应替用户猜测。

## 6. 如何提出一个好需求

推荐模板：

```text
请使用 $engineering-task 完成以下工程任务。

目标：
背景/动机：
必须包含：
明确不包含：
约束：
验收方式：
允许修改的范围：
需要我决定的事项：
```

Claude Code 使用相同正文，但首行改为 `/engineering-task 完成以下工程任务。`。

示例：

```text
请使用 $engineering-task 为订单查询接口增加分页。

目标：列表接口支持 page 和 page_size，并返回总数。
背景：当前一次返回全部订单，数据量增长后响应过慢。
必须包含：参数校验、默认值、接口测试、API 文档更新。
明确不包含：前端页面和数据库迁移。
约束：保持现有未传分页参数的调用兼容；page_size 最大为 100。
验收方式：旧测试通过；新增正常分页、边界值和错误参数测试。
允许修改的范围：订单 API、查询层、对应测试和文档。
需要我决定的事项：如果兼容性与性能目标冲突，先让我选择。
```

不必在需求中手写任务状态、Revision、Review JSON 或 transition 命令。显式调用后，让宿主的 `engineering-task` Skill 负责选择相应阶段和合法状态转换。

如果用户只说“给订单接口增加分页”，宿主会按普通工程请求处理，不会进入 Polaris。只有显式调用 `$engineering-task`（Codex）或 `/engineering-task`（Claude Code），才表示用户选择启用 Polaris 工作流。其余阶段 Skills 由已启动的入口 Skill 按状态节点分派；不要把阶段 Skill 当成另一个入口。

## 7. 提出需求后会发生什么

### 7.1 固定的对话检查点

Polaris 每次暂停、等待用户决定或完成一个阶段时，都会在对话框中输出一个固定状态块。首行格式为：

```text
[POLARIS:<MARKER>]
```

后续字段顺序固定为 `Task / Revision / Rigor / State / Outcome / Authority / Remaining / Next / User action`。没有内容的字段显示 `None`，不会被省略。`State` 必须来自最近一次成功转换后重新读取的仓库状态，不能提前宣布下一状态。

常见标记包括：

- `REQUIREMENTS_NEEDED`：需求仍有会影响方案或验收的未知项；
- `WORK_ITEM_PREVIEW`：Work Item 已整理好，等待用户确认冻结；
- `WORK_ITEM_QUALIFIED`、`PLAN_READY`、`IMPLEMENTATION_FINISHED`、`DOCS_SYNCED`：阶段检查点；
- `IMPLEMENTATION_HANDOFF_READY`：独立实现输入已冻结并注册；
- `IMPLEMENTATION_SESSION_STARTED`：宿主已创建或复用独立 Implementer 任务；
- `IMPLEMENTATION_PROGRESS`：展示最近有效的本机实现进度，不使用估算百分比；
- `REVIEW_HANDOFF_READY`：handoff 已冻结；宿主无法自动派发时显示完整的手动新任务提示；
- `REVIEW_SESSION_STARTED`：宿主已创建或复用独立 Review 任务，主任务正在等待；
- `REVIEW_ACCEPTED` / `REVIEW_REJECTED`、`VALIDATION_PASS` / `VALIDATION_FAIL`：审查与验证结论；
- `TASK_BLOCKED`：给出 blocker、Decision Owner 和解除条件；
- `TASK_CLOSED`：仅在转换脚本确实写入 `CLOSED` 后显示。

需求信息不完整时，`requirement-analysis` 每轮只问一到三个会实质影响结果的问题。每个问题会提供两到三个互斥选项，把推荐选项放在第一位，并逐项说明影响；如果选项都不合适，用户仍可直接给出精确答案。宿主提供 `request_user_input` 等结构化交互工具时，Polaris 优先在对话框中弹出选择面板；工具不可调用时，自动回退为内容相同的文本选项，不会为获得面板而自行切换模式或中断任务。

无论通过面板还是文本回答，答案都会写入相同的 Work Item 字段，未回答项会写入 `known_unknowns`，任务停留在 `DRAFT`。信息完整后，无论原始需求多详细，Polaris 都会先展示 `WORK_ITEM_PREVIEW`，列出目标、范围、约束、严谨度、风险、所有验收标准及证据方式，然后等待用户明确确认。确认时同样优先显示“确认并执行（推荐）/要求修改”的选择面板；说明文字明确告知：确认会冻结 Work Item，并授权 Polaris 在同一本地项目中自动创建本 revision 所需的全部独立 Implementer / Review 任务和后续 attempts。授权分别写入 `implementation_dispatch.authorized=true` 与 `review_dispatch.authorized=true`；新 Revision 会把两者重置为 `false` 并要求重新确认。未确认时不得进入 `QUALIFIED`，也不得创建 Worker 任务。

询问示例：

```text
1. 未传分页参数时，接口应采用哪种兼容行为？
   - A. 保持原有全量返回（推荐）——兼容性最好，但旧调用仍可能返回大量数据。
   - B. 自动使用默认分页——性能更稳定，但会改变旧调用的响应语义。
   - C. 拒绝未分页请求——约束最严格，但属于明显的破坏性变更。
   如果以上均不符合，可以直接说明期望的兼容规则。
```

选择面板是宿主能力，不是 Polaris 自定义 UI。当前会话没有提供该工具时，看到上述文本选项属于正常回退行为；它与面板回答具有相同的流程效力。

例如：

```text
[POLARIS:WORK_ITEM_PREVIEW]
Task: TASK-0001
Revision: r001
Rigor: R1
State: DRAFT
Outcome: Work Item 草案已完整，等待冻结确认
Authority: .polaris/tasks/TASK-0001/revisions/work-item-r001.json
Remaining: None
Next: QUALIFY
User action: 请选择“确认并执行”以冻结上述内容并授权自动创建所需的独立 Implementer / Review 任务；如需修改请逐项指出
```

用户确认后，Polaris 校验 JSON、执行转换、重新读取状态，再输出 `WORK_ITEM_QUALIFIED`。后续若目标、范围、硬约束或验收标准发生实质变化，必须创建新 Revision 并重新确认，不能静默覆盖已冻结内容。

### 7.2 状态主路径

默认主路径是：

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING → IMPLEMENTED
      → DOCS_SYNCED → REVIEWING → REVIEWED
      → VALIDATING → VERIFIED → CLOSED
```

各阶段含义：

1. `DRAFT`：把自然语言需求整理成 Work Item。
2. `QUALIFIED`：目标、范围、约束、验收证据、风险和决策所有者已冻结。
3. `PLANNED`：形成结构化 `working-set.json`、变更计划和验收映射。
4. `IMPLEMENTING`：在冻结范围内修改并运行局部检查。
5. `IMPLEMENTED`：已有 subject checkpoint commit 和实现证据。
6. `DOCS_SYNCED`：文档影响已分类，过时知识已处理。
7. `REVIEWING`：Reviewer 仅依据冻结 handoff 独立审查。
8. `REVIEWED`：Review 已接受。
9. `VALIDATING`：逐条机械验证验收标准。
10. `VERIFIED`：所有验收项 PASS。
11. `CLOSED`：结果产物齐全，任务关闭。

任务状态不得直接编辑。状态转换必须通过：

```powershell
python tools/polaris/scripts/transition_task.py TASK-0001 <EVENT> --repo .
```

合法事件、依赖产物和门禁以目标仓库冻结的 `.polaris/workflow.json` 为准。

## 8. R0、R1、R2 与用户参与点

Polaris 根据风险选择严谨度：

- `R0`：低风险、小范围、易回退的变更；宿主支持时仍使用独立 Implementer，但不要求独立 Reviewer，可在主任务做明确隔离的审查 pass。
- `R1`：常规非平凡工程变更；独立 Implementer 加至少一个独立 Reviewer，宿主支持时自动创建可见新任务。
- `R2`：高风险变更；独立 Implementer、Human 预批准和最终批准，并至少一个独立 Reviewer。安全、持久化格式或不可逆迁移等风险还可能要求两个 Reviewer。

用户通常在这些位置参与：

- Work Item 冻结前确认产品目标、范围和验收口径；
- R2 开始实现前进行预批准；
- 决定破坏性操作、不可逆迁移、权限扩大和风险接受；
- 任务进入 `BLOCKED` 时提供决定或外部条件；
- R2 关闭前进行最终批准；
- 需要时取消任务或要求新 Revision。

如果实现期间目标或范围改变，不应悄悄修改原 Work Item。应创建新 Revision，并让任务回到 `QUALIFIED` 重新规划。

## 9. 独立 Implementation 与随时查看进度

主任务在完成 Planning 和所需预批准后：

1. 执行 `START_IMPLEMENTATION`；
2. 生成不可变 `implementations/rNNN/handoff-NNN.json`；
3. 通过 `DISPATCH_IMPLEMENTATION` 注册 handoff；
4. 在同一本地项目和同一 checkout 创建独立 Implementer 任务；
5. 等待并验证 Implementation artifact，由主任务执行 `FINISH_IMPLEMENTATION`；
6. 续接同一个 Implementer 任务完成 Documentation Sync，再由主任务执行 `SYNC_DOCS`。

自动 Implementer 标题固定为：

```text
Polaris Implement · TASK-0001 · r001 · attempt 1
```

Implementer 只接收 task ID 和已注册 handoff，不继承主任务聊天。它可以修改本次 subject 范围内的代码、测试、构建配置和项目文档，但不能运行状态转换、执行 Review/Validation 或关闭任务。Implementation JSON 必须绑定 handoff path/hash 和 Implementer session ID；未绑定的结果会被门禁拒绝。

### 9.1 不发消息也能查看

直接打开下面的四格缩进 JSON 文件：

```text
.polaris/tasks/TASK-0001/runtime/progress.json
```

它保存当前 phase、有序 `implementation_steps`、最近检查、blocker、用户动作和更新时间，也是这份本机快照的机械权威。每个步骤都有稳定 `STEP-NNN`、标题、状态、关联的 Work Item 验收 ID 和终态结果。当前、已完成和剩余工作由这一个列表推导，不能跳步或回退；发现新工作时只能追加。Implementer 通过明确事件更新它，Polaris 不根据耗时猜测百分比，也不生成内容重复的 Markdown 文件。

这个目录默认加入 `.gitignore`，因此不会污染工作树，也不会随 Git 在另一台电脑继续。换电脑后，耐久状态仍能恢复到最近 checkpoint；新 Implementer 会创建新的本机进度快照。

### 9.2 其他查看方式

- 在主任务询问“展示 TASK-0001 当前进度并继续”，主任务会验证 `progress.json` 后输出 `IMPLEMENTATION_PROGRESS`，不会取消或重复派发 Worker；
- 在支持任务列表的 Codex 宿主中，点击确定性标题的 Implementer 任务查看它的实时输出；
- 在 Claude Code 中通过 subagent/task 面板查看 `polaris-implementer`，主任务以返回的 agent ID 续接同一 worker；
- 新主任务恢复时，`recover_task.py` 会在存在有效快照时返回 `live_implementation_progress`。

宿主无法创建、查找、等待或续接任务时，Polaris 使用同一个 handoff 在主任务中执行，`Dispatch mode` 显示 `same_session_fallback`。流程仍可完成并继续写进度，但主任务正在执行长操作时，状态回答可能延迟。

如果 Implementer 遇到权限、凭据、外部依赖或必须由 Human 决定的问题，进度会进入 `BLOCKED` 并同时填写 `blocker` 与 `user_action`；主任务据此告诉用户需要处理什么。

## 10. 独立 Review：自动 worker 与手动回退

实现和 Documentation Sync 完成后，由主任务根据 Implementer 的最终产物生成冻结 handoff：

```powershell
python tools/polaris/scripts/build_review_handoff.py TASK-0001 --repo . --implementer-session-id impl-20260813 --isolation fresh_session
python tools/polaris/scripts/transition_task.py TASK-0001 START_REVIEW --repo . --artifact review_handoff=reviews/r001/handoff-001.json
```

然后按严谨度处理：

- `R0`：允许同一会话执行明确隔离的审查 pass，handoff 使用 `r0_isolated_same_session`；
- `R1/R2`：Implementer 到这里停止工作；主任务只负责派发、等待、重读仓库 Authority 和执行机械转换；
- Codex 在同一本地项目中自动创建可见的新 Review 任务；Claude Code 创建非 fork `polaris-reviewer` subagent 并记录其 agent ID；两者都不继承 Implementer 对话，也不默认使用独立 worktree；
- 新 Reviewer 只接收已注册 handoff 路径，使用 `adversarial-review`，先查规格符合性，再查工程质量；
- Reviewer session ID 必须与实现者不同，并如实记录隔离方式和聊天继承声明。

自动任务标题固定为：

```text
Polaris Review · TASK-0001 · r001 · attempt 1 · reviewer 1
```

创建前会先查找该 slot 已存在的有效 Review artifact；Codex 再查找唯一同名任务，Claude Code 在当前主会话中复用已知 agent ID，因此恢复或等待中断不会正常地产生重复 Review worker。启动后主对话显示 `REVIEW_SESSION_STARTED`，其中包括 Review task/agent ID、Reviewer slot、handoff、dispatch mode，并在 Reviewer 执行期间显示 `User action: None`。

高风险 R2 的两个 Reviewer 按顺序启动，且 session ID 必须不同。任一 Reviewer `REJECT` 后不再启动本轮剩余 Reviewer；全部 `ACCEPT` 后，原 `engineering-task` 会话注册 `review`/`review_2` 并执行 `ACCEPT_REVIEW`。Reviewer 只写不可变 Review JSON，不修改实现，也不直接推进状态机。

如果宿主没有创建、列出或等待 worker 的能力，或者自动派发失败，Polaris 不会因此把业务任务写成 `BLOCKED`，而是保持 `REVIEWING`、显示 `REVIEW_HANDOFF_READY`，并给出手动新会话提示。完成手动 Review 后，回到原任务并用宿主入口从仓库恢复继续。

给新 Review 任务的请求可以是：

```text
请使用 $adversarial-review 独立审查 TASK-0001，Reviewer slot 1。
只依据 .polaris/tasks/TASK-0001/reviews/r001/handoff-001.json，不继承或假设主任务、Implementer 会话中的结论。
写入不可变 Review JSON 后返回 verdict 和路径，不要修改实现或执行状态转换。
```

在 Claude Code 手动新会话中，将 `$adversarial-review` 改为 `/adversarial-review`。

Session ID 是审计声明，不是身份认证。如果宿主没有提供 ID，每个会话开始时应生成一个不复用的稳定标识。

如果 Review 拒绝：

1. 任务返回 `IMPLEMENTING`；
2. 实现者用不可变 `review-response.json` 逐项回应全部 open Finding；
3. 新 subject 和响应一起注册，再生成下一份 handoff；
4. Reviewer 保留 Finding ID，复查完整新 patch，并填写 resolution；
5. 第三次 Review 仍为 `REJECT` 时，状态机会把任务送入 Human-owned `BLOCKED`，不能继续自动循环。

正常 R1 happy path 中，用户确认 Work Item 后不再需要手工创建 Implementer/Review 任务或向它们发送消息。R2 仍保留实施前批准和最终批准；权限请求、Human-owned 决策、Review 手动回退或 `TASK_BLOCKED` 会产生额外交互。

## 11. 恢复工作

### 11.1 同一电脑的新宿主会话

在仓库根目录运行：

```powershell
python tools/polaris/scripts/validate_project.py --repo .
python tools/polaris/scripts/recover_task.py TASK-0001 --repo . --json
```

然后告诉 Codex，或在 Claude Code 使用对应的 slash 语法：

```text
请使用 $engineering-task 从 .polaris 恢复并继续 TASK-0001。
```

宿主应根据当前状态加载对应 Skill，而不是从聊天记忆猜测下一步。

### 11.2 换一台电脑

旧电脑离开前：

```powershell
git status --short
git add <本次需要保存的代码、文档和 .polaris 产物>
git commit -m "Checkpoint current Polaris task"
git push
```

新电脑上：

```powershell
git clone <repository-url>
cd <repository-directory>
python tools/polaris/scripts/validate_project.py --repo .
python tools/polaris/scripts/recover_task.py TASK-0001 --repo . --json
```

再从仓库根目录新开 Codex 任务或 Claude Code 会话并请求恢复。只要宿主 Skills/agents、`tools/polaris/`、`.polaris/` 的耐久产物和 subject commits 都已提交并推送，就能恢复权威工作状态；ignored 的任务内 `runtime/` 会在继续实现时重新生成。

无法通过 Git 恢复的内容包括：旧电脑上未提交/未推送的文件、编辑器状态和完整聊天记录。重要决定应写入 Work Item、Plan、Review Response、Knowledge Delta 或 Result，而不是只留在对话里。

## 12. 更新项目中的 Polaris

升级必须从干净、已提交的目标仓库开始，并把 vendoring 与 Authority State 迁移视为同一个可审查变更。先比较源版本与目标项目的 `.polaris/project.json` / `.polaris/workflow.json`，再从新版 Polaris 源仓库运行：

```powershell
python scripts/vendor_project.py C:\path\to\target-repo --force
```

如果 `.polaris/project.json` 的版本已经等于新 `VERSION`，无需迁移。否则进入目标仓库，执行且只执行 vendored 新版本提供的迁移脚本：

```powershell
python tools/polaris/scripts/migrate_project.py --repo .
```

迁移协议具有以下固定规则：

1. `workflow/migrations.json` 是支持路径的唯一、append-only 注册表；历史步骤必须保留，以便校验已提交的迁移记录。一次命令只允许从当前项目版本迁移到 vendored 版本的一个显式相邻步骤，不推断、不跨级。
2. 注册步骤同时绑定源/目标 `polaris_version` 与 `workflow_version`。v1 迁移策略不改变冻结 workflow；需要改变 workflow 时必须先升级迁移协议和策略实现。
3. 项目版本由 `replace_version` 策略更新；每个现有任务由 `append_version_event` 策略追加同状态的 `MIGRATE_POLARIS` 事件，旧 `events.jsonl` 行不可修改。
4. `.polaris/migrations/MIG-<from>-to-<to>.json` 先写为 `IN_PROGRESS`，全部投影更新后改为 `COMPLETED`。迁移锁会记录迁移/任务身份、主机名和 PID；若进程在中间终止，同一主机重新执行命令会接管已死亡的同迁移锁、验证并复用已经追加的事件，不会重复迁移。活跃进程、其他迁移或来源不明的锁不会被自动删除。
5. 迁移完成后脚本自动运行项目校验；`validate_project.py` 会拒绝未完成记录、缺失/伪造的任务迁移事件或版本不一致。

没有注册路径时不要手改版本号。应先取得包含所需相邻步骤的 Polaris 版本，逐级完成并分别提交；任何失败都先保留 `.polaris/migrations/` 和事件现场，修复原因后重跑同一迁移命令。

从 vendoring 完成到迁移完成之间，所有正常写命令都会拒绝执行，包括新建任务、状态转换、生成 handoff、更新 Working Set/进度、记录探索和刷新索引。这是防止新工具向旧 Authority State 写入混合版本数据的硬门禁，不应绕过。

然后检查：

```powershell
git status --short
git diff -- .agents/skills .claude/skills .claude/agents tools/polaris
python tools/polaris/scripts/validate_project.py --repo .
```

确认差异后，把宿主 Skills/agents、`tools/polaris/`、安装清单以及 `.polaris/` 迁移记录/事件放在同一个升级提交中。已初始化项目的 `.polaris/workflow.json` 是冻结工作流；不要因为 vendoring 升级就手工覆盖它。v0.1.2 新增 `DISPATCH_IMPLEMENTATION`；v0.1.3 使用结构化恢复索引；v0.1.4 使用线性 `implementation_steps`；v0.1.5 镜像任务模板目录；v0.1.6 集中任务路径；v0.1.7 引入声明式宿主适配器；v0.1.8 补齐有限 Schema 子集；v0.1.9 引入安装清单；v0.1.10 引入显式相邻迁移协议；v0.1.11 加固 Adapter v2。Workflow 版本仍为 v0.1.2。

早期 v0.1 已冻结的 Work Item 可能没有 `implementation_dispatch` 或 `review_dispatch`。缺少前者的旧任务只能使用同会话 Implementation，缺少后者的旧任务只能使用手动 Review handoff；Polaris 不会把缺失字段解释为自动创建授权。创建新 Revision 后会生成两组 `authorized=false` 字段，用户再次“确认并执行”后才启用自动 Worker 任务。

## 13. 失败探索与卡点

如果一个技术方向被证据否定，不要让结论只留在聊天中。记录任务内探索：

```powershell
python tools/polaris/scripts/record_exploration.py TASK-0001 --repo . --module src/module --hypothesis "假设" --attempt "尝试" --evidence "命令与结果" --outcome rejected --failed-because "失败原因" --retry-when "可重试条件"
```

确认结论可跨任务复用后，再由 Documentation Sync 提升为项目级知识：

```powershell
python tools/polaris/scripts/record_exploration.py TASK-0001 --repo . --promote EXP-0001
```

遇到需要用户决策、外部权限或环境变化的卡点时，应记录 blocker 并进入 `BLOCKED`，而不是伪造 PASS 或无限重试。

## 14. 常见问题

### Codex 没有发现 Polaris Skills

1. 确认当前目录是仓库根目录；
2. 确认 `.agents/skills/engineering-task/SKILL.md` 存在；
3. 确认这些文件已在当前分支中，而不是只存在于另一台电脑；
4. vendoring 后新开一个 Codex 任务；
5. 检查仓库规则是否禁止加载或覆盖 Skills。

### Claude Code 没有发现 Polaris Skills

1. 确认从仓库根目录启动；
2. 确认 `.claude/skills/engineering-task/SKILL.md` 存在；
3. 运行 `/skills` 检查项目 Skill；
4. 如果 vendoring 前 `.claude/skills/` 不存在，重启 Claude Code；
5. 使用 `/engineering-task`，而不是 Codex 的 `$engineering-task`。

### `init_project.py` 报项目已存在

不要重复初始化。先运行 `validate_project.py`；如果项目已经接入，直接恢复或创建任务。

### vendoring 拒绝覆盖

这是防止误覆盖。先提交或备份现有修改、查看来源版本，确认升级后再使用 `--force`。

### 工作区不干净，还能提需求吗

可以，但必须能识别已有修改，并明确哪些属于用户、其他任务或本次任务。Polaris 不要求为了“干净”而删除有价值的工作。

### 可以手改 `.polaris/tasks/.../state.json` 吗

不可以。JSON 是机器权威状态，必须由确定性脚本通过门禁写入。手改会破坏事件账本、产物绑定或恢复能力。

### 为什么已经实现，还不能说完成

`IMPLEMENTED` 只表示实现 checkpoint 已形成。还需 Documentation Sync、Review、Validation 和 Result 门禁，状态机才能写入 `CLOSED`。

### 自动化脚本如何被其他工具读取

所有脚本都支持 `--json`。日志面向人阅读，JSON 结果和退出码用于机械判断。

## 15. 最短日常清单

提出新需求前：

```text
[ ] 已同步正确分支
[ ] git status 中每项修改都可解释
[ ] validate_project PASS
[ ] 已从仓库根目录打开新的或合适的 Codex 任务 / Claude Code 会话
[ ] 宿主能发现 engineering-task
[ ] 已显式调用 $engineering-task（Codex）或 /engineering-task（Claude Code）
[ ] 已说明目标、范围、约束、验收和 Human-owned 决策
```

暂停或换电脑前：

```text
[ ] 代码、文档和 .polaris 任务产物已形成一致 checkpoint
[ ] 重要决定没有只留在聊天中
[ ] 已提交并推送
[ ] 新环境可运行 validate_project 和 recover_task
```

Implementation 期间查看进度：

```text
[ ] 优先打开 .polaris/tasks/TASK-NNNN/runtime/progress.json
[ ] 或在主任务请求展示 IMPLEMENTATION_PROGRESS 后继续
[ ] 从 implementation_steps 推导 completed / current / remaining，不使用主观百分比
```

R1/R2 Review 前：

```text
[ ] Documentation Sync 已完成
[ ] handoff 已生成并注册
[ ] Implementer 任务已经结束，不再修改 subject 或执行 Review
[ ] Reviewer 使用新会话或不继承聊天的隔离 agent
[ ] Reviewer 只依据 handoff，并使用不同 session ID
```
