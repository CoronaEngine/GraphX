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

Use only these markers: `POLARIS_STARTED`, `REQUIREMENTS_NEEDED`, `WORK_ITEM_PREVIEW`, `WORK_ITEM_QUALIFIED`, `PLAN_READY`, `IMPLEMENTATION_FINISHED`, `DOCS_SYNCED`, `REVIEW_HANDOFF_READY`, `REVIEW_SESSION_STARTED`, `REVIEW_ACCEPTED`, `REVIEW_REJECTED`, `VALIDATION_PASS`, `VALIDATION_FAIL`, `TASK_BLOCKED`, `TASK_CANCELLED`, and `TASK_CLOSED`.

Never report an anticipated state. Read authority again after each transition and report the state only when the script succeeds. Link the readable artifact when one exists. A stage may add checkpoint-specific details after the nine fixed fields, but may not rename, reorder, or omit them.

For every bounded Human decision, prefer the host's structured choice UI when a user-input tool such as `request_user_input` is callable. Use one to three short questions, each with two or three mutually exclusive options; put the recommended option first and explain each impact. If the tool is unavailable, render the same questions and options as text. Never switch host modes merely to obtain the UI, and never block because the UI is unavailable. Treat UI and text answers identically when recording Authority.

1. Locate `AGENTS.md`, `.polaris/project.json`, `.polaris/workflow.json`, and the active task state.
2. For an existing task, run `tools/polaris/scripts/recover_task.py <task-id> --repo . --json`. Stop on validation, reference, or state conflicts.
3. Load only the recovery result, frozen Work Item, `WORKING_SET.md`, and paths justified by that set.
4. For a new request, invoke `$requirement-analysis` before changing code.
5. Follow `.polaris/workflow.json`. Invoke the stage Skill matching the current node.
6. Use `transition_task.py` for every state transition. Never edit `state.json` directly.
7. At `DOCS_SYNCED`, build and register an immutable reviewer handoff, run `START_REVIEW`, and report `REVIEW_HANDOFF_READY`. R0 performs an explicit isolated same-session pass. For R1/R2, stop all implementation and Review work in this context; it may only dispatch Reviewer tasks, wait, reload repository authority, and apply transitions from their immutable Review artifacts.
8. Require the frozen Work Item to contain `review_dispatch.mode=auto_new_task`, `fallback=manual_handoff`, `same_local_project=true`, and `authorized=true`. This records the user's `Confirm and execute` answer as explicit authorization to create every Reviewer task required for the confirmed revision, including follow-up attempts up to the graph limit. Do not create Reviewer tasks without that authority.
9. When the host can list, create, and wait for Codex tasks, resolve the current local project and dispatch a fresh task in that same local checkout. Never fork the implementation conversation and do not use a separate worktree by default. Use the exact title `Polaris Review · <TASK> · <REVISION> · attempt <N> · reviewer <SLOT>`.
10. Before creating a Reviewer task, first accept a valid deterministic Review artifact already produced for that slot; otherwise reuse one unique existing task with the exact title. Never create a duplicate for the same task, revision, attempt, and Reviewer slot. If multiple exact matches exist, use the manual fallback instead of guessing.
11. Give the Reviewer only the task ID, Reviewer slot, registered handoff path, and the instruction to invoke `$adversarial-review` from repository authority. Use this exact prompt: `Use $adversarial-review for <TASK>, Reviewer slot <SLOT>. Load only <HANDOFF> and its package. Write the immutable Review JSON and return its verdict and path. Do not modify implementation or run task transitions.` Do not include implementation explanations, summaries, chat history, proposed findings, or expected verdicts. After dispatch, emit `REVIEW_SESSION_STARTED` with the nine fixed fields plus `Review task`, `Reviewer slot`, `Handoff`, and `Dispatch mode`; set `User action` to `None` while the task is running.
12. Wait for each Reviewer task to finish, then reload and validate its immutable Review JSON before doing anything else. If it needs user attention, report the exact task and required action without performing Review here. If task creation, lookup, or waiting is unavailable or fails, keep state `REVIEWING`, report `REVIEW_HANDOFF_READY`, and provide the exact manual new-task prompt; do not enter `BLOCKED` solely because host automation is unavailable.
13. Dispatch required Reviewers sequentially. Stop the round on the first `REJECT`, register that artifact as `review`, and run `REJECT_REVIEW`. When all required Reviewers `ACCEPT`, register slot 1 as `review` and slot 2 as `review_2` when required, then run `ACCEPT_REVIEW`. Reviewer session IDs must be distinct. After either transition, reload state and emit `REVIEW_ACCEPTED` or `REVIEW_REJECTED`; on rework, generate a new handoff and new deterministic Reviewer task title.
14. Do not invoke `$adversarial-review` from an R1/R2 implementer context and never write a Review verdict here. Only Reviewer contexts write `ACCEPT` or `REJECT`; this orchestrator only validates, registers, and transitions their artifacts.
15. Stop at Human or mechanical gates. Record a blocker instead of guessing.
16. When a gate cannot proceed, record the blocker when the graph permits it and report `TASK_BLOCKED`; do not silently stop or guess.
17. Never declare the task complete from prose or stage output. Report `TASK_CLOSED` only after `transition_task.py` has successfully reached `CLOSED`; otherwise report the current checkpoint marker.

Use `$architecture-planning`, `$implementation`, `$documentation-sync`, `$adversarial-review`, and `$validation` only at their legal graph nodes. Give each conversation an opaque stable session ID; if the host exposes none, generate one once and reuse it only within that conversation.
