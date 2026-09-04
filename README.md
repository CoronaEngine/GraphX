# GraphX

GraphX is a strict Task Graph Executor for Codex.

```text
Workflow Config owns control.
GraphX validates and advances the graph.
Codex tasks perform semantic work.
```

[中文说明](README.zh-CN.md)

## Status

GraphX is in early implementation design. [plan.md](plan.md) is the single authority for product scope, execution semantics, implementation order, and release gates.

## What GraphX does

GraphX:

- validates a declarative Workflow Config;
- compiles it into an immutable typed Workflow IR;
- calculates the next ready node deterministically;
- dispatches nodes and validates structured results;
- maps every bound Agent attempt to exactly one independent, visible Codex task;
- serializes every workspace mutation;
- persists run state, attempts, thread IDs, and mutation leases in SQLite;
- commits a business outcome only through a validated terminal node; an operational failure or cancellation may end the run without one.

GraphX does not:

- invent or optimize the business workflow;
- perform coding work itself;
- manage model context, compaction, or chat history;
- reimplement Codex tools or sandboxing;
- allow an Agent to rewrite the graph or declare the workflow complete.

## Execution model

```text
Codex controller task
    -> GraphX Skill
    -> short MCP call
    -> Python Graph Executor
    -> durable DispatchReservation
    -> independent visible Codex task
    -> bound AgentAttempt and activated Task Contract
    -> validated NodeResult
    -> next graph transition
```

The Codex controller task shows overall graph progress. GraphX persists a dispatch reservation before asking the Host to create an external task. A successful bind atomically creates the `AgentAttempt` and its immutable task handle; semantic work starts only after activation. Retries create new reservations, attempts, and tasks.

External mechanical nodes such as `command` and `verifier` use persisted mechanical attempts and execution handles, without a Codex conversation. Pure `gate` and `terminal` conditions are evaluated internally.

## Mutation rule

Any node declared as `workspaceMutation` must acquire a durable workspace-scoped mutation lease. The initial executor permits at most one active external execution per run; within one GraphX coordination domain backed by a shared SQLite control store, it permits at most one mutation lease per canonical workspace identity. This does not lock out writers that bypass GraphX.

The next mutation cannot begin until the prior execution is quiescent (or strongly proven never to have existed), its workspace revision is reconciled, and the configured settlement requirement is satisfied by valid normal or equivalent recovery evidence. A mutation node may therefore be successful while its lease remains held for settlement. An uncertain mutation becomes `ambiguous` and is never replayed automatically.

## Runtime validation

Static typing does not validate runtime data. Workflow JSON, MCP messages, Codex results, SQLite rows, and recovered state are untrusted until checked.

GraphX uses four layers:

1. JSON Schema and strict boundary models;
2. semantic graph validation;
3. explicit state-transition validation;
4. SQLite constraints and transactions.

## Python implementation

The initial implementation uses:

- Python 3.12;
- Pyright strict;
- Ruff;
- pytest;
- strict Pydantic models or an equivalent JSON Schema validator;
- standard-library SQLite;
- a Python MCP server and a Codex Skill.

The Python package is split into pure `core`, use-case-oriented `application`, dependency-neutral wire `protocol`, and external `adapters`. Service dependencies point inward; Core performs no I/O, Application does not import concrete adapters, the external Host depends only on versioned protocol contracts, and only the SQLite adapter opens connections or executes SQL.

## Initial node types

- `agent`: dispatch an independent visible Codex task;
- `command`: ask the Host Adapter to run a declared command;
- `verifier`: produce structured verification evidence;
- `gate`: evaluate a restricted condition over persisted outputs;
- `terminal`: commit the declared workflow outcome.

## Documentation

- [plan.md](plan.md): authoritative product scope, architecture, Python implementation plan, and tests.
- [AGENTS.md](AGENTS.md): repository rules for contributors and coding agents.
