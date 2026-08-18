# Polaris

English | [简体中文](README.zh-CN.md)

> Current protocol version: `0.1.19` (in development); workflow version: `0.1.2`

Polaris is a repo-native engineering workflow for coding agent hosts. It stores requirements, plans, implementation results, independent reviews, validation evidence, and task state in Git, then uses deterministic gates to prevent requirement drift, stale evidence, and agents declaring their own work complete.

Polaris currently supports Codex and Claude Code. [plan.md](plan.md) is the v0.1 product and implementation authority. See the [Chinese usage guide](docs/USAGE.md) for detailed operations.

## Core workflow

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING → IMPLEMENTED
      → DOCS_SYNCED → REVIEWING → REVIEWED
      → VALIDATING → VERIFIED → CLOSED
```

- A Work Item freezes the goal, scope, and acceptance criteria.
- An independent Implementer works from an immutable handoff and updates code, tests, and documentation.
- An independent Reviewer checks specification compliance and engineering quality.
- Validation binds every acceptance criterion to reproducible evidence.
- `events.jsonl` records state changes; `state.json` is a rebuildable projection.
- Reviews and validations bind to the current revision, Git commits, and diff hash. Content changes invalidate stale evidence.
- Only `transition_task.py` can write `VERIFIED` or `CLOSED` after its gates pass.

Tasks use `R1` by default. Low-risk mechanical changes may use `R0`; public APIs, persistent formats, architecture boundaries, concurrency, security, and resource-lifetime changes require `R2`.

## Quick start

Requirements: Git, Python 3.10+, and either Codex or Claude Code. The Polaris runtime uses only the Python standard library.

Install the CLI from the Polaris source repository and vendor Polaris into a target repository:

```powershell
python -m pip install .
polaris vendor C:\path\to\target-repo
```

Enter the target repository, install its locked Polaris version, and initialize it:

```powershell
cd C:\path\to\target-repo
python -m pip install ./tools/polaris
polaris init-project
polaris doctor --repo .
```

Commit the durable `.agents/`, `.claude/`, `tools/polaris/`, and `.polaris/` files to Git.

Explicitly start a task from the target repository root:

```text
# Codex
$engineering-task Add idempotency protection to order creation, with tests and documentation.

# Claude Code
/engineering-task Add idempotency protection to order creation, with tests and documentation.
```

Ordinary requests do not enter Polaris automatically. The workflow first prepares a Work Item and waits for the user to confirm its goal, scope, and acceptance criteria before implementation begins.

## Common commands

```powershell
polaris doctor --repo .
polaris validate-project --repo .
polaris validate-task TASK-0001 --repo .
polaris recover TASK-0001 --repo .
```

The CLI also exposes `vendor`, `init-project`, `init-task`, `migrate`, and optional `code-intelligence` configuration. Run `polaris --help` or `polaris <command> --help` for parameters.

Do not advance task state by editing files. Internal workflow skills must execute legal events through the repository-locked transition script:

```powershell
python tools/polaris/scripts/transition_task.py TASK-0001 <EVENT> --repo .
```

## Optional CodeGraph context

The only formal Code Intelligence Provider is [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph). It is optional and never a workflow gate. The repository owner, not Polaris, installs and initializes it:

```text
codegraph install
codegraph init
polaris code-intelligence add codegraph --repo .
```

Run these commands from the target repository as appropriate. `codegraph init` creates the `.codegraph/` marker; without it Polaris records `UNAVAILABLE` and uses source and Git directly. Polaris can only read CodeGraph status, explore indexed relationships, and perform one bounded `codegraph sync` at a declared stage boundary. It never installs, initializes, starts, configures, reconfigures, waits for, or manages CodeGraph or its watcher/daemon/MCP configuration.

CodeGraph's watcher and connection reconciliation are the primary freshness mechanisms. Polaris records a limited conclusion at the time it checks: `CURRENT_AT_CHECK`, `PARTIAL_STALE`, `INDEX_STALE`, `NOT_VERIFIED`, or `UNAVAILABLE`; it never claims commit-exact graph freshness. A `PARTIAL_STALE` response names specific files: read each current file directly (`READ_SOURCE`), or inspect the registered Git diff if it was deleted (`INSPECT_GIT_DIFF`). For `INDEX_STALE` or `NOT_VERIFIED`, treat the graph only as a lead and search the repository plus Git (`SEARCH_SOURCE`). Validation remains graph-free and relies on source, Git, builds, tests, static checks, and Human Checks.

## v0.1 scope

Polaris v0.1 includes:

- host-native skills and declarative adapters;
- repository-resident JSON authority, workflow, and recovery indexes;
- standard-library validators, handoff, migration, and recovery scripts;
- a thin CLI that only locates and dispatches existing scripts;
- optional, non-blocking CodeGraph context from [colbymchenry/codegraph](https://github.com/colbymchenry/codegraph).

Polaris v0.1 does not include:

- daemons, schedulers, queues, or background services;
- dashboards, TUIs, IDEs, or standalone applications;
- databases, vector stores, or a Polaris-hosted code graph service;
- a custom agent runtime or model abstraction layer;
- task DAGs, automatic archiving, or cross-task scheduling;
- automatic merge, push, release, or remote CI orchestration.

## Repository layout

```text
skills/       Host-neutral workflow skills
hosts/        Codex and Claude Code adapters and worker definitions
scripts/      Executable commands and internal protocol modules
schemas/      Authority and artifact JSON schemas
templates/    Project and task templates
workflow/     Default workflow and migration registry
tests/        Gate, validator, and cross-platform tests
```

## Development and validation

```powershell
python tests/run_tests.py
python -m unittest discover -s tests -v
python -m compileall -q polaris_cli.py scripts tests
```

Contributions must preserve the standard-library-only runtime, four-space JSON, and cross-platform behavior. Add tests for every new or changed gate, state transition, and validator rule. Define task layout only in `scripts/internal/task_layout.py`; edit template bodies only in `templates/task-sources/`, then run:

```powershell
python scripts/materialize_task_layout.py
```

## Documentation

- [Chinese usage guide](docs/USAGE.md): setup, task execution, recovery, upgrades, and troubleshooting.
- [v0.1 implementation plan](plan.md): product scope, authority, workflow, protocol, and milestones.

## License

This repository does not currently include an open-source license. Until a license is added, do not assume the code may be redistributed under an open-source license.
