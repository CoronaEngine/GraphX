# CodeGraph Freshness Integration Implementation Plan

> **Historical plan:** This v2 plan has been superseded by
> `docs/superpowers/plans/2026-08-19-codegraph-polaris-mcp-proxy.md`.
> Current stages must use only `polaris_codegraph_explore`; the direct
> status/sync/raw-explore instructions below are retained solely as migration
> history and cannot support new Polaris `CURRENT` evidence.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `colbymchenry/codegraph` the only formal `codegraph` Provider, keep its graph current with watcher-aware one-shot sync, and record precise stale points that force bounded source fallback.

**Architecture:** Keep Provider selection and immutable evidence Provider-neutral, while a focused CodeGraph adapter owns the official CLI/status/banner contract. Stage Skills use `codegraph_explore` first, CLI as fallback, and persist v2 freshness records; legacy v1 records remain read-only historical evidence.

**Tech Stack:** Python 3.10+ standard library, JSON artifacts and Schemas, `unittest`, Git, optional external `codegraph` CLI/MCP.

**Spec:** `docs/superpowers/specs/2026-08-18-codegraph-freshness-design.md`

## Global Constraints

- `plan.md` remains the v0.1 product and implementation authority.
- Runtime code must remain dependency-free beyond the Python standard library.
- `codegraph` means only `https://github.com/colbymchenry/codegraph`.
- Polaris may run `codegraph sync` once when needed, but must not install CodeGraph, run `codegraph init`, start a daemon, or modify MCP configuration.
- `.codegraph/` creation remains a user decision; its absence is a non-blocking `UNAVAILABLE` result.
- CodeGraph evidence never replaces source, Git, builds, tests, Validation, Review, or Human gates.
- Polaris workflow version remains exactly `0.1.2`; only the Polaris protocol version advances from `0.1.18` to `0.1.19`.
- Every subprocess call must use an argument list, explicit `cwd`, finite timeout, and no shell.
- Repository paths stored in artifacts use POSIX separators and pass existing confinement/regular-file checks.
- Agents never write `VERIFIED` or `CLOSED`; all state transitions continue through `transition_task.py`.
- Generated `templates/task/` files are refreshed only through `python scripts/materialize_task_layout.py`.

## File Structure

- `providers/code-intelligence/codegraph.json`: the sole formal descriptor for the official Provider.
- `scripts/internal/codegraph_adapter.py`: CodeGraph-specific status, one-shot sync, banner classification, and freshness merge logic.
- `scripts/internal/code_intelligence_protocol.py`: Provider-neutral config, selection, v2/legacy record validation, immutable record writes.
- `scripts/code_intelligence_runtime.py`: internal `status`, `sync-if-needed`, and `classify-response` dispatcher used by Skills.
- `scripts/record_code_intelligence.py`: immutable record CLI only; old refresh planning flags are removed.
- `schemas/code-intelligence-provider.schema.json`: descriptor v2 structure.
- `schemas/code-intelligence-record.schema.json`: writable v2 evidence.
- `schemas/code-intelligence-record-v1.schema.json`: frozen read-only legacy evidence shape.
- `schemas/migration-record.schema.json`: optional retired-evidence inventory on new migration records.
- `templates/task-sources/code-intelligence-record.json`: canonical v2 template source.
- `templates/task/code-intelligence/r001/planning.json`: generated sample projection.
- `tests/test_codegraph.py`: focused Provider/adapter/runtime/record tests.
- `tests/test_core.py`: existing migration, vendoring, materialization, and whole-protocol assertions.
- `skills/*/SKILL.md` and `templates/AGENTS.md`: stage usage and source-fallback rules.
- `VERSION`, `pyproject.toml`, `templates/project.json`, task state templates, `workflow/migrations.json`: protocol `0.1.19` migration assets; workflow remains `0.1.2`.
- `README.md`, `docs/USAGE.md`, `plan.md`: official Provider and operational documentation.

---

### Task 1: Replace the Provider descriptor and require an initialized graph

**Files:**
- Modify: `providers/code-intelligence/codegraph.json`
- Modify: `schemas/code-intelligence-provider.schema.json`
- Modify: `scripts/internal/code_intelligence_protocol.py:73-183`
- Modify: `scripts/record_code_intelligence.py:23-56`
- Create: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: `.polaris/code-intelligence.json`, `.codegraph/`, host-exposed tool names, executable names discovered by the caller.
- Produces: `select_provider(repo: Path, available_tools: Iterable[str], root: Path | None = None, available_executables: Iterable[str] = ()) -> dict[str, Any] | None`.
- Produces selected descriptor fields: `provider_id`, `provider_version`, `transport`, `operations`, `cli_available`.

- [ ] **Step 1: Add failing descriptor and activation tests**

Create `tests/test_codegraph.py` with a small standard-library fixture and these concrete assertions:

```python
from __future__ import annotations

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
from internal.code_intelligence_protocol import (  # noqa: E402
    load_providers,
    select_provider,
)


class CodeGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="polaris-codegraph-")
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        init_project(self.repo, "codegraph-test")

    def tearDown(self) -> None:
        self.temp.cleanup()

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

    def test_old_product_tool_names_are_absent_from_descriptor(self) -> None:
        text = (ROOT / "providers/code-intelligence/codegraph.json").read_text(
            encoding="utf-8"
        )
        for fragment in ("get_ai_context", "index_files", "reindex_workspace"):
            self.assertNotIn(fragment, text)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m unittest tests.test_codegraph.CodeGraphTests.test_official_descriptor_uses_explore_status_and_sync tests.test_codegraph.CodeGraphTests.test_provider_requires_marker_and_accepts_mcp_or_cli -v
```

Expected: FAIL because descriptor v1 lacks `implementation`, `project_marker`, `cli`, and selection does not require `.codegraph/`.

- [ ] **Step 3: Implement descriptor v2 and marker-aware selection**

Change the descriptor to this shape, using the target Provider's documented extension set (case-insensitive matching means one `.r` entry covers both `.R` and `.r`):

```json
{
    "provider_version": 2,
    "provider_id": "codegraph",
    "display_name": "CodeGraph",
    "implementation": "https://github.com/colbymchenry/codegraph",
    "project_marker": ".codegraph",
    "transport": "mcp",
    "file_extensions": [
        ".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".go", ".rs",
        ".java", ".cs", ".php", ".rb", ".c", ".h", ".cpp", ".hpp",
        ".cc", ".m", ".mm", ".swift", ".kt", ".kts", ".scala", ".sc",
        ".dart", ".svelte", ".vue", ".astro", ".liquid", ".pas", ".dpr",
        ".dpk", ".lpr", ".lua", ".r", ".luau"
    ],
    "operations": {
        "explore": "codegraph_explore",
        "status": "codegraph_status"
    },
    "cli": {
        "executable": "codegraph",
        "explore_args": ["explore"],
        "status_args": ["status", "--json"],
        "sync_args": ["sync", "--quiet"]
    }
}
```

Update the Provider Schema so `provider_version` is `2`, all new fields are required, CLI argument arrays have `minItems: 1`, and every item is a non-empty string. Replace `OPERATIONS` with `{"explore", "status", "sync"}`. Add a helper that rejects absolute, multi-component, or symlink markers and make selection require a regular `.codegraph/` directory. Preserve `add_provider()` as configuration-only and update its message to say initialization remains the user's decision.

Remove `--plan-refresh`, `--provider`, `--subject-base`, and `--subject-head` from `record_code_intelligence.py`; runtime sync moves to Task 3. Add repeatable `--available-executable` beside `--available-tool` and pass both lists to `select_provider()`, so a non-MCP worker can select the initialized Provider without probing or executing it during selection.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
python -m unittest tests.test_codegraph -v
```

Expected: all Task 1 tests PASS.

- [ ] **Step 5: Run static configuration regression tests**

Run:

```bash
python -m unittest tests.test_core.PolarisCoreTests.test_code_intelligence_add_enables_prioritizes_and_preserves_scope tests.test_core.PolarisCoreTests.test_code_intelligence_add_rejects_unknown_provider_without_writing -v
```

Expected: PASS after updating only assertions that describe the new initialization message; config scope remains unchanged.

- [ ] **Step 6: Commit Task 1**

```bash
git add providers/code-intelligence/codegraph.json schemas/code-intelligence-provider.schema.json scripts/internal/code_intelligence_protocol.py scripts/record_code_intelligence.py tests/test_codegraph.py tests/test_core.py
git commit -m "feat: select the official CodeGraph provider"
```

---

### Task 2: Add deterministic status inspection and one-shot sync

**Files:**
- Create: `scripts/internal/codegraph_adapter.py`
- Modify: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: descriptor v2 CLI fields and official `codegraph status --json` output.
- Produces: `inspect_status(repo: Path, descriptor: dict[str, Any], *, runner: Runner = subprocess.run, timeout_seconds: int = 15) -> dict[str, Any]`.
- Produces: `sync_if_needed(repo: Path, descriptor: dict[str, Any], *, runner: Runner = subprocess.run, status_timeout_seconds: int = 15, sync_timeout_seconds: int = 120) -> dict[str, Any]`.
- Inspection result keys: `status`, `checked_at`, `basis`, `stale_points`, `status_response_sha256`, `error`, `needs_sync`, `pending_changes`.
- Sync result keys: `freshness`, `sync` where sync has `status`, `response_sha256`, `error`.

- [ ] **Step 1: Add failing healthy and pending-sync tests**

Add `importlib`, a completed-process factory, and a test helper that first asserts `scripts/internal/codegraph_adapter.py` exists, then imports it inside the test. This makes RED an assertion failure instead of a collection/import error. Use the helper to obtain `inspect_status` and `sync_if_needed`, then add these tests:

```python
def completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)

def healthy_status(project: Path) -> str:
    return json.dumps({
        "initialized": True,
        "projectPath": str(project),
        "pendingChanges": {"added": 0, "modified": 0, "removed": 0},
        "worktreeMismatch": None,
        "index": {
            "state": "complete",
            "pendingRefs": 0,
            "reindexRecommended": False,
        },
    })

def test_healthy_status_is_current_at_check(self) -> None:
    (self.repo / ".codegraph").mkdir()
    descriptor = load_providers(ROOT)["codegraph"]
    result = inspect_status(
        self.repo, descriptor, runner=lambda *args, **kwargs: completed(healthy_status(self.repo))
    )
    self.assertEqual(result["status"], "CURRENT_AT_CHECK")
    self.assertEqual(result["basis"], ["STATUS_JSON"])
    self.assertEqual(result["stale_points"], [])

def test_pending_changes_sync_once_and_recheck_once(self) -> None:
    (self.repo / ".codegraph").mkdir()
    pending = json.loads(healthy_status(self.repo))
    pending["pendingChanges"]["modified"] = 1
    responses = iter([
        completed(json.dumps(pending)),
        completed("Synced 1 changed file\n"),
        completed(healthy_status(self.repo)),
    ])
    calls: list[list[str]] = []
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return next(responses)
    result = sync_if_needed(self.repo, load_providers(ROOT)["codegraph"], runner=runner)
    self.assertEqual([call[1] for call in calls], ["status", "sync", "status"])
    self.assertEqual(result["sync"]["status"], "SUCCESS")
    self.assertEqual(result["freshness"]["status"], "CURRENT_AT_CHECK")
    self.assertIn("SYNC_ACKNOWLEDGED", result["freshness"]["basis"])
```

- [ ] **Step 2: Add failing table tests for every index-wide stale reason**

Use `subTest` cases for:

```python
cases = [
    ({"worktreeMismatch": {"worktreeRoot": "/a", "indexRoot": "/b"}}, "WORKTREE_MISMATCH"),
    ({"index": {"state": "partial", "pendingRefs": 0, "reindexRecommended": False}}, "INDEX_PARTIAL"),
    ({"index": {"state": "indexing", "pendingRefs": 0, "reindexRecommended": False}}, "INDEX_INDEXING"),
    ({"index": {"state": "failed", "pendingRefs": 0, "reindexRecommended": False}}, "INDEX_FAILED"),
    ({"index": {"state": "complete", "pendingRefs": 2, "reindexRecommended": False}}, "PENDING_REFERENCES"),
    ({"index": {"state": "complete", "pendingRefs": 0, "reindexRecommended": True}}, "REINDEX_RECOMMENDED"),
]
```

Assert every result is `INDEX_STALE`, has one `scope: INDEX` point with the expected reason, `fallback: SEARCH_SOURCE`, and does not call sync when the status is structurally unsafe rather than merely pending.

- [ ] **Step 3: Run Task 2 tests and verify RED**

```bash
python -m unittest tests.test_codegraph -v
```

Expected: FAIL on the explicit missing-adapter assertion.

- [ ] **Step 4: Implement status normalization and one-shot sync**

Implement the public functions around these internal boundaries:

```python
Runner = Callable[..., subprocess.CompletedProcess[str]]

def _run_cli(
    repo: Path,
    descriptor: dict[str, Any],
    args_key: str,
    timeout_seconds: int,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    command = [descriptor["cli"]["executable"], *descriptor["cli"][args_key]]
    return runner(
        command,
        cwd=repo,
        check=False,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout_seconds,
    )
```

Normalize paths with `Path(...).resolve()` and compare them to `repo.resolve()`. Convert timeout, missing executable, Unicode errors, nonzero exit, malformed JSON, wrong project, and invalid field types to `STATUS_UNREADABLE` or the more specific index reason. Compute response hashes with `hashlib.sha256(raw.encode("utf-8")).hexdigest()`. A structurally healthy status with nonzero pending counts returns `needs_sync: true` and preserves the counts in `pending_changes`; this intermediate inspection is not written as a final freshness record.

`sync_if_needed()` must return immediately for healthy status, call sync only when pending counts are nonzero, and never recurse. A nonzero sync or unhealthy second status produces `INDEX_STALE` with `SYNC_FAILED` while preserving more specific second-status points.

- [ ] **Step 5: Run focused tests and verify GREEN**

```bash
python -m unittest tests.test_codegraph -v
```

Expected: all adapter status/sync tests PASS and recorded command sequence is exactly `status`, `sync`, `status`.

- [ ] **Step 6: Commit Task 2**

```bash
git add scripts/internal/codegraph_adapter.py tests/test_codegraph.py
git commit -m "feat: inspect and sync CodeGraph freshness"
```

---

### Task 3: Classify stale banners and expose the internal runtime script

**Files:**
- Modify: `scripts/internal/codegraph_adapter.py`
- Create: `scripts/code_intelligence_runtime.py`
- Modify: `tests/test_codegraph.py`

**Interfaces:**
- Produces: `classify_response(repo: Path, response: str, *, checked_at: str | None = None) -> dict[str, Any]` with `classification` equal to `NONE`, `PARTIAL_STALE`, `INDEX_STALE`, or `NOT_VERIFIED`.
- Produces: `merge_freshness(status_result: dict[str, Any], response_result: dict[str, Any]) -> dict[str, Any]`.
- Runtime commands:
  - `python scripts/code_intelligence_runtime.py status --repo PATH --json`
  - `python scripts/code_intelligence_runtime.py sync-if-needed --repo PATH --json`
  - `python scripts/code_intelligence_runtime.py classify-response TASK-0001 --input PATH --repo PATH --json`

- [ ] **Step 1: Add failing partial and frozen banner tests**

Obtain `classify_response` with `getattr(adapter_module, "classify_response", None)` and assert it is callable before invoking it, so the missing behavior produces a clean RED assertion.

```python
def test_response_banner_marks_only_named_files_stale(self) -> None:
    source = self.repo / "src/widget.py"
    source.parent.mkdir()
    source.write_text("def widget():\n    return 1\n", encoding="utf-8")
    response = """⚠️ Some files referenced below were edited since the last index sync —
their codegraph entries may be stale:
  - src/widget.py (edited 800ms ago, pending sync)
For accurate content of those specific files, Read them directly.
"""
    result = classify_response(self.repo, response, checked_at="2026-08-18T00:00:00Z")
    self.assertEqual(result["classification"], "PARTIAL_STALE")
    self.assertEqual(result["stale_points"][0]["path"], "src/widget.py")
    self.assertEqual(result["stale_points"][0]["fallback"], "READ_SOURCE")
    self.assertEqual(result["stale_points"][0]["observed_sha256"], file_sha256(source))

def test_disabled_banner_freezes_the_whole_index(self) -> None:
    result = classify_response(
        self.repo,
        "⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n",
        checked_at="2026-08-18T00:00:00Z",
    )
    self.assertEqual(result["classification"], "INDEX_STALE")
    self.assertEqual(result["stale_points"][0]["reason"], "AUTO_SYNC_DISABLED")
```

Add rejection cases for `../outside.py`, absolute paths, a symlink resolving outside the repository, and a missing listed path mapping to `INSPECT_GIT_DIFF` with `observed_sha256: null`.

- [ ] **Step 2: Add failing runtime confinement and JSON-output tests**

Create a response file below `.polaris/tasks/TASK-0001/runtime/code-intelligence/`, call the script through `subprocess.run`, and assert envelope status `PASS` plus classification `PARTIAL_STALE`. Pass an input outside that runtime directory and assert exit code `2` with an input error.

- [ ] **Step 3: Run Task 3 tests and verify RED**

```bash
python -m unittest tests.test_codegraph -v
```

Expected: missing classifier/runtime failures.

- [ ] **Step 4: Implement exact banner parsing and freshness merge**

Match only the official leading sentences and list rows shaped as `- PATH (edited ..., pending sync)`. Resolve each candidate through `resolve_repo_reference`; existing paths must be regular files, while missing safe paths become deletion fallbacks. Do not treat arbitrary warning text as a valid banner.

Use this merge precedence:

```python
FRESHNESS_ORDER = {
    "CURRENT_AT_CHECK": 0,
    "PARTIAL_STALE": 1,
    "NOT_VERIFIED": 2,
    "INDEX_STALE": 3,
    "UNAVAILABLE": 4,
}
```

The more conservative status wins; combine unique basis values and stale points without changing their original order. Classification `NONE` is neutral: it preserves the status baseline and adds `RESPONSE_BANNER` only when the baseline already came from a successful status check. It must not upgrade a `NOT_VERIFIED` baseline. A malformed recognized banner returns classification `NOT_VERIFIED` and therefore downgrades the merged result.

Implement the runtime script as a thin `argparse` dispatcher over adapter functions. Before `classify-response`, resolve the task with `task_dir()`, require the input to be a regular file inside `code_intelligence_runtime_dir()`, and read UTF-8 text. Use `run_main()` for stable exit codes and JSON envelopes.

- [ ] **Step 5: Run focused tests and verify GREEN**

```bash
python -m unittest tests.test_codegraph -v
```

Expected: banner parsing, path security, merge precedence, and runtime CLI tests PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add scripts/internal/codegraph_adapter.py scripts/code_intelligence_runtime.py tests/test_codegraph.py
git commit -m "feat: classify stale CodeGraph responses"
```

---

### Task 4: Introduce writable v2 records and read-only v1 history

**Files:**
- Create: `schemas/code-intelligence-record-v1.schema.json`
- Modify: `schemas/code-intelligence-record.schema.json`
- Modify: `templates/task-sources/code-intelligence-record.json`
- Regenerate: `templates/task/code-intelligence/r001/planning.json`
- Modify: `scripts/internal/code_intelligence_protocol.py:293-446`
- Modify: `scripts/record_code_intelligence.py`
- Modify: `tests/test_codegraph.py`
- Modify: `tests/test_core.py:1568-1663,3320-3505`

**Interfaces:**
- Produces: `validate_legacy_record_value(repo: Path, task_id: str, value: dict[str, Any], root: Path | None = None) -> dict[str, Any]`.
- `validate_record_value(...)` accepts v1 for historical reads and v2 for current reads.
- `record(...)` writes only `record_version == 2`.
- v2 replaces `refresh` with `sync`, `freshness`, and `source_fallbacks`.

- [ ] **Step 1: Add failing legacy-read and legacy-write-block tests**

Import `internal.code_intelligence_protocol` as a module, obtain `validate_legacy_record_value` with `getattr(module, "validate_legacy_record_value", None)`, and first assert it is callable; this produces an assertion failure rather than an import error. The same test then loads the current v1 template through that callable. Add a second test that expects `record()` to reject the v1 value with `InputFailure("new Code Intelligence records must use record_version 2")`. The first RED run must fail because the legacy validator and frozen v1 Schema do not exist; do not create either production asset before observing that failure.

- [ ] **Step 2: Add failing v2 consistency tests**

Build v2 values from the template and test these exact rules:

```python
def test_partial_stale_record_requires_matching_source_fallback(self) -> None:
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
```

Also assert:

- `CURRENT_AT_CHECK` rejects stale points.
- `PARTIAL_STALE` rejects index points.
- `INDEX_STALE` requires an index point and a `SEARCH_SOURCE` fallback.
- `UNAVAILABLE` uses basis `NONE` and has no attempted query/sync.
- `READ_SOURCE` requires a current SHA.
- `INSPECT_GIT_DIFF` requires target base/head/diff hash and a null SHA.
- `SEARCH_SOURCE` requires a non-empty purpose.
- `sync.status == SUCCESS` requires a response hash and `SYNC_ACKNOWLEDGED` basis.
- Provider descriptor version is `2` and available operations are a subset of `explore`, `status`, `sync`.

- [ ] **Step 3: Run v2 tests and verify RED**

```bash
python -m unittest tests.test_codegraph -v
```

Expected: Schema and validator failures because the writable record is still v1.

- [ ] **Step 4: Implement the v2 Schema, template, and validator dispatch**

Make the writable template start with:

```json
{
    "record_version": 2,
    "provider": null,
    "status": "UNAVAILABLE",
    "queries": [],
    "sync": null,
    "freshness": {
        "status": "UNAVAILABLE",
        "checked_at": "1970-01-01T00:00:00Z",
        "basis": ["NONE"],
        "stale_points": []
    },
    "source_fallbacks": []
}
```

Retain the existing task/revision/target fields. Limit query operation to `explore`. Define `sync` statuses `SUCCESS`, `FAILED`, `SKIPPED`, `UNAVAILABLE`. Define the exact freshness, stale-point, and source-fallback enums from the Spec.

First add `schemas/code-intelligence-record-v1.schema.json` with the pre-change writable Schema content, then replace the writable Schema with v2. Split common task/target validation from version-specific validation. `record_reference()` chooses v1 or v2 by `record_version`; `record()` rejects v1 before selecting a destination. Legacy validation checks Schema, task/revision, subject commit/diff, canonical record name, response hashes, and confined symbol paths, but does not compare old capability sets to descriptor v2 or claim freshness.

- [ ] **Step 5: Regenerate and validate the task template tree**

```bash
python scripts/materialize_task_layout.py
python -m unittest tests.test_core.PolarisCoreTests.test_task_layout_is_single_source_and_templates_mirror_it -v
```

Expected: materializer exits 0 and template projection test PASS.

- [ ] **Step 6: Run record and artifact-reference regressions**

```bash
python -m unittest tests.test_codegraph tests.test_core.PolarisCoreTests.test_code_intelligence_record_is_compact_safe_and_immutable tests.test_core.PolarisCoreTests.test_implementation_and_final_documentation_subjects_are_bound tests.test_core.PolarisCoreTests.test_full_r1_flow_closes_only_after_review_and_validation -v
```

Expected: PASS after updating current-record fixtures to v2 while leaving explicit legacy fixtures at v1.

- [ ] **Step 7: Commit Task 4**

```bash
git add schemas/code-intelligence-record.schema.json schemas/code-intelligence-record-v1.schema.json templates/task-sources/code-intelligence-record.json templates/task/code-intelligence/r001/planning.json scripts/internal/code_intelligence_protocol.py scripts/record_code_intelligence.py tests/test_codegraph.py tests/test_core.py
git commit -m "feat: record CodeGraph freshness and fallbacks"
```

---

### Task 5: Update stage Skills and every Agent instruction surface

**Files:**
- Modify: `skills/code-intelligence/SKILL.md`
- Modify: `skills/architecture-planning/SKILL.md`
- Modify: `skills/implementation/SKILL.md`
- Modify: `skills/adversarial-review/SKILL.md`
- Modify: `skills/documentation-sync/SKILL.md`
- Modify: `templates/AGENTS.md`
- Modify: `tests/test_codegraph.py`
- Modify: `tests/test_core.py:680-760`

**Interfaces:**
- Consumes: `code_intelligence_runtime.py` actions and v2 record format.
- Produces: identical conditional usage semantics in Codex-rendered Skills, Claude Code-rendered Skills, Implementer/Reviewer instructions, and vendored `AGENTS.md`.

- [ ] **Step 1: Add failing instruction-contract tests**

Read each source Skill and render it through every host adapter. Assert the resulting text contains all of these exact semantic anchors:

```python
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
```

Assert Validation still says not to invoke Code Intelligence. Construct forbidden legacy tokens in the test with string concatenation, for example `"refresh" + "_files"`, so the retired names do not remain literally in the repository. Assert no rendered Skill contains either retired refresh token or any retired narrow operation token. Assert `templates/AGENTS.md` says to stop CodeGraph calls for the session when `.codegraph/` is absent and to preserve any installer-managed marker block.

- [ ] **Step 2: Run instruction tests and verify RED**

```bash
python -m unittest tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_share_codegraph_fallback_rules -v
```

Expected: FAIL because current Skills still describe the old multi-operation refresh model.

- [ ] **Step 3: Rewrite the internal Code Intelligence stage procedure**

Make `skills/code-intelligence/SKILL.md` direct the caller to:

1. Check project policy and `.codegraph/`.
2. Run internal `status` or `sync-if-needed` at the declared stage boundary.
3. Use only `codegraph_explore`, with `codegraph explore` as non-MCP fallback.
4. Save the raw response under task runtime and run `classify-response`.
5. Directly read every `PARTIAL_STALE` file and record its current SHA.
6. For `INDEX_STALE` or `NOT_VERIFIED`, use source search/Git fallback and stop repeated graph calls for that stage.
7. Never initialize, install, start, authenticate, or reconfigure CodeGraph.
8. Finalize a v2 record; never use it as a gate.

Update each stage Skill with its bounded query purpose. Implementation queries mid-stage only if a later declared step depends on new relationships. Documentation Sync runs `sync-if-needed` only for supported source changes. Reviewer queries independently. Validation remains graph-free.

- [ ] **Step 4: Update shared Agent rules without owning installer markers**

Append a normal Polaris-owned section to `templates/AGENTS.md`. Do not add CodeGraph's marker-fence syntax, because its installer owns that block. State the same marker, stale-file, frozen-index, and no-init rules. Keep generic Polaris repository rules unchanged.

- [ ] **Step 5: Run host rendering and vendoring tests**

```bash
python -m unittest tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_share_codegraph_fallback_rules tests.test_core.PolarisCoreTests.test_vendored_target_is_self_contained tests.test_core.PolarisCoreTests.test_host_adapters_render_from_one_host_neutral_skill_source -v
```

Expected: PASS for Codex and Claude Code outputs.

- [ ] **Step 6: Commit Task 5**

```bash
git add skills/code-intelligence/SKILL.md skills/architecture-planning/SKILL.md skills/implementation/SKILL.md skills/adversarial-review/SKILL.md skills/documentation-sync/SKILL.md templates/AGENTS.md tests/test_codegraph.py tests/test_core.py
git commit -m "feat: guide agents through stale CodeGraph data"
```

---

### Task 6: Retire v1 evidence during the 0.1.19 migration

**Files:**
- Modify: `VERSION`
- Modify: `pyproject.toml`
- Modify: `templates/project.json`
- Modify: `templates/task-sources/state.json`
- Regenerate: `templates/task/state.json`
- Modify: `workflow/migrations.json`
- Modify: `schemas/migration-record.schema.json`
- Modify: `scripts/internal/migration_protocol.py:16-364`
- Modify: `tests/test_core.py:1388-1505`
- Modify: `tests/test_codegraph.py`

**Interfaces:**
- Adds migration route `0.1.18-to-0.1.19`, workflow `0.1.2` to `0.1.2`.
- New migration records include `retired_code_intelligence_records` entries with `task_id`, canonical task-relative `path`, and SHA-256.
- Existing migration records without that optional field remain valid.

- [ ] **Step 1: Add a failing migration-retirement test**

In an initialized fixture, write a valid v1 record to `code-intelligence/r001/planning.json`, set project/task/event versions to `0.1.18`, vendor the new protocol, migrate, and assert:

```python
self.assertEqual(result["from"], "0.1.18")
self.assertEqual(result["to"], "0.1.19")
self.assertEqual(
    read_json(self.repo / ".polaris/project.json")["workflow_version"],
    "0.1.2",
)
migration = read_json(
    self.repo / ".polaris/migrations/MIG-0.1.18-to-0.1.19.json"
)
self.assertEqual(
    migration["retired_code_intelligence_records"],
    [{
        "task_id": "TASK-0001",
        "path": "code-intelligence/r001/planning.json",
        "sha256": file_sha256(legacy_path),
    }],
)
self.assertEqual(read_json(legacy_path)["record_version"], 1)
```

Also assert a newly generated v2 record can coexist at the next canonical stage path and that the v1 bytes do not change during migration.

- [ ] **Step 2: Run migration tests and verify RED**

```bash
python -m unittest tests.test_codegraph.CodeGraphTests.test_migration_retires_v1_records_without_rewriting_them tests.test_core.PolarisCoreTests.test_explicit_migration_appends_task_event_and_records_completion -v
```

Expected: FAIL because version `0.1.19`, route, and retirement inventory do not exist.

- [ ] **Step 3: Implement the adjacent migration and retirement inventory**

Advance only the Polaris version fields to `0.1.19`; keep every workflow field at `0.1.2`. Add the adjacent migration JSON step using existing `replace_version` and `append_version_event` strategies.

Add optional Schema property:

```json
"retired_code_intelligence_records": {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["task_id", "path", "sha256"],
        "additionalProperties": false
    }
}
```

In `_new_record()`, scan only canonical task Code Intelligence record paths, validate each v1 record through the legacy path, and append sorted inventory entries. Reject symlinks and noncanonical paths. Do not edit record files or artifact references. Existing older migration records without the optional field continue to validate.

- [ ] **Step 4: Regenerate templates and run migration recovery regressions**

```bash
python scripts/materialize_task_layout.py
python -m unittest tests.test_core.PolarisCoreTests.test_explicit_migration_appends_task_event_and_records_completion tests.test_core.PolarisCoreTests.test_migration_resumes_after_event_append_without_duplication tests.test_core.PolarisCoreTests.test_migration_reclaims_only_its_own_dead_process_lock tests.test_codegraph.CodeGraphTests.test_migration_retires_v1_records_without_rewriting_them -v
```

Expected: all PASS; workflow version assertions remain `0.1.2`.

- [ ] **Step 5: Run package and template version consistency checks**

```bash
python -m unittest tests.test_core.PolarisCoreTests.test_cli_packaging_declares_no_runtime_dependencies tests.test_core.PolarisCoreTests.test_project_version_mismatch_is_rejected tests.test_core.PolarisCoreTests.test_task_layout_is_single_source_and_templates_mirror_it -v
```

Expected: PASS with protocol `0.1.19` and workflow `0.1.2`.

- [ ] **Step 6: Commit Task 6**

```bash
git add VERSION pyproject.toml templates/project.json templates/task-sources/state.json templates/task/state.json workflow/migrations.json schemas/migration-record.schema.json scripts/internal/migration_protocol.py tests/test_core.py tests/test_codegraph.py
git commit -m "feat: migrate CodeGraph evidence to protocol 0.1.19"
```

---

### Task 7: Update product authority and user documentation

**Files:**
- Modify: `plan.md:489-517,650-677`
- Modify: `README.md:1-125,180-245`
- Modify: `docs/USAGE.md:1-45,180-220,600-635`
- Modify: `tests/test_codegraph.py`

**Interfaces:**
- Documents the only supported Provider, initialization ownership, freshness states, sync boundary, and fallback behavior.
- Removes old multi-operation and per-file/workspace refresh claims.

- [ ] **Step 1: Add a failing repository-content contract test**

Add a test that scans managed implementation, tests, Skills, templates, README, usage docs, and `plan.md`. Exclude `.git/`, `docs/superpowers/specs/`, `docs/superpowers/plans/`, and the frozen v1 JSON Schema. Build every forbidden legacy token through concatenated fragments so the test itself does not preserve a literal retired name. Assert those tokens are absent and the official repository URL appears in the descriptor, README, usage guide, and `plan.md`.

- [ ] **Step 2: Run the content test and verify RED**

```bash
python -m unittest tests.test_codegraph.CodeGraphTests.test_managed_surfaces_only_name_the_official_codegraph -v
```

Expected: FAIL on current README, usage guide, plan, tests, and old protocol wording.

- [ ] **Step 3: Rewrite the Code Intelligence authority section in `plan.md`**

Replace narrow logical tool and two-refresh-operation statements with:

- only `colbymchenry/codegraph` is formal in v0.1;
- `.codegraph/` is user-created;
- watcher and connect reconciliation are primary;
- one-shot sync is allowed at bounded points;
- freshness states and stale-point source fallbacks are persisted;
- Validation remains graph-free and Provider failures remain non-blocking.

Update the implementation checklist item without claiming daemon ownership or commit-exact freshness.

- [ ] **Step 4: Update README and the usage guide**

Set current version to `0.1.19`. Document the external setup sequence as user-run commands:

```text
codegraph install
codegraph init
polaris code-intelligence add codegraph --repo .
```

Clearly say Polaris only performs `status`, `explore`, and bounded `sync`; it never runs the first two setup commands. Add examples for `PARTIAL_STALE`, `INDEX_STALE`, and direct source fallback. Add the `0.1.19` migration note and state workflow remains `0.1.2`.

- [ ] **Step 5: Run documentation/content checks**

```bash
python -m unittest tests.test_codegraph.CodeGraphTests.test_managed_surfaces_only_name_the_official_codegraph -v
git diff --check
```

Expected: PASS and no whitespace errors.

- [ ] **Step 6: Commit Task 7**

```bash
git add plan.md README.md docs/USAGE.md tests/test_codegraph.py
git commit -m "docs: document live CodeGraph freshness"
```

---

### Task 8: Add the optional real-CLI smoke test and verify the whole repository

**Files:**
- Modify: `tests/test_codegraph.py`

**Interfaces:**
- Optional integration test consumes an already installed `codegraph` executable and creates an index only inside a disposable temporary repository.
- The normal suite has no CodeGraph dependency and reports `SKIP` when the executable is absent.

- [ ] **Step 1: Add the guarded real-CLI smoke test**

```python
import shutil

@unittest.skipUnless(shutil.which("codegraph"), "codegraph CLI is not installed")
def test_real_codegraph_status_shape_when_cli_is_available(self) -> None:
    source = self.repo / "sample.py"
    source.write_text("def sample():\n    return 1\n", encoding="utf-8")
    subprocess.run(
        ["codegraph", "init", str(self.repo)],
        cwd=self.repo,
        check=True,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=120,
    )
    descriptor = load_providers(ROOT)["codegraph"]
    result = inspect_status(self.repo, descriptor, timeout_seconds=30)
    self.assertEqual(result["status"], "CURRENT_AT_CHECK")
```

The test may initialize only `self.repo`, which is a validated `TemporaryDirectory`; it must never run against the workspace.

- [ ] **Step 2: Run the focused suite**

```bash
python -m unittest tests.test_codegraph -v
```

Expected: all deterministic tests PASS; real smoke PASS when CodeGraph is installed or explicitly reports `SKIP` otherwise.

- [ ] **Step 3: Rebuild generated assets and run the full suite**

```bash
python scripts/materialize_task_layout.py
python tests/run_tests.py
```

Expected: every Polaris scenario PASS; only the optional real CodeGraph test may be `SKIP`.

- [ ] **Step 4: Verify removal, versions, and clean generated state**

```bash
rg -n "codegraph_(get_ai_context|get_dependency_graph|get_call_graph|analyze_impact|pr_context|index_files|reindex_workspace)|refresh_files|refresh_workspace" providers scripts schemas skills templates tests README.md docs/USAGE.md plan.md --glob '!code-intelligence-record-v1.schema.json'
git diff --check
git status --short
```

Expected: `rg` exits 1 with no matches; `git diff --check` is silent; `git status --short` lists only intentional Task 8/test or regenerated changes before commit.

- [ ] **Step 5: Commit Task 8**

```bash
git add tests/test_codegraph.py templates/task
git commit -m "test: verify CodeGraph integration end to end"
```

- [ ] **Step 6: Capture final verification evidence**

Run again after the commit:

```bash
python tests/run_tests.py
git status --short
```

Expected: full suite PASS with the optional documented `SKIP`, and working tree clean.
