---
name: engineering-task
description: Run the Polaris repository workflow only when the user explicitly invokes `$engineering-task`. Do not activate for ordinary engineering requests or infer opt-in from implementation, change, refactor, optimization, fix, review, or recovery intent.
---

# Engineering Task

Require explicit user invocation of `$engineering-task`. If the user did not explicitly invoke this Skill, do not enter the Polaris workflow.

Treat the repository as authority. Never infer state or completion from chat history.

## Stable conversation contract

At every pause or completed workflow checkpoint, emit exactly one status block whose first line is `[POLARIS:<MARKER>]`. Keep these fields in this order and write `None` instead of omitting an empty field:

1. `Task`: task ID or `Pending` before allocation.
2. `Revision`: `rNNN` or `Pending`.
3. `Rigor`: `R0`, `R1`, `R2`, or `Pending`.
4. `State`: the repository state after the last successful transition.
5. `Outcome`: what this checkpoint established.
6. `Authority`: paths to the controlling JSON and readable projections.
7. `Remaining`: unresolved questions, Findings, failed acceptance criteria, or `None`.
8. `Next`: the next legal graph action.
9. `User action`: the exact decision/action required from the user, or `None`.

Use only these markers: `POLARIS_STARTED`, `REQUIREMENTS_NEEDED`, `WORK_ITEM_PREVIEW`, `WORK_ITEM_QUALIFIED`, `PLAN_READY`, `IMPLEMENTATION_FINISHED`, `DOCS_SYNCED`, `REVIEW_HANDOFF_READY`, `REVIEW_ACCEPTED`, `REVIEW_REJECTED`, `VALIDATION_PASS`, `VALIDATION_FAIL`, `TASK_BLOCKED`, `TASK_CANCELLED`, and `TASK_CLOSED`.

Never report an anticipated state. Read authority again after each transition and report the state only when the script succeeds. Link the readable artifact when one exists. A stage may add checkpoint-specific details after the nine fixed fields, but may not rename, reorder, or omit them.

For every bounded Human decision, prefer the host's structured choice UI when a user-input tool such as `request_user_input` is callable. Use one to three short questions, each with two or three mutually exclusive options; put the recommended option first and explain each impact. If the tool is unavailable, render the same questions and options as text. Never switch host modes merely to obtain the UI, and never block because the UI is unavailable. Treat UI and text answers identically when recording Authority.

1. Locate `AGENTS.md`, `.polaris/project.json`, `.polaris/workflow.json`, and the active task state.
2. For an existing task, run `tools/polaris/scripts/recover_task.py <task-id> --repo . --json`. Stop on validation, reference, or state conflicts.
3. Load only the recovery result, frozen Work Item, `WORKING_SET.md`, and paths justified by that set.
4. For a new request, invoke `$requirement-analysis` before changing code.
5. Follow `.polaris/workflow.json`. Invoke the stage Skill matching the current node.
6. Use `transition_task.py` for every state transition. Never edit `state.json` directly.
7. At `DOCS_SYNCED`, build and register an immutable reviewer handoff, then report `REVIEW_HANDOFF_READY`. For R1/R2, stop the implementer session after `START_REVIEW`; continue only in a fresh session or an isolated reviewer agent started without implementation chat history.
8. Do not invoke `$adversarial-review` from an R1/R2 implementer context. Pass only the registered handoff path to the Reviewer context.
9. Stop at Human, Reviewer, or mechanical gates. Record a blocker instead of guessing.
10. When a gate cannot proceed, record the blocker when the graph permits it and report `TASK_BLOCKED`; do not silently stop or guess.
11. Never declare the task complete from prose or stage output. Report `TASK_CLOSED` only after `transition_task.py` has successfully reached `CLOSED`; otherwise report the current checkpoint marker.

Use `$architecture-planning`, `$implementation`, `$documentation-sync`, `$adversarial-review`, and `$validation` only at their legal graph nodes. Give each conversation an opaque stable session ID; if the host exposes none, generate one once and reuse it only within that conversation.
