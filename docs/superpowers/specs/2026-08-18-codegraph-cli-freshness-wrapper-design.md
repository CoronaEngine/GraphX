# CodeGraph CLI Freshness Wrapper Design

## Status

- Date: 2026-08-18
- Status: proposed for implementation
- Scope: Polaris Code Intelligence protocol and stage behavior
- Provider: `colbymchenry/codegraph`

## Problem

Polaris currently lets Planning, Implementation, and Review choose either a
standalone CodeGraph `status` check or `sync-if-needed`, then query
`codegraph_explore` directly. A structurally healthy status with non-zero
`pendingChanges` is represented internally as `CURRENT_AT_CHECK` plus
`needs_sync: true`. The compact v2 record does not retain `needs_sync` or the
pending counts, so a status-only path can discard the known stale signal and
still validate as `CURRENT_AT_CHECK`.

Freshness checks and queries also use different transports: status and sync
run through the CLI in the repository working directory, while explore
prefers the host MCP connection. Polaris does not bind those operations to the
same project or deliver one mandatory freshness warning together with the
graph response.

The required behavior is deliberately fail-safe:

- Polaris may give an Agent stale graph output.
- Polaris must tell the Agent when the output is stale or cannot be verified.
- Known stale or unverifiable output must never be presented as current.
- Stale output remains useful only as a navigation lead; current source and
  Git remain authoritative.

## Guarantee Boundary

The wrapper guarantees that every graph response delivered by a Polaris stage
has an adjacent Polaris freshness envelope, and that every freshness signal
Polaris observes is classified conservatively. It does not prove that
CodeGraph's parser or relationship inference is semantically correct, and it
does not claim permanent or commit-exact freshness after delivery.

The core invariant is:

> Absence of freshness proof is not freshness. Any known stale signal becomes
> `STALE`; any unavailable or unreadable proof becomes `UNKNOWN`; only a fully
> healthy bounded query window may become `CURRENT`.

`UNKNOWN` has the same Agent usage restrictions as `STALE`.

## Selected Approach

Add a Polaris-owned CLI freshness wrapper and make it the only CodeGraph query
entry point used by Polaris stages. The wrapper uses CodeGraph CLI commands for
status, optional one-shot sync, and explore, all with the same explicit
repository working directory. It writes the raw response only to the ignored
task runtime and emits a freshness envelope before any graph content.

Direct `codegraph_explore` MCP calls remain available outside Polaris, but
Polaris stage Skills must not use them. If the wrapper cannot run, the stage
falls back to source and Git rather than calling the Provider directly.

This approach is preferred over instruction-only changes because the warning
must be mechanically adjacent to the graph response. It is preferred over a
new MCP proxy because the existing CLI exposes equivalent `status`, `sync`,
and `explore` operations without adding a daemon or transport subsystem.

## CLI Surface

Create `scripts/code_intelligence_query.py` with one bounded operation:

```text
python3 scripts/code_intelligence_query.py TASK-0001 \
  --repo . \
  --stage PLANNING \
  --query-id CIQ-001 \
  --purpose "discover frozen-task relationships" \
  --sync-if-needed \
  --query "symbols and paths relevant to the frozen task"
```

Required inputs:

- task ID, used to confine runtime evidence;
- repository path;
- Polaris stage and finite query purpose;
- the next sequential `CIQ-*` ID for this stage record;
- one non-empty query string.

`--sync-if-needed` permits the existing one-shot sync behavior. Omitting it is
read-only and does not wait for CodeGraph auto-sync. Neither mode sleeps,
polls, retries, initializes CodeGraph, or manages its daemon or watcher.

The command exits successfully when graph output is available, even when its
delivery state is `STALE` or `UNKNOWN`. Provider execution failure exits
successfully only after emitting an `UNKNOWN` envelope with no graph response
and a required source fallback. Invalid Polaris inputs remain command errors.

## Query Flow

1. Validate protocol compatibility, project configuration, `.codegraph/`, task
   identity, stage, purpose, and runtime confinement.
2. Run a CLI pre-query status check in `cwd=repo`.
3. If `--sync-if-needed` is set and the pre-query status has pending changes,
   run at most one bounded sync and at most one post-sync status check.
4. If the effective pre-query state permits a query, run one bounded
   `codegraph explore` in the same `cwd=repo`. Known pending changes and
   index-stale states permit a navigation-only query; unavailable status,
   project mismatch, or an unreadable pre-query status do not.
5. Save its exact UTF-8 response below
   `runtime/code-intelligence/`; never write raw output to Git artifacts.
6. Classify the response banner.
7. Run one CLI post-query status check.
8. Merge pre-query, sync, response, and post-query observations using the most
   conservative state.
9. Emit the envelope first, followed by raw graph output only when available.
10. Include the compact evidence bundle path in the envelope for the immutable
    stage record. The explicit query ID determines its unique runtime filename;
    the wrapper rejects an existing destination rather than overwriting it.

There is no query retry. A stale response is delivered once with restrictions;
an unknown response is either delivered as navigation-only evidence or
discarded when its project or response integrity cannot be established.

## Delivery States

### `CURRENT`

Allowed only when all of the following hold:

- pre-query or successful post-sync status is structurally healthy;
- its `projectPath` resolves to the requested repository;
- pending added, modified, and removed counts are all zero;
- there is no worktree mismatch, partial/indexing/failed index, pending
  reference, or reindex recommendation;
- the explore response contains no stale or disabled-auto-sync banner;
- the post-query status is also structurally healthy with zero pending counts.

The envelope uses `usage: NON_AUTHORITATIVE_CONTEXT`. Source, Git, builds,
tests, Review, and Validation remain authoritative.

### `STALE`

Used when Polaris observes any known stale signal, including:

- non-zero pending source changes before or after the query;
- a per-file stale response banner;
- auto-sync disabled;
- worktree mismatch;
- partial, indexing, or failed index state;
- pending references or reindex recommendation;
- a failed sync or an unhealthy post-sync status.

The envelope uses `usage: NAVIGATION_ONLY` and supplies exact required
fallback actions. A pending count without safe file names makes the entire
query `INDEX_STALE`; Polaris must not infer that unlisted relationships are
current.

### `UNKNOWN`

Used when freshness cannot be established, including missing capabilities,
timeouts, malformed status JSON, malformed recognized banners, unsafe paths,
project mismatch, or an unclassifiable Provider response. The envelope uses
`usage: NAVIGATION_ONLY` and requires repository source search and Git
evidence. It must never be promoted to `CURRENT` by a banner-free response.

Response classification is fail-safe. An exact supported banner produces its
documented stale state. Any other warning-like response containing a warning
marker, stale wording, or pending-sync wording produces `UNKNOWN`, including a
supported banner wrapped in prose, quotation, leading whitespace, or a BOM.
Only a response with no supported or suspicious freshness signal is neutral.

`UNAVAILABLE` remains the no-query state for disabled Code Intelligence,
missing `.codegraph/`, or missing CLI capability.

## Envelope

Every successful wrapper invocation begins stdout with a finite block:

```text
[POLARIS_CODEGRAPH_FRESHNESS]
state: STALE
record_status: INDEX_STALE
reason: PENDING_CHANGES
checked_at: 2026-08-18T12:00:00Z
pending_added: 0
pending_modified: 1
pending_removed: 0
usage: NAVIGATION_ONLY
required_fallback: SEARCH_SOURCE
evidence_bundle: runtime/code-intelligence/CIQ-001.json
[/POLARIS_CODEGRAPH_FRESHNESS]
```

The raw CodeGraph response, when retained, follows this block. The wrapper
must never print graph output before the envelope. Human-readable diagnostic
text is captured into the finite envelope error field. The wrapper flushes the
complete stdout envelope before writing graph bytes or any stderr diagnostic,
so a combined host transcript cannot expose raw graph content first.

## Evidence and Record Protocol

Introduce a new Code Intelligence record version rather than weakening or
rewriting immutable v2 evidence. Preserve v1 and v2 records as readable
historical artifacts; new stage records use v3.

The v3 query evidence contains:

- Provider ID and descriptor version;
- repository identity and stage target;
- query purpose and response SHA-256;
- pre-query status observation;
- optional sync observation and post-sync status;
- post-query status observation;
- pending added, modified, and removed counts for each successful status;
- response-banner classification and stale points;
- delivery state and usage restriction;
- exact source/Git fallback evidence.

`CURRENT` requires successful pre-query/effective status and post-query status
evidence with zero pending changes. `STALE` requires at least one explicit
stale reason. `UNKNOWN` requires an explicit verification failure. The
validator rejects missing observations, contradictory state, project
mismatch, response-hash mismatch, or a `CURRENT` claim with any non-zero
pending count.

Migration inventories immutable v2 records without rewriting them. The
Polaris protocol version increments; the workflow graph version does not
change because no workflow state or transition changes.

## Stage Behavior

- Planning, Implementation, and Review call only the wrapper for graph
  queries. They may request one-shot sync but cannot call raw MCP explore.
- Implementation may query after edits only through a fresh wrapper
  invocation; it does not reuse the entry envelope.
- Documentation Sync uses the same wrapper/status machinery for its final
  bounded sync evidence when supported source changed.
- Validation remains graph-free.
- On `STALE` or `UNKNOWN`, stage conclusions concerning returned files or
  relationships require the envelope's source/Git fallback before use.

Vendored `AGENTS.md`, host overlays, and canonical Skills must share this
contract. Because these are behavior-shaping Skill changes, they require the
repository's `writing-skills` workflow and adversarial before/after evaluation.

## Failure Handling

- Missing `.codegraph/` or disabled policy: emit `UNAVAILABLE`, no query.
- Missing CLI: emit `UNAVAILABLE`, no MCP bypass.
- Status failure before query: emit `UNKNOWN`; source fallback; no query by
  default.
- Explore failure: emit `UNKNOWN`; record the finite error; no graph output.
- Post-query status failure: graph may be delivered only as `UNKNOWN` and
  navigation-only.
- Pending changes after a successful explore: deliver as `STALE`, never
  `CURRENT`.
- Unsafe or cross-project response paths: discard the graph response and use
  source search.
- Sync failure: do not retry; continue with a stale or unknown envelope.

## Testing and Evaluation

Deterministic unit and integration tests must cover:

1. pending pre-query status cannot produce `CURRENT`;
2. pending post-query status downgrades an otherwise clean response;
3. zero-pending pre/post status plus a clean response produces `CURRENT`;
4. failed or malformed status produces `UNKNOWN` and never calls raw MCP;
5. stale and disabled-auto-sync banners produce `STALE`;
6. prefixed, malformed, or changed banner shapes fail conservatively;
7. CLI status and explore always share the requested `cwd`;
8. project mismatch discards graph output;
9. envelope always precedes graph bytes;
10. v3 validator rejects `CURRENT` with pending counts or missing post-query
    evidence;
11. historical v1/v2 records remain byte-identical and readable;
12. Planning, Implementation, Documentation Sync, Review, vendored agents,
    and host renderings prohibit raw CodeGraph MCP use;
13. Validation remains graph-free;
14. the full Polaris suite passes without requiring CodeGraph;
15. an optional real-CLI smoke test uses only a disposable temporary repo.

Skill evaluation must include pressure cases where an Agent is asked to skip
the wrapper, trust a clean-looking graph despite pending changes, reuse an old
Implementation envelope, or treat `UNKNOWN` as current. The post-change Agent
must refuse each shortcut and perform the required fallback.

## Non-Goals

- Proving that CodeGraph's parser or inferred relationships are semantically
  correct.
- Making graph freshness a workflow or acceptance gate.
- Waiting for automatic sync to finish.
- Installing, initializing, configuring, or managing CodeGraph.
- Building a second watcher, daemon, index, or MCP proxy.
- Guaranteeing that a response remains current after it has been delivered.

## Acceptance Criteria

1. No Polaris stage can receive CodeGraph graph output without a preceding
   freshness envelope from the wrapper.
2. Any observed pending change, stale banner, unhealthy index, project
   mismatch, or failed verification prevents a `CURRENT` delivery.
3. `UNKNOWN` is mechanically restricted exactly like `STALE`.
4. Pending counts and pre/post-query evidence remain auditable in immutable v3
   records.
5. Stale graph output remains available as navigation-only evidence with
   mandatory current-source or Git fallback.
6. Existing historical records and workflow transitions remain valid.
