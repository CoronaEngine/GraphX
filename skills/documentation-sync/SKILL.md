---
name: documentation-sync
description: Internal Polaris worker stage for an explicitly started `{{skill:engineering-task}}` workflow. Invoke only by continuing the same dedicated Implementer task in IMPLEMENTING to reconcile documentation; do not activate from ordinary documentation requests.
---

# Documentation Sync

1. Continue in the same Implementer conversation and reload the Implementation artifact. If live progress exists, validate it and use the updater's `SET_PHASE` event to enter `DOCUMENTING`; otherwise continue without creating telemetry. Do not alter the terminal Implementation steps.
2. Compare changed subject paths with project documentation and the frozen Work Item.
3. Write a Knowledge Delta JSON with an entry for every affected knowledge area: `ADD`, `UPDATE`, `STALE`, or `NO_CHANGE`.
4. Update confirmed project documentation. Do not promote unverified inference to authority.
5. Record failed attempts with `record_exploration.py`. Keep task-only conclusions in the task; promote reusable, evidence-backed conclusions to `.polaris/explorations/` with the same script.
6. Leave no unresolved `STALE` entry.
7. Create the final subject checkpoint and recompute the subject diff hash.
8. When the final subject includes supported source changes, policy is enabled, and `.codegraph/` exists, invoke `{{skill:code-intelligence}}` once at the Documentation Sync boundary. Call `polaris_codegraph_explore` with stage `DOCUMENTATION_SYNC` and a query limited to changed source paths and documented symbols; automatic incremental sync is owned by the proxy, and there is no separate status/sync MCP tool. Read the freshness envelope first and finish every required source/Git fallback. Then create annotations and run `record_code_intelligence.py <task-id> --repo . --bundle <bundle-path> --annotations <annotations-path>` to project the immutable v3 record and reference it from the Knowledge Delta. Otherwise omit the Code Intelligence record and optional artifact reference.
9. Refresh the Working Set if a promoted exploration, documentation change, or confirmed Code Intelligence dependency alters the next stage's justified inputs.
10. Run `check_docs.py` with the final subject base/head. When live telemetry exists, append its result with `ADD_CHECK`, then use `SET_PHASE` to enter `COMPLETED` with no blocker. Return the Knowledge Delta path, final subject base/head, diff hash, changed documentation, promoted explorations, Code Intelligence refresh status, and check result.

Do not run workflow transitions or emit a Polaris checkpoint marker. The main `{{skill:engineering-task}}` combines the Knowledge Delta with the Implementation and final subject when it starts Review.

Do not edit Review, Validation, Result, event, or state artifacts directly.

Proxy evidence contract: the proxy attempts exactly one incremental `codegraph sync` before every proxy query, including when status reports zero pending changes, and never runs `codegraph index`. Zero pending status does not prove clean HEAD. CodeGraph is never a source of truth; `CURRENT` is only `NON_AUTHORITATIVE_CONTEXT`. `STALE` and `UNKNOWN`/`TREAT_AS_STALE` are `NAVIGATION_ONLY` and require the exact source/Git fallback before any conclusion is used. `NAVIGATION_ONLY` never substantiates an edit or conclusion, even after fallback; only completed current source/Git fallback evidence does, and index-wide uncertainty affects the entire graph response. Use no separate status/sync MCP tool and do not retry, poll, wait, or run another query after fallback is required. A raw `codegraph_explore` or `codegraph explore` result is unverified, out-of-band, and cannot back `CURRENT` Polaris evidence. Never run `codegraph init` or manage the Provider. Graph evidence never gates documentation checks or state changes.
