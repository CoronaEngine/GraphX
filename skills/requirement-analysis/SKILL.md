---
name: requirement-analysis
description: Internal Polaris stage for an explicitly started `$engineering-task` workflow. Invoke only to convert its request into a frozen Work Item; do not activate from ordinary user requirements.
---

# Requirement Analysis

Inspect the repository before asking questions. Ask only about unknowns that cannot be inferred and materially affect the solution.

1. Define an observable goal and motivation.
2. Separate in-scope and out-of-scope work.
3. Record hard constraints and affected modules.
4. Give every acceptance criterion a stable `AC-NN` ID and reproducible evidence method.
5. Set every risk flag explicitly. Any true risk flag requires at least R2.
6. Assign Human and Agent decision owners. Do not decide Human-owned boundaries.
7. Bind `base_commit` to a full Git SHA.
8. Write the next immutable `revisions/work-item-rNNN.json` and its readable Markdown projection.
9. Validate the JSON, then use `transition_task.py ... QUALIFY` or `NEW_REVISION`.

Do not change production code in this stage. Discussion becomes authority only after it is recorded in the frozen Work Item or a Change Decision.
