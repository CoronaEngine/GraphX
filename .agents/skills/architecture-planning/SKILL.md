---
name: architecture-planning
description: Build a bounded working set and implementation plan for a frozen Polaris Work Item. Use when a task is QUALIFIED or returns to PLANNED because implementation strategy, risks, affected documentation, or acceptance-to-validation mapping must be established.
---

# Architecture Planning

1. Read the frozen Work Item and project rules.
2. Refresh `WORKING_SET.md` with `build_working_set.py`. Record every entry as path, reason, and discovery source; add explicit entries only for concrete dependencies.
3. Investigate only paths justified by the task or a discovered dependency.
4. Write `PLAN.md` as a delta from `base_commit`, including alternatives, risks, affected invariants, and expected documentation changes.
5. Map every acceptance criterion to a planned validation command or Human check.
6. Record any Human-owned decision as a `CD-*.json`; block if it remains unresolved.
7. Include task-local explorations and only project explorations matching an affected module or hypothesis.
8. Run task validation and transition with `PLAN` only when the plan and working set are complete.

Do not modify the frozen Work Item or start implementation from this stage.
