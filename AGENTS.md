# Polaris repository rules

- Treat plan.md as the clean-slate product and implementation authority.
- Optimize for one outcome: stable, correct, recoverable execution of one long software-engineering task.
- Do not preserve compatibility with pre-refactor Polaris tasks, protocols, commands, Skills, schemas, layouts, or migrations.
- The model may propose semantic actions, but only the Polaris Controller may execute tools, mutate mechanical state, or write DONE.
- Serialize mutating actions and establish a durable Action Boundary before the next model call. Parallelism is allowed only for bounded read-only work.
- Rebuild every model-visible Context View from authoritative state. Do not treat append-only chat history as the runtime context model.
- Bind mutable repository observations to provenance and version identity. Never recover stale content as if it were current.
- Persist dirty, poorly recoverable semantic information before eviction, compaction, pause, or shutdown.
- Add or update tests for every state transition, recovery branch, action gate, context-routing rule, validator, and completion gate.
- Dependencies are allowed when they directly serve model access, reliability, or testing. Do not add frameworks, services, databases, schedulers, dashboards, multi-host abstractions, or plugin systems without benchmark evidence and an approved plan.md change.
- Prefer one four-space-indented JSON authority when content must be mechanically validated and human-readable. Use Markdown for independent natural-language design and explanation.
- Keep files and modules small, single-purpose, and independently testable. Create directories only when their milestone begins.
