# Polaris

> 当前版本：`0.1.18`（开发中）

## Polaris 为什么存在

AI 很擅长快速生成代码，但真实的软件工程并不只需要“写出代码”。一个需求还要被准确理解、形成可执行计划、经过独立审查和验证，并在中断或换会话后继续推进。

仅靠聊天记录完成这些工作，常见问题是：

- 需求和验收标准在实现过程中发生漂移；
- AI 写完代码后自行判断“已经完成”，缺少独立审查与可复现证据；
- 计划、代码、测试和文档不同步；
- 会话中断后，新的 Agent 不知道任务做到哪里、为什么这样做；
- 用户只能反复追问进度，难以看到可信、统一的项目状态。

Polaris 的意义，是把 AI 编程从一次性的代码生成，升级为一套**可审计、可验证、可恢复的软件工程流程**。

它把需求、计划、实现、Review、Validation 和任务状态保存在代码仓库中，让仓库成为事实来源；再用确定性的工作流门禁约束 AI：谁负责实现，谁独立审查，什么证据足以通过，以及任务何时才能真正关闭。

最终，用户得到的不是一句“代码写好了”，而是一项能够回答以下问题的工程成果：

- 做什么，为什么做，验收标准是什么？
- 当前进行到哪一步，还有什么没有完成？
- 哪些代码、测试和文档发生了变化？
- 谁审查过，发现了什么，问题是否已经解决？
- 验证能否复现，任务为什么可以关闭？
- 换一个会话后，能否从仓库继续工作？

Polaris 当前运行在受支持的 Coding Agent 宿主之上，内置 Codex 与 Claude Code 适配器。它适合需要跨多个步骤完成、值得 Review、或需要保留决策与验证记录的工程任务；对于简单问答和无需工程闭环的小修改，可以继续直接使用 Coding Agent。

## 用户如何使用

Polaris 分为一次性的项目接入，以及日常的工程任务使用。完整说明见 [Polaris 使用说明书](docs/USAGE.md)。

### 1. 准备环境

你需要：

- Git；
- Python 3.10 或更高版本；
- Codex 或 Claude Code；
- 一个已经初始化 Git 的目标仓库。

Polaris v0.1 的运行时代码只使用 Python 标准库，不需要额外的运行时依赖。

### 2. 将 Polaris 接入项目

在 Polaris 源仓库安装 CLI，并把当前版本写入目标仓库：

```powershell
python -m pip install .
polaris vendor C:\path\to\target-repo
```

然后进入目标仓库，安装项目锁定的 Polaris 版本并初始化：

```powershell
cd C:\path\to\target-repo
python -m pip install ./tools/polaris
polaris init-project
polaris doctor --repo .
```

`doctor` 用于检查环境、安装文件、项目状态和任务记录；它只诊断，不会自动修改项目。

接入后，请将生成的 `.agents/`、`.claude/`、`tools/polaris/` 和 `.polaris/` 等耐久文件提交到 Git。这样团队成员和后续会话使用的是同一套版本与事实状态。

### 3. 在 Coding Agent 中提出工程需求

从目标仓库根目录新开一个 Codex 或 Claude Code 会话，描述目标、背景和约束，并显式启动 Polaris：

Codex：

```text
$engineering-task 为订单创建接口增加幂等保护，补充测试和使用文档。
```

Claude Code：

```text
/engineering-task 为订单创建接口增加幂等保护，补充测试和使用文档。
```

普通自然语言请求不会自动进入 Polaris。显式调用可以避免轻量问题被意外升级成完整工程流程；其他阶段 Skills 只会由已经启动的工作流在合法节点调用。

### 4. 确认需求与执行方案

Polaris 会先把你的描述整理为带验收标准的 Work Item，并在开始实现前展示关键范围、风险与计划。你需要确认需求是否准确；如果信息不足，Polaris 会在这一阶段提出澄清问题。

确认后，Polaris 按任务风险采用不同严谨度：

- `R0`：适合低风险、范围清晰的小任务；
- `R1`：默认工程闭环，包含独立 Review 和 Validation；
- `R2`：适合高风险变更，要求更严格的证据和双 Reviewer。

### 5. 查看进度并参与决策

执行期间可以直接询问当前任务的进度、已完成步骤、剩余工作和 blocker。Polaris 从仓库状态与实时进度快照回答，而不是依赖聊天记忆。

当需求变化、Review 连续失败、验证发现计划问题，或出现需要业务判断的 blocker 时，Polaris 会暂停并把决定交还给用户，不会擅自改变目标。

### 6. 恢复、检查与完成任务

换会话或中断后，可以从仓库恢复任务：

```powershell
polaris recover TASK-0001 --repo .
```

需要检查项目或单个任务时运行：

```powershell
polaris doctor --repo .
polaris validate-project --repo .
polaris validate-task TASK-0001 --repo .
```

任务只有在实现、文档同步、独立 Review 和 Validation 的门禁全部满足后，才能进入 `CLOSED`。Agent 不能绕过门禁自行宣布完成。

## Polaris 如何工作

Polaris 希望让 AI 从“生成代码”转向“可靠参与软件工程”：

```text
用户意图
  → 需求资格审查与 Work Item
  → 架构规划与最小 Working Set
  → 独立 Implementer：实现、证据与文档同步
  → 实时进度快照
  → 独立对抗 Review
  → 机械 Validation
  → CLOSED
```

核心原则：

- Graph 决定合法流程，Agent 只负责节点内执行。
- 聊天记录不是项目事实来源，权威状态保存在仓库中。
- 同一内容同时需要机械校验和人类阅读时，优先只保存四格缩进 JSON，并在展示时按需格式化；Markdown 只保存具有独立自然语言内容的实施计划、规则、Skills 和使用文档。
- Agent 不能自行宣布完成；只有门禁全部满足后，转换脚本才能写入 `VERIFIED` 或 `CLOSED`。
- Review、Validation 与 Work Item Revision、Git commit 和 diff hash 绑定。
- 新会话不依赖旧聊天，可以从仓库恢复任务状态。
- 每个暂停点和阶段结果都用固定对话检查点展示，状态始终来自转换后的仓库 Authority。
- 主任务是统一控制入口；Implementer 与 Reviewer 只依据冻结 handoff 工作，不拥有状态转换。

## v0.1 边界

v0.1 是 Repo-native Skill System，由以下部分组成：

```text
Host-native Skills
+ Repository Authority State
+ Deterministic Python Scripts
+ Thin standard-library CLI
+ Supported Agent Host Runtime
```

v0.1 明确不实现：

- 在 CLI 中重复实现协议逻辑，或扩展 CLI 为独立运行时
- daemon、watchdog、scheduler、队列或后台服务
- Dashboard、TUI、IDE 或独立 App
- 数据库、向量库或由 Polaris 运行的知识图谱服务；外部 MCP Code Intelligence Provider 仅作为可选线索源
- 自定义 Agent Runtime 或模型适配层
- Task DAG、自动归档和跨任务调度
- 自动 merge、push、发布或远程 CI 编排

## 当前实现状态

已经实现：

- v0.1 JSON Authority 模型、Schema 和四空格格式化规范
- 前进、返工、阻塞、取消和新 Revision 的 Workflow Graph
- `R0 / R1 / R2` 渐进式严谨度和高风险双 Reviewer 规则
- 八个宿主无关的同源 Workflow Skills，以及声明式、多宿主渲染与 vendoring
- 可选 Code Intelligence 协议：自动发现外部 Provider，按阶段查询或刷新，任何不可用/失败均非阻断降级
- Skills 和协议实现的目标仓库 vendoring
- 无运行时第三方依赖的 `polaris` 命令，薄层分发到项目锁定的脚本
- 项目、任务和 Work Item Revision 初始化
- 状态转换、项目/任务校验、事件账本和状态重建
- Git subject commit/diff hash 绑定
- 可恢复、验收标准绑定的线性 `implementation_steps`，以及冻结到 Implementation artifact 的 `step_results`
- 由 `scripts/internal/task_layout.py` 定义唯一目录结构，`scripts/materialize_task_layout.py` 同时生成模板树和真实任务目录
- 由 `.polaris/task-locations.json` 解耦稳定逻辑任务路径与实际目录，为物理归档保留可移动任务根
- Documentation impact 检查
- R1 Review → Validation → Result → CLOSED 的机械闭环
- 不可变 Reviewer handoff、独立会话声明和三轮 Review 上限
- 不可变 Implementation handoff、独立 Implementer 任务和 handoff/result 机械绑定
- `.polaris/tasks/<TASK>/runtime/` 下事件驱动的实时进度 JSON
- Codex 使用可见独立任务派发 Implementer/Reviewer
- Claude Code 使用非 fork、共享 checkout、可按 agent ID 续接的独立 subagent
- Review Response 与跨 Attempt 的稳定 Finding 生命周期
- Fresh-session Recovery、项目索引和可刷新 Working Set
- 只读聚合 Doctor：检查运行环境、协议、安装清单、迁移、任务位置、恢复索引、全部任务和操作残留，并输出证据与人工动作
- Failed Exploration 的任务内记录、项目级提升和按模块检索
- 固定字段的对话检查点、UI 面板优先/文本回退的澄清问题、Work Item 预览确认和验收占位符门禁
- 87 个带场景日志的自动化测试；GitHub Actions 使用 Python 3.10 在 Linux、Windows 和 macOS 运行，symlink 安全场景通过跨平台模拟覆盖

仍在建设：

- Codex 对 vendored Skills 的实际发现验证（Claude Code 2.1.220 的 Skill 与 Reviewer subagent smoke test 已通过）
- Horizon 和 Vision 真实项目试点
- Adversarial Review Yield 评估

完整范围和里程碑见 [plan.md](plan.md)。

## 仓库结构

```text
Polaris/
├── pyproject.toml          # pip 包元数据和 polaris console entry
├── polaris_cli.py         # 薄 CLI 分发器，不包含协议逻辑
├── skills/                 # 八个宿主无关的 Workflow Skills 源文件
├── hosts/                  # 平级宿主适配器、元数据、执行附录与专用文件
│   ├── codex/
│   └── claude-code/
├── scripts/                # 可执行辅助脚本；internal/ 保存不可独立运行的内部实现
├── schemas/                # 权威 JSON 数据结构
├── providers/              # 通用 Code Intelligence Provider Descriptor
├── templates/              # task-sources 是正文源；task 是脚本生成的目录投影
├── workflow/               # 默认声明式 Workflow Graph
├── tests/                  # Fixtures、规则测试和日志运行器
├── AGENTS.md               # 本仓库 AI 工程规则
├── VERSION
└── plan.md                 # v0.1 产品与实施权威文档
```

每个 `hosts/<host-id>/adapter.json` 都由 `schemas/host-adapter.schema.json` 校验。v2 清单声明 Skill 目标目录、真实入口 Skill、调用前缀、宿主能力、入口 frontmatter、可选 Skill overlay/appendix 和宿主专用文件。`vendor_project.py`、`init_project.py` 与 `validate_project.py` 只遍历这些清单，不包含 Codex/Claude Code 分支。新增同类文件型宿主时，增加一个适配器目录即可，不需要修改这三个核心流程。

接入目标仓库后：

```text
target-repo/
├── .agents/skills/         # vendored Codex Skills
├── .claude/skills/         # vendored Claude Code Skills
├── .claude/agents/         # Polaris Implementer/Reviewer subagents
├── tools/polaris/          # vendored、版本锁定的协议实现与安装清单
└── .polaris/               # 项目和任务 Authority State
    └── tasks/TASK-NNNN/
        └── runtime/        # 本任务的本机实时进度；默认忽略，不进入 Git
```

## 环境要求

- Git
- Python 3.10 或更高版本
- 一个已有 Polaris 适配器的 Coding Agent 宿主；当前为 Codex 或 Claude Code

Polaris v0.1 的运行时代码只使用标准库，不安装第三方运行时依赖。`pip` 和 `setuptools` 只用于安装 CLI。

任务目录规则只修改 `scripts/internal/task_layout.py`。模板正文只修改
`templates/task-sources/`；随后运行下列命令重建并校验生成的
`templates/task/`，不要直接编辑生成目录：

```powershell
python scripts/materialize_task_layout.py
```

`init_task.py` 和 `new_revision.py` 使用同一个物化模块创建真实任务目录；
`vendor_project.py` 也会在复制后重建目标仓库中的模板树。

状态转换仍只通过 `scripts/transition_task.py` 写入；门禁校验和候选状态效果分别位于
`scripts/internal/transition_gates.py` 与 `scripts/internal/transition_effects.py`。Review 协议按 artifact 引用、response、
handoff 和 finding lifecycle 分层，内部模块不得绕过 `transition_task.py` 直接写入状态。

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
python -m compileall -q polaris_cli.py scripts tests
```

## 接入一个目标仓库

先在 Polaris 源仓库安装 CLI：

```powershell
python -m pip install .
```

CLI 只负责定位并分发到 Polaris 源仓库或目标项目内锁定的 Python 脚本；原脚本入口仍保持兼容。

用户命令面仅包含 `vendor`、`init-project`、`init-task`、`doctor`、`validate-project`、`validate-task`、`recover`、`migrate` 和 `code-intelligence`。各命令的原脚本参数保持不变，可用 `polaris <command> --help` 查看。内部状态转换和 artifact 构建脚本不通过 CLI 暴露。

已经在当前 Coding Agent 宿主中配置好 CodeGraph MCP 后，可将它显式加入 Polaris 流程：

```powershell
polaris code-intelligence add codegraph --repo .
```

该命令启用 `auto_optional` 模式、将 CodeGraph 置于 Provider 优先级首位，并保留已有的索引范围和排除规则。它不安装、启动或验证 MCP 服务；实际工具可用性由下一次 Polaris Workflow 检查。

### 1. Vendor Polaris

```powershell
polaris vendor C:\path\to\target-repo
```

该操作读取所有 `hosts/*/adapter.json`，把 `skills/` 按各宿主的调用语法、frontmatter、overlay 和 appendix 渲染到清单声明的目标目录，同时复制宿主专用文件。`hosts/`、`providers/`、`scripts/`、`schemas/`、`skills/`、`templates/`、`workflow/` 和 `VERSION` 会一起进入 `tools/polaris/`，使目标仓库能够独立初始化、升级和校验适配器。生成的 `tools/polaris/install-manifest.json` 记录所有 Polaris 受管文件的 SHA-256 与哈希模式；文本使用 LF 规范化哈希，二进制保持严格字节哈希。`CLAUDE.md`、`.gitignore` 这类文件只保证存在，内容仍归项目所有。

`pyproject.toml` 和 `polaris_cli.py` 也会进入 `tools/polaris/`，因此目标仓库的锁定版本可以自行安装同一 CLI 入口。

目标仓库已经存在 vendored 文件时，显式使用 `--force` 才会更新：

```powershell
polaris vendor C:\path\to\target-repo --force
```

`--force` 会先校验旧安装清单，再在隔离事务目录中完整生成并校验新版；只有预生成成功后才替换目标文件。应用失败或进程崩溃时会从备份回滚/恢复，已从新版移除的受管文件不会残留，项目自有文件与清单外宿主配置不会被删除。受管文件有本地修改时默认拒绝覆盖；确认丢弃这些修改时必须额外传入 `--discard-managed-changes`。项目校验会拒绝受管文件缺失、哈希漂移或归属声明缺失。

已初始化的 `0.1.17` 项目升级到当前版本时，在 vendoring 后显式执行：

```powershell
python -m pip install --upgrade ./tools/polaris
polaris migrate --repo .
```

迁移只接受 `workflow/migrations.json` 中声明的相邻版本步骤；活动任务通过追加 `MIGRATE_POLARIS` 事件升级，不改写旧事件。迁移记录保存在 `.polaris/migrations/`，中断后重复同一命令会继续未完成步骤。没有声明的跨版本跳跃和 workflow 版本变化会被拒绝。

`0.1.2` 增加了新的 Workflow event；`0.1.3` 把恢复索引与 Working Set 从 Markdown 迁移为 JSON；`0.1.4` 将实时实现进度改为事件驱动的线性步骤；`0.1.5` 让任务模板目录镜像实际生成目录；`0.1.6` 将任务路径集中到单一真源；`0.1.7` 引入版本化声明式宿主适配器，并内置 Codex 与 Claude Code；`0.1.8` 补齐有限 Schema 子集；`0.1.9` 引入安装清单；`0.1.10` 引入显式迁移协议；`0.1.11` 加固 Adapter v2 的入口、overlay、symlink 与能力声明；`0.1.12` 统一写操作版本门禁、恢复迁移崩溃锁，并提供事务化 vendoring；`0.1.13` 引入 Plan Human 决策门禁，并解耦逻辑任务路径与物理目录；`0.1.14` 让 vendored 文本哈希兼容 Git 的跨平台换行转换，同时保持二进制严格校验；`0.1.15` 引入只读聚合 Doctor 和版本化诊断报告；`0.1.16` 增加自动发现、非阻断降级的可选 Code Intelligence Provider 协议与首个 CodeGraph MCP Adapter。Workflow Graph 协议仍是 `0.1.2`。

`0.1.17` 在不改变 Workflow `0.1.2` 的前提下增加无运行时第三方依赖的薄 `polaris` CLI。

`0.1.18` 增加 `polaris code-intelligence add <provider>`，用于把已配置的 Provider 显式加入 Polaris 流程；Workflow 仍为 `0.1.2`。

### 2. 初始化项目状态

在目标仓库中运行：

```powershell
polaris init-project
```

这会默认使用目标仓库目录名作为 `project_id`，并创建 `.polaris/project.json`、`.polaris/task-locations.json`、冻结的 `.polaris/workflow.json` 和恢复索引；目标仓库没有 `AGENTS.md` 或 `CLAUDE.md` 时还会创建对应的最小仓库规则，并在 `.gitignore` 中加入活动与未来归档任务的 `runtime/` 忽略规则。需要覆盖默认项目标识或从其他目录操作时，仍可使用 `polaris init-project my-project --repo C:\path\to\target-repo`。

### 3. 初始化任务

```powershell
polaris init-task TASK-0001 --rigor R1 --repo .
```

任务初始状态为 `DRAFT`。填写并冻结 `.polaris/tasks/TASK-0001/revisions/work-item-r001.json` 后，才能进入资格审查和后续阶段。

### 4. 校验项目和任务

```powershell
polaris validate-project --repo .
polaris validate-task TASK-0001 --repo .
```

统一退出码：

- `0`：PASS
- `1`：规则或门禁失败
- `2`：输入、环境或系统错误

所有脚本都支持 `--json`，便于由 Agent 或自动化程序读取结果。

需要一次查看全部健康状态时运行 Doctor：

```powershell
polaris doctor --repo .
polaris doctor --repo . --json
```

Doctor 不修复、不迁移、不删除残留，也不写入任何项目文件。它复用现有 Validator 的判定，一次聚合运行环境、仓库根、协议版本、Authority、安装清单、迁移记录、任务位置、恢复索引、全部活动任务、`.gitignore` 和未完成操作残留。`WARN` 给出证据与建议动作但返回 `0`；任一规则为 `FAIL` 时返回 `1`；Doctor 自身无法运行时返回 `2`。

### 5. 从新会话恢复

```powershell
polaris recover TASK-0001 --repo . --json
```

恢复脚本先校验 `.polaris/project-index.json`、项目和任务，再只返回当前 Revision、状态与 blocker、最后事件、下一动作、结构化 `working-set.json`，以及存在时的最近有效 Implementation 进度。它不读取聊天历史。

刷新 `working-set.json` 时可以保留已有条目，或用 `--force` 重建自动条目：

```powershell
python tools/polaris/scripts/build_working_set.py TASK-0001 --repo . --entry "Code|src/module.py|affected entry point|dependency from AC-01"
```

### 6. 交接独立 Implementation 与查询进度

进入 `IMPLEMENTING` 后，主任务生成并注册不可变 handoff，再在同一本地项目中创建确定性标题的 Implementer 任务：

```powershell
python tools/polaris/scripts/build_implementation_handoff.py TASK-0001 --repo .
python tools/polaris/scripts/transition_task.py TASK-0001 DISPATCH_IMPLEMENTATION --repo . --artifact implementation_handoff=implementations/r001/handoff-001.json
```

自动任务标题为 `Polaris Implement · <TASK> · <REVISION> · attempt <N>`。Implementer 只接收 handoff，负责代码、测试、实现 checkpoint，以及同一会话内的 Documentation Sync；它只写 Implementation、Knowledge Delta 和实时进度，不执行状态转换。主任务验证这些产物并推进 Graph。

开发期间可以直接打开四格缩进的实时快照：

```text
.polaris/tasks/TASK-0001/runtime/progress.json
```

它保存一份有序 `implementation_steps`：每项都有稳定 ID、标题、状态、关联验收标准和终态结果。当前步骤、完成项和剩余项都从这份列表推导；步骤只能线性推进，新工作只能追加。主任务验证 JSON 后按需格式化展示，不另存 Markdown 副本。该目录默认忽略，不污染 Git；它不是主观百分比，也不保证跨电脑恢复。宿主无法自动创建任务时，主任务使用相同 handoff 同会话执行，并明确提示即时状态回答可能延迟。

### 7. 交接独立 Review

完成 Documentation Sync 后，在实现者会话中生成 handoff：

```powershell
python tools/polaris/scripts/build_review_handoff.py TASK-0001 --repo . --implementer-session-id impl-20260813 --isolation fresh_session
python tools/polaris/scripts/transition_task.py TASK-0001 START_REVIEW --repo . --artifact review_handoff=reviews/r001/handoff-001.json
```

R1/R2 到这里必须停止实现与审查工作，但主任务会继续承担宿主编排：Work Item 中的 `review_dispatch.authorized=true` 记录用户的“确认并执行”授权。Codex 创建同一 checkout 中的独立可见 Review 任务；Claude Code 创建非 fork `polaris-reviewer` subagent，并用返回的 agent ID 作为 Reviewer session ID。两者都只传递 task ID、Reviewer slot 和已注册 handoff，不继承 Implementer 聊天，也不默认创建独立 worktree。宿主没有创建或等待 worker 的能力时，Polaris 回退为完整的手动新会话提示，状态保持 `REVIEWING`。

Review worker 使用确定性标题 `Polaris Review · <TASK> · <REVISION> · attempt <N> · reviewer <SLOT>`。恢复或重试时先复用已有有效 Review artifact；Codex 再复用唯一同名任务，Claude Code 在当前主会话中复用已知 agent ID，避免重复创建。高风险 R2 按顺序启动两个独立 Reviewer；任一 Reviewer 拒绝即停止本轮，全部接受后由主任务注册 Review artifacts 并推进状态。

Review 被拒绝后，实现者必须使用 `templates/task/reviews/r001/response-002.json` 所示结构逐项回复所有 open Finding，并在下一次 `FINISH_IMPLEMENTATION` 同时注册该响应。后续 Reviewer 必须保留 Finding ID、复查完整新 Patch 并填写 Reviewer resolution。第三次 Review 仍为 `REJECT` 时，任务自动进入 Human-owned `BLOCKED`。

Session ID 是审计声明，不是身份认证。如果宿主没有公开 ID，应在每个会话开始时生成一个不复用的稳定标识。

### 8. 记录失败探索

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
- v0.1 的 CLI 保持为现有脚本的薄分发层，不在其中增加协议逻辑、UI、服务进程或自定义 Agent Runtime。

## License

当前仓库尚未添加开源许可证。在许可证明确之前，请勿假定代码可以按任意开源协议再分发。
