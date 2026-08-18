from __future__ import annotations

import importlib
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
            self.assertIn("0.1.19", text, path.relative_to(ROOT).as_posix())
            self.assertIn("0.1.2", text, path.relative_to(ROOT).as_posix())

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
            (ROOT / "templates" / "task-sources" / "code-intelligence-record.json").read_text(
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

    def initialize_task(self) -> None:
        init_task(self.repo, "TASK-0001", "R1")

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
            InputFailure, "new Code Intelligence records must use record_version 2"
        ):
            record(self.repo, "TASK-0001", value, ROOT)

    def test_migration_retires_v1_records_without_rewriting_them(self) -> None:
        """0.1.19 inventories frozen v1 evidence while leaving its bytes intact."""
        self.initialize_task()
        self.set_protocol_version("0.1.18")
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

        self.assertEqual(result["from"], "0.1.18")
        self.assertEqual(result["to"], "0.1.19")
        self.assertEqual(
            json.loads((self.repo / ".polaris/project.json").read_text(encoding="utf-8"))["workflow_version"],
            "0.1.2",
        )
        migration = json.loads(
            (
                self.repo
                / ".polaris/migrations/MIG-0.1.18-to-0.1.19.json"
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
        result = record(self.repo, "TASK-0001", current, ROOT)
        self.assertTrue(result["path"].endswith("code-intelligence/r001/implementation-001.json"))

    def test_migration_rejects_noncanonical_v2_record_paths(self) -> None:
        """Migration scans only the canonical Code Intelligence record layout."""
        self.initialize_task()
        self.set_protocol_version("0.1.18")
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
        self.set_protocol_version("0.1.18")
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
                / ".polaris/migrations/MIG-0.1.18-to-0.1.19.json"
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
        self.set_protocol_version("0.1.18")
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
        self.assertEqual(
            validate_record_value(self.repo, "TASK-0001", value, ROOT)["record_version"],
            2,
        )

    def test_unavailable_record_cannot_claim_response_banner_evidence(self) -> None:
        self.initialize_task()
        value = self.v2_record()
        value["freshness"] = {
            "status": "UNAVAILABLE",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["RESPONSE_BANNER"],
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
                    "diff_hash": None, "purpose": "read stale response source",
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
                    "purpose": "search frozen CodeGraph index scope",
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
                    "purpose": "search after unreadable CodeGraph response",
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
        }
        value["status"] = "SKIPPED"
        value["freshness"] = {
            "status": "CURRENT_AT_CHECK",
            "checked_at": "2026-08-18T00:00:00Z",
            "basis": ["STATUS_JSON"],
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
            "stale_points": [{
                "scope": "FILE", "path": "src/widget.py", "reason": "PENDING_SYNC",
                "fallback": "READ_SOURCE", "observed_sha256": digest,
            }],
        }
        self.add_explore_response_evidence(value)
        value["source_fallbacks"] = [{
            "action": "READ_SOURCE", "path": "src/widget.py", "observed_sha256": "0" * 64,
            "base_commit": None, "head_commit": None, "diff_hash": None, "purpose": "read source",
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
                "purpose": "recover unavailable CodeGraph evidence",
            }],
        })
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
                "stale_points": [{
                    "scope": "FILE", "path": "src/widget.py", "reason": "PENDING_SYNC",
                    "fallback": "INSPECT_GIT_DIFF", "observed_sha256": None,
                }],
            },
            "source_fallbacks": [{
                "action": "INSPECT_GIT_DIFF", "path": "src/widget.py",
                "observed_sha256": None, "base_commit": base, "head_commit": added_head,
                "diff_hash": subject_diff_hash(self.repo, base, added_head), "purpose": "inspect change",
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
                        "basis": result["basis"], "stale_points": result["stale_points"],
                    },
                    "source_fallbacks": [{
                        "action": "SEARCH_SOURCE", "path": None,
                        "observed_sha256": None, "base_commit": None,
                        "head_commit": None, "diff_hash": None,
                        "purpose": "recover unreadable CodeGraph status",
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
                    "basis": freshness["basis"], "stale_points": freshness["stale_points"],
                },
                "source_fallbacks": ([{
                    "action": "SEARCH_SOURCE", "path": None,
                    "observed_sha256": None, "base_commit": None,
                    "head_commit": None, "diff_hash": None,
                    "purpose": "recover stale CodeGraph evidence",
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
            "purpose": "recover stale CodeGraph index",
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
                "basis": ["STATUS_JSON"], "stale_points": [{
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

    def test_arbitrary_warning_is_not_a_codegraph_banner(self) -> None:
        result = self.classify_response("⚠️ maybe stale: src/widget.py\n")

        self.assertEqual(result["classification"], "NONE")
        self.assertEqual(result["stale_points"], [])

    def test_prefixed_or_quoted_official_banner_is_not_recognized(self) -> None:
        banner = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/deleted.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
"""
        for response in (
            f"context before banner\n{banner}",
            f"> {banner}",
            f"quoted response: {banner}",
            f" {banner}",
            f"\ufeff{banner}",
        ):
            with self.subTest(response=response[:20]):
                result = self.classify_response(response)
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

    def test_runtime_rejects_symlinked_runtime_directory_before_reading(self) -> None:
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
