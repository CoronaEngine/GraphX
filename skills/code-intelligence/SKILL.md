---
name: code-intelligence
description: Internal optional Polaris stage support for bounded CodeGraph relationship queries. Invoke only from an active `{{skill:engineering-task}}` workflow when Planning, Implementation, Documentation Sync, or Review can benefit from indexed code relationships; never activate from ordinary requests or make provider availability a workflow gate.
---

# Code Intelligence

Treat Code Intelligence as read-only, best-effort evidence. Source, Git, builds, tests, and frozen Polaris artifacts remain authority.

1. Load `.polaris/code-intelligence.json` and project rules. If the policy disables Code Intelligence, record `UNAVAILABLE` and use the stage's source path. Use CodeGraph only when the repository root has an existing `.codegraph/` directory. When it is absent, record `UNAVAILABLE`, stop CodeGraph calls for this project for the session, and tell the user they may choose to initialize it; never run `codegraph init`.
2. At the calling stage's declared boundary, run `code_intelligence_runtime.py status` or `sync-if-needed`. The latter may run one bounded `codegraph sync` only when status reports pending changes; it never loops, waits for a watcher, or treats a successful command as a gate.
3. For an allowed frozen-scope relationship query, use only `codegraph_explore` when MCP exposes it. If MCP is unavailable and the executable is available, use `codegraph explore` as the non-MCP fallback. Do not select retired narrow operations. Bound the query to the Work Item, Working Set, registered subject, or a confirmed dependency; graph output cannot expand frozen scope, authorize change, satisfy acceptance, or determine a Review verdict.
4. Save each raw explore response only below the task's ignored `runtime/code-intelligence/` directory, then run `code_intelligence_runtime.py classify-response` for it. When `RESPONSE_BANNER` is a freshness basis, persist that successful explore response hash as `freshness.response_sha256`; final records contain the response hash and finite summary, never the response itself.
5. On `PARTIAL_STALE`, process every named path by its current safe state. If it is a current confined regular file, directly read it and record `READ_SOURCE` with its current SHA-256. If a safe path is missing/deleted, inspect the registered subject Git diff and record `INSPECT_GIT_DIFF` with null observed SHA-256 and bound base/head/diff evidence. For unsafe paths, record `NOT_VERIFIED` and use source search. The remaining graph response may still be navigation evidence, but never a conclusion about a stale path.
6. On `INDEX_STALE` or `NOT_VERIFIED`, use repository source search and Git evidence, record the `SEARCH_SOURCE` fallback, and stop repeated graph calls for that stage. Every `SEARCH_SOURCE` fallback records `result_paths`: zero or at most 100 unique POSIX paths, each a current confined regular file with its current SHA-256; non-`SEARCH_SOURCE` fallbacks use empty `result_paths`. On malformed, missing, or unavailable Provider output, continue the same source fallback without blocking the stage.
7. Never initialize, install, start, authenticate, or reconfigure CodeGraph. Do not manage its watcher, daemon, lock, or host MCP settings.
8. Finalize an immutable v2 Code Intelligence record with the stage's actual freshness, stale points, and source fallbacks. Code Intelligence is never a workflow gate.

Stage policy:

- Planning: at the Planning boundary, request only frozen-task relationship discovery needed to justify Working Set entries; confirm every returned path in repository source and record its query ID as `discovered_from`.
- Implementation: before editing, request only handoff-scoped edit relationships. Query again mid-stage only when a later declared implementation step depends on relationships changed by the current subject.
- Documentation Sync: run `sync-if-needed` once only when the final subject changed supported source files; otherwise record `SKIPPED`.
- Review: independently request only registered-subject impact relationships. Do not reuse Implementer query conclusions.
- Validation: do not invoke this Skill; use builds, tests, static checks, and Human Checks as the acceptance evidence.
