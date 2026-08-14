from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from init_project import initialize as init_project  # noqa: E402
from init_task import initialize as init_task  # noqa: E402
from build_working_set import build as build_working_set  # noqa: E402
from build_implementation_handoff import build as build_implementation_handoff  # noqa: E402
from build_review_handoff import build as build_review_handoff  # noqa: E402
from check_docs import check as check_docs  # noqa: E402
from new_revision import create as new_revision  # noqa: E402
from polaris_core import (  # noqa: E402
    InputFailure,
    RuleFailure,
    append_jsonl,
    file_sha256,
    read_json,
    rebuild_state_value,
    subject_diff_hash,
    validate_schema,
    write_json_atomic,
)
from rebuild_state import rebuild  # noqa: E402
from recover_task import recover  # noqa: E402
from record_exploration import promote as promote_exploration  # noqa: E402
from record_exploration import record as record_exploration  # noqa: E402
from transition_task import transition  # noqa: E402
from update_implementation_progress import update as update_implementation_progress  # noqa: E402
from implementation_protocol import validate_progress  # noqa: E402
from validate_task import validate  # noqa: E402
from validate_project import validate as validate_project  # noqa: E402
from vendor_project import SKILLS, vendor  # noqa: E402


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


class PolarisCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="polaris-test-")
        self.repo = Path(self.temp.name)
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.email", "polaris@test.local")
        run_git(self.repo, "config", "user.name", "Polaris Test")
        run_git(self.repo, "commit", "-q", "--allow-empty", "-m", "seed")
        init_project(self.repo, "test-project")
        init_task(self.repo, "TASK-0001", "R1")

    def tearDown(self) -> None:
        self.temp.cleanup()

    @property
    def task(self) -> Path:
        return self.repo / ".polaris" / "tasks" / "TASK-0001"

    def freeze_work_item(self) -> None:
        path = self.task / "revisions" / "work-item-r001.json"
        value = read_json(path)
        value.update(
            {
                "title": "Smoke task",
                "goal": "Exercise transitions",
                "motivation": "Test the mechanical core",
            }
        )
        value["scope"]["in"] = ["scripts"]
        value["acceptance"][0].update(
            {"statement": "Task reaches PLANNED", "evidence": "state validation"}
        )
        value["implementation_dispatch"]["authorized"] = True
        value["review_dispatch"]["authorized"] = True
        write_json_atomic(path, value)

    def dispatch_implementation(self) -> tuple[dict[str, object], dict[str, str]]:
        state = read_json(self.task / "state.json")
        existing = state["artifacts"].get("implementation_handoff")
        if existing is None:
            result = build_implementation_handoff(self.repo, "TASK-0001")
            handoff_path = Path(result["path"])
            transition(
                self.repo,
                "TASK-0001",
                "DISPATCH_IMPLEMENTATION",
                [
                    "implementation_handoff="
                    + handoff_path.relative_to(self.task).as_posix()
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )
            state = read_json(self.task / "state.json")
            existing = state["artifacts"]["implementation_handoff"]
        handoff_path = self.task / existing["path"]
        return read_json(handoff_path), existing

    def enter_implementing(self) -> None:
        self.freeze_work_item()
        build_working_set(self.repo, "TASK-0001", True)
        transition(
            self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
        )
        transition(
            self.repo,
            "TASK-0001",
            "PLAN",
            ["plan=PLAN.md", "working_set=WORKING_SET.md"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        transition(
            self.repo,
            "TASK-0001",
            "START_IMPLEMENTATION",
            [],
            None,
            None,
            None,
            None,
            None,
            None,
        )

    def implementation_value(
        self, base: str, head: str, session_id: str
    ) -> dict[str, object]:
        handoff, reference = self.dispatch_implementation()
        value = read_json(ROOT / "templates" / "task" / "implementation.json")
        value.update(
            {
                "artifact_attempt": handoff["artifact_attempt"],
                "implementer_session_id": session_id,
                "implementation_handoff_path": reference["path"],
                "implementation_handoff_sha256": reference["sha256"],
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": subject_diff_hash(self.repo, base, head),
            }
        )
        return value

    def knowledge_value(
        self, attempt: int, base: str, head: str
    ) -> dict[str, object]:
        value = read_json(ROOT / "templates" / "task" / "knowledge-delta.json")
        value.update(
            {
                "artifact_attempt": attempt,
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": subject_diff_hash(self.repo, base, head),
            }
        )
        return value

    def start_review(
        self,
        implementer_session_id: str = "impl-session",
        isolation: str = "fresh_session",
    ) -> tuple[dict[str, object], dict[str, object]]:
        handoff_result = build_review_handoff(
            self.repo,
            "TASK-0001",
            implementer_session_id,
            isolation,
        )
        handoff_path = Path(handoff_result["path"])
        transition(
            self.repo,
            "TASK-0001",
            "START_REVIEW",
            [f"review_handoff={handoff_path.relative_to(self.task).as_posix()}"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        state = read_json(self.task / "state.json")
        return read_json(handoff_path), state

    def review_value(
        self,
        handoff: dict[str, object],
        state: dict[str, object],
        reviewer_session_id: str,
        verdict: str,
        findings: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        reference = state["artifacts"]["review_handoff"]
        subject = state["subject"]
        review = read_json(ROOT / "templates" / "task" / "review.json")
        review.update(
            {
                "work_item_revision": state["current_revision"],
                "artifact_attempt": handoff["artifact_attempt"],
                "implementer_session_id": handoff["implementer_session_id"],
                "reviewer_session_id": reviewer_session_id,
                "handoff_path": reference["path"],
                "handoff_sha256": reference["sha256"],
                "isolation_attestation": {
                    "mode": handoff["required_isolation"],
                    "chat_history_inherited": False,
                    "reviewed_from_handoff_only": True,
                },
                "supersedes_review": handoff["previous_review"],
                "subject_base_commit": subject["base_commit"],
                "subject_head_commit": subject["head_commit"],
                "subject_diff_hash": subject["diff_hash"],
                "reviewed_at": "2026-08-13T00:00:00Z",
                "verdict": verdict,
                "findings": findings or [],
            }
        )
        return review

    def finish_and_reject_attempt(
        self,
        attempt: int,
        base: str,
        implementer_session_id: str,
        reviewer_session_id: str,
        finding: dict[str, object],
    ) -> dict[str, object]:
        self.dispatch_implementation()
        (self.repo / "subject.txt").write_text(
            f"review attempt {attempt}\n", encoding="utf-8"
        )
        run_git(self.repo, "add", "subject.txt")
        run_git(self.repo, "commit", "-q", "-m", f"review attempt {attempt}")
        head = run_git(self.repo, "rev-parse", "HEAD")
        diff_hash = subject_diff_hash(self.repo, base, head)
        implementation_path = (
            self.task / "implementations" / "r001" / f"attempt-{attempt:03d}.json"
        )
        implementation = self.implementation_value(base, head, implementer_session_id)
        write_json_atomic(implementation_path, implementation)
        artifacts = [
            f"implementation=implementations/r001/attempt-{attempt:03d}.json"
        ]
        if attempt > 1:
            prior_reference = read_json(self.task / "state.json")["artifacts"][
                "prior_review"
            ]
            response_path = (
                self.task / "reviews" / "r001" / f"response-{attempt:03d}.json"
            )
            response = read_json(ROOT / "templates" / "task" / "review-response.json")
            response.update(
                {
                    "artifact_attempt": attempt,
                    "implementer_session_id": implementer_session_id,
                    "prior_review_path": prior_reference["path"],
                    "prior_review_sha256": prior_reference["sha256"],
                    "subject_base_commit": base,
                    "subject_head_commit": head,
                    "subject_diff_hash": diff_hash,
                    "responded_at": f"2026-08-13T00:0{attempt}:00Z",
                    "responses": [
                        {
                            "finding_id": finding["id"],
                            "response": f"Reworked the subject for attempt {attempt}",
                            "evidence": f"Complete subject diff for attempt {attempt}",
                        }
                    ],
                }
            )
            write_json_atomic(response_path, response)
            artifacts.append(f"review_response=reviews/r001/response-{attempt:03d}.json")
        transition(
            self.repo,
            "TASK-0001",
            "FINISH_IMPLEMENTATION",
            artifacts,
            None,
            base,
            head,
            None,
            None,
            None,
        )
        knowledge_path = (
            self.task
            / "knowledge"
            / "r001"
            / f"knowledge-delta-{attempt:03d}.json"
        )
        knowledge = self.knowledge_value(attempt, base, head)
        knowledge["entries"][0].update(
            {"changed_paths": ["subject.txt"], "evidence": "No documentation impact"}
        )
        write_json_atomic(knowledge_path, knowledge)
        transition(
            self.repo,
            "TASK-0001",
            "SYNC_DOCS",
            [f"knowledge_delta=knowledge/r001/knowledge-delta-{attempt:03d}.json"],
            None,
            base,
            head,
            None,
            None,
            None,
        )
        handoff, state = self.start_review(implementer_session_id)
        current_finding = copy.deepcopy(finding)
        if attempt > 1:
            current_finding["evidence"] = f"Counterexample remains in attempt {attempt}"
            current_finding["reviewer_resolution"] = (
                f"Author response checked; defect remains in attempt {attempt}"
            )
        review_path = self.task / "reviews" / "r001" / f"review-{attempt:03d}.json"
        write_json_atomic(
            review_path,
            self.review_value(
                handoff,
                state,
                reviewer_session_id,
                "REJECT",
                [current_finding],
            ),
        )
        return transition(
            self.repo,
            "TASK-0001",
            "REJECT_REVIEW",
            [f"review=reviews/r001/review-{attempt:03d}.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )

    def test_new_draft_is_valid_and_rebuildable(self) -> None:
        """新建 DRAFT 任务可校验，并能从事件账本重建完全一致的状态。"""
        result = validate(self.repo, "TASK-0001")
        self.assertEqual(result["state"], "DRAFT")
        rebuilt = rebuild_state_value(self.task / "events.jsonl")
        self.assertEqual(rebuilt, read_json(self.task / "state.json"))
        state_text = (self.task / "state.json").read_text(encoding="utf-8")
        self.assertIn('\n    "task_id":', state_text)

    def test_legal_and_eight_illegal_work_item_fixtures(self) -> None:
        """合法 Work Item 通过，八类字段、ID、Revision 和风险格式错误被拒绝。"""
        fixture = read_json(ROOT / "tests" / "fixtures" / "work-item-cases.json")
        schema = read_json(ROOT / "schemas" / "work-item.schema.json")
        self.assertEqual(validate_schema(fixture["legal"], schema), [])
        for case in fixture["invalid"]:
            value = copy.deepcopy(fixture["legal"])
            parent = value
            for component in case["path"][:-1]:
                parent = parent[component]
            final = case["path"][-1]
            if case["operation"] == "delete":
                del parent[final]
            else:
                parent[final] = case["value"]
            with self.subTest(case=case["name"]):
                self.assertTrue(validate_schema(value, schema))

    def test_qualify_plan_and_reject_illegal_close(self) -> None:
        """DRAFT 可合法进入 QUALIFIED/PLANNED，但不能越过门禁直接 CLOSED。"""
        self.freeze_work_item()
        qualified = transition(
            self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
        )
        self.assertEqual(qualified["to"], "QUALIFIED")
        with self.assertRaises(RuleFailure):
            transition(
                self.repo, "TASK-0001", "CLOSE", [], None, None, None, None, None, None
            )
        planned = transition(
            self.repo,
            "TASK-0001",
            "PLAN",
            ["plan=PLAN.md", "working_set=WORKING_SET.md"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(planned["to"], "PLANNED")
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "PLANNED")

    def test_qualify_rejects_unresolved_acceptance_placeholders(self) -> None:
        """验收描述或证据为空白/TODO 时，Work Item 不得进入 QUALIFIED。"""
        self.freeze_work_item()
        path = self.task / "revisions" / "work-item-r001.json"
        frozen_draft = read_json(path)
        cases = [
            ("statement_blank", "statement", ""),
            ("statement_todo", "statement", "TODO"),
            ("evidence_blank", "evidence", "   "),
            ("evidence_todo", "evidence", "todo"),
        ]
        for name, field, invalid_value in cases:
            value = copy.deepcopy(frozen_draft)
            value["acceptance"][0][field] = invalid_value
            write_json_atomic(path, value)
            with self.subTest(case=name), self.assertRaises(RuleFailure):
                transition(
                    self.repo,
                    "TASK-0001",
                    "QUALIFY",
                    [],
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )

    def test_rebuild_repairs_state_projection(self) -> None:
        """手工伪造 CLOSED 状态会被发现，state 可由 events 恢复为 DRAFT。"""
        state_path = self.task / "state.json"
        state = read_json(state_path)
        state["status"] = "CLOSED"
        write_json_atomic(state_path, state)
        with self.assertRaises(RuleFailure):
            validate(self.repo, "TASK-0001")
        rebuild(self.repo, "TASK-0001", False)
        self.assertEqual(read_json(state_path)["status"], "DRAFT")

    def test_missing_work_item_is_an_input_error(self) -> None:
        """当前 Revision 的 Work Item 缺失时返回输入错误，不猜测任务合同。"""
        (self.task / "revisions" / "work-item-r001.json").unlink()
        with self.assertRaises(InputFailure):
            validate(self.repo, "TASK-0001")

    def test_broken_event_sequence_is_rejected(self) -> None:
        """Event sequence 断裂时拒绝恢复，避免跳过或重排审计事件。"""
        append_jsonl(
            self.task / "events.jsonl",
            {
                "sequence": 2,
                "event": "BROKEN",
                "from": "DRAFT",
                "to": "DRAFT",
            },
        )
        with self.assertRaises(InputFailure):
            validate(self.repo, "TASK-0001")

    def test_blocked_task_only_resumes_to_blocked_from(self) -> None:
        """BLOCKED 保存原状态，解除阻塞后只能返回 blocked_from。"""
        blocked = transition(
            self.repo,
            "TASK-0001",
            "BLOCK",
            [],
            None,
            None,
            None,
            "human_approval",
            "Need a boundary decision",
            "human",
        )
        self.assertEqual(blocked["to"], "BLOCKED")
        resumed = transition(
            self.repo,
            "TASK-0001",
            "RESOLVE_BLOCK",
            [],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(resumed["to"], "DRAFT")

    def test_transition_lock_conflict_is_rejected(self) -> None:
        """任务锁已占用时拒绝并发状态写入，保护 event/state 一致性。"""
        (self.task / ".transition.lock").write_text("held", encoding="utf-8")
        with self.assertRaises(InputFailure):
            transition(
                self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
            )

    def test_project_version_mismatch_is_rejected(self) -> None:
        """项目与 vendored Polaris 版本不一致时拒绝执行，不进行隐式迁移。"""
        project_path = self.repo / ".polaris" / "project.json"
        project = read_json(project_path)
        project["polaris_version"] = "0.1.9"
        write_json_atomic(project_path, project)
        with self.assertRaises(RuleFailure):
            validate_project(self.repo)

    def test_risk_flag_requires_r2(self) -> None:
        """任一高风险标记为 true 时，非 R2 Work Item 会被机械拒绝。"""
        path = self.task / "revisions" / "work-item-r001.json"
        value = read_json(path)
        value["risk_flags"]["security"] = True
        write_json_atomic(path, value)
        with self.assertRaises(RuleFailure):
            validate(self.repo, "TASK-0001")

    def test_vendored_target_is_self_contained(self) -> None:
        """目标仓库 vendoring 后仅凭 Skills、工具、状态和 Python 即可校验。"""
        vendor(ROOT, self.repo, False)
        self.assertTrue(
            (self.repo / ".agents" / "skills" / "engineering-task" / "SKILL.md").is_file()
        )
        self.assertTrue((self.repo / "tools" / "polaris" / "VERSION").is_file())
        result = validate_project(self.repo)
        self.assertEqual(result["active_tasks"], 1)

    def test_engineering_task_requires_explicit_invocation(self) -> None:
        """所有 Polaris Skills 禁止隐式调用，用户只能从 engineering-task 显式进入。"""
        source_skill = ROOT / "skills" / "engineering-task"
        source_instructions = (source_skill / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("only when the user explicitly invokes `$engineering-task`", source_instructions)
        self.assertIn(
            "only when the user explicitly invokes `$engineering-task`",
            (self.repo / "AGENTS.md").read_text(encoding="utf-8"),
        )

        vendor(ROOT, self.repo, False)
        for skill_name in SKILLS:
            source = ROOT / "skills" / skill_name
            vendored = self.repo / ".agents" / "skills" / skill_name
            source_metadata = (source / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )
            self.assertIn("allow_implicit_invocation: false", source_metadata)
            self.assertEqual(
                (vendored / "SKILL.md").read_text(encoding="utf-8"),
                (source / "SKILL.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (vendored / "agents" / "openai.yaml").read_text(encoding="utf-8"),
                source_metadata,
            )

    def test_skills_define_stable_conversation_checkpoints(self) -> None:
        """入口与每个阶段 Skill 都定义固定对话检查点，vendoring 后保持一致。"""
        expected_markers = {
            "engineering-task": [
                "POLARIS_STARTED",
                "IMPLEMENTATION_SESSION_STARTED",
                "IMPLEMENTATION_PROGRESS",
                "IMPLEMENTATION_FINISHED",
                "DOCS_SYNCED",
                "REVIEW_SESSION_STARTED",
                "REVIEW_ACCEPTED",
                "REVIEW_REJECTED",
                "TASK_BLOCKED",
                "TASK_CANCELLED",
                "TASK_CLOSED",
            ],
            "requirement-analysis": [
                "REQUIREMENTS_NEEDED",
                "WORK_ITEM_PREVIEW",
                "WORK_ITEM_QUALIFIED",
            ],
            "architecture-planning": ["PLAN_READY"],
            "implementation": [],
            "documentation-sync": [],
            "adversarial-review": [],
            "validation": ["VALIDATION_PASS", "VALIDATION_FAIL"],
        }
        contract_fields = [
            "`Task`",
            "`Revision`",
            "`Rigor`",
            "`State`",
            "`Outcome`",
            "`Authority`",
            "`Remaining`",
            "`Next`",
            "`User action`",
        ]
        entry_text = (ROOT / "skills" / "engineering-task" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        for field in contract_fields:
            self.assertIn(field, entry_text)

        requirement_text = (
            ROOT / "skills" / "requirement-analysis" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "two or three concrete, mutually exclusive answer options",
            requirement_text,
        )
        self.assertIn("(Recommended)", requirement_text)
        self.assertIn("precise free-form answer", requirement_text)
        self.assertIn("request_user_input", requirement_text)
        self.assertIn("render the identical questions and options in text", requirement_text)
        self.assertIn("Do not change host mode solely to obtain the panel", requirement_text)
        self.assertIn("Confirm and execute (Recommended)", requirement_text)

        self.assertIn("request_user_input", entry_text)
        self.assertIn("If the tool is unavailable", entry_text)
        self.assertIn("Treat UI and text answers identically", entry_text)

        vendor(ROOT, self.repo, False)
        for skill_name, markers in expected_markers.items():
            source_path = ROOT / "skills" / skill_name / "SKILL.md"
            vendored_path = (
                self.repo / ".agents" / "skills" / skill_name / "SKILL.md"
            )
            source_text = source_path.read_text(encoding="utf-8")
            self.assertEqual(vendored_path.read_text(encoding="utf-8"), source_text)
            for marker in markers:
                with self.subTest(skill=skill_name, marker=marker):
                    self.assertIn(marker, source_text)

    def test_worker_dispatch_requires_confirm_and_execute_authorization(self) -> None:
        """自动创建 Implementer/Review 任务前必须由 Work Item 确认显式授权。"""
        requirement_text = (
            ROOT / "skills" / "requirement-analysis" / "SKILL.md"
        ).read_text(encoding="utf-8")
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Confirm and execute (Recommended)", requirement_text)
        self.assertIn(
            "authorizes Polaris to create every required independent Implementation and Review task",
            requirement_text,
        )
        self.assertIn("implementation_dispatch", entry_text)
        self.assertIn("Do not create Reviewer tasks without it", entry_text)

        path = self.task / "revisions" / "work-item-r001.json"
        value = read_json(path)
        value.update(
            {
                "title": "Authorization gate",
                "goal": "Require explicit dispatch authorization",
                "motivation": "Keep authorization in repository authority",
            }
        )
        value["scope"]["in"] = ["skills"]
        value["acceptance"][0].update(
            {"statement": "Authorization is required", "evidence": "gate result"}
        )
        legacy_value = copy.deepcopy(value)
        legacy_value.pop("implementation_dispatch")
        legacy_value.pop("review_dispatch")
        schema = read_json(ROOT / "schemas" / "work-item.schema.json")
        self.assertEqual(validate_schema(legacy_value, schema), [])
        wrong_mode = copy.deepcopy(value)
        wrong_mode["implementation_dispatch"]["mode"] = "manual"
        self.assertTrue(validate_schema(wrong_mode, schema))
        write_json_atomic(path, legacy_value)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "QUALIFY",
                [],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        write_json_atomic(path, value)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "QUALIFY",
                [],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        value["implementation_dispatch"]["authorized"] = True
        value["review_dispatch"]["authorized"] = True
        write_json_atomic(path, value)
        self.assertEqual(
            transition(
                self.repo,
                "TASK-0001",
                "QUALIFY",
                [],
                None,
                None,
                None,
                None,
                None,
                None,
            )["to"],
            "QUALIFIED",
        )

    def test_r0_keeps_isolated_review_in_same_session(self) -> None:
        """R0 继续使用同会话隔离审查，不创建独立 Review 任务。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        review_text = (
            ROOT / "skills" / "adversarial-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("R0 performs an explicit isolated same-session pass", entry_text)
        self.assertIn("R0 may use the same session only as an explicit isolated pass", review_text)

    def test_implementation_dispatch_is_fresh_visible_and_idempotent(self) -> None:
        """Implementation 使用同项目可见新任务、确定性标题，并在恢复时避免重复派发。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Polaris Implement · <TASK> · <REVISION> · attempt <N>", entry_text
        )
        self.assertIn("dispatch a fresh task in that same local checkout", entry_text)
        self.assertIn("Never fork the main conversation", entry_text)
        self.assertIn("do not use a separate worktree by default", entry_text)
        self.assertIn("first reuse a valid Implementation artifact", entry_text)
        self.assertIn("Never create a duplicate", entry_text)
        fixture = read_json(
            ROOT / "tests" / "fixtures" / "implementation-dispatch-host-smoke.json"
        )
        self.assertEqual(fixture["required_isolation"], "fresh_session")
        self.assertEqual(
            fixture["deterministic_title"],
            "Polaris Implement · TASK-9998 · r001 · attempt 1",
        )

    def test_implementer_receives_only_handoff_and_cannot_transition(self) -> None:
        """Implementer 只接收冻结 handoff，产出 artifact 后由主任务执行转换。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        implementation_text = (
            ROOT / "skills" / "implementation" / "SKILL.md"
        ).read_text(encoding="utf-8")
        docs_text = (
            ROOT / "skills" / "documentation-sync" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Give the Implementer only the task ID and registered handoff path", entry_text)
        self.assertIn("Load only <HANDOFF> and its package", entry_text)
        self.assertIn("Do not read the main conversation", implementation_text)
        self.assertIn("Do not run `FINISH_IMPLEMENTATION`", implementation_text)
        self.assertIn("Continue the same Implementer task", entry_text)
        self.assertIn("Do not run `SYNC_DOCS`", docs_text)

    def test_implementation_handoff_and_result_are_mechanically_bound(self) -> None:
        """DISPATCH_IMPLEMENTATION 注册不可变 handoff，未绑定该 handoff 的实现结果不能完成。"""
        self.enter_implementing()
        handoff, reference = self.dispatch_implementation()
        state = read_json(self.task / "state.json")
        self.assertEqual(state["status"], "IMPLEMENTING")
        self.assertEqual(state["artifacts"]["implementation_handoff"], reference)
        self.assertEqual(handoff["artifact_attempt"], 1)
        self.assertEqual(
            handoff["output_path"], "implementations/r001/attempt-001.json"
        )

        base = run_git(self.repo, "rev-parse", "HEAD")
        (self.repo / "subject.txt").write_text("bound subject\n", encoding="utf-8")
        run_git(self.repo, "add", "subject.txt")
        run_git(self.repo, "commit", "-q", "-m", "bound implementation")
        head = run_git(self.repo, "rev-parse", "HEAD")
        path = self.task / handoff["output_path"]
        implementation = self.implementation_value(base, head, "impl-bound-session")
        implementation["implementation_handoff_sha256"] = "0" * 64
        write_json_atomic(path, implementation)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "FINISH_IMPLEMENTATION",
                ["implementation=implementations/r001/attempt-001.json"],
                None,
                base,
                head,
                None,
                None,
                None,
            )
        implementation["implementation_handoff_sha256"] = reference["sha256"]
        write_json_atomic(path, implementation)
        result = transition(
            self.repo,
            "TASK-0001",
            "FINISH_IMPLEMENTATION",
            ["implementation=implementations/r001/attempt-001.json"],
            None,
            base,
            head,
            None,
            None,
            None,
        )
        self.assertEqual(result["to"], "IMPLEMENTED")

    def test_live_implementation_progress_is_queryable_and_ignored(self) -> None:
        """事件驱动进度同时生成四空格 JSON 与 Markdown，并默认排除出 Git。"""
        self.enter_implementing()
        self.dispatch_implementation()
        title = "Polaris Implement · TASK-0001 · r001 · attempt 1"
        update_implementation_progress(
            self.repo,
            "TASK-0001",
            title,
            "Pending",
            "QUEUED",
            "Waiting for the Implementer task to start",
            [],
            ["Modify subject", "Run tests"],
            [],
            None,
            None,
        )
        progress_path = self.repo / ".polaris" / "runtime" / "TASK-0001" / "progress.json"
        projection_path = progress_path.with_name("STATUS.md")
        self.assertIn('    "task_id"', progress_path.read_text(encoding="utf-8"))
        self.assertIn("## Remaining", projection_path.read_text(encoding="utf-8"))
        self.assertEqual(
            run_git(self.repo, "check-ignore", ".polaris/runtime/TASK-0001/progress.json"),
            ".polaris/runtime/TASK-0001/progress.json",
        )
        update_implementation_progress(
            self.repo,
            "TASK-0001",
            title,
            "impl-progress-session",
            "TESTING",
            "Running focused tests",
            ["Modified subject"],
            ["Create checkpoint", "Synchronize docs"],
            ["unit tests: 8/8 PASS"],
            None,
            None,
        )
        progress = validate_progress(self.repo, "TASK-0001")
        self.assertEqual(progress["phase"], "TESTING")
        self.assertEqual(progress["checks"], ["unit tests: 8/8 PASS"])
        recovered = recover(self.repo, "TASK-0001")
        self.assertTrue(recovered["live_implementation_progress"]["available"])
        self.assertEqual(
            recovered["live_implementation_progress"]["value"]["phase"], "TESTING"
        )

    def test_live_progress_rejects_session_takeover_and_invalid_blocker(self) -> None:
        """同一 attempt 的进度禁止其他 session 接管，BLOCKED 必须给出用户动作。"""
        self.enter_implementing()
        self.dispatch_implementation()
        title = "Polaris Implement · TASK-0001 · r001 · attempt 1"
        update_implementation_progress(
            self.repo,
            "TASK-0001",
            title,
            "impl-owner-session",
            "IMPLEMENTING",
            "Editing subject",
            [],
            ["Run tests"],
            [],
            None,
            None,
        )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo,
                "TASK-0001",
                title,
                "impl-other-session",
                "TESTING",
                "Attempting takeover",
                [],
                [],
                [],
                None,
                None,
            )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo,
                "TASK-0001",
                title,
                "impl-owner-session",
                "BLOCKED",
                "Waiting",
                [],
                ["Continue"],
                [],
                None,
                None,
            )
        self.assertEqual(
            validate_progress(self.repo, "TASK-0001")["implementer_session_id"],
            "impl-owner-session",
        )

    def test_implementation_status_contract_and_same_session_fallback(self) -> None:
        """主任务提供可查询 marker；宿主不能派发时回退且明确响应可能延迟。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        for marker in (
            "IMPLEMENTATION_HANDOFF_READY",
            "IMPLEMENTATION_SESSION_STARTED",
            "IMPLEMENTATION_PROGRESS",
        ):
            self.assertIn(marker, entry_text)
        for detail in (
            "`Implementation task`",
            "`Handoff`",
            "`Progress`",
            "`Dispatch mode`",
        ):
            self.assertIn(detail, entry_text)
        self.assertIn("Dispatch mode: same_session_fallback", entry_text)
        self.assertIn("immediate status responses may be delayed", entry_text)

    def test_r1_dispatches_one_visible_fresh_local_task(self) -> None:
        """R1 在同一本地项目中创建可见新任务，禁止 fork 和默认 worktree。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("dispatch a fresh task in that same local checkout", entry_text)
        self.assertIn("Never fork the implementation conversation", entry_text)
        self.assertIn("do not use a separate worktree by default", entry_text)

    def test_reviewer_prompt_is_handoff_only_without_implementation_history(self) -> None:
        """Reviewer 启动提示只含身份与 handoff，不泄漏实现总结或预期 verdict。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        review_text = (
            ROOT / "skills" / "adversarial-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("only the task ID, Reviewer slot, registered handoff path", entry_text)
        self.assertIn(
            "Use $adversarial-review for <TASK>, Reviewer slot <SLOT>",
            entry_text,
        )
        self.assertIn("Do not include implementation explanations", entry_text)
        self.assertIn("another Reviewer's artifact, or an expected verdict", review_text)
        fixture = read_json(
            ROOT / "tests" / "fixtures" / "review-dispatch-host-smoke.json"
        )
        self.assertEqual(fixture["required_isolation"], "fresh_session")
        self.assertEqual(fixture["reviewer_slot"], 1)
        self.assertEqual(
            fixture["output"], ".polaris-host-smoke/review-result.json"
        )

    def test_review_dispatch_is_idempotent_by_artifact_and_title(self) -> None:
        """恢复时优先复用 artifact 或唯一同名任务，禁止重复派发。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Polaris Review · <TASK> · <REVISION> · attempt <N> · reviewer <SLOT>",
            entry_text,
        )
        self.assertIn("first accept a valid deterministic Review artifact", entry_text)
        self.assertIn("Never create a duplicate", entry_text)
        self.assertIn("multiple exact matches", entry_text)

    def test_review_rejection_returns_to_rework_and_redispatches(self) -> None:
        """Reviewer 拒绝后由主流程合法返工，并为下一 attempt 创建新任务。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("run `REJECT_REVIEW`", entry_text)
        self.assertIn("on rework, generate a new handoff", entry_text)
        self.assertIn("up to the graph limit", entry_text)

    def test_high_risk_r2_dispatches_distinct_reviewers_sequentially(self) -> None:
        """高风险 R2 串行派发两个 Reviewer，并要求不同 session ID。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        review_text = (
            ROOT / "skills" / "adversarial-review" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Dispatch required Reviewers sequentially", entry_text)
        self.assertIn("slot 2 as `review_2`", entry_text)
        self.assertIn("Reviewer session IDs must be distinct", entry_text)
        self.assertIn("review-<attempt>-2.json", review_text)

    def test_review_dispatch_falls_back_without_blocking(self) -> None:
        """宿主自动派发不可用时保持 REVIEWING 并回退手动提示。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("keep state `REVIEWING`", entry_text)
        self.assertIn("provide the exact manual new-task prompt", entry_text)
        self.assertIn(
            "do not enter `BLOCKED` solely because host automation is unavailable",
            entry_text,
        )

    def test_review_session_started_uses_stable_status_contract(self) -> None:
        """自动派发状态使用新 marker、固定九字段和四个 Review 详情字段。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("REVIEW_SESSION_STARTED", entry_text)
        for field in (
            "`Task`",
            "`Revision`",
            "`Rigor`",
            "`State`",
            "`Outcome`",
            "`Authority`",
            "`Remaining`",
            "`Next`",
            "`User action`",
        ):
            self.assertIn(field, entry_text)
        for detail in ("`Review task`", "`Reviewer slot`", "`Handoff`", "`Dispatch mode`"):
            self.assertIn(detail, entry_text)
        self.assertIn("set `User action` to `None` while the task is running", entry_text)

    def test_fresh_clone_recovers_the_committed_task_boundary(self) -> None:
        """Fresh Clone 仅凭已提交的 vendored 协议和仓库状态恢复最近阶段边界。"""
        vendor(ROOT, self.repo, False)
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", "Polaris checkpoint")
        with tempfile.TemporaryDirectory(prefix="polaris-clone-") as clone_temp:
            clone = Path(clone_temp) / "repo"
            subprocess.run(
                ["git", "clone", "-q", str(self.repo), str(clone)],
                check=True,
                text=True,
                capture_output=True,
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(clone / "tools" / "polaris" / "scripts" / "recover_task.py"),
                    "TASK-0001",
                    "--repo",
                    str(clone),
                    "--json",
                ],
                check=True,
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            recovered = json.loads(completed.stdout)
        self.assertEqual(recovered["status"], "PASS")
        self.assertEqual(recovered["task"]["work_item_revision"], 1)
        self.assertEqual(recovered["state"]["status"], "DRAFT")
        self.assertIn("AGENTS.md", {
            item["path"] for item in recovered["minimum_working_set"]["entries"]
        })

    def test_new_revision_is_created_then_explicitly_activated(self) -> None:
        """需求变化创建不可覆盖的新 Revision，并经 NEW_REVISION 显式激活。"""
        self.freeze_work_item()
        transition(
            self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
        )
        created = new_revision(self.repo, "TASK-0001")
        self.assertEqual(created["revision"], 2)
        path = self.task / "revisions" / "work-item-r002.json"
        value = read_json(path)
        self.assertFalse(value["implementation_dispatch"]["authorized"])
        self.assertFalse(value["review_dispatch"]["authorized"])
        value["implementation_dispatch"]["authorized"] = True
        value["review_dispatch"]["authorized"] = True
        value["known_unknowns"] = []
        write_json_atomic(path, value)
        activated = transition(
            self.repo,
            "TASK-0001",
            "NEW_REVISION",
            [],
            2,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(activated["to"], "QUALIFIED")
        self.assertEqual(read_json(self.task / "state.json")["current_revision"], 2)

    def test_implementation_and_final_documentation_subjects_are_bound(self) -> None:
        """Implementation 绑定实现 checkpoint，Knowledge Delta 绑定含文档的最终 subject。"""
        self.freeze_work_item()
        build_working_set(self.repo, "TASK-0001", True)
        transition(
            self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
        )
        transition(
            self.repo,
            "TASK-0001",
            "PLAN",
            ["plan=PLAN.md", "working_set=WORKING_SET.md"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        transition(
            self.repo,
            "TASK-0001",
            "START_IMPLEMENTATION",
            [],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.dispatch_implementation()
        base = run_git(self.repo, "rev-parse", "HEAD")
        (self.repo / "subject.txt").write_text("subject\n", encoding="utf-8")
        run_git(self.repo, "add", "subject.txt")
        run_git(self.repo, "commit", "-q", "-m", "subject")
        head = run_git(self.repo, "rev-parse", "HEAD")
        diff_hash = subject_diff_hash(self.repo, base, head)

        implementation_path = self.task / "implementations" / "r001" / "attempt-001.json"
        implementation = self.implementation_value(base, head, "impl-session")
        write_json_atomic(implementation_path, implementation)
        transition(
            self.repo,
            "TASK-0001",
            "FINISH_IMPLEMENTATION",
            ["implementation=implementations/r001/attempt-001.json"],
            None,
            base,
            head,
            None,
            None,
            None,
        )

        docs_path = self.repo / "docs" / "subject.md"
        docs_path.parent.mkdir()
        docs_path.write_text("Subject behavior documentation\n", encoding="utf-8")
        run_git(self.repo, "add", "docs/subject.md")
        run_git(self.repo, "commit", "-q", "-m", "sync subject documentation")
        final_head = run_git(self.repo, "rev-parse", "HEAD")
        knowledge_path = self.task / "knowledge" / "r001" / "knowledge-delta-001.json"
        knowledge = self.knowledge_value(1, base, final_head)
        knowledge["entries"][0].update(
            {
                "status": "UPDATE",
                "path": "docs/subject.md",
                "changed_paths": ["subject.txt", "docs/subject.md"],
                "evidence": "Added subject behavior documentation",
            }
        )
        correct_diff_hash = knowledge["subject_diff_hash"]
        knowledge["subject_diff_hash"] = "0" * 64
        write_json_atomic(knowledge_path, knowledge)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "SYNC_DOCS",
                ["knowledge_delta=knowledge/r001/knowledge-delta-001.json"],
                None,
                base,
                final_head,
                None,
                None,
                None,
            )
        knowledge["subject_diff_hash"] = correct_diff_hash
        write_json_atomic(knowledge_path, knowledge)
        result = check_docs(self.repo, "TASK-0001", knowledge_path, base, final_head)
        self.assertEqual(result["changed_paths"], 2)
        synced = transition(
            self.repo,
            "TASK-0001",
            "SYNC_DOCS",
            ["knowledge_delta=knowledge/r001/knowledge-delta-001.json"],
            None,
            base,
            final_head,
            None,
            None,
            None,
        )
        self.assertEqual(synced["to"], "DOCS_SYNCED")
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "DOCS_SYNCED")

    def test_stale_documentation_is_rejected(self) -> None:
        """Knowledge Delta 存在未处置 STALE 时拒绝文档同步通过。"""
        self.test_implementation_and_final_documentation_subjects_are_bound()
        knowledge_path = self.task / "knowledge" / "r001" / "knowledge-delta-001.json"
        knowledge = read_json(knowledge_path)
        knowledge["entries"][0]["status"] = "STALE"
        write_json_atomic(knowledge_path, knowledge)
        with self.assertRaises(RuleFailure):
            check_docs(self.repo, "TASK-0001", knowledge_path)

    def test_full_r1_flow_closes_only_after_review_and_validation(self) -> None:
        """R1 必须依次通过独立 Review、全部 AC Validation 和 Result 才能 CLOSED。"""
        self.test_implementation_and_final_documentation_subjects_are_bound()
        state = read_json(self.task / "state.json")
        subject = state["subject"]
        with self.assertRaises(RuleFailure):
            transition(
                self.repo, "TASK-0001", "CLOSE", [], None, None, None, None, None, None
            )
        transition(
            self.repo,
            "TASK-0001",
            "START_REVIEW",
            [
                "review_handoff="
                + Path(
                    build_review_handoff(
                        self.repo, "TASK-0001", "impl-session", "fresh_session"
                    )["path"]
                ).relative_to(self.task).as_posix()
            ],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        review_path = self.task / "reviews" / "r001" / "review-001.json"
        review = read_json(ROOT / "templates" / "task" / "review.json")
        handoff_reference = read_json(self.task / "state.json")["artifacts"][
            "review_handoff"
        ]
        review.update(
            {
                "work_item_revision": 2,
                "implementer_session_id": "impl-session",
                "reviewer_session_id": "review-session",
                "handoff_path": handoff_reference["path"],
                "handoff_sha256": handoff_reference["sha256"],
                "subject_base_commit": subject["base_commit"],
                "subject_head_commit": subject["head_commit"],
                "subject_diff_hash": subject["diff_hash"],
                "reviewed_at": "2026-08-12T00:00:00Z",
                "verdict": "ACCEPT",
            }
        )
        write_json_atomic(review_path, review)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "ACCEPT_REVIEW",
                ["review=reviews/r001/review-001.json"],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        review["work_item_revision"] = 1
        review["subject_diff_hash"] = "0" * 64
        write_json_atomic(review_path, review)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "ACCEPT_REVIEW",
                ["review=reviews/r001/review-001.json"],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        review["subject_diff_hash"] = subject["diff_hash"]
        write_json_atomic(review_path, review)
        transition(
            self.repo,
            "TASK-0001",
            "ACCEPT_REVIEW",
            ["review=reviews/r001/review-001.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        transition(
            self.repo,
            "TASK-0001",
            "START_VALIDATION",
            [],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        validation_path = self.task / "validations" / "r001" / "validation-001.json"
        validation = read_json(ROOT / "templates" / "task" / "validation.json")
        validation.update(
            {
                "subject_base_commit": subject["base_commit"],
                "subject_head_commit": subject["head_commit"],
                "subject_diff_hash": subject["diff_hash"],
                "validated_at": "2026-08-12T00:01:00Z",
                "verdict": "PASS",
                "acceptance_results": [],
            }
        )
        write_json_atomic(validation_path, validation)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PASS_VALIDATION",
                ["validation=validations/r001/validation-001.json"],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        validation["acceptance_results"] = [
                    {
                        "acceptance_id": "AC-01",
                        "command_or_check": "state validation",
                        "cwd": ".",
                        "environment_summary": "test",
                        "started_at": "2026-08-12T00:01:00Z",
                        "exit_code": 0,
                        "result": "PASS",
                        "output_path_or_hash": "inline:test",
                    }
                ]
        write_json_atomic(validation_path, validation)
        transition(
            self.repo,
            "TASK-0001",
            "PASS_VALIDATION",
            ["validation=validations/r001/validation-001.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        result_path = self.task / "results" / "r001" / "result-001.json"
        result = read_json(ROOT / "templates" / "task" / "result.json")
        result.update(
            {
                "subject_base_commit": subject["base_commit"],
                "subject_head_commit": subject["head_commit"],
                "subject_diff_hash": subject["diff_hash"],
                "summary": "Validated smoke task",
            }
        )
        write_json_atomic(result_path, result)
        closed = transition(
            self.repo,
            "TASK-0001",
            "CLOSE",
            ["result=results/r001/result-001.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(closed["to"], "CLOSED")
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "CLOSED")

    def test_r1_review_requires_a_bound_independent_session_attestation(self) -> None:
        """R1 Review 即使 session 字段不同，也必须绑定 handoff 且声明未继承实现聊天。"""
        self.test_implementation_and_final_documentation_subjects_are_bound()
        handoff, state = self.start_review()
        review_path = self.task / "reviews" / "r001" / "review-001.json"
        review = self.review_value(
            handoff, state, "impl-session", "ACCEPT"
        )
        write_json_atomic(review_path, review)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "ACCEPT_REVIEW",
                ["review=reviews/r001/review-001.json"],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        review["reviewer_session_id"] = "review-session"
        review["isolation_attestation"]["chat_history_inherited"] = True
        write_json_atomic(review_path, review)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "ACCEPT_REVIEW",
                ["review=reviews/r001/review-001.json"],
                None,
                None,
                None,
                None,
                None,
                None,
            )

    def test_review_handoff_freezes_evidence_directory(self) -> None:
        """Reviewer handoff 对证据目录做内容快照，生成后新增或修改证据会被拒绝。"""
        self.test_implementation_and_final_documentation_subjects_are_bound()
        evidence = self.task / "evidence" / "r001" / "checks.txt"
        evidence.write_text("original evidence\n", encoding="utf-8")
        handoff_path = Path(
            build_review_handoff(
                self.repo, "TASK-0001", "impl-session", "fresh_session"
            )["path"]
        )
        evidence.write_text("mutated evidence\n", encoding="utf-8")
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "START_REVIEW",
                [f"review_handoff={handoff_path.relative_to(self.task).as_posix()}"],
                None,
                None,
                None,
                None,
                None,
                None,
            )

    def test_validation_rework_supersedes_the_accepted_review(self) -> None:
        """Validation 返工保留已接受 Review，下一 handoff 递增 attempt 且无需伪造 Review Response。"""
        self.test_implementation_and_final_documentation_subjects_are_bound()
        handoff_1, state = self.start_review()
        review_path = self.task / "reviews" / "r001" / "review-001.json"
        write_json_atomic(
            review_path,
            self.review_value(handoff_1, state, "review-session-1", "ACCEPT"),
        )
        transition(
            self.repo,
            "TASK-0001",
            "ACCEPT_REVIEW",
            ["review=reviews/r001/review-001.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        transition(
            self.repo,
            "TASK-0001",
            "START_VALIDATION",
            [],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        subject_1 = read_json(self.task / "state.json")["subject"]
        validation_path = self.task / "validations" / "r001" / "validation-001.json"
        validation = read_json(ROOT / "templates" / "task" / "validation.json")
        validation.update(
            {
                "subject_base_commit": subject_1["base_commit"],
                "subject_head_commit": subject_1["head_commit"],
                "subject_diff_hash": subject_1["diff_hash"],
                "validated_at": "2026-08-13T00:10:00Z",
                "verdict": "FAIL",
                "acceptance_results": [
                    {
                        "acceptance_id": "AC-01",
                        "command_or_check": "counterexample",
                        "cwd": ".",
                        "environment_summary": "test",
                        "started_at": "2026-08-13T00:10:00Z",
                        "exit_code": 1,
                        "result": "FAIL",
                        "output_path_or_hash": "inline:failure",
                    }
                ],
            }
        )
        write_json_atomic(validation_path, validation)
        failed = transition(
            self.repo,
            "TASK-0001",
            "FAIL_IMPLEMENTATION",
            ["validation=validations/r001/validation-001.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(failed["to"], "IMPLEMENTING")
        state = read_json(self.task / "state.json")
        self.assertEqual(state["artifacts"]["prior_review"]["path"], "reviews/r001/review-001.json")

        base = subject_1["base_commit"]
        (self.repo / "subject.txt").write_text("validation fix\n", encoding="utf-8")
        run_git(self.repo, "add", "subject.txt")
        run_git(self.repo, "commit", "-q", "-m", "fix validation failure")
        head = run_git(self.repo, "rev-parse", "HEAD")
        diff_hash = subject_diff_hash(self.repo, base, head)
        implementation_path = self.task / "implementations" / "r001" / "attempt-002.json"
        implementation = self.implementation_value(base, head, "impl-session-2")
        write_json_atomic(implementation_path, implementation)
        transition(
            self.repo,
            "TASK-0001",
            "FINISH_IMPLEMENTATION",
            ["implementation=implementations/r001/attempt-002.json"],
            None,
            base,
            head,
            None,
            None,
            None,
        )
        knowledge_path = self.task / "knowledge" / "r001" / "knowledge-delta-002.json"
        knowledge = self.knowledge_value(2, base, head)
        knowledge["entries"][0].update(
            {
                "changed_paths": ["docs/subject.md", "subject.txt"],
                "evidence": "The final subject retains the synchronized documentation",
            }
        )
        write_json_atomic(knowledge_path, knowledge)
        transition(
            self.repo,
            "TASK-0001",
            "SYNC_DOCS",
            ["knowledge_delta=knowledge/r001/knowledge-delta-002.json"],
            None,
            base,
            head,
            None,
            None,
            None,
        )
        handoff_2, state = self.start_review("impl-session-2")
        self.assertEqual(handoff_2["artifact_attempt"], 2)
        self.assertEqual(
            handoff_2["previous_review"]["path"], "reviews/r001/review-001.json"
        )
        self.assertNotIn("review_response", state["artifacts"])

    def test_rejected_finding_requires_response_and_stable_follow_up(self) -> None:
        """Review 返工必须逐项回复，后续 Reviewer 保留稳定 Finding ID 并重新裁定。"""
        self.test_implementation_and_final_documentation_subjects_are_bound()
        handoff_1, state = self.start_review()
        finding = {
            "id": "F-001",
            "introduced_in_attempt": 1,
            "category": "specification",
            "acceptance_id": "AC-01",
            "scope_violation": False,
            "blocking": True,
            "severity": "high",
            "location": "subject.txt:1",
            "claim": "The subject does not satisfy AC-01",
            "evidence": "Counterexample from the frozen patch",
            "required_action": "Correct subject.txt and provide evidence",
            "status": "open",
            "reviewer_resolution": None,
        }
        review_1_path = self.task / "reviews" / "r001" / "review-001.json"
        write_json_atomic(
            review_1_path,
            self.review_value(
                handoff_1, state, "review-session-1", "REJECT", [finding]
            ),
        )
        rejected = transition(
            self.repo,
            "TASK-0001",
            "REJECT_REVIEW",
            ["review=reviews/r001/review-001.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(rejected["to"], "IMPLEMENTING")

        base = handoff_1["subject_base_commit"]
        (self.repo / "subject.txt").write_text("subject fixed\n", encoding="utf-8")
        run_git(self.repo, "add", "subject.txt")
        run_git(self.repo, "commit", "-q", "-m", "fix review finding")
        head = run_git(self.repo, "rev-parse", "HEAD")
        diff_hash = subject_diff_hash(self.repo, base, head)
        implementation_path = self.task / "implementations" / "r001" / "attempt-002.json"
        implementation = self.implementation_value(base, head, "impl-session-2")
        write_json_atomic(implementation_path, implementation)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "FINISH_IMPLEMENTATION",
                ["implementation=implementations/r001/attempt-002.json"],
                None,
                base,
                head,
                None,
                None,
                None,
            )

        prior_reference = read_json(self.task / "state.json")["artifacts"]["prior_review"]
        response_path = self.task / "reviews" / "r001" / "response-002.json"
        response = read_json(ROOT / "templates" / "task" / "review-response.json")
        response.update(
            {
                "implementer_session_id": "impl-session-2",
                "prior_review_path": prior_reference["path"],
                "prior_review_sha256": prior_reference["sha256"],
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": diff_hash,
                "responded_at": "2026-08-13T00:01:00Z",
                "responses": [
                    {
                        "finding_id": "F-001",
                        "response": "Corrected the acceptance behavior",
                        "evidence": "subject.txt at the new subject head",
                    }
                ],
            }
        )
        write_json_atomic(response_path, response)
        transition(
            self.repo,
            "TASK-0001",
            "FINISH_IMPLEMENTATION",
            [
                "implementation=implementations/r001/attempt-002.json",
                "review_response=reviews/r001/response-002.json",
            ],
            None,
            base,
            head,
            None,
            None,
            None,
        )
        knowledge_path = self.task / "knowledge" / "r001" / "knowledge-delta-002.json"
        knowledge = self.knowledge_value(2, base, head)
        knowledge["entries"][0].update(
            {
                "changed_paths": ["docs/subject.md", "subject.txt"],
                "evidence": "The final subject retains the synchronized documentation",
            }
        )
        write_json_atomic(knowledge_path, knowledge)
        transition(
            self.repo,
            "TASK-0001",
            "SYNC_DOCS",
            ["knowledge_delta=knowledge/r001/knowledge-delta-002.json"],
            None,
            base,
            head,
            None,
            None,
            None,
        )
        handoff_2, state = self.start_review("impl-session-2")
        review_2_path = self.task / "reviews" / "r001" / "review-002.json"
        write_json_atomic(
            review_2_path,
            self.review_value(handoff_2, state, "review-session-2", "ACCEPT"),
        )
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "ACCEPT_REVIEW",
                ["review=reviews/r001/review-002.json"],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        resolved = copy.deepcopy(finding)
        resolved.update(
            {
                "location": "subject.txt:1",
                "evidence": "Rechecked the complete new patch",
                "status": "resolved",
                "reviewer_resolution": "The new subject satisfies AC-01",
            }
        )
        write_json_atomic(
            review_2_path,
            self.review_value(
                handoff_2, state, "review-session-2", "ACCEPT", [resolved]
            ),
        )
        accepted = transition(
            self.repo,
            "TASK-0001",
            "ACCEPT_REVIEW",
            ["review=reviews/r001/review-002.json"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(accepted["to"], "REVIEWED")
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "REVIEWED")

    def test_third_rejected_review_enters_human_blocked_state(self) -> None:
        """第三次 Review 仍 REJECT 时不再自动返工，而是进入 Human-owned BLOCKED。"""
        self.freeze_work_item()
        build_working_set(self.repo, "TASK-0001", True)
        transition(self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None)
        transition(
            self.repo,
            "TASK-0001",
            "PLAN",
            ["plan=PLAN.md", "working_set=WORKING_SET.md"],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        transition(
            self.repo, "TASK-0001", "START_IMPLEMENTATION", [], None, None, None, None, None, None
        )
        base = run_git(self.repo, "rev-parse", "HEAD")
        finding = {
            "id": "F-001",
            "introduced_in_attempt": 1,
            "category": "engineering",
            "acceptance_id": None,
            "scope_violation": False,
            "blocking": True,
            "severity": "high",
            "location": "subject.txt:1",
            "claim": "A blocking defect remains",
            "evidence": "The patch fails the counterexample",
            "required_action": "Escalate the disputed boundary",
            "status": "open",
            "reviewer_resolution": None,
        }
        self.assertEqual(
            self.finish_and_reject_attempt(
                1, base, "impl-session-1", "review-session-1", finding
            )["to"],
            "IMPLEMENTING",
        )
        self.assertEqual(
            self.finish_and_reject_attempt(
                2, base, "impl-session-2", "review-session-2", finding
            )["to"],
            "IMPLEMENTING",
        )
        result = self.finish_and_reject_attempt(
            3, base, "impl-session-3", "review-session-3", finding
        )
        self.assertEqual(result["to"], "BLOCKED")
        state = read_json(self.task / "state.json")
        self.assertEqual(state["blocker"]["type"], "review_dispute")

    def test_recovery_working_set_and_exploration_promotion(self) -> None:
        """Fresh-session Recovery 只输出四类最小信息，并检索匹配模块的失败探索。"""
        work_item_path = self.task / "revisions" / "work-item-r001.json"
        work_item = read_json(work_item_path)
        work_item["affected_modules"] = ["scripts"]
        write_json_atomic(work_item_path, work_item)
        recorded = record_exploration(
            self.repo,
            "TASK-0001",
            "scripts",
            "A direct state edit might be safe",
            "Edited a disposable projection",
            "validate_task rejected the projection",
            "rejected",
            "events.jsonl remained authoritative",
            "Retry only if the state protocol changes",
            [],
        )
        promoted = promote_exploration(
            self.repo, "TASK-0001", recorded["exploration_id"]
        )
        self.assertTrue(Path(promoted["path"]).is_file())
        with self.assertRaises(InputFailure):
            promote_exploration(self.repo, "TASK-0001", recorded["exploration_id"])
        build_working_set(
            self.repo,
            "TASK-0001",
            True,
            [
                "Code|scripts/recover_task.py|recovery entry point|M3 implementation"
            ],
            [],
        )
        recovered = recover(self.repo, "TASK-0001")
        self.assertEqual(recovered["task"]["work_item_revision"], 1)
        self.assertEqual(recovered["state"]["status"], "DRAFT")
        self.assertIn("Work Item", recovered["recommended_next_action"])
        paths = {
            item["path"] for item in recovered["minimum_working_set"]["entries"]
        }
        self.assertIn("scripts/recover_task.py", paths)
        self.assertIn("AGENTS.md", paths)
        self.assertIn(".polaris/project-index.md", paths)
        self.assertIn(
            f".polaris/explorations/{recorded['exploration_id']}.json", paths
        )


if __name__ == "__main__":
    unittest.main()
