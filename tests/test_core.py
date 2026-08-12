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
from check_docs import check as check_docs  # noqa: E402
from new_revision import create as new_revision  # noqa: E402
from polaris_core import (  # noqa: E402
    InputFailure,
    RuleFailure,
    append_jsonl,
    read_json,
    rebuild_state_value,
    subject_diff_hash,
    validate_schema,
    write_json_atomic,
)
from rebuild_state import rebuild  # noqa: E402
from transition_task import transition  # noqa: E402
from validate_task import validate  # noqa: E402
from validate_project import validate as validate_project  # noqa: E402
from vendor_project import vendor  # noqa: E402


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
            [],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        review_path = self.task / "reviews" / "r001" / "review-001.json"
        review = read_json(ROOT / "templates" / "task" / "review.json")
        review.update(
            {
                "work_item_revision": 2,
                "implementer_session_id": "impl-session",
                "reviewer_session_id": "review-session",
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


if __name__ == "__main__":
    unittest.main()
