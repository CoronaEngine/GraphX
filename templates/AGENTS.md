# Repository engineering rules

- Enter the Polaris workflow only when the user explicitly invokes `$engineering-task`; ordinary engineering requests do not opt in.
- Invoke stage Skills only from an already active Polaris workflow at their legal graph nodes; do not use them as implicit entry points.
- Use the stable Polaris conversation checkpoints defined by `$engineering-task`; never pass a Human confirmation gate silently.
- Treat `.polaris/` JSON and the frozen Work Item revision as workflow authority.
- When the same content must serve mechanical validation and human reading, store only four-space-indented JSON and format it on demand; use Markdown only for independent prose, plans, rules, or instructions.
- Follow `.polaris/workflow.json`; use vendored scripts for every state transition.
- Do not edit `state.json`, `events.jsonl`, `VERIFIED`, or `CLOSED` directly.
- Keep unrelated user changes out of task checkpoint commits.
- Prefer a fresh same-project Implementer task from the registered Implementation handoff; keep live progress under each task's ignored `runtime/` subdirectory.
- Let only the main `$engineering-task` context apply workflow transitions; Implementer and Reviewer tasks only write their declared artifacts.
- For R1/R2 Review, stop implementation and use the registered handoff in a fresh Review task or isolated reviewer agent.
- Recover a task from repository state; do not require previous chat history.
