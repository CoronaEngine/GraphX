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
        write_json_atomic(path, value)

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
        implementation = read_json(ROOT / "templates" / "task" / "implementation.json")
        implementation.update(
            {
                "artifact_attempt": attempt,
                "implementer_session_id": implementer_session_id,
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": diff_hash,
            }
        )
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
        knowledge = read_json(ROOT / "templates" / "task" / "knowledge-delta.json")
        knowledge["artifact_attempt"] = attempt
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
            "implementation": ["IMPLEMENTATION_FINISHED"],
            "documentation-sync": ["DOCS_SYNCED"],
            "adversarial-review": ["REVIEW_ACCEPTED", "REVIEW_REJECTED"],
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

    def test_implementation_and_documentation_subject_are_bound(self) -> None:
        """Implementation 与 Knowledge Delta 必须绑定同一 Git subject 和 changed paths。"""
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
        base = run_git(self.repo, "rev-parse", "HEAD")
        (self.repo / "subject.txt").write_text("subject\n", encoding="utf-8")
        run_git(self.repo, "add", "subject.txt")
        run_git(self.repo, "commit", "-q", "-m", "subject")
        head = run_git(self.repo, "rev-parse", "HEAD")
        diff_hash = subject_diff_hash(self.repo, base, head)

        implementation_path = self.task / "implementations" / "r001" / "attempt-001.json"
        implementation = read_json(ROOT / "templates" / "task" / "implementation.json")
        implementation.update(
            {
                "implementer_session_id": "impl-session",
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": diff_hash,
            }
        )
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

        knowledge_path = self.task / "knowledge" / "r001" / "knowledge-delta-001.json"
        knowledge = read_json(ROOT / "templates" / "task" / "knowledge-delta.json")
        knowledge["entries"][0].update(
            {"changed_paths": ["subject.txt"], "evidence": "No project docs describe subject.txt"}
        )
        write_json_atomic(knowledge_path, knowledge)
        result = check_docs(self.repo, "TASK-0001", knowledge_path)
        self.assertEqual(result["changed_paths"], 1)
        synced = transition(
            self.repo,
            "TASK-0001",
            "SYNC_DOCS",
            ["knowledge_delta=knowledge/r001/knowledge-delta-001.json"],
            None,
            base,
            head,
            None,
            None,
            None,
        )
        self.assertEqual(synced["to"], "DOCS_SYNCED")
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "DOCS_SYNCED")

    def test_stale_documentation_is_rejected(self) -> None:
        """Knowledge Delta 存在未处置 STALE 时拒绝文档同步通过。"""
        self.test_implementation_and_documentation_subject_are_bound()
        knowledge_path = self.task / "knowledge" / "r001" / "knowledge-delta-001.json"
        knowledge = read_json(knowledge_path)
        knowledge["entries"][0]["status"] = "STALE"
        write_json_atomic(knowledge_path, knowledge)
        with self.assertRaises(RuleFailure):
            check_docs(self.repo, "TASK-0001", knowledge_path)

    def test_full_r1_flow_closes_only_after_review_and_validation(self) -> None:
        """R1 必须依次通过独立 Review、全部 AC Validation 和 Result 才能 CLOSED。"""
        self.test_implementation_and_documentation_subject_are_bound()
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
        self.test_implementation_and_documentation_subject_are_bound()
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
        self.test_implementation_and_documentation_subject_are_bound()
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
        self.test_implementation_and_documentation_subject_are_bound()
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
        implementation = read_json(ROOT / "templates" / "task" / "implementation.json")
        implementation.update(
            {
                "artifact_attempt": 2,
                "implementer_session_id": "impl-session-2",
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": diff_hash,
            }
        )
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
        knowledge = read_json(ROOT / "templates" / "task" / "knowledge-delta.json")
        knowledge["artifact_attempt"] = 2
        knowledge["entries"][0].update(
            {"changed_paths": ["subject.txt"], "evidence": "No documentation impact"}
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
        self.test_implementation_and_documentation_subject_are_bound()
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
        implementation = read_json(ROOT / "templates" / "task" / "implementation.json")
        implementation.update(
            {
                "artifact_attempt": 2,
                "implementer_session_id": "impl-session-2",
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": diff_hash,
            }
        )
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
        knowledge = read_json(ROOT / "templates" / "task" / "knowledge-delta.json")
        knowledge["artifact_attempt"] = 2
        knowledge["entries"][0].update(
            {
                "changed_paths": ["subject.txt"],
                "evidence": "No project documentation describes subject.txt",
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
