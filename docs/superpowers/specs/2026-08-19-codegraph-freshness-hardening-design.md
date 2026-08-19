# Polaris CodeGraph Freshness Hardening Design

## Status

- Date: 2026-08-19
- Status: approved for specification
- Scope: Polaris-only CodeGraph query and evidence behavior
- Provider repository changes: prohibited

## Context

Polaris already routes workflow-owned CodeGraph evidence through the
project-scoped `polaris_codegraph_explore` proxy. The proxy checks CodeGraph
status, can run one incremental sync, executes one explore query, checks status
again, and places a freshness envelope before graph output.

The current implementation does not yet meet the desired contract:

- the caller can set `sync_if_needed: false`, so freshness depends on Agent
  behavior rather than the proxy;
- an unreadable or timed-out pre-query status prevents the query, even when the
  repository identity is known and stale graph data would still be useful for
  navigation;
- response classification is coupled to older CodeGraph warning text and does
  not precisely recognize current `indexing in progress`, auto-sync-disabled,
  or changed-on-disk notices;
- a broad suspicious-word scan can confuse warning-like words in verbatim source
  with CodeGraph response framing;
- the proxy bundle does not explicitly identify the automatic refresh policy
  that governed the query.

CodeGraph is an external Provider. This change must not modify its repository,
commands, MCP tools, watcher, daemon, configuration, or index implementation.

## Goals

1. Return graph data that is as fresh as Polaris can obtain with one bounded
   incremental reconciliation.
2. Return known-stale graph data when it remains useful, but make its staleness
   impossible to miss.
3. Return graph data when freshness cannot be verified, clearly marking it as
   unknown and requiring it to be treated as stale.
4. Prevent stale or unverifiable relationships from becoming planning,
   implementation, documentation, or Review conclusions without current source
   or Git verification.
5. Preserve the optional, non-gating role of Code Intelligence.
6. Preserve all committed Code Intelligence v1, v2, and v3 records unchanged.

## Non-Goals

- Changing the CodeGraph repository or asking CodeGraph to add an API.
- Automatically running `codegraph index` or otherwise performing a full
  rebuild. Full rebuilds are always initiated by the user.
- Installing, initializing, starting, configuring, or supervising CodeGraph.
- Waiting for a watcher, polling, retrying, or adding a daemon or scheduler.
- Proving that CodeGraph parsing or inferred relationships are semantically
  correct.
- Claiming that a result remains current after it has been delivered.
- Making CodeGraph availability or freshness a workflow gate.

## Decisions

### Bounded freshness

The only positive freshness claim is `CURRENT_AT_CHECK`. It means Polaris found
no stale or unverifiable signal during the bounded pre-query, optional-sync,
query, and post-query window. It is not a permanent guarantee and is not a
claim of strict Git-commit equivalence.

### Automatic incremental reconciliation

The proxy, not the caller, owns the refresh decision. If the pre-query status
reports any pending added, modified, or removed files, the proxy runs exactly
one bounded `codegraph sync` and then checks status once more. It does this for
every Polaris stage that queries CodeGraph.

The proxy never runs `codegraph index`. Index states that require or recommend a
full rebuild remain stale and include a user-action reason.

### Useful stale and unknown output

A failed, timed-out, or malformed freshness check does not by itself prevent an
explore query when Polaris has independently established the fixed repository
identity and safe paths. The graph result is delivered as `UNKNOWN`, with
`TREAT_AS_STALE` and `NAVIGATION_ONLY` restrictions.

Known stale signals produce `STALE`. Both `STALE` and `UNKNOWN` results may guide
navigation, but no relationship or conclusion derived from them is usable until
the relevant current source or Git facts have been checked.

Repository/worktree identity mismatch or unsafe path resolution prevents the
query. Polaris must not deliver another checkout's graph as navigation for the
current checkout.

## Considered Approaches

### 1. Harden the existing Polaris proxy — selected

Keep status, optional incremental synchronization, query, post-query status,
classification, evidence, and delivery in one Polaris-owned operation. This is
the only approach that makes the freshness warning mechanically adjacent to the
graph output while leaving CodeGraph unchanged.

### 2. Mark every result stale

This is safe but discards useful `CURRENT_AT_CHECK` evidence and does not satisfy
the goal of obtaining the freshest practical data.

### 3. Use separate status and raw CodeGraph calls

This requires the Agent to preserve the association between two independent
tool calls. It can omit or overlook the warning, and it leaves a wider race
between the status observation and delivered graph content.

## Architecture

`polaris_codegraph_explore` remains the only CodeGraph path that can create
Polaris Code Intelligence evidence. Raw CodeGraph MCP and shell commands remain
available outside that evidence path and are always unverified for Polaris.

The project-scoped MCP server fixes the repository root at launch. A tool call
provides task, stage, sequential query ID, purpose, and query, but no repository
path and no refresh-policy switch. The proxy performs all operations with that
fixed repository as the working directory.

The components retain narrow responsibilities:

- `codegraph_adapter.py` invokes and normalizes CodeGraph CLI status, sync, and
  explore operations and classifies Provider response framing.
- `code_intelligence_proxy.py` validates Polaris stage context, owns the bounded
  query window, merges observations, persists immutable runtime evidence, and
  renders the freshness envelope.
- `code_intelligence_mcp.py` exposes the single project-scoped MCP tool and
  guarantees that the envelope precedes graph content.
- `code_intelligence_protocol.py` validates and projects proxy evidence into the
  existing Code Intelligence record.
- the Code Intelligence Skill performs required current-source or Git fallback
  before using stale or unknown graph conclusions.

## Query Flow

1. Validate protocol compatibility, policy, fixed repository root, task and
   stage context, query ID, purpose, and evidence-path confinement.
2. Verify that `.codegraph/` and the CodeGraph CLI are available.
3. Execute `codegraph status --json` in the fixed repository.
4. If the status proves a repository/worktree identity mismatch, stop without
   querying and return no graph content.
5. If pending changes are known, execute exactly one incremental
   `codegraph sync`, then execute one post-sync status check.
6. Do not sync merely because the index is partial, failed, built with an older
   extraction version, or has another index-wide stale reason. Those conditions
   cannot be repaired reliably by pretending an incremental sync is a rebuild.
   If pending changes coexist with an index-wide stale reason, still perform the
   one incremental sync for those changes while retaining any reason that
   remains after the post-sync check.
7. If status is unreadable or unavailable for a verification reason, retain the
   failure observation and continue. Missing Provider capability or an unsafe
   identity/path remains a no-query condition.
8. Execute one bounded `codegraph explore`. Do not retry.
9. Hash and persist an exact UTF-8 response only under the task's ignored runtime
   evidence directory. Reject overwrite or digest mismatch.
10. Classify only CodeGraph response framing and metadata notices.
11. Execute one post-query status check whenever an explore response was
    obtained.
12. Merge all observations conservatively and persist the immutable proxy
    bundle.
13. Return the freshness envelope as the first MCP content block. Return raw
    graph output, when safe and available, only in a later block.
14. Require and record the source/Git fallback for every `STALE` or `UNKNOWN`
    result before projecting or using its conclusions.

There is no wait, poll, query retry, sync retry, full rebuild, or raw-MCP
substitution.

## Delivery States

### `CURRENT_AT_CHECK`

All of the following are required:

- the effective pre-query status is structurally valid and belongs to the fixed
  repository;
- pending added, modified, and removed counts are zero after any allowed sync;
- there is no worktree mismatch, partial/indexing/failed index, pending
  resolution work, or reindex recommendation;
- explore succeeds and response framing carries no stale or unverifiable
  signal;
- post-query status is structurally valid, belongs to the same repository, and
  has zero pending changes and no unhealthy index signal.

Usage is `NON_AUTHORITATIVE_CONTEXT`. Source, Git, builds, tests, Review,
Validation, and Human decisions remain authoritative.

### `STALE`

At least one known stale signal exists, such as:

- pending changes remain before or after the query;
- the one allowed sync fails;
- CodeGraph reports pending sync, indexing in progress, changed-on-disk source,
  or disabled auto-sync;
- the index is partial, indexing, failed, has pending resolution work, or
  recommends a rebuild;
- a query-time or post-query observation proves the index changed during the
  window.

Graph output is returned when safe. Usage is `NAVIGATION_ONLY`, and the envelope
contains the exact known reasons and required fallback.

### `UNKNOWN`

Freshness cannot be established, including status timeout, malformed status,
unrecognized Provider freshness framing, post-query verification failure, or
response-integrity uncertainty.

Graph output is still returned when repository identity, path confinement, and
response integrity are safe enough to deliver it. The envelope includes
`freshness: TREAT_AS_STALE`, usage is `NAVIGATION_ONLY`, and current-source or
Git fallback is mandatory.

If a known stale signal and a verification failure coexist, the delivery must
retain both. The top-level state is `STALE` because known staleness must remain
explicit; the verification failure is an additional reason and cannot promote
the result.

### `UNAVAILABLE`

No CodeGraph data is available because policy disables it, `.codegraph/` is
absent, or the CLI is missing, so no Provider query can be attempted. Polaris
continues with source and Git. If explore is attempted but fails, the result is
instead `UNKNOWN` with no graph content because Polaris observed a verification
failure rather than Provider absence.

An identity mismatch is represented as an unverifiable no-graph result rather
than Provider absence, so diagnostics preserve the security-relevant reason.

## Response Classification

CodeGraph returns human-readable text rather than a versioned structured
freshness object. Polaris therefore maintains a conservative compatibility
adapter without modifying CodeGraph.

The classifier recognizes current documented framing for:

- referenced files pending sync;
- referenced files whose indexing is in progress;
- pending files elsewhere in the project;
- auto-sync disabled or watcher degradation;
- files changed on disk after their last index sync;
- worktree/index-root mismatch.

Classification is framing-aware. It examines only leading notices, recognized
file-section metadata, and recognized trailing notices. It must not search
verbatim source bodies for generic words such as `stale`, `warning`, or
`pending`, because those words can be legitimate program text.

Exact recognized notices create precise file- or index-scoped stale points. A
new or malformed warning-like notice in a framing position produces `UNKNOWN`.
Ordinary source text cannot create a freshness downgrade. Status JSON remains
the primary machine-readable freshness basis; response parsing is an additional
race and degradation signal.

## Freshness Envelope

Every successful proxy tool result starts with a finite block similar to:

```text
[POLARIS_CODEGRAPH_FRESHNESS]
state: UNKNOWN
record_status: NOT_VERIFIED
freshness: TREAT_AS_STALE
reason: PRE_STATUS_TIMEOUT
checked_at: 2026-08-19T00:00:00Z
pending_added: 0
pending_modified: 0
pending_removed: 0
usage: NAVIGATION_ONLY
required_fallback: SEARCH_SOURCE
evidence_bundle: runtime/code-intelligence/CIQ-001.json
[/POLARIS_CODEGRAPH_FRESHNESS]
```

The envelope is always the first content block. No stdout, stderr, diagnostic,
or graph bytes may precede it. Raw graph output, if retained, is a separate later
content block.

## Source and Git Fallback

`STALE` and `UNKNOWN` evidence cannot support a workflow conclusion until the
required fallback is complete:

- for a safe named current regular file, read it and record `READ_SOURCE` with
  its current SHA-256;
- for a safe missing or deleted file, inspect the registered subject's Git diff
  and record `INSPECT_GIT_DIFF` with the bound base, head, and diff hashes;
- for an unsafe, index-wide, or unknown point, perform a bounded repository
  search and record `SEARCH_SOURCE` with zero to 100 confined current regular
  files and their SHA-256 values.

An old graph relationship can choose where to look. Only the resulting current
source or Git fact can support a plan, edit, documentation conclusion, or Review
verdict.

## Interface and Versioning

- Polaris protocol/package version advances from `0.1.21` to `0.1.22`.
- Workflow remains `0.1.3`; no workflow node, edge, status, or transition gate
  changes.
- `polaris_codegraph_explore` removes the public `sync_if_needed` argument. The
  proxy always owns the incremental-sync decision.
- New runtime proxy evidence uses `bundle_version: 2` and records the automatic
  refresh policy.
- Bundle v1 remains readable for an interrupted pre-upgrade task, but new calls
  never write it.
- New durable Code Intelligence records remain `record_version: 3`; the current
  record already represents pre/post status, sync, query, delivery state,
  reasons, and source fallback.
- Existing v1, v2, and v3 durable records remain immutable and valid.
- The adjacent migration updates vendored protocol files, host MCP definitions,
  Skills, and validators without rewriting Code Intelligence records or
  changing workflow state.

## Failure Handling

| Condition | Query? | Delivery | Required action |
|---|---:|---|---|
| Clean pre/post status | Yes | `CURRENT_AT_CHECK` | None beyond normal authority checks |
| Pending, sync succeeds, post-sync clean | Yes | Eligible for `CURRENT_AT_CHECK` | None beyond normal authority checks |
| Pending, sync fails | Yes | `STALE` | Source/Git fallback |
| Pending remains after sync | Yes | `STALE` | Source/Git fallback |
| Index partial/failed/rebuild recommended | Yes | `STALE` | Source/Git fallback; user may rebuild |
| Pre-status timeout/malformed | Yes | `UNKNOWN` | Treat as stale; source/Git fallback |
| Post-status timeout/malformed | Yes | `UNKNOWN`, unless known stale also exists | Treat as stale; source/Git fallback |
| Unknown response-framing warning | Yes, already completed | `UNKNOWN` | Treat as stale; source/Git fallback |
| Repository/worktree identity mismatch | No | `UNKNOWN`, no graph | Source/Git fallback |
| Unsafe response path or digest mismatch | No deliverable graph | `UNKNOWN` | Source/Git fallback |
| Policy disabled, marker absent, or CLI absent | No | `UNAVAILABLE` | Use source/Git |
| Explore failure | Attempted | `UNKNOWN`, no graph | Treat as stale; use source/Git |

No failure path invokes `codegraph index`.

## Implementation Scope

Expected Polaris files include:

- `scripts/internal/codegraph_adapter.py`
- `scripts/internal/code_intelligence_proxy.py`
- `scripts/internal/code_intelligence_protocol.py`
- `scripts/code_intelligence_mcp.py`
- Code Intelligence schemas and runtime bundle validation as needed
- `skills/code-intelligence/SKILL.md` and stage Skills that call it
- host-rendered/vendored instructions and templates
- `plan.md`, README files, and usage documentation
- protocol version and adjacent migration metadata
- `tests/test_codegraph.py` and relevant core/vendoring tests

The CodeGraph repository is outside implementation scope and must remain
unchanged.

## Testing

Deterministic tests must cover:

1. clean pre/post observations produce `CURRENT_AT_CHECK`;
2. pending changes cause exactly one incremental sync for every querying stage;
3. a successful sync followed by clean status can produce `CURRENT_AT_CHECK`;
4. sync failure or remaining pending changes still runs explore and produces
   `STALE`;
5. unreadable, malformed, failed, or timed-out pre-status still runs explore and
   produces `UNKNOWN`;
6. repository/worktree mismatch prevents explore;
7. pending changes first observed after explore downgrade the result;
8. current CodeGraph pending, indexing, degraded/disabled, changed-on-disk, and
   mismatch notices classify correctly;
9. warning-like words inside returned source do not affect classification;
10. an unknown warning in a framing position produces `UNKNOWN`;
11. the envelope is always the first content block and graph output is never
    delivered before it;
12. stale and unknown records without the exact required source/Git fallback are
    rejected;
13. the MCP schema has no caller-controlled sync bypass;
14. command-runner tests prove no proxy branch can invoke `codegraph index`;
15. bundle v2 is validated and bundle v1 remains readable for interrupted
    upgrade recovery;
16. committed Code Intelligence v1, v2, and v3 records remain byte-identical and
    valid;
17. Windows paths and CRLF, macOS, and Linux behavior are covered without
    platform-specific assumptions;
18. the complete Polaris suite passes without CodeGraph installed;
19. an optional real-CLI smoke test uses only a disposable temporary repository.

## Acceptance Criteria

1. Every Polaris-delivered graph response is preceded by a machine-readable and
   human-visible freshness envelope.
2. A pending change always triggers at most one automatic incremental sync and
   can never trigger a full rebuild.
3. No caller can disable the automatic incremental-sync policy.
4. A freshness-check failure still permits safe graph delivery as `UNKNOWN`.
5. A known stale signal is always visible as `STALE`, even when other
   verification failures coexist.
6. Only a fully clean bounded window can produce `CURRENT_AT_CHECK`.
7. `STALE` and `UNKNOWN` graph data is navigation-only until current source or
   Git fallback is recorded.
8. Repository/worktree mismatch and unsafe paths never deliver graph content.
9. Existing durable Code Intelligence records remain unchanged and valid.
10. No file in the CodeGraph repository is modified.
