# Polaris CodeGraph clean-HEAD freshness hardening design

## Status

- Date: 2026-08-20
- Status: approved for implementation
- Scope: Polaris CodeGraph proxy, evidence, documentation, and adjacent version migration
- CodeGraph repository: read-only dependency; do not modify it

## Problem

Polaris 0.1.22 runs `codegraph sync` only when `codegraph status --json`
reports pending added, modified, or removed files. CodeGraph 1.5.0 uses Git
status as its fast-path candidate list. After an indexed file is changed and
committed, or after switching to another clean branch in the same worktree,
Git status can be empty even though the CodeGraph database still describes the
previous clean HEAD. Both Polaris status observations can therefore report zero
pending changes, a neutral explore response can omit a newly committed symbol,
and the proxy can incorrectly deliver `CURRENT`.

## Goals

1. Every Polaris proxy query automatically attempts exactly one bounded
   incremental `codegraph sync`, even when the initial status reports zero
   pending changes.
2. A clean committed change or clean branch switch must not be delivered as
   current merely because Git status is empty.
3. `CURRENT` remains a finite at-check observation and is explicitly never a
   source of truth.
4. Status, sync, response, or identity failures remain conservative and
   non-gating.
5. Existing durable Code Intelligence records and runtime bundle v1/v2 remain
   readable without rewriting them.

## Non-goals

- Do not run `codegraph index`.
- Do not start, configure, wait for, or manage a watcher or daemon.
- Do not make CodeGraph a workflow gate.
- Do not change Workflow 0.1.3 states or transitions.
- Do not claim that CodeGraph is strictly bound to a Git commit.
- Do not modify the CodeGraph repository.

## Query window

The proxy-owned window is:

1. Validate the fixed repository, task, stage, query identity, policy, marker,
   and CLI availability.
2. Run pre-status.
3. Refuse sync and explore when pre-status proves a project or worktree identity
   mismatch.
4. Otherwise run exactly one `codegraph sync --quiet`, regardless of pending
   counts.
5. Run one post-sync status check.
6. Run exactly one explore when repository identity remains safe.
7. Classify the response and run one post-query status check.
8. Conservatively merge every observation and emit the envelope before graph
   content.

An unreadable pre-status does not block a safe sync or explore, but it remains
verification-failure evidence: later clean observations must not promote the
delivery above `UNKNOWN`. A known stale signal remains `STALE` even when another
observation is unreadable. A failed sync remains `STALE` and the graph may still
be returned only for navigation.

## Evidence compatibility

New proxy calls write runtime bundle version 3 with this fixed policy:

    {
        "mode": "AUTO_INCREMENTAL_BEFORE_QUERY",
        "max_sync_attempts": 1,
        "full_rebuild": "USER_ONLY"
    }

Bundle v1 and v2 remain projectable under their frozen historical contracts.
Durable Code Intelligence records remain record version 3; new bundle
provenance guarantees the stronger write path without invalidating already
committed record v3 evidence.

## User-visible authority

Every freshness envelope includes `source_of_truth: false`. Delivery semantics
remain:

- `CURRENT / NON_AUTHORITATIVE_CONTEXT`: bounded context observed clean after
  the mandatory sync; source and Git remain authority.
- `STALE / NAVIGATION_ONLY`: known stale signal; exact source/Git fallback is
  required.
- `UNKNOWN / TREAT_AS_STALE / NAVIGATION_ONLY`: freshness cannot be proved;
  exact source/Git fallback is required.
- `UNAVAILABLE / NO_GRAPH`: no graph content.

Raw CodeGraph tools remain out-of-band, unverified, and unable to support
Polaris `CURRENT` evidence.

## Versioning

Polaris advances from 0.1.22 to 0.1.23. Workflow remains 0.1.3. The adjacent
0.1.22-to-0.1.23 migration replaces only the Polaris version and appends the
normal version event; it neither inventories nor rewrites Code Intelligence
records.

## Acceptance tests

- A clean initial status still causes exactly one sync before explore.
- A clean committed new symbol is discovered after the mandatory sync.
- A clean branch switch is reconciled before explore.
- Unknown pre-status is never promoted to current by later clean observations.
- Sync failure or unhealthy post-sync status cannot become current.
- Project/worktree mismatch runs neither sync nor explore.
- Bundle v1/v2 remain readable; new bundles are v3 with the fixed policy.
- The first MCP content block states `source_of_truth: false`.
- The full standard-library-only test suite passes without CodeGraph installed.

