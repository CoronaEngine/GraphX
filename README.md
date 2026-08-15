# Polaris

完整的首次接入、日常提需求、独立 Implementation、进度查询、Review、恢复与升级流程见 [Polaris 使用说明书](docs/USAGE.md)。

Polaris 是一套运行在受支持 Coding Agent 宿主之上的、以仓库为权威状态的软件工程工作流系统。当前内置 Codex 与 Claude Code 适配器。

它将模糊需求转换为冻结的 Work Item，通过声明式 Workflow、独立实现、可查询进度、独立对抗审查、可复现验证和文档同步，约束 AI 按可审计、可恢复的工程流程工作。

Polaris 采用显式启用：普通工程需求不会自动进入 Polaris；用户必须按当前宿主适配器的语法主动调用 `engineering-task`（Codex 为 `$engineering-task`，Claude Code 为 `/engineering-task`）。其他阶段 Skills 只能由已启动的工作流在合法节点分派。

> 当前版本：`0.1.12`（开发中）

## 核心目标

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
+ Supported Agent Host Runtime
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
- 七个宿主无关的同源 Workflow Skills，以及声明式、多宿主渲染与 vendoring
- Skills 和协议实现的目标仓库 vendoring
- 项目、任务和 Work Item Revision 初始化
- 状态转换、项目/任务校验、事件账本和状态重建
- Git subject commit/diff hash 绑定
- 可恢复、验收标准绑定的线性 `implementation_steps`，以及冻结到 Implementation artifact 的 `step_results`
- 由 `scripts/internal/task_layout.py` 定义唯一目录结构，`scripts/materialize_task_layout.py` 同时生成模板树和真实任务目录
- Documentation impact 检查
- R1 Review → Validation → Result → CLOSED 的机械闭环
- 不可变 Reviewer handoff、独立会话声明和三轮 Review 上限
- 不可变 Implementation handoff、独立 Implementer 任务和 handoff/result 机械绑定
- `.polaris/tasks/<TASK>/runtime/` 下事件驱动的实时进度 JSON
- Codex 使用可见独立任务派发 Implementer/Reviewer
- Claude Code 使用非 fork、共享 checkout、可按 agent ID 续接的独立 subagent
- Review Response 与跨 Attempt 的稳定 Finding 生命周期
- Fresh-session Recovery、项目索引和可刷新 Working Set
- Failed Exploration 的任务内记录、项目级提升和按模块检索
- 固定字段的对话检查点、UI 面板优先/文本回退的澄清问题、Work Item 预览确认和验收占位符门禁
- 69 个带场景日志的自动化测试；真实 symlink 集成场景在平台不支持时明确跳过

仍在建设：

- Codex 对 vendored Skills 的实际发现验证（Claude Code 2.1.220 的 Skill 与 Reviewer subagent smoke test 已通过）
- Horizon 和 Vision 真实项目试点
- Adversarial Review Yield 评估

完整范围和里程碑见 [plan.md](plan.md)。

## 仓库结构

```text
Polaris/
├── skills/                 # 七个宿主无关的 Workflow Skills 源文件
├── hosts/                  # 平级宿主适配器、元数据、执行附录与专用文件
│   ├── codex/
│   └── claude-code/
├── scripts/                # 可执行辅助脚本；internal/ 保存不可独立运行的内部实现
├── schemas/                # 权威 JSON 数据结构
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

Polaris v0.1 的 Python 代码只使用标准库，不需要安装第三方依赖。

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
python -m compileall -q scripts tests
```

## 接入一个目标仓库

以下命令均从 Polaris 源仓库运行。它们是直接执行的 Python 脚本，不是 Polaris CLI。

### 1. Vendor Polaris

```powershell
python scripts/vendor_project.py C:\path\to\target-repo
```

该操作读取所有 `hosts/*/adapter.json`，把 `skills/` 按各宿主的调用语法、frontmatter、overlay 和 appendix 渲染到清单声明的目标目录，同时复制宿主专用文件。`hosts/`、`scripts/`、`schemas/`、`skills/`、`templates/`、`workflow/` 和 `VERSION` 会一起进入 `tools/polaris/`，使目标仓库能够独立初始化、升级和校验适配器。生成的 `tools/polaris/install-manifest.json` 记录所有 Polaris 受管文件的 SHA-256，以及 `CLAUDE.md`、`.gitignore` 这类仅保证存在、内容归项目所有的保留文件。

目标仓库已经存在 vendored 文件时，显式使用 `--force` 才会更新：

```powershell
python scripts/vendor_project.py C:\path\to\target-repo --force
```

`--force` 会先校验旧安装清单，再在隔离事务目录中完整生成并校验新版；只有预生成成功后才替换目标文件。应用失败或进程崩溃时会从备份回滚/恢复，已从新版移除的受管文件不会残留，项目自有文件与清单外宿主配置不会被删除。受管文件有本地修改时默认拒绝覆盖；确认丢弃这些修改时必须额外传入 `--discard-managed-changes`。项目校验会拒绝受管文件缺失、哈希漂移或归属声明缺失。

已初始化的 `0.1.11` 项目升级到当前版本时，在 vendoring 后显式执行：

```powershell
python tools/polaris/scripts/migrate_project.py --repo .
```

迁移只接受 `workflow/migrations.json` 中声明的相邻版本步骤；活动任务通过追加 `MIGRATE_POLARIS` 事件升级，不改写旧事件。迁移记录保存在 `.polaris/migrations/`，中断后重复同一命令会继续未完成步骤。没有声明的跨版本跳跃和 workflow 版本变化会被拒绝。

`0.1.2` 增加了新的 Workflow event；`0.1.3` 把恢复索引与 Working Set 从 Markdown 迁移为 JSON；`0.1.4` 将实时实现进度改为事件驱动的线性步骤；`0.1.5` 让任务模板目录镜像实际生成目录；`0.1.6` 将任务路径集中到单一真源；`0.1.7` 引入版本化声明式宿主适配器，并内置 Codex 与 Claude Code；`0.1.8` 补齐有限 Schema 子集；`0.1.9` 引入安装清单；`0.1.10` 引入显式迁移协议；`0.1.11` 加固 Adapter v2 的入口、overlay、symlink 与能力声明；`0.1.12` 统一写操作版本门禁、恢复迁移崩溃锁，并提供事务化 vendoring。Workflow Graph 协议仍是 `0.1.2`。

### 2. 初始化项目状态

在目标仓库中运行：

```powershell
python tools/polaris/scripts/init_project.py my-project --repo .
```

这会创建 `.polaris/project.json`、冻结的 `.polaris/workflow.json` 和恢复索引；目标仓库没有 `AGENTS.md` 或 `CLAUDE.md` 时还会创建对应的最小仓库规则，并在 `.gitignore` 中加入 `.polaris/tasks/*/runtime/`。

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
- v0.1 不扩建 CLI、UI、服务进程或自定义 Agent Runtime。

## License

当前仓库尚未添加开源许可证。在许可证明确之前，请勿假定代码可以按任意开源协议再分发。
