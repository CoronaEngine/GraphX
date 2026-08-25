# Polaris 长任务可靠性实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 构建一个面向单个长时间软件工程任务的受控 Agent Harness，使任务在上下文增长、进程中断、工作区变化、工具失败和模型过早宣布完成时，仍能稳定、正确、可恢复地执行。

**Architecture:** Polaris 采用路线 C：不把能力做成提示词集合或 Codex 外层补丁，而是由独立 Controller 掌握模型调用、上下文投影、工具执行、状态持久化、恢复和完成权限。第一条实现纵切面先证明主动 Context Working Set 的价值，随后补齐 Task Contract、Observation Ledger、Action Boundary 和 Independent Verifier，形成完整闭环。

**Tech Stack:** Python 3.12、标准库 dataclasses/json/pathlib、file-based storage、OpenAI Python SDK、pytest、pytest-asyncio、Hypothesis、uv；所有依赖写入 pyproject.toml 并锁定到 uv.lock。

**Spec:** 本文件同时是 Polaris 的产品规格、架构权威与分阶段实施计划。

## Global Constraints

- 只优化一个结果：一个长时间软件工程任务的正确完成率。
- 第一版仅支持 macOS、一个可信本地仓库、一个活动任务、一个前台 Controller 和 OpenAI 一个模型提供方。
- 不兼容旧 Polaris 的任务、协议、命令、Skills、Schemas、目录或迁移。
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

这些结论只描述当前可验证的公开行为，不假设未公开 hosted backend 的内部能力。

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

- 旧版兼容与迁移；
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
