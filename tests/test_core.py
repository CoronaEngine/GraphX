from __future__ import annotations

import copy
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS))

from init_project import initialize as init_project  # noqa: E402
from init_task import initialize as init_task  # noqa: E402
from internal.artifact_protocol import normalized_reference  # noqa: E402
from internal.doctor_protocol import diagnose_project  # noqa: E402
from internal.code_intelligence_protocol import (  # noqa: E402
    add_provider,
    load_config,
    plan_refresh,
    record as record_code_intelligence,
    select_provider,
    validate_record_value,
    validate_static_configuration,
)
from internal.host_adapters import (  # noqa: E402
    discover_skills,
    load_host_adapters,
    render_skill,
)
from internal.install_manifest import (  # noqa: E402
    BYTE_HASH_MODE,
    TEXT_HASH_MODE,
    managed_file_sha256,
)
from build_working_set import build as build_working_set  # noqa: E402
from build_implementation_handoff import build as build_implementation_handoff  # noqa: E402
from build_review_handoff import build as build_review_handoff  # noqa: E402
from check_docs import check as check_docs  # noqa: E402
from configure_code_intelligence import add as configure_code_intelligence  # noqa: E402
from new_revision import create as new_revision  # noqa: E402
from internal.polaris_core import (  # noqa: E402
    InputFailure,
    RuleFailure,
    append_jsonl,
    acquire_migration_lock,
    file_sha256,
    protocol_root,
    read_json,
    read_jsonl,
    rebuild_state_value,
    release_lock,
    require_protocol_compatible,
    subject_diff_hash,
    validate_schema,
    write_json_atomic,
    write_text_atomic,
)
from migrate_project import migrate as migrate_project  # noqa: E402
from rebuild_state import rebuild  # noqa: E402
from recover_task import recover  # noqa: E402
from record_exploration import promote as promote_exploration  # noqa: E402
from record_exploration import record as record_exploration  # noqa: E402
from record_plan_decision import record as record_plan_decision  # noqa: E402
from transition_task import transition  # noqa: E402
from internal.transition_effects import apply_event_effects  # noqa: E402
from update_implementation_progress import update as update_implementation_progress  # noqa: E402
from internal.implementation_protocol import (  # noqa: E402
    step_results,
    validate_handoff as validate_implementation_handoff,
    validate_progress,
)
from internal.task_location_protocol import load_task_locations  # noqa: E402
from materialize_task_layout import (  # noqa: E402
    materialize_template_tree,
    validate_materialized_template_tree,
)
from internal.task_layout import (  # noqa: E402
    ARCHIVED_RUNTIME_IGNORE_PATTERN,
    TEMPLATE_SAMPLE_PATHS,
    TEMPLATE_SOURCE_PATHS,
    task_repo_relative_path,
    task_relative_path,
    template_path,
    template_source_path,
)
from validate_task import validate  # noqa: E402
from validate_project import validate as validate_project  # noqa: E402
import doctor_project as doctor_module  # noqa: E402
import polaris_cli  # noqa: E402
import vendor_project as vendor_module  # noqa: E402
from vendor_project import vendor  # noqa: E402


SKILLS = discover_skills(ROOT)


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


def host_adapter(host_id: str) -> dict[str, object]:
    return next(
        adapter
        for adapter in load_host_adapters(ROOT)
        if adapter["host_id"] == host_id
    )


def repository_file_snapshot(repo: Path) -> dict[str, bytes]:
    """Capture project files while excluding Git's internal implementation state."""
    return {
        path.relative_to(repo).as_posix(): path.read_bytes()
        for path in sorted(repo.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }


@contextmanager
def simulated_symlinks(*paths: Path) -> Iterator[None]:
    """Report selected paths as symlinks without requiring filesystem support."""
    original_is_symlink = Path.is_symlink
    selected = {path.absolute() for path in paths}

    def is_symlink(path: Path) -> bool:
        return path.absolute() in selected or original_is_symlink(path)

    with mock.patch.object(
        Path, "is_symlink", autospec=True, side_effect=is_symlink
    ):
        yield


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

    def test_init_project_defaults_to_repository_directory_name(self) -> None:
        """init-project 无参数时使用目标仓库目录名，同时保留显式项目标识。"""
        repo = self.repo / "default-project-id"
        repo.mkdir()
        init_project(repo)
        project = read_json(repo / ".polaris" / "project.json")
        index = read_json(repo / ".polaris" / "project-index.json")
        self.assertEqual(project["project_id"], "default-project-id")
        self.assertEqual(index["project_id"], "default-project-id")

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

    def set_protocol_version(self, version: str) -> None:
        """Rewrite the minimal test fixture as an older internally consistent project."""
        project_path = self.repo / ".polaris" / "project.json"
        project = read_json(project_path)
        project["polaris_version"] = version
        write_json_atomic(project_path, project)
        state_path = self.task / "state.json"
        state = read_json(state_path)
        state["polaris_version"] = version
        write_json_atomic(state_path, state)
        event_path = self.task / "events.jsonl"
        events = read_jsonl(event_path)
        for event in events:
            event["polaris_version"] = version
        write_text_atomic(
            event_path,
            "".join(
                json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
                for event in events
            ),
        )

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
            [
                "plan=PLAN.md",
                "plan_decisions=plan-decisions.json",
                "working_set=working-set.json",
            ],
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
        title = (
            f"Polaris Implement · TASK-0001 · r001 · attempt "
            f"{handoff['artifact_attempt']}"
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "Pending", "INITIALIZE"
        )
        progress = validate_progress(self.repo, "TASK-0001")
        if progress["phase"] == "QUEUED":
            update_implementation_progress(
                self.repo,
                "TASK-0001",
                title,
                session_id,
                "DEFINE_STEPS",
                defined_steps=[
                    {"title": "Implement accepted change", "acceptance_ids": ["AC-01"]}
                ],
            )
            update_implementation_progress(
                self.repo, "TASK-0001", title, session_id, "START_STEP",
                step_id="STEP-001",
            )
            update_implementation_progress(
                self.repo, "TASK-0001", title, session_id, "COMPLETE_STEP",
                step_id="STEP-001", result="Implemented and checked the accepted change",
            )
            update_implementation_progress(
                self.repo, "TASK-0001", title, session_id, "SET_PHASE",
                phase="CHECKPOINTING",
            )
        progress = validate_progress(self.repo, "TASK-0001")
        value = read_json(template_path(ROOT, "implementation"))
        value.update(
            {
                "artifact_attempt": handoff["artifact_attempt"],
                "implementer_session_id": session_id,
                "implementation_handoff_path": reference["path"],
                "implementation_handoff_sha256": reference["sha256"],
                "subject_base_commit": base,
                "subject_head_commit": head,
                "subject_diff_hash": subject_diff_hash(self.repo, base, head),
                "step_results": step_results(progress),
            }
        )
        return value

    def knowledge_value(
        self, attempt: int, base: str, head: str
    ) -> dict[str, object]:
        value = read_json(template_path(ROOT, "knowledge_delta"))
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
        review = read_json(template_path(ROOT, "review"))
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
            response = read_json(template_path(ROOT, "review_response"))
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

    def test_scripts_root_contains_only_runnable_command_entries(self) -> None:
        """scripts 根目录只放可运行命令，internal 只放不可独立运行的实现模块。"""
        self.assertEqual(protocol_root(ROOT), ROOT)
        command_files = sorted((ROOT / "scripts").glob("*.py"))
        self.assertTrue(command_files)
        for path in command_files:
            source = path.read_text(encoding="utf-8")
            self.assertIn("def main(", source, path.name)
            self.assertIn('if __name__ == "__main__":', source, path.name)

        internal_files = sorted((ROOT / "scripts" / "internal").glob("*.py"))
        self.assertGreater(len(internal_files), 1)
        for path in internal_files:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn('if __name__ == "__main__":', source, path.name)

    def test_cli_exposes_only_user_commands_and_forwards_to_locked_scripts(self) -> None:
        """统一 CLI 只暴露用户命令，并透传参数、仓库根和退出码。"""
        self.assertEqual(
            {command: spec[0] for command, spec in polaris_cli.COMMANDS.items()},
            {
                "vendor": "vendor_project.py",
                "init-project": "init_project.py",
                "init-task": "init_task.py",
                "doctor": "doctor_project.py",
                "validate-project": "validate_project.py",
                "validate-task": "validate_task.py",
                "recover": "recover_task.py",
                "migrate": "migrate_project.py",
                "code-intelligence": "configure_code_intelligence.py",
            },
        )
        completed = subprocess.CompletedProcess([], 7)
        with mock.patch.object(
            polaris_cli.subprocess, "run", return_value=completed
        ) as invoked:
            result = polaris_cli.dispatch("doctor", ["--json"], ROOT / "tests")
        self.assertEqual(result, 7)
        invoked.assert_called_once_with(
            [
                sys.executable,
                str(ROOT / "scripts" / "doctor_project.py"),
                "--json",
                "--repo",
                str(ROOT),
            ]
        )

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(polaris_cli.main(["--help"]), 0)
        for command in polaris_cli.COMMANDS:
            self.assertIn(command, output.getvalue())
        self.assertNotIn("transition-task", output.getvalue())

    def test_cli_runs_vendored_protocol_from_nested_and_explicit_repositories(self) -> None:
        """CLI 从子目录或 --repo 定位 vendored 协议，并保持原脚本 JSON 语义。"""
        vendor(ROOT, self.repo, False)
        nested = self.repo / "src" / "nested path"
        nested.mkdir(parents=True)
        command = [
            sys.executable,
            str(ROOT / "polaris_cli.py"),
            "validate-project",
            "--json",
        ]
        nested_result = subprocess.run(
            command, cwd=nested, text=True, encoding="utf-8", capture_output=True
        )
        self.assertEqual(nested_result.returncode, 0, nested_result.stderr)
        self.assertEqual(json.loads(nested_result.stdout)["status"], "PASS")

        explicit_result = subprocess.run(
            [*command, "--repo", str(self.repo)],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(explicit_result.returncode, 0, explicit_result.stderr)
        self.assertEqual(json.loads(explicit_result.stdout)["status"], "PASS")

        configure_result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "polaris_cli.py"),
                "code-intelligence",
                "add",
                "codegraph",
                "--json",
            ],
            cwd=nested,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        self.assertEqual(configure_result.returncode, 0, configure_result.stderr)
        configured = json.loads(configure_result.stdout)
        self.assertEqual(configured["status"], "PASS")
        self.assertEqual(configured["provider"], "codegraph")
        self.assertEqual(configured["runtime_status"], "checked_by_next_workflow")

        errors = io.StringIO()
        with tempfile.TemporaryDirectory(prefix="polaris-no-protocol-") as empty:
            with redirect_stderr(errors):
                self.assertEqual(
                    polaris_cli.main(["doctor", "--repo", empty]), 2
                )
        self.assertIn("cannot locate tools/polaris", errors.getvalue())

    def test_cli_packaging_declares_no_runtime_dependencies(self) -> None:
        """pip console script 使用独立分发名，且不声明运行时第三方依赖。"""
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('name = "corona-polaris"', metadata)
        self.assertIn('version = "' + (ROOT / "VERSION").read_text().strip() + '"', metadata)
        self.assertIn('dependencies = []', metadata)
        self.assertIn('polaris = "polaris_cli:main"', metadata)

    def test_artifact_protocol_rejects_escape_and_registered_hash_drift(self) -> None:
        """共享 artifact 引用层拒绝越界路径和注册后的内容漂移。"""
        with self.assertRaises(RuleFailure):
            normalized_reference(self.task, "../../outside.json")

        plan_path = self.task / "PLAN.md"
        reference = normalized_reference(self.task, "PLAN.md")
        plan_path.write_text("changed after registration\n", encoding="utf-8")
        with self.assertRaises(RuleFailure):
            normalized_reference(self.task, reference)

    def test_transition_effects_clear_only_the_expected_rework_artifacts(self) -> None:
        """回退效果独立计算，并为 Implementation/Plan 回退保留正确 artifact。"""
        state = {"status": "VALIDATING"}
        artifacts = {
            "plan": {"path": "PLAN.md", "sha256": "plan"},
            "working_set": {"path": "working-set.json", "sha256": "working"},
            "implementation": {"path": "implementation.json", "sha256": "impl"},
            "knowledge_delta": {"path": "knowledge.json", "sha256": "knowledge"},
            "validation": {"path": "validation.json", "sha256": "validation"},
        }

        implementation_rework = {
            "artifacts": copy.deepcopy(artifacts),
            "subject": {"diff_hash": "subject"},
        }
        destination = apply_event_effects(
            ROOT,
            self.task,
            state,
            implementation_rework,
            "FAIL_IMPLEMENTATION",
            "IMPLEMENTING",
            {},
        )
        self.assertEqual(destination, "IMPLEMENTING")
        self.assertEqual(
            set(implementation_rework["artifacts"]), {"plan", "working_set"}
        )
        self.assertIsNone(implementation_rework["subject"])

        plan_rework = {
            "artifacts": copy.deepcopy(artifacts),
            "subject": {"diff_hash": "subject"},
        }
        destination = apply_event_effects(
            ROOT,
            self.task,
            state,
            plan_rework,
            "FAIL_PLAN",
            "PLANNED",
            {},
        )
        self.assertEqual(destination, "PLANNED")
        self.assertEqual(set(plan_rework["artifacts"]), {"plan", "working_set"})
        self.assertIsNone(plan_rework["subject"])

    def test_task_layout_is_single_source_and_templates_mirror_it(self) -> None:
        """模板树和真实任务树都从 task_layout 与平铺内容源机械生成。"""
        validate_materialized_template_tree(ROOT)
        template_root = ROOT / "templates" / "task"
        actual = {
            path.relative_to(template_root).as_posix()
            for path in template_root.rglob("*")
            if path.is_file()
        }
        expected = {path.as_posix() for path in TEMPLATE_SAMPLE_PATHS.values()}
        self.assertEqual(actual, expected)
        self.assertEqual(set(TEMPLATE_SAMPLE_PATHS), set(TEMPLATE_SOURCE_PATHS))
        for artifact in TEMPLATE_SAMPLE_PATHS:
            self.assertEqual(
                template_path(ROOT, artifact).read_bytes(),
                template_source_path(ROOT, artifact).read_bytes(),
            )

        fixture_root = self.repo / "layout-fixture"
        shutil.copytree(
            ROOT / "templates" / "task-sources",
            fixture_root / "templates" / "task-sources",
        )
        materialize_template_tree(fixture_root)
        validate_materialized_template_tree(fixture_root)
        fixture_files = {
            path.relative_to(fixture_root / "templates" / "task").as_posix()
            for path in (fixture_root / "templates" / "task").rglob("*")
            if path.is_file()
        }
        self.assertEqual(fixture_files, expected)

        for relative in (
            "runtime",
            "revisions",
            "implementations/r001",
            "knowledge/r001",
            "reviews/r001",
            "validations/r001",
            "results/r001",
            "evidence/r001",
            "explorations",
        ):
            self.assertTrue((self.task / relative).is_dir(), relative)
        self.assertEqual(
            task_relative_path("implementation", revision=12, attempt=3).as_posix(),
            "implementations/r012/attempt-003.json",
        )
        self.assertEqual(
            task_relative_path("review", revision=12, attempt=3, reviewer=2).as_posix(),
            "reviews/r012/review-003-2.json",
        )
        self.assertEqual(
            task_repo_relative_path("TASK-0042", "progress").as_posix(),
            ".polaris/tasks/TASK-0042/runtime/progress.json",
        )
        forbidden = (
            'directory / "state.json"',
            'directory / "events.jsonl"',
            'directory / "working-set.json"',
            'directory / "PLAN.md"',
            'directory / "runtime"',
            'directory / "revisions"',
            'directory / "implementations"',
            'directory / "knowledge"',
            'directory / "reviews"',
            'directory / "validations"',
            'directory / "results"',
            'directory / "evidence"',
        )
        for script in (ROOT / "scripts").glob("*.py"):
            if script.name == "task_layout.py":
                continue
            source = script.read_text(encoding="utf-8")
            for fragment in forbidden:
                self.assertNotIn(fragment, source, f"task path escaped task_layout.py: {script}")
        state_text = (self.task / "state.json").read_text(encoding="utf-8")
        self.assertIn('\n    "task_id":', state_text)

    def test_task_location_registry_is_validated_without_real_symlinks(self) -> None:
        """任务位置登记拒绝重复位置和 symlink，安全测试不依赖平台创建能力。"""
        registry_path = self.repo / ".polaris" / "task-locations.json"
        locations = load_task_locations(self.repo)
        self.assertEqual(locations, {"TASK-0001": self.task.absolute()})

        duplicate = read_json(registry_path)
        duplicate["locations"].append(copy.deepcopy(duplicate["locations"][0]))
        write_json_atomic(registry_path, duplicate)
        with self.assertRaises(RuleFailure):
            load_task_locations(self.repo)

        duplicate["locations"].pop()
        write_json_atomic(registry_path, duplicate)
        with simulated_symlinks(registry_path):
            with self.assertRaises(RuleFailure):
                load_task_locations(self.repo)
        with self.assertRaises(InputFailure):
            init_task(self.repo, "../TASK-0002", "R1")
        registry_path.unlink()
        with self.assertRaises(InputFailure):
            validate(self.repo, "TASK-0001")

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

    def test_schema_validator_enforces_every_declared_constraint_keyword(self) -> None:
        """轻量 Schema 校验器执行仓库实际使用的长度、数量和唯一性规则。"""
        self.assertTrue(validate_schema("", {"type": "string", "minLength": 1}))
        self.assertEqual(
            validate_schema("极", {"type": "string", "minLength": 1}), []
        )
        self.assertTrue(validate_schema([], {"type": "array", "minItems": 1}))
        self.assertTrue(
            validate_schema(
                ["AC-01", "AC-01"],
                {"type": "array", "uniqueItems": True},
            )
        )
        self.assertTrue(
            validate_schema(
                [{"value": [1, True]}, {"value": [1.0, True]}],
                {"type": "array", "uniqueItems": True},
            )
        )
        self.assertEqual(
            validate_schema(
                [True, 1], {"type": "array", "uniqueItems": True}
            ),
            [],
        )
        self.assertTrue(validate_schema(True, {"const": 1}))
        self.assertEqual(validate_schema(1.0, {"const": 1}), [])
        self.assertTrue(validate_schema(True, {"enum": [1, "true"]}))
        self.assertTrue(validate_schema(0.5, {"type": "number", "minimum": 1}))
        with self.assertRaises(InputFailure):
            validate_schema("value", {"type": "string", "maxLength": 1})

        implementation_schema = read_json(
            ROOT / "schemas" / "implementation.schema.json"
        )
        implementation = read_json(template_path(ROOT, "implementation"))
        implementation["step_results"] = []
        self.assertTrue(validate_schema(implementation, implementation_schema))
        implementation = read_json(template_path(ROOT, "implementation"))
        implementation["step_results"][0]["result"] = ""
        self.assertTrue(validate_schema(implementation, implementation_schema))

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
            [
                "plan=PLAN.md",
                "plan_decisions=plan-decisions.json",
                "working_set=working-set.json",
            ],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(planned["to"], "PLANNED")
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "PLANNED")

    def test_plan_gate_requires_a_bound_decision_register(self) -> None:
        """PLAN 必须显式提交与当前 PLAN.md 哈希绑定的决策登记。"""
        self.freeze_work_item()
        transition(
            self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
        )
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                ["plan=PLAN.md", "working_set=working-set.json"],
                None,
                None,
                None,
                None,
                None,
                None,
            )

        plan_path = self.task / "PLAN.md"
        plan_path.write_text("# Plan\n\nChanged after initialization.\n", encoding="utf-8")
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                [
                    "plan=PLAN.md",
                    "plan_decisions=plan-decisions.json",
                    "working_set=working-set.json",
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )

    def test_pending_plan_decision_blocks_until_human_authority_is_bound(self) -> None:
        """Human 选择写入 CD 后才能解除阻塞并进入 PLANNED。"""
        self.freeze_work_item()
        transition(
            self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
        )
        plan_path = self.task / "PLAN.md"
        register_path = self.task / "plan-decisions.json"
        register = {
            "register_version": 1,
            "task_id": "TASK-0001",
            "work_item_revision": 1,
            "plan": {"path": "PLAN.md", "sha256": file_sha256(plan_path)},
            "decisions": [
                {
                    "decision_id": "PD-001",
                    "decision_owner": "human",
                    "question": "Which compatibility policy should the Plan use?",
                    "options": [
                        {
                            "option_id": "OPT-01",
                            "label": "Preserve behavior (Recommended)",
                            "consequence": "Keeps existing callers compatible.",
                        },
                        {
                            "option_id": "OPT-02",
                            "label": "Adopt strict behavior",
                            "consequence": "Simplifies the new path but breaks callers.",
                        },
                    ],
                    "recommended_option_id": "OPT-01",
                    "status": "PENDING",
                    "resolution": None,
                }
            ],
        }
        write_json_atomic(register_path, register)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                [
                    "plan=PLAN.md",
                    "plan_decisions=plan-decisions.json",
                    "working_set=working-set.json",
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )

        blocked = transition(
            self.repo,
            "TASK-0001",
            "BLOCK",
            [],
            None,
            None,
            None,
            "plan_decision",
            "PD-001 requires a Human selection",
            "human",
        )
        self.assertEqual(blocked["to"], "BLOCKED")
        decision_lock = self.task / ".transition.lock"
        decision_lock.write_text("held", encoding="utf-8")
        with self.assertRaises(InputFailure):
            record_plan_decision(
                self.repo, "TASK-0001", "PD-001", "OPT-01", "repository-owner"
            )
        decision_lock.unlink()
        recorded = record_plan_decision(
            self.repo, "TASK-0001", "PD-001", "OPT-01", "repository-owner"
        )
        authority_path = self.repo / recorded["decision"]
        authority = read_json(authority_path)
        self.assertEqual(authority["decision"], "OPT-01")
        self.assertEqual(authority["plan_decision_id"], "PD-001")
        resolved_register = read_json(register_path)
        self.assertEqual(resolved_register["decisions"][0]["status"], "RESOLVED")

        resolved = transition(
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
        self.assertEqual(resolved["to"], "QUALIFIED")
        wrong_context = copy.deepcopy(authority)
        wrong_context["plan_decision_id"] = "PD-002"
        write_json_atomic(authority_path, wrong_context)
        resolved_register["decisions"][0]["resolution"]["decision_sha256"] = (
            file_sha256(authority_path)
        )
        write_json_atomic(register_path, resolved_register)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                [
                    "plan=PLAN.md",
                    "plan_decisions=plan-decisions.json",
                    "working_set=working-set.json",
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        write_json_atomic(authority_path, authority)
        resolved_register["decisions"][0]["resolution"]["decision_sha256"] = (
            file_sha256(authority_path)
        )
        write_json_atomic(register_path, resolved_register)
        planned = transition(
            self.repo,
            "TASK-0001",
            "PLAN",
            [
                "plan=PLAN.md",
                "plan_decisions=plan-decisions.json",
                "working_set=working-set.json",
            ],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        self.assertEqual(planned["to"], "PLANNED")
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "PLANNED")
        with simulated_symlinks(authority_path):
            with self.assertRaises(RuleFailure):
                validate(self.repo, "TASK-0001")

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
        handoff = build_implementation_handoff(self.repo, "TASK-0001")
        package = read_json(Path(handoff["path"]))["package"]
        self.assertIn("plan_decisions", {entry["role"] for entry in package})

    def test_working_set_json_rejects_wrong_revision_and_unsafe_paths(self) -> None:
        """Working Set 绑定 Revision，并拒绝越界、不存在或无理由的路径。"""
        self.freeze_work_item()
        transition(
            self.repo, "TASK-0001", "QUALIFY", [], None, None, None, None, None, None
        )
        build_working_set(self.repo, "TASK-0001", True)
        path = self.task / "working-set.json"
        valid = read_json(path)
        self.assertFalse((self.task / "WORKING_SET.md").exists())

        wrong_revision = copy.deepcopy(valid)
        wrong_revision["work_item_revision"] = 2
        write_json_atomic(path, wrong_revision)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                [
                    "plan=PLAN.md",
                    "plan_decisions=plan-decisions.json",
                    "working_set=working-set.json",
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )

        unsafe = copy.deepcopy(valid)
        unsafe["entries"].append(
            {
                "section": "Code",
                "path": "../../outside.py",
                "reason": "invalid escape",
                "discovered_from": "test",
            }
        )
        write_json_atomic(path, unsafe)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                [
                    "plan=PLAN.md",
                    "plan_decisions=plan-decisions.json",
                    "working_set=working-set.json",
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        nonexistent = copy.deepcopy(valid)
        nonexistent["entries"].append(
            {
                "section": "Code",
                "path": "src/provider-guess.py",
                "reason": "reported by Code Intelligence",
                "discovered_from": "CIQ-001",
            }
        )
        write_json_atomic(path, nonexistent)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                [
                    "plan=PLAN.md",
                    "plan_decisions=plan-decisions.json",
                    "working_set=working-set.json",
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )

        unjustified = copy.deepcopy(valid)
        unjustified["entries"].append(
            {
                "section": "Code",
                "path": "scripts",
                "reason": "   ",
                "discovered_from": "CIQ-001",
            }
        )
        write_json_atomic(path, unjustified)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo,
                "TASK-0001",
                "PLAN",
                [
                    "plan=PLAN.md",
                    "plan_decisions=plan-decisions.json",
                    "working_set=working-set.json",
                ],
                None,
                None,
                None,
                None,
                None,
                None,
            )
        write_json_atomic(path, valid)

    def test_project_index_json_rejects_wrong_project_and_stale_tasks(self) -> None:
        """Project Index 必须绑定项目，并完整列出 active task。"""
        path = self.repo / ".polaris" / "project-index.json"
        valid = read_json(path)
        self.assertFalse((self.repo / ".polaris" / "project-index.md").exists())

        wrong_project = copy.deepcopy(valid)
        wrong_project["project_id"] = "another-project"
        write_json_atomic(path, wrong_project)
        with self.assertRaises(RuleFailure):
            validate_project(self.repo)

        stale = copy.deepcopy(valid)
        stale["tasks"] = []
        write_json_atomic(path, stale)
        with self.assertRaises(RuleFailure):
            validate_project(self.repo)
        write_json_atomic(path, valid)

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
        project["polaris_version"] = "9.9.9"
        write_json_atomic(project_path, project)
        with self.assertRaises(RuleFailure):
            validate_project(self.repo)
        events_before = (self.task / "events.jsonl").read_text(encoding="utf-8")
        with self.assertRaisesRegex(RuleFailure, "explicit migration"):
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
        with self.assertRaisesRegex(RuleFailure, "explicit migration"):
            init_task(self.repo, "TASK-0002", "R1")
        self.assertEqual(
            (self.task / "events.jsonl").read_text(encoding="utf-8"),
            events_before,
        )
        self.assertFalse((self.repo / ".polaris" / "tasks" / "TASK-0002").exists())

    def test_every_normal_writer_uses_the_protocol_compatibility_gate(self) -> None:
        """全部正常状态写入口共享项目、workflow 与任务版本门禁。"""
        writers = (
            "build_implementation_handoff.py",
            "build_review_handoff.py",
            "build_working_set.py",
            "init_task.py",
            "new_revision.py",
            "rebuild_state.py",
            "record_exploration.py",
            "record_code_intelligence.py",
            "record_plan_decision.py",
            "refresh_project_index.py",
            "transition_task.py",
            "update_implementation_progress.py",
        )
        for name in writers:
            source = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("require_protocol_compatible", source, name)

        workflow_path = self.repo / ".polaris" / "workflow.json"
        workflow = read_json(workflow_path)
        workflow["workflow_version"] = "0.1.99"
        write_json_atomic(workflow_path, workflow)
        with self.assertRaisesRegex(RuleFailure, "frozen workflow"):
            require_protocol_compatible(self.repo)

        workflow["workflow_version"] = "0.1.2"
        write_json_atomic(workflow_path, workflow)
        state = read_json(self.task / "state.json")
        state["polaris_version"] = "0.1.10"
        with self.assertRaisesRegex(RuleFailure, "task Polaris version"):
            require_protocol_compatible(self.repo, state)

    def test_explicit_migration_appends_task_event_and_records_completion(self) -> None:
        """相邻版本迁移追加审计事件，不改写任务历史，并留下完成记录。"""
        self.set_protocol_version("0.1.18")
        vendor(ROOT, self.repo, False)

        result = migrate_project(self.repo)

        self.assertEqual(result["from"], "0.1.18")
        self.assertEqual(result["to"], "0.1.19")
        self.assertEqual(result["migrated_tasks"], 1)
        events = read_jsonl(self.task / "events.jsonl")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["polaris_version"], "0.1.18")
        self.assertEqual(events[1]["event"], "MIGRATE_POLARIS")
        self.assertEqual(events[1]["from"], events[1]["to"])
        self.assertEqual(events[1]["polaris_version"], "0.1.19")
        record = read_json(
            self.repo
            / ".polaris"
            / "migrations"
            / "MIG-0.1.18-to-0.1.19.json"
        )
        self.assertEqual(record["status"], "COMPLETED")
        self.assertIsNotNone(record["completed_at"])
        self.assertEqual(
            set(load_task_locations(self.repo)),
            {"TASK-0001"},
        )
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)

    def test_migration_resumes_after_event_append_without_duplication(self) -> None:
        """中断后重跑会采用已追加的迁移事件并完成投影，不重复写事件。"""
        self.set_protocol_version("0.1.18")
        vendor(ROOT, self.repo, False)
        state = read_json(self.task / "state.json")
        started_at = "2026-08-15T00:00:00Z"
        record = {
            "record_version": 1,
            "migration_id": "0.1.18-to-0.1.19",
            "from_polaris_version": "0.1.18",
            "to_polaris_version": "0.1.19",
            "from_workflow_version": "0.1.2",
            "to_workflow_version": "0.1.2",
            "status": "IN_PROGRESS",
            "started_at": started_at,
            "completed_at": None,
            "tasks": [
                {
                    "task_id": "TASK-0001",
                    "source_sequence": 0,
                    "migration_sequence": 1,
                }
            ],
        }
        write_json_atomic(
            self.repo
            / ".polaris"
            / "migrations"
            / "MIG-0.1.18-to-0.1.19.json",
            record,
        )
        append_jsonl(
            self.task / "events.jsonl",
            {
                "sequence": 1,
                "timestamp": started_at,
                "event": "MIGRATE_POLARIS",
                "gate": "explicit_protocol_migration",
                "from": state["status"],
                "to": state["status"],
                "task_id": "TASK-0001",
                "polaris_version": "0.1.19",
                "workflow_version": "0.1.2",
                "current_revision": state["current_revision"],
                "rigor": state["rigor"],
                "blocked_from": state["blocked_from"],
                "blocker": state["blocker"],
                "artifacts": state["artifacts"],
                "subject": state["subject"],
                "migration_id": "0.1.18-to-0.1.19",
            },
        )

        migrate_project(self.repo)

        self.assertEqual(len(read_jsonl(self.task / "events.jsonl")), 2)
        self.assertEqual(read_json(self.task / "state.json")["sequence"], 1)
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)

    def test_migration_reclaims_only_its_own_dead_process_lock(self) -> None:
        """迁移可接管同一迁移的崩溃锁，但不能抢占仍存活的进程。"""
        self.set_protocol_version("0.1.18")
        vendor(ROOT, self.repo, False)
        lock_path = self.task / ".transition.lock"
        write_json_atomic(
            lock_path,
            {
                "lock_version": 1,
                "kind": "polaris_migration",
                "migration_id": "0.1.18-to-0.1.19",
                "task_id": "TASK-0001",
                "hostname": socket.gethostname(),
                "pid": 2147483647,
                "created_at": "2026-08-15T00:00:00Z",
            },
        )

        migrate_project(self.repo)

        self.assertFalse(lock_path.exists())
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)

        write_json_atomic(
            lock_path,
            {
                "lock_version": 1,
                "kind": "polaris_migration",
                "migration_id": "active-migration",
                "task_id": "TASK-0001",
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "created_at": "2026-08-15T00:00:00Z",
            },
        )
        with self.assertRaisesRegex(InputFailure, "still running"):
            acquire_migration_lock(
                lock_path, "active-migration", "TASK-0001"
            )
        lock_path.unlink()

    def test_migration_rejects_an_undeclared_version_jump(self) -> None:
        """没有注册的跨版本路径机械拒绝，且不创建部分迁移记录。"""
        self.set_protocol_version("0.1.10")
        vendor(ROOT, self.repo, False)

        with self.assertRaisesRegex(RuleFailure, "no explicit adjacent migration"):
            migrate_project(self.repo)

        self.assertFalse((self.repo / ".polaris" / "migrations").exists())
        self.assertEqual(
            read_json(self.repo / ".polaris" / "project.json")["polaris_version"],
            "0.1.10",
        )

    def test_code_intelligence_auto_detects_available_operations_and_can_be_disabled(self) -> None:
        """已初始化的可选代码情报按 MCP 工具能力发现；缺失或禁用时不产生硬依赖。"""
        (self.repo / ".codegraph").mkdir()
        selected = select_provider(
            self.repo,
            ["codegraph_explore", "codegraph_status"],
            ROOT,
        )
        self.assertEqual(selected["provider_id"], "codegraph")
        self.assertEqual(
            selected["operations"],
            {
                "explore": "codegraph_explore",
                "status": "codegraph_status",
            },
        )
        self.assertIsNone(select_provider(self.repo, [], ROOT))

        config = load_config(self.repo, ROOT)
        config["mode"] = "disabled"
        write_json_atomic(self.repo / ".polaris" / "code-intelligence.json", config)
        self.assertIsNone(
            select_provider(self.repo, ["codegraph_explore"], ROOT)
        )
        self.assertEqual(
            validate_static_configuration(self.repo, ROOT)["mode"], "disabled"
        )

    def test_code_intelligence_v1_record_is_read_only_historical_evidence(self) -> None:
        """v1 精简记录升级后仍可读取，并绑定任务、提交和安全路径。"""
        base = run_git(self.repo, "rev-parse", "HEAD")
        value = read_json(
            ROOT / "templates" / "task-sources" / "code-intelligence-record.json"
        )
        value["record_version"] = 1
        value.pop("sync")
        value.pop("freshness")
        value.pop("source_fallbacks")
        value.pop("status_check")
        value["refresh"] = None
        value["target"]["base_commit"] = base
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["status"],
            "UNAVAILABLE",
        )
        with self.assertRaisesRegex(InputFailure, "record_version 2"):
            record_code_intelligence(self.repo, "TASK-0001", value, ROOT)

        invalid = copy.deepcopy(value)
        invalid["status"] = "USED"
        invalid["provider"] = {
            "id": "codegraph",
            "descriptor_version": 1,
            "transport": "mcp",
            "available_operations": ["symbol_search"],
        }
        invalid["queries"] = [
            {
                "id": "CIQ-001",
                "operation": "symbol_search",
                "purpose": "find an affected symbol",
                "status": "SUCCESS",
                "summary": "one external result",
                "symbols": [
                    {"path": "../outside.cpp", "line": 1, "name": "outside"}
                ],
                "response_sha256": "0" * 64,
                "error": None,
            }
        ]
        with self.assertRaises(RuleFailure):
            validate_record_value(self.repo, "TASK-0001", invalid, ROOT)

        failed = copy.deepcopy(invalid)
        failed["provider"]["available_operations"] = [
            "symbol_search",
            "refresh_files",
        ]
        failed.update(
            {
                "stage": "IMPLEMENTATION",
                "artifact_attempt": 1,
                "status": "FAILED",
                "queries": [
                    {
                        "id": "CIQ-001",
                        "operation": "symbol_search",
                        "purpose": "find an affected symbol",
                        "status": "FAILED",
                        "summary": "",
                        "symbols": [],
                        "response_sha256": None,
                        "error": "provider timeout",
                    }
                ],
                "refresh": {
                    "operation": "refresh_files",
                    "paths": [],
                    "status": "FAILED",
                    "freshness": "not_verified",
                    "response_sha256": None,
                    "error": "refresh timeout",
                },
            }
        )
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", failed, ROOT)["status"],
            "FAILED",
        )

        raw = self.task / "runtime" / "code-intelligence" / "response.json"
        raw.parent.mkdir(parents=True)
        raw.write_text("{}\n", encoding="utf-8")
        ignored = run_git(self.repo, "check-ignore", raw.relative_to(self.repo).as_posix())
        self.assertEqual(ignored, raw.relative_to(self.repo).as_posix())

    def test_code_intelligence_add_enables_prioritizes_and_preserves_scope(self) -> None:
        """add 命令启用并优先 Provider，同时保留已有索引范围且可幂等重跑。"""
        config_path = self.repo / ".polaris" / "code-intelligence.json"
        write_json_atomic(
            config_path,
            {
                "config_version": 1,
                "mode": "disabled",
                "provider_priority": [],
                "include": ["src/**", "tests/**"],
                "exclude": ["vendor/**", "generated/**"],
            },
        )

        result = configure_code_intelligence(self.repo, "codegraph")

        self.assertTrue(result["changed"])
        self.assertEqual(result["runtime_status"], "checked_by_next_workflow")
        config = read_json(config_path)
        self.assertEqual(config["mode"], "auto_optional")
        self.assertEqual(config["provider_priority"], ["codegraph"])
        self.assertEqual(config["include"], ["src/**", "tests/**"])
        self.assertEqual(config["exclude"], ["vendor/**", "generated/**"])
        before = config_path.read_bytes()

        repeated = configure_code_intelligence(self.repo, "codegraph")

        self.assertFalse(repeated["changed"])
        self.assertEqual(config_path.read_bytes(), before)
        self.assertEqual(
            validate_static_configuration(self.repo, ROOT)["mode"], "auto_optional"
        )

    def test_code_intelligence_add_rejects_unknown_provider_without_writing(self) -> None:
        """未知 Provider 返回输入错误，且不会创建或改写项目配置。"""
        config_path = self.repo / ".polaris" / "code-intelligence.json"
        self.assertFalse(config_path.exists())

        with self.assertRaises(InputFailure):
            add_provider(self.repo, "unknown-provider", ROOT)

        self.assertFalse(config_path.exists())

    def test_code_intelligence_refresh_uses_file_or_workspace_operations(self) -> None:
        """新增修改走文件刷新，删除重命名走工作区刷新，无代码变化则跳过。"""
        base = run_git(self.repo, "rev-parse", "HEAD")
        source = self.repo / "src" / "sample.cpp"
        source.parent.mkdir()
        source.write_text("int sample() { return 1; }\n", encoding="utf-8")
        run_git(self.repo, "add", "src/sample.cpp")
        run_git(self.repo, "commit", "-q", "-m", "add source")
        added = run_git(self.repo, "rev-parse", "HEAD")

        incremental = plan_refresh(self.repo, base, added, "codegraph", ROOT)
        self.assertEqual(incremental["operation"], "refresh_files")
        self.assertEqual(incremental["status"], "PENDING")
        self.assertEqual(incremental["paths"][0]["change"], "ADDED")
        self.assertEqual(
            incremental["paths"][0]["sha256"], file_sha256(source)
        )

        run_git(self.repo, "mv", "src/sample.cpp", "src/renamed.cpp")
        run_git(self.repo, "commit", "-q", "-m", "rename source")
        renamed = run_git(self.repo, "rev-parse", "HEAD")
        workspace = plan_refresh(self.repo, added, renamed, "codegraph", ROOT)
        self.assertEqual(workspace["operation"], "refresh_workspace")
        self.assertEqual(workspace["paths"][0]["change"], "RENAMED")

        (self.repo / "NOTES.md").write_text("notes\n", encoding="utf-8")
        run_git(self.repo, "add", "NOTES.md")
        run_git(self.repo, "commit", "-q", "-m", "add notes")
        docs = run_git(self.repo, "rev-parse", "HEAD")
        skipped = plan_refresh(self.repo, renamed, docs, "codegraph", ROOT)
        self.assertEqual(skipped["status"], "SKIPPED")
        self.assertEqual(skipped["paths"], [])

    def test_risk_flag_requires_r2(self) -> None:
        """任一高风险标记为 true 时，非 R2 Work Item 会被机械拒绝。"""
        path = self.task / "revisions" / "work-item-r001.json"
        value = read_json(path)
        value["risk_flags"]["security"] = True
        write_json_atomic(path, value)
        with self.assertRaises(RuleFailure):
            validate(self.repo, "TASK-0001")

    def test_vendored_target_is_self_contained(self) -> None:
        """目标仓库 vendoring 后同时包含 Codex、Claude Code 与机械协议。"""
        vendor(ROOT, self.repo, False)
        for adapter in load_host_adapters(ROOT):
            skill_root = self.repo / str(adapter["skill_target"])
            self.assertTrue((skill_root / "engineering-task" / "SKILL.md").is_file())
            for item in adapter["files"]:
                self.assertTrue((self.repo / item["target"]).is_file())
        self.assertTrue((self.repo / "tools" / "polaris" / "VERSION").is_file())
        self.assertTrue(
            (self.repo / "tools" / "polaris" / "hosts" / "codex" / "adapter.json").is_file()
        )
        self.assertTrue(
            (
                self.repo
                / "tools"
                / "polaris"
                / "providers"
                / "code-intelligence"
                / "codegraph.json"
            ).is_file()
        )
        self.assertEqual(
            (self.repo / "tools" / "polaris" / "pyproject.toml").read_bytes(),
            (ROOT / "pyproject.toml").read_bytes(),
        )
        self.assertEqual(
            (self.repo / "tools" / "polaris" / "polaris_cli.py").read_bytes(),
            (ROOT / "polaris_cli.py").read_bytes(),
        )
        result = validate_project(self.repo)
        self.assertEqual(result["active_tasks"], 1)

    def test_doctor_reports_a_healthy_vendored_project_without_writing(self) -> None:
        """Doctor 聚合健康检查并通过报告 Schema，且诊断前后项目文件完全不变。"""
        vendor(ROOT, self.repo, False)
        before = repository_file_snapshot(self.repo)

        report = diagnose_project(self.repo)

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["warnings"], 0)
        self.assertEqual(report["mode"], "vendored")
        self.assertIn(
            "task:TASK-0001", {check["id"] for check in report["checks"]}
        )
        self.assertTrue(
            all(not check["actions"] for check in report["checks"])
        )
        schema = read_json(ROOT / "schemas" / "doctor-report.schema.json")
        self.assertEqual(validate_schema(report, schema), [])
        self.assertEqual(repository_file_snapshot(self.repo), before)

    def test_doctor_aggregates_independent_failures_with_actions(self) -> None:
        """多个独立故障一次全部报告，且每个失败项都提供明确的人工动作。"""
        vendor(ROOT, self.repo, False)
        managed_skill = (
            self.repo / ".agents" / "skills" / "engineering-task" / "SKILL.md"
        )
        managed_skill.write_text("tampered\n", encoding="utf-8")
        state_path = self.task / "state.json"
        state = read_json(state_path)
        state["status"] = "CLOSED"
        write_json_atomic(state_path, state)
        gitignore_path = self.repo / ".gitignore"
        gitignore = gitignore_path.read_text(encoding="utf-8")
        gitignore_path.write_text(
            gitignore.replace(f"{ARCHIVED_RUNTIME_IGNORE_PATTERN}\n", ""),
            encoding="utf-8",
        )

        report = diagnose_project(self.repo)

        failed = {
            check["id"]: check
            for check in report["checks"]
            if check["status"] == "FAIL"
        }
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(
            {
                "install_manifest",
                "project_index",
                "task:TASK-0001",
                "project_validation",
                "runtime_ignore",
            }.issubset(failed)
        )
        self.assertTrue(
            all(check["evidence"] and check["actions"] for check in failed.values())
        )
        self.assertEqual(report["summary"]["failed"], len(failed))

    def test_doctor_warnings_are_non_blocking_and_cli_failures_block(self) -> None:
        """Doctor 对 WARN、FAIL 和自身运行错误分别返回 0、1、2。"""
        (self.task / ".transition.lock").write_text("held\n", encoding="utf-8")
        command = [
            sys.executable,
            str(SCRIPTS / "doctor_project.py"),
            "--repo",
            str(self.repo),
            "--json",
        ]

        warned = subprocess.run(command, text=True, capture_output=True)

        self.assertEqual(warned.returncode, 0, warned.stderr)
        warning_report = json.loads(warned.stdout)
        self.assertEqual(warning_report["status"], "WARN")
        warnings = [
            check
            for check in warning_report["checks"]
            if check["status"] == "WARN"
        ]
        self.assertTrue(
            {"protocol", "install_manifest", "operation_residue"}.issubset(
                {check["id"] for check in warnings}
            )
        )
        self.assertTrue(
            all(check["evidence"] and check["actions"] for check in warnings)
        )
        (self.task / ".transition.lock").unlink()
        (self.repo / ".gitignore").unlink()

        failed = subprocess.run(command, text=True, capture_output=True)

        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertEqual(json.loads(failed.stdout)["status"], "FAIL")

        output = io.StringIO()
        with (
            mock.patch.object(
                doctor_module,
                "diagnose_project",
                side_effect=OSError("diagnostic runtime unavailable"),
            ),
            mock.patch.object(
                sys,
                "argv",
                ["doctor_project.py", "--repo", str(self.repo), "--json"],
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(doctor_module.main(), 2)
        error_report = json.loads(output.getvalue())
        self.assertEqual(error_report["status"], "ERROR")
        schema = read_json(ROOT / "schemas" / "doctor-report.schema.json")
        self.assertEqual(validate_schema(error_report, schema), [])

    def test_install_manifest_detects_drift_and_preserves_project_owned_files(self) -> None:
        """清单哈希拒绝受管文件漂移，但不把项目自有文件冻结为模板内容。"""
        vendor(ROOT, self.repo, False)
        with self.assertRaisesRegex(InputFailure, "requires --force"):
            vendor(ROOT, self.repo, False, discard_managed_changes=True)
        manifest_path = self.repo / "tools" / "polaris" / "install-manifest.json"
        manifest = read_json(manifest_path)
        managed = {item["path"]: item for item in manifest["managed_files"]}
        self.assertEqual(manifest["manifest_version"], 2)
        self.assertEqual(
            manifest["polaris_version"],
            (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
        )
        self.assertIn(
            ".agents/skills/engineering-task/SKILL.md",
            managed,
        )
        self.assertIn("tools/polaris/scripts/validate_project.py", managed)
        self.assertEqual(
            managed[".agents/skills/engineering-task/SKILL.md"]["hash_mode"],
            TEXT_HASH_MODE,
        )
        self.assertIn("CLAUDE.md", manifest["preserved_files"])
        self.assertIn(".gitignore", manifest["preserved_files"])

        managed_skill = (
            self.repo / ".agents" / "skills" / "engineering-task" / "SKILL.md"
        )
        lf_content = managed_skill.read_bytes().replace(b"\r\n", b"\n")
        managed_skill.write_bytes(lf_content.replace(b"\n", b"\r\n"))
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)

        managed_skill.write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(RuleFailure, "hash mismatch"):
            validate_project(self.repo)

        project_rules = self.repo / "CLAUDE.md"
        project_rules.write_text("# Project-owned rules\n", encoding="utf-8")
        with self.assertRaisesRegex(RuleFailure, "hash mismatch"):
            vendor(ROOT, self.repo, True)
        vendor(ROOT, self.repo, True, discard_managed_changes=True)
        self.assertEqual(
            project_rules.read_text(encoding="utf-8"), "# Project-owned rules\n"
        )
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)

    def test_install_manifest_upgrades_v1_newlines_and_keeps_binary_hashes_strict(
        self,
    ) -> None:
        """旧清单只兼容文本换行；v2 未知二进制资产仍执行原始字节哈希。"""
        vendor(ROOT, self.repo, False)
        manifest_path = self.repo / "tools" / "polaris" / "install-manifest.json"
        manifest = read_json(manifest_path)
        managed_skill = (
            self.repo / ".agents" / "skills" / "engineering-task" / "SKILL.md"
        )
        lf_content = managed_skill.read_bytes().replace(b"\r\n", b"\n")
        managed_skill.write_bytes(lf_content)
        manifest["manifest_version"] = 1
        for item in manifest["managed_files"]:
            item.pop("hash_mode")
            item["sha256"] = file_sha256(self.repo / item["path"])
        write_json_atomic(manifest_path, manifest)

        managed_skill.write_bytes(lf_content.replace(b"\n", b"\r\n"))
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)
        vendor(ROOT, self.repo, True)

        manifest = read_json(manifest_path)
        binary_path = self.repo / "tools" / "polaris" / "opaque.bin"
        binary_path.write_bytes(b"\x00line\n")
        manifest["managed_files"].append(
            {
                "path": binary_path.relative_to(self.repo).as_posix(),
                "hash_mode": BYTE_HASH_MODE,
                "sha256": managed_file_sha256(binary_path, BYTE_HASH_MODE),
            }
        )
        manifest["managed_files"].sort(key=lambda item: item["path"])
        write_json_atomic(manifest_path, manifest)
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)

        binary_path.write_bytes(b"\x00line\r\n")
        with self.assertRaisesRegex(RuleFailure, "hash mismatch"):
            validate_project(self.repo)

    def test_install_manifest_rejects_invalid_hash_contracts(self) -> None:
        """清单版本、必填模式、路径分类和文本编码必须机械一致。"""
        vendor(ROOT, self.repo, False)
        manifest_path = self.repo / "tools" / "polaris" / "install-manifest.json"
        manifest = read_json(manifest_path)
        skill_relative = ".agents/skills/engineering-task/SKILL.md"
        skill_item = next(
            item
            for item in manifest["managed_files"]
            if item["path"] == skill_relative
        )
        managed_skill = self.repo / skill_relative

        manifest["manifest_version"] = 1
        write_json_atomic(manifest_path, manifest)
        with self.assertRaisesRegex(RuleFailure, "v1 must not declare hash_mode"):
            validate_project(self.repo)

        manifest["manifest_version"] = 2
        skill_item.pop("hash_mode")
        write_json_atomic(manifest_path, manifest)
        with self.assertRaisesRegex(RuleFailure, "lacks hash_mode"):
            validate_project(self.repo)

        skill_item["hash_mode"] = BYTE_HASH_MODE
        write_json_atomic(manifest_path, manifest)
        with self.assertRaisesRegex(RuleFailure, "hash mode mismatch"):
            validate_project(self.repo)

        skill_item["hash_mode"] = TEXT_HASH_MODE
        write_json_atomic(manifest_path, manifest)
        managed_skill.write_bytes(b"\xff")
        with self.assertRaisesRegex(InputFailure, "not UTF-8"):
            validate_project(self.repo)

    def test_vendor_rolls_back_after_partial_apply_failure(self) -> None:
        """事务应用中途失败时恢复全部旧输出，不留下半更新安装。"""
        vendor(ROOT, self.repo, False)
        manifest_path = self.repo / "tools" / "polaris" / "install-manifest.json"
        skill_path = self.repo / ".agents" / "skills" / "engineering-task" / "SKILL.md"
        original_manifest = manifest_path.read_bytes()
        original_skill = skill_path.read_bytes()
        with tempfile.TemporaryDirectory(prefix="polaris-vendor-source-") as temp:
            source = Path(temp) / "source"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            canonical = source / "skills" / "engineering-task" / "SKILL.md"
            canonical.write_text(
                canonical.read_text(encoding="utf-8") + "\nTransaction test.\n",
                encoding="utf-8",
            )
            original_copy = vendor_module._copy_install_path
            copy_count = 0

            def fail_after_copy(staged: Path, destination: Path) -> None:
                nonlocal copy_count
                original_copy(staged, destination)
                copy_count += 1
                if copy_count == 2:
                    raise OSError("injected vendor apply failure")

            with mock.patch.object(
                vendor_module, "_copy_install_path", side_effect=fail_after_copy
            ):
                with self.assertRaisesRegex(OSError, "injected vendor apply failure"):
                    vendor(source, self.repo, True)

        self.assertEqual(manifest_path.read_bytes(), original_manifest)
        self.assertEqual(skill_path.read_bytes(), original_skill)
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)
        self.assertEqual(
            list(
                self.repo.parent.glob(
                    f".{self.repo.name}-polaris-vendor-transaction-*"
                )
            ),
            [],
        )

    def test_vendor_recovers_an_interrupted_apply_transaction(self) -> None:
        """下次 vendoring 会先恢复已崩溃进程留下的 APPLYING 事务。"""
        vendor(ROOT, self.repo, False)
        manifest_path = self.repo / "tools" / "polaris" / "install-manifest.json"
        original_manifest = manifest_path.read_bytes()
        with tempfile.TemporaryDirectory(prefix="polaris-vendor-crash-") as temp:
            source = Path(temp) / "source"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )

            def interrupt_apply(
                stage: Path, target: Path, affected: list[Path]
            ) -> None:
                destination = affected[0]
                staged = stage / destination.relative_to(target)
                vendor_module._remove_path(destination)
                vendor_module._copy_install_path(staged, destination)
                raise SystemExit("simulated process crash")

            with mock.patch.object(
                vendor_module, "_apply_staged_install", side_effect=interrupt_apply
            ):
                with self.assertRaisesRegex(SystemExit, "simulated process crash"):
                    vendor(source, self.repo, True)

            transactions = list(
                self.repo.parent.glob(
                    f".{self.repo.name}-polaris-vendor-transaction-*"
                )
            )
            self.assertEqual(len(transactions), 1)
            journal_path = transactions[0] / "journal.json"
            journal = read_json(journal_path)
            self.assertEqual(journal["status"], "APPLYING")
            with self.assertRaisesRegex(InputFailure, "still running"):
                vendor(source, self.repo, True)
            journal["pid"] = 2147483647
            write_json_atomic(journal_path, journal)
            (source / "VERSION").unlink()

            with self.assertRaisesRegex(RuleFailure, "Polaris VERSION"):
                vendor(source, self.repo, True)

        self.assertEqual(manifest_path.read_bytes(), original_manifest)
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)
        self.assertEqual(
            list(
                self.repo.parent.glob(
                    f".{self.repo.name}-polaris-vendor-transaction-*"
                )
            ),
            [],
        )

    def test_force_vendor_removes_files_owned_by_previous_manifest(self) -> None:
        """强制升级按旧清单清除已淘汰受管文件，不遗留历史产物。"""
        vendor(ROOT, self.repo, False)
        stale = self.repo / ".agents" / "skills" / "obsolete" / "SKILL.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("obsolete\n", encoding="utf-8")
        manifest_path = self.repo / "tools" / "polaris" / "install-manifest.json"
        manifest = read_json(manifest_path)
        manifest["managed_files"].append(
            {
                "path": stale.relative_to(self.repo).as_posix(),
                "hash_mode": TEXT_HASH_MODE,
                "sha256": managed_file_sha256(stale, TEXT_HASH_MODE),
            }
        )
        write_json_atomic(manifest_path, manifest)

        vendor(ROOT, self.repo, True)

        self.assertFalse(stale.exists())
        self.assertFalse(stale.parent.exists())
        current = read_json(manifest_path)
        self.assertNotIn(
            ".agents/skills/obsolete/SKILL.md",
            {item["path"] for item in current["managed_files"]},
        )
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)

    def test_init_project_adds_claude_bridge_without_overwriting_it(self) -> None:
        """初始化创建 Claude 规则桥接，已有 CLAUDE.md 仍归用户所有。"""
        self.assertIn(
            "/engineering-task",
            (self.repo / "CLAUDE.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "@AGENTS.md",
            (self.repo / "CLAUDE.md").read_text(encoding="utf-8"),
        )
        with tempfile.TemporaryDirectory(prefix="polaris-claude-rules-") as temp:
            repo = Path(temp)
            run_git(repo, "init", "-q")
            (repo / "CLAUDE.md").write_text("# Existing rules\n", encoding="utf-8")
            init_project(repo, "existing-claude-rules")
            self.assertEqual(
                (repo / "CLAUDE.md").read_text(encoding="utf-8"),
                "# Existing rules\n",
            )

    def test_engineering_task_requires_explicit_invocation(self) -> None:
        """所有 Polaris Skills 禁止隐式调用，用户只能从 engineering-task 显式进入。"""
        source_skill = ROOT / "skills" / "engineering-task"
        source_instructions = (source_skill / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "only when the user explicitly invokes `{{skill:engineering-task}}`",
            source_instructions,
        )
        self.assertIn(
            "explicitly invokes its rendered entry Skill",
            (self.repo / "AGENTS.md").read_text(encoding="utf-8"),
        )

        vendor(ROOT, self.repo, False)
        codex = host_adapter("codex")
        claude = host_adapter("claude-code")
        for skill_name in SKILLS:
            source = ROOT / "skills" / skill_name
            vendored = self.repo / ".agents" / "skills" / skill_name
            source_metadata = (
                ROOT
                / "hosts"
                / "codex"
                / "skill-overlays"
                / skill_name
                / "agents"
                / "openai.yaml"
            ).read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: false", source_metadata)
            self.assertEqual(
                (vendored / "SKILL.md").read_text(encoding="utf-8"),
                render_skill(
                    (source / "SKILL.md").read_text(encoding="utf-8"),
                    skill_name,
                    codex,
                ),
            )
            self.assertEqual(
                (vendored / "agents" / "openai.yaml").read_text(encoding="utf-8"),
                source_metadata,
            )
            claude_skill = self.repo / ".claude" / "skills" / skill_name
            self.assertEqual(
                (claude_skill / "SKILL.md").read_text(encoding="utf-8"),
                render_skill(
                    (source / "SKILL.md").read_text(encoding="utf-8"),
                    skill_name,
                    claude,
                ),
            )
            self.assertFalse((claude_skill / "agents" / "openai.yaml").exists())
        claude_entry = (
            self.repo / ".claude" / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", claude_entry)
        self.assertIn("explicitly invokes `/engineering-task`", claude_entry)
        self.assertNotIn("$engineering-task", claude_entry)

    def test_host_adapters_render_from_one_host_neutral_skill_source(self) -> None:
        """宿主语法和执行附录来自清单，核心 Skill 不内置宿主分支。"""
        source = (ROOT / "skills" / "engineering-task" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("{{skill:engineering-task}}", source)
        self.assertNotIn("$engineering-task", source)
        self.assertNotIn("/engineering-task", source)

        adapters = {item["host_id"]: item for item in load_host_adapters(ROOT)}
        self.assertEqual(set(adapters), {"codex", "claude-code"})
        self.assertFalse((ROOT / "hosts" / "codex" / "skills").exists())
        codex = render_skill(source, "engineering-task", adapters["codex"])
        claude = render_skill(source, "engineering-task", adapters["claude-code"])
        self.assertIn("$engineering-task", codex)
        self.assertIn("fresh visible Codex tasks", codex)
        self.assertIn("/engineering-task", claude)
        self.assertIn("non-fork `polaris-implementer`", claude)
        self.assertIn("disable-model-invocation: true", claude)

        synthetic = dict(adapters["codex"])
        synthetic.update(
            {
                "host_id": "synthetic",
                "invocation_prefix": "!",
                "entry_frontmatter": [],
                "skill_appendix_root": None,
            }
        )
        rendered = render_skill(source, "engineering-task", synthetic)
        self.assertIn("!engineering-task", rendered)
        self.assertNotIn("Codex host execution", rendered)
        with self.assertRaises(InputFailure):
            render_skill(
                source + "\n{{skill:not-installed}}\n",
                "engineering-task",
                synthetic,
                set(SKILLS),
            )

    def test_host_adapter_contract_rejects_invalid_or_conflicting_manifests(self) -> None:
        """适配器拒绝未知版本、空调用语法、越界路径和重叠目标。"""

        def adapter(host_id: str) -> dict[str, object]:
            return {
                "adapter_version": 2,
                "host_id": host_id,
                "display_name": host_id,
                "skill_target": f".{host_id}/skills",
                "invocation_prefix": "!",
                "entry_skill": "engineering-task",
                "capabilities": {
                    "structured_user_input": False,
                    "worker_create": False,
                    "worker_status": False,
                    "worker_resume": False,
                    "stable_worker_identity": False,
                },
                "entry_frontmatter": [],
                "skill_overlay_root": None,
                "skill_appendix_root": None,
                "files": [
                    {
                        "source": "bridge.md",
                        "target": f".{host_id}/bridge.md",
                        "overwrite": True,
                    }
                ],
            }

        cases = {
            "unknown version": lambda first, _second: first.update(
                {"adapter_version": 3}
            ),
            "blank prefix": lambda first, _second: first.update(
                {"invocation_prefix": ""}
            ),
            "unsafe path": lambda first, _second: first.update(
                {"skill_target": "../escape"}
            ),
            "overlapping target": lambda first, second: second["files"][0].update(
                {"target": first["skill_target"]}
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory(
                prefix="polaris-host-contract-"
            ) as temp:
                root = Path(temp)
                (root / "schemas").mkdir()
                shutil.copyfile(
                    ROOT / "schemas" / "host-adapter.schema.json",
                    root / "schemas" / "host-adapter.schema.json",
                )
                shutil.copytree(ROOT / "skills", root / "skills")
                first = adapter("host-a")
                second = adapter("host-b")
                mutate(first, second)
                for value in (first, second):
                    host_root = root / "hosts" / str(value["host_id"])
                    host_root.mkdir(parents=True)
                    (host_root / "bridge.md").write_text(
                        "bridge\n", encoding="utf-8"
                    )
                    write_json_atomic(host_root / "adapter.json", value)
                with self.assertRaises(RuleFailure):
                    load_host_adapters(root)

    def test_host_adapter_hardening_rejects_entry_overlay_and_capability_errors(self) -> None:
        """入口必须存在，overlay 不得覆写 Skill，worker 能力依赖必须自洽。"""
        cases = {
            "missing entry": (
                lambda adapter, _source: adapter.update(
                    {"entry_skill": "not-installed"}
                ),
                "entry_skill is not installed",
            ),
            "SKILL overlay": (
                lambda _adapter, source: (
                    source
                    / "hosts"
                    / "codex"
                    / "skill-overlays"
                    / "engineering-task"
                    / "SKILL.md"
                ).write_text("override\n", encoding="utf-8"),
                "must not replace SKILL.md",
            ),
            "inconsistent capabilities": (
                lambda adapter, _source: adapter["capabilities"].update(
                    {"worker_create": False}
                ),
                "worker_status requires worker_create",
            ),
        }
        for name, (mutate, message) in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory(
                prefix="polaris-adapter-hardening-"
            ) as temp:
                source = Path(temp) / "source"
                shutil.copytree(
                    ROOT,
                    source,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
                )
                adapter_path = source / "hosts" / "codex" / "adapter.json"
                adapter = read_json(adapter_path)
                mutate(adapter, source)
                write_json_atomic(adapter_path, adapter)
                with self.assertRaisesRegex(RuleFailure, message):
                    load_host_adapters(source)

    def test_host_adapter_sources_reject_symlinks(self) -> None:
        """所有平台都机械验证 Adapter 源文件的 symlink 拒绝分支。"""
        with tempfile.TemporaryDirectory(prefix="polaris-adapter-symlink-") as temp:
            temp_root = Path(temp)
            source = temp_root / "source"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            outside = temp_root / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            agent = (
                source
                / "hosts"
                / "claude-code"
                / "agents"
                / "polaris-reviewer.md"
            )

            with simulated_symlinks(agent):
                with self.assertRaisesRegex(RuleFailure, "symlink"):
                    load_host_adapters(source)
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_vendor_rejects_symlinked_adapter_targets(self) -> None:
        """所有平台都机械验证 vendoring 目标的 symlink 拒绝分支。"""
        with tempfile.TemporaryDirectory(prefix="polaris-target-symlink-") as temp:
            temp_root = Path(temp)
            target = temp_root / "target"
            outside = temp_root / "outside"
            target.mkdir()
            outside.mkdir()
            run_git(target, "init", "-q")

            with simulated_symlinks(target / ".agents"):
                with self.assertRaisesRegex(RuleFailure, "symlink"):
                    vendor(ROOT, target, False)
            self.assertEqual(list(outside.iterdir()), [])

    def test_real_filesystem_symlink_boundaries_when_supported(self) -> None:
        """文件系统支持 symlink 时，真实验证 Adapter 读边界和 vendoring 写边界。"""
        with tempfile.TemporaryDirectory(prefix="polaris-real-symlink-") as temp:
            temp_root = Path(temp)
            source = temp_root / "source"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            outside_file = temp_root / "outside.md"
            outside_file.write_text("outside\n", encoding="utf-8")
            agent = (
                source
                / "hosts"
                / "claude-code"
                / "agents"
                / "polaris-reviewer.md"
            )
            agent.unlink()
            try:
                agent.symlink_to(outside_file)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"filesystem symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(RuleFailure, "symlink"):
                load_host_adapters(source)

            target = temp_root / "target"
            outside_directory = temp_root / "outside"
            target.mkdir()
            outside_directory.mkdir()
            run_git(target, "init", "-q")
            try:
                (target / ".agents").symlink_to(
                    outside_directory, target_is_directory=True
                )
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"directory symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(RuleFailure, "symlink"):
                vendor(ROOT, target, False)
            self.assertEqual(list(outside_directory.iterdir()), [])

    def test_vendor_and_validator_discover_a_third_host_without_code_changes(self) -> None:
        """新增第三宿主只需清单，vendoring、初始化和校验无需新增分支。"""
        with tempfile.TemporaryDirectory(prefix="polaris-third-host-") as temp:
            temp_root = Path(temp)
            source = temp_root / "source"
            target = temp_root / "target"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"),
            )
            synthetic_root = source / "hosts" / "synthetic"
            synthetic_root.mkdir()
            write_json_atomic(
                synthetic_root / "adapter.json",
                {
                    "adapter_version": 2,
                    "host_id": "synthetic",
                    "display_name": "Synthetic Host",
                    "skill_target": ".synthetic/skills",
                    "invocation_prefix": "!",
                    "entry_skill": "engineering-task",
                    "capabilities": {
                        "structured_user_input": False,
                        "worker_create": False,
                        "worker_status": False,
                        "worker_resume": False,
                        "stable_worker_identity": False,
                    },
                    "entry_frontmatter": [],
                    "skill_overlay_root": None,
                    "skill_appendix_root": None,
                    "files": [],
                },
            )
            target.mkdir()
            run_git(target, "init", "-q")
            vendor(source, target, False)
            init_project(target, "third-host-project")
            entry = (
                target / ".synthetic" / "skills" / "engineering-task" / "SKILL.md"
            ).read_text(encoding="utf-8")
            self.assertIn("!engineering-task", entry)
            self.assertNotIn("{{skill:", entry)
            self.assertEqual(validate_project(target)["active_tasks"], 0)

    def test_force_vendor_preserves_unrelated_claude_configuration(self) -> None:
        """升级只替换 Polaris 的 Claude 文件，不删除项目已有配置。"""
        unrelated_skill = self.repo / ".claude" / "skills" / "project-specific"
        unrelated_agent = self.repo / ".claude" / "agents" / "project-agent.md"
        unrelated_skill.mkdir(parents=True)
        unrelated_agent.parent.mkdir(parents=True, exist_ok=True)
        (unrelated_skill / "SKILL.md").write_text("# Keep me\n", encoding="utf-8")
        unrelated_agent.write_text("# Keep me\n", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("# Project-owned Claude rules\n", encoding="utf-8")
        vendor(ROOT, self.repo, False)
        vendor(ROOT, self.repo, True)
        self.assertEqual(
            (unrelated_skill / "SKILL.md").read_text(encoding="utf-8"), "# Keep me\n"
        )
        self.assertEqual(unrelated_agent.read_text(encoding="utf-8"), "# Keep me\n")
        self.assertEqual(
            (self.repo / "CLAUDE.md").read_text(encoding="utf-8"),
            "# Project-owned Claude rules\n",
        )

    def test_validate_project_requires_complete_claude_adapter(self) -> None:
        """vendored 项目缺少 Claude Skill 或 worker 定义时机械拒绝。"""
        vendor(ROOT, self.repo, False)
        (self.repo / ".claude" / "agents" / "polaris-reviewer.md").unlink()
        with self.assertRaises(RuleFailure):
            validate_project(self.repo)

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
            "architecture-planning": ["PLAN_DECISIONS_NEEDED", "PLAN_READY"],
            "implementation": [],
            "documentation-sync": [],
            "adversarial-review": [],
            "validation": ["VALIDATION_PASS", "VALIDATION_FAIL"],
            "code-intelligence": [],
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
        architecture_text = (
            ROOT / "skills" / "architecture-planning" / "SKILL.md"
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
        self.assertIn("plan-decisions.json", architecture_text)
        self.assertIn("request_user_input", architecture_text)
        self.assertIn("two or three mutually exclusive options", architecture_text)
        self.assertIn("(Recommended)", architecture_text)
        self.assertIn("record_plan_decision.py", architecture_text)
        self.assertIn("precise free-form answer", architecture_text)
        self.assertIn("PLAN_DECISIONS_NEEDED", architecture_text)

        self.assertIn("request_user_input", entry_text)
        self.assertIn("If the tool is unavailable", entry_text)
        self.assertIn("Treat UI and text answers identically", entry_text)

        vendor(ROOT, self.repo, False)
        codex = host_adapter("codex")
        claude = host_adapter("claude-code")
        for skill_name, markers in expected_markers.items():
            source_path = ROOT / "skills" / skill_name / "SKILL.md"
            vendored_path = (
                self.repo / ".agents" / "skills" / skill_name / "SKILL.md"
            )
            source_text = source_path.read_text(encoding="utf-8")
            self.assertEqual(
                vendored_path.read_text(encoding="utf-8"),
                render_skill(source_text, skill_name, codex),
            )
            claude_path = self.repo / ".claude" / "skills" / skill_name / "SKILL.md"
            self.assertEqual(
                claude_path.read_text(encoding="utf-8"),
                render_skill(source_text, skill_name, claude),
            )
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
        source = (ROOT / "skills" / "engineering-task" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        entry_text = render_skill(source, "engineering-task", host_adapter("codex"))
        self.assertIn(
            "Polaris Implement · <TASK> · <REVISION> · attempt <N>", entry_text
        )
        self.assertIn("fresh visible Codex tasks in the same local checkout", entry_text)
        self.assertIn("Never fork the main conversation", entry_text)
        self.assertIn("use a separate worktree by default", entry_text)
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
        self.assertIn("Continue the exact same Implementer worker", entry_text)
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

    def test_frozen_task_references_survive_physical_root_relocation(self) -> None:
        """任务整体搬迁后，逻辑路径、handoff、进度、探索与恢复仍可解析。"""
        self.enter_implementing()
        handoff, _ = self.dispatch_implementation()
        recorded = record_exploration(
            self.repo,
            "TASK-0001",
            "scripts",
            "The task root may be movable",
            "Freeze a handoff before relocating the complete task directory",
            "The location resolver can rebind logical task references",
            "inconclusive",
            "Physical relocation had not yet been tested",
            "Retry after introducing the location registry",
            [],
        )
        promote_exploration(self.repo, "TASK-0001", recorded["exploration_id"])
        task_package_paths = {
            item["path"]
            for item in handoff["package"]
            if item["path"].startswith(".polaris/tasks/TASK-0001/")
        }
        self.assertTrue(task_package_paths)

        old_directory = self.task
        relocated = self.repo / ".polaris" / "archive" / "tasks" / "TASK-0001"
        relocated.parent.mkdir(parents=True)
        shutil.move(str(old_directory), str(relocated))
        registry_path = self.repo / ".polaris" / "task-locations.json"
        registry = read_json(registry_path)
        registry["locations"][0]["path"] = (
            ".polaris/archive/tasks/TASK-0001"
        )
        write_json_atomic(registry_path, registry)

        self.assertEqual(load_task_locations(self.repo)["TASK-0001"], relocated.absolute())
        with self.assertRaises(InputFailure):
            init_task(self.repo, "TASK-0001", "R1")
        self.assertFalse(old_directory.exists())
        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "IMPLEMENTING")
        state = read_json(relocated / "state.json")
        validate_implementation_handoff(
            self.repo,
            protocol_root(self.repo),
            relocated,
            state,
            True,
        )

        title = "Polaris Implement · TASK-0001 · r001 · attempt 1"
        progress = update_implementation_progress(
            self.repo,
            "TASK-0001",
            title,
            "Pending",
            "INITIALIZE",
        )
        self.assertTrue((relocated / "runtime" / "progress.json").is_file())
        self.assertEqual(
            run_git(
                self.repo,
                "check-ignore",
                ".polaris/archive/tasks/TASK-0001/runtime/progress.json",
            ),
            ".polaris/archive/tasks/TASK-0001/runtime/progress.json",
        )
        self.assertEqual(progress["value"]["handoff_path"], (
            ".polaris/tasks/TASK-0001/implementations/r001/handoff-001.json"
        ))
        recovered = recover(self.repo, "TASK-0001")
        self.assertTrue(recovered["live_implementation_progress"]["available"])
        recovered_paths = {
            item["path"] for item in recovered["minimum_working_set"]["entries"]
        }
        self.assertIn(
            ".polaris/tasks/TASK-0001/revisions/work-item-r001.json",
            recovered_paths,
        )

    def test_live_implementation_progress_is_queryable_and_ignored(self) -> None:
        """事件驱动进度只生成四空格 JSON，并默认排除出 Git。"""
        self.enter_implementing()
        self.dispatch_implementation()
        title = "Polaris Implement · TASK-0001 · r001 · attempt 1"
        update_implementation_progress(
            self.repo,
            "TASK-0001",
            title,
            "Pending",
            "INITIALIZE",
        )
        progress_path = self.task / "runtime" / "progress.json"
        self.assertIn('    "task_id"', progress_path.read_text(encoding="utf-8"))
        self.assertFalse(progress_path.with_name("STATUS.md").exists())
        self.assertEqual(
            run_git(
                self.repo,
                "check-ignore",
                ".polaris/tasks/TASK-0001/runtime/progress.json",
            ),
            ".polaris/tasks/TASK-0001/runtime/progress.json",
        )
        update_implementation_progress(
            self.repo,
            "TASK-0001",
            title,
            "impl-progress-session",
            "DEFINE_STEPS",
            defined_steps=[
                {"title": "Modify subject", "acceptance_ids": ["AC-01"]},
                {"title": "Run focused tests", "acceptance_ids": ["AC-01"]},
            ],
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-progress-session", "START_STEP",
            step_id="STEP-001",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-progress-session", "COMPLETE_STEP",
            step_id="STEP-001", result="Modified subject",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-progress-session", "START_STEP",
            phase="TESTING", step_id="STEP-002",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-progress-session", "ADD_CHECK",
            phase="TESTING", checks=["unit tests: 8/8 PASS"],
        )
        progress = validate_progress(self.repo, "TASK-0001")
        self.assertEqual(progress["phase"], "TESTING")
        self.assertEqual(progress["current_step_id"], "STEP-002")
        self.assertEqual(progress["implementation_steps"][0]["status"], "COMPLETED")
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
            "Pending",
            "INITIALIZE",
        )
        update_implementation_progress(
            self.repo,
            "TASK-0001",
            title,
            "impl-owner-session",
            "DEFINE_STEPS",
            defined_steps=[{"title": "Run tests", "acceptance_ids": ["AC-01"]}],
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-owner-session", "START_STEP",
            step_id="STEP-001",
        )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo,
                "TASK-0001",
                title,
                "impl-other-session",
                "ADD_CHECK",
                checks=["attempting takeover"],
            )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo,
                "TASK-0001",
                title,
                "impl-owner-session",
                "BLOCK_STEP",
                step_id="STEP-001",
                blocker="Waiting",
            )
        self.assertEqual(
            validate_progress(self.repo, "TASK-0001")["implementer_session_id"],
            "impl-owner-session",
        )

    def test_implementation_steps_are_linear_append_only_and_acceptance_bound(self) -> None:
        """步骤只能按序执行；新增只能追加，未知验收 ID 与跳步都会被拒绝。"""
        self.enter_implementing()
        self.dispatch_implementation()
        title = "Polaris Implement · TASK-0001 · r001 · attempt 1"
        update_implementation_progress(
            self.repo, "TASK-0001", title, "Pending", "INITIALIZE"
        )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo, "TASK-0001", title, "impl-linear-session", "DEFINE_STEPS",
                defined_steps=[{"title": "Unknown acceptance", "acceptance_ids": ["AC-99"]}],
            )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-linear-session", "DEFINE_STEPS",
            defined_steps=[
                {"title": "First", "acceptance_ids": ["AC-01"]},
                {"title": "Second", "acceptance_ids": ["AC-01"]},
            ],
        )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo, "TASK-0001", title, "impl-linear-session", "START_STEP",
                step_id="STEP-002",
            )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-linear-session", "SKIP_STEP",
            step_id="STEP-001", result="Already satisfied by existing code",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-linear-session", "APPEND_STEP",
            step_title="Third", acceptance_ids=["AC-01"],
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-linear-session", "START_STEP",
            step_id="STEP-002",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-linear-session", "BLOCK_STEP",
            step_id="STEP-002", blocker="Need a decision", user_action="Choose the behavior",
        )
        self.assertEqual(validate_progress(self.repo, "TASK-0001")["phase"], "BLOCKED")
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-linear-session", "RESUME_STEP",
            step_id="STEP-002",
        )
        progress = validate_progress(self.repo, "TASK-0001")
        self.assertEqual(
            [step["id"] for step in progress["implementation_steps"]],
            ["STEP-001", "STEP-002", "STEP-003"],
        )
        self.assertEqual(progress["implementation_steps"][0]["status"], "SKIPPED")

    def test_checkpoint_requires_terminal_steps_and_freezes_step_results(self) -> None:
        """未完成步骤不能进入 checkpoint，最终 artifact 必须精确冻结步骤结果。"""
        self.enter_implementing()
        handoff, reference = self.dispatch_implementation()
        title = "Polaris Implement · TASK-0001 · r001 · attempt 1"
        update_implementation_progress(
            self.repo, "TASK-0001", title, "Pending", "INITIALIZE"
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-freeze-session", "DEFINE_STEPS",
            defined_steps=[{"title": "Finish work", "acceptance_ids": ["AC-01"]}],
        )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo, "TASK-0001", title, "impl-freeze-session", "SET_PHASE",
                phase="CHECKPOINTING",
            )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-freeze-session", "START_STEP",
            step_id="STEP-001",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-freeze-session", "COMPLETE_STEP",
            step_id="STEP-001", result="Finished work",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-freeze-session", "SET_PHASE",
            phase="CHECKPOINTING",
        )
        base = run_git(self.repo, "rev-parse", "HEAD")
        (self.repo / "freeze.txt").write_text("done\n", encoding="utf-8")
        run_git(self.repo, "add", "freeze.txt")
        run_git(self.repo, "commit", "-q", "-m", "freeze implementation")
        head = run_git(self.repo, "rev-parse", "HEAD")
        implementation = read_json(template_path(ROOT, "implementation"))
        implementation.update({
            "artifact_attempt": handoff["artifact_attempt"],
            "implementer_session_id": "impl-freeze-session",
            "implementation_handoff_path": reference["path"],
            "implementation_handoff_sha256": reference["sha256"],
            "subject_base_commit": base,
            "subject_head_commit": head,
            "subject_diff_hash": subject_diff_hash(self.repo, base, head),
            "step_results": [{"id": "STEP-001", "status": "COMPLETED", "result": "wrong"}],
        })
        path = self.task / handoff["output_path"]
        write_json_atomic(path, implementation)
        with self.assertRaises(RuleFailure):
            transition(
                self.repo, "TASK-0001", "FINISH_IMPLEMENTATION",
                ["implementation=implementations/r001/attempt-001.json"],
                None, base, head, None, None, None,
            )
        implementation["step_results"] = [
            {"id": "STEP-001", "status": "COMPLETED", "result": "Finished work"}
        ]
        write_json_atomic(path, implementation)
        transition(
            self.repo, "TASK-0001", "FINISH_IMPLEMENTATION",
            ["implementation=implementations/r001/attempt-001.json"],
            None, base, head, None, None, None,
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-freeze-session", "SET_PHASE",
            phase="DOCUMENTING",
        )
        update_implementation_progress(
            self.repo, "TASK-0001", title, "impl-freeze-session", "SET_PHASE",
            phase="COMPLETED",
        )
        with self.assertRaises(RuleFailure):
            update_implementation_progress(
                self.repo, "TASK-0001", title, "impl-freeze-session", "SET_PHASE",
                phase="IMPLEMENTING",
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
        """R1 按宿主创建隔离 worker，禁止 fork 和默认 worktree。"""
        source = (ROOT / "skills" / "engineering-task" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        codex = render_skill(source, "engineering-task", host_adapter("codex"))
        claude = render_skill(source, "engineering-task", host_adapter("claude-code"))
        self.assertIn("fresh visible Codex tasks in the same local checkout", codex)
        self.assertIn("fresh non-fork `polaris-implementer`", claude)
        self.assertIn("Resume the same Implementer agent ID", claude)
        self.assertIn("Never fork the implementation conversation", source)
        self.assertIn("use a separate worktree by default", codex)

    def test_claude_workers_are_isolated_and_resume_implementer(self) -> None:
        """Claude Code 使用非 fork Reviewer，并只续接原 Implementer 做文档同步。"""
        implementer = (
            ROOT / "hosts" / "claude-code" / "agents" / "polaris-implementer.md"
        ).read_text(encoding="utf-8")
        reviewer = (
            ROOT / "hosts" / "claude-code" / "agents" / "polaris-reviewer.md"
        ).read_text(encoding="utf-8")
        source = (ROOT / "skills" / "engineering-task" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        entry_text = render_skill(
            source, "engineering-task", host_adapter("claude-code")
        )
        self.assertIn("skills:\n  - implementation\n  - documentation-sync", implementer)
        self.assertIn("resumes this same agent", implementer)
        self.assertIn("skills:\n  - adversarial-review", reviewer)
        self.assertIn("do not read or inherit implementation chat", reviewer)
        self.assertIn("non-fork `polaris-implementer` or `polaris-reviewer`", entry_text)
        self.assertIn("returned agent ID", entry_text)

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
            "Use {{skill:adversarial-review}} for <TASK>, Reviewer slot <SLOT>",
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
        self.assertIn("ambiguous identity uses manual fallback", entry_text)

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
        self.assertIn("task_layout.review_path", review_text)

    def test_review_dispatch_falls_back_without_blocking(self) -> None:
        """宿主自动派发不可用时保持 REVIEWING 并回退手动提示。"""
        entry_text = (
            ROOT / "skills" / "engineering-task" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("keep state `REVIEWING`", entry_text)
        self.assertIn("provide the exact manual new-session prompt", entry_text)
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
        self.assertIn("set `User action` to `None` while the worker is running", entry_text)

    def test_fresh_clone_recovers_the_committed_task_boundary(self) -> None:
        """Fresh Clone 经 Git 换行转换后仍可恢复已提交的阶段边界。"""
        vendor(ROOT, self.repo, False)
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", "Polaris checkpoint")
        with tempfile.TemporaryDirectory(prefix="polaris-clone-") as clone_temp:
            clone = Path(clone_temp) / "repo"
            cloned = subprocess.run(
                ["git", "clone", "-q", str(self.repo), str(clone)],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(
                cloned.returncode,
                0,
                f"git clone failed\nstdout:\n{cloned.stdout}\nstderr:\n{cloned.stderr}",
            )
            manifest = read_json(
                clone / "tools" / "polaris" / "install-manifest.json"
            )
            for item in manifest["managed_files"]:
                if item["hash_mode"] != TEXT_HASH_MODE:
                    continue
                managed_path = clone / item["path"]
                lf_content = (
                    managed_path.read_bytes()
                    .replace(b"\r\n", b"\n")
                    .replace(b"\r", b"\n")
                )
                managed_path.write_bytes(lf_content.replace(b"\n", b"\r\n"))
            completed = subprocess.run(
                [
                    sys.executable,
                    str(clone / "tools" / "polaris" / "scripts" / "recover_task.py"),
                    "TASK-0001",
                    "--repo",
                    str(clone),
                    "--json",
                ],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(
                completed.returncode,
                0,
                "recover_task.py failed\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
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
            [
                "plan=PLAN.md",
                "plan_decisions=plan-decisions.json",
                "working_set=working-set.json",
            ],
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

        implementation_intelligence = read_json(
            ROOT / "templates" / "task-sources" / "code-intelligence-record.json"
        )
        implementation_intelligence.update(
            {
                "stage": "IMPLEMENTATION",
                "artifact_attempt": 1,
                "target": {
                    "base_commit": base,
                    "head_commit": head,
                    "diff_hash": diff_hash,
                },
            }
        )
        implementation_intelligence_result = record_code_intelligence(
            self.repo, "TASK-0001", implementation_intelligence, ROOT
        )
        implementation_intelligence_path = Path(
            implementation_intelligence_result["path"]
        )
        implementation_path = self.task / "implementations" / "r001" / "attempt-001.json"
        implementation = self.implementation_value(base, head, "impl-session")
        implementation["code_intelligence"] = {
            "path": implementation_intelligence_path.relative_to(self.task).as_posix(),
            "sha256": file_sha256(implementation_intelligence_path),
        }
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
        final_diff_hash = subject_diff_hash(self.repo, base, final_head)
        documentation_intelligence = read_json(
            ROOT / "templates" / "task-sources" / "code-intelligence-record.json"
        )
        documentation_intelligence.update(
            {
                "stage": "DOCUMENTATION_SYNC",
                "artifact_attempt": 1,
                "target": {
                    "base_commit": base,
                    "head_commit": final_head,
                    "diff_hash": final_diff_hash,
                },
            }
        )
        documentation_intelligence_result = record_code_intelligence(
            self.repo, "TASK-0001", documentation_intelligence, ROOT
        )
        documentation_intelligence_path = Path(
            documentation_intelligence_result["path"]
        )
        knowledge_path = self.task / "knowledge" / "r001" / "knowledge-delta-001.json"
        knowledge = self.knowledge_value(1, base, final_head)
        knowledge["code_intelligence"] = {
            "path": documentation_intelligence_path.relative_to(self.task).as_posix(),
            "sha256": file_sha256(documentation_intelligence_path),
        }
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
        review_handoff_result = build_review_handoff(
            self.repo, "TASK-0001", "impl-session", "fresh_session"
        )
        review_handoff = read_json(Path(review_handoff_result["path"]))
        self.assertTrue(
            {
                "implementation_code_intelligence",
                "documentation_code_intelligence",
            }.issubset({item["role"] for item in review_handoff["package"]})
        )
        transition(
            self.repo,
            "TASK-0001",
            "START_REVIEW",
            [
                "review_handoff="
                + Path(review_handoff_result["path"]).relative_to(self.task).as_posix()
            ],
            None,
            None,
            None,
            None,
            None,
            None,
        )
        review_path = self.task / "reviews" / "r001" / "review-001.json"
        review = read_json(template_path(ROOT, "review"))
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
        validation = read_json(template_path(ROOT, "validation"))
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
        result = read_json(template_path(ROOT, "result"))
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

    def test_review_handoff_survives_physical_root_relocation(self) -> None:
        """Reviewer 冻结包使用逻辑任务路径，整体搬迁不改变其内容或校验结果。"""
        self.test_implementation_and_final_documentation_subjects_are_bound()
        handoff, _ = self.start_review()
        self.assertIn(
            ".polaris/tasks/TASK-0001/PLAN.md",
            {item["path"] for item in handoff["package"]},
        )
        old_directory = self.task
        relocated = self.repo / ".polaris" / "archive" / "tasks" / "TASK-0001"
        relocated.parent.mkdir(parents=True)
        shutil.move(str(old_directory), str(relocated))
        registry_path = self.repo / ".polaris" / "task-locations.json"
        registry = read_json(registry_path)
        registry["locations"][0]["path"] = ".polaris/archive/tasks/TASK-0001"
        write_json_atomic(registry_path, registry)

        self.assertEqual(validate_project(self.repo)["active_tasks"], 1)
        self.assertEqual(validate(self.repo, "TASK-0001")["state"], "REVIEWING")

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
        validation = read_json(template_path(ROOT, "validation"))
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
        response = read_json(template_path(ROOT, "review_response"))
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
            [
                "plan=PLAN.md",
                "plan_decisions=plan-decisions.json",
                "working_set=working-set.json",
            ],
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
        self.assertIn(".polaris/project-index.json", paths)
        self.assertIn(
            f".polaris/explorations/{recorded['exploration_id']}.json", paths
        )


if __name__ == "__main__":
    unittest.main()
