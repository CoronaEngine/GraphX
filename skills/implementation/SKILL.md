---
name: implementation
description: Internal Polaris stage for an explicitly started `$engineering-task` workflow. Invoke only for the current frozen Work Item in IMPLEMENTING; do not activate from ordinary implementation or fix requests.
---

# Implementation

1. Confirm the current Work Item revision, rigor, plan, working set, and required pre-approval.
2. Change only the declared subject paths. Protect unrelated user changes.
3. Work in small build/test/fix loops inside this node.
4. Do not alter goal, scope, acceptance, or hard constraints. Create a new revision if any must change.
5. Record deviations from Plan and their reasons in the Implementation artifact.
6. After Review rejection, load the registered prior Review. Answer every open Finding exactly once in an immutable Review Response and bind it to the new subject.
7. Run the planned local checks and capture reproducible evidence.
8. Create a subject checkpoint commit containing code, tests, build configuration, and relevant project docs only.
9. Record `subject_base_commit`, `subject_head_commit`, `subject_diff_hash`, session ID, and the next immutable artifact attempt.
10. Transition with `FINISH_IMPLEMENTATION`, registering the Review Response when reworking, and report `IMPLEMENTATION_FINISHED`.

Emit `[POLARIS:IMPLEMENTATION_FINISHED]` only after the transition succeeds and state is reloaded. Use the nine fixed `$engineering-task` status fields, then include the subject base/head commits, diff hash, checks run, deviations, and Review Response path when present.

Do not self-accept Review, write Validation PASS, or claim completion.
