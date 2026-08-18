# Polaris 工作流精简实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Polaris 升级到协议 `0.1.20` / workflow `0.1.3`，删除没有独立治理边界的状态和转换，并让本机实时进度不再阻断耐久流程。

**Architecture:** 以新的声明式 workflow 为控制面，把 Implementation、Documentation 和 Review handoff 合并进 `START_REVIEW` 门禁，把 Review 接受直接推进到 Validation，并为 R0/R1 提供原子 `PASS_AND_CLOSE`。任务校验拆成“已保存投影校验”和“候选投影校验”两层；迁移协议升级为 v2，显式替换冻结 workflow 并映射旧任务状态。

**Tech Stack:** Python 3.10+ 标准库、JSON Schema 有限子集、`unittest`、Git fixture。

**Spec:** `docs/superpowers/specs/2026-08-18-workflow-simplification-design.md`

## Global Constraints

- `plan.md` 是当前 v0.1 产品与实现 Authority，最终必须同步更新。
- 运行时不得新增 Python 标准库以外的依赖。
- 所有 JSON 使用四空格缩进，并由现有原子写入工具生成。
- 每个门禁、状态转换、迁移分支和 Validator 规则必须先有失败测试。
- Agent 不得直接写入 `VERIFIED` 或 `CLOSED`；仍由 `transition_task.py` 通过门禁转换。
- 历史 event 和 artifact 保持不可变；新版本只追加迁移事件并更新投影。
- Windows、macOS 与 Linux 路径和进程语义继续使用现有跨平台抽象。

---

### Task 1: 冻结 workflow 0.1.3 与新状态契约

**Files:**
- Modify: `workflow/default-workflow.json`
- Modify: `schemas/task-state.schema.json`
- Modify: `schemas/project-index.schema.json`
- Modify: `templates/project.json`
- Modify: `templates/task-sources/state.json`
- Generated: `templates/task/state.json`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: 现有 `transition_task.transition(...)` 对声明式 `event/from/to/gate` 的解释。
- Produces: workflow `0.1.3`；事件 `START_IMPLEMENTATION`、`START_REVIEW`、`ACCEPT_REVIEW`、`PASS_AND_CLOSE`、`PASS_VALIDATION`、`CLOSE` 的唯一合法边。

- [ ] **Step 1: 写入失败的 workflow 契约测试**

在 `tests/test_core.py` 新增：

```python
def test_workflow_013_contains_only_governance_states(self) -> None:
    workflow = read_json(ROOT / "workflow" / "default-workflow.json")
    self.assertEqual(workflow["workflow_version"], "0.1.3")
    self.assertNotIn("IMPLEMENTED", workflow["states"])
    self.assertNotIn("DOCS_SYNCED", workflow["states"])
    self.assertNotIn("REVIEWED", workflow["states"])
    events = {item["event"]: item for item in workflow["transitions"]}
    self.assertNotIn("DISPATCH_IMPLEMENTATION", events)
    self.assertNotIn("FINISH_IMPLEMENTATION", events)
    self.assertNotIn("SYNC_DOCS", events)
    self.assertNotIn("START_VALIDATION", events)
    self.assertEqual(events["START_REVIEW"]["from"], ["IMPLEMENTING"])
    self.assertEqual(events["ACCEPT_REVIEW"]["to"], "VALIDATING")
    self.assertEqual(events["PASS_AND_CLOSE"]["to"], "CLOSED")
```

- [ ] **Step 2: 运行测试并确认因旧 workflow 失败**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_workflow_013_contains_only_governance_states -v`

Expected: FAIL，报告 `0.1.2 != 0.1.3` 或旧状态仍存在。

- [ ] **Step 3: 最小修改 workflow、状态 Schema 和版本模板**

将主路径转换定义为：

```json
{
    "event": "START_IMPLEMENTATION",
    "from": ["PLANNED"],
    "to": "IMPLEMENTING",
    "gate": "implementation_start_ready"
}
```

```json
{
    "event": "START_REVIEW",
    "from": ["IMPLEMENTING"],
    "to": "REVIEWING",
    "gate": "review_start_ready"
}
```

```json
{
    "event": "ACCEPT_REVIEW",
    "from": ["REVIEWING"],
    "to": "VALIDATING",
    "gate": "review_accepted"
}
```

并增加 `PASS_AND_CLOSE` 的 `validation_passed_and_closure_ready` gate；`PASS_VALIDATION` 保留给 R2，`CLOSE` 保留为 `VERIFIED → CLOSED`。

- [ ] **Step 4: 物化任务模板并运行契约测试**

Run: `python3 scripts/materialize_task_layout.py`

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_workflow_013_contains_only_governance_states -v`

Expected: PASS。

- [ ] **Step 5: 提交声明式契约**

```bash
git add workflow/default-workflow.json schemas/task-state.schema.json schemas/project-index.schema.json templates/project.json templates/task-sources/state.json templates/task/state.json tests/test_core.py
git commit -m "feat: define simplified workflow 0.1.3"
```

### Task 2: 合并 Implementation、Documentation 与 Review 启动门禁

**Files:**
- Modify: `scripts/internal/transition_gates.py`
- Modify: `scripts/internal/transition_effects.py`
- Modify: `scripts/build_review_handoff.py`
- Modify: `scripts/internal/implementation_protocol.py`
- Modify: `scripts/update_implementation_progress.py`
- Modify: `scripts/validate_task.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `validate_implementation_handoff(...)`、`validate_handoff(...)`、`check_docs.check(...)`、artifact registration from `prepare_next_state(...)`。
- Produces: `check_implementation_artifact(...)`、`check_knowledge_delta(...)` 等可由 transition gate 和 task validator 复用的只读校验；`build_review_handoff.build(...)` 接受 `IMPLEMENTING` 且已有最终 artifact/subject 的状态。

- [ ] **Step 1: 写失败测试，证明 handoff 在 START_IMPLEMENTATION 中原子注册**

```python
def test_start_implementation_atomically_registers_handoff(self) -> None:
    self.freeze_and_plan()
    handoff = build_implementation_handoff(self.repo, "TASK-0001")
    result = transition(
        self.repo,
        "TASK-0001",
        "START_IMPLEMENTATION",
        [f"implementation_handoff={Path(handoff['path']).relative_to(self.task).as_posix()}"],
        None, None, None, None, None, None,
    )
    self.assertEqual(result["to"], "IMPLEMENTING")
    state = read_json(self.task / "state.json")
    self.assertIn("implementation_handoff", state["artifacts"])
    with self.assertRaisesRegex(RuleFailure, "unknown workflow event"):
        transition(
            self.repo, "TASK-0001", "DISPATCH_IMPLEMENTATION", [],
            None, None, None, None, None, None,
        )
```

- [ ] **Step 2: 写失败测试，证明 progress 缺失不阻断 START_REVIEW**

使用现有 fixture helper 生成最终 subject、Implementation、Knowledge Delta 和 Review handoff，删除 `runtime/progress.json` 后执行：

```python
result = transition(
    self.repo,
    "TASK-0001",
    "START_REVIEW",
    [
        "implementation=implementations/r001/attempt-001.json",
        "knowledge_delta=knowledge/r001/knowledge-delta-001.json",
        "review_handoff=reviews/r001/handoff-001.json",
    ],
    None,
    base,
    head,
    None,
    None,
    None,
)
self.assertEqual(result["to"], "REVIEWING")
```

- [ ] **Step 3: 运行两项测试并确认失败原因来自旧转换/旧 progress 门禁**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_start_implementation_atomically_registers_handoff tests.test_core.PolarisCoreTests.test_start_review_does_not_require_live_progress -v`

Expected: FAIL；旧 `START_IMPLEMENTATION` 不接受 handoff 或 `build_review_handoff` 只允许 `DOCS_SYNCED`。

- [ ] **Step 4: 实现组合 gate 与共享 artifact 校验**

在 `transition_gates.check_gate(...)` 中用两个组合分支替代旧四个分支：

```python
if gate == "implementation_start_ready":
    if state["rigor"] == "R2":
        artifact_file(directory, state, "pre_approval")
    validate_implementation_handoff(repo, root, directory, state, True)
elif gate == "review_start_ready":
    validate_implementation_record(repo, root, directory, state)
    validate_knowledge_delta(repo, root, directory, state)
    validate_handoff(repo, root, directory, state)
```

移除 `validate_progress(...)` 对耐久 gate 的调用。`update_implementation_progress.py` 和 `implementation_protocol.validate_progress(...)` 只接受当前 `IMPLEMENTING`；允许 `DOCUMENTING/COMPLETED` phase 在该状态内发生。

- [ ] **Step 5: 更新 Review handoff 构建入口与 validator 状态顺序**

`build_review_handoff.build(...)` 从 `IMPLEMENTING` 读取已注册 Implementation、Knowledge Delta 和最终 subject。`validate_task.py` 不再使用线性 `ORDER/at_least` 推断已删除状态，而按当前状态需要的 artifact 集合校验。

- [ ] **Step 6: 运行 Implementation/Review/Progress 相关测试**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_start_implementation_atomically_registers_handoff tests.test_core.PolarisCoreTests.test_start_review_does_not_require_live_progress tests.test_core.PolarisCoreTests.test_implementation_steps_are_linear_append_only_and_acceptance_bound tests.test_core.PolarisCoreTests.test_live_progress_rejects_session_takeover_and_invalid_blocker -v`

Expected: PASS。

- [ ] **Step 7: 提交合并门禁**

```bash
git add scripts/internal/transition_gates.py scripts/internal/transition_effects.py scripts/build_review_handoff.py scripts/internal/implementation_protocol.py scripts/update_implementation_progress.py scripts/validate_task.py tests/test_core.py
git commit -m "feat: combine implementation and review readiness gates"
```

### Task 3: 候选投影校验与 R0/R1 原子关闭

**Files:**
- Modify: `scripts/validate_task.py`
- Modify: `scripts/internal/transition_gates.py`
- Modify: `scripts/transition_task.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Produces: `validate_projection(repo: Path, task_id: str, state: dict[str, Any], *, check_event_projection: bool) -> dict[str, Any]`。
- Consumes: `transition_task.prepare_next_state(...)` 生成的候选 state，以及 `apply_event_effects(...)` 计算后的最终 destination。

- [ ] **Step 1: 写失败的 Review 直达 Validation 测试**

```python
accepted = transition(
    self.repo,
    "TASK-0001",
    "ACCEPT_REVIEW",
    ["review=reviews/r001/review-001.json"],
    None, None, None, None, None, None,
)
self.assertEqual(accepted["to"], "VALIDATING")
with self.assertRaisesRegex(RuleFailure, "unknown workflow event"):
    transition(
        self.repo, "TASK-0001", "START_VALIDATION", [],
        None, None, None, None, None, None,
    )
```

- [ ] **Step 2: 写失败的 R1 PASS_AND_CLOSE 候选投影测试**

```python
closed = transition(
    self.repo,
    "TASK-0001",
    "PASS_AND_CLOSE",
    [
        "validation=validations/r001/validation-001.json",
        "result=results/r001/result-001.json",
    ],
    None, None, None, None, None, None,
)
self.assertEqual(closed["to"], "CLOSED")
self.assertEqual(validate(self.repo, "TASK-0001")["state"], "CLOSED")
```

再加入反例：篡改已注册 Implementation hash 后，`PASS_AND_CLOSE` 必须在追加事件前失败，并保持 sequence/status 不变。

- [ ] **Step 3: 写失败的 R2 分流测试**

```python
with self.assertRaisesRegex(RuleFailure, "R0/R1"):
    transition(
        self.repo, "TASK-0001", "PASS_AND_CLOSE", artifacts,
        None, None, None, None, None, None,
    )
verified = transition(
    self.repo, "TASK-0001", "PASS_VALIDATION",
    ["validation=validations/r001/validation-001.json"],
    None, None, None, None, None, None,
)
self.assertEqual(verified["to"], "VERIFIED")
```

- [ ] **Step 4: 运行测试并确认旧流程失败**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_review_acceptance_enters_validation tests.test_core.PolarisCoreTests.test_r1_pass_and_close_validates_candidate_projection tests.test_core.PolarisCoreTests.test_r2_keeps_verified_final_approval_gate -v`

Expected: FAIL，事件缺失或目标状态仍为旧值。

- [ ] **Step 5: 抽取共享投影校验并在关闭 gate 中调用**

`validate(...)` 继续执行 event/state 重建一致性，然后调用
`validate_projection(repo: Path, task_id: str, state: dict[str, Any]) -> dict[str, Any]`。
该函数依次校验协议与 workflow 版本、Work Item 身份和 rigor、当前状态要求的
Plan/Working Set、Implementation/Knowledge Delta、Review、Validation、Result、subject
绑定及 R2 approval，并返回包含 `message`、`task` 和 `state` 的结果对象。

`transition_task.transition(...)` 在 `apply_event_effects(...)` 后先将 candidate `status` 设为 destination，再把候选传给 closure gate 或统一的 post-gate candidate validator，只有成功后才增加 sequence、追加事件并写 state。

- [ ] **Step 6: 实现严格 rigor 分流**

`validation_passed_and_closure_ready` 拒绝 R2，并要求 PASS Validation、完整 AC、Result 和 candidate CLOSED 投影；`validation_passed` 拒绝非 R2。`closure_ready` 只接受 R2 的 VERIFIED 状态、Result、final approval 和完整 candidate CLOSED 投影。

- [ ] **Step 7: 运行关闭与完整 R1/R2 测试**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_review_acceptance_enters_validation tests.test_core.PolarisCoreTests.test_r1_pass_and_close_validates_candidate_projection tests.test_core.PolarisCoreTests.test_r2_keeps_verified_final_approval_gate tests.test_core.PolarisCoreTests.test_full_r1_flow_closes_only_after_review_and_validation -v`

Expected: PASS。

- [ ] **Step 8: 提交候选校验和关闭路径**

```bash
git add scripts/validate_task.py scripts/internal/transition_gates.py scripts/transition_task.py tests/test_core.py
git commit -m "feat: validate candidate projection before task closure"
```

### Task 4: 升级迁移协议并映射 workflow 0.1.2 任务

**Files:**
- Modify: `schemas/migration-protocol.schema.json`
- Modify: `schemas/migration-record.schema.json`
- Modify: `schemas/event.schema.json`
- Modify: `workflow/migrations.json`
- Modify: `scripts/internal/migration_protocol.py`
- Test: `tests/test_core.py`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Produces: migration protocol v2 strategy `replace_version_and_workflow` / `append_mapped_workflow_event`。
- Produces: `map_migrated_status(state: dict[str, Any]) -> tuple[str, str | None]`，返回新 status 和映射后的 blocked_from。

- [ ] **Step 1: 写状态映射表驱动失败测试**

```python
cases = {
    "DRAFT": "DRAFT",
    "QUALIFIED": "QUALIFIED",
    "PLANNED": "PLANNED",
    "IMPLEMENTED": "IMPLEMENTING",
    "DOCS_SYNCED": "IMPLEMENTING",
    "REVIEWING": "REVIEWING",
    "REVIEWED": "VALIDATING",
    "VALIDATING": "VALIDATING",
    "VERIFIED": "VERIFIED",
    "CLOSED": "CLOSED",
    "CANCELLED": "CANCELLED",
}
for old, expected in cases.items():
    with self.subTest(old=old):
        state = {"status": old, "blocked_from": None, "artifacts": {}}
        self.assertEqual(map_migrated_status(state)[0], expected)
```

另测 `IMPLEMENTING` 无 handoff 映射到 `PLANNED`、有 handoff保持 `IMPLEMENTING`，以及 `BLOCKED.blocked_from` 同步映射。

- [ ] **Step 2: 写完整迁移失败测试**

从协议 `0.1.19` / workflow `0.1.2` fixture 运行 `migrate_project(...)`，断言：

```python
self.assertEqual(project["polaris_version"], "0.1.20")
self.assertEqual(project["workflow_version"], "0.1.3")
self.assertEqual(frozen_workflow["workflow_version"], "0.1.3")
self.assertEqual(event["from"], "DOCS_SYNCED")
self.assertEqual(event["to"], "IMPLEMENTING")
self.assertEqual(event["previous_workflow_version"], "0.1.2")
```

- [ ] **Step 3: 运行测试并确认 v1 协议拒绝 workflow 变化**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_workflow_migration_maps_every_legacy_state tests.test_core.PolarisCoreTests.test_migration_replaces_frozen_workflow_and_maps_tasks -v`

Expected: FAIL，报告 v1 migration protocol cannot change workflow versions。

- [ ] **Step 4: 实现 migration protocol v2 Schema 与注册步骤**

新增 `0.1.19-to-0.1.20`：

```json
{
    "migration_id": "0.1.19-to-0.1.20",
    "from_polaris_version": "0.1.19",
    "to_polaris_version": "0.1.20",
    "from_workflow_version": "0.1.2",
    "to_workflow_version": "0.1.3",
    "project_strategy": "replace_version_and_workflow",
    "task_strategy": "append_mapped_workflow_event"
}
```

旧步骤继续使用 v1 strategy 值，协议 loader 按 strategy 验证是否允许 workflow 变化。

- [ ] **Step 5: 实现事件、记录和冻结 workflow 替换**

迁移事件记录 `from/to` 状态和 `previous_polaris_version`、`previous_workflow_version`；migration record task entry增加 `source_status`、`target_status`。在持有所有任务锁且写入 IN_PROGRESS record 后，用 vendored `default-workflow.json` 原子替换 `.polaris/workflow.json`，再更新 project 版本。

- [ ] **Step 6: 验证崩溃恢复和历史 Code Intelligence 迁移不回归**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_migration_replaces_frozen_workflow_and_maps_tasks tests.test_core.PolarisCoreTests.test_migration_resumes_after_event_append_without_duplication tests.test_codegraph.CodeGraphTests.test_migration_retires_v1_records_without_rewriting_them -v`

Expected: PASS。

- [ ] **Step 7: 提交 workflow 迁移**

```bash
git add schemas/migration-protocol.schema.json schemas/migration-record.schema.json schemas/event.schema.json workflow/migrations.json scripts/internal/migration_protocol.py tests/test_core.py tests/test_codegraph.py
git commit -m "feat: migrate frozen projects to workflow 0.1.3"
```

### Task 5: 同步恢复、Skills、可选 Code Intelligence 与宿主表面

**Files:**
- Modify: `scripts/internal/recovery_protocol.py`
- Modify: `scripts/recover_task.py`
- Modify: `skills/engineering-task/SKILL.md`
- Modify: `skills/implementation/SKILL.md`
- Modify: `skills/documentation-sync/SKILL.md`
- Modify: `skills/adversarial-review/SKILL.md`
- Modify: `skills/validation/SKILL.md`
- Modify: `skills/architecture-planning/SKILL.md`
- Modify: `skills/code-intelligence/SKILL.md`
- Modify: `hosts/codex/skill-appendices/engineering-task.md`
- Modify: `hosts/claude-code/skill-appendices/engineering-task.md`
- Test: `tests/test_core.py`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: 新 workflow event/state 名称。
- Produces: 新的稳定对话标记、Worker prompt、恢复 next action，以及“只有实际 Provider 操作才写耐久 record”的阶段规则。

- [ ] **Step 1: 写失败的 Skill/恢复表面测试**

```python
surfaces = [
    ROOT / "skills/engineering-task/SKILL.md",
    ROOT / "skills/validation/SKILL.md",
    ROOT / "docs/USAGE.md",
]
for path in surfaces:
    text = path.read_text(encoding="utf-8")
    self.assertNotIn("DISPATCH_IMPLEMENTATION", text)
    self.assertNotIn("START_VALIDATION", text)
self.assertIn("PASS_AND_CLOSE", (ROOT / "skills/validation/SKILL.md").read_text())
```

为 Code Intelligence 增加测试：缺少 `.codegraph/` 时，阶段 Skill 明确允许省略 record，而不是要求 durable `UNAVAILABLE` artifact。

- [ ] **Step 2: 运行表面测试并确认旧文案失败**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_workflow_surfaces_use_simplified_events tests.test_codegraph.CodeGraphTests.test_stage_surfaces_do_not_require_unused_provider_records -v`

Expected: FAIL，旧事件名和 mandatory unavailable record 仍存在。

- [ ] **Step 3: 更新恢复动作和 progress 读取边界**

`NEXT_ACTIONS` 只包含新状态；`IMPLEMENTING` 同时覆盖实现、文档和 Review handoff 准备。`recover_task.py` 仅在 `IMPLEMENTING` 且 progress 文件存在时尝试读取；无文件返回 `None`，不视为 blocker。

- [ ] **Step 4: 更新 canonical Skills 与宿主 appendix**

主 Controller 的新顺序是：构建 handoff并 `START_IMPLEMENTATION`、派发 Implementer、等待最终 Implementation + Knowledge Delta、构建 Review handoff并 `START_REVIEW`、Reviewer ACCEPT 后进入 VALIDATING、R0/R1 `PASS_AND_CLOSE`、R2 `PASS_VALIDATION` 后等待最终批准再 `CLOSE`。

Documentation Sync 继续作为同一 Implementer 内部 Skill，但在 `IMPLEMENTING` 内完成且不再对应 Graph transition。

- [ ] **Step 5: 放宽未使用 Code Intelligence 的 durable record 要求**

Planning、Implementation、Review、Documentation Sync 在未执行 status/sync/explore 时不生成 record；一旦执行 Provider 操作，继续使用 v2 record、freshness 和源码回退校验。Artifact Schema 中已有可选 `code_intelligence` 字段，不新增空占位字段。

- [ ] **Step 6: 运行 Skill 渲染、宿主和 Code Intelligence 测试**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_workflow_surfaces_use_simplified_events tests.test_core.PolarisCoreTests.test_host_adapters_render_from_one_host_neutral_skill_source tests.test_codegraph.CodeGraphTests.test_stage_surfaces_do_not_require_unused_provider_records tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_share_codegraph_fallback_rules -v`

Expected: PASS。

- [ ] **Step 7: 提交执行表面更新**

```bash
git add scripts/internal/recovery_protocol.py scripts/recover_task.py skills hosts tests/test_core.py tests/test_codegraph.py
git commit -m "docs: align workflow skills with simplified states"
```

### Task 6: 更新 Authority、用户文档、版本与生成物

**Files:**
- Modify: `VERSION`
- Modify: `plan.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/USAGE.md`
- Modify: `templates/task-sources/*` as required by changed defaults
- Generated: `templates/task/*`
- Test: `tests/test_core.py`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Produces: 所有产品 Authority、用户说明、模板和版本字符串一致指向协议 `0.1.20` / workflow `0.1.3`。

- [ ] **Step 1: 更新版本一致性测试并确认失败**

把现有版本表面断言改为：

```python
for path in version_surfaces:
    text = path.read_text(encoding="utf-8")
    self.assertIn("0.1.20", text, path.as_posix())
    self.assertIn("0.1.3", text, path.as_posix())
```

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_managed_surfaces_only_name_the_official_codegraph -v`

Expected: FAIL，当前版本仍为 `0.1.19` / `0.1.2`。

- [ ] **Step 2: 更新 VERSION、plan.md、README 和 USAGE**

删除旧 happy path、中间 checkpoint 和 mandatory progress/Code Intelligence record 叙述；写入迁移 `0.1.19 → 0.1.20`、状态映射、R0/R1 `PASS_AND_CLOSE` 与 R2 `VERIFIED` 最终批准路径。

- [ ] **Step 3: 重新物化模板并检查生成漂移**

Run: `python3 scripts/materialize_task_layout.py`

Run: `python3 scripts/materialize_task_layout.py --check`

Expected: PASS；如果脚本不提供 `--check`，运行 `python3 -m unittest tests.test_core.PolarisCoreTests.test_task_layout_is_single_source_and_templates_mirror_it -v` 作为机械检查。

- [ ] **Step 4: 运行文档、版本和模板测试**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_task_layout_is_single_source_and_templates_mirror_it tests.test_core.PolarisCoreTests.test_skills_define_stable_conversation_checkpoints tests.test_codegraph.CodeGraphTests.test_readmes_keep_codegraph_operational_boundaries -v`

Expected: PASS。

- [ ] **Step 5: 提交 Authority 和文档**

```bash
git add VERSION plan.md README.md README.zh-CN.md docs/USAGE.md templates tests/test_core.py tests/test_codegraph.py
git commit -m "docs: publish Polaris 0.1.20 workflow 0.1.3"
```

### Task 7: 全量回归、编译和干净交付

**Files:**
- Modify: only files required by failures attributable to this workflow change
- Test: `tests/run_tests.py`

**Interfaces:**
- Produces: 一个标准库运行时、模板一致、完整测试通过的协议版本。

- [ ] **Step 1: 运行完整自动化测试**

Run: `python3 tests/run_tests.py`

Expected: `150+` tests，失败 `0`、错误 `0`。

- [ ] **Step 2: 运行 unittest discovery**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS。

- [ ] **Step 3: 运行编译检查**

Run: `python3 -m compileall -q polaris_cli.py scripts tests`

Expected: exit `0`，无输出。

- [ ] **Step 4: 运行文档和模板检查**

Run: `python3 scripts/check_docs.py --help`

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_task_layout_is_single_source_and_templates_mirror_it -v`

Expected: PASS。

- [ ] **Step 5: 检查最终 diff 与工作区**

Run: `git diff --check`

Run: `git status --short`

Expected: 没有 whitespace error；只有本计划范围内的预期修改，或在最终提交后 clean。

- [ ] **Step 6: 最终提交（仅在仍有已验证修改时）**

```bash
git add -A
git commit -m "test: verify simplified Polaris workflow"
```
