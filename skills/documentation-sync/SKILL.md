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
8. When the final subject includes supported source changes and the Provider is available, invoke `{{skill:code-intelligence}}` once at the Documentation Sync boundary with `sync-if-needed`. Use CodeGraph only with an existing `.codegraph/` directory: prefer `codegraph_explore`, with `codegraph explore` as the non-MCP fallback. A bounded `codegraph sync` is non-blocking. If a Provider operation ran, reference its immutable v2 record from the Knowledge Delta; otherwise omit the Code Intelligence record and its optional artifact reference. Never claim commit-exact freshness.
9. Refresh the Working Set if a promoted exploration, documentation change, or confirmed Code Intelligence dependency alters the next stage's justified inputs.
10. Run `check_docs.py` with the final subject base/head. When live telemetry exists, append its result with `ADD_CHECK`, then use `SET_PHASE` to enter `COMPLETED` with no blocker. Return the Knowledge Delta path, final subject base/head, diff hash, changed documentation, promoted explorations, Code Intelligence refresh status, and check result.

Do not run workflow transitions or emit a Polaris checkpoint marker. The main `{{skill:engineering-task}}` combines the Knowledge Delta with the Implementation and final subject when it starts Review.

Do not edit Review, Validation, Result, event, or state artifacts directly.

CodeGraph fallback contract: never run `codegraph init` or manage the Provider. Save and classify each response; when `RESPONSE_BANNER` is present, persist its successful explore response hash as `freshness.response_sha256`. For `PARTIAL_STALE`, if a named path is a current confined regular file, directly read it and record `READ_SOURCE` with its current SHA-256; if a safe path is missing/deleted, inspect the registered subject Git diff and record `INSPECT_GIT_DIFF` with null observed SHA-256 and bound base/head/diff evidence; for unsafe paths, record `NOT_VERIFIED` and use source search. For `INDEX_STALE` or `NOT_VERIFIED`, use source search and Git evidence, then stop graph calls for this stage. Each `SEARCH_SOURCE` fallback records `result_paths`: zero or at most 100 unique POSIX paths, each a current confined regular file with its current SHA-256; non-`SEARCH_SOURCE` fallbacks use empty `result_paths`. Graph evidence never gates documentation checks or state changes.
