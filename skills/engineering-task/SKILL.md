---
name: engineering-task
description: Run the Polaris repository workflow only when the user explicitly invokes `$engineering-task`. Do not activate for ordinary engineering requests or infer opt-in from implementation, change, refactor, optimization, fix, review, or recovery intent.
---

# Engineering Task

Require explicit user invocation of `$engineering-task`. If the user did not explicitly invoke this Skill, do not enter the Polaris workflow.

Treat the repository as authority. Never infer state or completion from chat history.

1. Locate `AGENTS.md`, `.polaris/project.json`, `.polaris/workflow.json`, and the active task state.
2. For an existing task, run `tools/polaris/scripts/recover_task.py <task-id> --repo . --json`. Stop on validation, reference, or state conflicts.
3. Load only the recovery result, frozen Work Item, `WORKING_SET.md`, and paths justified by that set.
4. For a new request, invoke `$requirement-analysis` before changing code.
5. Follow `.polaris/workflow.json`. Invoke the stage Skill matching the current node.
6. Use `transition_task.py` for every state transition. Never edit `state.json` directly.
7. At `DOCS_SYNCED`, build and register an immutable reviewer handoff. For R1/R2, stop the implementer session after `START_REVIEW`; continue only in a fresh session or an isolated reviewer agent started without implementation chat history.
8. Do not invoke `$adversarial-review` from an R1/R2 implementer context. Pass only the registered handoff path to the Reviewer context.
9. Stop at Human, Reviewer, or mechanical gates. Record a blocker instead of guessing.
10. Never declare the task complete. Report `IMPLEMENTATION_FINISHED`, Review verdict, or Validation verdict; only the transition script may reach `CLOSED`.

Use `$architecture-planning`, `$implementation`, `$documentation-sync`, `$adversarial-review`, and `$validation` only at their legal graph nodes. Give each conversation an opaque stable session ID; if the host exposes none, generate one once and reuse it only within that conversation.
