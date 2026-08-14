---
name: architecture-planning
description: Internal Polaris stage for an explicitly started `$engineering-task` workflow. Invoke only for a frozen task at QUALIFIED or returned PLANNED; do not activate from ordinary planning requests.
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
