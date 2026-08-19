---
name: code-intelligence
description: Internal optional Polaris stage support for bounded CodeGraph relationship queries. Invoke only from an active `{{skill:engineering-task}}` workflow when Planning, Implementation, Documentation Sync, or Review can benefit from indexed code relationships; never activate from ordinary requests or make provider availability a workflow gate.
---

# Code Intelligence

CodeGraph is optional navigation context. Source, Git, builds, tests, frozen artifacts, Review, Validation, and Human decisions remain authority.

1. Load `.polaris/code-intelligence.json` and project rules. If policy disables Code Intelligence or the repository root lacks `.codegraph/`, skip the proxy, use source/Git, and omit the Code Intelligence record because no proxy operation ran. Never run `codegraph init`.
2. For Polaris graph evidence call only `polaris_codegraph_explore`, using the active task ID, legal stage, next `CIQ-NNN`, bounded purpose/query, and the stage's declared `sync_if_needed` value. The project registration fixes the repository root. Use no separate status/sync MCP tool and do not retry, poll, wait, or run another query after an envelope requires the stage fallback.
3. Read the `freshness envelope` before any graph content:
   - `CURRENT` with `usage: NON_AUTHORITATIVE_CONTEXT` permits the graph only as non-authoritative context.
   - `STALE` or `UNKNOWN` with `usage: NAVIGATION_ONLY` requires every named source/Git fallback. `NAVIGATION_ONLY` never substantiates an edit or conclusion, even after fallback; only the resulting current source/Git evidence does. Index-wide uncertainty affects the entire graph response. `UNKNOWN` is never current.
   - `UNAVAILABLE` with `usage: NO_GRAPH` means use source/Git and do not expect graph content.
4. Complete fallbacks exactly. For a safe named current regular file, read it and record `READ_SOURCE` with its current SHA-256. For a safe missing/deleted path, inspect the registered subject diff and record `INSPECT_GIT_DIFF` with null observed SHA-256 and bound base/head/diff hashes. For an unsafe path or index-wide stale/unknown result, perform an actual bounded repository search and record `SEARCH_SOURCE` with zero to 100 unique confined POSIX `result_paths`, each a current regular file and current SHA-256; an empty result is valid only when that search found no current file. In `STALE`/`UNKNOWN`, annotate a symbol only when its current path is covered by `READ_SOURCE` or a hashed `SEARCH_SOURCE` result.
5. A raw `codegraph_explore` MCP call or `codegraph explore` shell command remains user-accessible out-of-band, but its output is always unverified for Polaris and cannot back `CURRENT` Polaris evidence. Never project raw Provider output into a Polaris record.
6. If the proxy ran, use the envelope's `evidence_bundle` path, write an annotations JSON containing only `summary`, confirmed `symbols`, and completed `source_fallbacks`, then run `record_code_intelligence.py <task-id> --repo . --bundle <bundle-path> --annotations <annotations-path>`. This projects an immutable v3 record; do not hand-author records. If the proxy did not run, omit the Code Intelligence record and optional artifact reference.
7. Never install, initialize, start, authenticate, configure, reconfigure, or manage CodeGraph, its watcher, daemon, lock, raw MCP registration, or project index. Proxy failure and every non-current state are non-gating.

Stage policy:

- Planning: query only frozen-task relationships needed to justify Working Set entries. Confirm safe current returned paths in current source before recording the query ID as `discovered_from`; confirm a safe missing/deleted path through the registered subject Git diff instead.
- Implementation: make a bounded handoff-scoped call before editing when useful. Any conclusion needed after edits requires a fresh `polaris_codegraph_explore` call; never reuse the entry freshness envelope. If an earlier non-current envelope ended graph use for the stage, use source/Git only rather than making that post-edit call.
- Documentation Sync: only when supported source changed, make one query over changed source paths and documented symbols with `sync_if_needed: true`; there is no separate status/sync MCP tool.
- Review: independently query only registered-subject impact relationships. Never inherit or reuse the Implementer's envelope, bundle, or conclusions.
- Validation: do not invoke this Skill. Validation remains graph-free.
