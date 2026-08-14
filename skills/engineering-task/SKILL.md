---
name: engineering-task
description: Run the Polaris repository workflow only when the user explicitly invokes `$engineering-task`. Do not activate for ordinary engineering requests or infer opt-in from implementation, change, refactor, optimization, fix, review, or recovery intent.
---

# Engineering Task

Require explicit user invocation of `$engineering-task`. If the user did not explicitly invoke this Skill, do not enter the Polaris workflow. Treat repository JSON as authority and never infer state or completion from chat history.

## Stable conversation contract

At every pause or completed workflow checkpoint, emit exactly one status block whose first line is `[POLARIS:<MARKER>]`. Keep these fields in this order and write `None` instead of omitting an empty field:

1. `Task`: task ID or `Pending` before allocation.
2. `Revision`: `rNNN` or `Pending`.
3. `Rigor`: `R0`, `R1`, `R2`, or `Pending`.
4. `State`: repository state after the last successful transition.
5. `Outcome`: what this checkpoint established.
6. `Authority`: controlling JSON and essential context documents.
7. `Remaining`: unresolved questions, work, Findings, failed acceptance criteria, or `None`.
8. `Next`: next legal graph action.
9. `User action`: exact user decision/action required, or `None`.

Use only these markers: `POLARIS_STARTED`, `REQUIREMENTS_NEEDED`, `WORK_ITEM_PREVIEW`, `WORK_ITEM_QUALIFIED`, `PLAN_READY`, `IMPLEMENTATION_HANDOFF_READY`, `IMPLEMENTATION_SESSION_STARTED`, `IMPLEMENTATION_PROGRESS`, `IMPLEMENTATION_FINISHED`, `DOCS_SYNCED`, `REVIEW_HANDOFF_READY`, `REVIEW_SESSION_STARTED`, `REVIEW_ACCEPTED`, `REVIEW_REJECTED`, `VALIDATION_PASS`, `VALIDATION_FAIL`, `TASK_BLOCKED`, `TASK_CANCELLED`, and `TASK_CLOSED`.

Never report an anticipated state. Reload authority after every transition. A stage may append details after the nine fields but may not rename, reorder, or omit them. For bounded Human decisions, prefer `request_user_input` or equivalent structured choices. If the tool is unavailable, render identical text choices. Treat UI and text answers identically. Do not change host mode to obtain UI.

## Main-task ownership

1. Locate `AGENTS.md`, `.polaris/project.json`, `.polaris/project-index.json`, `.polaris/workflow.json`, and active task state.
2. Recover existing work with `recover_task.py <task-id> --repo . --json`; stop on validation, reference, or state conflicts.
3. Load only the recovery result, frozen Work Item, Working Set, and paths justified by it.
4. Invoke `$requirement-analysis` for a new request and `$architecture-planning` at `QUALIFIED` or returned `PLANNED`.
5. Use `transition_task.py` for every state transition. Never edit `state.json` directly.
6. Act as the user-facing controller: dispatch workers, validate artifacts, apply transitions, answer status queries, and surface exact user actions. On the automatic path, do not modify subject code, tests, build files, or project documentation.

## Independent Implementation

7. Before Implementation, require frozen `implementation_dispatch` authority with `mode=auto_new_task`, `fallback=same_session`, `same_local_project=true`, and `authorized=true`. The same `Confirm and execute` answer authorizes every Implementer task for the revision, including rework attempts up to the graph limit.
8. Run `START_IMPLEMENTATION` after required R2 pre-approval. Run `build_implementation_handoff.py`, register the exact returned path with `DISPATCH_IMPLEMENTATION`, then emit `IMPLEMENTATION_HANDOFF_READY`. Never assemble task-relative paths independently of `task_layout.py`.
9. When the host can list, create, wait for, and continue Codex tasks, resolve the current local project and dispatch a fresh task in that same local checkout. Never fork the main conversation and do not use a separate worktree by default. Use the exact title `Polaris Implement · <TASK> · <REVISION> · attempt <N>`.
10. Before creation, first reuse a valid Implementation artifact bound to the registered handoff; otherwise reuse one unique task with the exact title. Never create a duplicate for the same task, revision, and attempt. Multiple exact matches require the same-session fallback rather than guessing.
11. Give the Implementer only the task ID and registered handoff path. Use this exact prompt: `Use $implementation for <TASK>. Load only <HANDOFF> and its package as task context; read state.json only to verify the registered handoff. Work in the shared local checkout, define and execute linear implementation_steps through update_implementation_progress.py, write the immutable Implementation JSON at output_path with matching step_results, and return its path. Do not run task transitions, Review, Validation, or close the task.` Do not include main-chat history or implementation advice.
12. Initialize the ignored live snapshot with the updater's `INITIALIZE` event, then emit `IMPLEMENTATION_SESSION_STARTED` with the nine fixed fields plus `Implementation task`, `Handoff`, `Progress`, and `Dispatch mode`; set `User action` to `None` while work is proceeding.
13. While `IMPLEMENTING`, answer status requests by validating the registered handoff's `progress_json_path` and formatting its fields directly in the conversation. Emit `IMPLEMENTATION_PROGRESS` with the latest phase; current step ID/title; completed or skipped prefix; pending suffix; checks; blocker; timestamp; and task link. Derive those views from the single ordered `implementation_steps` list. Do not persist a duplicate Markdown status file, invent percentages, infer progress from elapsed time, or reconstruct the path from prose. A status query must not cancel or duplicate the worker.
14. Wait for the Implementer result. Require live progress phase `CHECKPOINTING`, every step terminal, the same Implementer session, and exact equality between the live step projection and immutable `step_results`. Then register the Implementation, run `FINISH_IMPLEMENTATION`, and reload state. Continue the same Implementer task with `$documentation-sync`; it writes Knowledge Delta and any documentation checkpoint without running transitions. Register that artifact, run `SYNC_DOCS`, reload state, and emit `DOCS_SYNCED`. Only then is the Implementer task finished.
15. If task management is unavailable or dispatch fails, use the registered handoff in this main task, invoke `$implementation` and `$documentation-sync` locally, and keep writing the same progress snapshots. Report `Dispatch mode: same_session_fallback` and that immediate status responses may be delayed; do not block solely because host automation is unavailable.
16. If an Implementer requests permission or hits a blocker, show the exact Implementer task and `User action`. The Implementer never advances the graph, reviews itself, validates acceptance, or closes the task.

## Independent Review

17. At `DOCS_SYNCED`, build and register an immutable Reviewer handoff, run `START_REVIEW`, and emit `REVIEW_HANDOFF_READY`. R0 performs an explicit isolated same-session pass. For R1/R2, the main task only dispatches Reviewers, waits, reloads authority, and applies transitions. Never fork the implementation conversation.
18. Require frozen `review_dispatch` authority with `mode=auto_new_task`, `fallback=manual_handoff`, `same_local_project=true`, and `authorized=true`. Do not create Reviewer tasks without it.
19. Use the exact title `Polaris Review · <TASK> · <REVISION> · attempt <N> · reviewer <SLOT>`. Before creating it, first accept a valid deterministic Review artifact, then reuse one unique exact-title task. Never create a duplicate; multiple exact matches use manual fallback.
20. Give the Reviewer only the task ID, Reviewer slot, registered handoff path. Use this exact prompt: `Use $adversarial-review for <TASK>, Reviewer slot <SLOT>. Load only <HANDOFF> and its package. Write the immutable Review JSON and return its verdict and path. Do not modify implementation or run task transitions.` Do not include implementation explanations, chat history, proposed findings, or expected verdicts.
21. After dispatch, emit `REVIEW_SESSION_STARTED` with the nine fields plus `Review task`, `Reviewer slot`, `Handoff`, and `Dispatch mode`; set `User action` to `None` while the task is running. If task creation, lookup, or waiting fails, keep state `REVIEWING`, emit `REVIEW_HANDOFF_READY`, and provide the exact manual new-task prompt; do not enter `BLOCKED` solely because host automation is unavailable.
22. Dispatch required Reviewers sequentially. On the first `REJECT`, register the artifact and run `REJECT_REVIEW`; on rework, generate a new handoff and a fresh Implementer attempt. When all required Reviewers `ACCEPT`, register slot 1 as `review` and slot 2 as `review_2` when required, then run `ACCEPT_REVIEW`. Reviewer session IDs must be distinct from each other and the Implementer.
23. Never write a Review verdict in the main or Implementer task. Only Reviewer tasks write `ACCEPT` or `REJECT`.

## Completion and gates

24. Invoke `$validation` only at `VALIDATING`. Stop at Human or mechanical gates and record a blocker instead of guessing.
25. Report `TASK_CLOSED` only after `transition_task.py` actually reaches `CLOSED`; otherwise report the current checkpoint.

Give each conversation an opaque stable session ID. If the host exposes none, generate one once and reuse it only within that conversation.
