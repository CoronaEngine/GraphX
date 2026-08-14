---
name: requirement-analysis
description: Internal Polaris stage for an explicitly started `$engineering-task` workflow. Invoke only to convert its request into a frozen Work Item; do not activate from ordinary user requirements.
---

# Requirement Analysis

Inspect the repository before asking questions. Ask only about unknowns that cannot be inferred and materially affect the solution.

## Stable qualification interaction

If material unknowns remain, keep the task in `DRAFT` and emit `REQUIREMENTS_NEEDED` using the `$engineering-task` status fields. After those fields, ask one to three focused questions per round. For each question, state the recommended default and the consequence of choosing it. Record every unanswered item in `known_unknowns`; do not modify production code or run `QUALIFY` while any remain.

When the draft is complete, always emit `WORK_ITEM_PREVIEW` before freezing it, even when the original request appeared complete. After the fixed status fields, show:

- observable goal and motivation;
- in-scope and out-of-scope work;
- hard constraints, affected modules, rigor, and true risk flags;
- every acceptance ID with its statement and evidence method;
- Human-owned decisions and approval gates;
- remaining unknowns, which must be `None`.

Ask the user to explicitly confirm this preview. Do not infer confirmation from silence or from the original request. Only after confirmation may you write the final draft, validate it, and run `QUALIFY` or `NEW_REVISION`. Then reload state and emit `WORK_ITEM_QUALIFIED` with the frozen JSON and Markdown projection paths. Any later substantive change to goal, scope, constraints, or acceptance creates a new immutable revision; never silently overwrite the qualified revision.

1. Define an observable goal and motivation.
2. Separate in-scope and out-of-scope work.
3. Record hard constraints and affected modules.
4. Give every acceptance criterion a stable `AC-NN` ID and reproducible evidence method.
5. Set every risk flag explicitly. Any true risk flag requires at least R2.
6. Assign Human and Agent decision owners. Do not decide Human-owned boundaries.
7. Bind `base_commit` to a full Git SHA.
8. Write the next `revisions/work-item-rNNN.json` draft and readable Markdown projection. It becomes immutable when qualification succeeds.
9. Present `WORK_ITEM_PREVIEW` and wait for explicit Human confirmation.
10. Validate the JSON, then use `transition_task.py ... QUALIFY` or `NEW_REVISION` and report `WORK_ITEM_QUALIFIED`.

Do not change production code in this stage. Discussion becomes authority only after it is recorded in the frozen Work Item or a Change Decision.
