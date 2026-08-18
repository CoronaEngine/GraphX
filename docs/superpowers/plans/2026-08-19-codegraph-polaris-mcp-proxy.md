# CodeGraph Polaris MCP Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a project-scoped Polaris MCP proxy that performs one bounded CodeGraph freshness window, delivers an adjacent freshness envelope, and records auditable v3 evidence without making CodeGraph a workflow gate.

**Architecture:** Extend the existing CodeGraph CLI adapter with reusable status/sync/explore primitives, then place a host-neutral proxy orchestration module above it. A thin standard-library stdio MCP entry point exposes only `polaris_codegraph_explore`; host adapter v3 renders project-local registrations for Codex and Claude Code. New v3 records copy and validate the proxy bundle while frozen v1/v2 schemas remain readable historical formats.

**Tech Stack:** Python 3.10+ standard library (`argparse`, `hashlib`, `json`, `subprocess`, `unittest`; `tomllib` when available), JSON Schema through Polaris's existing validator, JSON-RPC 2.0/MCP stdio protocol revision `2025-11-25`, Git, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-18-codegraph-polaris-mcp-proxy-design.md`

## Global Constraints

- Polaris protocol and package version becomes exactly `0.1.21`.
- Workflow graph version remains exactly `0.1.3`; do not change states or transitions.
- Host adapter manifest version becomes exactly v3.
- New Code Intelligence writes use record v3; v1 and v2 remain immutable historical read formats.
- `colbymchenry/codegraph` remains the only official CodeGraph Provider.
- Runtime code remains Python-standard-library-only; add no package dependency.
- The proxy performs no sleep, polling, retry, CodeGraph installation, initialization, configuration, daemon management, or watcher management.
- One invocation performs at most one pre-status, one sync, one post-sync status, one explore, and one post-query status.
- Raw `codegraph_explore` MCP and unrestricted shell access remain available but cannot back `CURRENT` Polaris evidence.
- Validation remains graph-free and CI must pass without CodeGraph installed.
- `CURRENT` is non-authoritative context; `STALE` and `UNKNOWN` are navigation-only and require exact source/Git fallback evidence.
- Project mismatch, unsafe paths, malformed warnings, missing proof, and unavailable capabilities fail closed.

---

## File Structure

- `scripts/internal/codegraph_adapter.py`: low-level bounded CodeGraph CLI calls and fail-safe response classification.
- `scripts/internal/code_intelligence_proxy.py`: stage resolution, query-window orchestration, delivery-state merge, runtime bundle persistence, and envelope rendering.
- `scripts/code_intelligence_mcp.py`: newline-delimited JSON-RPC/MCP stdio dispatcher only.
- `scripts/internal/code_intelligence_protocol.py`: v1/v2/v3 record selection and semantic validation.
- `schemas/code-intelligence-record-v2.schema.json`: frozen copy of the current v2 schema.
- `schemas/code-intelligence-record.schema.json`: current v3 schema.
- `schemas/code-intelligence-record-annotations.schema.json`: Agent-supplied summaries, symbols, and completed fallback evidence used when projecting a bundle.
- `scripts/internal/project_mcp_registration.py`: non-destructive Codex TOML and Claude JSON registration rendering/validation.
- `scripts/internal/host_adapters.py`: adapter v3 manifest validation and safe project MCP target resolution.
- `scripts/vendor_project.py`, `scripts/init_project.py`, `scripts/validate_project.py`: transactionally install and validate the project-local registration.
- `hosts/codex/adapter.json`, `hosts/claude-code/adapter.json`: declarative host registration metadata.
- `skills/*`, `templates/AGENTS.md`, `README*.md`, `docs/USAGE.md`, `plan.md`: one shared human/Agent behavior contract.
- `workflow/migrations.json`, `scripts/internal/migration_protocol.py`, version/template files: adjacent `0.1.20` to `0.1.21` migration and frozen v2 inventory.
- `tests/test_codegraph.py`: adapter, proxy, MCP, record, migration, Skill, and optional real-CLI coverage.
- `tests/test_core.py`: host registration, vendoring, version, validation, and rollback coverage.

---

### Task 1: Bounded CodeGraph CLI primitives and fail-safe response classification

**Files:**
- Modify: `scripts/internal/codegraph_adapter.py`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: existing `inspect_status(repo, descriptor, runner, timeout_seconds) -> dict` and CodeGraph descriptor `cli.*_args`.
- Produces: `run_explore(repo, descriptor, query, *, runner, timeout_seconds) -> dict`, `synchronize_observed_status(repo, descriptor, initial, *, runner, status_timeout_seconds, sync_timeout_seconds) -> dict`, and stricter `classify_response(repo, response, checked_at=None) -> dict`.

- [ ] **Step 1: Write failing tests for one-shot explore and observed-status sync**

Add tests that assert the exact call sequence and shared repository cwd:

```python
def test_explore_and_observed_sync_are_bounded_to_one_repo(self) -> None:
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs["cwd"]))
        if command[1:3] == ["status", "--json"]:
            return completed(healthy_status(self.repo))
        if command[1:] == ["sync", "--quiet"]:
            return completed("synced\n")
        return completed("graph response\n")

    pending = json.loads(healthy_status(self.repo))
    pending["pendingChanges"]["modified"] = 1
    initial = codegraph_adapter._status_result(
        self.repo, pending, "2026-08-19T00:00:00Z", "a" * 64
    )
    synchronized = codegraph_adapter.synchronize_observed_status(
        self.repo, load_providers(ROOT)["codegraph"], initial, runner=runner
    )
    explored = codegraph_adapter.run_explore(
        self.repo, load_providers(ROOT)["codegraph"], "find symbol A", runner=runner
    )
    self.assertEqual(synchronized["sync"]["status"], "SUCCESS")
    self.assertEqual(explored["status"], "SUCCESS")
    self.assertEqual(explored["response_sha256"], hashlib.sha256(b"graph response\n").hexdigest())
    self.assertTrue(all(cwd == self.repo for _command, cwd in calls))
    self.assertEqual(sum(command[1] == "sync" for command, _cwd in calls), 1)
    self.assertEqual(sum(command[1] == "explore" for command, _cwd in calls), 1)
```

- [ ] **Step 2: Run the new focused test and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_explore_and_observed_sync_are_bounded_to_one_repo -v`

Expected: `AttributeError` for `synchronize_observed_status` or `run_explore`.

- [ ] **Step 3: Implement the reusable primitives and refactor the legacy wrapper**

Use these exact public shapes:

```python
def run_explore(repo, descriptor, query, *, runner=subprocess.run, timeout_seconds=60):
    checked_at = _checked_at()
    if not isinstance(query, str) or not query.strip():
        return {"status": "FAILED", "checked_at": checked_at, "response": None,
                "response_sha256": None, "error": "CodeGraph query must not be blank"}
    try:
        completed = _run_cli(
            repo, descriptor, "explore_args", timeout_seconds, runner,
            extra_args=[query],
        )
        raw, digest = _stdout_and_hash(completed)
    except (KeyError, OSError, TypeError, UnicodeError, ValueError,
            subprocess.TimeoutExpired) as error:
        return {"status": "FAILED", "checked_at": checked_at, "response": None,
                "response_sha256": None, "error": _error_summary(error)}
    if completed.returncode != 0:
        return {"status": "FAILED", "checked_at": checked_at, "response": None,
                "response_sha256": digest,
                "error": f"CodeGraph explore exited with {completed.returncode}"}
    return {"status": "SUCCESS", "checked_at": checked_at, "response": raw,
            "response_sha256": digest, "error": None}
```

Change `_run_cli(..., extra_args: list[str] | None = None)` to append only the supplied list. Move the current sync body into `synchronize_observed_status(...)`; keep `sync_if_needed(...)` as `inspect_status(...)` followed by that function so the existing CLI remains compatible.

- [ ] **Step 4: Write failing tests for suspicious warning forms**

Replace the old permissive expectations with:

```python
def test_suspicious_or_wrapped_freshness_warnings_are_not_verified(self) -> None:
    samples = (
        "warning: graph may be stale\n",
        "quoted: ⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n",
        "\ufeff⚠️ CodeGraph auto-sync is DISABLED — the index is frozen.\n",
        " pending-sync required\n",
    )
    for response in samples:
        with self.subTest(response=response):
            result = codegraph_adapter.classify_response(self.repo, response)
            self.assertEqual(result["classification"], "NOT_VERIFIED")
            self.assertEqual(result["stale_points"][0]["reason"], "STATUS_UNREADABLE")
            self.assertEqual(
                result["response_sha256"],
                hashlib.sha256(response.encode("utf-8")).hexdigest(),
            )
```

- [ ] **Step 5: Run the warning test and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_suspicious_or_wrapped_freshness_warnings_are_not_verified -v`

Expected: at least one sample classifies as `NONE`.

- [ ] **Step 6: Implement conservative suspicious-signal classification**

After exact supported-banner parsing and before returning `NONE`, reject case-insensitive `warning`, `stale`, `pending-sync`, `pending sync`, `out-of-date`, or any `⚠` marker as `NOT_VERIFIED`. Preserve the exact response digest in every branch.

- [ ] **Step 7: Run adapter tests**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_explore_and_observed_sync_are_bounded_to_one_repo tests.test_codegraph.CodeGraphTests.test_suspicious_or_wrapped_freshness_warnings_are_not_verified tests.test_codegraph.CodeGraphTests.test_pending_changes_sync_once_and_recheck_once tests.test_codegraph.CodeGraphTests.test_response_banner_marks_only_named_files_stale -v`

Expected: all PASS; no test observes more than one sync or explore.

- [ ] **Step 8: Commit Task 1**

```bash
git add scripts/internal/codegraph_adapter.py tests/test_codegraph.py
git commit -m "feat: add bounded CodeGraph query primitives"
```

---

### Task 2: Proxy query-window engine and immutable runtime bundles

**Files:**
- Create: `scripts/internal/code_intelligence_proxy.py`
- Modify: `scripts/internal/task_layout.py`
- Modify: `scripts/internal/code_intelligence_protocol.py`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: Task 1's `inspect_status`, `synchronize_observed_status`, `run_explore`, and `classify_response`.
- Produces: `resolve_stage_context(repo, task_id, stage) -> dict`, `execute_proxy_query(repo, task_id, stage, query_id, purpose, query, sync_if_needed, *, runner=subprocess.run) -> dict`, and `render_freshness_envelope(bundle) -> str`.

- [ ] **Step 1: Write failing stage-context and path-confinement tests**

Assert these canonical runtime locations:

```python
def test_proxy_stage_context_uses_record_name_and_sequential_query_ids(self) -> None:
    context = code_intelligence_proxy.resolve_stage_context(
        self.repo, "TASK-0001", "PLANNING"
    )
    self.assertEqual(context["work_item_revision"], 1)
    self.assertEqual(context["artifact_attempt"], None)
    self.assertEqual(context["reviewer_slot"], None)
    self.assertEqual(context["record_name"], "planning")
    expected = (
        self.repo
        / ".polaris/tasks/TASK-0001/runtime/code-intelligence/planning/CIQ-001.json"
    )
    self.assertEqual(
        code_intelligence_proxy.proxy_bundle_path(
            self.repo, "TASK-0001", context, "CIQ-001"
        ),
        expected,
    )
```

Add table cases for Implementation/Documentation Sync using the current implementation handoff attempt, and Review using the current review handoff plus the next reviewer slot. Reject a stage inconsistent with task state, `CIQ-000`, a skipped ID, an existing bundle, a symlinked runtime component, and more than `CIQ-999`.

- [ ] **Step 2: Run stage-context tests and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_proxy_stage_context_uses_record_name_and_sequential_query_ids -v`

Expected: import failure for `internal.code_intelligence_proxy`.

- [ ] **Step 3: Implement stage resolution and bundle layout**

Add `code_intelligence_proxy_bundle` to `TASK_PATH_PATTERNS`:

```python
"code_intelligence_proxy_bundle": (
    "runtime/code-intelligence/{record_name}/{query_id}.json"
),
"code_intelligence_proxy_response": (
    "runtime/code-intelligence/{record_name}/{query_id}.response.txt"
),
```

Extend `task_relative_path(..., query_id: str = "CIQ-001")` and pass
`query_id=query_id` into its single `pattern.format(...)` call so both helpers
remain governed by the task-layout registry.

`resolve_stage_context` must validate the task, current revision, and stage-specific artifact, then return exactly:

```python
{
    "task_id": task_id,
    "work_item_revision": revision,
    "stage": stage,
    "artifact_attempt": attempt_or_none,
    "reviewer_slot": slot_or_none,
    "record_name": _record_name(record_identity),
    "target": {"base_commit": base, "head_commit": head, "diff_hash": diff_hash},
}
```

Planning derives `base_commit` from the frozen work item and uses null head/diff. Implementation and Documentation Sync use the current implementation handoff/subject. Review uses the current review handoff subject and chooses slot 1 before slot 2. Reuse existing artifact validators rather than trusting raw JSON fields.

- [ ] **Step 4: Write failing query-window classification tests**

Use a scripted runner and assert all four outcomes:

```python
class ScriptedCodeGraphRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if not self.responses:
            raise AssertionError(f"unexpected extra CodeGraph call: {command}")
        return self.responses.pop(0)

def test_proxy_window_requires_clean_pre_and_post_status_for_current(self) -> None:
    runner = ScriptedCodeGraphRunner([
        completed(healthy_status(self.repo)),
        completed("graph bytes\n"),
        completed(healthy_status(self.repo)),
    ])
    result = code_intelligence_proxy.execute_proxy_query(
        self.repo, "TASK-0001", "PLANNING", "CIQ-001",
        "locate affected symbols", "symbol A", False, runner=runner,
    )
    bundle = result["bundle"]
    self.assertEqual(bundle["delivery"]["state"], "CURRENT")
    self.assertEqual(bundle["delivery"]["usage"], "NON_AUTHORITATIVE_CONTEXT")
    self.assertEqual(bundle["delivery"]["record_status"], "CURRENT_AT_CHECK")
    self.assertEqual([call[0][1] for call in runner.calls], ["status", "explore", "status"])
```

Add cases for pending pre-status without sync (`STALE/INDEX_STALE` but explore once), pending pre-status with a successful single sync, pending post-status downgrade, malformed pre-status (`UNKNOWN` and no explore), explore failure (`UNKNOWN` without graph), stale banner, suspicious banner, project mismatch, disabled policy/no marker/missing executable (`UNAVAILABLE` and no Provider call), and unsafe response path (discard graph).

- [ ] **Step 5: Run query-window tests and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_proxy_window_requires_clean_pre_and_post_status_for_current -v`

Expected: missing `execute_proxy_query`.

- [ ] **Step 6: Implement the exact bundle and conservative merge**

Persist this versioned shape with `write_json_atomic` and reject overwrite:

```python
{
    "bundle_version": 1,
    "proxy": {"server_id": "polaris-codegraph", "tool": "polaris_codegraph_explore"},
    "provider": {"id": "codegraph", "descriptor_version": 2},
    "repository": {"project_id": project_id, "root_sha256": sha256(str(repo.resolve()))},
    "task_context": stage_context,
    "query": {
        "id": query_id, "purpose": purpose, "text": query,
        "status": "SUCCESS|FAILED|UNAVAILABLE", "response_sha256": digest_or_none,
        "error": error_or_none,
    },
    "pre_status": status_observation,
    "sync": sync_observation_or_none,
    "post_sync_status": status_observation_or_none,
    "response_classification": classification_or_none,
    "post_query_status": status_observation_or_none,
    "delivery": {
        "state": "CURRENT|STALE|UNKNOWN|UNAVAILABLE",
        "record_status": "CURRENT_AT_CHECK|PARTIAL_STALE|INDEX_STALE|NOT_VERIFIED|UNAVAILABLE",
        "reason": finite_reason,
        "checked_at": timestamp,
        "usage": "NON_AUTHORITATIVE_CONTEXT|NAVIGATION_ONLY|NO_GRAPH",
        "required_fallback": "NONE|READ_SOURCE|INSPECT_GIT_DIFF|SEARCH_SOURCE",
        "stale_points": stale_points,
        "error": finite_error_or_none,
    },
    "response_path": task_relative_response_path_or_none,
}
```

Only `CURRENT` may use `NON_AUTHORITATIVE_CONTEXT`; only `UNAVAILABLE` may use `NO_GRAPH`. Any known stale signal wins over clean observations. Any missing/unreadable proof becomes `UNKNOWN`. Save the exact UTF-8 graph response before the bundle and verify its digest. If project identity or response integrity is unsafe, remove `response_path` and do not return graph text.

- [ ] **Step 7: Implement and test the bounded envelope**

`render_freshness_envelope` must emit only finite scalar fields between exact start/end markers, with pending counts from the most conservative successful status and a task-relative bundle path. Add an assertion that the first returned character sequence is `[POLARIS_CODEGRAPH_FRESHNESS]` and that diagnostics are truncated to 240 characters.

- [ ] **Step 8: Run proxy tests**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests -k proxy -v`

Expected: all proxy tests PASS and all fake runner call counts match their exact maxima.

- [ ] **Step 9: Commit Task 2**

```bash
git add scripts/internal/code_intelligence_proxy.py scripts/internal/task_layout.py scripts/internal/code_intelligence_protocol.py tests/test_codegraph.py
git commit -m "feat: bind CodeGraph queries to freshness windows"
```

---

### Task 3: Standard-library stdio MCP server

**Files:**
- Create: `scripts/code_intelligence_mcp.py`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: Task 2's `execute_proxy_query` and `render_freshness_envelope`.
- Produces: executable MCP server supporting `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call` for exactly one tool.

- [ ] **Step 1: Write a subprocess MCP transcript test**

Send one compact JSON object per input line:

```python
messages = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    }},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
]
completed = subprocess.run(
    [sys.executable, SCRIPTS / "code_intelligence_mcp.py", "--repo", self.repo],
    input="".join(json.dumps(item) + "\n" for item in messages),
    text=True, capture_output=True, check=False,
)
responses = [json.loads(line) for line in completed.stdout.splitlines()]
self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
self.assertEqual(responses[0]["result"]["capabilities"], {"tools": {"listChanged": False}})
self.assertEqual([item["name"] for item in responses[1]["result"]["tools"]],
                 ["polaris_codegraph_explore"])
self.assertNotIn("codegraph_explore", {item["name"] for item in responses[1]["result"]["tools"]})
```

Also assert the initialized notification produces no response and stdout contains no non-JSON lines.

- [ ] **Step 2: Run the transcript test and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_mcp_server_initializes_and_lists_one_proxy_tool -v`

Expected: script missing.

- [ ] **Step 3: Implement the MCP lifecycle and one tool schema**

Use newline-delimited UTF-8 JSON-RPC per the MCP `2025-11-25` stdio transport. The tool schema must set `additionalProperties: false`, require all six approved arguments, constrain task/stage/query IDs, and never expose a repository argument:

```python
TOOL = {
    "name": "polaris_codegraph_explore",
    "description": "Run one bounded Polaris CodeGraph freshness window.",
    "inputSchema": {
        "type": "object",
        "required": ["task_id", "stage", "query_id", "purpose", "query", "sync_if_needed"],
        "additionalProperties": False,
        "properties": {
            "task_id": {"type": "string", "pattern": r"^TASK-[0-9]{4}$"},
            "stage": {"type": "string", "enum": ["PLANNING", "IMPLEMENTATION", "DOCUMENTATION_SYNC", "REVIEW"]},
            "query_id": {"type": "string", "pattern": r"^CIQ-[0-9]{3}$"},
            "purpose": {"type": "string", "minLength": 1, "maxLength": 240},
            "query": {"type": "string", "minLength": 1, "maxLength": 8000},
            "sync_if_needed": {"type": "boolean"},
        },
    },
}
```

Return parse/invalid-request/method errors as JSON-RPC `-32700`, `-32600`, `-32601`, and `-32602`. Return user-correctable tool execution/input failures as `tools/call` results with `isError: true`. Never write logs to stdout.

- [ ] **Step 4: Write failing envelope-order and error tests**

Mock `execute_proxy_query` in-process and assert a successful tool call returns two text blocks—the envelope first and raw graph second. A stale/unknown graph remains `isError: false`; Provider failure has only the envelope; invalid stage/query is `isError: true`; unknown tool name is `-32602`; requests before initialization are rejected.

- [ ] **Step 5: Implement tool-call result formatting**

Return:

```python
{
    "content": [
        {"type": "text", "text": render_freshness_envelope(bundle)},
        *([{"type": "text", "text": graph_text}] if graph_text is not None else []),
    ],
    "structuredContent": {"bundle": bundle},
    "isError": False,
}
```

The structured bundle must match the saved runtime bundle exactly. Ensure `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` produces one physical stdout line.

- [ ] **Step 6: Run MCP tests**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests -k mcp_server -v`

Expected: all PASS; no output before the envelope and no repository property in the tool schema.

- [ ] **Step 7: Commit Task 3**

```bash
git add scripts/code_intelligence_mcp.py tests/test_codegraph.py
git commit -m "feat: expose the Polaris CodeGraph MCP proxy"
```

---

### Task 4: Code Intelligence v3 record projection and validation

**Files:**
- Create: `schemas/code-intelligence-record-v2.schema.json`
- Create: `schemas/code-intelligence-record-annotations.schema.json`
- Modify: `schemas/code-intelligence-record.schema.json`
- Modify: `scripts/internal/code_intelligence_protocol.py`
- Modify: `scripts/record_code_intelligence.py`
- Modify: `templates/task-sources/code-intelligence-record.json`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: Task 2 bundle v1 and existing v1/v2 validators/fallback rules.
- Produces: `validate_historical_v2_record_value(...)`, `_validate_v3_record_value(...)`, and `record_proxy_bundle(repo, task_id, bundle_path, annotations, root=None) -> dict`.

- [ ] **Step 1: Freeze v2 and write failing v3 projection tests**

Copy the current schema byte-for-byte to `code-intelligence-record-v2.schema.json`, then add a test that records a Task 2 bundle through:

```python
result = record_proxy_bundle(
    self.repo,
    "TASK-0001",
    bundle_path,
    {
        "summary": "Located the affected symbol.",
        "symbols": [{"path": "src/a.py", "line": 1, "name": "A"}],
        "source_fallbacks": [],
    },
    ROOT,
)
recorded = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
self.assertEqual(recorded["record_version"], 3)
self.assertEqual(recorded["proxy"]["server_id"], "polaris-codegraph")
self.assertEqual(recorded["query_window"]["pre_status"]["pending_changes"],
                 {"added": 0, "modified": 0, "removed": 0})
self.assertEqual(recorded["delivery"]["state"], "CURRENT")
```

- [ ] **Step 2: Run the projection test and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_v3_record_projects_exact_proxy_bundle -v`

Expected: `record_proxy_bundle` missing.

- [ ] **Step 3: Define the v3 and annotations schemas**

The current schema must require these top-level fields and reject extras:

```json
[
  "record_version", "task_id", "work_item_revision", "stage",
  "artifact_attempt", "reviewer_slot", "provider", "repository", "target",
  "status", "proxy", "query", "query_window", "delivery",
  "source_fallbacks", "recorded_at"
]
```

Use `record_version: {"const": 3}`. `proxy` requires `server_id: "polaris-codegraph"`, `tool: "polaris_codegraph_explore"`, and a 64-hex `evidence_bundle_sha256`. `repository` requires nonblank `project_id` and 64-hex `root_sha256`. `query_window` requires `pre_status`, nullable `sync`, nullable `post_sync_status`, nullable `response_classification`, and nullable `post_query_status`. Every successful status observation requires `checked_at`, `response_sha256`, exact nonnegative `pending_changes`, `stale_reasons`, and null error; failed/unavailable observations prohibit pending counts and hashes. Reuse the current stale-point and source-fallback definitions without weakening them.

The annotations schema permits only `summary`, `symbols`, and `source_fallbacks`; the recorder derives identity, target, status, observations, hashes, and timestamps from the bundle/current task.

- [ ] **Step 4: Implement bundle projection and v3 semantic invariants**

`record_proxy_bundle` must confine the bundle below the current task's runtime directory, reject symlinks, validate bundle v1, hash its exact bytes, confirm its repository/task/stage context, and build the record. Map bundle delivery to record status exactly:

```python
RECORD_STATUS = {
    "CURRENT": "USED",
    "STALE": "USED",
    "UNKNOWN": "FAILED",
    "UNAVAILABLE": "UNAVAILABLE",
}
```

The v3 validator must reject: a non-proxy provider, project/root mismatch, target mismatch, non-sequential query ID for that stage record, response hash mismatch, `CURRENT` without two successful zero-pending effective pre/post observations, stale without an explicit reason/fallback, unknown without a verification error, unavailable with any attempted operation, successful sync without post-sync status, more than one sync, and missing exact fallback evidence.

- [ ] **Step 5: Preserve historical validators and make v3 the only new write**

Dispatch exactly:

```python
if version == 1:
    return validate_legacy_record_value(...)
if version == 2:
    return _validate_v2_record_value(..., schema_name="code-intelligence-record-v2.schema.json")
if version == 3:
    return _validate_v3_record_value(...)
raise RuleFailure("unsupported Code Intelligence record version")
```

`record(...)` must reject versions 1 and 2 with `new Code Intelligence records must use record_version 3`. Add `validate_historical_v2_record_value` so migration can validate canonical prior-revision v2 records without requiring the task's current revision.

- [ ] **Step 6: Update the recording CLI and template**

Support only:

```text
record_code_intelligence.py TASK-0001 --bundle <runtime bundle> --annotations <json>
record_code_intelligence.py --select-provider ...
```

Reject the old unrestricted `--input` new-write path. Update the template to a valid v3 unavailable example carrying proxy/repository/query-window/delivery fields and no attempted graph operation.

- [ ] **Step 7: Add mutation tests for every v3 invariant**

Deep-copy a valid v3 record, mutate one field per subtest, and assert `RuleFailure` for nonzero pending `CURRENT`, missing post-query status, response hash mismatch, bundle hash shape, repository mismatch, contradictory delivery/usage, stale without fallback, unsafe fallback result path, sync without post-sync observation, and v2 new-write attempt. Verify frozen v1/v2 samples remain byte-identical and readable.

- [ ] **Step 8: Run record tests**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests -k v3 -v`

Expected: all v3 tests PASS; existing v1/v2 historical tests PASS after updating only expected new-write messages.

- [ ] **Step 9: Commit Task 4**

```bash
git add schemas/code-intelligence-record-v2.schema.json schemas/code-intelligence-record-annotations.schema.json schemas/code-intelligence-record.schema.json scripts/internal/code_intelligence_protocol.py scripts/record_code_intelligence.py templates/task-sources/code-intelligence-record.json tests/test_codegraph.py
git commit -m "feat: record auditable CodeGraph proxy evidence"
```

---

### Task 5: Host adapter v3 and non-destructive project MCP registration

**Files:**
- Create: `scripts/internal/project_mcp_registration.py`
- Modify: `schemas/host-adapter.schema.json`
- Modify: `hosts/codex/adapter.json`
- Modify: `hosts/claude-code/adapter.json`
- Modify: `scripts/internal/host_adapters.py`
- Modify: `scripts/vendor_project.py`
- Modify: `scripts/init_project.py`
- Modify: `scripts/validate_project.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: Task 3's vendored entry path `tools/polaris/scripts/code_intelligence_mcp.py`.
- Produces: `project_mcp_target(repo, adapter) -> Path`, `merge_project_mcp(repo, adapter, source_text=None) -> str`, and `validate_project_mcp(repo, adapter) -> None`.

- [ ] **Step 1: Write failing adapter-v3 manifest tests**

Require each manifest to contain:

```json
"project_mcp": {
    "server_id": "polaris-codegraph",
    "format": "codex-toml",
    "target": ".codex/config.toml",
    "command": "python3",
    "args": ["tools/polaris/scripts/code_intelligence_mcp.py", "--repo", "."]
}
```

Claude differs only by `format: "claude-json"` and `target: ".mcp.json"`. Update synthetic adapters in tests to version 3 and provide a unique safe target. Reject unknown format, wrong server ID, absolute/parent paths, a launcher outside `tools/polaris`, missing `--repo .`, duplicate registration targets, and overlap with `skill_target`/`files`.

- [ ] **Step 2: Run manifest tests and confirm RED**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_host_adapter_contract_rejects_invalid_or_conflicting_manifests -v`

Expected: schema rejects v3 or missing `project_mcp`.

- [ ] **Step 3: Implement adapter-v3 schema and semantic validation**

Set `adapter_version.const` to 3 and make `project_mcp` required. Validate `server_id`, `format`, target confinement, exact project-relative launcher, argument order, and target overlap in `load_host_adapters`. Keep host discovery declarative—no host ID branches in vendoring or validation.

- [ ] **Step 4: Write failing non-destructive merge tests**

For Codex, start with:

```toml
model = "gpt-5"
[mcp_servers.other]
command = "other"
```

Assert the original bytes remain and one marked Polaris block is appended:

```toml
# POLARIS_MCP_START polaris-codegraph
[mcp_servers.polaris-codegraph]
command = "python3"
args = ["tools/polaris/scripts/code_intelligence_mcp.py", "--repo", "."]
cwd = "."
enabled = true
required = false
enabled_tools = ["polaris_codegraph_explore"]
# POLARIS_MCP_END polaris-codegraph
```

For Claude, preserve unrelated top-level fields and `mcpServers.other`, then insert exactly:

```json
"polaris-codegraph": {
    "type": "stdio",
    "command": "python3",
    "args": ["tools/polaris/scripts/code_intelligence_mcp.py", "--repo", "."],
    "env": {}
}
```

Assert idempotent rerendering, exact managed-block replacement, malformed TOML/JSON rejection, conflicting unmanaged same-name rejection, symlink rejection, and unrelated-content preservation.

- [ ] **Step 5: Implement format-specific merge/validation in one focused module**

Use `tomllib.loads` when available to validate full TOML before and after replacing the uniquely marked block. On Python 3.10, use the standard-library-only compatibility path to validate and extract the managed MCP tables while preserving unrelated TOML bytes; never rewrite unrelated TOML bytes. Use `json.loads` plus four-space `json.dumps(..., ensure_ascii=False, indent=4) + "\n"` for Claude. A same-name Claude entry is accepted only if it exactly equals the managed definition; otherwise raise `RuleFailure`.

- [ ] **Step 6: Integrate registration into the vendor transaction**

During `_stage_install`, read the target host config if present, render its merged staged form, and list it as a preserved path. Add each registration target to `_polaris_destinations`/affected paths so rollback backs it up. `init_project.initialize` merges registrations only when `protocol_root(repo) == repo / "tools/polaris"`; source-tree initialization without a vendored runtime must not create a dangling registration.

- [ ] **Step 7: Validate exact vendored runtime ownership**

In `validate_project`, parse each registration, require only the declared tool, ensure its launcher is a regular file under the vendored root, reject symlink hops, and require `--repo .`. Include the registration config in the install manifest's preserved paths, never managed files.

- [ ] **Step 8: Run host/vendoring tests**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests -k host -v`

Run: `python3 -m unittest tests.test_core.PolarisCoreTests.test_vendor_rolls_back_after_partial_apply_failure tests.test_core.PolarisCoreTests.test_force_vendor_preserves_unrelated_claude_configuration tests.test_core.PolarisCoreTests.test_vendored_target_is_self_contained -v`

Expected: all PASS; injected apply failure restores both host configs byte-for-byte.

- [ ] **Step 9: Commit Task 5**

```bash
git add scripts/internal/project_mcp_registration.py schemas/host-adapter.schema.json hosts/codex/adapter.json hosts/claude-code/adapter.json scripts/internal/host_adapters.py scripts/vendor_project.py scripts/init_project.py scripts/validate_project.py tests/test_core.py
git commit -m "feat: register the project CodeGraph proxy"
```

---

### Task 6: Protocol 0.1.21 migration and frozen v2 inventory

**Files:**
- Modify: `VERSION`
- Modify: `pyproject.toml`
- Modify: `templates/project.json`
- Modify: `templates/task/state.json`
- Modify: `templates/task-sources/state.json`
- Modify: `workflow/migrations.json`
- Modify: `scripts/internal/migration_protocol.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/USAGE.md`
- Modify: `plan.md`
- Test: `tests/test_codegraph.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: Task 4's `validate_historical_v2_record_value` and Task 5 adapter v3 registration.
- Produces: adjacent migration `0.1.20-to-0.1.21`, protocol/package version `0.1.21`, unchanged workflow `0.1.3`.

- [ ] **Step 1: Write failing version-route and frozen-v2 migration tests**

Create a valid v2 record in both current and prior revision directories, freeze their bytes, migrate, then assert:

```python
self.assertEqual(result["from"], "0.1.20")
self.assertEqual(result["to"], "0.1.21")
self.assertEqual(read_json(self.repo / ".polaris/project.json")["workflow_version"], "0.1.3")
self.assertEqual(v2_path.read_bytes(), frozen_v2_bytes)
self.assertIn(
    {"task_id": "TASK-0001", "path": "code-intelligence/r001/planning.json",
     "sha256": hashlib.sha256(frozen_v2_bytes).hexdigest()},
    migration["retired_code_intelligence_records"],
)
```

Add rejection tests for noncanonical v2 path, mutated v2 bytes on resumed migration, cross-root/dangling symlink, skipped `0.1.20 -> 0.1.22`, and workflow version change.

- [ ] **Step 2: Run migration tests and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests -k migration -v`

Expected: no `0.1.20-to-0.1.21` route and/or v2 not inventoried.

- [ ] **Step 3: Add the adjacent migration and version replacements**

Append exactly:

```json
{
    "migration_id": "0.1.20-to-0.1.21",
    "from_polaris_version": "0.1.20",
    "to_polaris_version": "0.1.21",
    "from_workflow_version": "0.1.3",
    "to_workflow_version": "0.1.3",
    "project_strategy": "replace_version",
    "task_strategy": "append_version_event"
}
```

Change only protocol/package/template version literals to `0.1.21`; leave every workflow version at `0.1.3`.

- [ ] **Step 4: Inventory v2 without weakening historical validation**

Pass the migration step into `_retired_code_intelligence_records`. For `0.1.20-to-0.1.21`, include canonical validated v2 records (and retain already supported v1 inventory) with task-relative path and exact SHA-256. Other historical migration records remain valid and byte-identical. On resume, compare the recomputed inventory with the frozen migration record before appending events.

- [ ] **Step 5: Update authority/version documentation**

Update the current-version lines and migration ledger in both READMEs, `docs/USAGE.md`, and `plan.md`. State that `0.1.21` adds the project-scoped proxy, host adapter v3, and v3 records; state explicitly that Workflow remains `0.1.3`, CodeGraph remains optional/non-gating, and v1/v2 are historical only.

- [ ] **Step 6: Run version and migration tests**

Run: `python3 -m unittest tests.test_core.PolarisCoreTests -k migration -v`

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests -k migration -v`

Expected: all PASS; route is adjacent and frozen v2 bytes do not change.

- [ ] **Step 7: Commit Task 6**

```bash
git add VERSION pyproject.toml templates/project.json templates/task/state.json templates/task-sources/state.json workflow/migrations.json scripts/internal/migration_protocol.py README.md README.zh-CN.md docs/USAGE.md plan.md tests/test_codegraph.py tests/test_core.py
git commit -m "feat: migrate CodeGraph evidence to protocol 0.1.21"
```

---

### Task 7: Stage Skills, host renderings, and user-facing proxy contract

**Files:**
- Modify: `skills/code-intelligence/SKILL.md`
- Modify: `skills/architecture-planning/SKILL.md`
- Modify: `skills/implementation/SKILL.md`
- Modify: `skills/documentation-sync/SKILL.md`
- Modify: `skills/adversarial-review/SKILL.md`
- Modify: `templates/AGENTS.md`
- Modify: relevant `hosts/*/skill-appendices/*.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/USAGE.md`
- Test: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: MCP tool name/arguments from Task 3, bundle-to-record CLI from Task 4, and registration behavior from Task 5.
- Produces: one consistent Agent/human contract across canonical, rendered, vendored, and localized surfaces.

- [ ] **Step 1: Invoke the required Skill-writing workflow**

Before changing any Skill, read and follow `superpowers:writing-skills`. Record the required baseline adversarial evaluation using these four prompts: skip the proxy, trust a clean graph with pending changes, reuse an old Implementation envelope, and treat `UNKNOWN` as current.

- [ ] **Step 2: Write failing semantic contract tests**

Render every Skill through every adapter and assert the relevant surfaces contain all exact anchors:

```python
anchors = (
    "polaris_codegraph_explore",
    "freshness envelope",
    "NON_AUTHORITATIVE_CONTEXT",
    "NAVIGATION_ONLY",
    "source/Git fallback",
    "raw `codegraph_explore`",
    "cannot back `CURRENT` Polaris evidence",
)
```

Assert Documentation Sync also contains `sync_if_needed: true`, changed source paths/documented symbols, and “no separate status/sync MCP tool”. Assert Validation surfaces contain none of `polaris_codegraph_explore`, `codegraph status`, or `codegraph sync`. Mutation-check removal of the proxy tool name and fallback branch from one rendered surface.

- [ ] **Step 3: Run semantic tests and confirm RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_require_proxy_provenance tests.test_codegraph.CodeGraphTests.test_documentation_sync_uses_one_proxy_query tests.test_codegraph.CodeGraphTests.test_validation_remains_graph_free -v`

Expected: existing direct status/sync instructions violate the new anchors.

- [ ] **Step 4: Rewrite canonical stage behavior**

Use the exact lifecycle:

1. If Code Intelligence is disabled or `.codegraph/` is absent, skip proxy and use source/Git.
2. Call only `polaris_codegraph_explore` for Polaris graph evidence.
3. Read the envelope before graph content.
4. Treat `CURRENT` as non-authoritative context.
5. For `STALE`/`UNKNOWN`, complete every named fallback before using affected conclusions.
6. Record via `record_code_intelligence.py --bundle ... --annotations ...` only if a proxy operation occurred.
7. Raw Provider MCP/shell output remains allowed but is always out-of-band and cannot support `CURRENT`.

Implementation must require a fresh call after edits. Documentation Sync must perform one bounded changed-path/symbol query with `sync_if_needed: true` only when supported source changed. Review must independently call the proxy and never inherit the implementer's envelope. Validation must remain graph-free.

- [ ] **Step 5: Update human docs without obsolete paths**

Document project trust/first-use approval, `.codex/config.toml`, `.mcp.json`, exact envelope meanings, source/Git fallback, optional/non-gating status, and user ownership of CodeGraph install/init/config/watchers. Remove stage instructions that tell users to separately choose `status` or `sync-if-needed` before raw MCP explore.

- [ ] **Step 6: Regenerate/render and run adversarial evaluation**

Run: `python3 scripts/materialize_task_layout.py`

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_require_proxy_provenance tests.test_codegraph.CodeGraphTests.test_documentation_sync_uses_one_proxy_query tests.test_codegraph.CodeGraphTests.test_validation_remains_graph_free -v`

Repeat the four baseline prompts through the Skill evaluation method required by `writing-skills`. The changed behavior must refuse every shortcut and state the required fallback.

- [ ] **Step 7: Commit Task 7**

```bash
git add skills hosts templates/AGENTS.md README.md README.zh-CN.md docs/USAGE.md tests/test_codegraph.py
git commit -m "docs: route Polaris stages through the CodeGraph proxy"
```

---

### Task 8: End-to-end acceptance, packaging, and PR readiness

**Files:**
- Modify if tests expose gaps: only files already named in Tasks 1-7
- Test: `tests/test_codegraph.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a clean, reviewable feature branch ready for draft PR and CI monitoring.

- [ ] **Step 1: Add a fake-CLI end-to-end MCP test**

Create an executable temporary `codegraph` fixture that records cwd/argv and returns scripted status/sync/explore outputs. Vendor Polaris into a disposable Git repo, initialize the task and `.codegraph/`, launch the registered MCP command, call the tool, record its bundle into v3, and run `validate_project.py`. Assert envelope order, exact call maxima, runtime ignore, record hash binding, and no graph calls during project validation.

- [ ] **Step 2: Add optional real-CLI smoke coverage**

Extend the existing disposable-repo guard. If `codegraph` is absent, skip. If present, create the temporary repo outside the Polaris workspace, never run init/configuration, and run only when the fixture already has an explicitly created safe marker/index. Assert all CLI commands use the disposable repo cwd and clean up through `TemporaryDirectory`.

- [ ] **Step 3: Run focused suites**

Run: `python3 -m unittest tests.test_codegraph -v`

Run: `python3 -m unittest tests.test_core -v`

Expected: all PASS; the optional real-CLI test may be the only skip.

- [ ] **Step 4: Run repository-wide verification**

Run: `python3 tests/run_tests.py`

Run: `python3 -m compileall -q polaris_cli.py scripts tests`

Run: `python3 scripts/materialize_task_layout.py && git diff --exit-code`

Run: `git diff --check dev...HEAD`

Run: `rg -n "record_version.?[:=].?2|0\.1\.20|adapter_version.?[:=].?2|status.*or.*sync-if-needed" README.md README.zh-CN.md docs plan.md skills hosts templates scripts schemas tests --glob '!schemas/code-intelligence-record-v2.schema.json' --glob '!schemas/code-intelligence-record-v1.schema.json'`

Expected: full suite PASS; compile/materialize/diff checks exit 0; the final scan contains only deliberate historical/migration assertions.

- [ ] **Step 5: Review the final diff against all 17 acceptance tests**

For each numbered item in the design's Testing and Evaluation section, point to one passing test name. Confirm no implementation added a dependency, daemon, watcher, retry loop, Validation graph call, alternate Provider, global MCP registration, or raw-tool restriction.

Use this coverage map during review:

| Spec test | Plan coverage |
| --- | --- |
| 1-3 pre/post pending and clean currentness | Task 2 query-window table tests |
| 4 failed/malformed status | Task 2 no-explore `UNKNOWN` tests |
| 5-6 exact, stale, wrapped, and suspicious banners | Task 1 classifier tests and Task 2 delivery tests |
| 7 shared cwd | Task 1 call-sequence test and Task 8 fake CLI |
| 8 project mismatch | Task 2 discard test |
| 9 envelope ordering | Task 3 tool result test and Task 8 transcript |
| 10 v3 pending/post-query rejection | Task 4 mutation tests |
| 11 historical v1/v2 bytes/readability | Tasks 4 and 6 migration tests |
| 12 stage/vendored/host provenance | Task 7 rendered semantic contract |
| 13 graph-free Validation | Task 7 negative surface test and Task 8 validation call log |
| 14 suite without CodeGraph | Task 8 full suite |
| 15 disposable real CLI | Task 8 guarded smoke test |
| 16 non-destructive host registration | Task 5 merge/rollback tests |
| 17 single Documentation Sync proxy | Task 7 semantic test |

- [ ] **Step 6: Commit any verification-only test corrections**

```bash
git add tests README.md README.zh-CN.md docs plan.md
git commit -m "test: verify the CodeGraph MCP proxy end to end"
```

Skip this commit if Step 4 required no changes.

- [ ] **Step 7: Hand off for branch finishing and CI**

After a clean verification run, use `superpowers:requesting-code-review`, then `superpowers:finishing-a-development-branch`. Publish a draft PR targeting `dev` with the GitHub publishing workflow. Monitor every GitHub Actions check; for any failure, use `github:gh-fix-ci`, reproduce the failing check locally, add or tighten a regression test, push the fix, and continue until all required checks pass.
