---
name: engineering-task
description: Govern non-trivial software engineering work through the Polaris repository workflow. Use when a user asks Codex to implement, change, refactor, optimize, or fix a project and the work must be qualified, planned, reviewed, validated, documented, or resumed from .polaris state.
---

# Engineering Task

Treat the repository as authority. Never infer completion from chat history.

1. Locate `AGENTS.md`, `.polaris/project.json`, `.polaris/workflow.json`, and the active task state.
2. Run `tools/polaris/scripts/validate_project.py` and `validate_task.py` before resuming an existing task.
3. Load only the frozen Work Item, `WORKING_SET.md`, referenced decisions, affected module docs, entry points, and tests.
4. For a new request, invoke `$requirement-analysis` before changing code.
5. Follow `.polaris/workflow.json`. Invoke the stage Skill matching the current node.
6. Use `transition_task.py` for every state transition. Never edit `state.json` directly.
7. Stop at Human, Reviewer, or mechanical gates. Record a blocker instead of guessing.
8. Never declare the task complete. Report `IMPLEMENTATION_FINISHED`, Review verdict, or Validation verdict; only the transition script may reach `CLOSED`.

Use `$architecture-planning`, `$implementation`, `$documentation-sync`, `$adversarial-review`, and `$validation` only at their legal graph nodes.
