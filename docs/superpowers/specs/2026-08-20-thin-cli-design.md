# Polaris Thin CLI Design

## Context

Polaris is being rebuilt from commit `3589fc3`, before CodeGraph support was added. The current protocol version is `0.1.15`. The rebuild intentionally omits CodeGraph and restores only the useful user-facing CLI layer.

## Decision

Release the CLI restoration as Polaris `0.1.16`.

The CLI is a standard-library-only dispatcher. It does not own workflow rules, validation, migrations, state transitions, scheduling, persistence, or agent orchestration. It locates the correct source or vendored protocol script, forwards arguments unchanged apart from supplying an inferred `--repo`, and returns the child process exit status.

The public command set is exactly:

| Command | Script |
| --- | --- |
| `vendor` | `vendor_project.py` |
| `init-project` | `init_project.py` |
| `init-task` | `init_task.py` |
| `doctor` | `doctor_project.py` |
| `validate-project` | `validate_project.py` |
| `validate-task` | `validate_task.py` |
| `recover` | `recover_task.py` |
| `migrate` | `migrate_project.py` |

Internal state transitions and artifact-building scripts remain script-only. There is no `code-intelligence` command and no CodeGraph/provider subsystem.

## Resolution and dispatch

For commands other than `vendor`, the dispatcher uses an explicit `--repo` when present. Otherwise it walks from the current directory toward the filesystem root. At each candidate repository it prefers `tools/polaris/scripts/<script>` when the corresponding vendored `VERSION` exists; it also accepts the Polaris source tree layout for repository development. When the repository was inferred, the dispatcher appends `--repo <resolved-root>`.

For `vendor`, `--source` selects the protocol source. Without it, the dispatcher walks upward from the current directory. The target argument and all original options are forwarded unchanged.

The dispatcher invokes scripts with the running interpreter (`sys.executable`), preserves standard input/output/error streams, and returns the child exit status. Dispatcher resolution or operating-system errors print `ERROR: ...` to standard error and return `2`; interruption returns `130`. Script-defined `0`, `1`, and `2` meanings remain unchanged.

## Packaging and vendoring

The root `pyproject.toml` exposes `polaris = "polaris_cli:main"` under distribution name `corona-polaris`, version `0.1.16`, Python `>=3.10`, and no runtime dependencies. `setuptools` is build tooling only.

`vendor_project.py` copies `pyproject.toml` and `polaris_cli.py` beside `VERSION` under `tools/polaris/`. Both files are managed by the install manifest. This lets a target repository install the exact CLI that matches its vendored protocol.

## Versioning

`VERSION`, project templates, task source templates, and materialized task templates advance from `0.1.15` to `0.1.16`. Workflow version remains `0.1.2`.

`workflow/migrations.json` gains one adjacent `0.1.15-to-0.1.16` migration using `replace_version` for the project and `append_version_event` for tasks. Existing migration behavior, resumability, and lock ownership rules remain unchanged.

## Documentation and CI

`AGENTS.md`, `plan.md`, `README.md`, and `docs/USAGE.md` describe the thin CLI as part of v0.1 while continuing to forbid protocol logic in it. Examples use the eight public commands where applicable and retain direct script examples for internal state transitions.

CI compiles `polaris_cli.py`, installs the package with `--no-deps`, smoke-tests `polaris --help`, and runs the existing cross-platform test suite.

## Acceptance criteria

- `polaris --help` lists exactly the eight public commands and no internal command.
- Dispatch from a nested directory uses the repository-locked vendored script.
- Explicit `--repo` and `--source` forms are accepted and not rewritten.
- Arguments, output streams, and child exit status retain the underlying script semantics.
- A vendored target contains byte-identical `pyproject.toml` and `polaris_cli.py`, both covered by its install manifest.
- The package declares zero runtime dependencies and installs a working `polaris` console entry point.
- A `0.1.15` project migrates explicitly and resumably to `0.1.16`; no workflow version change occurs.
- Tests and documentation contain no CodeGraph or `code-intelligence` CLI surface.
