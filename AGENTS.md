# Polaris repository rules

- Treat `plan.md` as the current v0.1 product and implementation authority.
- Keep the runtime dependency-free beyond the Python standard library.
- When content must be both mechanically validated and human-readable, prefer one four-space-indented JSON representation and format it on demand. Use Markdown only when it carries independent natural-language content that JSON would represent poorly.
- Add or update tests for every workflow gate, state transition, and validator rule.
- Do not add a CLI, daemon, scheduler, database, Dashboard, Task DAG, or custom Agent Runtime in v0.1.
- Do not let an Agent write `VERIFIED` or `CLOSED` directly; route state changes through `transition_task.py`.
