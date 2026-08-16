---
name: code-intelligence
description: Internal optional Polaris stage support for querying and refreshing a repository Code Intelligence Provider. Invoke only from an active `{{skill:engineering-task}}` workflow when Planning, Implementation, Documentation Sync, or Review can benefit from indexed code relationships; never activate from ordinary requests or make provider availability a workflow gate.
---

# Code Intelligence

Treat Code Intelligence as read-only, best-effort evidence. Source, Git, builds, tests, and frozen Polaris artifacts remain authority.

1. Load `.polaris/code-intelligence.json` when present; otherwise use the protocol default `auto_optional` policy. `disabled` skips all provider work.
2. Inspect the tools exposed by the current host and compare them with descriptors under the protocol root's `providers/code-intelligence/` directory. Select the first configured provider with at least one operation available. Never install, start, authenticate, or reconfigure a provider.
3. Use only the operation requested by the calling stage. Missing operations, tool errors, empty indexes, timeouts, and malformed responses are non-blocking. Record `UNAVAILABLE`, `FAILED`, `EMPTY`, or `SKIPPED`, then immediately continue with the stage's original repository search and source-reading path.
4. Bound every query to the frozen Work Item, Working Set, changed subject, or a dependency discovered from them. Confirm returned paths against the repository before using them. Provider results cannot expand frozen scope, authorize a change, satisfy acceptance, or determine a Review verdict.
5. Keep exact provider responses only below the task's ignored `runtime/code-intelligence/` directory. Finalize a compact immutable record with `record_code_intelligence.py`; store only purpose, operation, status, bounded symbol/path references, response hash, and refresh evidence.
6. For refresh planning, run `record_code_intelligence.py ... --plan-refresh` against the final subject commits. Use `refresh_files` for eligible added or modified files. Use `refresh_workspace` when eligible files were deleted or renamed. Skip refresh when no eligible code changed.
7. Report freshness only as `refresh_acknowledged` or `spot_checked`. Never claim that an external index is commit-exact.

Stage policy:

- Planning: prefer `context`, `dependencies`, `call_graph`, and `impact`; add a returned path to the Working Set only after repository confirmation and with its query ID as `discovered_from`.
- Implementation: prefer `context` and `impact` before editing. Refresh mid-implementation only when a later declared step needs relationships from newly changed code.
- Documentation Sync: attempt the final subject refresh after the documentation checkpoint and before completing live progress.
- Review: query the frozen subject independently with `review_context` and `impact`; do not reuse Implementer conclusions. Provider observations do not violate handoff isolation when they are derived only from the registered subject.
- Validation: do not invoke this Skill; use builds, tests, static checks, and Human Checks as the acceptance evidence.
