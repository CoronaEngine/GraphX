---
name: requirement-analysis
description: Internal Polaris stage for an explicitly started `$engineering-task` workflow. Invoke only to convert its request into a frozen Work Item; do not activate from ordinary user requirements.
---

# Requirement Analysis

Inspect the repository before asking questions. Ask only about unknowns that cannot be inferred and materially affect the solution.

## Stable qualification interaction

If material unknowns remain, keep the task in `DRAFT` and emit `REQUIREMENTS_NEEDED` using the `$engineering-task` status fields. Prepare one to three focused questions per round. Every question must include two or three concrete, mutually exclusive answer options. Put the recommended option first, suffix its label with `(Recommended)`, and explain each option's consequence in one sentence.

When `request_user_input` or an equivalent structured choice tool is callable, use it to display the questions as a UI panel and wait for the response. Keep each header short, keep option labels concise, and do not add an `Other` option when the host supplies a free-form choice automatically. When no such tool is callable, render the identical questions and options in text, followed by an invitation to provide a precise free-form answer. Do not change host mode solely to obtain the panel. Record UI and text answers through the same Work Item fields, keep every unanswered item in `known_unknowns`, and do not modify production code or run `QUALIFY` while any remain.

When the draft is complete, always emit `WORK_ITEM_PREVIEW` before freezing it, even when the original request appeared complete. After the fixed status fields, show:

- observable goal and motivation;
- in-scope and out-of-scope work;
- hard constraints, affected modules, rigor, and true risk flags;
- every acceptance ID with its statement and evidence method;
- Human-owned decisions and approval gates;
- remaining unknowns, which must be `None`.

Ask the user to explicitly confirm this preview. Prefer the structured choice UI with `Confirm and qualify (Recommended)` and `Request changes`; use the same choices as text when the UI is unavailable. Do not infer confirmation from silence or from the original request. Only after confirmation may you write the final draft, validate it, and run `QUALIFY` or `NEW_REVISION`. Then reload state and emit `WORK_ITEM_QUALIFIED` with the frozen JSON and Markdown projection paths. Any later substantive change to goal, scope, constraints, or acceptance creates a new immutable revision; never silently overwrite the qualified revision.

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
