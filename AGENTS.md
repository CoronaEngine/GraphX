# Polaris repository rules

- Treat `plan.md` as the current v0.1 product and implementation authority.
- Keep the runtime dependency-free beyond the Python standard library.
- When content must be both mechanically validated and human-readable, prefer one four-space-indented JSON representation and format it on demand. Use Markdown only when it carries independent natural-language content that JSON would represent poorly.
- Add or update tests for every workflow gate, state transition, and validator rule.
- Keep the user-facing `polaris` CLI a standard-library-only thin dispatcher over the existing scripts. Do not move protocol logic into it or add a daemon, scheduler, database, Dashboard, Task DAG, or custom Agent Runtime in v0.1.
- Do not let an Agent write `VERIFIED` or `CLOSED` directly; route state changes through `transition_task.py`.
