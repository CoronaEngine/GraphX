from __future__ import annotations

import importlib
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
from internal.code_intelligence_protocol import (  # noqa: E402
    _project_marker_path,
    load_providers,
    select_provider,
)
from internal.polaris_core import RuleFailure, file_sha256  # noqa: E402


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


class CodeGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="polaris-codegraph-")
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        init_project(self.repo, "codegraph-test")

    def tearDown(self) -> None:
        self.temp.cleanup()

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

    def test_record_cli_requires_task_id_and_input(self) -> None:
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
        self.assertEqual(payload["message"], "recording requires task_id and --input")

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

        self.assertEqual(result["status"], "NOT_VERIFIED")
        self.assertEqual(result["stale_points"][0]["reason"], "STATUS_UNREADABLE")

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

    def test_unhealthy_recheck_preserves_index_reason_and_adds_sync_failure(self) -> None:
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
        self.assertEqual(result["sync"]["status"], "SUCCESS")
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

    def test_arbitrary_warning_is_not_a_codegraph_banner(self) -> None:
        result = self.classify_response("⚠️ maybe stale: src/widget.py\n")

        self.assertEqual(result["classification"], "NONE")
        self.assertEqual(result["stale_points"], [])

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
