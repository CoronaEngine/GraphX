# CodeGraph Clean-HEAD Freshness Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a clean committed change or clean branch switch from being delivered as current CodeGraph context by attempting one incremental sync before every Polaris proxy query.

**Architecture:** Keep status, sync, explore, response classification, and post-query status inside the existing project-scoped proxy. Introduce runtime bundle v3 for the stronger refresh policy, retain v1/v2 read compatibility, and keep durable record v3 and Workflow 0.1.3 unchanged.

**Tech Stack:** Python 3.10+ standard library, `unittest`, JSON/JSON Schema, Git, CodeGraph CLI 1.5.x optional real-CLI coverage.

**Spec:** `docs/superpowers/specs/2026-08-20-codegraph-clean-head-freshness-design.md`

## Global Constraints

- Treat `plan.md` as the v0.1 product and implementation authority.
- Keep the runtime dependency-free beyond the Python standard library.
- Run at most one incremental `codegraph sync` per proxy query.
- Never run `codegraph index`, watcher, daemon, polling, or retries.
- Keep CodeGraph optional and non-gating.
- Keep Workflow version exactly `0.1.3`.
- Preserve all committed Code Intelligence v1/v2/v3 records and runtime bundle v1/v2 evidence.
- Do not modify `/Users/zero/Documents/work/ai/codegraph`.

---

### Task 1: Specify mandatory clean-status synchronization

**Files:**
- Modify: `tests/test_codegraph.py`
- Modify: `scripts/internal/codegraph_adapter.py:818-877`

**Interfaces:**
- Consumes: `inspect_status(repo, descriptor, ...) -> dict[str, Any]`.
- Produces: `synchronize_observed_status(repo, descriptor, initial, ..., force_attempt=False) -> dict[str, Any]`; `force_attempt=True` executes one sync even when `initial["needs_sync"]` is false.

- [ ] **Step 1: Add a failing adapter test for a clean initial status**

  Add a test that supplies clean status, sync success, and clean recheck; call
  `synchronize_observed_status(..., force_attempt=True)` and assert the command
  sequence is `sync`, `status`, the sync status is `SUCCESS`, and the returned
  freshness basis includes `SYNC_ACKNOWLEDGED`.

- [ ] **Step 2: Run the focused test and verify RED**

  Run:

      python3 -m unittest tests.test_codegraph.CodeGraphTests.test_clean_status_can_force_one_sync_and_recheck -v

  Expected: ERROR because `force_attempt` is not accepted.

- [ ] **Step 3: Implement the minimal adapter option**

  Extend the function signature with keyword-only `force_attempt: bool = False`
  and replace the skip condition with:

      if not force_attempt and not initial["needs_sync"]:
          return {"freshness": initial, "sync": skipped, "post_sync_status": None}

  Reject non-boolean values as `NOT_VERIFIED` without invoking CodeGraph.

- [ ] **Step 4: Verify GREEN and legacy conditional behavior**

  Run the new test plus existing pending, timeout, failure, and `sync_if_needed`
  tests. Expected: all PASS and the legacy wrapper still skips clean status.

- [ ] **Step 5: Commit Task 1**

      git add tests/test_codegraph.py scripts/internal/codegraph_adapter.py
      git commit -m "fix: support mandatory bounded CodeGraph sync"

---

### Task 2: Enforce the mandatory proxy query window

**Files:**
- Modify: `tests/test_codegraph.py`
- Modify: `scripts/internal/code_intelligence_proxy.py:52-56,340-486,489-785`

**Interfaces:**
- Consumes: Task 1 `synchronize_observed_status(..., force_attempt=True)`.
- Produces: runtime bundle v3 with `REFRESH_POLICY_V3`; retains `REFRESH_POLICY_V2` as frozen historical data.

- [ ] **Step 1: Add failing proxy behavior tests**

  Add tests that assert:

  - a clean status calls `status`, `sync`, `status`, `explore`, `status`;
  - the new bundle is version 3 and policy mode is
    `AUTO_INCREMENTAL_BEFORE_QUERY`;
  - an unreadable pre-status still syncs and explores but remains `UNKNOWN`;
  - a failed mandatory sync explores once and returns `STALE`;
  - identity mismatch calls only status.

- [ ] **Step 2: Run the focused proxy tests and verify RED**

  Expected failures: clean status omits sync, bundle version is 2, and the
  unreadable-status call sequence lacks sync.

- [ ] **Step 3: Implement the fixed window**

  Preserve the original `pre_status`, call the adapter once with
  `force_attempt=True`, and derive `effective_pre` from post-sync freshness.
  Pass original verification failure evidence into `_delivery` so a successful
  sync cannot erase an unreadable pre-status. Do not attempt sync or explore
  after a proven identity mismatch.

- [ ] **Step 4: Verify GREEN and all proxy state combinations**

  Run every test whose name starts with `test_proxy_`. Expected: all PASS.

- [ ] **Step 5: Commit Task 2**

      git add tests/test_codegraph.py scripts/internal/code_intelligence_proxy.py
      git commit -m "fix: sync every Polaris CodeGraph query window"

---

### Task 3: Preserve bundle compatibility and clarify authority

**Files:**
- Modify: `tests/test_codegraph.py`
- Modify: `scripts/internal/code_intelligence_protocol.py:1205-1367`
- Modify: `scripts/internal/code_intelligence_proxy.py:788-822`
- Modify: `scripts/code_intelligence_mcp.py:166-188`

**Interfaces:**
- Consumes: bundle versions 1, 2, and 3.
- Produces: new bundle v3 projections into unchanged durable record v3; envelope line `source_of_truth: false`.

- [ ] **Step 1: Add failing compatibility and envelope tests**

  Assert that bundle v2 is checked against frozen
  `AUTO_INCREMENTAL_ON_PENDING`, bundle v3 against
  `AUTO_INCREMENTAL_BEFORE_QUERY`, mutated policies are rejected, and the first
  MCP content block contains `source_of_truth: false` before graph content.

- [ ] **Step 2: Run the focused tests and verify RED**

  Expected: bundle v3 is unsupported and the envelope lacks the authority line.

- [ ] **Step 3: Implement version-aware bundle projection**

  Accept exact base keys for v1, frozen v2 keys/policy for v2, and the same keys
  with the new policy for v3. Continue projecting record version 3. Add the
  authority line to every rendered envelope without changing delivery enums.

- [ ] **Step 4: Verify GREEN across bundle, record, and MCP tests**

  Run bundle v1/v2/v3, proxy record projection, MCP ordering, and source fallback
  tests. Expected: all PASS.

- [ ] **Step 5: Commit Task 3**

      git add tests/test_codegraph.py scripts/internal/code_intelligence_protocol.py scripts/internal/code_intelligence_proxy.py scripts/code_intelligence_mcp.py
      git commit -m "feat: publish CodeGraph bundle v3 freshness evidence"

---

### Task 4: Add real clean-HEAD regression coverage

**Files:**
- Modify: `tests/test_codegraph.py`

**Interfaces:**
- Consumes: installed CodeGraph CLI when available; otherwise the test follows the existing optional real-CLI skip convention.
- Produces: disposable Git repositories proving clean committed and clean branch-switch drift is reconciled by one sync.

- [ ] **Step 1: Add the committed-symbol regression test**

  Initialize and index a disposable repository, commit a new uniquely named
  function without syncing, verify status reports zero pending and explore does
  not find it, run one sync, then verify explore finds it.

- [ ] **Step 2: Add the clean-branch regression test**

  Index the initial branch, create and commit a second branch with a unique
  symbol, verify the clean status blind spot, then verify one sync reconciles it.

- [ ] **Step 3: Run both tests**

  Expected: PASS with CodeGraph installed; clean skip when unavailable. Both
  disposable repositories must be outside the Polaris and CodeGraph workspaces.

- [ ] **Step 4: Commit Task 4**

      git add tests/test_codegraph.py
      git commit -m "test: cover clean HEAD CodeGraph drift"

---

### Task 5: Publish protocol 0.1.23 without changing Workflow

**Files:**
- Modify: `VERSION`
- Modify: `pyproject.toml`
- Modify: `templates/project.json`
- Modify: `templates/task-sources/state.json`
- Modify: `templates/task/state.json`
- Modify: `workflow/migrations.json`
- Modify: `scripts/internal/migration_protocol.py`
- Modify: `tests/test_codegraph.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Produces: adjacent migration `0.1.22-to-0.1.23` using `replace_version` and `append_version_event`; Workflow remains 0.1.3.

- [ ] **Step 1: Add failing version and migration tests**

  Assert every authority surface publishes 0.1.23, the migration is adjacent and
  version-only, it preserves existing record v3 bytes, and a workflow change is
  rejected.

- [ ] **Step 2: Run focused tests and verify RED**

  Expected: current authorities remain 0.1.22 and the migration is absent.

- [ ] **Step 3: Update versions and append the migration**

  Change only Polaris/package versions to 0.1.23. Append exactly one migration
  entry from 0.1.22 to 0.1.23 with Workflow 0.1.3 on both sides. Keep its
  retirement inventory empty through the existing non-inventory behavior.

- [ ] **Step 4: Verify GREEN across migration and vendoring tests**

  Run version, migration, install-manifest, vendoring, and self-contained target
  tests. Expected: all PASS.

- [ ] **Step 5: Commit Task 5**

      git add VERSION pyproject.toml templates/project.json templates/task-sources/state.json templates/task/state.json workflow/migrations.json scripts/internal/migration_protocol.py tests/test_codegraph.py tests/test_core.py
      git commit -m "chore: advance Polaris protocol to 0.1.23"

---

### Task 6: Synchronize product authority and verify end to end

**Files:**
- Modify: `plan.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/USAGE.md`
- Modify: `skills/code-intelligence/SKILL.md`
- Modify: `skills/architecture-planning/SKILL.md`
- Modify: `skills/implementation/SKILL.md`
- Modify: `skills/documentation-sync/SKILL.md`
- Modify: `skills/adversarial-review/SKILL.md`
- Modify: `templates/AGENTS.md`
- Modify: `tests/test_codegraph.py`
- Modify: `tests/test_core.py`

**Interfaces:**
- Produces: one consistent user and Agent contract for mandatory incremental sync, finite freshness, and non-authoritative graph usage.

- [ ] **Step 1: Add failing surface-contract tests**

  Require all CodeGraph-capable Skills and user authorities to state that every
  proxy query attempts one incremental sync, raw results remain unverified, and
  CodeGraph is never source of truth. Require release notes to name protocol
  0.1.23 and Workflow 0.1.3.

- [ ] **Step 2: Run focused tests and verify RED**

  Expected: existing surfaces still say sync occurs only when pending exists.

- [ ] **Step 3: Update canonical Skills, template, plan, and documentation**

  Replace pending-only wording with mandatory per-query incremental sync. State
  that status pending counts alone do not bind the graph to clean HEAD. Retain
  all source/Git fallback, raw-tool, ownership, optionality, and Validation
  boundaries.

- [ ] **Step 4: Run focused documentation and Skill tests**

  Expected: all surface and documentation consistency tests PASS.

- [ ] **Step 5: Run complete verification**

      python3 tests/run_tests.py
      python3 scripts/check_docs.py --help
      git diff --check
      git status --short
      git -C /Users/zero/Documents/work/ai/codegraph status --short

  Expected: complete suite PASS, no whitespace errors, only intended Polaris
  files changed, and the CodeGraph repository remains clean.

- [ ] **Step 6: Commit Task 6**

      git add plan.md README.md README.zh-CN.md docs/USAGE.md skills templates/AGENTS.md tests/test_codegraph.py tests/test_core.py docs/superpowers/specs/2026-08-20-codegraph-clean-head-freshness-design.md docs/superpowers/plans/2026-08-20-codegraph-clean-head-freshness.md
      git commit -m "docs: define clean HEAD CodeGraph freshness"
