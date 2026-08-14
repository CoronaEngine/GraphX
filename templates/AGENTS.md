# Repository engineering rules

- Enter the Polaris workflow only when the user explicitly invokes `$engineering-task`; ordinary engineering requests do not opt in.
- Invoke stage Skills only from an already active Polaris workflow at their legal graph nodes; do not use them as implicit entry points.
- Treat `.polaris/` JSON and the frozen Work Item revision as workflow authority.
- Follow `.polaris/workflow.json`; use vendored scripts for every state transition.
- Do not edit `state.json`, `events.jsonl`, `VERIFIED`, or `CLOSED` directly.
- Keep unrelated user changes out of task checkpoint commits.
- For R1/R2 Review, stop the implementer session and use the registered handoff in a fresh session or isolated reviewer agent.
- Recover a task from repository state; do not require previous chat history.
