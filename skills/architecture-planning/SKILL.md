---
name: architecture-planning
description: Internal Polaris stage for an explicitly started `{{skill:engineering-task}}` workflow. Invoke only for a frozen task at QUALIFIED or returned PLANNED; do not activate from ordinary planning requests.
---

# Architecture Planning

1. Read the frozen Work Item and project rules.
2. Refresh `working-set.json` with `build_working_set.py`. Record every entry as section, path, reason, and discovery source; add explicit entries only for concrete dependencies. Do not parse or create a duplicate Markdown Working Set.
3. Investigate only paths justified by the task or a discovered dependency.
4. Write `PLAN.md` as a delta from `base_commit`, including alternatives, risks, affected invariants, and expected documentation changes. Keep rationale in Markdown; do not use it as decision authority.
5. Map every acceptance criterion to a planned validation command or Human check.
6. Write `plan-decisions.json` after the Plan is stable. Bind its `plan.path` and `plan.sha256` to `PLAN.md`. Use an empty `decisions` array when no Human-owned Plan decision is required.
7. For each Human-owned Plan decision, record one concrete question with two or three mutually exclusive options. Put the recommended option first, suffix its label with `(Recommended)`, and give every option one concise consequence. Ask at most three questions per round through `request_user_input` or an equivalent structured-choice tool; if unavailable, render identical text choices. Accept a precise free-form answer, treat UI and text answers identically, and never infer consent from silence.
8. Before asking, leave each decision `PENDING`, run `BLOCK` with blocker type `plan_decision`, owner `human`, and the pending `PD-*` IDs in the reason, then reload state and emit `[POLARIS:PLAN_DECISIONS_NEEDED]` with the nine fixed status fields plus the exact questions. Set `Authority` to `PLAN.md` and `plan-decisions.json`, `Remaining` to the pending IDs, `Next` to `RESOLVE_BLOCK`, and `User action` to the exact requested selections.
9. For each Human answer, call `record_plan_decision.py` with the task ID, `PD-*` ID, selected option ID, and the actual Human identity exposed by the host; use `repository-owner` only when the host exposes no identity. The script creates one append-only project authority `.polaris/decisions/CD-*.json` bound to the task, `PD-*`, current Work Item revision, Plan hash, and selected option, then updates the register. For a precise free-form answer, first represent that exact answer as a concrete option with a new deterministic option ID and consequence, while keeping the total at two or three, then record it normally. If the answer changes the frozen contract boundary, create a new Work Item revision instead of resolving the Plan decision. Run `RESOLVE_BLOCK` only after every pending entry is resolved.
10. Include task-local explorations and only project explorations matching an affected module or hypothesis.
11. Run task validation and transition with `PLAN` only when the Plan, Plan decision register, and Working Set are complete. Register `plan=PLAN.md`, `plan_decisions=plan-decisions.json`, and `working_set=working-set.json`; the gate must reject pending decisions or stale hashes.

After the transition succeeds, reload state and emit `[POLARIS:PLAN_READY]` with the nine fixed `{{skill:engineering-task}}` status fields. Put the Plan, Plan decision register, Working Set, acceptance-to-validation mapping, and resolved Human decisions in the checkpoint details. Set unresolved decisions to `None`.

Do not modify the frozen Work Item or start implementation from this stage.
