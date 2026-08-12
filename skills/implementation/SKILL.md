---
name: implementation
description: Implement the current frozen Polaris Work Item within its declared scope and plan. Use only in IMPLEMENTING, including fixes after Review rejection or Validation failure, while recording deviations, tests, subject commits, and reproducible evidence.
---

# Implementation

1. Confirm the current Work Item revision, rigor, plan, working set, and required pre-approval.
2. Change only the declared subject paths. Protect unrelated user changes.
3. Work in small build/test/fix loops inside this node.
4. Do not alter goal, scope, acceptance, or hard constraints. Create a new revision if any must change.
5. Record deviations from Plan and their reasons in the Implementation artifact.
6. Run the planned local checks and capture reproducible evidence.
7. Create a subject checkpoint commit containing code, tests, build configuration, and relevant project docs only.
8. Record `subject_base_commit`, `subject_head_commit`, and `subject_diff_hash`.
9. Transition with `FINISH_IMPLEMENTATION` and report `IMPLEMENTATION_FINISHED`.

Do not self-accept Review, write Validation PASS, or claim completion.
