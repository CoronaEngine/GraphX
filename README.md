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
- maps every Agent attempt to an independent, visible Codex task;
- serializes every workspace mutation;
- persists run state, attempts, thread IDs, and mutation leases in SQLite;
- finishes only through a validated terminal node.

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
    -> NodeDispatch
    -> independent visible Codex task for an Agent attempt
    -> validated NodeResult
    -> next graph transition
```

The Codex controller task shows overall graph progress. Every `agent` attempt has its own Codex task and persisted thread ID. Retries create new attempts and new tasks.

Mechanical nodes such as `command`, `verifier`, `gate`, and `terminal` do not require their own conversation.

## Mutation rule

Any node declared as `workspaceMutation` must acquire a durable workspace-scoped mutation lease. The initial executor dispatches one node at a time, so mutating Agents and commands can never overlap.

The next mutation cannot begin until the previous attempt is committed, proven not to have run, or explicitly resolved. An uncertain mutation becomes `AMBIGUOUS` and is never replayed automatically.

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

Core code forbids unvalidated `Any`, unsafe casts, arbitrary evaluation, dynamic Runner imports, mutable IR, and direct database writes outside the Store.

## Initial node types

- `agent`: dispatch an independent visible Codex task;
- `command`: ask the Host Adapter to run a declared command;
- `verifier`: produce structured verification evidence;
- `gate`: evaluate a restricted condition over persisted outputs;
- `terminal`: commit the declared workflow outcome.

## Documentation

- [plan.md](plan.md): authoritative product scope, architecture, Python implementation plan, and tests.
- [AGENTS.md](AGENTS.md): repository rules for contributors and coding agents.
