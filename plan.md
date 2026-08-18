# Polaris v0.1 —— AI Engineering Workflow System 实施计划

> 状态：Implementation underway
> 目标版本：v0.1
> 当前协议：`0.1.20`；Workflow：`0.1.3`
> 产品形态：Repo-native Skill System
> 宿主 Runtime：声明式可扩展；v0.1 内置 Codex、Claude Code
>
> **已确认的 MVP 决策：v0.1 提供无运行时第三方依赖的薄 `polaris` CLI，仅定位并分发到现有 Python 脚本，不承载协议逻辑。Polaris Skills、版本化声明式宿主适配器、可选 Provider Descriptor、CLI、辅助脚本、Schema、模板和默认 Workflow 全部 vendoring 到目标仓库。所有宿主共享同一套仓库 Authority 和机械协议。**

## 1. 目标与定位

Polaris v0.1 是一套运行在受支持 Coding Agent 宿主之上的、可持久化的软件工程协议：

```text
Workflow Skills
+ Repository State
+ Deterministic Validators / Helpers
+ Thin standard-library CLI dispatcher
+ Supported Agent Host Runtime
```

它把模糊需求转化为冻结的 Work Item，按声明式工作流推进实现、独立审查、机械验证和文档同步，并允许新会话仅从仓库恢复工作。

v0.1 的目标是验证这套工程方法能否提高 Horizon / Vision 上复杂任务的可靠性，而不是先建设基础设施。

### 核心原则

1. **Graph owns control. Agent owns execution.** Graph 定义合法顺序和门禁；Agent 只执行节点内工作。
2. **Execution loops live inside nodes; governance loops are explicit graph edges.** 节点内允许搜索、编码和测试循环；跨 Implementation、Review、Validation 的返工必须通过声明式 Graph 边推进，不能由无界 Agent Loop 自行决定流程和完成状态。
3. **Artifact dependencies enable; governance transitions gate.** 依赖产物齐备只表示节点可开始；进入下一状态仍须满足机械、Reviewer 或 Human Gate。
4. **Context is a working set/cache, not a database.** 仓库保存知识，Context 只加载当前任务所需的最小工作集。
5. **Recovery must be progressive, not exhaustive.** 先地图、再任务、再模块、最后按需深入，禁止默认重读整个项目。
6. **Agent never owns completion state.** Agent 可以提交实现和证据，只有确定性脚本在门禁满足后才能写入 `VERIFIED` / `CLOSED`。
7. **Decisions have owners.** 目标与边界归 Human；执行策略归 Agent；合法性与完备性归机械校验。
8. **Changes are deltas.** Work Item 和知识包只描述相对当前系统的变化，不复制整套项目知识。
9. **Independent review is adversarial.** Reviewer 使用独立会话，从冻结合同、代码差异和证据出发，先检查“做对事情”，再检查“事情做对”。
10. **Failed exploration is durable knowledge.** 失败尝试必须记录原因、证据和重试条件，避免跨会话重复踩坑。
11. **Rigor is progressive.** 风险越高，所需产物、独立审查和人工门禁越严格。
12. **Machine validation wins format decisions.** 同一内容同时需要机械校验和人类阅读时，默认只保存四格缩进 JSON，并在展示时按需格式化；只有独立自然语言内容无法用结构化字段清晰表达时才使用 Markdown。
13. **Task layout has one source.** `scripts/internal/task_layout.py` 是任务相对路径的唯一权威；`scripts/materialize_task_layout.py` 从该定义同时生成 `templates/task/` 样例树和真实任务目录。模板正文只维护在平铺的 `templates/task-sources/`，Schema 不重复硬编码目录正则。
14. **Cross-platform behavior is a design constraint.** 任何新增或修改的代码都必须在设计、实现和 Review 时明确考虑 Windows、macOS 与 Linux；不得依赖硬编码路径分隔符、特定 shell、仅单平台成立的文件系统或进程语义。平台能力存在差异时必须先做能力检测并提供确定性降级或明确错误；核心规则使用平台无关测试始终验证，真实 symlink 等可选文件系统集成测试仅在能力可用时运行，不支持时明确 `SKIP`，不得误报 `FAIL`。

## 2. MVP 范围

### 必须实现

- 一个顶层 `engineering-task` Skill 和六个阶段 Skill。
- Skills、辅助脚本、Schema、模板和默认 Workflow vendoring 到目标仓库并纳入 Git。
- `.polaris/` 仓库状态协议、模板与默认工作流图。
- Work Item 修订、任务状态、事件账本、工作集、Review、Validation、Result。
- 项目初始化、任务初始化、状态转换、结构校验、文档影响检查、工作集生成脚本。
- 通过 pip 安装、只暴露用户命令的薄 `polaris` CLI；保留原 Python 脚本入口。
- 只读聚合 Doctor；复用现有 Validator，一次输出环境、协议、Authority、任务与操作残留的证据和人工动作。
- 可选 Code Intelligence 协议；唯一正式 Provider 是 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)，按阶段检查新鲜度、必要时有限同步、保存精简证据，并在任何不可用或失败时非阻断降级。
- 独立 Implementer worker、不可变 Implementation handoff 与事件驱动实时进度快照。
- 验收标准绑定的线性 `implementation_steps`；步骤只能依次推进或在末尾追加，最终结果冻结进 Implementation artifact。
- 独立 worker context 的对抗审查协议。
- Fresh-session / fresh-clone 的渐进恢复协议。
- `R0 / R1 / R2` 三档渐进式严谨度。
- Horizon 首个试点；通过后在 Vision 做第二个试点。

### 明确不做

- 在 CLI 中重复协议逻辑、暴露内部状态转换命令，或将 CLI 扩展为独立 runtime
- daemon、watchdog、scheduler、队列或后台服务
- Dashboard、TUI、IDE 或独立 App
- 自定义 Agent Runtime、模型适配层或进程生命周期管理
- 数据库、向量库、由 Polaris 运行的知识图谱服务或事件服务；外部 MCP Code Intelligence Provider 仅作为可选线索源
- 通用自动多任务调度、跨项目管理、实时进度百分比；当前 TASK 内由宿主创建必要的独立 Implementer / Review 任务不属于通用调度
- Task DAG、任务归档和跨任务依赖调度
- 通用领域 Skill 市场
- 自动合并、发布或远程 CI 编排

## 3. 架构边界

```text
Human
  │  owns intent, hard constraints, approvals
  ▼
Main host task + Polaris Workflow Skills
  │  owns orchestration, status, gates and transitions
  ├───────────── host dispatch ─────────────┐
  ▼                                         ▼
Fresh Implementer worker               Fresh Reviewer worker(s)
  │  code / tests / docs / progress         │  immutable verdict
  └────────── same local checkout ──────────┘
                      │
                      ▼
        Repository Code + .polaris authority
                      │
                      ▼
           Deterministic Python scripts
        schema / references / gates / transitions
```

v0.1 没有常驻控制器，因此 Graph 的控制力来自三层：Skill 必须解释 Graph；脚本拒绝非法转换；验收标准要求所有任务通过脚本。不能防止恶意手改状态文件，这不是 v0.1 要解决的问题。

### Authority 顺序

发生冲突时按以下顺序处理：

1. Human 确认的项目要求与 Change Decision
2. 当前冻结的 Work Item revision
3. 当前代码、测试、构建事实及其 Git commit / diff hash
4. `events.jsonl` 中通过合法转换脚本追加的事件
5. 由事件重建的 `state.json` 投影
6. 与当前 Work Item revision、commit 和 diff hash 匹配的 Review / Validation evidence
7. Plan、工作笔记、聊天记录和状态摘要

聊天和 `PLAN.md` 是叙述或计划，不得覆盖权威 JSON 状态；`project-index.json` 与 `working-set.json` 是可校验的结构化恢复索引和有限上下文。结构化 artifact 不生成内容重复的 Markdown 副本。旧 Review 或 Validation 不得覆盖更新后的代码事实；其绑定的 revision、commit 或 diff hash 不匹配时自动失效。

## 4. 仓库布局

### Polaris 自身仓库

```text
polaris/
├── README.md
├── AGENTS.md
├── VERSION
├── pyproject.toml                     # pip 元数据与 console entry
├── polaris_cli.py                    # 薄分发器
├── hosts/
│   ├── codex/
│   │   ├── adapter.json               # Skill 目标、调用语法与资产清单
│   │   ├── skill-overlays/            # Codex 专用 Skill metadata overlay
│   │   └── skill-appendices/          # Codex worker 执行语义
│   └── claude-code/
│       ├── adapter.json
│       ├── CLAUDE.md
│       ├── agents/                    # Claude Code 非 fork worker 定义
│       └── skill-appendices/
├── skills/                            # 宿主无关、单一来源
│   ├── engineering-task/SKILL.md
│   ├── requirement-analysis/SKILL.md
│   ├── architecture-planning/SKILL.md
│   ├── implementation/SKILL.md
│   ├── adversarial-review/SKILL.md
│   ├── validation/SKILL.md
│   ├── documentation-sync/SKILL.md
│   └── code-intelligence/SKILL.md      # 仅由阶段 Skill 内部调用
├── providers/
│   └── code-intelligence/codegraph.json
├── templates/
│   ├── AGENTS.md                  # 共享规则
│   ├── project-index.json
│   ├── task-sources/              # 模板正文唯一来源；不表达目录结构
│   │   ├── state.json
│   │   ├── work-item.json
│   │   ├── implementation.json
│   │   └── ...
│   └── task/                      # 由 materialize_task_layout.py 生成；禁止手改
│       ├── state.json
│       ├── working-set.json
│       ├── PLAN.md
│       ├── plan-decisions.json
│       ├── runtime/progress.json
│       ├── revisions/work-item-r001.json
│       ├── implementations/r001/
│       │   ├── handoff-001.json
│       │   └── attempt-001.json
│       ├── knowledge/r001/knowledge-delta-001.json
│       ├── reviews/r001/
│       │   ├── handoff-001.json
│       │   ├── review-001.json
│       │   └── response-002.json
│       ├── validations/r001/validation-001.json
│       ├── results/r001/result-001.json
│       └── explorations/EXP-0001.json
├── workflow/default-workflow.json
├── schemas/
│   ├── project.schema.json
│   ├── host-adapter.schema.json
│   ├── task-state.schema.json
│   ├── workflow.schema.json
│   ├── work-item.schema.json
│   ├── working-set.schema.json
│   ├── project-index.schema.json
│   ├── doctor-report.schema.json
│   ├── review.schema.json
│   └── validation.schema.json
├── scripts/
│   ├── init_project.py
│   ├── init_task.py
│   ├── materialize_task_layout.py
│   ├── new_revision.py
│   ├── build_working_set.py
│   ├── doctor_project.py
│   ├── validate_project.py
│   ├── validate_task.py
│   ├── transition_task.py
│   ├── rebuild_state.py
│   ├── check_docs.py
│   └── internal/                  # 不可独立运行的协议实现
│       ├── task_layout.py
│       ├── host_adapters.py
│       ├── doctor_protocol.py
│       ├── polaris_core.py
│       ├── transition_gates.py
│       └── transition_effects.py
└── tests/
    ├── fixtures/
    └── test_*.py
```

### 接入后的目标仓库

```text
target-repo/
├── AGENTS.md
├── CLAUDE.md                          # Claude Code 入口与共享规则桥接
├── .agents/
│   └── skills/                    # vendored Codex Skills
│       ├── engineering-task/SKILL.md
│       ├── requirement-analysis/SKILL.md
│       ├── architecture-planning/SKILL.md
│       ├── implementation/SKILL.md
│       ├── adversarial-review/SKILL.md
│       ├── validation/SKILL.md
│       └── documentation-sync/SKILL.md
├── .claude/
│   ├── skills/                    # 同源渲染的 Claude Code Skills
│   │   ├── engineering-task/SKILL.md
│   │   └── ...
│   └── agents/
│       ├── polaris-implementer.md
│       └── polaris-reviewer.md
├── tools/
│   └── polaris/                   # vendored、项目锁定的协议实现
│       ├── VERSION
│       ├── hosts/
│       ├── scripts/
│       ├── schemas/
│       ├── templates/
│       └── workflow/default-workflow.json
├── docs/                         # 人和 Agent 共用的真实项目文档
│   ├── architecture/
│   ├── decisions/
│   └── modules/<module>/index.md
└── .polaris/
    ├── project.json
    ├── project-index.json         # 保持短小，只做结构化恢复地图
    ├── task-locations.json        # Task ID 到实际目录的可校验映射
    ├── workflow.json
    ├── decisions/
    │   └── CD-*.json              # append-only，权威 Human Decision/Approval
    ├── explorations/EXP-*.json    # 可跨任务复用的失败探索
    ├── tasks/
    │   └── TASK-0001/
    │       ├── state.json         # 可由事件重建的当前状态投影
    │       ├── runtime/            # 本任务的本机实时状态；默认 Git ignored
    │       │   └── progress.json   # 实时进度 JSON 权威快照
    │       ├── revisions/
    │       │   └── work-item-r001.json  # 权威执行合同
    │       ├── PLAN.md
    │       ├── plan-decisions.json # 绑定 PLAN.md 与 Human 选择/CD
    │       ├── working-set.json
    │       ├── implementations/r001/
    │       │   ├── handoff-001.json
    │       │   └── attempt-001.json
    │       ├── knowledge/r001/
    │       │   └── knowledge-delta-001.json
    │       ├── reviews/r001/
    │       │   └── review-001.json
    │       ├── validations/r001/
    │       │   └── validation-001.json
    │       ├── results/r001/
    │       │   └── result-001.json
    │       ├── evidence/r001/     # 可复现命令摘要、日志或其哈希
    │       ├── events.jsonl       # append-only，状态转换记录
    │       └── explorations/EXP-*.json
```

宿主渲染目录、`tools/polaris/` 和 `.polaris/` 的耐久状态均纳入 Git；唯一例外是各任务目录下的 `.polaris/tasks/<TASK>/runtime/`，它保存当前电脑上的实时进度并默认忽略，不参与阶段门禁或 Fresh Clone 恢复。宿主目录与 `tools/polaris/` 是 vendored 协议包，`.polaris/` 其余内容是项目运行状态。`project.json` 必须记录 `polaris_version` 和 `workflow_version`。Codex 从 `.agents/skills/` 发现 `$skill-name`，Claude Code 从 `.claude/skills/` 发现 `/skill-name`；两份 Skill 由宿主无关的 `skills/` 单一来源生成。

### 任务路径模型

任务引用分为三层，不得混用：

1. Task-relative：`state.json` artifacts、Implementation/Review 关联等任务内部字段，以当前任务根目录为基准，例如 `reviews/r001/review-001.json`。
2. Logical repo-relative：handoff package、Working Set、实时进度和提升后的 Exploration 使用稳定逻辑地址 `.polaris/tasks/<TASK>/...`。它是持久身份，不表示文件必须物理位于该目录。
3. Physical location：`.polaris/task-locations.json` 保存 Task ID 到实际仓库目录的映射。所有脚本必须通过 `task_dir()`、`logical_repo_path()` 或 `resolve_repo_reference()` 解析，不得自行拼接或用 `repo / logical_path` 打开任务文件。

新任务默认映射到 `.polaris/tasks/<TASK>`。位置路径必须位于 `.polaris/` 下、以 Task ID 结尾、使用 POSIX 分隔符、不得重复、越界或穿过 symlink。项目校验要求注册表与 `project.json.active_tasks` 完全一致，并继续对实际目录运行完整任务校验。旧 handoff 和 Working Set 保持原逻辑路径即可；改变 physical location 不得改写历史 artifact。v0.1.13 只建立可移动任务根和兼容迁移，不提供归档/恢复命令或归档可见性语义；后续物理归档应在此层之上增加事务化移动和 append-only Archive Event。

每次 vendoring 必须生成并提交 `tools/polaris/install-manifest.json`。清单把完整归 Polaris 所有的输出登记为带 SHA-256 与明确 `hash_mode` 的 `managed_files`，把内容归项目维护但安装要求存在的文件登记为 `preserved_files`。已知 UTF-8 文本使用 `text_lf_sha256`，哈希前统一 CRLF/CR 为 LF，以保持 Git Fresh Clone 跨平台稳定；未知或二进制资产使用 `byte_sha256`，不得放宽字节校验。旧 v1 清单只允许已知文本文件按 LF/CRLF 等价验证，以便安全升级到 v2。项目校验必须验证受管文件存在、哈希模式与路径类型一致、哈希一致且必要适配器输出已登记；强制升级必须先按旧清单删除旧受管文件，再生成新清单，不删除保留文件或清单外文件。没有旧清单的早期安装只能走已知目录的兼容更新，不能猜测并删除未知文件。

### 宿主适配契约

每个宿主占用独立、平级的 `hosts/<host-id>/`，并提供由 `host-adapter.schema.json` 校验的 `adapter.json`。清单版本 `adapter_version=2` 声明 Skill 目标目录、调用前缀、入口 Skill、宿主能力、额外 frontmatter、可选 metadata overlay、执行附录和宿主专用文件。能力至少包括结构化用户输入、worker 创建、状态查询、续接和稳定身份；依赖关系必须机械自洽。共享 Skill 只使用 `{{skill:<name>}}` 占位符和宿主无关 worker 语义；vendoring 时再渲染调用语法并追加宿主执行机制。

`vendor_project.py`、`init_project.py` 和 `validate_project.py` 必须通过 `scripts/internal/host_adapters.py` 发现 canonical Skills 与所有清单，不得按宿主 ID 编写条件分支。入口必须指向实际 Skill；overlay 只能向已知 Skill 增加 canonical 源中不存在的普通文件，不能替换 `SKILL.md` 或其他源内容；adapter 源树与全部目标路径禁止 symlink。新增满足 v2 文件型契约的宿主只增加目录和资产；目标路径冲突、越界路径、缺失源文件、能力矛盾和未知清单版本都必须机械拒绝。需要超出 v2 表达能力的新机制时，先升级 adapter schema/version，再保持旧版本迁移边界，不把宿主差异写回共享 Workflow 或 Authority schema。

JSON 文件是机械门禁的权威输入。结构化 artifact 不生成同名 Markdown 副本；用户可直接查看四格缩进 JSON，主任务也可按需格式化展示。旧 revision 和旧 attempt 文件不可覆盖，`state.json` 仅保存当前有效 artifact 的指针。

## 5. Skill 列表与职责

| Skill | 责任 | 禁止事项 |
|---|---|---|
| `engineering-task` | 用户显式调用后的主控制任务；恢复、选择 rigor、派发/续接 Worker、汇总实时状态、验证 artifact、执行转换 | 自动路径不修改 subject；不隐式触发，不直接宣布完成，不绕过 transition 脚本 |
| `requirement-analysis` | 澄清目标、验收、范围、硬约束、Decision Owner；生成并冻结 Work Item revision | 不替 Human 决定目标、破坏性边界或产品取舍 |
| `architecture-planning` | 构造最小工作集；调查代码；形成 delta-oriented Plan、风险与验证映射 | 不把推测写成项目事实，不无界加载仓库 |
| `implementation` | 独立 Implementer 只依据注册 handoff 小步实现；运行 build/test/fix loop；写实时进度与 Implementation artifact | 不读取主聊天，不执行状态转换，不修改 Work Item，不自审或关闭任务 |
| `adversarial-review` | 在独立会话审查 spec compliance 与 engineering quality；管理 finding 生命周期 | 不接受作者自证；不依赖原实现会话的隐式上下文 |
| `validation` | 把 acceptance criterion 映射到可复现证据；运行规定验证；产出 verdict 输入 | 不弱化验收条件，不用主观总结代替命令结果 |
| `documentation-sync` | 在同一 Implementer 任务中继续分析知识 delta、更新文档并写 Knowledge Delta | 不执行状态转换，不自动把未确认推断升级为权威知识 |
| `code-intelligence` | 内部可选能力；发现 Provider，执行符号/依赖/影响查询，记录精简结果并按规则刷新 | 不作为用户入口，不扩展 scope，不替代源码、构建、测试、Review 或门禁 |

Skill 描述应按触发边界编写，而不是做技术能力菜单。用户仅通过适配器渲染后的 `engineering-task` 入口进入 Polaris（当前 Codex 为 `$engineering-task`，Claude Code 为 `/engineering-task`），阶段 Skills 只由已启动的工作流在合法节点分派，R1/R2 Reviewer 只从已注册 handoff 调用。宿主专用 metadata/frontmatter 固化显式触发边界；普通工程请求不进入 Polaris。共享 Skill 与每个适配器的渲染结果都使用 fixture 做回归测试。

### 稳定对话协议

`engineering-task` 负责所有用户可见检查点的一致性。每次暂停、Human gate、阶段完成、Review/Validation verdict 和终态都必须输出一个以 `[POLARIS:<MARKER>]` 开头的状态块，并按固定顺序包含 `Task / Revision / Rigor / State / Outcome / Authority / Remaining / Next / User action`。空字段写 `None`，不得省略；状态只能在转换脚本成功后重新读取 Authority 再报告，不得提前宣布。`IMPLEMENTATION_SESSION_STARTED` 表示宿主已创建或复用独立 Implementer 任务；`IMPLEMENTATION_PROGRESS` 从本机进度 JSON 展示最近有效的 phase、当前动作、完成项、剩余项、检查与 blocker；`REVIEW_SESSION_STARTED` 表示宿主已创建独立 Reviewer 任务。两类任务启动标记均附带确定性任务标题、handoff、dispatch mode，并在无需用户处理时显示 `User action: None`。

需求分析每轮最多询问三个会实质影响方案或验收的问题。每个问题必须给出两到三个互斥选项，推荐项排在第一位并逐项说明影响，同时允许用户提供选项之外的精确答案。宿主提供 `request_user_input` 或等效结构化交互工具时优先弹出选择面板；不可调用时必须显示内容相同的文本选项，不得为获得 UI 自行切换宿主模式或阻塞流程。两种回答写入相同 Authority；未回答项进入 `known_unknowns`，任务保持 `DRAFT`。信息完整后必须先展示 `WORK_ITEM_PREVIEW`，完整列出目标、范围、硬约束、rigor、风险、Human-owned 决策和每个 AC 的 statement/evidence，并以相同的 UI-first/text-fallback 规则等待用户明确确认。推荐确认项为“确认并执行”，其说明必须明确：确认会冻结 Work Item，并授权 Polaris 在同一本地项目中自动创建当前 revision 所需的全部独立 Implementer / Review 任务以及图允许范围内的后续 attempts。确认分别写入 `implementation_dispatch=mode:auto_new_task / fallback:same_session / same_local_project:true / authorized:true` 与 `review_dispatch=mode:auto_new_task / fallback:manual_handoff / same_local_project:true / authorized:true`；新 revision 将两者的 `authorized` 重置为 `false`。确认后才能执行 `QUALIFY` 或 `NEW_REVISION` 并输出 `WORK_ITEM_QUALIFIED`。已冻结后发生实质需求变化必须创建新 revision，不允许静默覆盖。

v0.1 不增加自定义对话 Runtime 或自定义 UI；选择面板和 Worker 创建完全复用宿主工具。具体创建、身份、查找、等待和续接语义由渲染后的宿主执行附录定义：Codex 使用同一 checkout 中的独立可见任务；Claude Code 使用非 fork 的 `polaris-implementer` / `polaris-reviewer` subagent。Implementer 派发不可用时回退主任务同会话执行并声明响应可能延迟；Reviewer 派发不可用时回退手动新会话。稳定性由共享 Skill、宿主适配器、仓库 Authority、转换后重读和 fixture 测试共同保证。`transition_task.py` 必须机械拒绝 statement 或 evidence 为空白/`TODO` 的验收项。

## 6. Work Item 与任务模型

### ID 与修订

- Task：`TASK-0001`
- Human Change Decision：`CD-0001`
- Failed Exploration：`EXP-0001`
- Work Item revision：`TASK-0001@r001`
- 权威文件：`revisions/work-item-r001.json`；Work Item 预览由主任务直接从 JSON 格式化展示，不落盘重复 Markdown。
- 修订文件不可覆盖；需求变化通过 `new_revision.py` 生成下一版、追加事件，并在 `state.json` 更新当前指针。
- 已开始实现后如 Goal、Acceptance、Scope、Hard Constraint 变化，任务退回 `QUALIFIED`，Plan、Review、Validation 对新 revision 重新失效。

### Work Item 必填字段

```json
{
  "id": "TASK-0001",
  "revision": 1,
  "title": "<short title>",
  "rigor": "R1",
  "goal": "<observable outcome>",
  "motivation": "<why now>",
  "scope": {
    "in": [],
    "out": []
  },
  "constraints": [],
  "acceptance": [
    {
      "id": "AC-01",
      "statement": "<observable criterion>",
      "evidence": "<command, test, benchmark or human check>"
    }
  ],
  "affected_modules": [],
  "base_commit": "<git sha>",
  "risk_flags": {
    "public_api": false,
    "persistent_format": false,
    "irreversible_migration": false,
    "architecture_boundary": false,
    "concurrency": false,
    "security": false,
    "resource_lifetime": false,
    "critical_performance": false
  },
  "decision_owners": {
    "human": [],
    "agent": []
  },
  "approval_gates": [],
  "implementation_dispatch": {
    "mode": "auto_new_task",
    "fallback": "same_session",
    "same_local_project": true,
    "authorized": false
  },
  "review_dispatch": {
    "mode": "auto_new_task",
    "fallback": "manual_handoff",
    "same_local_project": true,
    "authorized": false
  },
  "known_unknowns": []
}
```

`base_commit` 必须是可解析的 Git commit SHA，不允许使用 working-tree marker。所有机械读取字段均存储在 JSON 中；`PLAN.md` 不使用可被误认为权威数据的自由格式 front matter。

### Delta-oriented change package

每个 Task 目录就是一个 Change Package，只保存：

- 预期行为或知识相对 `base_commit` 的变化
- 影响模块、接口、不变量和文档
- 明确不变的边界
- 实际代码 diff 与偏离 Plan 的原因
- 新增、更新、失效或无需变更的知识条目

权威 `knowledge-delta-<attempt>.json` 必须把每项标记为 `ADD / UPDATE / STALE / NO_CHANGE`，并给出目标路径和证据；不生成同名 Markdown 副本。关闭前不得存在未处置的 `STALE`。

### Decision ownership

**Human-owned：**最终目标、验收边界、硬约束、禁区、公共 API/格式破坏、重大性能或安全取舍、任务取消。

**Agent-owned：**调查路径、工作集、方案比较、任务拆解、实现细节、测试补充、retry strategy、低风险文档同步。

**Mechanical-owned：**schema 合法性、引用完整性、节点 ready、transition 合法性、证据存在、关闭资格。

Human Decision 和 Approval 必须落入 append-only 的 `CD-*.json`，至少记录 `decision_id / approved_by / approved_at / approval_gate / work_item_revision / plan_hash / subject_diff_hash / decision`。实施前尚无 subject 时 `subject_diff_hash` 可以为 `null`，但必须绑定 `plan_hash`；最终审批必须绑定 `subject_diff_hash`。Validator 校验引用和绑定关系，但该机制属于可审计工程治理，不提供密码学身份认证。聊天中的同意只有写入 Change Decision 后才成为 Authority。

Work Item 确认与 Plan 决策是两个独立 Human gate。前者冻结目标、范围、约束、AC 和 worker 授权；后者只处理合同允许范围内、规划后才暴露的 Human-owned 方案取舍。`PLAN.md` 保存推理、备选方案和影响，`plan-decisions.json` 保存结构化问题、两到三个互斥选项、推荐项、状态以及对 `PLAN.md` 的路径和 SHA-256 绑定。无待决项也必须写空登记。待决项存在时任务通过 `BLOCK` 进入 `BLOCKED`，输出 `PLAN_DECISIONS_NEEDED`；用户选择由 `record_plan_decision.py` 写入 append-only `CD-*.json`，登记保存所选 option、CD 路径和哈希。若回答改变冻结合同，必须创建新 Work Item revision，不能作为 Plan 决策消化。

`PLAN` 门禁只接受所有条目均为 `RESOLVED` 的登记，并校验 task/revision、Plan 哈希、推荐项顺序、选项唯一性、CD Schema/哈希/路径、`task_id`、`plan_decision_id` 及 `approval_gate=plan_decision`。`FAIL_PLAN` 保留 Plan 决策登记；Implementation 与 Review handoff 在新协议任务中都携带它。升级前已处于 `PLANNED` 或更后状态且没有登记的旧任务保持可验证；它们下一次执行 `PLAN` 时必须采用新协议。

## 7. 声明式 Workflow Graph

默认主路径：

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING → REVIEWING → VALIDATING
                                                     ├─ R0/R1 → CLOSED
                                                     └─ R2 → VERIFIED → CLOSED
```

Implementation 与 Documentation Sync 在同一个 `IMPLEMENTING` 节点内完成。`START_REVIEW` 一次性校验并注册 Implementation、Knowledge Delta、Review handoff 和最终 subject，使 Reviewer 审查的 commit 同时包含代码、测试和项目文档。Review 或 Validation 引发返工时，下游 Review 和 Validation 证据失效，并按 Graph 回到相应治理节点重新执行。

必须支持以下治理回路：

```text
REVIEWING  -- REJECT --> IMPLEMENTING
VALIDATING -- FAIL: implementation --> IMPLEMENTING
VALIDATING -- FAIL: plan/evidence map --> PLANNED
任意执行状态 -- NEW_REVISION --> QUALIFIED
任意非终态 -- EXTERNAL_BLOCKER --> BLOCKED
BLOCKED -- RESOLVED --> blocked_from
任意非终态 -- HUMAN_CANCEL --> CANCELLED
```

`BLOCKED` 保存 `blocked_from`、`blocker_type`、原因和所需 Decision Owner。R2 等待人工审批使用 `blocker_type=human_approval`，不增加单独的等待状态。条件解除后默认只返回 `blocked_from`；生成新 revision 时由 `NEW_REVISION` 特殊转换直接进入 `QUALIFIED`。

v0.1 不设置 `FAILED`：可修复失败通过治理回路处理，外部阻塞进入 `BLOCKED`，人工放弃进入 `CANCELLED`，脚本或环境异常以退出码 `2` 报告且不改变业务状态。

| 目标状态 | Artifact dependency（ready） | Governance gate（可转换） |
|---|---|---|
| `QUALIFIED` | 用户确认的冻结 Work Item revision | 必填字段通过；AC statement/evidence 非空且非 `TODO`；Human-owned 未决项为零 |
| `PLANNED` | Plan + Plan Decision Register + Working Set | 每个 AC 有验证映射；风险与受影响文档已列出；Human-owned Plan 决策均绑定 CD 且无未决项 |
| `IMPLEMENTING` | Plan + Working Set + Implementation handoff | `START_IMPLEMENTATION` 原子注册 handoff；R2 已获得实施前 Human approval；handoff 与当前 revision/attempt/Plan/Working Set 绑定 |
| `REVIEWING` | Implementation + Knowledge Delta + Review handoff + 冻结 subject | `START_REVIEW` 组合门禁校验实现、文档、handoff、session、commit/diff；无未处置 STALE |
| `VALIDATING` | 当前 revision/subject 对应的 accepted Review | 所需 Reviewer 数量满足；blocking findings 为零；Review 直接通过 `ACCEPT_REVIEW` 进入本状态 |
| `VERIFIED` | 当前 subject 对应的 PASS Validation | 仅 R2 使用；所有 AC 为 PASS，等待最终 Human approval |
| `CLOSED` | PASS Validation + Result | R0/R1 通过 `PASS_AND_CLOSE` 原子校验候选投影；R2 另需最终 Human approval 后 `CLOSE` |

`.polaris/workflow.json` 保存当前项目实际使用且版本锁定的节点、边、依赖和门禁 ID；`tools/polaris/workflow/default-workflow.json` 只用于初始化。`transition_task.py` 只接受图中边并先运行对应 validators，Skill 不直接编辑 `state` 字段。v0.1 遇到 `polaris_version` 或 `workflow_version` 不匹配时拒绝正常执行，不做隐式迁移。

版本升级必须先 vendoring 目标协议，再显式运行 vendored `migrate_project.py`。`workflow/migrations.json` 是迁移路径唯一且 append-only 的注册表，一次只执行一个从当前版本到目标版本的相邻步骤；历史步骤必须保留以校验已提交记录。Migration protocol v2 保留 `replace_version` / `append_version_event`，并增加 `replace_version_and_workflow` / `append_mapped_workflow_event`。`0.1.19 → 0.1.20` 原子替换冻结 workflow 为 `0.1.3`，追加带源/目标状态及旧版本字段的迁移事件；旧 `IMPLEMENTED`、`DOCS_SYNCED` 映射到 `IMPLEMENTING`，旧 `REVIEWED` 映射到 `VALIDATING`，其余治理状态保持含义。迁移以 `.polaris/migrations/MIG-*.json` 记录 `IN_PROGRESS/COMPLETED`、各任务 sequence 和状态映射；重跑必须可恢复且不得重复事件。未知路径、跨版本跳跃、未声明的 workflow 变化、任务集合并发变化和不完整记录都必须机械拒绝。

迁移占用任务转换锁时必须写入结构化 owner：迁移 ID、任务 ID、主机名、PID 和创建时间。重跑只允许接管同一迁移在同一主机上、且原 PID 已确认不存在的锁；活跃 PID、其他迁移、其他主机、空锁或损坏锁一律拒绝。这样既能从进程崩溃或机器重启恢复，又不把真实并发误判为遗留锁。

vendoring 更新必须先在目标仓库外的隔离事务目录中完成 Skill 渲染、协议复制、模板物化、安装清单生成与哈希校验，再备份全部受影响路径并进入替换阶段。事务 journal 使用 `STAGING/PREPARED/APPLYING/COMMITTED` 状态和主机/PID owner；普通异常立即恢复旧文件，同一主机上已死亡进程留下的 `PREPARED/APPLYING` 事务在下次运行前恢复，活跃或其他主机事务不得接管。强制更新默认先验证旧清单并拒绝受管文件漂移；丢弃漂移必须使用独立显式选项。

除初始化全新项目、vendoring 和显式迁移外，任何会写入项目、任务、artifact、恢复索引或实时进度的正常脚本，都必须先通过同一个协议兼容门禁：项目版本等于 vendored `VERSION`，冻结 workflow 等于项目 workflow，涉及任务时任务版本也必须一致。版本不匹配期间只允许校验、检查和显式迁移，不允许产生混合版本状态。

## 8. Context Bootstrap 与 Working Set

固定恢复顺序：

```text
AGENTS.md
  → .polaris/project-index.json
  → active task state + frozen Work Item
  → working-set.json
  → affected module index
  → referenced Decision / Exploration
  → code entry points and tests
  → deeper history only when a concrete unknown requires it
```

### Working Set 规则

- `project-index.json` 只含项目 ID、活跃任务摘要、blocker、每项 next action、一个 recommended task/action 和固定链接，并通过 Schema 校验。
- `working-set.json` 的 entries 使用 `Documents / Code / Tests / Decisions / Explorations / Unknowns` section，并为每项保存 path、reason 和 discovered_from。
- 每个条目记录 `path + reason + discovered_from`；代码只列入口和直接相关区域，不复制代码正文。
- 默认先定位再读取、先局部再扩展。新增内容必须由具体问题或依赖链触发。
- 文档负责导航、约束和原因；代码、测试、构建结果负责当前事实。冲突时登记 `documentation_stale`，不得静默选边。
- 工作集是可替换缓存，不是长期知识库；可在任务推进中增删，所有持久结论回写项目文档、Decision 或 Exploration。

### 可选 Code Intelligence 协议

- v0.1 的唯一正式 Provider 是 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph)。`providers/code-intelligence/codegraph.json` 声明其 MCP `codegraph_explore` 和 CLI `status`、`explore`、`sync` 能力；核心 record 使用 Provider-neutral 的新鲜度和回退字段。
- `.codegraph/` 由用户创建和维护。Polaris 允许用户显式运行 `polaris code-intelligence add codegraph --repo .`，但绝不安装、初始化、启动或配置 Provider、watcher、daemon、锁或 MCP；缺少 marker 或策略禁用时直接回退源码，不生成新的阶段 record。
- Provider 原生 watcher 与连接时 reconciliation 是保持索引接近工作树的主机制。Polaris 只在阶段入口、已知索引冻结或最终 Documentation Sync 的有界点读取 status；仅在 status 表示 pending 时至多执行一次 `codegraph sync`，随后至多复查一次，绝不等待或轮询。
- 记录的结论限定为检查时：`CURRENT_AT_CHECK`、`PARTIAL_STALE`、`INDEX_STALE`、`NOT_VERIFIED` 或 `UNAVAILABLE`，不得宣称与某个 Git commit 严格一致。逐文件 stale point 必须记录路径和原因；文件仍存在时 Agent 直接读取源码并记录 `READ_SOURCE`，已删除时检查注册 subject 的 Git diff 并记录 `INSPECT_GIT_DIFF`；索引级失效使用 `SEARCH_SOURCE` 和 Git 证据。
- Planning、Implementation 与 Reviewer 只在冻结范围内使用图关系；返回路径必须经源码确认才可进入 Working Set，Reviewer 必须独立查询。响应的局部 stale 不会丢弃其余图线索，但 stale 路径不能直接作为编辑或 Review 结论。
- 只有阶段实际执行 Provider `status`、`sync` 或 `explore` 操作时才写耐久 record，并准确记录成功、失败和新鲜度；未执行操作时省略 artifact 引用。图不扩展 scope，也不是 Workflow gate；Validation 完全不调用 CodeGraph，仍只依赖源码、Git、构建、测试、静态检查和 Human Check。
- Git 只保存绑定 Provider、阶段、subject、目的、有限摘要、响应哈希、新鲜度、stale point 与源码回退证据；原始响应只进入 ignored runtime。已提交 v1 record 是不可变历史证据，迁移后标为 `retired_provider_evidence`，不能支持新的新鲜度结论。

## 9. 确定性脚本

全部使用 Python 标准库；无安装器、无共享服务。所有脚本必须使用跨平台的路径、编码、换行、原子写入、锁和进程能力实现，禁止把 Bash、PowerShell 或某一文件系统的行为当作共同前提；必须为平台差异增加机械测试。权威产物采用 JSON，Validator 实现 Polaris v0.1 明确定义的有限 Schema 子集，只支持 `required / type / enum / const / pattern / minimum / minLength / properties / items / minItems / uniqueItems / additionalProperties` 等实际使用能力，不宣称兼容完整 JSON Schema 标准，也不解析 YAML 或任意 Markdown。统一退出码：`0=PASS/非阻断 WARN`、`1=规则失败`、`2=输入/系统错误`，并支持 `--json` 输出。

| 脚本 | 最小职责 |
|---|---|
| `init_project.py` | 在 vendored 协议包已存在的前提下创建 `.polaris/`、复制默认 graph/config，不覆盖已有文件 |
| `init_task.py` | 分配 Task ID，通过统一物化器创建 r001 与完整任务目录，追加事件 |
| `new_revision.py` | 复制当前 revision 为下一不可变修订，记录失效范围 |
| `build_working_set.py` | 根据 Work Item、模块索引和显式引用生成/刷新结构化工作集 |
| `refresh_project_index.py` | 从项目和任务 Authority 原子刷新结构化恢复索引 |
| `build_implementation_handoff.py` | 从当前 revision、Plan、Working Set 与 prior Review 构造不可变 Implementer 输入包 |
| `internal/task_layout.py` | 集中定义所有任务相对路径、动态 revision/attempt 渲染和模板样例投影 |
| `materialize_task_layout.py` | 从 `internal/task_layout.py` 生成模板样例树和真实任务目录，并校验生成物与平铺模板正文一致 |
| `update_implementation_progress.py` | 通过明确事件原子更新 ignored 的线性步骤进度；拒绝 session 接管、跳步、回退、未知验收 ID 和非法 blocker |
| `doctor_project.py` | 只读聚合环境、协议、Authority、清单、迁移、索引、任务与操作残留诊断，输出版本化报告、证据和人工动作 |
| `record_code_intelligence.py` | 写入不可变的精简 Code Intelligence Record；只接受已检查的 v2 新鲜度、stale point 和源码回退证据 |
| `code_intelligence_runtime.py` | 内部阶段工具：读取一次 status、按需至多 sync 一次并复查一次，或分类 explore 响应；不暴露为用户 CLI 命令 |
| `configure_code_intelligence.py` | 启用并优先一个已配置 Provider，保留现有索引范围，不安装或运行 Provider |
| `validate_project.py` | 检查目录、ID、结构化索引、活动任务、dangling refs、graph schema |
| `validate_task.py` | 检查 revision、artifact JSON、commit/diff hash、finding、AC evidence、docs delta 和 closure eligibility |
| `transition_task.py` | 获取任务锁，校验合法边与 gate，追加带 sequence 的事件，再原子替换 `state.json` |
| `rebuild_state.py` | 校验事件序列并从 `events.jsonl` 重建 `state.json` 投影 |
| `check_docs.py` | 将 changed paths 与 Knowledge Delta 对照，拒绝未解释的文档影响 |

Doctor 不定义第二套合法性规则：项目和任务结论必须调用现有 Validator 与协议模块，独立检查只覆盖运行环境、调用边界和未完成操作残留。诊断必须尽量执行全部安全检查，不因首个失败停止；报告按 `schemas/doctor-report.schema.json` 为检查项使用 `PASS/WARN/FAIL`、evidence 与 actions，只有 Doctor 自身无法产出检查项时顶层状态才使用 `ERROR`。Doctor 永远不自动修复、迁移、刷新索引或删除锁/事务目录，且运行前后项目文件必须保持字节一致。

`transition_task.py` 保持为唯一状态写入口，只负责编排锁、Workflow 规则、事件追加、`state.json` 原子替换和 Project Index 刷新。`internal/transition_gates.py` 只读校验 gate，`internal/transition_effects.py` 只计算候选状态、目标状态和事件内容，二者都不得直接写状态或事件。Review 校验按共享 artifact 引用、author response、冻结 handoff 和 finding lifecycle 分别放在 `internal/artifact_protocol.py`、`internal/review_response_protocol.py`、`internal/review_handoff_protocol.py` 与 `internal/review_protocol.py`；`internal/review_protocol.py` 保留原有公开导入名称的兼容重导出。

Implementation、Knowledge Delta、Review、Validation 和 Result 的权威 JSON 必须绑定当前适用的 `task_id / work_item_revision / artifact_attempt / subject_base_commit / subject_head_commit / subject_diff_hash`。Implementation 绑定编码 checkpoint，Knowledge Delta 与后续 Review/Validation/Result 绑定包含最终项目文档的 subject。保存这些治理 JSON 后，后续 transition event 记录其 `artifact_path / artifact_content_hash / artifact_commit`；`artifact_commit` 不写进 artifact 自身，避免产生无法满足的提交自引用。治理产物自身不会改变 subject hash，从而避免 Review 必须审查自身的循环依赖。任何 subject path 变化都会生成新的 subject commit/hash，并使旧 Review 和 Validation 失效。

Subject 默认包含 Work Item scope 内的源代码、测试、构建配置和 `docs/`；排除 `.polaris/tasks/<task-id>/` 中的 Review、Validation、event、state、Result 等治理产物。Vendored Skills、`tools/polaris/` 或 `.polaris/workflow.json` 的修改属于协议升级，不得夹带在普通工程 Task 中。

Validation evidence 至少记录 `acceptance_id / command_or_check / cwd / environment_summary / started_at / exit_code / result / output_path_or_hash`。大型原始日志可以只保存受版本控制的摘要和内容哈希，但 PASS 结论必须能够由记录的命令或 Human Check 引用复现。

`events.jsonl` 是合法状态转换的 append-only 记录，`state.json` 是可重建投影。每个事件包含连续 `sequence`、前后状态、Work Item revision、artifact 引用、subject/artifact commit、subject diff hash 和时间。`transition_task.py` 使用任务级锁文件避免并发写入；若进程在事件追加后、state 替换前中断，后续校验必须通过事件重建 state。事件序列损坏时返回退出码 `2`，不得猜测或自动跳过。

测试必须包含：happy path、缺 Work Item、非法前进或回退、revision 过期、Review 对错 commit/diff、AC 缺证据、未处置 STALE、BLOCKED 恢复、事件/state 不一致重建、并发锁冲突、CLOSED 被手工伪造。

## 10. 独立 Implementer 与对抗 Review 协议

### Independent Implementation

1. 主任务是唯一用户入口和状态机所有者；自动路径中不修改 subject，只负责生成/注册 handoff、派发或续接 Worker、等待、读取进度、校验产物和执行转换。
2. 先生成 `implementations/rNNN/handoff-NNN.json`，再由 `START_IMPLEMENTATION` 原子校验和注册。handoff 冻结 Work Item、Plan、Working Set、项目规则、subject base、prior Review（返工时）、确定性输出路径和可选实时进度路径。
3. Work Item 的 `implementation_dispatch.authorized=true` 是“确认并执行”对当前 revision 全部 Implementer attempts 的显式授权。宿主按自身执行附录在同一本地项目和 checkout 创建隔离 worker；worker 不继承主聊天，也不默认使用 worktree。Codex 的 worker 是可见新任务，Claude Code 的 worker 是保留 agent ID 的非 fork `polaris-implementer` subagent。
4. Implementer 标题固定为 `Polaris Implement · <TASK> · <REVISION> · attempt <N>`。创建前先复用与 handoff 绑定的有效 Implementation artifact，其次只按适配器声明的稳定身份复用唯一 worker。多条或不明确记录时不得猜测，回退同会话执行。
5. Implementer 只接收 task ID 与已注册 handoff，不接收主聊天、实现建议或预期结果。它拥有本轮代码、测试、构建文件和项目文档的单写者权限，但不执行 Graph 转换、Review、Validation 或关闭。
6. `implementation_steps` 在 Implementation artifact 中形成耐久终态证据。宿主需要实时报告时可用 `INITIALIZE / DEFINE_STEPS / START_STEP / COMPLETE_STEP / BLOCK_STEP / RESUME_STEP / SKIP_STEP / APPEND_STEP` 维护 ignored 快照；不能重排、删除、改名或回退。
7. `.polaris/tasks/<TASK>/runtime/progress.json` 是可选本机遥测；存在时 current、completed 和 remaining 由步骤状态推导，主任务按需格式化展示。门禁不得要求该 ignored 文件存在，也不得要求它与耐久 `step_results` 完全相等；不生成 Markdown 副本、Task DAG 或主观百分比。
8. 每个任务的 `runtime/` 子目录默认 Git ignored，不影响工作树 checkpoint，也不承诺跨电脑恢复。正式 Implementation、Knowledge Delta、commit/diff 和 event 继续写入耐久 Authority。主任务可随时读取进度；若整个宿主停止运行，快照只代表最后一次成功更新。
9. Implementation artifact 必须绑定 handoff path/hash、Implementer session 和终态 `step_results`。同一个 Implementer worker 随后在 `IMPLEMENTING` 内执行 `documentation-sync`，写回 Knowledge Delta 和最终 subject checkpoint。主任务构建 Review handoff，并用一次 `START_REVIEW` 组合校验和注册全部产物。
10. Review 或 Validation 返工生成新 attempt、新 handoff 和新的 Implementer 任务；prior Review 通过 handoff 传递，Implementer 写 Review Response。不同 attempt 不复用 Implementer session。
11. 宿主缺少创建、查找、等待或续接能力时，主任务使用同一 handoff 执行 `same_session` fallback；已有进度文件可继续更新，但不得为了门禁新建它。需明确提示即时状态响应可能延迟；不得仅因宿主能力不足把业务任务置为 `BLOCKED`。

### Independent Review

1. Implementer 完成 Implementation checkpoint 和 Documentation Sync 后停止实现与审查，不得自审后直接进入 Validation；主任务只保留宿主调度、等待、Authority 重读和机械转换职责。
2. R1/R2 优先由宿主按执行附录在同一本地 checkout 创建新的 Reviewer worker；当前 Codex 使用可见新任务，Claude Code 使用非 fork `polaris-reviewer` subagent。Reviewer 不继承主任务或 Implementer 的聊天历史，只接收 task ID、Reviewer slot 和已注册 handoff 路径。不得使用继承历史的 fork，也不默认使用独立 worktree。R0 允许主任务同会话，但必须重新加载冻结合同和最终 Patch，执行隔离式 adversarial pass。
3. Work Item 的 `review_dispatch.authorized=true` 是“确认并执行”对本 revision 自动创建全部必需 Review 任务的权威记录。宿主缺少创建、查找或等待能力，或者派发失败时，状态保持 `REVIEWING`，显示 `REVIEW_HANDOFF_READY` 和完整手动提示；不得仅因宿主不支持自动派发而进入 `BLOCKED`。
4. Review 任务标题固定为 `Polaris Review · <TASK> · <REVISION> · attempt <N> · reviewer <SLOT>`。创建前先复用已有有效 Review artifact，其次复用唯一的同名任务；同一 key 不得重复创建，发现多个同名任务时回退人工处理。
5. Reviewer 只接收：冻结 Work Item、Plan、Working Set、`subject_base_commit`、最终 `subject_head_commit`、`subject_diff_hash`、项目规则、相关模块文档、实现记录、Knowledge Delta 和可复现证据。
6. 第一遍检查 **Specification Compliance**：是否解决正确问题、越界、漏掉 AC、引入未授权行为。
7. 第二遍检查 **Engineering Quality**：正确性、生命周期、并发、安全、性能、兼容性、可维护性、测试缺口和反例。
8. Finding 使用稳定 ID，包含 `severity / location / claim / evidence / required_action / status`。权威记录写入 `reviews/<revision>/review-<attempt>.json`；第二 Reviewer 使用 `review-<attempt>-2.json`，不生成同名 Markdown 副本。
9. `critical`、`high`、任何 AC 不满足或越界均为 blocking。作者必须逐项回复；Reviewer 必须重新检查新 diff/证据后才能关闭。
10. Review JSON 必须记录 `implementer_session_id / reviewer_session_id / work_item_revision / subject_base_commit / subject_head_commit / subject_diff_hash / reviewed_at`。Validator 检查引用、哈希和 R1/R2 session ID 不同；该机制是可审计治理，不是防恶意伪造的身份认证。
11. R1 需要一名独立 Reviewer。R2 默认需要一名独立 Reviewer；涉及安全、不可逆数据迁移或公共持久化格式变更时需要两名独立 Reviewer，按 slot 顺序派发，任一 `REJECT` 即停止本轮，全部 `ACCEPT` 才能推进。
12. 最多三轮 author-reviewer 循环；`REJECT` 通过 Graph 回到 `IMPLEMENTING`。任何代码、测试或项目文档变化都会生成新的 subject checkpoint 和 subject diff hash，并使旧 Review/Validation 失效。每轮使用新的确定性任务标题和独立 Reviewer session；三轮后仍有争议则进入 `BLOCKED` 并按 Decision Owner 升级，不启动“仲裁 Agent”替代 Human-owned 决策。
13. 只有 Reviewer 可在 Review JSON 中写 `ACCEPT` 或 `REJECT`；Review 任务只写不可变 Review artifact，由原 `engineering-task` 编排上下文验证、注册并调用 transition 脚本推进状态。

## 11. Recovery 与失败探索

### Recovery protocol

新会话必须先运行项目/任务校验，再按第 8 节恢复路径读取。恢复输出只回答：

- 当前冻结任务和 revision 是什么？
- 当前状态、blocker、最后一个有效事件是什么？
- 当前 recommended next action 是什么？
- 完成该动作所需的最小 Working Set 是什么？
- 当前处于 Implementation 时，最近一个有效实时进度快照是什么？

只有状态冲突、引用损坏或证据缺失时才向历史扩展。聊天记录不得成为恢复前提。

### Durability checkpoint

- Vendored Skills、`tools/polaris/`、`.polaris/` 的耐久状态和任务代码均纳入 Git；`.polaris/tasks/<TASK>/runtime/` 是明确忽略的本机瞬时例外。
- `REVIEWING`、`VALIDATING`、`VERIFIED` 和 `CLOSED` 的 subject 证据必须绑定本地 checkpoint commit；Polaris 不自动 push、merge 或发布。
- Fresh-session 可以继续当前工作树；Fresh-clone 只保证恢复到最近一次已提交的阶段边界，不承诺恢复尚未保存或尚未提交的编辑器内容。
- Review 和 Validation 只接受 Git commit SHA，不接受 working-tree marker。创建 checkpoint 前必须识别并保护用户已有的无关改动，不能把不属于 Task scope 的变化混入证据 commit。

### Failed Exploration 模板

```json
{
  "id": "EXP-0001",
  "task": "TASK-0001@r001",
  "module": "<module>",
  "hypothesis": "<why attempted>",
  "attempt": "<what was done>",
  "evidence": "<commands/results/diff>",
  "outcome": "rejected",
  "failed_because": "<cause>",
  "retry_when": "<specific changed condition>",
  "related": []
}
```

`outcome` 只能是 `rejected` 或 `inconclusive`。仅影响当前任务的探索留在任务目录；可复用结论经 documentation-sync 提升到 `.polaris/explorations/` 或模块文档。平时不加载，只有关键词、模块或假设相关时检索。

## 12. Progressive Rigor

| 等级 | 适用 | 强制要求 |
|---|---|---|
| `R0` | 局部、可逆、低风险的文档/测试数据/机械修改 | Work Item、最小 Plan、机械验证、Knowledge Delta；允许隔离式同会话 Review，但不得自判 CLOSED |
| `R1` | 默认的非平凡代码任务 | 全套 artifact、独立单 Reviewer、build/test 证据、docs check |
| `R2` | 公共 API/格式、架构边界、并发/安全、资源生命周期、重大性能路径 | R1 + 实施前 Human approval + 扩展验证矩阵 + 最终 Human approval；安全、不可逆数据迁移或公共持久化格式变更需要两名独立 Reviewer |

Work Item 的 `risk_flags` 用于机械计算最低 rigor：任意 risk flag 为真时最低为 R2；R0 仅允许文档、测试数据或明确可逆且不触及生产行为的机械修改。Agent 可以提高等级；降低机械建议等级必须记录绑定当前 Work Item revision 的 Human Change Decision。首个 Horizon/Vision 试点默认使用 R1；涉及 RHI 公共边界或 GPU 生命周期则使用 R2。

## 13. MVP 里程碑与实施顺序

### M0 — 协议冻结（第 1–2 天）

- [x] 冻结 ID、状态、revision、attempt、artifact、finding、evidence、event 的 JSON 结构
- [x] 写包含前进、返工、阻塞、取消和新 revision 边的 `default-workflow.json`
- [x] 冻结三档 rigor、risk flag、Reviewer 数量和 Human Approval 规则
- [x] 建立合法/非法 fixture，包括 commit/diff hash 失配和事件/state 不一致

完成标准：仅凭 schema 和 fixture 可以明确判断每个状态转换应 PASS 还是 FAIL。

### M1 — Repo skeleton 与 Skills（第 3–5 天）

- [x] 建源仓库目录、JSON artifact 模板、必要 Markdown 上下文模板和八个 Skill
- [x] 建立版本化 `hosts/*/adapter.json` 契约，从宿主无关 Skills 生成 Codex/Claude Code 目录与 worker 文件，并将适配器、脚本、Schema、模板和 Workflow vendoring 到 `tools/polaris/`
- [x] 将 Adapter 升级到 v2，校验真实入口、overlay 新增边界、symlink confinement 与宿主能力依赖
- [x] 用安装清单登记 vendored 文件归属、跨平台文本哈希/严格字节哈希，并以预生成、备份、回滚和崩溃恢复事务执行强制升级
- [x] 建立显式相邻迁移注册表、可恢复迁移记录与 append-only 任务版本事件
- [ ] 用最小 fixture 验证当前 Codex 宿主能够发现仓库内 Skills
- [x] 用 Claude Code 2.1.220 实际验证 `/engineering-task` 项目 Skill 与 `polaris-reviewer` 非 fork subagent 的发现和拒绝无 handoff 调用
- [x] `engineering-task` 实现仅显式触发、恢复、分派、门禁停止规则
- [x] 阶段 Skill 明确输入、输出、owner 和禁止事项
- [x] 固定对话检查点、Work Item 预览确认和阶段结果标记

完成标准：用户显式调用宿主对应的 `engineering-task` 入口提交一个模糊 R1 任务时，宿主先建立 Work Item，不直接改代码；未显式调用时不进入 Polaris。

### M2 — Mechanical core（第 6–9 天）

- [x] 实现 init、revision、validate、transition、state rebuild、docs check
- [x] 实现只读聚合 Doctor、版本化诊断报告与多故障/无写入测试
- [x] 实现唯一正式的 [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph) Provider、用户显式 add、watcher/connect reconciliation、有限 sync、新鲜度/失效点记录与非阻断源码回退测试
- [x] 所有工作流状态转换经 `transition_task.py`
- [x] `QUALIFY` 机械拒绝空白或 `TODO` 的验收描述与证据
- [x] 单元测试覆盖第 9 节失败场景

完成标准：非法跳转、过期 Review、错误 commit/diff、缺 AC 证据、未处置文档漂移和损坏事件序列均被脚本稳定拒绝；合法事件可以重建 `state.json`。

### M3 — Review、Recovery 与 Working Set（第 10–12 天）

- [x] 实现独立 Implementer 自动派发、确定性任务复用、handoff/result 绑定和同会话回退
- [x] 实现事件驱动实时进度 JSON、本机忽略规则、session 所有权与恢复读取
- [x] 实现验收标准绑定的线性 Implementation steps、追加式变更和终态 step results 门禁
- [x] 实现绑定 revision、commit、diff hash 和 session attestation 的 reviewer handoff 与 finding lifecycle
- [x] 实现渐进恢复与 Working Set 刷新
- [x] 实现 failed exploration 的任务内记录与项目级提升
- [x] 实现宿主支持时自动创建可见独立 Review 任务，并在不支持时回退手动交接

完成标准：全新受支持宿主会话不读取旧聊天即可指出当前状态、blocker、next action，并开始正确节点。

### M4 — Horizon 试点（第 13–17 天）

- [ ] 选择一个 1–3 天、涉及 2–5 个文件、具有明确 build/test 的 R1 任务
- [ ] 推荐范围：Horizon RHI/Vulkan backend 的一个垂直切片，而不是“实现完整 Vulkan backend”
- [ ] 用普通 Codex 流程留一份基线记录，再用 Polaris 跑完整闭环
- [ ] 记录返工、Reviewer findings、恢复耗时、流程开销和漏检
- [ ] 计算 `Adversarial Review Yield`：独立 Reviewer 发现、且 Implementer 与基础测试未发现的有效问题数量

完成标准：任务只能经 Documentation Sync、独立 Review、AC 证据和 docs check 关闭；新会话可在 10 分钟内恢复并继续，Fresh Clone 可恢复到最近一次 checkpoint commit。

### M5 — Vision 复验与 v0.1 结论（第 18–21 天）

- [ ] 选择一个带图像正确性或性能证据的 Vision R1/R2 任务
- [ ] 修订一次 Skills/validators，但不新增产品层级
- [ ] 输出 `v0.1-evaluation.md`：有效机制、摩擦点、流程自动化候选痛点、放弃项

完成标准：至少两个不同工程任务闭环，并能够用证据决定是否继续下一阶段。CLI 只作为现有脚本的安装与分发入口。

## 14. v0.1 总体验收标准

- [ ] 目标仓库仅依赖 Python 和 vendored `tools/polaris/` 即可运行；CLI 可从该目录安装，不需要第三方运行时依赖。
- [ ] 非平凡任务不会在 Work Item 冻结前进入 Implementation。
- [ ] 每个暂停点和阶段结果都按固定字段展示，Work Item 未经用户确认不进入 `QUALIFIED`。
- [ ] 自动路径中主任务保持为可查询控制入口；Implementer 只从冻结 handoff 工作并持续写入最近有效进度。
- [ ] Implementation artifact 绑定当前 handoff path/hash 和终态 step results；不同返工 attempt 使用新的确定性 Implementer 任务。
- [ ] 每个前进、返工、阻塞、取消和新 revision 转换都可由 graph + artifact + gate 机械解释。
- [ ] Agent 无法通过正常流程自行写入 `VERIFIED` 或 `CLOSED`。
- [ ] R1/R2 Review 来自独立上下文；R0 使用隔离式 adversarial pass；全部覆盖 specification 与 engineering 两层。
- [ ] Review、Validation 和 Human Approval 均绑定当前 Work Item revision、checkpoint commit 和 diff hash，代码或文档变化会使旧证据失效。
- [ ] 所有 AC 均能追溯到可复现证据；编译通过不能单独代表完成。
- [ ] 任一任务可在无聊天历史的新会话中渐进恢复，并可从 Fresh Clone 恢复到最近一次已提交阶段边界。
- [ ] 项目增长不会要求启动时加载全部文档；Working Set 有明确理由链。
- [ ] 需求变化产生新 revision，不静默改写执行合同。
- [ ] 失败探索不会丢失，并包含明确 `retry_when`。
- [ ] 代码变化对项目知识的影响已更新、标记或明确判定 `NO_CHANGE`。
- [ ] Documentation Sync 在最终独立 Review 前完成，Reviewer 审查包含代码、测试和文档的最终 Patch。
- [ ] `events.jsonl` 可重建 `state.json`，并发写入、事件断裂和版本不匹配会被拒绝。
- [ ] 所有代码变更均完成 Windows、macOS、Linux 兼容性审查；核心规则测试不依赖可选平台能力，真实平台能力不可用时只跳过对应集成测试。
- [ ] Horizon 和 Vision 各完成至少一个真实闭环，并形成可比较的评估记录。
- [ ] 两个试点均记录 `Adversarial Review Yield`，用于判断独立 Review 带来的收益是否值得其时间和 token 成本。
- [ ] v0.1 的 CLI 仅为现有脚本的薄分发层；没有 daemon、Dashboard、scheduler、自定义 runtime 或 database。
- [ ] v0.1 中没有 Task DAG、自动归档或跨任务依赖调度。

## 15. 开工第一批任务

按以下顺序直接实施：

1. 创建第 4 节源仓库骨架和目标仓库 vendoring fixture。
2. 先写权威 JSON artifact 结构、有限 Schema 子集与完整 `default-workflow.json`，不要先写长 Skill。
3. 建一个合法任务以及覆盖非法边、过期 revision、错误 commit/diff、事件损坏和证据缺失的非法 fixture。
4. 实现 `validate_task.py`、`transition_task.py` 与 `rebuild_state.py`，锁定“Agent 不拥有完成状态”。
5. 写 `engineering-task/SKILL.md`，让其只围绕 graph、owner、artifact、checkpoint 和 gate 编排。
6. 补齐阶段 Skills、JSON artifact 模板、必要 Markdown 上下文模板、Documentation Sync 和 reviewer handoff。
7. 将 Skills 和协议实现 vendoring 到 Horizon fixture，验证发现、版本锁定和 Fresh Clone Recovery。
8. 用 Horizon 的一个小型 R1 任务 dogfood；遇到摩擦先改协议和 Skill，CLI 保持薄分发层，不扩建 UI。

## 16. 长期产品方向（不属于 v0.1）

Polaris 的长期方向是演化为运行在不同 Coding Agent 之上的轻量工程控制层：

```text
Polaris Thin App / Control Plane
              │
              ▼
         Agent Runtime
              │
      Codex / Claude Code / Others
```

长期能力可以包括多任务依赖管理、跨项目状态、可视化界面、多模型适配和 Reviewer arbitration，但必须建立在 v0.1 的真实试点证据之上。v0.1 不把薄 CLI 扩展为 daemon、scheduler、数据库或自定义 Agent Runtime。

v0.1 的核心边界是：Polaris 定义不同 Agent 应读取什么、承担什么职责、产出什么证据，以及满足哪些门禁后任务才能继续；Codex 或 Claude Code 负责 Session、Agent Loop、工具调用、执行环境和上下文运行时。

## 一句话定义

> **Polaris v0.1 是由受支持 Coding Agent 宿主执行、由仓库状态承载、由声明式 Graph 与确定性校验约束的软件工程工作协议。**
