# Polaris-only CodeGraph MCP Freshness Proxy Design

## Status

- Date: 2026-08-18
- Status: approved for implementation on 2026-08-19
- Scope: Polaris Code Intelligence protocol and stage behavior
- Provider: `colbymchenry/codegraph`

## Version Boundary

- Polaris protocol and package version: `0.1.20` to `0.1.21`.
- Workflow graph version: remains `0.1.3`; no state or transition changes.
- Host adapter manifest version: v2 to v3.
- Code Intelligence records written by new stages: v3.
- Code Intelligence v1 and v2 records: immutable historical read support only.

The adjacent `0.1.20` to `0.1.21` migration inventories immutable v2 records
without rewriting them. It upgrades the host registration and protocol files,
but does not alter the workflow graph.

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

The proxy guarantees that every proxy graph response delivered by a Polaris
stage has an adjacent Polaris freshness envelope, and that every freshness
signal Polaris observes is classified conservatively. It does not prove that
CodeGraph's parser or relationship inference is semantically correct, and it
does not claim permanent or commit-exact freshness after delivery.

The original `codegraph_explore` MCP tool and unrestricted shell access remain
available. Consequently, Polaris cannot prevent an Agent from bypassing the
proxy. It can require the proxy in canonical stage instructions and
mechanically reject Code Intelligence evidence that lacks proxy provenance,
but it cannot prove that an Agent never observed an out-of-band raw response.

The core invariant is:

> Absence of freshness proof is not freshness. Any known stale signal becomes
> `STALE`; any unavailable or unreadable proof becomes `UNKNOWN`; only a fully
> healthy bounded query window may become `CURRENT`.

`UNKNOWN` has the same Agent usage restrictions as `STALE`.

## Selected Approach

Add a project-scoped Polaris MCP server exposing one
`polaris_codegraph_explore` tool. Polaris stage Skills use this proxy for
freshness-aware graph queries. The existing `codegraph_explore` MCP tool stays
installed and callable for non-Polaris work, and Polaris does not remove,
wrap, deny, or restrict shell commands.

The proxy uses CodeGraph CLI commands internally for status, optional
one-shot sync, and explore, all with the same explicit repository working
directory. This avoids an MCP-to-MCP dependency while preserving output
equivalence with `codegraph_explore`. It writes the raw response only to the
ignored task runtime and returns a structured freshness envelope together
with any graph content.

If the proxy cannot run, the Polaris stage falls back to source and Git. It
must not silently substitute the raw Provider tool for Polaris evidence.
Agents remain free to use the original tool or shell outside that evidence
path, but any such output is unverified navigation context and cannot produce
a `CURRENT` Polaris record.

This approach is preferred over instruction-only changes because freshness
must be mechanically adjacent to the graph response. It preserves the raw
Provider and shell surfaces as requested while giving Polaris records one
auditable, fail-safe path.

## MCP Surface

Create `scripts/code_intelligence_mcp.py`, a standard-library stdio MCP server
launched from the vendored Polaris project runtime. It exposes one bounded
tool:

```text
polaris_codegraph_explore({
  "task_id": "TASK-0001",
  "stage": "PLANNING",
  "query_id": "CIQ-001",
  "purpose": "discover frozen-task relationships",
  "query": "symbols and paths relevant to the frozen task",
  "sync_if_needed": true
})
```

Required inputs:

- task ID, used to confine runtime evidence;
- Polaris stage and finite query purpose;
- the next sequential `CIQ-*` ID for this stage record;
- one non-empty query string.

The repository is fixed by the project-scoped server launch configuration and
is intentionally not a tool argument.

`sync_if_needed: true` permits the existing one-shot sync behavior. `false` is
read-only and does not wait for CodeGraph auto-sync. Neither mode sleeps,
polls, retries, initializes CodeGraph, or manages its daemon or watcher.

The MCP result is successful when graph output is available, even when its
delivery state is `STALE` or `UNKNOWN`. Provider execution failure returns an
`UNKNOWN` result with no graph response and a required source fallback.
Invalid Polaris inputs return an MCP tool error.

## Query Flow

1. Validate protocol compatibility, project configuration, `.codegraph/`, task
   identity, stage, purpose, and runtime confinement.
2. Run a CLI pre-query status check in `cwd=repo`.
3. If `sync_if_needed` is true and the pre-query status has pending changes,
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
    the proxy rejects an existing destination rather than overwriting it.

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

## Proxy Activation

The proxy is project-scoped and Polaris-owned. Host adapters render a local
MCP registration that launches the vendored server with one fixed repository
root. They do not add a global server, change the user's raw CodeGraph MCP
registration, remove any CodeGraph tool, or alter shell permissions.

The server process receives the repository root at launch and does not accept
an arbitrary project path from the tool call. It rejects a missing, moved, or
symlinked project root. Removing or disabling the project-local Polaris MCP
registration disables the proxy without affecting CodeGraph itself.

Host adapter v3 adds one required declarative `project_mcp` registration. It
identifies the fixed `polaris-codegraph` server ID, the host-native project
configuration target and format, and the project-relative vendored launcher.
For the supported hosts, the targets are `.codex/config.toml` for Codex and
`.mcp.json` for Claude Code. The host renderer owns these syntax differences;
the Code Intelligence adapter remains host-neutral.

Initialization and vendoring merge only the named `polaris-codegraph` entry
and preserve unrelated user servers and settings. They refuse malformed host
configuration, path/symlink escape, or an existing same-name registration with
a different definition instead of silently overwriting it. Upgrade removes or
replaces only the previously managed Polaris entry. Project validation parses
the resulting host configuration and proves that this entry launches only
`tools/polaris/scripts/code_intelligence_mcp.py`, fixes the repository argument
to the project root, and exposes no user-selected repository parameter.

The launcher and server independently resolve and compare the configured root
with the actual project root. A host starting the process from an unexpected
working directory therefore fails closed rather than querying another
repository. Host-native trust or first-use approval remains a user decision;
Polaris does not bypass it.

## Envelope

Every successful proxy tool result begins with a finite text content block:

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

The raw CodeGraph response, when retained, is a later content block in the same
MCP tool result. The proxy must never return graph content before the envelope.
Human-readable diagnostics are captured in the finite envelope error field;
subprocess stdout and stderr are never forwarded ahead of the envelope.

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
Polaris protocol and package version become `0.1.21`; the workflow graph stays
at `0.1.3` because no workflow state or transition changes.

## Stage Behavior

- Planning, Implementation, and Review use the proxy for freshness-aware
  Polaris graph evidence. The raw `codegraph_explore` remains callable, but
  its output is out-of-band, always unverified for Polaris, and cannot back a
  `CURRENT` stage record.
- Implementation may query after edits only through a fresh proxy invocation
  for Polaris evidence; it does not reuse the entry envelope.
- When supported source changed, Documentation Sync makes one bounded
  `polaris_codegraph_explore` call with `stage: DOCUMENTATION_SYNC`,
  `sync_if_needed: true`, and a query limited to the changed source paths and
  documented symbols. Its post-query status is the final sync observation;
  there is no second status/sync MCP tool. When no supported source changed,
  it creates no Code Intelligence record. `STALE` or `UNKNOWN` results require
  the same source/Git fallback before documentation conclusions are used.
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
4. failed or malformed status produces `UNKNOWN` and does not run Provider
   explore inside the proxy;
5. stale and disabled-auto-sync banners produce `STALE`;
6. prefixed, malformed, or changed banner shapes fail conservatively;
7. CLI status and explore always share the requested `cwd`;
8. project mismatch discards graph output;
9. envelope always precedes graph bytes;
10. v3 validator rejects `CURRENT` with pending counts or missing post-query
    evidence;
11. historical v1/v2 records remain byte-identical and readable;
12. Planning, Implementation, Documentation Sync, Review, vendored agents,
    and host renderings require proxy provenance for Polaris evidence while
    preserving the raw CodeGraph MCP tool and unrestricted shell access;
13. Validation remains graph-free;
14. the full Polaris suite passes without requiring CodeGraph;
15. an optional real-CLI smoke test uses only a disposable temporary repo.
16. host registration merges into existing Codex TOML and Claude JSON without
    changing unrelated servers or settings, rejects conflicting same-name
    entries and unsafe paths, and validates the exact vendored launcher/root;
17. Documentation Sync uses the single explore proxy for its final bounded
    query, skips graph evidence when supported source did not change, and
    never calls a separate sync/status MCP tool.

Skill evaluation must include pressure cases where an Agent is asked to skip
the proxy, trust a clean-looking graph despite pending changes, reuse an old
Implementation envelope, or treat `UNKNOWN` as current. The post-change Agent
must refuse each shortcut and perform the required fallback.

## Non-Goals

- Proving that CodeGraph's parser or inferred relationships are semantically
  correct.
- Making graph freshness a workflow or acceptance gate.
- Waiting for automatic sync to finish.
- Installing, initializing, configuring, or managing CodeGraph.
- Building a second watcher, daemon, or index.
- Removing, disabling, or restricting the original CodeGraph MCP tool.
- Restricting shell access or rejecting ordinary shell use outside Polaris
  Code Intelligence evidence.
- Guaranteeing that a response remains current after it has been delivered.

## Acceptance Criteria

1. No CodeGraph output can be accepted as Polaris Code Intelligence evidence
   without a proxy evidence bundle whose MCP result placed the freshness
   envelope before the graph content.
2. Any observed pending change, stale banner, unhealthy index, project
   mismatch, or failed verification prevents a `CURRENT` delivery.
3. `UNKNOWN` is mechanically restricted exactly like `STALE`.
4. Pending counts and pre/post-query evidence remain auditable in immutable v3
   records.
5. Stale graph output remains available as navigation-only evidence with
   mandatory current-source or Git fallback.
6. Existing historical records and workflow transitions remain valid.
7. The original `codegraph_explore` tool and unrestricted shell access remain
   available and unchanged.
