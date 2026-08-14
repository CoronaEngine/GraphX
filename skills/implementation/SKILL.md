---
name: implementation
description: Internal Polaris worker stage for an explicitly started `$engineering-task` workflow. Invoke only in the dedicated Implementer task, or the declared same-session fallback, with a registered Implementation handoff while state is IMPLEMENTING; do not activate from ordinary implementation or fix requests.
---

# Implementation

1. Require the task ID and registered `implementations/rNNN/handoff-NNN.json`. Load only that handoff and its package as task context; read `state.json` only to verify registration. Do not read the main conversation or infer unstated requirements.
2. Confirm state is `IMPLEMENTING`, the handoff hash matches `state.json`, and `artifact_attempt`, revision, base commit, output path, and progress paths are current.
3. Generate one stable Implementer session ID for this conversation. Before changing code, use the initialized live snapshot's `DEFINE_STEPS` event to create a non-empty ordered `implementation_steps` list. Every step receives the next `STEP-NNN` ID and must reference one or more acceptance IDs from the frozen Work Item.
4. Execute steps linearly with `START_STEP`, then `COMPLETE_STEP`, `BLOCK_STEP`, or `RESUME_STEP`; use `SKIP_STEP` only with an explicit reason. Existing step identity, title, order, and acceptance bindings are immutable. Newly discovered work may only be added at the end with `APPEND_STEP`. Never edit `progress.json` directly.
5. Change only declared subject paths and protect unrelated user changes. Work in small build/test/fix loops.
6. Do not alter goal, scope, acceptance, or hard constraints. Return a blocker when any must change.
7. Record Plan deviations and reasons. After Review rejection, load the handoff's prior Review, answer every open Finding once in an immutable Review Response, and bind it to the new subject.
8. Run planned local checks and append reproducible evidence with `ADD_CHECK`. Never report a made-up percentage; derive completed, current, and remaining work from the ordered steps.
9. Complete or explicitly skip every step, then create a subject checkpoint commit containing scoped code, tests, build configuration, and relevant project docs only.
10. Write the immutable Implementation JSON at the handoff's `output_path`. Bind the handoff, subject, session, deviations, and checks, and copy the exact terminal `id`, `status`, and `result` projection into `step_results`.
11. Use `SET_PHASE` to enter `CHECKPOINTING` only after every step is `COMPLETED` or `SKIPPED`, then return the artifact path, session ID, subject base/head, diff hash, step results, checks, deviations, Review Response path when present, and remaining Documentation Sync work.

Do not run `FINISH_IMPLEMENTATION`, Documentation Sync, Review, Validation, or any completion transition. Do not emit a Polaris checkpoint marker; the main `$engineering-task` validates the artifact, advances the graph, and continues this task for `$documentation-sync`.
