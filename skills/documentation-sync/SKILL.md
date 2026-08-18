---
name: documentation-sync
description: Internal Polaris worker stage for an explicitly started `{{skill:engineering-task}}` workflow. Invoke only by continuing the same dedicated Implementer task in IMPLEMENTED to reconcile documentation; do not activate from ordinary documentation requests.
---

# Documentation Sync

1. Continue in the same Implementer conversation and reload the registered Implementation artifact and live progress. Use the progress updater's `SET_PHASE` event to enter `DOCUMENTING`; do not alter the terminal Implementation steps.
2. Compare changed subject paths with project documentation and the frozen Work Item.
3. Write a Knowledge Delta JSON with an entry for every affected knowledge area: `ADD`, `UPDATE`, `STALE`, or `NO_CHANGE`.
4. Update confirmed project documentation. Do not promote unverified inference to authority.
5. Record failed attempts with `record_exploration.py`. Keep task-only conclusions in the task; promote reusable, evidence-backed conclusions to `.polaris/explorations/` with the same script.
6. Leave no unresolved `STALE` entry.
7. Create the final subject checkpoint and recompute the subject diff hash.
8. When the final subject includes supported source changes, invoke `{{skill:code-intelligence}}` once at the Documentation Sync boundary with `sync-if-needed`; otherwise record `SKIPPED`. Use CodeGraph only with an existing `.codegraph/` directory: prefer `codegraph_explore`, with `codegraph explore` as the non-MCP fallback. A bounded `codegraph sync` is non-blocking. Record `UNAVAILABLE` or `FAILED` and continue when CodeGraph cannot run. Reference the immutable v2 Documentation Sync Code Intelligence record from the Knowledge Delta; never claim commit-exact freshness.
9. Refresh the Working Set if a promoted exploration, documentation change, or confirmed Code Intelligence dependency alters the next stage's justified inputs.
10. Run `check_docs.py` with the final subject base/head, append its result with `ADD_CHECK`, then use `SET_PHASE` to enter `COMPLETED` with no blocker. Return the Knowledge Delta path, final subject base/head, diff hash, changed documentation, promoted explorations, Code Intelligence refresh status, and check result.

Do not run `SYNC_DOCS` or emit a Polaris checkpoint marker. The main `{{skill:engineering-task}}` validates and registers the artifact, advances the graph, reloads state, and emits `[POLARIS:DOCS_SYNCED]`.

Do not edit Review, Validation, Result, event, or state artifacts directly.

CodeGraph fallback contract: never run `codegraph init` or manage the Provider. Save and classify each response. For `PARTIAL_STALE`, directly read each listed file and record its SHA-256. For `INDEX_STALE` or `NOT_VERIFIED`, use source search and Git evidence, then stop graph calls for this stage. Graph evidence never gates documentation checks or state changes.
