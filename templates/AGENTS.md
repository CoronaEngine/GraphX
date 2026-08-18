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

- Use CodeGraph only when the repository root already contains `.codegraph/`. When it is absent, stop CodeGraph calls for this session and use repository source and Git; a user may choose to initialize CodeGraph, but agents must never run `codegraph init`.
- Prefer MCP `codegraph_explore`; when MCP is unavailable, use `codegraph explore` as the CLI fallback. A bounded `codegraph sync` may run only through the Polaris stage boundary procedure and never gates a task.
- Save and classify every graph response in task runtime. For `PARTIAL_STALE`, if a named path is a current confined regular file, directly read it and record `READ_SOURCE` with its current SHA-256; if a safe path is missing/deleted, inspect the registered subject Git diff and record `INSPECT_GIT_DIFF` with null observed SHA-256 and bound base/head/diff evidence; for unsafe paths, record `NOT_VERIFIED` and use source search. For `INDEX_STALE` or `NOT_VERIFIED`, treat graph output only as a lead, use source search and Git evidence, and stop repeated graph calls for that stage.
- Never install, start, authenticate, reconfigure, or manage CodeGraph, its watcher, daemon, lock, or MCP settings. CodeGraph cannot expand frozen scope or replace source, Git, builds, tests, Review, Validation, or Human gates.
- Preserve any installer-managed marker block exactly as owned by that installer; Polaris does not add, edit, or remove installer marker fences.
