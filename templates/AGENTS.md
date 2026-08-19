# Repository engineering rules

- Enter the Polaris workflow only when the user explicitly invokes its rendered entry Skill using the active host adapter; ordinary engineering requests do not opt in.
- Invoke stage Skills only from an already active Polaris workflow at their legal graph nodes; do not use them as implicit entry points.
- Use the stable Polaris conversation checkpoints defined by the host's `engineering-task` Skill; never pass a Human confirmation gate silently.
- Treat `.polaris/` JSON and the frozen Work Item revision as workflow authority.
- When the same content must serve mechanical validation and human reading, store only four-space-indented JSON and format it on demand; use Markdown only for independent prose, plans, rules, or instructions.
- Follow `.polaris/workflow.json`; use vendored scripts for every state transition.
- Do not edit `state.json`, `events.jsonl`, `VERIFIED`, or `CLOSED` directly.
- Keep unrelated user changes out of task checkpoint commits.
- Prefer a fresh same-project Implementer task from the registered Implementation handoff; keep live progress under each task's ignored `runtime/` subdirectory.
- Let only the main `engineering-task` context apply workflow transitions; Implementer and Reviewer workers only write their declared artifacts.
- For R1/R2 Review, stop implementation and use the registered handoff in a fresh Review task or isolated reviewer agent.
- Recover a task from repository state; do not require previous chat history.

## Optional CodeGraph rules

- Use CodeGraph only when project policy permits it and the repository root already contains `.codegraph/`. Otherwise skip the proxy, use source/Git, and omit the Code Intelligence record; agents never run `codegraph init`.
- For Polaris evidence call only `polaris_codegraph_explore` and read its freshness envelope before graph content. The proxy automatically runs at most one incremental `codegraph sync` when pending changes exist and never runs `codegraph index`. When status cannot be verified but the project has a safe repository identity, the proxy still calls `polaris_codegraph_explore` and returns `UNKNOWN`/`TREAT_AS_STALE`; graph content remains navigation-only and any conclusion requires the exact source/Git fallback. `CURRENT` is `NON_AUTHORITATIVE_CONTEXT`; `STALE` and `UNKNOWN`/`TREAT_AS_STALE` are `NAVIGATION_ONLY` and require the exact source/Git fallback before any conclusion is used. `NAVIGATION_ONLY` never substantiates an edit or conclusion, even after fallback; only completed current source/Git fallback evidence does, and index-wide uncertainty affects the entire graph response. Use no separate status/sync MCP tool and do not retry, poll, wait, or run another query after fallback is required. `UNAVAILABLE` means no graph.
- Complete fallbacks exactly: a safe current regular file uses `READ_SOURCE` with current SHA-256; a safe missing/deleted path uses `INSPECT_GIT_DIFF` with null observed SHA-256 and bound base/head/diff hashes; unsafe or index-wide stale/unknown results use `SEARCH_SOURCE` with finite confined POSIX result paths and current hashes.
- A raw `codegraph_explore` or `codegraph explore` result is out-of-band and cannot back `CURRENT` Polaris evidence. If the proxy ran, write annotations and run `record_code_intelligence.py <task-id> --repo . --bundle <bundle-path> --annotations <annotations-path>` to project v3; do not hand-author a record.
- Never install, initialize, start, authenticate, configure, reconfigure, or manage CodeGraph, its watcher, daemon, lock, raw MCP registration, or index. CodeGraph cannot expand frozen scope or replace source, Git, builds, tests, Review, Validation, or Human gates.
- Preserve any installer-managed marker block exactly as owned by that installer; Polaris does not add, edit, or remove installer marker fences.
