# Polaris

Polaris is a deterministic Task Graph Executor for probabilistic coding agents.

It executes a workflow supplied as data. The workflow defines the nodes, dependencies, conditions, retries, and completion criteria; Polaris validates and enforces those rules without deciding what the workflow should be.

```text
Config owns control.
Polaris enforces control.
Nodes perform work.
```

[中文说明](README.zh-CN.md)

## Status

Polaris is in early design and implementation. The authoritative implementation scope is [plan.md](plan.md); [Polaris_Design_ZH_v0.2.md](Polaris_Design_ZH_v0.2.md) contains the longer design rationale.

## What Polaris does

```text
Workflow JSON
    -> compiler and static validation
    -> immutable typed Workflow IR
    -> persistent graph runtime
    -> node runners
    -> verified terminal outcome
```

Polaris owns:

- workflow compilation and graph validation;
- deterministic ready-node calculation and scheduling;
- node and run state transitions;
- typed inputs, outputs, and content-addressed artifacts;
- bounded retries, timeouts, and conservative recovery;
- durable action boundaries around side effects;
- verification gates and terminal-state enforcement;
- deterministic context materialization from declared node inputs.

Polaris does not own:

- the business meaning or preferred shape of a workflow;
- automatic workflow invention or optimization;
- the reasoning policy inside an agent node;
- token-level context compaction, transcript garbage collection, or model caching;
- distributed scheduling or a general-purpose enterprise workflow platform.

## Workflow-agnostic, not semantics-free

Polaris does not need to know whether a node is planning, editing Rust, running tests, or reviewing a patch. It does need to understand the graph's execution semantics: node types, dependencies, typed data flow, conditions, retry policy, side effects, persistence, and terminal outcomes.

The same runtime should execute any valid v1 DAG without hard-coded stage names or workflow-specific branches.

## Workflow IR

IR means Intermediate Representation: the normalized, typed, immutable form between user-authored configuration and runtime execution.

```text
Human-authored config
        |
        v
Compiler + validator
        |
        v
Workflow IR
        |
        v
Graph Executor
```

The compiler resolves references, expands defaults, type-checks inputs and outputs, compiles conditions into a restricted AST, analyzes the graph, and assigns a stable IR hash. Runtime state is stored separately and can never mutate the IR.

## Built-in node types in v1

- `agent`: run Codex or another compatible agent runtime against a structured task contract;
- `command`: execute an argv-based local command with bounded output and timeout;
- `verifier`: produce mechanical or probabilistic evidence about artifacts;
- `gate`: evaluate a restricted condition over persisted data;
- `terminal`: commit the declared workflow outcome when its prerequisites hold.

Node runners perform local work and return structured results. They cannot rewrite the graph, commit runtime state directly, or declare the whole run complete.

## Reliability model

Polaris persists the workflow IR, append-only events, materialized run state, node attempts, logs, and artifacts. Before a side-effecting attempt starts, it records a durable action boundary.

After a crash, Polaris reconciles each unfinished attempt as one of:

- proven not executed, so policy may permit a retry;
- proven successful, so the original result can be committed;
- uncertain, so the node becomes `AMBIGUOUS` and later side effects stop pending intervention.

Polaris does not claim exactly-once execution where the underlying runner cannot prove it.

## Agent context boundary

For an `agent` node, Polaris builds a Task Contract from the node specification, declared artifacts, workspace identity, output schema, and attempt policy. It does not replay the entire workflow history by default.

The underlying agent runtime—such as Codex—continues to own its model context window, compaction, tool protocol, and inference behavior. Polaris owns cross-node data routing, artifact identity, observation freshness, and recovery.

## v1 scope

The first release is intentionally narrow:

- one local foreground run;
- JSON config plus JSON Schema;
- immutable typed IR;
- sequential execution of an acyclic graph in stable order;
- five built-in node types;
- typed artifacts and restricted conditions;
- bounded timeout and retry policies;
- append-only events, atomic checkpoints, and crash recovery;
- CLI commands for validate, run, resume, and inspect.

Cycles, dynamic graph expansion, parallel joins, distributed runners, external side effects, visual workflow editing, and a plugin system are later candidates, not v1 commitments.

## Design invariants

1. Configuration owns the workflow; runtime never invents business control flow.
2. Invalid graphs fail before execution.
3. Authoritative state lives outside model context.
4. Only the executor commits state transitions.
5. Cross-node data moves through typed, integrity-checked artifacts.
6. Retries and timeouts are explicit and bounded.
7. Uncertain side effects are surfaced as `AMBIGUOUS`, never silently replayed.
8. Workflow completion requires an explicit verified terminal node.

## Documentation

- [plan.md](plan.md): authoritative product scope, execution semantics, implementation tasks, and test gates.
- [Polaris_Design_ZH_v0.2.md](Polaris_Design_ZH_v0.2.md): detailed Chinese design rationale and architectural exploration.
- [AGENTS.md](AGENTS.md): repository rules for contributors and coding agents.
