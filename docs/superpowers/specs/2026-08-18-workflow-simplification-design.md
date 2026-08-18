# Polaris Workflow Simplification Design

## Status

Approved direction: implement the workflow simplifications identified in the repository audit.

Target protocol version: `0.1.20`  
Target workflow version: `0.1.3`

## Problem

The current `0.1.2` workflow preserves strong governance boundaries, but several persisted states and gates do not introduce new authority, evidence, or a human decision. The largest problem is that ignored local telemetry in `runtime/progress.json` is a hard prerequisite for the durable `FINISH_IMPLEMENTATION` transition even though the protocol says runtime state does not participate in phase gates or Fresh Clone recovery.

The happy path also contains mechanically adjacent transitions that can be combined:

- `START_IMPLEMENTATION` followed by the `DISPATCH_IMPLEMENTATION` self-transition;
- `FINISH_IMPLEMENTATION` followed by resuming the same Implementer for `SYNC_DOCS`;
- `ACCEPT_REVIEW` followed by `START_VALIDATION`, with the same Reviews checked twice;
- `PASS_VALIDATION` followed by `CLOSE` for R0/R1, where no final Human approval exists.

Code Intelligence is optional and non-blocking, but every stage currently writes an unavailable or skipped record even when the Provider is not used. This creates durable noise without strengthening a gate.

Finally, the product authority says closure requires a full task validation pass, while the implemented closure gate currently checks only Result and the optional R2 final approval.

## Goals

1. Remove persisted states and transitions that have no distinct governance boundary.
2. Make ignored live progress optional telemetry rather than durable authority.
3. Keep Work Item, Plan decisions, Implementation handoff, Implementation, Knowledge Delta, Review handoff, Review, Validation, Result, event ledger, and state projection as durable artifacts.
4. Preserve independent Review and acceptance-driven Validation as separate stages.
5. Preserve an explicit `VERIFIED` waiting state only for R2 final Human approval.
6. Make closure validate the complete candidate task projection before committing the transition.
7. Provide an explicit, recoverable migration from workflow `0.1.2` to `0.1.3`.
8. Keep the runtime dependency-free beyond the Python standard library.

## Non-goals

- Removing independent Implementer or Reviewer isolation.
- Removing Work Item confirmation, Plan decisions, Knowledge Delta, Review, or Validation.
- Introducing a daemon, scheduler, task DAG, database, or custom Agent Runtime.
- Automatically pushing, merging, publishing, or running remote CI.
- Rewriting or deleting historical artifacts or events.

## Options Considered

### Option A: Change only Skills and documentation

This would reduce conversational ceremony but leave the persisted workflow and gates unchanged. Existing frozen workflow projects would still require the old transitions. It would also leave the ignored-progress hard gate in place.

Rejected because it does not solve the mechanical redundancy.

### Option B: Keep all states but automatically chain transitions

The controller could immediately run `DISPATCH_IMPLEMENTATION`, `START_VALIDATION`, and `CLOSE` after their predecessors. This reduces user-visible pauses but retains duplicate events, repeated validation, intermediate checkpoint commits, and recovery states with no independent meaning.

Rejected because it hides rather than removes the complexity.

### Option C: Version and simplify the workflow

Introduce workflow `0.1.3`, remove redundant states and events, loosen the telemetry dependency, and explicitly migrate existing tasks.

Selected because it aligns persisted control flow with actual governance boundaries while preserving auditability.

## Target Workflow

The normal persisted path becomes:

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING
      → REVIEWING → VALIDATING → CLOSED
```

R2 uses an additional final approval state:

```text
VALIDATING → VERIFIED → CLOSED
```

The states `IMPLEMENTED`, `DOCS_SYNCED`, and `REVIEWED` are removed from workflow `0.1.3`.

The following governance loops remain:

```text
REVIEWING  -- REJECT_REVIEW --> IMPLEMENTING
VALIDATING -- FAIL_IMPLEMENTATION --> IMPLEMENTING
VALIDATING -- FAIL_PLAN --> PLANNED
non-terminal -- NEW_REVISION --> QUALIFIED
non-terminal -- BLOCK --> BLOCKED
BLOCKED -- RESOLVE_BLOCK --> blocked_from
non-terminal -- CANCEL --> CANCELLED
```

## Transition Design

### Start Implementation

`START_IMPLEMENTATION` moves `PLANNED → IMPLEMENTING` and requires the Implementation handoff in the same transition. Its gate combines:

- R2 pre-approval validation;
- handoff identity, revision, attempt, Plan, Working Set, and package validation.

`DISPATCH_IMPLEMENTATION` is removed. Worker dispatch remains a host action performed after the handoff is registered; it is not a persisted workflow state.

### Finish Implementation and Start Review

The Implementer completes code, tests, required project documentation, final checks, the Implementation artifact, and Knowledge Delta before returning. Both artifacts bind the same final subject commit and diff hash.

The main controller then builds the immutable Review handoff and runs `START_REVIEW` directly from `IMPLEMENTING`. The transition registers:

- `implementation`;
- `knowledge_delta`;
- `review_handoff`;
- the final subject base/head commits.

Its combined gate checks the Implementation handoff binding, Implementation artifact, Knowledge Delta, documentation impact, final subject, and Review handoff. It then moves `IMPLEMENTING → REVIEWING`.

There is no separate Implementation checkpoint commit before documentation. The final subject checkpoint already includes code, tests, build configuration, and project documentation.

### Accept Review and Start Validation

`ACCEPT_REVIEW` validates all required Review artifacts once and moves `REVIEWING → VALIDATING`. `START_VALIDATION` is removed. Validation remains a separate stage and produces a new immutable Validation artifact.

### Pass Validation and Close

Two explicit pass events avoid conditional destinations hidden in code:

- `PASS_AND_CLOSE`: valid only for R0/R1, registers Validation and Result, validates the complete candidate CLOSED projection, and moves `VALIDATING → CLOSED`.
- `PASS_VALIDATION`: valid only for R2, registers Validation, validates all acceptance criteria, and moves `VALIDATING → VERIFIED`.

R2 then records final Human approval and Result before `CLOSE` moves `VERIFIED → CLOSED`. Both closing paths execute the same complete candidate-task validator before appending the event.

## Candidate Projection Validation

Task validation will be refactored so the same rules can validate either:

- the projection currently stored in `state.json`; or
- a candidate projection prepared by `transition_task.py` before an event is appended.

The public `validate_task.py` command continues to validate the stored state and event reconstruction. Closing gates call the shared candidate validator with the proposed CLOSED state and registered artifacts. No transition may append a CLOSED event and validate afterward.

This eliminates the current discrepancy between `plan.md` and `closure_ready` without duplicating a second set of closure rules.

## Live Implementation Progress

`runtime/progress.json` remains available for hosts that can expose live progress, but it is explicitly best-effort and optional:

- it remains Git ignored;
- its absence never blocks `START_REVIEW`, recovery, or closure;
- R0 does not require initialization or step events;
- R1/R2 may use ordered steps for status reporting, but the final Implementation artifact is authoritative;
- if a valid progress snapshot exists, the controller may compare it with the Implementation summary and report discrepancies as a warning, not a transition failure;
- Implementation `step_results` remain required durable summaries and are written directly into the Implementation artifact.

The progress updater continues to reject corrupt or conflicting updates when it is used. Its local state machine is not part of the project workflow graph.

## Code Intelligence Records

Code Intelligence remains optional, provider-neutral at artifact boundaries, and non-blocking.

- Stage artifacts may omit the Code Intelligence reference when no query or freshness-relevant operation was performed.
- Missing marker, disabled policy, or a Provider known to be unavailable in the current session does not require a new durable stage record.
- A durable record is written only when a stage performed a Provider status, sync, or explore operation whose result is useful audit evidence.
- Source and Git fallbacks remain mandatory whenever Provider evidence is stale or insufficient.
- Validation continues to exclude Code Intelligence as acceptance evidence.

Historical v1 and v2 records remain immutable and readable.

## Migration from Workflow 0.1.2

Protocol `0.1.20` adds an explicit migration strategy capable of replacing the frozen workflow and mapping task projections. The migration remains adjacent, append-only, resumable, and lock-protected.

State mapping:

| Old state | New state |
|---|---|
| `DRAFT` | `DRAFT` |
| `QUALIFIED` | `QUALIFIED` |
| `PLANNED` | `PLANNED` |
| `IMPLEMENTING` with registered handoff | `IMPLEMENTING` |
| `IMPLEMENTING` without registered handoff | `PLANNED` |
| `IMPLEMENTED` | `IMPLEMENTING` |
| `DOCS_SYNCED` | `IMPLEMENTING` |
| `REVIEWING` | `REVIEWING` |
| `REVIEWED` | `VALIDATING` |
| `VALIDATING` | `VALIDATING` |
| `VERIFIED` | `VERIFIED` |
| `BLOCKED` | `BLOCKED`, with `blocked_from` mapped by the same rules |
| `CLOSED` | `CLOSED` |
| `CANCELLED` | `CANCELLED` |

Artifacts are preserved. Mapping `DOCS_SYNCED → IMPLEMENTING` lets the new `START_REVIEW` gate reuse the existing Implementation and Knowledge Delta and generate only the missing Review handoff. Mapping `IMPLEMENTED → IMPLEMENTING` lets the same Implementer finish documentation without relying on the ignored progress file.

Each migrated task receives one `MIGRATE_POLARIS` event containing old/new protocol version, old/new workflow version, and old/new state. The migration record stores before/after event sequence and mapped status. Reruns reuse an already appended matching event and reject inconsistent partial state.

## Authority and Artifact Compatibility

- Historical `events.jsonl` entries may name removed states; they remain valid historical events.
- The rebuilt current projection uses the final migration event and workflow `0.1.3`.
- Existing immutable artifacts are never rewritten merely to adopt the new workflow.
- New Implementation and Knowledge Delta artifacts bind one final subject.
- `state.json` continues to store only current artifact pointers.
- Result remains a durable closure summary, but R0/R1 controllers generate it before `PASS_AND_CLOSE` rather than through a separate VERIFIED checkpoint.

## Skills and User-Facing Contract

The stable nine-field Polaris status block remains unchanged. Removed checkpoint markers are no longer emitted on new workflow tasks:

- `IMPLEMENTATION_FINISHED` and `DOCS_SYNCED` collapse into `REVIEW_HANDOFF_READY` after the final subject is ready;
- `REVIEW_ACCEPTED` reports state `VALIDATING` and immediately identifies Validation as the next action;
- R0/R1 `VALIDATION_PASS` is followed by the same successful transition result at `CLOSED`, so the controller emits only `TASK_CLOSED`;
- R2 still emits `VALIDATION_PASS` at `VERIFIED`, requesting final approval.

Recovery recommendations and documentation are updated to describe the new states and legal next actions.

## Testing Strategy

Tests are written before implementation changes and must cover:

1. `START_IMPLEMENTATION` atomically registers and validates its handoff.
2. `DISPATCH_IMPLEMENTATION` is absent and rejected.
3. Missing `runtime/progress.json` does not block the final implementation-to-review transition.
4. `START_REVIEW` requires matching Implementation, Knowledge Delta, documentation check, final subject, and Review handoff.
5. Implementation and Knowledge Delta bind the same final subject.
6. `ACCEPT_REVIEW` moves directly to `VALIDATING`; `START_VALIDATION` is absent.
7. R0/R1 `PASS_AND_CLOSE` requires Validation, Result, and a complete candidate-task validation pass.
8. R2 cannot use `PASS_AND_CLOSE`, reaches `VERIFIED` through `PASS_VALIDATION`, and still requires final approval to close.
9. Code Intelligence references may be omitted when unused, while present records remain fully validated.
10. Every old workflow state migrates deterministically, including `BLOCKED.blocked_from` and the pre-handoff IMPLEMENTING edge case.
11. Interrupted migration resumes without duplicate events.
12. Documentation, templates, schemas, host-rendered Skills, and the full R1/R2 flow match workflow `0.1.3`.

The full repository test suite, compile check, template materialization check, and clean-worktree inspection are required before completion.

## Success Criteria

- New R1 happy paths require one start-implementation transition, one start-review transition, one review-accept transition, and one pass-and-close transition after planning.
- No ignored runtime file is required by a durable gate.
- Review and Validation remain independently evidenced.
- R2 retains both Human approval gates.
- Existing `0.1.2` projects have an explicit adjacent migration path.
- `validate_task.py` and closing transitions share one legality implementation.
- All tests pass using only Python standard-library runtime code.
