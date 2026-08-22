# Polaris

> Clean-slate architecture phase. The new runtime is not implemented or usable yet.

Polaris is a controlled Agent Harness for one long-running software-engineering task.

Its only product goal is:

> **Make an Agent execute long tasks more reliably, correctly, and recoverably.**

The product and implementation authority is [plan.md](plan.md).

## Why Polaris exists

Long tasks often fail even when the model is capable of solving each local step:

- goals and constraints drift after many turns;
- old source, logs, and observations pollute the active context;
- important facts remain stored but stop influencing current decisions;
- a process interruption destroys implicit progress;
- stale repository observations are recovered as if they were current;
- failed actions repeat without changed preconditions;
- the executing model declares completion without independent evidence.

Polaris addresses these failures through runtime mechanisms instead of asking the model to remember more instructions.

## Product model

~~~text
Human
  ↓
Task Contract
  ↓
Polaris Controller
  ├── Runtime State / Event Store
  ├── Context Manager
  ├── Model Client
  ├── Action Gate
  ├── Tool Gateway
  ├── Checkpoint / Recovery
  └── Independent Verifier
        ↓
Local Repository + Tests + Git
~~~

The model owns semantic work:

- understanding requirements and code;
- forming and revising hypotheses;
- choosing implementation strategies;
- writing changes;
- interpreting failures;
- proposing the next action.

Polaris owns facts, resources, and lifecycle:

- freezing the task contract;
- constructing every model-visible Context View;
- validating and executing tools;
- recording provenance and workspace effects;
- establishing durable Action Boundaries;
- recovering after interruption;
- independently verifying completion.

## Controlled execution loop

Every externally observable action returns control to Polaris:

~~~text
Load authoritative state
→ Build minimal Context View
→ Call model
→ Normalize proposed action
→ Check action gate
→ Execute tool or control action
→ Capture provenance and workspace effects
→ Append event
→ Atomically update state
→ Continue / Wait / Verify
~~~

Read-only actions may run as a bounded parallel batch. Mutating actions are serialized, and each mutation must form a durable Action Boundary before the next model call.

The model may request a tool, submit a semantic checkpoint, ask the user, or propose completion. It cannot directly mutate mechanical state or write DONE.

## Context management

Polaris treats the context window as a working set, not a database.

Storage Policy determines:

- whether information has durable backing;
- whether it can be recovered exactly;
- how expensive recovery is;
- which source and version it belongs to.

Attention Policy determines:

- what the current action needs to see;
- which constraints must be foregrounded;
- what remains in the hot working set;
- what becomes a compact recovery reference;
- how the attention budget is spent.

Stored state and model-visible state are intentionally different. Each model request receives a fresh projection of authoritative state rather than append-only chat history.

## Core invariants

1. **The contract does not drift.** Goals, scope, constraints, and acceptance criteria come from a frozen Task Contract.
2. **State does not disappear.** Completed external actions and the next action are persisted before another model call.
3. **Recovery is version-aware.** Mutable repository observations bind provenance and source version.
4. **Failure is bounded.** An unchanged failed action cannot repeat indefinitely.
5. **Mutations are controlled.** Only Polaris executes tools and changes mechanical state.
6. **Completion is not self-certified.** Only the Controller can write DONE after independent verification.

## First release scope

The first implementation intentionally supports only:

- macOS;
- one trusted local repository;
- one active task;
- OpenAI as the single model provider;
- one foreground Controller process;
- local files, search, Patch, Shell, and Git tools;
- file-based state, events, memory, outputs, and checkpoints;
- one clean-context Verifier;
- microbenchmarks, trace replay, and end-to-end long-task evaluation.

## Explicit non-goals

The first release will not include:

- compatibility with pre-refactor Polaris;
- Codex or Claude Code Skill hosting;
- multiple model providers;
- multiple tasks or projects;
- schedulers, queues, daemons, or Task DAGs;
- dashboards, TUI, IDE integrations, or plugin systems;
- databases, vector stores, or knowledge-graph services;
- vendoring, installation manifests, migrations, or cross-platform packaging;
- automatic merge, push, release, or remote execution.

These capabilities require benchmark evidence and an approved change to [plan.md](plan.md).

## Current status

The refactor branch has removed the previous workflow-system implementation. The old Skills, schemas, scripts, templates, host adapters, workflow graph, tests, and usage documentation remain available only through Git history.

The repository is currently in the M0 authority-reset phase:

- the clean-slate architecture is defined;
- the old implementation has been removed;
- the new runtime and tests have not been created;
- there is no installation command or supported user workflow yet.

Do not use old Polaris documentation, releases, or commands as guidance for the new system.

## Roadmap

The implementation proceeds in this order:

1. define failure traces, minimal data models, and baseline benchmarks;
2. build the durable State/Event kernel;
3. add the controlled mutation boundary;
4. add recoverability-aware and attention-aware context management;
5. add the independent verification gate;
6. run baseline, full-system, and ablation long-task evaluations.

Detailed architecture, metrics, milestones, and release gates are maintained in [plan.md](plan.md).
