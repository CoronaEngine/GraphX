from __future__ import annotations

import copy
import importlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from init_project import initialize as init_project  # noqa: E402
from init_task import initialize as init_task  # noqa: E402
from migrate_project import migrate as migrate_project  # noqa: E402
from new_revision import create as new_revision  # noqa: E402
from transition_task import transition  # noqa: E402
from internal.code_intelligence_protocol import (  # noqa: E402
    _project_marker_path,
    load_providers,
    record,
    select_provider,
    validate_record_value,
)
from internal.host_adapters import discover_skills, load_host_adapters, render_skill  # noqa: E402
from internal.polaris_core import (  # noqa: E402
    InputFailure,
    RuleFailure,
    file_sha256,
    subject_diff_hash,
    write_json_atomic,
    write_text_atomic,
)
from vendor_project import vendor  # noqa: E402


def completed(
    stdout: str, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def healthy_status(project: Path) -> str:
    return json.dumps(
        {
            "initialized": True,
            "projectPath": str(project),
            "pendingChanges": {"added": 0, "modified": 0, "removed": 0},
            "worktreeMismatch": None,
            "index": {
                "state": "complete",
                "pendingRefs": 0,
                "reindexRecommended": False,
            },
        }
    )


def validated_disposable_codegraph_repo(repo: Path, fixture_root: str) -> Path:
    """Return only the resolved unittest fixture repo outside this workspace."""
    temporary_repo = repo.resolve()
    if temporary_repo != Path(fixture_root).resolve():
        raise AssertionError("real CLI target must exactly match the temporary fixture repo")
    try:
        temporary_repo.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise AssertionError("real CLI target must not be inside the workspace")
    try:
        temporary_repo.relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError as error:
        raise AssertionError("real CLI target must be inside the system temporary directory") from error
    return temporary_repo


class CodeGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="polaris-codegraph-")
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "polaris@test.local"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Polaris Test"],
            cwd=self.repo,
            check=True,
        )
        init_project(self.repo, "codegraph-test")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "initialize test project"],
            cwd=self.repo,
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_managed_surfaces_only_name_the_official_codegraph(self) -> None:
        """Current product surfaces retain only the official CodeGraph identity."""
        official = "https://github.com/" + "colbymchenry/" + "codegraph"
        retired_names = {
            "codegraph_" + "symbol_" + "search",
            "codegraph_" + "get_" + "ai_" + "context",
            "codegraph_" + "get_" + "dependency_" + "graph",
            "codegraph_" + "get_" + "call_" + "graph",
            "codegraph_" + "analyze_" + "impact",
            "codegraph_" + "pr_" + "context",
            "codegraph_" + "index_" + "files",
            "codegraph_" + "reindex_" + "workspace",
            "refresh_" + "files",
            "refresh_" + "workspace",
            "plan_" + "refresh",
        }
        managed_roots = [
            ROOT / "hosts",
            ROOT / "providers",
            ROOT / "schemas",
            ROOT / "scripts",
            ROOT / "skills",
            ROOT / "templates",
            ROOT / "tests",
        ]
        managed_paths = [
            path
            for root in managed_roots
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path != ROOT / "schemas" / "code-intelligence-record-v1.schema.json"
        ]
        managed_paths.extend([
            ROOT / "README.md",
            ROOT / "README.zh-CN.md",
            ROOT / "docs" / "USAGE.md",
            ROOT / "plan.md",
        ])
        for path in managed_paths:
            text = path.read_text(encoding="utf-8")
            for retired in retired_names:
                self.assertNotIn(retired, text, path.relative_to(ROOT).as_posix())
        for path in [
            ROOT / "providers" / "code-intelligence" / "codegraph.json",
            ROOT / "README.md",
            ROOT / "README.zh-CN.md",
            ROOT / "docs" / "USAGE.md",
            ROOT / "plan.md",
        ]:
            self.assertIn(official, path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix())
        for path in [ROOT / "README.md", ROOT / "README.zh-CN.md"]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("0.1.20", text, path.relative_to(ROOT).as_posix())
            self.assertIn("0.1.3", text, path.relative_to(ROOT).as_posix())

    def test_authority_surfaces_publish_workflow_013(self) -> None:
        for path in [
            ROOT / "README.md",
            ROOT / "README.zh-CN.md",
            ROOT / "docs" / "USAGE.md",
            ROOT / "plan.md",
        ]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("0.1.20", text, path.relative_to(ROOT).as_posix())
            self.assertIn("0.1.3", text, path.relative_to(ROOT).as_posix())

    def test_readmes_keep_codegraph_operational_boundaries(self) -> None:
        """User-facing authorities retain the source-fallback and ownership boundaries."""
        shared_anchors = [
            "codegraph install",
            "codegraph init",
            ".codegraph/",
            "codegraph sync",
            "READ_SOURCE",
            "INSPECT_GIT_DIFF",
            "SEARCH_SOURCE",
            "Validation",
            "daemon",
        ]
        localized_anchors = {
            ROOT / "README.md": [
                "repository owner, not Polaris",
                "one bounded",
                "reconfigures",
                "workflow gate",
                "Validation remains graph-free",
            ],
            ROOT / "README.zh-CN.md": [
                "仓库所有者（而不是 Polaris）",
                "至多执行一次有界",
                "重新配置",
                "Workflow 门禁",
                "Validation 不调用 CodeGraph",
            ],
        }
        for path, anchors in localized_anchors.items():
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                for anchor in [*shared_anchors, *anchors]:
                    self.assertIn(anchor, text, f"{path.name}: {anchor}")
                mutated = text.replace("codegraph sync", "codegraph-sync", 1)
                with self.assertRaises(AssertionError):
                    self.assertIn("codegraph sync", mutated, path.name)

    def test_stage_surfaces_do_not_require_unused_provider_records(self) -> None:
        """未执行 Provider 操作的阶段明确省略 record，不制造 UNAVAILABLE 噪声。"""
        for relative in [
            "skills/architecture-planning/SKILL.md",
            "skills/implementation/SKILL.md",
            "skills/documentation-sync/SKILL.md",
            "skills/adversarial-review/SKILL.md",
            "skills/code-intelligence/SKILL.md",
        ]:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("omit the Code Intelligence record", text, relative)

    def adapter_functions(self) -> tuple[object, object]:
        adapter_path = SCRIPTS / "internal" / "codegraph_adapter.py"
        self.assertTrue(
            adapter_path.is_file(),
            "CodeGraph adapter must exist before it can inspect status",
        )
        module = importlib.import_module("internal.codegraph_adapter")
        return module.inspect_status, module.sync_if_needed

    def adapter_module(self) -> object:
        return importlib.import_module("internal.codegraph_adapter")

    def classify_response(
        self, response: str, *, checked_at: str = "2026-08-18T00:00:00Z"
    ) -> dict[str, object]:
        classifier = getattr(self.adapter_module(), "classify_response", None)
        self.assertTrue(callable(classifier), "CodeGraph response classifier must exist")
        return classifier(self.repo, response, checked_at=checked_at)

    def v2_record(self) -> dict[str, object]:
        value = json.loads(
            (ROOT / "tests/fixtures/code-intelligence-record-v2.json").read_text(
                encoding="utf-8"
            )
        )
        value["target"]["base_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            capture_output=True,
            check=True,
            encoding="utf-8",
            text=True,
        ).stdout.strip()
        return value

    @staticmethod
    def add_explore_response_evidence(value: dict[str, object]) -> None:
        """Make a fixture auditable as one successful CodeGraph explore response."""
        value["provider"] = {
            "id": "codegraph",
            "descriptor_version": 2,
            "transport": "mcp",
            "available_operations": ["explore"],
        }
        value["queries"] = [{
            "id": "CIQ-001",
            "operation": "explore",
            "purpose": "inspect CodeGraph response freshness",
            "status": "SUCCESS",
            "summary": "CodeGraph response",
            "symbols": [],
            "response_sha256": "0" * 64,
            "error": None,
        }]
        value["freshness"]["response_sha256"] = "0" * 64

    def initialize_task(self) -> None:
        init_task(self.repo, "TASK-0001", "R1")

    def qualify_task(self) -> None:
        self.initialize_task()
        path = self.repo / ".polaris/tasks/TASK-0001/revisions/work-item-r001.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update({
            "title": "CodeGraph proxy task",
            "goal": "Exercise the bounded proxy",
            "motivation": "Keep graph evidence freshness-aware",
        })
        value["scope"]["in"] = ["scripts"]
        value["acceptance"][0].update({
            "statement": "The proxy emits a freshness envelope",
            "evidence": "proxy bundle",
        })
        value["implementation_dispatch"]["authorized"] = True
        value["review_dispatch"]["authorized"] = True
        write_json_atomic(path, value)
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

    def proxy_module(self) -> object:
        return importlib.import_module("internal.code_intelligence_proxy")

    def record_current_v3_fixture(self) -> tuple[dict[str, object], dict[str, object]]:
        self.qualify_task()
        (self.repo / ".codegraph").mkdir()
        source = self.repo / "src/a.py"
        source.parent.mkdir()
        source.write_text("class A:\n    pass\n", encoding="utf-8")
        proxy = self.proxy_module()
        responses = [
            completed(healthy_status(self.repo)),
            completed("A is defined in src/a.py\n"),
            completed(healthy_status(self.repo)),
        ]

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return responses.pop(0)

        with mock.patch("internal.code_intelligence_proxy.shutil.which", return_value="/bin/codegraph"):
            query = proxy.execute_proxy_query(
                self.repo,
                "TASK-0001",
                "PLANNING",
                "CIQ-001",
                "locate A",
                "symbol A",
                False,
                runner=runner,
            )
        protocol = importlib.import_module("internal.code_intelligence_protocol")
        result = protocol.record_proxy_bundle(
            self.repo,
            "TASK-0001",
            query["bundle_path"],
            {
                "summary": "Located the affected symbol.",
                "symbols": [{"path": "src/a.py", "line": 1, "name": "A"}],
                "source_fallbacks": [],
            },
            ROOT,
        )
        recorded = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        return recorded, query

    def test_proxy_stage_context_uses_record_name_and_sequential_query_ids(self) -> None:
        self.qualify_task()
        proxy = self.proxy_module()

        context = proxy.resolve_stage_context(self.repo, "TASK-0001", "PLANNING")

        self.assertEqual(context["work_item_revision"], 1)
        self.assertEqual(context["artifact_attempt"], None)
        self.assertEqual(context["reviewer_slot"], None)
        self.assertEqual(context["record_name"], "planning")
        expected = (
            self.repo
            / ".polaris/tasks/TASK-0001/runtime/code-intelligence/planning/CIQ-001.json"
        )
        self.assertEqual(
            proxy.proxy_bundle_path(self.repo, "TASK-0001", context, "CIQ-001"),
            expected,
        )
        with self.assertRaisesRegex(InputFailure, "next sequential"):
            proxy.proxy_bundle_path(self.repo, "TASK-0001", context, "CIQ-002")
        with self.assertRaisesRegex(InputFailure, "invalid CodeGraph query id"):
            proxy.proxy_bundle_path(self.repo, "TASK-0001", context, "CIQ-000")

    def test_proxy_stage_context_binds_attempt_subject_and_review_slot(self) -> None:
        self.qualify_task()
        proxy = self.proxy_module()
        task = self.repo / ".polaris/tasks/TASK-0001"
        state_path = task / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
        implementation_handoff = {
            "artifact_attempt": 2,
            "subject_base_commit": base,
        }
        state["status"] = "IMPLEMENTING"
        write_json_atomic(state_path, state)
        with mock.patch(
            "internal.code_intelligence_proxy.validate_implementation_handoff",
            return_value=(implementation_handoff, {"path": "handoff.json", "sha256": "0" * 64}),
        ):
            implementation = proxy.resolve_stage_context(
                self.repo, "TASK-0001", "IMPLEMENTATION"
            )
            documentation = proxy.resolve_stage_context(
                self.repo, "TASK-0001", "DOCUMENTATION_SYNC"
            )
        self.assertEqual(implementation["record_name"], "implementation-002")
        self.assertEqual(documentation["record_name"], "documentation-sync-002")
        self.assertEqual(implementation["target"], {
            "base_commit": base,
            "head_commit": base,
            "diff_hash": subject_diff_hash(self.repo, base, base),
        })

        state["status"] = "REVIEWING"
        write_json_atomic(state_path, state)
        review_handoff = {
            "artifact_attempt": 2,
            "subject_base_commit": base,
            "subject_head_commit": base,
            "subject_diff_hash": subject_diff_hash(self.repo, base, base),
        }
        with mock.patch(
            "internal.code_intelligence_proxy.validate_review_handoff",
            return_value=review_handoff,
        ):
            review = proxy.resolve_stage_context(self.repo, "TASK-0001", "REVIEW")
        self.assertEqual(review["record_name"], "review-002-slot-1")
        state["artifacts"]["review"] = {"path": "review.json", "sha256": "0" * 64}
        write_json_atomic(state_path, state)
        with mock.patch(
            "internal.code_intelligence_proxy.validate_review_handoff",
            return_value=review_handoff,
        ):
            review_2 = proxy.resolve_stage_context(self.repo, "TASK-0001", "REVIEW")
        self.assertEqual(review_2["record_name"], "review-002-slot-2")

        with self.assertRaisesRegex(RuleFailure, "inconsistent with task status"):
            proxy.resolve_stage_context(self.repo, "TASK-0001", "PLANNING")

    def test_proxy_window_requires_clean_pre_and_post_status_for_current(self) -> None:
        self.qualify_task()
        (self.repo / ".codegraph").mkdir()
        proxy = self.proxy_module()
        calls: list[tuple[list[str], dict[str, object]]] = []
        responses = [
            completed(healthy_status(self.repo)),
            completed("graph bytes\n"),
            completed(healthy_status(self.repo)),
        ]

        def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            if not responses:
                raise AssertionError(f"unexpected extra CodeGraph call: {command}")
            return responses.pop(0)

        with mock.patch("internal.code_intelligence_proxy.shutil.which", return_value="/bin/codegraph"):
            result = proxy.execute_proxy_query(
                self.repo,
                "TASK-0001",
                "PLANNING",
                "CIQ-001",
                "locate affected symbols",
                "symbol A",
                False,
                runner=runner,
            )

        bundle = result["bundle"]
        self.assertEqual(bundle["delivery"]["state"], "CURRENT")
        self.assertEqual(bundle["delivery"]["usage"], "NON_AUTHORITATIVE_CONTEXT")
        self.assertEqual(bundle["delivery"]["record_status"], "CURRENT_AT_CHECK")
        self.assertEqual([call[0][1] for call in calls], ["status", "explore", "status"])
        self.assertTrue(all(Path(call[1]["cwd"]).resolve() == self.repo.resolve() for call in calls))
        self.assertEqual(result["response"], "graph bytes\n")
        self.assertTrue(result["envelope"].startswith("[POLARIS_CODEGRAPH_FRESHNESS]\n"))
        self.assertEqual(
            hashlib.sha256(
                (self.repo / ".polaris/tasks/TASK-0001/runtime/code-intelligence/planning/CIQ-001.response.txt").read_bytes()
            ).hexdigest(),
            bundle["query"]["response_sha256"],
        )

    def test_proxy_window_downgrades_pending_unknown_and_unavailable_states(self) -> None:
        cases = [
            ("pending", "STALE", 3),
            ("malformed", "UNKNOWN", 1),
            ("missing_marker", "UNAVAILABLE", 0),
        ]
        for index, (case, expected_state, expected_calls) in enumerate(cases, start=1):
            with self.subTest(case=case):
                if index > 1:
                    self.tearDown()
                    self.setUp()
                self.qualify_task()
                proxy = self.proxy_module()
                query_id = "CIQ-001"
                calls: list[list[str]] = []
                status = json.loads(healthy_status(self.repo))
                if case == "pending":
                    status["pendingChanges"]["modified"] = 1
                    responses = [
                        completed(json.dumps(status)),
                        completed("graph bytes\n"),
                        completed(json.dumps(status)),
                    ]
                else:
                    responses = [completed("not-json\n")]
                if case != "missing_marker":
                    (self.repo / ".codegraph").mkdir()

                def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return responses.pop(0)

                with mock.patch("internal.code_intelligence_proxy.shutil.which", return_value="/bin/codegraph"):
                    result = proxy.execute_proxy_query(
                        self.repo,
                        "TASK-0001",
                        "PLANNING",
                        query_id,
                        "inspect freshness",
                        "symbol A",
                        False,
                        runner=runner,
                    )
                self.assertEqual(result["bundle"]["delivery"]["state"], expected_state)
                self.assertEqual(len(calls), expected_calls)
                if expected_state == "UNAVAILABLE":
                    self.assertIsNone(result["response"])

    def test_proxy_window_syncs_once_and_rechecks_after_the_query(self) -> None:
        self.qualify_task()
        (self.repo / ".codegraph").mkdir()
        proxy = self.proxy_module()
        pending = json.loads(healthy_status(self.repo))
        pending["pendingChanges"]["modified"] = 1
        responses = [
            completed(json.dumps(pending)),
            completed("synced\n"),
            completed(healthy_status(self.repo)),
            completed("graph bytes\n"),
            completed(healthy_status(self.repo)),
        ]
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return responses.pop(0)

        with mock.patch("internal.code_intelligence_proxy.shutil.which", return_value="/bin/codegraph"):
            result = proxy.execute_proxy_query(
                self.repo,
                "TASK-0001",
                "PLANNING",
                "CIQ-001",
                "refresh one query window",
                "symbol A",
                True,
                runner=runner,
            )

        self.assertEqual(
            [command[1] for command in calls],
            ["status", "sync", "status", "explore", "status"],
        )
        self.assertEqual(result["bundle"]["sync"]["status"], "SUCCESS")
        self.assertEqual(result["bundle"]["delivery"]["state"], "CURRENT")
        self.assertEqual(
            result["bundle"]["delivery"]["pending_changes"],
            {"added": 0, "modified": 0, "removed": 0},
        )

    def test_proxy_window_never_promotes_failed_or_post_stale_queries(self) -> None:
        cases = [
            ("explore_failed", "UNKNOWN", ["status", "explore"]),
            ("post_pending", "STALE", ["status", "explore", "status"]),
        ]
        for index, (case, expected_state, expected_calls) in enumerate(cases, start=1):
            with self.subTest(case=case):
                if index > 1:
                    self.tearDown()
                    self.setUp()
                self.qualify_task()
                (self.repo / ".codegraph").mkdir()
                proxy = self.proxy_module()
                post = json.loads(healthy_status(self.repo))
                post["pendingChanges"]["added"] = 1
                responses = (
                    [completed(healthy_status(self.repo)), completed("", 1, "failed")]
                    if case == "explore_failed"
                    else [
                        completed(healthy_status(self.repo)),
                        completed("graph bytes\n"),
                        completed(json.dumps(post)),
                    ]
                )
                calls: list[list[str]] = []

                def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return responses.pop(0)

                with mock.patch("internal.code_intelligence_proxy.shutil.which", return_value="/bin/codegraph"):
                    result = proxy.execute_proxy_query(
                        self.repo,
                        "TASK-0001",
                        "PLANNING",
                        "CIQ-001",
                        "verify failure handling",
                        "symbol A",
                        False,
                        runner=runner,
                    )
                self.assertEqual(result["bundle"]["delivery"]["state"], expected_state)
                self.assertEqual([command[1] for command in calls], expected_calls)
                if case == "explore_failed":
                    self.assertIsNone(result["response"])
                else:
                    self.assertEqual(
                        result["bundle"]["delivery"]["reason"], "PENDING_CHANGES"
                    )

    def test_proxy_window_classifies_banners_and_discards_unsafe_paths(self) -> None:
        partial = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/widget.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
"""
        cases = [
            ("partial", partial, "STALE", True),
            ("suspicious", "warning: graph may be stale\n", "UNKNOWN", True),
            ("unsafe", partial.replace("src/widget.py", "../escape.py"), "UNKNOWN", False),
        ]
        for index, (case, response, expected_state, retained) in enumerate(cases, start=1):
            with self.subTest(case=case):
                if index > 1:
                    self.tearDown()
                    self.setUp()
                self.qualify_task()
                (self.repo / ".codegraph").mkdir()
                source = self.repo / "src/widget.py"
                source.parent.mkdir()
                source.write_text("value = 1\n", encoding="utf-8")
                proxy = self.proxy_module()
                responses = [
                    completed(healthy_status(self.repo)),
                    completed(response),
                    completed(healthy_status(self.repo)),
                ]

                def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                    return responses.pop(0)

                with mock.patch("internal.code_intelligence_proxy.shutil.which", return_value="/bin/codegraph"):
                    result = proxy.execute_proxy_query(
                        self.repo,
                        "TASK-0001",
                        "PLANNING",
                        "CIQ-001",
                        "classify response",
                        "symbol A",
                        False,
                        runner=runner,
                    )
                self.assertEqual(result["bundle"]["delivery"]["state"], expected_state)
                self.assertEqual(result["response"] is not None, retained)
                self.assertEqual(result["bundle"]["response_path"] is not None, retained)

    def test_proxy_window_rejects_cross_project_and_runtime_symlink_evidence(self) -> None:
        self.qualify_task()
        (self.repo / ".codegraph").mkdir()
        proxy = self.proxy_module()
        other = self.repo / "other"
        other.mkdir()
        wrong = json.loads(healthy_status(self.repo))
        wrong["projectPath"] = str(other)
        calls: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return completed(json.dumps(wrong))

        with mock.patch("internal.code_intelligence_proxy.shutil.which", return_value="/bin/codegraph"):
            result = proxy.execute_proxy_query(
                self.repo,
                "TASK-0001",
                "PLANNING",
                "CIQ-001",
                "reject cross-project status",
                "symbol A",
                False,
                runner=runner,
            )
        self.assertEqual([command[1] for command in calls], ["status"])
        self.assertEqual(result["bundle"]["delivery"]["state"], "UNKNOWN")
        self.assertEqual(result["bundle"]["delivery"]["reason"], "PROJECT_MISMATCH")

        self.tearDown()
        self.setUp()
        self.qualify_task()
        runtime = self.repo / ".polaris/tasks/TASK-0001/runtime"
        shutil.rmtree(runtime)
        runtime.symlink_to(self.repo / "escaped-runtime", target_is_directory=True)
        context = proxy.resolve_stage_context(self.repo, "TASK-0001", "PLANNING")
        with self.assertRaisesRegex(RuleFailure, "crosses a symlink"):
            proxy.proxy_bundle_path(self.repo, "TASK-0001", context, "CIQ-001")

    def test_proxy_window_disabled_policy_or_missing_cli_never_calls_provider(self) -> None:
        for index, case in enumerate(("disabled", "missing_cli"), start=1):
            with self.subTest(case=case):
                if index > 1:
                    self.tearDown()
                    self.setUp()
                self.qualify_task()
                (self.repo / ".codegraph").mkdir()
                if case == "disabled":
                    config_path = self.repo / ".polaris/code-intelligence.json"
                    config = json.loads(
                        (ROOT / "templates/code-intelligence.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    config["mode"] = "disabled"
                    write_json_atomic(config_path, config)
                proxy = self.proxy_module()

                def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                    raise AssertionError("disabled or unavailable CodeGraph must not run")

                executable = "/bin/codegraph" if case == "disabled" else None
                with mock.patch(
                    "internal.code_intelligence_proxy.shutil.which",
                    return_value=executable,
                ):
                    result = proxy.execute_proxy_query(
                        self.repo,
                        "TASK-0001",
                        "PLANNING",
                        "CIQ-001",
                        "verify activation gate",
                        "symbol A",
                        True,
                        runner=runner,
                    )
                self.assertEqual(result["bundle"]["delivery"]["state"], "UNAVAILABLE")
                self.assertEqual(result["bundle"]["query"]["status"], "UNAVAILABLE")
                self.assertIsNone(result["response"])

    def test_proxy_envelope_is_finite_and_truncates_diagnostics(self) -> None:
        self.qualify_task()
        proxy = self.proxy_module()
        context = proxy.resolve_stage_context(self.repo, "TASK-0001", "PLANNING")
        bundle = {
            "task_context": context,
            "query": {"id": "CIQ-001"},
            "delivery": {
                "state": "UNKNOWN",
                "record_status": "NOT_VERIFIED",
                "reason": "STATUS_UNREADABLE",
                "checked_at": "2026-08-19T00:00:00Z",
                "pending_changes": {"added": 0, "modified": 0, "removed": 0},
                "usage": "NAVIGATION_ONLY",
                "required_fallback": "SEARCH_SOURCE",
                "error": "x" * 300,
            },
        }

        envelope = proxy.render_freshness_envelope(bundle)

        self.assertTrue(envelope.startswith("[POLARIS_CODEGRAPH_FRESHNESS]\n"))
        self.assertTrue(envelope.endswith("[/POLARIS_CODEGRAPH_FRESHNESS]\n"))
        error_line = next(line for line in envelope.splitlines() if line.startswith("error: "))
        self.assertEqual(len(error_line.removeprefix("error: ")), 240)

    def test_mcp_server_initializes_and_lists_one_proxy_tool(self) -> None:
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        completed_process = subprocess.run(
            [
                sys.executable,
                SCRIPTS / "code_intelligence_mcp.py",
                "--repo",
                self.repo,
            ],
            input="".join(json.dumps(item) + "\n" for item in messages),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed_process.returncode, 0, completed_process.stderr)
        responses = [json.loads(line) for line in completed_process.stdout.splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
        self.assertEqual(
            responses[0]["result"]["capabilities"],
            {"tools": {"listChanged": False}},
        )
        tools = responses[1]["result"]["tools"]
        self.assertEqual([item["name"] for item in tools], ["polaris_codegraph_explore"])
        self.assertNotIn("repository", tools[0]["inputSchema"]["properties"])
        self.assertEqual(completed_process.stderr, "")

    def test_mcp_server_returns_envelope_before_graph_and_preserves_bundle(self) -> None:
        module = importlib.import_module("code_intelligence_mcp")
        server = module.McpServer(self.repo)
        initialized = server.handle({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        })
        self.assertIn("result", initialized)
        self.assertIsNone(server.handle({
            "jsonrpc": "2.0", "method": "notifications/initialized"
        }))
        bundle = {
            "delivery": {"state": "STALE"},
            "query": {"id": "CIQ-001"},
        }
        proxy_result = {
            "bundle": bundle,
            "bundle_path": self.repo / "bundle.json",
            "response": "graph bytes\n",
            "envelope": "[POLARIS_CODEGRAPH_FRESHNESS]\nstate: STALE\n[/POLARIS_CODEGRAPH_FRESHNESS]\n",
        }
        request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "polaris_codegraph_explore",
                "arguments": {
                    "task_id": "TASK-0001",
                    "stage": "PLANNING",
                    "query_id": "CIQ-001",
                    "purpose": "locate symbols",
                    "query": "symbol A",
                    "sync_if_needed": False,
                },
            },
        }
        with mock.patch(
            "code_intelligence_mcp.execute_proxy_query", return_value=proxy_result
        ):
            response = server.handle(request)

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["content"][0]["text"], proxy_result["envelope"])
        self.assertEqual(result["content"][1]["text"], "graph bytes\n")
        self.assertEqual(result["structuredContent"], {"bundle": bundle})

        proxy_result["response"] = None
        with mock.patch(
            "code_intelligence_mcp.execute_proxy_query", return_value=proxy_result
        ):
            no_graph = server.handle({**request, "id": 3})
        self.assertFalse(no_graph["result"]["isError"])
        self.assertEqual(len(no_graph["result"]["content"]), 1)

    def test_mcp_server_rejects_lifecycle_tool_and_input_errors(self) -> None:
        module = importlib.import_module("code_intelligence_mcp")
        server = module.McpServer(self.repo)
        before = server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}
        })
        self.assertEqual(before["error"]["code"], -32600)
        server.handle({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        })
        server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        unknown = server.handle({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "codegraph_explore", "arguments": {}},
        })
        self.assertEqual(unknown["error"]["code"], -32602)
        invalid = server.handle({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "polaris_codegraph_explore",
                "arguments": {
                    "task_id": "TASK-0001",
                    "stage": "INVALID",
                    "query_id": "CIQ-000",
                    "purpose": "locate symbols",
                    "query": "symbol A",
                    "sync_if_needed": False,
                },
            },
        })
        self.assertTrue(invalid["result"]["isError"])
        self.assertNotIn("structuredContent", invalid["result"])

    def test_mcp_server_emits_jsonrpc_parse_and_method_errors_one_per_line(self) -> None:
        transcript = "{bad json\n" + "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "unknown", "params": {}}),
        ]) + "\n"
        completed_process = subprocess.run(
            [sys.executable, SCRIPTS / "code_intelligence_mcp.py", "--repo", self.repo],
            input=transcript,
            text=True,
            capture_output=True,
            check=False,
        )

        responses = [json.loads(line) for line in completed_process.stdout.splitlines()]
        self.assertEqual([item["error"]["code"] for item in responses], [-32700, -32602, -32601])
        self.assertTrue(all("\n" not in line for line in completed_process.stdout.splitlines()))

    def test_v3_record_projects_exact_proxy_bundle(self) -> None:
        recorded, query = self.record_current_v3_fixture()
        self.assertEqual(recorded["record_version"], 3)
        self.assertEqual(recorded["proxy"]["server_id"], "polaris-codegraph")
        self.assertEqual(
            recorded["query_window"]["pre_status"]["pending_changes"],
            {"added": 0, "modified": 0, "removed": 0},
        )
        self.assertEqual(recorded["delivery"]["state"], "CURRENT")
        self.assertEqual(
            recorded["proxy"]["evidence_bundle_sha256"],
            file_sha256(query["bundle_path"]),
        )
        self.assertEqual(recorded["query"]["symbols"][0]["path"], "src/a.py")

    def test_v3_record_rejects_mutated_window_identity_and_fallbacks(self) -> None:
        recorded, _query = self.record_current_v3_fixture()
        protocol = importlib.import_module("internal.code_intelligence_protocol")

        def current_to_stale(value: dict[str, object]) -> None:
            pending = {
                "scope": "INDEX",
                "path": None,
                "reason": "PENDING_CHANGES",
                "fallback": "SEARCH_SOURCE",
                "observed_sha256": None,
            }
            value["query_window"]["post_query_status"]["pending_changes"]["added"] = 1
            value["query_window"]["post_query_status"]["needs_sync"] = True
            value["delivery"].update({
                "state": "STALE",
                "record_status": "INDEX_STALE",
                "reason": "PENDING_CHANGES",
                "usage": "NAVIGATION_ONLY",
                "required_fallback": "SEARCH_SOURCE",
                "stale_points": [pending],
                "pending_changes": {"added": 1, "modified": 0, "removed": 0},
            })

        mutations: list[tuple[str, object]] = [
            (
                "current pending",
                lambda value: value["delivery"]["pending_changes"].update(
                    {"modified": 1}
                ),
            ),
            (
                "missing post status",
                lambda value: value["query_window"].update(
                    {"post_query_status": None}
                ),
            ),
            (
                "response hash mismatch",
                lambda value: value["query_window"]["response_classification"].update(
                    {"response_sha256": "1" * 64}
                ),
            ),
            (
                "bundle hash shape",
                lambda value: value["proxy"].update(
                    {"evidence_bundle_sha256": "short"}
                ),
            ),
            (
                "repository mismatch",
                lambda value: value["repository"].update(
                    {"project_id": "another-project"}
                ),
            ),
            (
                "delivery usage",
                lambda value: value["delivery"].update(
                    {"usage": "NAVIGATION_ONLY"}
                ),
            ),
            (
                "sync without post-sync",
                lambda value: value["query_window"].update({
                    "sync": {
                        "status": "SUCCESS",
                        "response_sha256": "2" * 64,
                        "error": None,
                    },
                    "post_sync_status": None,
                }),
            ),
        ]
        for name, mutation in mutations:
            with self.subTest(name=name):
                value = copy.deepcopy(recorded)
                mutation(value)
                with self.assertRaises(RuleFailure):
                    protocol.validate_record_value(self.repo, "TASK-0001", value, ROOT)

        stale_without_fallback = copy.deepcopy(recorded)
        current_to_stale(stale_without_fallback)
        with self.assertRaisesRegex(RuleFailure, "source fallback"):
            protocol.validate_record_value(
                self.repo, "TASK-0001", stale_without_fallback, ROOT
            )

        unsafe_fallback = copy.deepcopy(stale_without_fallback)
        unsafe_fallback["source_fallbacks"] = [{
            "action": "SEARCH_SOURCE",
            "path": None,
            "observed_sha256": None,
            "base_commit": None,
            "head_commit": None,
            "diff_hash": None,
            "purpose": "inspect current repository source",
            "result_paths": [{
                "path": "../outside.py",
                "observed_sha256": "0" * 64,
            }],
        }]
        with self.assertRaises(RuleFailure):
            protocol.validate_record_value(
                self.repo, "TASK-0001", unsafe_fallback, ROOT
            )

        with self.assertRaisesRegex(InputFailure, "record_version 3"):
            record(self.repo, "TASK-0001", self.v2_record(), ROOT)

    def test_v3_record_preserves_stale_unknown_and_unavailable_restrictions(self) -> None:
        cases = [
            ("stale", "STALE", "USED"),
            ("unknown", "UNKNOWN", "FAILED"),
            ("unavailable", "UNAVAILABLE", "UNAVAILABLE"),
        ]
        for index, (case, delivery_state, record_status) in enumerate(cases, start=1):
            with self.subTest(case=case):
                if index > 1:
                    self.tearDown()
                    self.setUp()
                self.qualify_task()
                source = self.repo / "src/a.py"
                source.parent.mkdir()
                source.write_text("class A:\n    pass\n", encoding="utf-8")
                if case != "unavailable":
                    (self.repo / ".codegraph").mkdir()
                if case == "stale":
                    pending = json.loads(healthy_status(self.repo))
                    pending["pendingChanges"]["modified"] = 1
                    responses = [
                        completed(json.dumps(pending)),
                        completed("A is defined in src/a.py\n"),
                        completed(json.dumps(pending)),
                    ]
                elif case == "unknown":
                    responses = [completed("not-json\n")]
                else:
                    responses = []

                def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                    if not responses:
                        raise AssertionError(f"unexpected provider call: {command}")
                    return responses.pop(0)

                proxy = self.proxy_module()
                with mock.patch(
                    "internal.code_intelligence_proxy.shutil.which",
                    return_value="/bin/codegraph",
                ):
                    query = proxy.execute_proxy_query(
                        self.repo,
                        "TASK-0001",
                        "PLANNING",
                        "CIQ-001",
                        "locate A conservatively",
                        "symbol A",
                        False,
                        runner=runner,
                    )
                fallback = {
                    "action": "SEARCH_SOURCE",
                    "path": None,
                    "observed_sha256": None,
                    "base_commit": None,
                    "head_commit": None,
                    "diff_hash": None,
                    "purpose": "verify the graph conclusion in current source",
                    "result_paths": [{
                        "path": "src/a.py",
                        "observed_sha256": file_sha256(source),
                    }],
                }
                protocol = importlib.import_module("internal.code_intelligence_protocol")
                result = protocol.record_proxy_bundle(
                    self.repo,
                    "TASK-0001",
                    query["bundle_path"],
                    {
                        "summary": "Used source fallback.",
                        "symbols": [],
                        "source_fallbacks": [fallback],
                    },
                    ROOT,
                )
                recorded = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
                self.assertEqual(recorded["delivery"]["state"], delivery_state)
                self.assertEqual(recorded["status"], record_status)
                self.assertEqual(recorded["delivery"]["usage"], (
                    "NO_GRAPH" if case == "unavailable" else "NAVIGATION_ONLY"
                ))
                self.assertEqual(
                    recorded["source_fallbacks"][0]["action"], "SEARCH_SOURCE"
                )

    def test_v2_schema_is_frozen_for_historical_reads(self) -> None:
        frozen = ROOT / "schemas/code-intelligence-record-v2.schema.json"
        self.assertTrue(frozen.is_file())
        self.assertEqual(json.loads(frozen.read_text(encoding="utf-8"))["title"],
                         "Polaris Code Intelligence record v2")

        self.initialize_task()
        value = self.v2_record()
        path = self.repo / ".polaris/tasks/TASK-0001/code-intelligence/r001/planning.json"
        write_json_atomic(path, value)
        original = path.read_bytes()
        protocol = importlib.import_module("internal.code_intelligence_protocol")
        validated = protocol.validate_historical_v2_record_value(
            self.repo, "TASK-0001", path, value, ROOT
        )
        self.assertEqual(validated["record_version"], 2)
        self.assertEqual(path.read_bytes(), original)

    def set_protocol_version(self, version: str) -> None:
        project_path = self.repo / ".polaris/project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["polaris_version"] = version
        write_json_atomic(project_path, project)
        state_path = self.repo / ".polaris/tasks/TASK-0001/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["polaris_version"] = version
        write_json_atomic(state_path, state)
        event_path = self.repo / ".polaris/tasks/TASK-0001/events.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        for event in events:
            event["polaris_version"] = version
        write_text_atomic(
            event_path,
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        )

    def set_workflow_version(self, version: str) -> None:
        project_path = self.repo / ".polaris/project.json"
        project = json.loads(project_path.read_text(encoding="utf-8"))
        project["workflow_version"] = version
        write_json_atomic(project_path, project)
        workflow_path = self.repo / ".polaris/workflow.json"
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        workflow["schema_version"] = version
        workflow["workflow_version"] = version
        write_json_atomic(workflow_path, workflow)
        state_path = self.repo / ".polaris/tasks/TASK-0001/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["workflow_version"] = version
        write_json_atomic(state_path, state)
        event_path = self.repo / ".polaris/tasks/TASK-0001/events.jsonl"
        events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
        for event in events:
            event["workflow_version"] = version
        write_text_atomic(
            event_path,
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        )

    def test_legacy_v1_records_remain_readable_but_cannot_be_written(self) -> None:
        self.initialize_task()
        protocol = importlib.import_module("internal.code_intelligence_protocol")
        legacy_validator = getattr(protocol, "validate_legacy_record_value", None)
        self.assertTrue(callable(legacy_validator))
        legacy = json.loads(
            (ROOT / "schemas" / "code-intelligence-record-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(legacy["properties"]["record_version"]["const"], 1)
        value = {
            "record_version": 1,
            "task_id": "TASK-0001",
            "work_item_revision": 1,
            "stage": "PLANNING",
            "artifact_attempt": None,
            "reviewer_slot": None,
            "provider": None,
            "target": {
                "base_commit": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=self.repo,
                    capture_output=True,
                    check=True,
                    encoding="utf-8",
                    text=True,
                ).stdout.strip(),
                "head_commit": None,
                "diff_hash": None,
            },
            "status": "UNAVAILABLE",
            "queries": [],
            "refresh": None,
            "recorded_at": "1970-01-01T00:00:00Z",
        }
        self.assertEqual(legacy_validator(self.repo, "TASK-0001", value, ROOT)["record_version"], 1)
        with self.assertRaisesRegex(
            InputFailure, "new Code Intelligence records must use record_version 3"
        ):
            record(self.repo, "TASK-0001", value, ROOT)

    def test_migration_retires_v1_records_without_rewriting_them(self) -> None:
        """0.1.20 inventories frozen v1 evidence while leaving its bytes intact."""
        self.initialize_task()
        self.set_protocol_version("0.1.19")
        self.set_workflow_version("0.1.2")
        legacy_path = (
            self.repo
            / ".polaris/tasks/TASK-0001/code-intelligence/r001/planning.json"
        )
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy = {
            "record_version": 1,
            "task_id": "TASK-0001",
            "work_item_revision": 1,
            "stage": "PLANNING",
            "artifact_attempt": None,
            "reviewer_slot": None,
            "provider": None,
            "target": {
                "base_commit": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=self.repo,
                    capture_output=True,
                    check=True,
                    encoding="utf-8",
                    text=True,
                ).stdout.strip(),
                "head_commit": None,
                "diff_hash": None,
            },
            "status": "UNAVAILABLE",
            "queries": [],
            "refresh": None,
            "recorded_at": "1970-01-01T00:00:00Z",
        }
        write_json_atomic(legacy_path, legacy)
        legacy_bytes = legacy_path.read_bytes()
        vendor(ROOT, self.repo, False)

        result = migrate_project(self.repo)

        self.assertEqual(result["from"], "0.1.19")
        self.assertEqual(result["to"], "0.1.20")
        self.assertEqual(
            json.loads((self.repo / ".polaris/project.json").read_text(encoding="utf-8"))["workflow_version"],
            "0.1.3",
        )
        migration = json.loads(
            (
                self.repo
                / ".polaris/migrations/MIG-0.1.19-to-0.1.20.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            migration["retired_code_intelligence_records"],
            [{
                "task_id": "TASK-0001",
                "path": "code-intelligence/r001/planning.json",
                "sha256": file_sha256(legacy_path),
            }],
        )
        self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))["record_version"], 1)
        self.assertEqual(legacy_path.read_bytes(), legacy_bytes)

        current = self.v2_record()
        current.update({"stage": "IMPLEMENTATION", "artifact_attempt": 1})
        with self.assertRaisesRegex(
            InputFailure, "new Code Intelligence records must use record_version 3"
        ):
            record(self.repo, "TASK-0001", current, ROOT)

    def test_migration_rejects_noncanonical_v2_record_paths(self) -> None:
        """Migration scans only the canonical Code Intelligence record layout."""
        self.initialize_task()
        self.set_protocol_version("0.1.19")
        self.set_workflow_version("0.1.2")
        noncanonical = (
            self.repo
            / ".polaris/tasks/TASK-0001/code-intelligence/r001/not-a-stage.json"
        )
        write_json_atomic(noncanonical, self.v2_record())
        vendor(ROOT, self.repo, False)

        with self.assertRaisesRegex(RuleFailure, "non-canonical"):
            migrate_project(self.repo)

    def test_migration_inventories_v1_records_from_prior_revisions(self) -> None:
        """A frozen r001 v1 record remains inventoryable after TASK-0001 reaches r002."""
        self.initialize_task()
        new_revision(self.repo, "TASK-0001")
        state_path = self.repo / ".polaris/tasks/TASK-0001/state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["current_revision"] = 2
        write_json_atomic(state_path, state)
        events_path = self.repo / ".polaris/tasks/TASK-0001/events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        events[0]["current_revision"] = 2
        write_text_atomic(
            events_path,
            "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        )
        self.set_protocol_version("0.1.19")
        self.set_workflow_version("0.1.2")
        legacy_path = (
            self.repo
            / ".polaris/tasks/TASK-0001/code-intelligence/r001/planning.json"
        )
        legacy = {
            "record_version": 1,
            "task_id": "TASK-0001",
            "work_item_revision": 1,
            "stage": "PLANNING",
            "artifact_attempt": None,
            "reviewer_slot": None,
            "provider": None,
            "target": {
                "base_commit": subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=self.repo,
                    capture_output=True,
                    check=True,
                    encoding="utf-8",
                    text=True,
                ).stdout.strip(),
                "head_commit": None,
                "diff_hash": None,
            },
            "status": "UNAVAILABLE",
            "queries": [],
            "refresh": None,
            "recorded_at": "1970-01-01T00:00:00Z",
        }
        write_json_atomic(legacy_path, legacy)
        legacy_bytes = legacy_path.read_bytes()
        with self.assertRaisesRegex(
            RuleFailure, "targets the wrong task revision"
        ):
            validate_record_value(self.repo, "TASK-0001", legacy, ROOT)
        vendor(ROOT, self.repo, False)

        try:
            migrate_project(self.repo)
        except RuleFailure as exc:
            self.fail(f"migration rejected immutable historical evidence: {exc}")

        migration = json.loads(
            (
                self.repo
                / ".polaris/migrations/MIG-0.1.19-to-0.1.20.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            migration["retired_code_intelligence_records"],
            [{
                "task_id": "TASK-0001",
                "path": "code-intelligence/r001/planning.json",
                "sha256": file_sha256(legacy_path),
            }],
        )
        self.assertEqual(legacy_path.read_bytes(), legacy_bytes)

    def test_migration_rejects_a_dangling_code_intelligence_symlink(self) -> None:
        """A dangling record-root symlink is rejected rather than treated as absent."""
        self.initialize_task()
        self.set_protocol_version("0.1.19")
        self.set_workflow_version("0.1.2")
        records_root = self.repo / ".polaris/tasks/TASK-0001/code-intelligence"
        shutil.rmtree(records_root)
        records_root.symlink_to(self.repo / "missing-code-intelligence")
        vendor(ROOT, self.repo, False)

        with self.assertRaisesRegex(RuleFailure, "must not be a symlink"):
            migrate_project(self.repo)

    def test_partial_stale_record_requires_matching_source_fallback(self) -> None:
        self.initialize_task()
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        value = self.v2_record()
        digest = file_sha256(source)
        value["freshness"] = {
            "status": "PARTIAL_STALE",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["RESPONSE_BANNER"],
            "response_sha256": None,
            "stale_points": [{
                "scope": "FILE",
                "path": "src/widget.py",
                "reason": "PENDING_SYNC",
                "fallback": "READ_SOURCE",
                "observed_sha256": digest,
            }],
        }
        value["status"] = "USED"
        self.add_explore_response_evidence(value)
        with self.assertRaisesRegex(RuleFailure, "matching source fallback"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["source_fallbacks"] = [{
            "action": "READ_SOURCE",
            "path": "src/widget.py",
            "observed_sha256": digest,
            "base_commit": None,
            "head_commit": None,
            "diff_hash": None,
            "purpose": "confirm pending CodeGraph content",
            "result_paths": [],
        }]
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"],
            2,
        )

    def test_response_banner_evidence_requires_a_hashed_explore_query(self) -> None:
        """A stale banner is valid only when this record can audit its explore response."""
        self.initialize_task()
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        digest = file_sha256(source)
        value = self.v2_record()
        value.update({
            "status": "USED",
            "provider": {
                "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                "available_operations": ["status"],
            },
            "freshness": {
                "status": "PARTIAL_STALE",
                "checked_at": "2026-08-18T00:00:00Z",
                "basis": ["RESPONSE_BANNER"],
                "response_sha256": None,
                "stale_points": [{
                    "scope": "FILE",
                    "path": "src/widget.py",
                    "reason": "PENDING_SYNC",
                    "fallback": "READ_SOURCE",
                    "observed_sha256": digest,
                }],
            },
            "source_fallbacks": [{
                "action": "READ_SOURCE",
                "path": "src/widget.py",
                "observed_sha256": digest,
                "base_commit": None,
                "head_commit": None,
                "diff_hash": None,
                "purpose": "confirm pending CodeGraph content",
                "result_paths": [],
            }],
        })
        with self.assertRaisesRegex(RuleFailure, "explore capability"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

        value["provider"] = {
            "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
            "available_operations": ["explore"],
        }
        with self.assertRaisesRegex(RuleFailure, "successful explore query"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

        value["queries"] = [{
            "id": "CIQ-001", "operation": "explore", "purpose": "inspect stale response",
            "status": "SUCCESS", "summary": "stale banner", "symbols": [],
            "response_sha256": "0" * 64, "error": None,
        }]
        value["freshness"]["response_sha256"] = "0" * 64
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"],
            2,
        )

    def test_response_banner_freshness_digest_binds_the_classified_response(self) -> None:
        """A banner conclusion must identify the exact successful explore response."""
        self.initialize_task()
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        digest = file_sha256(source)
        cases = (
            (
                "PARTIAL_STALE",
                [{
                    "scope": "FILE", "path": "src/widget.py", "reason": "PENDING_SYNC",
                    "fallback": "READ_SOURCE", "observed_sha256": digest,
                }],
                [{
                    "action": "READ_SOURCE", "path": "src/widget.py",
                    "observed_sha256": digest, "base_commit": None, "head_commit": None,
                    "diff_hash": None, "purpose": "read stale response source", "result_paths": [],
                }],
            ),
            (
                "INDEX_STALE",
                [{
                    "scope": "INDEX", "path": None, "reason": "AUTO_SYNC_DISABLED",
                    "fallback": "SEARCH_SOURCE", "observed_sha256": None,
                }],
                [{
                    "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
                    "base_commit": None, "head_commit": None, "diff_hash": None,
                    "purpose": "search stale CodeGraph index scope", "result_paths": [],
                }],
            ),
            (
                "NOT_VERIFIED",
                [{
                    "scope": "INDEX", "path": None, "reason": "STATUS_UNREADABLE",
                    "fallback": "SEARCH_SOURCE", "observed_sha256": None,
                }],
                [{
                    "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
                    "base_commit": None, "head_commit": None, "diff_hash": None,
                    "purpose": "search after unreadable CodeGraph response", "result_paths": [],
                }],
            ),
        )
        for status, stale_points, fallbacks in cases:
            with self.subTest(status=status):
                value = self.v2_record()
                value.update({
                    "status": "USED",
                    "freshness": {
                        "status": status,
                        "checked_at": "2026-08-18T00:00:00Z",
                        "basis": ["RESPONSE_BANNER"],
                        "response_sha256": None,
                        "stale_points": stale_points,
                    },
                    "source_fallbacks": fallbacks,
                })
                self.add_explore_response_evidence(value)
                value["freshness"]["response_sha256"] = None
                with self.assertRaisesRegex(RuleFailure, "freshness response hash"):
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)
                value["freshness"]["response_sha256"] = "1" * 64
                with self.assertRaisesRegex(RuleFailure, "must match"):
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)
                value["freshness"]["response_sha256"] = "0" * 64
                self.assertEqual(
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"],
                    2,
                )

    def test_unavailable_freshness_cannot_retain_a_classified_response_digest(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value["freshness"]["response_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuleFailure, "UNAVAILABLE freshness response hash"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

    def test_search_source_fallback_records_only_current_finite_search_results(self) -> None:
        self.initialize_task()
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        entry = {"path": "src/widget.py", "observed_sha256": file_sha256(source)}
        value = self.v2_record()
        value["source_fallbacks"] = [{
            "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
            "base_commit": None, "head_commit": None, "diff_hash": None,
            "purpose": "search affected source", "result_paths": [entry],
        }]
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

        invalid_cases: list[tuple[str, object, str]] = [
            ("hash", [{"path": "src/widget.py", "observed_sha256": "0" * 64}], "hash is stale"),
            ("traversal", [{"path": "../widget.py", "observed_sha256": entry["observed_sha256"]}], "invalid repository reference"),
            ("deleted", [{"path": "src/deleted.py", "observed_sha256": entry["observed_sha256"]}], "not a current regular file"),
            ("duplicate", [entry, dict(entry)], "duplicate SEARCH_SOURCE result path"),
            ("over-limit", [entry] * 101, "maxItems 100"),
        ]
        outside = self.repo / "outside.py"
        outside.write_text("outside\n", encoding="utf-8")
        link = self.repo / "src/link.py"
        link.symlink_to(outside)
        invalid_cases.append((
            "symlink",
            [{"path": "src/link.py", "observed_sha256": file_sha256(outside)}],
            "crosses a symlink",
        ))
        directory = self.repo / "src/directory.py"
        directory.mkdir()
        invalid_cases.append((
            "directory",
            [{"path": "src/directory.py", "observed_sha256": entry["observed_sha256"]}],
            "not a current regular file",
        ))
        for name, result_paths, error in invalid_cases:
            with self.subTest(name=name):
                value["source_fallbacks"][0]["result_paths"] = result_paths
                with self.assertRaisesRegex(RuleFailure, error):
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)

        value["source_fallbacks"][0]["result_paths"] = [entry]
        value["source_fallbacks"][0]["action"] = "READ_SOURCE"
        value["source_fallbacks"][0]["path"] = "src/widget.py"
        value["source_fallbacks"][0]["observed_sha256"] = entry["observed_sha256"]
        with self.assertRaisesRegex(RuleFailure, "non-SEARCH_SOURCE fallback"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

    def test_unavailable_record_cannot_claim_response_banner_evidence(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value["freshness"] = {
            "status": "UNAVAILABLE",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["RESPONSE_BANNER"],
            "response_sha256": None,
            "stale_points": [],
        }
        with self.assertRaisesRegex(RuleFailure, "cannot claim observed graph freshness"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

    def test_auditable_response_banners_preserve_noncurrent_freshness_states(self) -> None:
        self.initialize_task()
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        digest = file_sha256(source)
        cases = [
            (
                "PARTIAL_STALE",
                [{
                    "scope": "FILE", "path": "src/widget.py", "reason": "PENDING_SYNC",
                    "fallback": "READ_SOURCE", "observed_sha256": digest,
                }],
                [{
                    "action": "READ_SOURCE", "path": "src/widget.py",
                    "observed_sha256": digest, "base_commit": None, "head_commit": None,
                    "diff_hash": None, "purpose": "read stale response source", "result_paths": [],
                }],
            ),
            (
                "INDEX_STALE",
                [{
                    "scope": "INDEX", "path": None, "reason": "AUTO_SYNC_DISABLED",
                    "fallback": "SEARCH_SOURCE", "observed_sha256": None,
                }],
                [{
                    "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
                    "base_commit": None, "head_commit": None, "diff_hash": None,
                    "purpose": "search frozen CodeGraph index scope", "result_paths": [],
                }],
            ),
            (
                "NOT_VERIFIED",
                [{
                    "scope": "INDEX", "path": None, "reason": "STATUS_UNREADABLE",
                    "fallback": "SEARCH_SOURCE", "observed_sha256": None,
                }],
                [{
                    "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
                    "base_commit": None, "head_commit": None, "diff_hash": None,
                    "purpose": "search after unreadable CodeGraph response", "result_paths": [],
                }],
            ),
        ]
        for status, stale_points, fallbacks in cases:
            with self.subTest(status=status):
                value = self.v2_record()
                value.update({
                    "status": "USED",
                    "freshness": {
                        "status": status,
                        "checked_at": "2026-08-18T00:00:00Z",
                        "basis": ["RESPONSE_BANNER"],
                        "response_sha256": None,
                        "stale_points": stale_points,
                    },
                    "source_fallbacks": fallbacks,
                })
                self.add_explore_response_evidence(value)
                self.assertEqual(
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"],
                    2,
                )

    def test_v2_freshness_statuses_require_consistent_stale_points(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        index_point = {
            "scope": "INDEX",
            "path": None,
            "reason": "INDEX_FAILED",
            "fallback": "SEARCH_SOURCE",
            "observed_sha256": None,
        }
        search = {
            "action": "SEARCH_SOURCE",
            "path": None,
            "observed_sha256": None,
            "base_commit": None,
            "head_commit": None,
            "diff_hash": None,
            "purpose": "find affected source",
            "result_paths": [],
        }
        value["status"] = "SKIPPED"
        value["freshness"] = {
            "status": "CURRENT_AT_CHECK",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
            "response_sha256": None,
            "stale_points": [index_point],
        }
        value["source_fallbacks"] = [search]
        value["provider"] = {
            "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
            "available_operations": ["status"],
        }
        value["status_check"] = {
            "status": "SUCCESS", "phase": "STAGE_ENTRY",
            "response_sha256": "0" * 64, "error": None,
        }
        with self.assertRaisesRegex(RuleFailure, "CURRENT_AT_CHECK"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["freshness"]["status"] = "PARTIAL_STALE"
        with self.assertRaisesRegex(RuleFailure, "PARTIAL_STALE"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["freshness"]["status"] = "INDEX_STALE"
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"],
            2,
        )

    def test_v2_fallback_and_sync_rules_are_auditable(self) -> None:
        self.initialize_task()
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        value = self.v2_record()
        digest = file_sha256(source)
        value["status"] = "SKIPPED"
        value["freshness"] = {
            "status": "PARTIAL_STALE",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["RESPONSE_BANNER"],
            "response_sha256": None,
            "stale_points": [{
                "scope": "FILE", "path": "src/widget.py", "reason": "PENDING_SYNC",
                "fallback": "READ_SOURCE", "observed_sha256": digest,
            }],
        }
        self.add_explore_response_evidence(value)
        value["source_fallbacks"] = [{
            "action": "READ_SOURCE", "path": "src/widget.py", "observed_sha256": "0" * 64,
            "base_commit": None, "head_commit": None, "diff_hash": None, "purpose": "read source", "result_paths": [],
        }]
        with self.assertRaisesRegex(RuleFailure, "READ_SOURCE fallback hash is stale"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["source_fallbacks"][0]["observed_sha256"] = digest
        value["source_fallbacks"][0]["action"] = "INSPECT_GIT_DIFF"
        value["source_fallbacks"][0]["observed_sha256"] = None
        with self.assertRaisesRegex(RuleFailure, "cannot describe an existing file"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value = self.v2_record()
        value["provider"] = {
            "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
            "available_operations": ["sync"],
        }
        value["sync"] = {"status": "SUCCESS", "response_sha256": None, "error": None}
        with self.assertRaisesRegex(RuleFailure, "successful Code Intelligence sync requires"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["sync"]["response_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuleFailure, "SYNC_ACKNOWLEDGED"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

    def test_v2_unavailable_and_provider_capabilities_are_restricted(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value["queries"] = [{
            "id": "CIQ-001", "operation": "explore", "purpose": "query", "status": "SUCCESS",
            "summary": "result", "symbols": [], "response_sha256": "0" * 64, "error": None,
        }]
        with self.assertRaisesRegex(RuleFailure, "UNAVAILABLE record contains"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value = self.v2_record()
        value["provider"] = {
            "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
            "available_operations": ["status"],
        }
        value["status_check"] = {
            "status": "SUCCESS", "phase": "STAGE_ENTRY",
            "response_sha256": "0" * 64, "error": None,
        }
        with self.assertRaisesRegex(RuleFailure, "unavailable Code Intelligence record"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value = self.v2_record()
        value["provider"] = {
            "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
            "available_operations": ["symbol_search"],
        }
        with self.assertRaises(RuleFailure):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

        for status_check in (
            {"status": "FAILED", "phase": "STAGE_ENTRY", "response_sha256": None, "error": "status failed"},
            {"status": "SKIPPED", "phase": "STAGE_ENTRY", "response_sha256": None, "error": None},
        ):
            with self.subTest(status_check=status_check["status"]):
                value = self.v2_record()
                value["provider"] = {
                    "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                    "available_operations": ["status"],
                }
                value["status_check"] = status_check
                with self.assertRaisesRegex(RuleFailure, "unavailable Code Intelligence record"):
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)

        value = self.v2_record()
        value["status_check"] = {
            "status": "UNAVAILABLE", "phase": "STAGE_ENTRY",
            "response_sha256": None, "error": None,
        }
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

        for sync in (
            {"status": "SKIPPED", "response_sha256": None, "error": None},
            {"status": "SUCCESS", "response_sha256": "0" * 64, "error": None},
            {"status": "FAILED", "response_sha256": None, "error": "sync failed"},
            {"status": "UNAVAILABLE", "response_sha256": "0" * 64, "error": None},
            {"status": "UNAVAILABLE", "response_sha256": None, "error": "unavailable"},
        ):
            with self.subTest(sync=sync["status"]):
                value = self.v2_record()
                value["sync"] = sync
                with self.assertRaises(RuleFailure):
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)

    def test_unavailable_sync_results_project_to_v2_records(self) -> None:
        self.initialize_task()
        _, sync_if_needed = self.adapter_functions()
        descriptor = load_providers(ROOT)["codegraph"]

        unavailable = sync_if_needed(
            self.repo,
            descriptor,
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        self.assertEqual(unavailable["freshness"]["status"], "UNAVAILABLE")
        self.assertEqual(unavailable["sync"], {
            "status": "UNAVAILABLE", "response_sha256": None, "error": None,
        })
        value = self.v2_record()
        value["sync"] = unavailable["sync"]
        value["freshness"] = {
            key: unavailable["freshness"][key]
            for key in ("status", "checked_at", "basis", "stale_points")
        }
        value["freshness"]["response_sha256"] = None
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

        unsafe_descriptor = dict(descriptor)
        unsafe_descriptor["project_marker"] = ".."
        unsafe = sync_if_needed(
            self.repo,
            unsafe_descriptor,
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )
        self.assertEqual(unsafe["freshness"]["status"], "UNAVAILABLE")
        self.assertEqual(unsafe["sync"], {
            "status": "UNAVAILABLE", "response_sha256": None, "error": None,
        })
        value = self.v2_record()
        value.update({
            "sync": unsafe["sync"],
            "freshness": {
                key: unsafe["freshness"][key]
                for key in ("status", "checked_at", "basis", "stale_points")
            },
            "source_fallbacks": [{
                "action": "SEARCH_SOURCE", "path": None,
                "observed_sha256": None, "base_commit": None,
                "head_commit": None, "diff_hash": None,
                "purpose": "recover unavailable CodeGraph evidence", "result_paths": [],
            }],
        })
        value["freshness"]["response_sha256"] = None
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

    def test_inspect_git_diff_is_only_valid_for_missing_stale_files(self) -> None:
        self.initialize_task()
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True,
            check=True, encoding="utf-8", text=True,
        ).stdout.strip()
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/widget.py"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "add widget"], cwd=self.repo, check=True
        )
        added_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True,
            check=True, encoding="utf-8", text=True,
        ).stdout.strip()
        value = self.v2_record()
        value.update({
            "status": "SKIPPED",
            "target": {
                "base_commit": base,
                "head_commit": added_head,
                "diff_hash": subject_diff_hash(self.repo, base, added_head),
            },
            "freshness": {
                "status": "PARTIAL_STALE",
                "checked_at": "2026-08-18T00:00:00Z",
                "basis": ["RESPONSE_BANNER"],
                "response_sha256": None,
                "stale_points": [{
                    "scope": "FILE", "path": "src/widget.py", "reason": "PENDING_SYNC",
                    "fallback": "INSPECT_GIT_DIFF", "observed_sha256": None,
                }],
            },
            "source_fallbacks": [{
                "action": "INSPECT_GIT_DIFF", "path": "src/widget.py",
                "observed_sha256": None, "base_commit": base, "head_commit": added_head,
                "diff_hash": subject_diff_hash(self.repo, base, added_head), "purpose": "inspect change", "result_paths": [],
            }],
        })
        self.add_explore_response_evidence(value)
        with self.assertRaisesRegex(RuleFailure, "existing file"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        source.unlink()
        subprocess.run(["git", "add", "-u"], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "delete widget"], cwd=self.repo, check=True
        )
        deleted_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True,
            check=True, encoding="utf-8", text=True,
        ).stdout.strip()
        value["target"] = {
            "base_commit": base,
            "head_commit": deleted_head,
            "diff_hash": subject_diff_hash(self.repo, base, deleted_head),
        }
        value["source_fallbacks"][0].update({
            "base_commit": base,
            "head_commit": deleted_head,
            "diff_hash": subject_diff_hash(self.repo, base, deleted_head),
        })
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

    def test_sync_evidence_requires_advertised_sync_capability(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value.update({
            "status": "USED",
            "provider": {
                "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                "available_operations": ["status"],
            },
            "status_check": {
                "status": "SUCCESS", "phase": "POST_SYNC",
                "response_sha256": "1" * 64, "error": None,
            },
            "sync": {"status": "SUCCESS", "response_sha256": "0" * 64, "error": None},
            "freshness": {
                "status": "CURRENT_AT_CHECK",
                "checked_at": "2026-08-18T00:00:00Z",
                "basis": ["SYNC_ACKNOWLEDGED"],
                "response_sha256": None,
                "stale_points": [],
            },
        })
        with self.assertRaisesRegex(RuleFailure, "sync capability"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["provider"] = {
            "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
            "available_operations": ["sync", "status"],
        }
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

    def test_current_freshness_requires_a_real_non_none_evidence_path(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value.update({
            "status": "SKIPPED",
            "freshness": {
                "status": "CURRENT_AT_CHECK",
                "checked_at": "2026-08-18T00:00:00Z",
                "basis": ["NONE"],
                "response_sha256": None,
                "stale_points": [],
            },
        })
        with self.assertRaisesRegex(RuleFailure, "basis NONE is reserved"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["freshness"]["basis"] = ["CONNECT_RECONCILIATION"]
        with self.assertRaisesRegex(RuleFailure, "CURRENT_AT_CHECK requires"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

    def test_current_freshness_requires_hashed_status_check_evidence(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value.update({
            "status": "SKIPPED",
            "freshness": {
                "status": "CURRENT_AT_CHECK",
                "checked_at": "2026-08-18T00:00:00Z",
                "basis": ["STATUS_JSON"],
                "response_sha256": None,
                "stale_points": [],
            },
        })
        with self.assertRaisesRegex(RuleFailure, "structured status check evidence"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["status_check"] = {
            "status": "SUCCESS", "phase": "STAGE_ENTRY",
            "response_sha256": "0" * 64, "error": None,
        }
        with self.assertRaisesRegex(RuleFailure, "status capability"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["provider"] = {
            "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
            "available_operations": ["status"],
        }
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

    def test_sync_currentness_requires_successful_post_sync_status_check(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value.update({
            "status": "USED",
            "provider": {
                "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                "available_operations": ["sync", "status"],
            },
            "sync": {"status": "SUCCESS", "response_sha256": "0" * 64, "error": None},
            "freshness": {
                "status": "CURRENT_AT_CHECK",
                "checked_at": "2026-08-18T00:00:00Z",
                "basis": ["SYNC_ACKNOWLEDGED"],
                "response_sha256": None,
                "stale_points": [],
            },
        })
        with self.assertRaisesRegex(RuleFailure, "successful status check"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["status_check"] = {
            "status": "SUCCESS", "phase": "STAGE_ENTRY",
            "response_sha256": "1" * 64, "error": None,
        }
        with self.assertRaisesRegex(RuleFailure, "POST_SYNC status check"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)
        value["status_check"]["phase"] = "POST_SYNC"
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

    def test_failed_status_check_records_adapter_not_verified_results(self) -> None:
        self.initialize_task()
        (self.repo / ".codegraph").mkdir()
        inspect_status, _ = self.adapter_functions()
        descriptor = load_providers(ROOT)["codegraph"]
        for raw, returncode in (("{not json", 0), ("status failed", 3)):
            with self.subTest(returncode=returncode):
                result = inspect_status(
                    self.repo,
                    descriptor,
                    runner=lambda *args, **kwargs: completed(raw, returncode),
                )
                self.assertEqual(result["status"], "NOT_VERIFIED")
                self.assertEqual(result["basis"], ["STATUS_JSON"])
                self.assertEqual(result["stale_points"][0]["reason"], "STATUS_UNREADABLE")
                self.assertTrue(result["error"])
                self.assertIsNotNone(result["status_response_sha256"])
                value = self.v2_record()
                value.update({
                    "status": "FAILED",
                    "provider": {
                        "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                        "available_operations": ["status"],
                    },
                    "status_check": {
                        "status": "FAILED", "phase": "STAGE_ENTRY",
                        "response_sha256": result["status_response_sha256"],
                        "error": result["error"],
                    },
                    "freshness": {
                        "status": result["status"], "checked_at": result["checked_at"],
                        "basis": result["basis"], "response_sha256": None,
                        "stale_points": result["stale_points"],
                    },
                    "source_fallbacks": [{
                        "action": "SEARCH_SOURCE", "path": None,
                        "observed_sha256": None, "base_commit": None,
                        "head_commit": None, "diff_hash": None,
                        "purpose": "recover unreadable CodeGraph status", "result_paths": [],
                    }],
                })
                self.assertEqual(
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
                )

    def test_sync_results_project_to_v2_records_without_false_success(self) -> None:
        """A sync command is successful only after a healthy post-sync status."""
        self.initialize_task()
        (self.repo / ".codegraph").mkdir()
        _, sync_if_needed = self.adapter_functions()
        descriptor = load_providers(ROOT)["codegraph"]
        pending = json.loads(healthy_status(self.repo))
        pending["pendingChanges"]["modified"] = 1

        def runner_for(
            responses: list[subprocess.CompletedProcess[str]],
        ) -> object:
            iterator = iter(responses)
            return lambda *args, **kwargs: next(iterator)

        def project(
            result: dict[str, object], status_check: dict[str, object]
        ) -> dict[str, object]:
            freshness = result["freshness"]
            sync = result["sync"]
            value = self.v2_record()
            value.update({
                "status": "USED" if sync["status"] == "SUCCESS" else "FAILED",
                "provider": {
                    "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                    "available_operations": ["status", "sync"],
                },
                "status_check": status_check,
                "sync": sync,
                "freshness": {
                    "status": freshness["status"], "checked_at": freshness["checked_at"],
                    "basis": freshness["basis"], "response_sha256": None,
                    "stale_points": freshness["stale_points"],
                },
                "source_fallbacks": ([{
                    "action": "SEARCH_SOURCE", "path": None,
                    "observed_sha256": None, "base_commit": None,
                    "head_commit": None, "diff_hash": None,
                    "purpose": "recover stale CodeGraph evidence", "result_paths": [],
                }] if freshness["stale_points"] else []),
            })
            return value

        malformed_post = sync_if_needed(
            self.repo,
            descriptor,
            runner=runner_for([
                completed(json.dumps(pending)),
                completed("synced\n"),
                completed("{not json"),
            ]),
        )
        self.assertEqual(malformed_post["sync"]["status"], "FAILED")
        self.assertEqual(malformed_post["freshness"]["status"], "INDEX_STALE")
        self.assertEqual(malformed_post["freshness"]["error"], "CodeGraph post-sync status is not current")
        self.assertIn("SYNC_FAILED", [
            point["reason"] for point in malformed_post["freshness"]["stale_points"]
        ])
        self.assertEqual(
            validate_record_value(
                self.repo,
                "TASK-0001",
                project(malformed_post, {
                    "status": "FAILED", "phase": "POST_SYNC",
                    "response_sha256": malformed_post["freshness"]["status_response_sha256"],
                    "error": malformed_post["freshness"]["error"],
                }),
                ROOT,
            )["record_version"],
            2,
        )

        unhealthy = json.loads(healthy_status(self.repo))
        unhealthy["index"]["state"] = "failed"
        unhealthy_post = sync_if_needed(
            self.repo,
            descriptor,
            runner=runner_for([
                completed(json.dumps(pending)),
                completed("synced\n"),
                completed(json.dumps(unhealthy)),
            ]),
        )
        self.assertEqual(unhealthy_post["sync"]["status"], "FAILED")
        self.assertEqual(unhealthy_post["freshness"]["status"], "INDEX_STALE")
        self.assertEqual(unhealthy_post["freshness"]["error"], "CodeGraph post-sync status is not current")
        self.assertEqual(
            validate_record_value(
                self.repo,
                "TASK-0001",
                project(unhealthy_post, {
                    "status": "SUCCESS", "phase": "POST_SYNC",
                    "response_sha256": unhealthy_post["freshness"]["status_response_sha256"],
                    "error": None,
                }),
                ROOT,
            )["record_version"],
            2,
        )

        healthy_post = sync_if_needed(
            self.repo,
            descriptor,
            runner=runner_for([
                completed(json.dumps(pending)),
                completed("synced\n"),
                completed(healthy_status(self.repo)),
            ]),
        )
        self.assertEqual(healthy_post["sync"]["status"], "SUCCESS")
        self.assertEqual(
            validate_record_value(
                self.repo,
                "TASK-0001",
                project(healthy_post, {
                    "status": "SUCCESS", "phase": "POST_SYNC",
                    "response_sha256": healthy_post["freshness"]["status_response_sha256"],
                    "error": None,
                }),
                ROOT,
            )["record_version"],
            2,
        )

        raw_failure = sync_if_needed(
            self.repo,
            descriptor,
            runner=runner_for([
                completed(json.dumps(pending)),
                completed("sync failed", returncode=1),
            ]),
        )
        self.assertEqual(raw_failure["sync"]["status"], "FAILED")
        self.assertEqual(raw_failure["freshness"]["status"], "INDEX_STALE")
        self.assertEqual(
            validate_record_value(
                self.repo,
                "TASK-0001",
                project(raw_failure, {
                    "status": "SUCCESS", "phase": "STAGE_ENTRY",
                    "response_sha256": raw_failure["freshness"]["status_response_sha256"],
                    "error": None,
                }),
                ROOT,
            )["record_version"],
            2,
        )

    def test_noncurrent_post_sync_check_downgrades_sync_evidence(self) -> None:
        self.initialize_task()
        fallback = {
            "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
            "base_commit": None, "head_commit": None, "diff_hash": None,
            "purpose": "recover stale CodeGraph index", "result_paths": [],
        }
        for status, reason in (("INDEX_STALE", "INDEX_FAILED"),):
            with self.subTest(status=status):
                value = self.v2_record()
                value.update({
                    "status": "USED",
                    "provider": {
                        "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                        "available_operations": ["sync", "status"],
                    },
                    "status_check": {
                        "status": "SUCCESS", "phase": "STAGE_ENTRY",
                        "response_sha256": "1" * 64, "error": None,
                    },
                    "sync": {
                        "status": "SUCCESS", "response_sha256": "0" * 64, "error": None,
                    },
                    "freshness": {
                        "status": status, "checked_at": "2026-08-18T00:00:00Z",
                        "basis": ["STATUS_JSON", "SYNC_ACKNOWLEDGED"],
                        "response_sha256": None,
                        "stale_points": [{
                            "scope": "INDEX", "path": None, "reason": reason,
                            "fallback": "SEARCH_SOURCE", "observed_sha256": None,
                        }],
                    },
                    "source_fallbacks": [fallback],
                })
                with self.assertRaisesRegex(RuleFailure, "POST_SYNC status check"):
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)
                value["status_check"]["phase"] = "POST_SYNC"
                with self.assertRaisesRegex(RuleFailure, "successful sync requires"):
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)
                value["sync"] = {
                    "status": "FAILED", "response_sha256": "0" * 64,
                    "error": "CodeGraph post-sync status is not current",
                }
                value["status"] = "FAILED"
                value["freshness"]["basis"] = ["STATUS_JSON"]
                value["freshness"]["stale_points"].append({
                    "scope": "INDEX", "path": None, "reason": "SYNC_FAILED",
                    "fallback": "SEARCH_SOURCE", "observed_sha256": None,
                })
                self.assertEqual(
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
                )

        value = self.v2_record()
        value.update({
            "status": "SKIPPED",
            "provider": {
                "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                "available_operations": ["status"],
            },
            "status_check": {
                "status": "SUCCESS", "phase": "POST_SYNC",
                "response_sha256": "0" * 64, "error": None,
            },
            "freshness": {
                "status": "INDEX_STALE", "checked_at": "2026-08-18T00:00:00Z",
                "basis": ["STATUS_JSON"], "response_sha256": None, "stale_points": [{
                    "scope": "INDEX", "path": None, "reason": "INDEX_FAILED",
                    "fallback": "SEARCH_SOURCE", "observed_sha256": None,
                }],
            },
            "source_fallbacks": [fallback],
        })
        with self.assertRaisesRegex(RuleFailure, "POST_SYNC status check requires an attempted sync"):
            validate_record_value(self.repo, "TASK-0001", value, ROOT)

    def test_official_descriptor_uses_explore_status_and_sync(self) -> None:
        descriptor = load_providers(ROOT)["codegraph"]
        self.assertEqual(descriptor["provider_version"], 2)
        self.assertEqual(
            descriptor["implementation"],
            "https://github.com/colbymchenry/codegraph",
        )
        self.assertEqual(descriptor["project_marker"], ".codegraph")
        self.assertEqual(
            descriptor["operations"],
            {"explore": "codegraph_explore", "status": "codegraph_status"},
        )
        self.assertEqual(descriptor["cli"]["sync_args"], ["sync", "--quiet"])

    def test_all_agent_surfaces_share_codegraph_fallback_rules(self) -> None:
        """Stage instructions keep CodeGraph stale-data fallbacks identical per host."""
        required_fragments = (
            ".codegraph/",
            "codegraph_explore",
            "codegraph explore",
            "codegraph sync",
            "PARTIAL_STALE",
            "INDEX_STALE",
            "directly read",
            "never run `codegraph init`",
        )
        partial_stale_branches = (
            "current confined regular file",
            "READ_SOURCE",
            "current SHA-256",
            "missing/deleted",
            "INSPECT_GIT_DIFF",
            "null observed SHA-256",
            "base/head/diff evidence",
            "unsafe paths",
            "NOT_VERIFIED",
            "source search",
        )
        audit_binding_fragments = (
            "freshness.response_sha256",
            "successful explore response",
            "result_paths",
            "at most 100",
            "POSIX",
            "current confined regular file",
            "empty `result_paths`",
        )
        retired_operations = (
            "symbol" + "_search",
            "call" + "_graph",
            "review" + "_context",
            "refresh" + "_files",
            "refresh" + "_workspace",
        )
        stage_skills = (
            "code-intelligence",
            "architecture-planning",
            "implementation",
            "adversarial-review",
            "documentation-sync",
        )
        available_skills = set(discover_skills(ROOT))
        for adapter in load_host_adapters(ROOT):
            for skill_name in stage_skills:
                source = (ROOT / "skills" / skill_name / "SKILL.md").read_text(
                    encoding="utf-8"
                )
                rendered = render_skill(
                    source, skill_name, adapter, available_skills
                )
                for fragment in required_fragments:
                    self.assertIn(fragment, rendered, f"{adapter['host_id']}:{skill_name}")
                for fragment in partial_stale_branches:
                    self.assertIn(fragment, rendered, f"{adapter['host_id']}:{skill_name}")
                for fragment in audit_binding_fragments:
                    self.assertIn(fragment, rendered, f"{adapter['host_id']}:{skill_name}")
                self.assertIn("v2", rendered, f"{adapter['host_id']}:{skill_name}")
                self.assertNotIn("directly read every listed stale file", rendered)
                for retired in retired_operations:
                    self.assertNotIn(retired, rendered, f"{adapter['host_id']}:{skill_name}")

        validation = (ROOT / "skills" / "validation" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Do not invoke Code Intelligence", validation)

        agents = (ROOT / "templates" / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("stop CodeGraph calls for this session", agents)
        self.assertIn("installer-managed marker block", agents)
        for fragment in partial_stale_branches:
            self.assertIn(fragment, agents)
        for fragment in audit_binding_fragments:
            self.assertIn(fragment, agents)
        self.assertNotIn("directly read every listed stale file", agents)

    def test_provider_requires_marker_and_accepts_mcp_or_cli(self) -> None:
        self.assertIsNone(
            select_provider(self.repo, ["codegraph_explore"], ROOT)
        )
        (self.repo / ".codegraph").mkdir()
        selected = select_provider(self.repo, ["codegraph_explore"], ROOT)
        self.assertEqual(selected["operations"], {"explore": "codegraph_explore"})
        cli = select_provider(
            self.repo, [], ROOT, available_executables=["codegraph"]
        )
        self.assertTrue(cli["cli_available"])

    def test_project_marker_rejects_unsafe_paths_and_symlinks(self) -> None:
        for marker in ("/absolute", ".codegraph/cache"):
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(RuleFailure, "unsafe"):
                    _project_marker_path(self.repo, marker)

        target = self.repo / "marker-target"
        target.mkdir()
        (self.repo / ".codegraph").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(RuleFailure, "must not be a symlink"):
            _project_marker_path(self.repo, ".codegraph")

    def test_record_cli_requires_task_id_bundle_and_annotations(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                SCRIPTS / "record_code_intelligence.py",
                "--repo",
                self.repo,
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ERROR")
        self.assertEqual(
            payload["message"],
            "recording requires task_id, --bundle, and --annotations",
        )

    def test_old_product_tool_names_are_absent_from_descriptor(self) -> None:
        text = (ROOT / "providers/code-intelligence/codegraph.json").read_text(
            encoding="utf-8"
        )
        for fragment in ("get_ai_context", "index_files", "reindex_workspace"):
            self.assertNotIn(fragment, text)

    def test_healthy_status_is_current_at_check(self) -> None:
        inspect_status, _ = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()

        result = inspect_status(
            self.repo,
            load_providers(ROOT)["codegraph"],
            runner=lambda *args, **kwargs: completed(healthy_status(self.repo)),
        )

        self.assertEqual(result["status"], "CURRENT_AT_CHECK")
        self.assertEqual(result["basis"], ["STATUS_JSON"])
        self.assertEqual(result["stale_points"], [])
        self.assertFalse(result["needs_sync"])
        self.assertEqual(
            result["pending_changes"], {"added": 0, "modified": 0, "removed": 0}
        )

    def test_pending_changes_sync_once_and_recheck_once(self) -> None:
        _, sync_if_needed = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()
        pending = json.loads(healthy_status(self.repo))
        pending["pendingChanges"]["modified"] = 1
        responses = iter(
            [
                completed(json.dumps(pending)),
                completed("Synced 1 changed file\n"),
                completed(healthy_status(self.repo)),
            ]
        )
        calls: list[list[str]] = []

        def runner(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return next(responses)

        result = sync_if_needed(
            self.repo, load_providers(ROOT)["codegraph"], runner=runner
        )

        self.assertEqual([call[1] for call in calls], ["status", "sync", "status"])
        self.assertEqual(result["sync"]["status"], "SUCCESS")
        self.assertEqual(result["freshness"]["status"], "CURRENT_AT_CHECK")
        self.assertIn("SYNC_ACKNOWLEDGED", result["freshness"]["basis"])

    def test_explore_and_observed_sync_are_bounded_to_one_repo(self) -> None:
        adapter = self.adapter_module()
        (self.repo / ".codegraph").mkdir()
        calls: list[tuple[list[str], Path]] = []

        def runner(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            cwd = kwargs["cwd"]
            self.assertIsInstance(cwd, Path)
            calls.append((command, cwd))
            if command[1:3] == ["status", "--json"]:
                return completed(healthy_status(self.repo))
            if command[1:] == ["sync", "--quiet"]:
                return completed("synced\n")
            return completed("graph response\n")

        pending = json.loads(healthy_status(self.repo))
        pending["pendingChanges"]["modified"] = 1
        initial = adapter._status_result(
            self.repo, pending, "2026-08-19T00:00:00Z", "a" * 64
        )
        synchronized = adapter.synchronize_observed_status(
            self.repo,
            load_providers(ROOT)["codegraph"],
            initial,
            runner=runner,
        )
        explored = adapter.run_explore(
            self.repo,
            load_providers(ROOT)["codegraph"],
            "find symbol A",
            runner=runner,
        )

        self.assertEqual(synchronized["sync"]["status"], "SUCCESS")
        self.assertEqual(explored["status"], "SUCCESS")
        self.assertEqual(
            explored["response_sha256"],
            hashlib.sha256(b"graph response\n").hexdigest(),
        )
        self.assertTrue(all(cwd == self.repo for _command, cwd in calls))
        self.assertEqual(sum(command[1] == "sync" for command, _cwd in calls), 1)
        self.assertEqual(sum(command[1] == "explore" for command, _cwd in calls), 1)

    def test_index_wide_stale_reasons_do_not_sync(self) -> None:
        inspect_status, sync_if_needed = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()
        cases = [
            (
                {"worktreeMismatch": {"worktreeRoot": "/a", "indexRoot": "/b"}},
                "WORKTREE_MISMATCH",
            ),
            (
                {
                    "index": {
                        "state": "partial",
                        "pendingRefs": 0,
                        "reindexRecommended": False,
                    }
                },
                "INDEX_PARTIAL",
            ),
            (
                {
                    "index": {
                        "state": "indexing",
                        "pendingRefs": 0,
                        "reindexRecommended": False,
                    }
                },
                "INDEX_INDEXING",
            ),
            (
                {
                    "index": {
                        "state": "failed",
                        "pendingRefs": 0,
                        "reindexRecommended": False,
                    }
                },
                "INDEX_FAILED",
            ),
            (
                {
                    "index": {
                        "state": "complete",
                        "pendingRefs": 2,
                        "reindexRecommended": False,
                    }
                },
                "PENDING_REFERENCES",
            ),
            (
                {
                    "index": {
                        "state": "complete",
                        "pendingRefs": 0,
                        "reindexRecommended": True,
                    }
                },
                "REINDEX_RECOMMENDED",
            ),
        ]
        descriptor = load_providers(ROOT)["codegraph"]
        for override, expected_reason in cases:
            with self.subTest(reason=expected_reason):
                status = json.loads(healthy_status(self.repo))
                status.update(override)
                calls: list[list[str]] = []

                def runner(
                    command: list[str], **kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return completed(json.dumps(status))

                inspection = inspect_status(self.repo, descriptor, runner=runner)
                result = sync_if_needed(self.repo, descriptor, runner=runner)

                self.assertEqual(inspection["status"], "INDEX_STALE")
                self.assertEqual(result["freshness"]["status"], "INDEX_STALE")
                self.assertEqual(
                    inspection["stale_points"],
                    [
                        {
                            "scope": "INDEX",
                            "path": None,
                            "reason": expected_reason,
                            "fallback": "SEARCH_SOURCE",
                            "observed_sha256": None,
                        }
                    ],
                )
                self.assertEqual(calls, [["codegraph", "status", "--json"]] * 2)
                self.assertEqual(result["sync"]["status"], "SKIPPED")

    def test_unreadable_statuses_fall_back_without_sync(self) -> None:
        _, sync_if_needed = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()
        descriptor = load_providers(ROOT)["codegraph"]
        wrong_project = json.loads(healthy_status(self.repo))
        wrong_project["projectPath"] = str(self.repo / "other")
        invalid_counts = json.loads(healthy_status(self.repo))
        invalid_counts["pendingChanges"]["added"] = True
        cases = [
            (completed("not json"), "malformed JSON"),
            (completed(healthy_status(self.repo), returncode=1, stderr="failed"), "nonzero"),
            (completed(json.dumps(wrong_project)), "wrong project"),
            (completed(json.dumps(invalid_counts)), "invalid counts"),
        ]
        for response, name in cases:
            with self.subTest(name=name):
                calls: list[list[str]] = []

                def runner(
                    command: list[str], **kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return response

                result = sync_if_needed(self.repo, descriptor, runner=runner)
                self.assertEqual(result["freshness"]["status"], "NOT_VERIFIED")
                self.assertEqual(
                    result["freshness"]["stale_points"][0]["reason"],
                    "STATUS_UNREADABLE",
                )
                self.assertEqual(result["sync"]["status"], "SKIPPED")
                self.assertEqual(calls, [["codegraph", "status", "--json"]])

    def test_unsafe_marker_does_not_run_codegraph(self) -> None:
        inspect_status, _ = self.adapter_functions()
        descriptor = dict(load_providers(ROOT)["codegraph"])
        descriptor["project_marker"] = ".."

        result = inspect_status(
            self.repo,
            descriptor,
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )

        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["basis"], ["NONE"])
        self.assertEqual(result["stale_points"], [])

    def test_failed_sync_marks_the_index_stale_without_retrying(self) -> None:
        _, sync_if_needed = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()
        pending = json.loads(healthy_status(self.repo))
        pending["pendingChanges"]["added"] = 1
        responses = iter(
            [completed(json.dumps(pending)), completed("sync failed", returncode=1)]
        )
        calls: list[list[str]] = []

        def runner(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return next(responses)

        result = sync_if_needed(
            self.repo, load_providers(ROOT)["codegraph"], runner=runner
        )

        self.assertEqual([call[1] for call in calls], ["status", "sync"])
        self.assertEqual(result["sync"]["status"], "FAILED")
        self.assertEqual(result["freshness"]["status"], "INDEX_STALE")
        self.assertEqual(
            result["freshness"]["stale_points"][-1]["reason"], "SYNC_FAILED"
        )

    def test_unhealthy_recheck_downgrades_sync_and_preserves_index_reason(self) -> None:
        _, sync_if_needed = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()
        pending = json.loads(healthy_status(self.repo))
        pending["pendingChanges"]["removed"] = 1
        unhealthy = json.loads(healthy_status(self.repo))
        unhealthy["index"]["state"] = "failed"
        responses = iter(
            [
                completed(json.dumps(pending)),
                completed("Synced 1 changed file\n"),
                completed(json.dumps(unhealthy)),
            ]
        )
        calls: list[list[str]] = []

        def runner(
            command: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return next(responses)

        result = sync_if_needed(
            self.repo, load_providers(ROOT)["codegraph"], runner=runner
        )

        self.assertEqual([call[1] for call in calls], ["status", "sync", "status"])
        self.assertEqual(result["sync"]["status"], "FAILED")
        self.assertEqual(
            result["sync"]["error"], "CodeGraph post-sync status is not current"
        )
        self.assertEqual(result["freshness"]["status"], "INDEX_STALE")
        self.assertEqual(
            [point["reason"] for point in result["freshness"]["stale_points"]],
            ["INDEX_FAILED", "SYNC_FAILED"],
        )
        self.assertFalse(result["freshness"]["needs_sync"])

    def test_invalid_status_timeouts_do_not_run_codegraph(self) -> None:
        inspect_status, _ = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()
        descriptor = load_providers(ROOT)["codegraph"]
        invalid_timeouts = [
            (None, "none"),
            (float("nan"), "nan"),
            (float("inf"), "positive infinity"),
            (float("-inf"), "negative infinity"),
            (0, "zero"),
            (-1, "negative"),
            ("15", "string"),
            (True, "boolean"),
        ]
        for timeout, name in invalid_timeouts:
            with self.subTest(timeout=name):
                calls: list[list[str]] = []

                def runner(
                    command: list[str], **kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    return completed(healthy_status(self.repo))

                result = inspect_status(
                    self.repo,
                    descriptor,
                    runner=runner,
                    timeout_seconds=timeout,
                )

                self.assertEqual(result["status"], "NOT_VERIFIED")
                self.assertEqual(
                    result["stale_points"][0]["reason"], "STATUS_UNREADABLE"
                )
                self.assertEqual(calls, [])

    def test_invalid_sync_timeouts_do_not_run_codegraph(self) -> None:
        _, sync_if_needed = self.adapter_functions()
        (self.repo / ".codegraph").mkdir()
        descriptor = load_providers(ROOT)["codegraph"]
        invalid_timeouts = [
            ("status_timeout_seconds", None, "none"),
            ("status_timeout_seconds", float("nan"), "nan"),
            ("status_timeout_seconds", float("inf"), "positive infinity"),
            ("status_timeout_seconds", float("-inf"), "negative infinity"),
            ("status_timeout_seconds", 0, "zero"),
            ("status_timeout_seconds", -1, "negative"),
            ("status_timeout_seconds", "15", "string"),
            ("sync_timeout_seconds", None, "none"),
            ("sync_timeout_seconds", float("nan"), "nan"),
            ("sync_timeout_seconds", float("inf"), "positive infinity"),
            ("sync_timeout_seconds", float("-inf"), "negative infinity"),
            ("sync_timeout_seconds", 0, "zero"),
            ("sync_timeout_seconds", -1, "negative"),
            ("sync_timeout_seconds", "120", "string"),
        ]
        for parameter, timeout, name in invalid_timeouts:
            with self.subTest(parameter=parameter, timeout=name):
                calls: list[list[str]] = []

                def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                    calls.append(command)
                    self.fail("runner must not be called for an invalid timeout")

                arguments: dict[str, object] = {
                    "runner": runner,
                    parameter: timeout,
                }

                result = sync_if_needed(self.repo, descriptor, **arguments)

                self.assertEqual(result["freshness"]["status"], "NOT_VERIFIED")
                self.assertEqual(
                    result["freshness"]["stale_points"][0]["reason"],
                    "STATUS_UNREADABLE",
                )
                self.assertEqual(result["sync"]["status"], "SKIPPED")
                self.assertEqual(calls, [])

    def test_response_banner_marks_only_named_files_stale(self) -> None:
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("def widget():\n    return 1\n", encoding="utf-8")
        response = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/widget.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
"""

        result = self.classify_response(response)

        self.assertEqual(result["classification"], "PARTIAL_STALE")
        self.assertEqual(result["basis"], ["RESPONSE_BANNER"])
        self.assertEqual(result["stale_points"][0]["path"], "src/widget.py")
        self.assertEqual(result["stale_points"][0]["fallback"], "READ_SOURCE")
        self.assertEqual(
            result["stale_points"][0]["observed_sha256"], file_sha256(source)
        )

    def test_disabled_banner_freezes_the_whole_index(self) -> None:
        result = self.classify_response(
            "⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n"
        )

        self.assertEqual(result["classification"], "INDEX_STALE")
        self.assertEqual(result["basis"], ["RESPONSE_BANNER"])
        self.assertEqual(result["stale_points"][0]["reason"], "AUTO_SYNC_DISABLED")
        self.assertEqual(result["stale_points"][0]["fallback"], "SEARCH_SOURCE")

    def test_response_banner_rejects_unsafe_and_symlink_paths(self) -> None:
        outside = self.repo.parent / "outside.py"
        outside.write_text("outside\n", encoding="utf-8")
        link = self.repo / "src/link.py"
        link.parent.mkdir()
        link.symlink_to(outside)
        prefix = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
"""
        suffix = "For accurate content of those specific files, Read them directly.\n"
        for listed_path in ("../outside.py", outside.as_posix(), "src/link.py"):
            with self.subTest(listed_path=listed_path):
                result = self.classify_response(
                    f"{prefix}  - {listed_path} (edited 800ms ago, pending sync)\n{suffix}"
                )
                self.assertEqual(result["classification"], "NOT_VERIFIED")
                self.assertEqual(
                    result["stale_points"][0]["reason"], "STATUS_UNREADABLE"
                )

    def test_response_banner_missing_file_requires_git_diff(self) -> None:
        response = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/deleted.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
"""

        result = self.classify_response(response)

        self.assertEqual(result["classification"], "PARTIAL_STALE")
        self.assertEqual(result["stale_points"][0]["fallback"], "INSPECT_GIT_DIFF")
        self.assertIsNone(result["stale_points"][0]["observed_sha256"])

    def test_response_banner_normalizes_safe_windows_relative_paths(self) -> None:
        source = self.repo / "src/nested/widget.py"
        source.parent.mkdir(parents=True)
        source.write_text("def widget():\n    return 1\n", encoding="utf-8")
        prefix = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
"""
        suffix = "For accurate content of those specific files, Read them directly.\n"
        cases = [
            ("src\\nested\\widget.py", "READ_SOURCE", file_sha256(source)),
            ("src\\nested/deleted.py", "INSPECT_GIT_DIFF", None),
        ]

        for listed_path, fallback, digest in cases:
            with self.subTest(listed_path=listed_path):
                result = self.classify_response(
                    f"{prefix}  - {listed_path} (edited 800ms ago, pending sync)\n{suffix}"
                )

                self.assertEqual(result["classification"], "PARTIAL_STALE")
                point = result["stale_points"][0]
                self.assertEqual(
                    point["path"],
                    "src/nested/widget.py"
                    if fallback == "READ_SOURCE"
                    else "src/nested/deleted.py",
                )
                self.assertEqual(point["fallback"], fallback)
                self.assertEqual(point["observed_sha256"], digest)

    def test_response_banner_rejects_unsafe_windows_style_paths(self) -> None:
        prefix = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
"""
        suffix = "For accurate content of those specific files, Read them directly.\n"
        unsafe_paths = (
            "C:\\src\\widget.py",
            "C:/src/widget.py",
            "\\\\server\\share\\widget.py",
            "\\\\?\\C:\\src\\widget.py",
            "\\\\.\\PhysicalDrive0",
            "\\src\\widget.py",
            "/src/widget.py",
            "src\\\\widget.py",
            "src\\.\\widget.py",
            "src\\..\\outside.py",
        )

        for listed_path in unsafe_paths:
            with self.subTest(listed_path=listed_path):
                result = self.classify_response(
                    f"{prefix}  - {listed_path} (edited 800ms ago, pending sync)\n{suffix}"
                )

                self.assertEqual(result["classification"], "NOT_VERIFIED")
                self.assertEqual(
                    result["stale_points"][0]["reason"], "STATUS_UNREADABLE"
                )

    def test_suspicious_or_wrapped_freshness_warnings_are_not_verified(self) -> None:
        banner = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/deleted.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
"""
        samples = (
            "warning: graph may be stale\n",
            "⚠️ maybe stale: src/widget.py\n",
            "quoted: ⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n",
            "\ufeff⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n",
            " pending-sync required\n",
            f"context before banner\n{banner}",
            f"> {banner}",
            f"quoted response: {banner}",
            f" {banner}",
            f"\ufeff{banner}",
        )
        for response in samples:
            with self.subTest(response=response[:30]):
                result = self.classify_response(response)
                self.assertEqual(result["classification"], "NOT_VERIFIED")
                self.assertEqual(
                    result["stale_points"][0]["reason"], "STATUS_UNREADABLE"
                )
                self.assertEqual(
                    result["response_sha256"],
                    hashlib.sha256(response.encode("utf-8")).hexdigest(),
                )

    def test_merge_freshness_uses_conservative_status_and_ordered_evidence(self) -> None:
        merger = getattr(self.adapter_module(), "merge_freshness", None)
        self.assertTrue(callable(merger), "CodeGraph freshness merger must exist")
        status = {
            "status": "CURRENT_AT_CHECK",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
            "stale_points": [],
            "status_response_sha256": "status-sha",
            "error": None,
            "needs_sync": False,
            "pending_changes": {"added": 0, "modified": 0, "removed": 0},
        }
        response = self.classify_response(
            """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/deleted.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
"""
        )

        result = merger(status, response)

        self.assertEqual(result["status"], "PARTIAL_STALE")
        self.assertEqual(result["basis"], ["STATUS_JSON", "RESPONSE_BANNER"])
        self.assertEqual(result["stale_points"], response["stale_points"])
        self.assertEqual(result["status_response_sha256"], "status-sha")

    def test_none_response_does_not_upgrade_unverified_status(self) -> None:
        merger = getattr(self.adapter_module(), "merge_freshness", None)
        self.assertTrue(callable(merger), "CodeGraph freshness merger must exist")
        status = {
            "status": "NOT_VERIFIED",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
            "stale_points": [{"reason": "STATUS_UNREADABLE"}],
        }

        result = merger(status, self.classify_response("normal response\n"))

        self.assertEqual(result["status"], "NOT_VERIFIED")
        self.assertEqual(result["basis"], ["STATUS_JSON"])

    def test_none_response_suppression_projects_to_v2_unverified_and_unavailable_records(self) -> None:
        """A discarded neutral response must not leave unverifiable hash evidence."""
        self.initialize_task()
        merger = getattr(self.adapter_module(), "merge_freshness", None)
        self.assertTrue(callable(merger), "CodeGraph freshness merger must exist")
        response = self.classify_response("normal response\n")

        unverified = merger({
            "status": "NOT_VERIFIED",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
            "stale_points": [{
                "scope": "INDEX", "path": None, "reason": "STATUS_UNREADABLE",
                "fallback": "SEARCH_SOURCE", "observed_sha256": None,
            }],
            "error": "status unreadable",
        }, response)
        self.assertEqual(unverified["basis"], ["STATUS_JSON"])
        self.assertIsNone(unverified["response_sha256"])
        value = self.v2_record()
        value.update({
            "status": "FAILED",
            "provider": {
                "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                "available_operations": ["status"],
            },
            "status_check": {
                "status": "FAILED", "phase": "STAGE_ENTRY",
                "response_sha256": None, "error": "status unreadable",
            },
            "freshness": {
                "status": unverified["status"], "checked_at": unverified["checked_at"],
                "basis": unverified["basis"],
                "response_sha256": unverified["response_sha256"],
                "stale_points": unverified["stale_points"],
            },
            "source_fallbacks": [{
                "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
                "base_commit": None, "head_commit": None, "diff_hash": None,
                "purpose": "recover unreadable CodeGraph status", "result_paths": [],
            }],
        })
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

        unavailable = merger({
            "status": "UNAVAILABLE",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["NONE"],
            "stale_points": [],
            "error": "CodeGraph project marker is unavailable",
        }, response)
        self.assertEqual(unavailable["basis"], ["NONE"])
        self.assertIsNone(unavailable["response_sha256"])
        value = self.v2_record()
        value["freshness"] = {
            "status": unavailable["status"], "checked_at": unavailable["checked_at"],
            "basis": unavailable["basis"],
            "response_sha256": unavailable["response_sha256"],
            "stale_points": unavailable["stale_points"],
        }
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
        )

    def test_unavailable_merge_discards_every_response_conclusion(self) -> None:
        """A provider-neutral unavailable result cannot retain graph response evidence."""
        self.initialize_task()
        merger = getattr(self.adapter_module(), "merge_freshness", None)
        self.assertTrue(callable(merger), "CodeGraph freshness merger must exist")
        unavailable = {
            "status": "UNAVAILABLE",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["NONE"],
            "stale_points": [],
            "status_response_sha256": None,
            "error": "CodeGraph project marker is unavailable",
            "needs_sync": False,
            "pending_changes": None,
        }
        responses = (
            "normal response\n",
            "⚠️ Some files referenced below were edited since the last index sync —\n"
            "their codegraph entries may be stale:\n"
            "  - src/deleted.py (edited 800ms ago, pending sync)\n"
            "For accurate content of those specific files, Read them directly.\n",
            "⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n",
            "⚠️ Some files referenced below were edited since the last index sync —\n"
            "their codegraph entries may be stale:\n",
        )

        for response_text in responses:
            with self.subTest(response=response_text[:24]):
                response = self.classify_response(response_text)
                merged = merger(unavailable, response)
                self.assertEqual(merged["status"], "UNAVAILABLE")
                self.assertEqual(merged["basis"], ["NONE"])
                self.assertEqual(merged["stale_points"], [])
                self.assertIsNone(merged["response_sha256"])
                value = self.v2_record()
                value["freshness"] = {
                    "status": merged["status"],
                    "checked_at": merged["checked_at"],
                    "basis": merged["basis"],
                    "response_sha256": merged["response_sha256"],
                    "stale_points": merged["stale_points"],
                }
                self.assertEqual(
                    validate_record_value(
                        self.repo, "TASK-0001", value, ROOT
                    )["record_version"],
                    2,
                )

    def test_retained_response_evidence_projects_to_v2_with_matching_explore_hash(self) -> None:
        """Retained neutral and banner evidence binds the recorded explore response."""
        self.initialize_task()
        merger = getattr(self.adapter_module(), "merge_freshness", None)
        self.assertTrue(callable(merger), "CodeGraph freshness merger must exist")
        status = {
            "status": "CURRENT_AT_CHECK",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
            "stale_points": [],
            "status_response_sha256": "1" * 64,
            "error": None,
        }
        source = self.repo / "src/widget.py"
        source.parent.mkdir()
        source.write_text("def widget():\n    return 1\n", encoding="utf-8")
        responses = [
            ("normal response\n", []),
            (
                "⚠️ Some files referenced below were edited since the last index sync —\n"
                "their codegraph entries may be stale:\n"
                "  - src/widget.py (edited 800ms ago, pending sync)\n"
                "For accurate content of those specific files, Read them directly.\n",
                [{
                    "action": "READ_SOURCE", "path": "src/widget.py",
                    "observed_sha256": file_sha256(source), "base_commit": None,
                    "head_commit": None, "diff_hash": None,
                    "purpose": "read CodeGraph stale file from source",
                    "result_paths": [],
                }],
            ),
            (
                "⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n",
                [{
                    "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
                    "base_commit": None, "head_commit": None, "diff_hash": None,
                    "purpose": "recover stale CodeGraph index", "result_paths": [],
                }],
            ),
            (
                "⚠️ Some files referenced below were edited since the last index sync —\n"
                "their codegraph entries may be stale:\n",
                [{
                    "action": "SEARCH_SOURCE", "path": None, "observed_sha256": None,
                    "base_commit": None, "head_commit": None, "diff_hash": None,
                    "purpose": "recover unreadable CodeGraph response", "result_paths": [],
                }],
            ),
        ]

        for response_text, source_fallbacks in responses:
            with self.subTest(response=response_text[:24]):
                response = self.classify_response(response_text)
                merged = merger(status, response)
                self.assertIn("RESPONSE_BANNER", merged["basis"])
                self.assertEqual(merged["response_sha256"], response["response_sha256"])
                value = self.v2_record()
                value.update({
                    "status": "USED",
                    "provider": {
                        "id": "codegraph", "descriptor_version": 2, "transport": "mcp",
                        "available_operations": ["explore", "status"],
                    },
                    "queries": [{
                        "id": "CIQ-001", "operation": "explore",
                        "purpose": "inspect CodeGraph response freshness", "status": "SUCCESS",
                        "summary": "CodeGraph response", "symbols": [],
                        "response_sha256": merged["response_sha256"], "error": None,
                    }],
                    "status_check": {
                        "status": "SUCCESS", "phase": "STAGE_ENTRY",
                        "response_sha256": status["status_response_sha256"], "error": None,
                    },
                    "freshness": {
                        "status": merged["status"], "checked_at": merged["checked_at"],
                        "basis": merged["basis"],
                        "response_sha256": merged["response_sha256"],
                        "stale_points": merged["stale_points"],
                    },
                    "source_fallbacks": source_fallbacks,
                })
                self.assertEqual(
                    validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"], 2
                )

    def test_none_response_records_banner_check_after_successful_stale_status(self) -> None:
        merger = getattr(self.adapter_module(), "merge_freshness", None)
        self.assertTrue(callable(merger), "CodeGraph freshness merger must exist")
        status = {
            "status": "INDEX_STALE",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
            "stale_points": [{"reason": "INDEX_FAILED"}],
        }

        result = merger(status, self.classify_response("normal response\n"))

        self.assertEqual(result["status"], "INDEX_STALE")
        self.assertEqual(result["basis"], ["STATUS_JSON", "RESPONSE_BANNER"])

    def test_malformed_recognized_banner_downgrades_status(self) -> None:
        merger = getattr(self.adapter_module(), "merge_freshness", None)
        self.assertTrue(callable(merger), "CodeGraph freshness merger must exist")
        status = {
            "status": "CURRENT_AT_CHECK",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
            "stale_points": [],
        }
        response = self.classify_response(
            "⚠️ Some files referenced below were edited since the last index sync —\n"
            "their codegraph entries may be stale:\n"
        )

        result = merger(status, response)

        self.assertEqual(response["classification"], "NOT_VERIFIED")
        self.assertEqual(result["status"], "NOT_VERIFIED")

    def test_runtime_classify_response_confines_input_and_emits_json(self) -> None:
        (self.repo / ".codegraph").mkdir()
        (self.repo / "README.md").write_text("test repository\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Polaris Test",
                "-c",
                "user.email=polaris@example.test",
                "commit",
                "-qm",
                "initialize test repository",
            ],
            cwd=self.repo,
            check=True,
        )
        init_task(self.repo, "TASK-0001", "R1")
        runtime = self.repo / ".polaris/tasks/TASK-0001/runtime/code-intelligence"
        runtime.mkdir()
        response_path = runtime / "response.txt"
        response_path.write_text(
            """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/deleted.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
""",
            encoding="utf-8",
        )
        command = [
            sys.executable,
            SCRIPTS / "code_intelligence_runtime.py",
            "classify-response",
            "TASK-0001",
            "--input",
            response_path,
            "--repo",
            self.repo,
            "--json",
        ]

        completed_process = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, check=False
        )

        self.assertEqual(completed_process.returncode, 0, completed_process.stderr)
        payload = json.loads(completed_process.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["classification"], "PARTIAL_STALE")

        outside = self.repo / "response.txt"
        outside.write_text("normal response\n", encoding="utf-8")
        outside_command = [*command]
        outside_command[outside_command.index(response_path)] = outside
        rejected = subprocess.run(
            outside_command, cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(rejected.returncode, 2)
        rejected_payload = json.loads(rejected.stdout)
        self.assertEqual(rejected_payload["status"], "ERROR")
        self.assertIn("runtime", rejected_payload["message"])

    def test_runtime_disabled_mode_skips_status_and_sync_without_calling_codegraph(self) -> None:
        """Disabled projects never load or invoke the optional provider runtime."""
        (self.repo / ".codegraph").mkdir()
        write_json_atomic(
            self.repo / ".polaris" / "code-intelligence.json",
            {
                "config_version": 1,
                "mode": "disabled",
                "provider_priority": [],
                "include": [],
                "exclude": [],
            },
        )
        runtime = importlib.import_module("code_intelligence_runtime")
        expected_freshness = {
            "status": "UNAVAILABLE",
            "basis": ["NONE"],
            "stale_points": [],
            "status_response_sha256": None,
            "error": "Code Intelligence is disabled by project configuration",
            "needs_sync": False,
            "pending_changes": None,
        }
        for command in ("status", "sync-if-needed"):
            with self.subTest(command=command):
                output = io.StringIO()
                with (
                    mock.patch.object(sys, "argv", ["code_intelligence_runtime.py", command, "--repo", str(self.repo), "--json"]),
                    mock.patch.object(runtime, "load_providers", side_effect=AssertionError("descriptor must not be loaded")) as providers,
                    mock.patch.object(runtime, "inspect_status", side_effect=AssertionError("CodeGraph status must not run")) as status,
                    mock.patch.object(runtime, "sync_if_needed", side_effect=AssertionError("CodeGraph sync must not run")) as sync,
                    redirect_stdout(output),
                ):
                    self.assertEqual(runtime.main(), 0)

                payload = json.loads(output.getvalue())
                freshness = payload if command == "status" else payload["freshness"]
                self.assertEqual(
                    {key: freshness[key] for key in expected_freshness},
                    expected_freshness,
                )
                if command == "sync-if-needed":
                    self.assertEqual(payload["status"], "PASS")
                    self.assertEqual(
                        payload["sync"],
                        {"status": "UNAVAILABLE", "response_sha256": None, "error": None},
                    )
                providers.assert_not_called()
                status.assert_not_called()
                sync.assert_not_called()

    def test_runtime_classify_disabled_skips_input_descriptor_and_classifier(self) -> None:
        """A disabled project does not inspect a raw CodeGraph response."""
        (self.repo / ".codegraph").mkdir()
        write_json_atomic(
            self.repo / ".polaris" / "code-intelligence.json",
            {
                "config_version": 1,
                "mode": "disabled",
                "provider_priority": [],
                "include": [],
                "exclude": [],
            },
        )
        runtime = importlib.import_module("code_intelligence_runtime")
        output = io.StringIO()
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "code_intelligence_runtime.py",
                    "classify-response",
                    "TASK-0001",
                    "--input",
                    "must-not-be-read.txt",
                    "--repo",
                    str(self.repo),
                    "--json",
                ],
            ),
            mock.patch.object(
                runtime,
                "_runtime_input",
                side_effect=AssertionError("response input must not be read"),
            ) as input_path,
            mock.patch.object(
                runtime,
                "load_providers",
                side_effect=AssertionError("descriptor must not be loaded"),
            ) as providers,
            mock.patch.object(
                runtime,
                "classify_response",
                side_effect=AssertionError("response must not be classified"),
            ) as classifier,
            redirect_stdout(output),
        ):
            self.assertEqual(runtime.main(), 0)

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "UNAVAILABLE")
        self.assertEqual(payload["basis"], ["NONE"])
        self.assertEqual(payload["stale_points"], [])
        self.assertEqual(payload["status_response_sha256"], None)
        self.assertEqual(
            payload["error"], "Code Intelligence is disabled by project configuration"
        )
        self.assertFalse(payload["needs_sync"])
        self.assertIsNone(payload["pending_changes"])
        input_path.assert_not_called()
        providers.assert_not_called()
        classifier.assert_not_called()

    def test_runtime_classify_without_safe_marker_skips_input_descriptor_and_classifier(self) -> None:
        """An absent or symlinked marker never authorizes response parsing."""
        runtime = importlib.import_module("code_intelligence_runtime")
        marker = self.repo / ".codegraph"
        target = self.repo / "marker-target"
        target.mkdir()

        for unsafe_marker in (False, True):
            with self.subTest(unsafe_marker=unsafe_marker):
                if marker.exists() or marker.is_symlink():
                    marker.unlink()
                if unsafe_marker:
                    marker.symlink_to(target, target_is_directory=True)
                output = io.StringIO()
                with (
                    mock.patch.object(
                        sys,
                        "argv",
                        [
                            "code_intelligence_runtime.py",
                            "classify-response",
                            "TASK-0001",
                            "--input",
                            "must-not-be-read.txt",
                            "--repo",
                            str(self.repo),
                            "--json",
                        ],
                    ),
                    mock.patch.object(
                        runtime,
                        "_runtime_input",
                        side_effect=AssertionError("response input must not be read"),
                    ) as input_path,
                    mock.patch.object(
                        runtime,
                        "load_providers",
                        side_effect=AssertionError("descriptor must not be loaded"),
                    ) as providers,
                    mock.patch.object(
                        runtime,
                        "classify_response",
                        side_effect=AssertionError("response must not be classified"),
                    ) as classifier,
                    redirect_stdout(output),
                ):
                    self.assertEqual(runtime.main(), 0)

                payload = json.loads(output.getvalue())
                self.assertEqual(payload["status"], "UNAVAILABLE")
                self.assertEqual(payload["basis"], ["NONE"])
                self.assertEqual(payload["stale_points"], [])
                self.assertEqual(payload["status_response_sha256"], None)
                self.assertEqual(
                    payload["error"], "CodeGraph project marker is unavailable"
                )
                self.assertFalse(payload["needs_sync"])
                self.assertIsNone(payload["pending_changes"])
                input_path.assert_not_called()
                providers.assert_not_called()
                classifier.assert_not_called()

    def test_runtime_rejects_symlinked_runtime_directory_before_reading(self) -> None:
        (self.repo / ".codegraph").mkdir()
        (self.repo / "README.md").write_text("test repository\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Polaris Test",
                "-c",
                "user.email=polaris@example.test",
                "commit",
                "-qm",
                "initialize test repository",
            ],
            cwd=self.repo,
            check=True,
        )
        init_task(self.repo, "TASK-0001", "R1")
        runtime = self.repo / ".polaris/tasks/TASK-0001/runtime"
        outside = self.repo / "outside-runtime"
        external_runtime = outside / "code-intelligence"
        external_runtime.mkdir(parents=True)
        response_path = external_runtime / "response.txt"
        response_path.write_text("normal response\n", encoding="utf-8")
        runtime.rmdir()
        runtime.symlink_to(outside, target_is_directory=True)

        completed_process = subprocess.run(
            [
                sys.executable,
                SCRIPTS / "code_intelligence_runtime.py",
                "classify-response",
                "TASK-0001",
                "--input",
                runtime / "code-intelligence/response.txt",
                "--repo",
                self.repo,
                "--json",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed_process.returncode, 2)
        payload = json.loads(completed_process.stdout)
        self.assertEqual(payload["status"], "ERROR")
        self.assertIn("symlink", payload["message"])

    @unittest.skipUnless(shutil.which("codegraph"), "codegraph CLI is not installed")
    def test_real_codegraph_status_shape_when_cli_is_available(self) -> None:
        """The optional CLI smoke test may initialize only its disposable repository."""
        temporary_repo = validated_disposable_codegraph_repo(self.repo, self.temp.name)

        source = self.repo / "sample.py"
        source.write_text("def sample():\n    return 1\n", encoding="utf-8")
        subprocess.run(
            ["codegraph", "init", str(temporary_repo)],
            cwd=temporary_repo,
            check=True,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=120,
            shell=False,
        )

        descriptor = load_providers(ROOT)["codegraph"]
        result = self.adapter_module().inspect_status(
            temporary_repo, descriptor, timeout_seconds=30
        )
        self.assertEqual(result["status"], "CURRENT_AT_CHECK")

    def test_real_cli_fixture_rejects_temporary_paths_nested_in_workspace(self) -> None:
        """A hostile TMPDIR beneath the workspace must never become an init target."""
        nested_workspace_temp = ROOT / "nested-temporary-repository"

        with self.assertRaisesRegex(AssertionError, "must not be inside the workspace"):
            validated_disposable_codegraph_repo(
                nested_workspace_temp, nested_workspace_temp
            )

        workspace_alias = self.repo / "workspace-alias"
        try:
            workspace_alias.symlink_to(ROOT, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks are not available: {error}")
        with self.assertRaisesRegex(AssertionError, "must not be inside the workspace"):
            validated_disposable_codegraph_repo(workspace_alias, workspace_alias)
