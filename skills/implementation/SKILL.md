---
name: implementation
description: Internal Polaris worker stage for an explicitly started `$engineering-task` workflow. Invoke only in the dedicated Implementer task, or the declared same-session fallback, with a registered Implementation handoff while state is IMPLEMENTING; do not activate from ordinary implementation or fix requests.
---

# Implementation

1. Require the task ID and registered `implementations/rNNN/handoff-NNN.json`. Load only that handoff and its package as task context; read `state.json` only to verify registration. Do not read the main conversation or infer unstated requirements.
2. Confirm state is `IMPLEMENTING`, the handoff hash matches `state.json`, and `artifact_attempt`, revision, base commit, output path, and progress paths are current.
3. Generate one stable Implementer session ID for this conversation. Update live progress with `update_implementation_progress.py` when starting a step, completing a step, finishing a test run, hitting a blocker, and preparing a checkpoint.
4. Change only declared subject paths and protect unrelated user changes. Work in small build/test/fix loops.
5. Do not alter goal, scope, acceptance, or hard constraints. Return a blocker when any must change.
6. Record Plan deviations and reasons. After Review rejection, load the handoff's prior Review, answer every open Finding once in an immutable Review Response, and bind it to the new subject.
7. Run planned local checks and record reproducible evidence. Never report a made-up percentage; report completed, current, and remaining steps.
8. Create a subject checkpoint commit containing scoped code, tests, build configuration, and relevant project docs only.
9. Write the immutable Implementation JSON at the handoff's `output_path`. Bind `implementation_handoff_path` and `implementation_handoff_sha256`, plus subject commits, diff hash, session ID, deviations, and checks.
10. Set live progress to `CHECKPOINTING` with the Implementation artifact ready, then return the artifact path, session ID, subject base/head, diff hash, checks, deviations, Review Response path when present, and remaining Documentation Sync work.

Do not run `FINISH_IMPLEMENTATION`, Documentation Sync, Review, Validation, or any completion transition. Do not emit a Polaris checkpoint marker; the main `$engineering-task` validates the artifact, advances the graph, and continues this task for `$documentation-sync`.
