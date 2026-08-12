# Polaris v0.1 —— AI Engineering Workflow System 实施计划

> 状态：Ready to implement
> 目标版本：v0.1
> 产品形态：Repo-native Skill System
> 宿主 Runtime：Codex
>
> **已确认的 MVP 决策：v0.1 不实现 CLI，也不提供 shell wrapper。Polaris Skills、辅助脚本、Schema、模板和默认 Workflow 全部 vendoring 到目标仓库；所有入口由仓库内 Codex Skills 和 Python 脚本提供。**

## 1. 目标与定位

Polaris v0.1 是一套运行在 Codex 之上的、可持久化的软件工程协议：

```text
Workflow Skills
+ Repository State
+ Deterministic Validators / Helpers
+ Codex Agent Runtime
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

## 2. MVP 范围

### 必须实现

- 一个顶层 `engineering-task` Skill 和六个阶段 Skill。
- Skills、辅助脚本、Schema、模板和默认 Workflow vendoring 到目标仓库并纳入 Git。
- `.polaris/` 仓库状态协议、模板与默认工作流图。
- Work Item 修订、任务状态、事件账本、工作集、Review、Validation、Result。
- 项目初始化、任务初始化、状态转换、结构校验、文档影响检查、工作集生成脚本。
- 独立 Codex 会话的对抗审查协议。
- Fresh-session / fresh-clone 的渐进恢复协议。
- `R0 / R1 / R2` 三档渐进式严谨度。
- Horizon 首个试点；通过后在 Vision 做第二个试点。

### 明确不做

- **任何形式的 `polaris` CLI 或 shell wrapper，包括 `polaris status`、`polaris doctor` 等命令**
- daemon、watchdog、scheduler、队列或后台服务
- Dashboard、TUI、IDE 或独立 App
- 自定义 Agent Runtime、模型适配层或进程生命周期管理
- 数据库、向量库、知识图谱服务或事件服务
- 自动多任务调度、跨项目管理、实时进度百分比
- Task DAG、任务归档和跨任务依赖调度
- 通用领域 Skill 市场
- 自动合并、发布或远程 CI 编排

## 3. 架构边界

```text
Human
  │  owns intent, hard constraints, approvals
  ▼
Codex + Polaris Workflow Skills
  │  interpret graph, execute node-local loops
  ├───────────────┐
  ▼               ▼
Repository Code   .polaris/ authority state
  │               │
  └──── evidence ─┘
          │
          ▼
Deterministic Python scripts
  schema / references / gates / transitions / verdict
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

聊天、`project-index.md`、Markdown 报告均是导航、叙述或投影，不得覆盖权威 JSON 状态。旧 Review 或 Validation 不得覆盖更新后的代码事实；其绑定的 revision、commit 或 diff hash 不匹配时自动失效。

## 4. 仓库布局

### Polaris 自身仓库

```text
polaris/
├── README.md
├── AGENTS.md
├── VERSION
├── skills/
│   ├── engineering-task/SKILL.md
│   ├── requirement-analysis/SKILL.md
│   ├── architecture-planning/SKILL.md
│   ├── implementation/SKILL.md
│   ├── adversarial-review/SKILL.md
│   ├── validation/SKILL.md
│   └── documentation-sync/SKILL.md
├── templates/
│   ├── project-index.md
│   └── task/
│       ├── state.json
│       ├── work-item.json
│       ├── work-item.md
│       ├── plan.md
│       ├── working-set.md
│       ├── implementation.json
│       ├── implementation.md
│       ├── review.json
│       ├── review.md
│       ├── validation.json
│       ├── validation.md
│       ├── knowledge-delta.json
│       ├── knowledge-delta.md
│       ├── result.json
│       └── result.md
├── workflow/default-workflow.json
├── schemas/
│   ├── project.schema.json
│   ├── task-state.schema.json
│   ├── workflow.schema.json
│   ├── work-item.schema.json
│   ├── review.schema.json
│   └── validation.schema.json
├── scripts/
│   ├── init_project.py
│   ├── init_task.py
│   ├── new_revision.py
│   ├── build_working_set.py
│   ├── validate_project.py
│   ├── validate_task.py
│   ├── transition_task.py
│   ├── rebuild_state.py
│   └── check_docs.py
└── tests/
    ├── fixtures/
    └── test_*.py
```

### 接入后的目标仓库

```text
target-repo/
├── AGENTS.md
├── .agents/
│   └── skills/                    # vendored Codex Skills
│       ├── engineering-task/SKILL.md
│       ├── requirement-analysis/SKILL.md
│       ├── architecture-planning/SKILL.md
│       ├── implementation/SKILL.md
│       ├── adversarial-review/SKILL.md
│       ├── validation/SKILL.md
│       └── documentation-sync/SKILL.md
├── tools/
│   └── polaris/                   # vendored、项目锁定的协议实现
│       ├── VERSION
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
    ├── project-index.md           # 保持短小，只做恢复地图
    ├── workflow.json
    ├── decisions/
    │   ├── CD-*.json              # append-only，权威 Human Decision/Approval
    │   └── CD-*.md                # 可选可读投影
    ├── explorations/EXP-*.json    # 可跨任务复用的失败探索
    ├── tasks/
    │   └── TASK-0001/
    │       ├── state.json         # 可由事件重建的当前状态投影
    │       ├── revisions/
    │       │   ├── work-item-r001.json  # 权威执行合同
    │       │   └── WORK_ITEM-r001.md    # 可读投影
    │       ├── PLAN.md
    │       ├── WORKING_SET.md
    │       ├── implementations/r001/
    │       │   ├── attempt-001.json
    │       │   └── IMPLEMENTATION-001.md
    │       ├── knowledge/r001/
    │       │   ├── knowledge-delta-001.json
    │       │   └── KNOWLEDGE_DELTA-001.md
    │       ├── reviews/r001/
    │       │   ├── review-001.json
    │       │   └── REVIEW-001.md
    │       ├── validations/r001/
    │       │   ├── validation-001.json
    │       │   └── VALIDATION-001.md
    │       ├── results/r001/
    │       │   ├── result-001.json
    │       │   └── RESULT-001.md
    │       ├── evidence/r001/     # 可复现命令摘要、日志或其哈希
    │       ├── events.jsonl       # append-only，状态转换记录
    │       └── explorations/EXP-*.json
```

`.agents/skills/`、`tools/polaris/` 和 `.polaris/` 均纳入 Git。前两者是 vendored 协议包，`.polaris/` 是项目运行状态。`project.json` 必须记录 `polaris_version` 和 `workflow_version`。v0.1 开工前使用最小 fixture 验证宿主能够发现仓库内 `.agents/skills/`；如果宿主发现规则不同，只调整 vendoring 路径，不改变 Skills 随目标仓库版本化的决定。

JSON 文件是机械门禁的权威输入；同名 Markdown 只用于人类阅读，不参与状态判定。旧 revision 和旧 attempt 文件不可覆盖，`state.json` 仅保存当前有效 artifact 的指针。

## 5. Skill 列表与职责

| Skill | 责任 | 禁止事项 |
|---|---|---|
| `engineering-task` | 总入口；恢复状态；选择 rigor；解析 Graph；调用阶段 Skill；遇门禁停止 | 不直接宣布完成，不绕过 transition 脚本 |
| `requirement-analysis` | 澄清目标、验收、范围、硬约束、Decision Owner；生成并冻结 Work Item revision | 不替 Human 决定目标、破坏性边界或产品取舍 |
| `architecture-planning` | 构造最小工作集；调查代码；形成 delta-oriented Plan、风险与验证映射 | 不把推测写成项目事实，不无界加载仓库 |
| `implementation` | 按冻结 revision 和 Plan 小步实现；运行节点内 build/test/fix loop；记录偏差和证据 | 不修改 Work Item；不把本地测试通过等同完成 |
| `adversarial-review` | 在独立会话审查 spec compliance 与 engineering quality；管理 finding 生命周期 | 不接受作者自证；不依赖原实现会话的隐式上下文 |
| `validation` | 把 acceptance criterion 映射到可复现证据；运行规定验证；产出 verdict 输入 | 不弱化验收条件，不用主观总结代替命令结果 |
| `documentation-sync` | 分析知识 delta；更新或标记 stale 文档；提升可复用 Decision / Exploration | 不自动把未确认推断升级为权威知识 |

Skill 描述应按“何时必须触发的行为”编写，而不是做技术能力菜单。Skill 本身使用 fixture 做回归测试。

## 6. Work Item 与任务模型

### ID 与修订

- Task：`TASK-0001`
- Human Change Decision：`CD-0001`
- Failed Exploration：`EXP-0001`
- Work Item revision：`TASK-0001@r001`
- 权威文件：`revisions/work-item-r001.json`；可读投影：`revisions/WORK_ITEM-r001.md`。
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
  "known_unknowns": []
}
```

`base_commit` 必须是可解析的 Git commit SHA，不允许使用 working-tree marker。所有机械读取字段均存储在 JSON 中；Markdown 不使用可被误认为权威数据的自由格式 front matter。

### Delta-oriented change package

每个 Task 目录就是一个 Change Package，只保存：

- 预期行为或知识相对 `base_commit` 的变化
- 影响模块、接口、不变量和文档
- 明确不变的边界
- 实际代码 diff 与偏离 Plan 的原因
- 新增、更新、失效或无需变更的知识条目

权威 `knowledge-delta-<attempt>.json` 必须把每项标记为 `ADD / UPDATE / STALE / NO_CHANGE`，并给出目标路径和证据；Markdown 仅是投影。关闭前不得存在未处置的 `STALE`。

### Decision ownership

**Human-owned：**最终目标、验收边界、硬约束、禁区、公共 API/格式破坏、重大性能或安全取舍、任务取消。

**Agent-owned：**调查路径、工作集、方案比较、任务拆解、实现细节、测试补充、retry strategy、低风险文档同步。

**Mechanical-owned：**schema 合法性、引用完整性、节点 ready、transition 合法性、证据存在、关闭资格。

Human Decision 和 Approval 必须落入 append-only 的 `CD-*.json`，至少记录 `decision_id / approved_by / approved_at / approval_gate / work_item_revision / plan_hash / subject_diff_hash / decision`。实施前尚无 subject 时 `subject_diff_hash` 可以为 `null`，但必须绑定 `plan_hash`；最终审批必须绑定 `subject_diff_hash`。Validator 校验引用和绑定关系，但该机制属于可审计工程治理，不提供密码学身份认证。聊天中的同意只有写入 Change Decision 后才成为 Authority。

## 7. 声明式 Workflow Graph

默认主路径：

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING → IMPLEMENTED
      → DOCS_SYNCED → REVIEWING → REVIEWED
      → VALIDATING → VERIFIED → CLOSED
```

文档同步在独立 Review 之前完成，使 Reviewer 审查的 subject commit 同时包含代码、测试和项目文档，并让 Review Package 包含对应的 Knowledge Delta。Review 或 Validation 引发返工时，旧 Documentation Sync、Review 和 Validation 均失效，并按 Graph 回到相应节点重新执行。

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
| `QUALIFIED` | 冻结的 Work Item revision | 必填字段通过；Human-owned 未决项为零 |
| `PLANNED` | Plan + Working Set | 每个 AC 有验证映射；风险与受影响文档已列出 |
| `IMPLEMENTING` | `PLANNED` | R2 已获得实施前 Human approval |
| `IMPLEMENTED` | Implementation record + checkpoint commit | 实现者检查通过；所有偏离 Plan 已记录；subject commit 和 diff hash 已冻结 |
| `DOCS_SYNCED` | Knowledge Delta + docs checkpoint commit | 无未处置 STALE；必要 Decision/Exploration 已落盘；最终 Review subject 已冻结 |
| `REVIEWING` | 冻结 revision + subject base/head commit + subject diff hash + evidence | R1/R2 Reviewer session 与 implementer session 独立；R0 可使用隔离式同会话 Review |
| `REVIEWED` | 当前 revision/subject 对应的 Review JSON | verdict=`ACCEPT`；所需 Reviewer 数量满足；blocking findings 为零 |
| `VALIDATING` | Validation plan | Review 针对当前 revision、subject head commit 和 subject diff hash |
| `VERIFIED` | 当前 subject 对应的 Validation JSON | 所有 AC 为 PASS；验证命令退出码有效 |
| `CLOSED` | Result JSON | `validate_task.py` 全 PASS；R2 已获最终 Human approval |

`.polaris/workflow.json` 保存当前项目实际使用且版本锁定的节点、边、依赖和门禁 ID；`tools/polaris/workflow/default-workflow.json` 只用于初始化。`transition_task.py` 只接受图中边并先运行对应 validators，Skill 不直接编辑 `state` 字段。v0.1 遇到 `polaris_version` 或 `workflow_version` 不匹配时拒绝执行，不自动迁移。

## 8. Context Bootstrap 与 Working Set

固定恢复顺序：

```text
AGENTS.md
  → .polaris/project-index.md
  → active task state + frozen Work Item
  → WORKING_SET.md
  → affected module index
  → referenced Decision / Exploration
  → code entry points and tests
  → deeper history only when a concrete unknown requires it
```

### Working Set 规则

- `project-index.md` 只含项目目标摘要、活跃任务、blocker、可执行任务、一个 recommended next action 和链接；建议不超过 200 行。
- `WORKING_SET.md` 分 `Documents / Code / Tests / Decisions / Explorations / Unknowns`。
- 每个条目记录 `path + reason + discovered_from`；代码只列入口和直接相关区域，不复制代码正文。
- 默认先定位再读取、先局部再扩展。新增内容必须由具体问题或依赖链触发。
- 文档负责导航、约束和原因；代码、测试、构建结果负责当前事实。冲突时登记 `documentation_stale`，不得静默选边。
- 工作集是可替换缓存，不是长期知识库；可在任务推进中增删，所有持久结论回写项目文档、Decision 或 Exploration。

## 9. 确定性脚本

全部使用 Python 标准库；无安装器、无共享服务。权威产物采用 JSON，Validator 实现 Polaris v0.1 明确定义的有限 Schema 子集，只支持 `required / type / enum / pattern / items / additionalProperties` 等实际使用能力，不宣称兼容完整 JSON Schema 标准，也不解析 YAML 或任意 Markdown。统一退出码：`0=PASS`、`1=规则失败`、`2=输入/系统错误`，并支持 `--json` 输出。

| 脚本 | 最小职责 |
|---|---|
| `init_project.py` | 在 vendored 协议包已存在的前提下创建 `.polaris/`、复制默认 graph/config，不覆盖已有文件 |
| `init_task.py` | 分配 Task ID，创建 r001 与完整任务目录，追加事件 |
| `new_revision.py` | 复制当前 revision 为下一不可变修订，记录失效范围 |
| `build_working_set.py` | 根据 Work Item、模块索引和显式引用生成/刷新工作集骨架 |
| `validate_project.py` | 检查目录、ID、索引链接、活动任务、dangling refs、graph schema |
| `validate_task.py` | 检查 revision、artifact JSON、commit/diff hash、finding、AC evidence、docs delta 和 closure eligibility |
| `transition_task.py` | 获取任务锁，校验合法边与 gate，追加带 sequence 的事件，再原子替换 `state.json` |
| `rebuild_state.py` | 校验事件序列并从 `events.jsonl` 重建 `state.json` 投影 |
| `check_docs.py` | 将 changed paths 与 Knowledge Delta 对照，拒绝未解释的文档影响 |

Review、Validation 和 Result 的权威 JSON 必须绑定 `task_id / work_item_revision / artifact_attempt / subject_base_commit / subject_head_commit / subject_diff_hash`。`subject_*` 表示被审查和验证的代码、测试与项目文档 Patch。保存这些治理 JSON 后，后续 transition event 记录其 `artifact_path / artifact_content_hash / artifact_commit`；`artifact_commit` 不写进 artifact 自身，避免产生无法满足的提交自引用。治理产物自身不会改变 subject hash，从而避免 Review 必须审查自身的循环依赖。任何 subject path 变化都会生成新的 subject commit/hash，并使旧 Review 和 Validation 失效。

Subject 默认包含 Work Item scope 内的源代码、测试、构建配置和 `docs/`；排除 `.polaris/tasks/<task-id>/` 中的 Review、Validation、event、state、Result 等治理产物。Vendored Skills、`tools/polaris/` 或 `.polaris/workflow.json` 的修改属于协议升级，不得夹带在普通工程 Task 中。

Validation evidence 至少记录 `acceptance_id / command_or_check / cwd / environment_summary / started_at / exit_code / result / output_path_or_hash`。大型原始日志可以只保存受版本控制的摘要和内容哈希，但 PASS 结论必须能够由记录的命令或 Human Check 引用复现。

`events.jsonl` 是合法状态转换的 append-only 记录，`state.json` 是可重建投影。每个事件包含连续 `sequence`、前后状态、Work Item revision、artifact 引用、subject/artifact commit、subject diff hash 和时间。`transition_task.py` 使用任务级锁文件避免并发写入；若进程在事件追加后、state 替换前中断，后续校验必须通过事件重建 state。事件序列损坏时返回退出码 `2`，不得猜测或自动跳过。

测试必须包含：happy path、缺 Work Item、非法前进或回退、revision 过期、Review 对错 commit/diff、AC 缺证据、未处置 STALE、BLOCKED 恢复、事件/state 不一致重建、并发锁冲突、CLOSED 被手工伪造。

## 10. 独立对抗 Review 协议

1. 实现者完成 Implementation checkpoint 和 Documentation Sync 后停止，不得自审后直接进入 Validation。
2. R1/R2 在新的 Codex 会话或隔离的 reviewer agent 中启动 Review；Reviewer 不继承实现会话的聊天历史。R0 允许同会话，但必须重新加载冻结合同和最终 Patch，执行隔离式 adversarial pass。
3. Reviewer 只接收：冻结 Work Item、Plan、Working Set、`subject_base_commit`、最终 `subject_head_commit`、`subject_diff_hash`、项目规则、相关模块文档、实现记录、Knowledge Delta 和可复现证据。
4. 第一遍检查 **Specification Compliance**：是否解决正确问题、越界、漏掉 AC、引入未授权行为。
5. 第二遍检查 **Engineering Quality**：正确性、生命周期、并发、安全、性能、兼容性、可维护性、测试缺口和反例。
6. Finding 使用稳定 ID，包含 `severity / location / claim / evidence / required_action / status`。权威记录写入 `reviews/<revision>/review-<attempt>.json`，Markdown 只做可读投影。
7. `critical`、`high`、任何 AC 不满足或越界均为 blocking。作者必须逐项回复；Reviewer 必须重新检查新 diff/证据后才能关闭。
8. Review JSON 必须记录 `implementer_session_id / reviewer_session_id / work_item_revision / subject_base_commit / subject_head_commit / subject_diff_hash / reviewed_at`。Validator 检查引用、哈希和 R1/R2 session ID 不同；该机制是可审计治理，不是防恶意伪造的身份认证。
9. R1 需要一名独立 Reviewer。R2 默认需要一名独立 Reviewer；涉及安全、不可逆数据迁移或公共持久化格式变更时需要两名独立 Reviewer，且全部 `ACCEPT` 才能推进。
10. 最多三轮 author-reviewer 循环；`REJECT` 通过 Graph 回到 `IMPLEMENTING`。任何代码、测试或项目文档变化都会生成新的 subject checkpoint 和 subject diff hash，并使旧 Review/Validation 失效。三轮后仍有争议则进入 `BLOCKED` 并按 Decision Owner 升级，不启动“仲裁 Agent”替代 Human-owned 决策。
11. 只有 Reviewer 可在 Review JSON 中写 `ACCEPT`；只有 transition/validator 脚本可据此推进状态。

## 11. Recovery 与失败探索

### Recovery protocol

新会话必须先运行项目/任务校验，再按第 8 节恢复路径读取。恢复输出只回答：

- 当前冻结任务和 revision 是什么？
- 当前状态、blocker、最后一个有效事件是什么？
- 当前 recommended next action 是什么？
- 完成该动作所需的最小 Working Set 是什么？

只有状态冲突、引用损坏或证据缺失时才向历史扩展。聊天记录不得成为恢复前提。

### Durability checkpoint

- Vendored Skills、`tools/polaris/`、`.polaris/` 和任务代码均纳入 Git。
- `IMPLEMENTED`、`DOCS_SYNCED`、`REVIEWED`、`VERIFIED` 必须引用一个本地 checkpoint commit；Polaris 不自动 push、merge 或发布。
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

- [ ] 冻结 ID、状态、revision、attempt、artifact、finding、evidence、event 的 JSON 结构
- [ ] 写包含前进、返工、阻塞、取消和新 revision 边的 `default-workflow.json`
- [ ] 冻结三档 rigor、risk flag、Reviewer 数量和 Human Approval 规则
- [ ] 建立合法/非法 fixture，包括 commit/diff hash 失配和事件/state 不一致

完成标准：仅凭 schema 和 fixture 可以明确判断每个状态转换应 PASS 还是 FAIL。

### M1 — Repo skeleton 与 Skills（第 3–5 天）

- [ ] 建源仓库目录、JSON/Markdown 模板和七个 Skill
- [ ] 将 Skills vendoring 到 `.agents/skills/`，将版本锁定的脚本/Schema/模板/Workflow vendoring 到 `tools/polaris/`
- [ ] 用最小 fixture 验证当前 Codex 宿主能够发现仓库内 Skills
- [ ] `engineering-task` 实现触发、恢复、分派、门禁停止规则
- [ ] 阶段 Skill 明确输入、输出、owner 和禁止事项

完成标准：Codex 接到一个模糊 R1 任务时先建立 Work Item，不直接改代码。

### M2 — Mechanical core（第 6–9 天）

- [ ] 实现 init、revision、validate、transition、state rebuild、docs check
- [ ] 所有状态写入经 `transition_task.py`
- [ ] 单元测试覆盖第 9 节失败场景

完成标准：非法跳转、过期 Review、错误 commit/diff、缺 AC 证据、未处置文档漂移和损坏事件序列均被脚本稳定拒绝；合法事件可以重建 `state.json`。

### M3 — Review、Recovery 与 Working Set（第 10–12 天）

- [ ] 实现绑定 revision、commit、diff hash 和 session attestation 的 reviewer handoff 与 finding lifecycle
- [ ] 实现渐进恢复与 Working Set 刷新
- [ ] 实现 failed exploration 的任务内记录与项目级提升

完成标准：全新 Codex 会话不读取旧聊天即可指出当前状态、blocker、next action，并开始正确节点。

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

完成标准：至少两个不同工程任务闭环，并能够用证据决定是否继续下一阶段。CLI 仅可作为 v0.1 之后的独立产品决策，不属于本计划的交付范围。

## 14. v0.1 总体验收标准

- [ ] 目标仓库无需安装 Polaris 程序即可使用；vendored `.agents/skills/`、`tools/polaris/`、`.polaris/` 和 Python 足以运行。
- [ ] 非平凡任务不会在 Work Item 冻结前进入 Implementation。
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
- [ ] Horizon 和 Vision 各完成至少一个真实闭环，并形成可比较的评估记录。
- [ ] 两个试点均记录 `Adversarial Review Yield`，用于判断独立 Review 带来的收益是否值得其时间和 token 成本。
- [ ] v0.1 中没有 CLI、daemon、Dashboard、scheduler、自定义 runtime 或 database。
- [ ] v0.1 中没有 Task DAG、自动归档或跨任务依赖调度。

## 15. 开工第一批任务

按以下顺序直接实施：

1. 创建第 4 节源仓库骨架和目标仓库 vendoring fixture。
2. 先写权威 JSON artifact 结构、有限 Schema 子集与完整 `default-workflow.json`，不要先写长 Skill。
3. 建一个合法任务以及覆盖非法边、过期 revision、错误 commit/diff、事件损坏和证据缺失的非法 fixture。
4. 实现 `validate_task.py`、`transition_task.py` 与 `rebuild_state.py`，锁定“Agent 不拥有完成状态”。
5. 写 `engineering-task/SKILL.md`，让其只围绕 graph、owner、artifact、checkpoint 和 gate 编排。
6. 补齐阶段 Skills、JSON/Markdown 模板、Documentation Sync 和 reviewer handoff。
7. 将 Skills 和协议实现 vendoring 到 Horizon fixture，验证发现、版本锁定和 Fresh Clone Recovery。
8. 用 Horizon 的一个小型 R1 任务 dogfood；遇到摩擦先改协议和 Skill，不扩建 CLI/UI。

## 16. 长期产品方向（不属于 v0.1）

Polaris 的长期方向是演化为运行在不同 Coding Agent 之上的轻量工程控制层：

```text
Polaris Thin App / Control Plane
              │
              ▼
         Agent Runtime
              │
      Codex / Claude / Others
```

长期能力可以包括多任务依赖管理、跨项目状态、可视化界面、多模型适配和 Reviewer arbitration，但必须建立在 v0.1 的真实试点证据之上。v0.1 不为这些能力预先建设 CLI、daemon、scheduler、数据库或自定义 Agent Runtime。

v0.1 的核心边界是：Polaris 定义不同 Agent 应读取什么、承担什么职责、产出什么证据，以及满足哪些门禁后任务才能继续；Codex 负责 Session、Agent Loop、工具调用、执行环境和上下文运行时。

## 一句话定义

> **Polaris v0.1 是由 Codex 执行、由仓库状态承载、由声明式 Graph 与确定性校验约束的软件工程工作协议。**
