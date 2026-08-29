# Polaris 长任务可靠性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 构建一个面向单个长时间软件工程任务的受控 Agent Harness，使任务在上下文增长、进程中断、工作区变化、工具失败和模型过早宣布完成时，仍能稳定、正确、可恢复地执行。

**Architecture:** Polaris 采用路线 C：不把能力做成提示词集合或 Codex 外层补丁，而是由独立 Controller 掌握模型调用、上下文投影、工具执行、状态持久化、恢复和完成权限。第一条实现纵切面先证明主动 Context Working Set 的价值，随后补齐 Task Contract、Observation Ledger、Action Boundary 和 Independent Verifier，形成完整闭环。

**Tech Stack:** Python 3.12、标准库 dataclasses/json/pathlib、file-based storage、OpenAI Python SDK、pytest、pytest-asyncio、Hypothesis、uv；所有依赖写入 pyproject.toml 并锁定到 uv.lock。

**Spec:** 本文件同时是 Polaris 的产品规格、架构权威与分阶段实施计划。

## Global Constraints

- 只优化一个结果：一个长时间软件工程任务的正确完成率。
- 第一版仅支持 macOS、一个可信本地仓库、一个活动任务、一个前台 Controller 和 OpenAI 一个模型提供方。
- 模型只能提出语义动作；只有 Controller 可以执行工具、修改机械状态和写入 DONE。
- 所有 mutation 串行执行；每次 mutation 后、下次模型调用前必须建立耐久 Action Boundary。
- 每次模型请求都从权威状态重新构建 Context View，不把追加式聊天记录当作运行时上下文模型。
- 可变仓库观察必须绑定 provenance 和 version identity；旧观察不得作为当前事实恢复。
- eviction、compaction、暂停和退出前，必须持久化 dirty 且难以恢复的关键语义。
- 任何状态转换、恢复分支、action gate、context routing 和 completion gate 都必须有测试。
- 第一版不引入数据库服务、向量库、知识图谱、队列、daemon、scheduler、Dashboard、TUI、IDE、多任务、多 Agent 或插件系统。
- 没有 benchmark 证据的复杂机制不进入第一版。

---

## 1. 决策背景：Codex 已有能力与 Polaris 的边界

Polaris 不以“Codex 完全没有长任务能力”为前提。当前 Codex 已经具备：

- 持久化 Goal、token budget、自动续跑和任务恢复；
- token 阈值、模型切换、用户请求等触发的 compaction；
- 本地或服务端摘要，以及 compaction 前后 hook；
- 工具输出截断和有限的上下文容量保护；
- World State 的结构化快照与增量注入；
- rollout、线程历史和工具事件的持久化。

因此，Polaris 不重复实现“更长的聊天记录”“另一种 Goal 文本”或“context 快满时做摘要”。Polaris 只针对当前公开实现中仍不具备通用、机械保证的部分：

1. **弱结构任务契约**：Codex Goal 主要是自由文本 objective，没有独立的 scope、hard constraints、acceptance criteria、revision 和证据失效关系。
2. **缺少主动语义维护**：compaction 主要由容量和运行事件触发，不会在 context 尚未接近上限时持续清理已过期、已取代或低价值内容。
3. **缺少通用 provenance/recoverability**：被截断或摘要的信息通常没有统一的 source、version、content hash、恢复配方和恢复成本。
4. **缺少 stale-safe fault-in**：文件修改后，旧观察仍可能以文本存在；没有通用机制保证恢复的是指定历史版本或当前版本。
5. **缺少动作感知的上下文路由**：没有按当前 read/edit/test/review 动作构造最小任务知识集合的通用策略。
6. **缺少 compaction 前语义落盘协议**：hook 存在，但 root cause、decision、invariant、blocker 等关键语义没有内置 dirty-state flush 保证。
7. **摘要无法机械验证**：多次摘要可能漂移，摘要事实通常没有逐项绑定原始证据。
8. **缺少通用耐久 mutation 生命周期**：没有覆盖所有有副作用工具的 PREPARED、RUNNING、SUCCEEDED、FAILED、AMBIGUOUS 协议及恢复 reconciliation。
9. **完成仍主要由执行模型触发**：Codex 倡导 evidence-based completion，但 Goal complete 接口本身不要求独立 Verifier 提交结构化证据。
10. **缺少机械失败熔断**：相同前置条件下的相同失败没有统一 fingerprint 门禁。

### 1.1 证据口径与审计快照

本节使用三种证据等级：

- **DOC — 官方明确行为**：OpenAI 官方文档直接描述的产品或 API 行为。
- **SRC — 源码直接事实**：固定 Codex commit 中可直接定位的类型、字段、分支或处理流程。
- **AUDIT — 公开实现审计推断**：在明确范围和检索词下没有发现通用机制。它支持“当前公开实现中未发现”，不支持“所有 hosted backend 都不存在”。

本次审计固定为：

- 审计日期：2026-08-26；
- 仓库：openai/codex；
- commit：da4cf1cdeaf8fb44a18bb75fd8df0094097f90b8；
- 本地源码根目录：../codex；
- 官方 Goal 依据：[Using Goals in Codex](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)；
- 官方 compaction 依据：[Compaction](https://developers.openai.com/api/docs/guides/compaction)。

源码位置全部相对于 Codex 仓库根目录，并绑定上述 commit。后续 Codex 更新后不得沿用旧行号直接声称结论仍然成立；必须重新执行第 1.3 节审计。

### 1.2 逐项证据链

#### E1 — Goals 已提供持久目标和续跑，但合同接口仍是弱结构

- **事实**：Codex Goal 是持久化 thread state，带 objective、lifecycle、budget、progress accounting，并能在 idle 时继续、在 resume 后恢复。
- **DOC**：官方 Goal 文档明确把 Goal 描述为 persistent objective、thread-scoped completion contract，并要求基于文件、测试、日志、benchmark 或 artifact 判断完成。
- **SRC**：codex-rs/ext/goal/src/runtime.rs:195-211 在 active 状态触发 continue_if_idle；同文件 338-359 从 state DB 恢复 active Goal。
- **SRC**：codex-rs/ext/goal/src/spec.rs:25-56 的 create_goal schema 只有 objective 与 token_budget；同文件 60-70 的 update_goal 输入只有 complete/blocked status。
- **SRC**：codex-rs/ext/goal/src/tool.rs:49-60 的请求类型再次确认 create 输入是 objective/token_budget，update 输入是 status；185-240 的 handler 将这些值直接写入或更新持久状态。
- **有界结论**：不能把 Codex 描述成“没有任务契约”；准确说法是它有 durable Goal，但公开 tool schema 没有独立的 scope、hard constraints、acceptance criteria、revision 和 evidence payload。
- **Polaris 决策**：实现版本化 Task Contract，并让 completion evidence 显式绑定 contract revision，而不是复制 Goal 文本。

#### E2 — 自动 compaction 的公开触发面以容量和运行事件为主

- **事实**：Responses API 支持 server-side 和 standalone compaction；Codex 还支持用户请求、context limit、model downshift 和 compaction compatibility hash 变化等原因。
- **DOC**：官方 Compaction 文档说明 server-side compaction 在 rendered token count 跨过 compact_threshold 时运行；standalone endpoint 由调用方显式触发。
- **SRC**：codex-rs/core/src/session/context_window.rs:23-79 计算 active tokens、auto-compact limit 和 token_limit_reached。
- **SRC**：codex-rs/core/src/session/turn.rs:1024-1037 在 token_limit_reached 时执行 pre-turn compaction。
- **SRC**：codex-rs/analytics/src/facts.rs:419-423 枚举 UserRequested、ContextLimit、ModelDownshift、CompHashChanged 四类 CompactionReason。
- **有界结论**：Codex 已经能提前配置低于物理窗口的 token threshold，也存在非容量运行事件；但当前公开触发原因中没有按 supersession、staleness、phase/action relevance 或 recoverability 持续维护 working set 的通用原因。
- **Polaris 决策**：主动 maintenance 由 action 完成、workspace 变化、item supersede、phase 变化和 freshness 失效触发，即使 context 只占 soft budget 的少部分也运行。

#### E3 — 运行时上下文仍以 transcript 为核心，工具输出采用截断而非通用外置恢复

- **事实**：Codex 在历史项进入 ContextManager 时会对函数和自定义工具输出应用 truncation policy；context overflow 时还会重写较新的工具输出。
- **SRC**：codex-rs/core/src/context_manager/history.rs:46-53 将 ContextManager 定义为 thread history transcript，主体是按时间排列的 ResponseItemEnvelope vector。
- **SRC**：同文件 471-500 对 FunctionCallOutput 和 CustomToolCallOutput 调用 truncate_function_output_payload。
- **SRC**：codex-rs/core/src/compact_remote.rs:457-487 在窗口溢出修剪中用 truncated_output_payload 重写工具输出。
- **有界结论**：截断能控制 token，但上述通用路径没有同时返回 content-addressed artifact、expected hash 和 recovery recipe，因而不等价于“正文外置后可精确 fault-in”。个别工具自行持久化文件不推翻该结论。
- **Polaris 决策**：大型结果先进入 Artifact Store，Context View 只持有 hash reference；恢复时校验内容身份。

#### E4 — Codex 有 World State diff，但历史项没有通用 observation provenance schema

- **事实**：Codex World State 能为类型化 section 持久化 snapshot，并相对上一快照生成 full/diff/history diff。
- **SRC**：codex-rs/core/src/context/world_state/mod.rs:217-235 定义可持久化 typed WorldStateSection；397-434 实现 render_full、render_diff 和 render_history_diff。
- **事实**：通用历史 envelope 的 harness metadata 当前只公开 client_authored 标志。
- **SRC**：codex-rs/history/src/lib.rs:36-50 定义 ResponseItemEnvelope 和 CodexHarnessMetadata；metadata 字段只有 client_authored。
- **AUDIT**：在 codex-rs/core/src/context_manager、codex-rs/core/src/context 和 codex-rs/history/src 范围检索 recoverability、recovery_recipe、attention_pin、source_version、workspace_version，没有发现统一的 Context Item 字段族。
- **有界结论**：World State 是重要的增量上下文能力，不能被忽略；但它没有证明任意源码片段、日志和工具观察都绑定 source identity、content hash、workspace version、恢复成本和恢复配方。
- **Polaris 决策**：保留 World State 的“typed snapshot/diff”思想，并将 provenance/recoverability 扩展成所有 Observation 的统一协议。

#### E5 — 当前公开实现未发现 stale-safe、action-aware 的通用任务上下文路由

- **事实**：ContextManager 管理 transcript，World State 管理注册 section 的当前设置投影；二者都不是按 read/edit/test/review 动作选择任务语义 item 的统一 Observation Ledger。
- **SRC**：codex-rs/core/src/context_manager/history.rs:46-65 展示 transcript、reference context 和 world-state baseline 三类核心状态。
- **SRC**：codex-rs/core/src/context/world_state/mod.rs:397-434 的 diff 决策基于 section snapshot 或 retained fragment，而不是 task action、changed path、constraint scope、recovery cost 和 stale source version 的联合路由。
- **AUDIT**：上述 context/history 审计范围未发现 action_tags、attention_pin、recovery_recipe 或 workspace_version 组成的统一 routing contract。
- **有界结论**：不能声称 Codex 完全不会按需注入上下文；准确结论是当前公开实现中未发现面向任意任务观察、同时执行 stale validation 与 action-aware routing 的通用层。
- **Polaris 决策**：ContextManifest 为每个 include/exclude 记录 reason code，并在 fault-in 时验证 source/content/workspace identity。

#### E6 — compaction 有 hook，但没有内置 dirty semantic state flush 协议

- **事实**：Codex 在 compaction 前后提供 hook，调用方可以扩展行为。
- **SRC**：codex-rs/core/src/compact.rs:185-221 在 compact task 前调用 run_pre_compact_hooks，成功后调用 post hook。
- **AUDIT**：ContextManager、World State 和 history envelope 中没有发现统一的 dirty semantic item、recoverability 等级以及“root cause、decision、invariant、blocker 必须先持久化才能 eviction”的状态转换。
- **有界结论**：hook 是扩展点，不等于内置语义 durability guarantee；用户可以自行构建类似机制，但 Codex 核心当前没有提供通用完成协议。
- **Polaris 决策**：maintenance、compaction、pause 和 shutdown 共用同一个 flush_dirty_semantics gate，失败则禁止驱逐或结束。

#### E7 — compaction 能续接状态，但摘要保真没有逐事实机械证明

- **DOC**：官方 Compaction 文档说明返回的 compaction item 会用更少 token 携带关键先前状态，同时明确它是 opaque、not intended to be human-interpretable。
- **SRC**：codex-rs/core/src/compact.rs:352-389 从历史和模型输出构造 summary_text，并用 compacted history 替换旧历史。
- **SRC**：同文件 395 的用户警告明确提示 long threads 和 multiple compactions 可能降低模型准确性。
- **有界结论**：这些证据证明 compaction 是有效的连续性机制，但没有证明摘要中的每个事实都绑定原始 artifact、source hash 或可自动验证的 claim ledger。
- **Polaris 决策**：摘要只承载导航和高密度语义；关键事实必须保留 evidence reference，并可从权威 artifact 重新构建。

#### E8 — mutation lifecycle、completion authority 和失败熔断属于公开实现审计缺口

- **事实**：Goal 文档要求 evidence-based completion，但模型可见 update_goal tool 的请求只携带 complete/blocked status。
- **SRC**：codex-rs/ext/goal/src/spec.rs:60-70 和 codex-rs/ext/goal/src/tool.rs:56-60、228-240 没有 criterion evidence、contract revision 或 workspace version 参数。
- **AUDIT**：在 codex-rs/core/src、codex-rs/ext、codex-rs/history/src 和 codex-rs/state/src 检索通用 ActionStatus、PREPARED/RUNNING/SUCCEEDED/FAILED/AMBIGUOUS、action_fingerprint、precondition_fingerprint、failure_fingerprint，没有发现覆盖所有 workspace mutation 的统一持久状态机；命中项是局部 prepared 类型或 network approval 的 Ambiguous，不构成通用 Action Boundary。
- **有界结论**：这不否定 rollout、审批、工具事件或特定工具的恢复能力；它只说明当前公开实现中未发现 Polaris 所要求的通用 mutation transaction、独立 evidence gate 和相同前置条件失败熔断。
- **Polaris 决策**：由 Controller 独占 mutation 和 DONE 权限，把三项机制作为独立、可故障注入测试的运行时不变量。

### 1.3 可复现审计方法与更新规则

使用固定 commit 复核正向源码证据：

~~~bash
git -C ../codex show da4cf1cdeaf8fb44a18bb75fd8df0094097f90b8:codex-rs/core/src/session/context_window.rs
git -C ../codex show da4cf1cdeaf8fb44a18bb75fd8df0094097f90b8:codex-rs/core/src/context_manager/history.rs
git -C ../codex show da4cf1cdeaf8fb44a18bb75fd8df0094097f90b8:codex-rs/core/src/context/world_state/mod.rs
git -C ../codex show da4cf1cdeaf8fb44a18bb75fd8df0094097f90b8:codex-rs/ext/goal/src/spec.rs
~~~

在固定 commit 复核通用机制缺口：

~~~bash
git -C ../codex grep -n -E 'recoverability|recovery_recipe|attention_pin|source_version|workspace_version' da4cf1cdeaf8fb44a18bb75fd8df0094097f90b8 -- codex-rs/core/src/context_manager codex-rs/core/src/context codex-rs/history/src
git -C ../codex grep -n -E 'action_fingerprint|precondition_fingerprint|failure_fingerprint' da4cf1cdeaf8fb44a18bb75fd8df0094097f90b8 -- codex-rs/core/src codex-rs/ext codex-rs/history/src codex-rs/state/src
~~~

上述两个负向审计命令预期无输出并以 status 1 结束，表示在声明的 commit、目录和检索词范围内没有匹配；其他错误状态不能解释为“未发现”。

负向检索只能支持其列出的目录、commit 和词汇范围。出现以下任一变化时必须更新本节：

- Codex 新增 context item provenance/recovery schema；
- compaction 新增 relevance、staleness、supersession 或 action-aware trigger；
- Goal schema 新增结构化 contract revision 或 evidence payload；
- 新增通用 mutation lifecycle、reconciliation 或 failure fingerprint；
- 官方文档对 hosted behavior 作出新的明确说明。

这些结论只描述当前可验证的公开行为，不假设未公开 hosted backend 的内部能力，也不把“源码中未发现”写成数学意义上的不存在证明。

## 2. 产品定义与成功标准

Polaris 是围绕一个长任务运行的确定性监督器：

~~~text
Human
  ↓
Versioned Task Contract
  ↓
Polaris Controller
  ├── Runtime State / Event Store
  ├── Observation & Artifact Ledger
  ├── Context Working-Set Manager
  ├── Model Client
  ├── Action Gate / Tool Gateway
  ├── Checkpoint / Recovery
  └── Independent Verifier
        ↓
Local Repository + Tests + Git
~~~

模型负责理解、推理、生成方案、编写变更、解释失败和提出下一动作。Polaris 负责事实、资源和生命周期：冻结合同、生成上下文、校验并执行动作、记录版本、恢复中断以及裁决完成。

“稳定、正确、可恢复”必须同时满足：

1. 合同不漂移：摘要和模型不能静默修改目标、范围或硬约束。
2. 状态不丢失：外部动作和 next action 在下一轮模型调用前已经持久化。
3. 上下文不污染：模型看到的是当前动作所需的高密度 Working Set。
4. 恢复不陈旧：观察绑定明确版本；历史版本与当前版本不可混淆。
5. 失败有边界：相同前提下的同一失败动作最多实际执行两次。
6. Mutation 可解释：每次修改都有前后 workspace identity、输入、输出和 changed paths。
7. 完成不自证：执行模型只能提出完成候选，独立 Verifier 决定是否满足合同。
8. 中断可恢复：进程退出后不依赖旧聊天即可继续或安全停止。

## 3. 第一版范围与非目标

第一版必须交付：

- 冻结且可修订的 Task Contract；
- append-only Action Event 与原子 Runtime State；
- content-addressed Artifact Store；
- 带 provenance、version 和 recoverability 的 Observation Ledger；
- 即使 context 未满也会运行的主动 Context Working-Set policy；
- 最小文件读取、搜索、Patch、Shell、Git Tool Gateway；
- mutation 前 Action Gate 和 mutation 后 Action Boundary；
- crash recovery 与 ambiguous mutation reconciliation；
- 干净上下文中的独立 Verifier；
- microbenchmark、trace replay、端到端 baseline/full/ablation 比较。

第一版明确不做：

- 多模型、多宿主、多任务、多项目和 Task DAG；
- 自动 push、merge、发布或远程执行；
- 完整 OS sandbox；
- 额外 LLM context router；
- 长期知识库、团队记忆或跨项目个性化；
- UI、插件市场、安装生态或跨平台产品化。

## 4. 核心数据模型

权威数据保存在目标仓库的 .polaris 目录：

~~~text
.polaris/
├── task.json
├── state.json
├── events.jsonl
├── observations.jsonl
├── artifacts/
│   └── sha256/
└── checkpoints/
~~~

### 4.1 Task Contract

TaskContract 必须包含：

~~~python
@dataclass(frozen=True)
class TaskContract:
    task_id: str
    revision: int
    goal: str
    motivation: str
    scope_in: tuple[str, ...]
    scope_out: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    human_decisions: tuple[str, ...]
    supersedes_revision: int | None
~~~

revision 增加时，旧 revision 绑定的 completion candidate 和 verification verdict 自动失效。合同文件只能由 Controller 根据明确用户输入写入。

### 4.2 Observation 与 Artifact

~~~python
class Recoverability(StrEnum):
    EXACT = "exact"
    EXPENSIVE = "expensive"
    POOR = "poor"

@dataclass(frozen=True)
class SourceIdentity:
    kind: str
    locator: str
    content_hash: str
    workspace_version: str | None
    observed_at: str

@dataclass(frozen=True)
class RecoveryRecipe:
    method: str
    arguments: Mapping[str, JSONValue]
    expected_content_hash: str | None

@dataclass(frozen=True)
class ContextItem:
    item_id: str
    kind: str
    content: str | None
    artifact_hash: str | None
    provenance: SourceIdentity
    recovery: RecoveryRecipe | None
    recoverability: Recoverability
    recovery_cost: int
    freshness: str
    salience: int
    phase_tags: tuple[str, ...]
    action_tags: tuple[str, ...]
    persistent_pin: bool
    attention_pin: bool
    dirty: bool
    supersedes: tuple[str, ...]
~~~

Persistent Pin 表示内容必须有耐久 backing；Attention Pin 只表示下一次特定动作必须看见。两者不得合并成一个 pin。

### 4.3 Runtime State 与 Action

~~~python
class RunStatus(StrEnum):
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    VERIFYING = "verifying"
    DONE = "done"
    CANCELLED = "cancelled"

class ActionStatus(StrEnum):
    PREPARED = "prepared"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"

@dataclass(frozen=True)
class RuntimeState:
    state_version: int
    task_id: str
    contract_revision: int
    run_status: RunStatus
    active_action_id: str | None
    workspace_version: str
    blocker: str | None
    next_action: str | None
    completion_candidate_id: str | None
~~~

每个 Action Event 记录 run ID、action ID、action fingerprint、precondition fingerprint、state version、workspace before/after、tool input、result reference、changed paths、recovery status 和 next action。

## 5. Context Working-Set Policy

上下文窗口是临时工作集，不是数据库。Storage Policy 与 Attention Policy 必须独立。

### 5.1 主动维护触发器

Working-Set maintenance 在以下任一事件后运行，不等待 token 接近上限：

- action 完成；
- workspace version 改变；
- 新 item supersede 旧 item；
- phase 或 next action 改变；
- observation freshness 失效；
- Context View 预计超过 soft budget；
- checkpoint、暂停、退出或 compaction 前。

### 5.2 机械策略

处理顺序固定为：

1. flush dirty 且 EXPENSIVE/POOR 的语义项；
2. 将大型内容写入 Artifact Store，并用 hash reference 替换；
3. 失效与当前 workspace version 不匹配的当前事实；
4. 移除已被 supersede 且没有独立历史价值的内容；
5. 淘汰 EXACT 且恢复便宜的正文，只保留 recovery recipe；
6. 根据 action tags、path、risk、constraint scope 和 freshness 选择 Foreground Set；
7. 在 hard token budget 内生成 Context View manifest；
8. fault-in 时校验 hash，不匹配则返回 STALE，不把内容注入模型。

第一版不调用额外 LLM 评价 relevance。机械排序使用：

~~~text
keep_score =
    5 * hard_constraint_match
  + 4 * active_action_match
  + 3 * changed_path_match
  + 3 * poor_recoverability
  + 2 * explicit_attention_pin
  + salience
  - recovery_cost_discount
  - staleness_penalty
  - superseded_penalty
~~~

权重通过 benchmark 调整，不能凭直觉继续增加特征。

### 5.3 Context View 布局

每次请求按固定顺序生成：

1. 当前 Task Contract revision 的相关 projection；
2. Runtime State、active blocker 和 next action；
3. 当前动作必须满足的硬约束；
4. Foreground observations 与必要源码片段；
5. 最近的有界 causal suffix；
6. 可恢复内容的 manifest，不注入正文；
7. 当前可调用工具和输出协议。

任何单项不得超过 10K tokens；整个 View 必须有 hard cap。历史对话只有在它已转化为权威事实或属于有界 causal suffix 时才可进入 View。

## 6. 受控执行与恢复

每轮流程：

~~~text
Load authoritative state
→ Maintain working set
→ Build Context View
→ Call model
→ Normalize proposed action
→ Validate action gate
→ Persist PREPARED
→ Execute tool
→ Capture output and workspace effects
→ Persist terminal action event
→ Atomically update state
→ Continue / Wait / Verify
~~~

Action Gate 必须拒绝：

- 工作区路径逃逸；
- 超出 contract scope 的 mutation；
- 模型观察的 workspace version 与当前版本不同；
- 上一个 mutation 尚未达到耐久终态；
- 存在未解决 AMBIGUOUS action；
- 相同 precondition 下第三次执行相同失败 fingerprint；
- 未获明确授权的不可逆、凭据、权限或网络副作用。

进程在 RUNNING 后中断时，Recovery Reconciler 检查工作区和工具证据：

- 能证明未执行：记录 FAILED/NOT_EXECUTED，允许重新规划；
- 能证明已完整执行：补写 SUCCEEDED 和 workspace effects；
- 无法证明：写入 AMBIGUOUS，进入 WAITING，禁止自动 mutation。

## 7. 独立完成裁决

执行模型只能返回 PROPOSE_DONE。Controller 随后：

~~~text
Freeze completion candidate
→ Bind contract revision and workspace version
→ Run deterministic acceptance evidence
→ Build clean verifier context
→ Run read-only independent verifier
→ PASS or structured corrective actions
~~~

VerificationVerdict 必须逐项绑定 acceptance criterion、evidence command、exit/result、artifact hash、contract revision、workspace version 和 final diff hash。

以下任一条件禁止 DONE：

- acceptance criterion 没有证据；
- evidence 对应旧 contract 或旧 workspace；
- 存在 blocker、AMBIGUOUS action 或 dirty semantic state；
- final diff 包含未解释或越界修改；
- Verifier 返回 reject；
- Verifier 后工作区再次变化。

## 8. 代码结构

在对应任务开始时创建目录，不提前生成空模块：

~~~text
pyproject.toml
src/polaris/
├── contract/
│   ├── model.py
│   └── store.py
├── state/
│   ├── model.py
│   ├── event_store.py
│   ├── state_store.py
│   └── replay.py
├── artifacts/
│   ├── store.py
│   └── observations.py
├── context/
│   ├── policy.py
│   ├── router.py
│   ├── view.py
│   └── tokens.py
├── actions/
│   ├── model.py
│   ├── gate.py
│   ├── fingerprint.py
│   └── recovery.py
├── tools/
│   ├── protocol.py
│   ├── filesystem.py
│   ├── patch.py
│   ├── shell.py
│   └── git.py
├── model/
│   ├── protocol.py
│   └── openai_client.py
├── verification/
│   ├── model.py
│   ├── evidence.py
│   └── verifier.py
└── controller.py
tests/
├── contract/
├── state/
├── artifacts/
├── context/
├── actions/
├── tools/
├── verification/
├── traces/
└── end_to_end/
benchmarks/
├── tasks/
├── traces/
├── runner.py
└── report.py
~~~

## 9. 实施任务

### Task 1: 建立基线、项目骨架与版本化 Task Contract

**Files:**
- Create: pyproject.toml
- Create: src/polaris/contract/model.py
- Create: src/polaris/contract/store.py
- Create: tests/contract/test_contract_store.py
- Create: benchmarks/tasks/constraint_recall.json
- Modify: README.md
- Modify: README.zh-CN.md

**Interfaces:**
- Produces: TaskContract、AcceptanceCriterion、ContractStore.create、ContractStore.revise、ContractStore.load。
- Produces: canonical_json(value) -> bytes，供后续 hash 和原子存储复用。

- [ ] **Step 1: 写 Task Contract 失败测试**

  覆盖首次创建、冻结字段、revision 单调递增、supersedes_revision、非法直接覆盖、旧 completion binding 失效标记。

- [ ] **Step 2: 运行测试并确认失败**

  Run: uv run pytest tests/contract/test_contract_store.py -q

  Expected: FAIL，因为 polaris.contract 尚不存在。

- [ ] **Step 3: 实现最小模型和原子 ContractStore**

  store.py 使用同目录临时文件、flush、os.fsync 和 os.replace；JSON 使用四空格缩进与稳定 key 排序。任何 revision 必须显式携带用户提供的变更原因。

- [ ] **Step 4: 添加第一个 baseline task**

  constraint_recall.json 包含早期硬约束、长干扰轨迹、最终修改目标和确定性评分规则；baseline runner 暂不实现。

- [ ] **Step 5: 运行测试并提交**

  Run: uv run pytest tests/contract/test_contract_store.py -q

  Expected: PASS。

  Commit: feat: add versioned task contracts

### Task 2: 实现 append-only Event Store、原子 State Store 与 replay

**Files:**
- Create: src/polaris/state/model.py
- Create: src/polaris/state/event_store.py
- Create: src/polaris/state/state_store.py
- Create: src/polaris/state/replay.py
- Create: tests/state/test_event_replay.py
- Create: tests/state/test_crash_consistency.py

**Interfaces:**
- Produces: ActionEvent、RuntimeState、EventStore.append、EventStore.read_valid_prefix、StateStore.replace、replay(events) -> RuntimeState。
- Consumes: canonical_json from Task 1。

- [ ] **Step 1: 写 event sequence 和 replay 失败测试**

  覆盖连续 sequence、重复 action ID、非法状态转换、snapshot 与 replay 深度相等。

- [ ] **Step 2: 写 crash consistency 失败测试**

  在 JSONL 最后一行和 state 临时文件的每个写入边界注入截断；合法前缀必须可恢复，损坏不得静默跳过。

- [ ] **Step 3: 运行测试并确认失败**

  Run: uv run pytest tests/state -q

  Expected: FAIL，因为 EventStore 和 StateStore 尚不存在。

- [ ] **Step 4: 实现事件追加、原子状态替换和 replay**

  EventStore 每次 append 后 flush 和 fsync；read_valid_prefix 返回最后合法 sequence 和明确 corruption result。StateStore 只缓存 replay 结果，不覆盖事件权威。

- [ ] **Step 5: 运行测试并提交**

  Run: uv run pytest tests/state -q

  Expected: PASS。

  Commit: feat: add durable event and state stores

### Task 3: 实现 Artifact Store 与版本感知 Observation Ledger

**Files:**
- Create: src/polaris/artifacts/store.py
- Create: src/polaris/artifacts/observations.py
- Create: tests/artifacts/test_artifact_store.py
- Create: tests/artifacts/test_observation_recovery.py

**Interfaces:**
- Produces: ArtifactStore.put(bytes) -> sha256、ArtifactStore.get_verified(hash) -> bytes。
- Produces: ObservationLedger.record、recover_exact、mark_stale、supersede。
- Produces: SourceIdentity、RecoveryRecipe、ContextItem、Recoverability。

- [ ] **Step 1: 写 content-addressed storage 失败测试**

  覆盖相同内容去重、hash 校验、损坏检测、单项硬大小上限和大型输出正文外置。

- [ ] **Step 2: 写 stale recovery 失败测试**

  记录文件观察后修改文件；recover_exact 必须恢复指定历史 artifact 或返回 STALE，绝不能把当前内容冒充历史内容。

- [ ] **Step 3: 运行测试并确认失败**

  Run: uv run pytest tests/artifacts -q

  Expected: FAIL，因为 artifact 和 observation 模块尚不存在。

- [ ] **Step 4: 实现 Artifact Store 和 Observation Ledger**

  artifact 写入先计算 sha256，再原子 rename；Observation JSONL 保存 source identity、workspace version、recipe、recoverability、dirty 和 supersedes。

- [ ] **Step 5: 运行测试并提交**

  Run: uv run pytest tests/artifacts -q

  Expected: PASS。

  Commit: feat: add recoverable observation ledger

### Task 4: 完成路线 C 的主动 Context Working-Set 纵切面

**Files:**
- Create: src/polaris/context/policy.py
- Create: src/polaris/context/router.py
- Create: src/polaris/context/view.py
- Create: src/polaris/context/tokens.py
- Create: tests/context/test_maintenance.py
- Create: tests/context/test_routing.py
- Create: tests/context/test_view_budget.py
- Create: benchmarks/traces/context_pressure.jsonl
- Create: benchmarks/runner.py

**Interfaces:**
- Produces: maintain_working_set(state, items, trigger) -> MaintenanceResult。
- Produces: route_context(action, contract, state, items, budget) -> ContextManifest。
- Produces: build_context_view(manifest, stores) -> ModelContext。
- Consumes: ContractStore、ObservationLedger、ArtifactStore。

- [ ] **Step 1: 写“context 未满也主动清理”的失败测试**

  构造占用仅为 soft budget 40% 的 item 集合；当新 observation supersede 旧 observation、workspace version 变化或 action phase 改变时，maintenance 仍必须外置或驱逐旧正文。

- [ ] **Step 2: 写 dirty flush 和 stale fault-in 失败测试**

  POOR/EXPENSIVE dirty item 在 eviction 前必须写入 artifact/observation；hash 或 workspace identity 不匹配时不得进入 ModelContext。

- [ ] **Step 3: 写 action-aware routing 和 hard-cap 失败测试**

  edit 动作必须看到相关 path 的约束和源码；test 动作必须看到 acceptance evidence；无关旧日志只留 manifest。每个 item 和总 View 均必须遵守硬上限。

- [ ] **Step 4: 运行测试并确认失败**

  Run: uv run pytest tests/context -q

  Expected: FAIL，因为 Context Manager 尚不存在。

- [ ] **Step 5: 实现纯机械 maintenance、routing 和 View builder**

  严格实现第 5 节触发器、处理顺序和 keep_score；不增加辅助 LLM 调用。ContextManifest 必须记录每个 include/exclude 的 reason code，供 benchmark 审计。

- [ ] **Step 6: 实现 context microbenchmark**

  runner 输出 constraint survival、stale injection、foreground precision/recall、input tokens 和 maintenance wall time；保存 baseline 与 Polaris 两组 JSON 报告。

- [ ] **Step 7: 运行测试和 benchmark 并提交**

  Run: uv run pytest tests/context -q

  Run: uv run python benchmarks/runner.py --suite context

  Expected: 所有测试 PASS；硬约束存活率 100%，stale injection 为 0，routing 不调用额外模型。

  Commit: feat: add proactive context working set

### Task 5: 实现 Action 模型、Gate、Tool Gateway 与耐久 mutation boundary

**Files:**
- Create: src/polaris/actions/model.py
- Create: src/polaris/actions/fingerprint.py
- Create: src/polaris/actions/gate.py
- Create: src/polaris/tools/protocol.py
- Create: src/polaris/tools/filesystem.py
- Create: src/polaris/tools/patch.py
- Create: src/polaris/tools/shell.py
- Create: src/polaris/tools/git.py
- Create: tests/actions/test_gate.py
- Create: tests/actions/test_failure_fingerprint.py
- Create: tests/tools/test_mutation_boundary.py

**Interfaces:**
- Produces: ProposedAction、PreparedAction、ActionResult、ActionStatus。
- Produces: action_fingerprint(action) 和 precondition_fingerprint(state, workspace)。
- Produces: ActionGate.validate(action, contract, state) -> GateDecision。
- Produces: Tool.execute(prepared) -> ActionResult protocol。

- [ ] **Step 1: 写 Gate 失败测试**

  覆盖 path escape、scope 越界、stale workspace、pending mutation、AMBIGUOUS action、不可逆命令和未授权网络副作用。

- [ ] **Step 2: 写重复失败熔断测试**

  相同 action fingerprint 与 precondition fingerprint 允许两次实际执行；第三次必须返回 BLOCKED_REPEATED_FAILURE。任一相关前置条件变化后计数重新计算。

- [ ] **Step 3: 写 mutation durability 失败测试**

  断言 PREPARED 和 RUNNING 已 fsync 后工具才能执行；终态 event、workspace effects 和 state replacement 完成后才能再次调用模型。

- [ ] **Step 4: 运行测试并确认失败**

  Run: uv run pytest tests/actions tests/tools -q

  Expected: FAIL，因为 action 和 tool 模块尚不存在。

- [ ] **Step 5: 实现 Gate、fingerprint 和最小工具集**

  Shell 接收 argv tuple、cwd、timeout 和 side_effect_class，不接收未解析 shell string。Patch 只能写 contract scope 内路径。Git 第一版仅暴露 status、diff 和 rev-parse。

- [ ] **Step 6: 运行测试并提交**

  Run: uv run pytest tests/actions tests/tools -q

  Expected: PASS。

  Commit: feat: enforce durable action boundaries

### Task 6: 实现 crash recovery 与 ambiguous mutation reconciliation

**Files:**
- Create: src/polaris/actions/recovery.py
- Create: tests/actions/test_recovery.py
- Create: tests/traces/test_crash_injection.py
- Create: benchmarks/traces/mutation_crashes.jsonl

**Interfaces:**
- Produces: RecoveryReconciler.reconcile(action, events, workspace) -> RecoveryDecision。
- Consumes: Action Event、Artifact Store、Git workspace identity。

- [ ] **Step 1: 为每个 Action Boundary 写 crash injection 失败测试**

  在 PREPARED 前后、RUNNING 后、文件替换中、结果 artifact 写入后和 state 替换前注入退出。

- [ ] **Step 2: 写三类 reconciliation 失败测试**

  分别证明未执行、已完整执行和无法证明。第三类必须进入 AMBIGUOUS/WAITING，且后续 mutation 被 Gate 拒绝。

- [ ] **Step 3: 运行测试并确认失败**

  Run: uv run pytest tests/actions/test_recovery.py tests/traces/test_crash_injection.py -q

  Expected: FAIL，因为 RecoveryReconciler 尚不存在。

- [ ] **Step 4: 实现 read-only reconciliation**

  Reconciler 只读取事件、artifact、文件 hash 和 Git diff；不能为了探测而重放原动作。

- [ ] **Step 5: 运行测试并提交**

  Run: uv run pytest tests/actions/test_recovery.py tests/traces/test_crash_injection.py -q

  Expected: PASS，所有已定义崩溃点恢复正确率 100%。

  Commit: feat: reconcile interrupted mutations

### Task 7: 接入 Model Client 与 Controller 闭环

**Files:**
- Create: src/polaris/model/protocol.py
- Create: src/polaris/model/openai_client.py
- Create: src/polaris/controller.py
- Create: tests/model/test_model_protocol.py
- Create: tests/traces/test_controller_loop.py

**Interfaces:**
- Produces: ModelClient.complete(ModelContext) -> ModelTurn。
- Produces: Controller.run_one_turn() -> TurnOutcome。
- Consumes: Task Contract、State/Event Stores、Context Manager、Action Gate、Tool Gateway。

- [ ] **Step 1: 写标准化模型输出失败测试**

  只接受 TOOL、CHECKPOINT、ASK_USER、PROPOSE_DONE 四类结果；未知类型和缺失字段成为可恢复协议错误，不执行工具。

- [ ] **Step 2: 写多轮 Controller trace 失败测试**

  使用 deterministic fake ModelClient 完成 read、checkpoint、patch、test、propose_done 流程；断言每轮 View 都从 state 重新生成而非追加旧消息。

- [ ] **Step 3: 运行测试并确认失败**

  Run: uv run pytest tests/model tests/traces/test_controller_loop.py -q

  Expected: FAIL，因为 ModelClient 和 Controller 尚不存在。

- [ ] **Step 4: 实现 protocol、OpenAI adapter 和单轮 Controller**

  OpenAI adapter 只负责请求转换、响应解析、usage/latency/request identity；业务状态和 tool execution 不进入 adapter。

- [ ] **Step 5: 运行测试并提交**

  Run: uv run pytest tests/model tests/traces/test_controller_loop.py -q

  Expected: PASS。

  Commit: feat: add controlled model execution loop

### Task 8: 实现 Independent Verifier 与唯一 DONE 门禁

**Files:**
- Create: src/polaris/verification/model.py
- Create: src/polaris/verification/evidence.py
- Create: src/polaris/verification/verifier.py
- Create: tests/verification/test_evidence_binding.py
- Create: tests/verification/test_completion_gate.py
- Create: tests/traces/test_verifier_rework.py

**Interfaces:**
- Produces: CompletionCandidate、CriterionEvidence、VerificationVerdict。
- Produces: EvidenceRunner.run(candidate) -> tuple[CriterionEvidence, ...]。
- Produces: IndependentVerifier.verify(clean_context) -> VerificationVerdict。
- Produces: Controller.apply_verdict(verdict)；这是唯一允许写入 DONE 的入口。

- [ ] **Step 1: 写 evidence binding 失败测试**

  旧 contract revision、旧 workspace version、旧 diff hash 或缺少 artifact 的证据必须失效。

- [ ] **Step 2: 写 completion authority 失败测试**

  模型、Tool、StateStore 和 replay 都不能直接构造合法 DONE 转换；只有 Controller 在有效 PASS verdict 后可以写入。

- [ ] **Step 3: 写 verifier reject/rework trace**

  执行模型过早 PROPOSE_DONE；Verifier 发现未满足 criterion，返回结构化 corrective action，Controller 回到 RUNNING 并生成 next action。

- [ ] **Step 4: 运行测试并确认失败**

  Run: uv run pytest tests/verification tests/traces/test_verifier_rework.py -q

  Expected: FAIL，因为 verification 模块尚不存在。

- [ ] **Step 5: 实现证据运行器、clean-context verifier 和 DONE gate**

  Verifier 只读；clean context 不包含执行模型的自我评价，只包含合同、final diff、当前 workspace facts 和证据引用。

- [ ] **Step 6: 运行测试并提交**

  Run: uv run pytest tests/verification tests/traces/test_verifier_rework.py -q

  Expected: PASS。

  Commit: feat: require independent completion verification

### Task 9: 建立端到端 benchmark、ablation 与 release gate

**Files:**
- Create: benchmarks/tasks/multi_file_change.json
- Create: benchmarks/tasks/long_debugging.json
- Create: benchmarks/tasks/stale_observation.json
- Create: benchmarks/tasks/interrupted_run.json
- Create: benchmarks/tasks/premature_completion.json
- Modify: benchmarks/runner.py
- Create: benchmarks/report.py
- Create: tests/end_to_end/test_benchmark_smoke.py
- Modify: README.md
- Modify: README.zh-CN.md

**Interfaces:**
- Produces: run_suite(mode, seed, budget) -> BenchmarkRun。
- Produces: compare_runs(baseline, full, ablations) -> BenchmarkReport。
- Modes: baseline、polaris、no_context_routing、no_recovery_policy、no_independent_verifier。

- [ ] **Step 1: 写 benchmark schema 和 deterministic smoke test**

  每个 task 固定 repository fixture、contract、budget、allowed tools、fault schedule 和 scorer；报告必须记录模型版本、seed、token、latency、成功、约束违反和恢复结果。

- [ ] **Step 2: 运行 smoke test 并确认失败**

  Run: uv run pytest tests/end_to_end/test_benchmark_smoke.py -q

  Expected: FAIL，因为 suite/report 尚不完整。

- [ ] **Step 3: 实现 baseline/full/ablation runner 和报告**

  baseline 使用相同模型、工具权限、任务和预算，但关闭 Polaris 特有机制；ablation 每次只关闭一个机制。

- [ ] **Step 4: 运行全部 deterministic tests**

  Run: uv run pytest -q

  Expected: PASS。

- [ ] **Step 5: 运行真实模型 benchmark**

  Run: uv run python benchmarks/runner.py --suite long-tasks --modes baseline,polaris,no_context_routing,no_recovery_policy,no_independent_verifier

  Expected: 生成包含原始 run artifacts 和汇总统计的报告；不得只保留平均值。

- [ ] **Step 6: 根据 release gate 决定继续或停止扩展**

  仅当第 10 节所有机械指标满足，且正确完成率达到门槛时更新 README 为可试用状态。未达标则记录失败样本，删除无收益机制或回到对应任务修正，不增加新产品范围。

  Commit: test: add long-task reliability benchmarks

## 10. 测试矩阵与发布门槛

### 10.1 必须机械达到

- Action Boundary 崩溃恢复正确率：100%。
- Hard Constraint 持久化存活率：100%。
- stale observation 注入模型：0。
- 未经有效 Verifier PASS 写入 DONE：0。
- 工作区外 mutation：0。
- 无新前置条件下同一失败动作执行超过两次：0。
- Context Routing 额外 LLM 调用：0。
- event/state replay 不一致静默通过：0。

### 10.2 端到端 release gate

- 长任务正确完成率相对 baseline 提升至少 10 个百分点。
- 关键约束违反率相对 baseline 至少降低 50%。
- 中断恢复任务正确完成率至少 95%。
- 每个成功任务的输入 token 不超过 baseline 的 110%。
- Context Manager 自身 wall-time overhead 低于 5%，不含模型、工具和独立验证时间。

长期目标是在不降低正确完成率的前提下，使每个成功任务的输入 token 相对 baseline 降低至少 20%。

## 11. 阶段门禁

路线 C 按以下顺序推进：

1. **Foundation**：Task 1–3 建立权威数据、版本和恢复基础。
2. **Context Vertical Slice**：Task 4 单独证明主动 working set 能减少污染且不丢失关键约束。
3. **Controlled Runtime**：Task 5–7 把模型与工具纳入耐久 Controller 边界。
4. **Completion Authority**：Task 8 建立执行者不能绕过的独立完成裁决。
5. **Evidence Gate**：Task 9 用 baseline/full/ablation 决定哪些机制保留。

每个阶段必须满足自己的 deterministic tests 后才能进入下一阶段。真实模型 benchmark 不能替代故障注入和状态机测试。

## 12. 产品决策规则

新增任何机制前必须回答：

1. 它针对哪一种已观察到的长任务失败？
2. 它由 Harness 机械完成，还是只要求模型记住？
3. 它如何单独 benchmark 和 ablation？
4. 它增加多少 token、latency、持久化成本和状态复杂度？
5. 如果没有显著收益，能否完整删除？

无法给出可测答案的机制不进入第一版。

## 13. 最终产品判定

Polaris 的成功不是让任务无限续跑，也不是让上下文保存更多内容，而是：

> **模型在每一步都基于当前、可追溯、足够且不过载的事实行动；任何外部修改都有耐久边界；中断后能够安全恢复；只有与当前合同和当前工作区绑定的独立证据才能结束任务。**
