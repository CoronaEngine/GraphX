"""Zero-runtime-dependency command dispatcher for user-facing Polaris scripts."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence


COMMANDS = {
    "vendor": ("vendor_project.py", "Vendor Polaris into a target repository"),
    "init-project": ("init_project.py", "Initialize project Authority"),
    "init-task": ("init_task.py", "Initialize a task"),
    "doctor": ("doctor_project.py", "Diagnose project health"),
    "validate-project": ("validate_project.py", "Validate project Authority"),
    "validate-task": ("validate_task.py", "Validate a task"),
    "recover": ("recover_task.py", "Recover a task from repository Authority"),
    "migrate": ("migrate_project.py", "Run the next explicit project migration"),
}


def _parser() -> argparse.ArgumentParser:
    command_help = "\n".join(
        f"  {command:<18} {description}"
        for command, (_, description) in COMMANDS.items()
    )
    parser = argparse.ArgumentParser(
        prog="polaris",
        description="Dispatch user-facing commands to the repository-locked Polaris protocol.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="commands:\n" + command_help + "\n\nRun 'polaris <command> --help' for command options.",
    )
    parser.add_argument("command", nargs="?", help=argparse.SUPPRESS)
    return parser


def _option_value(arguments: Sequence[str], option: str) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == option:
            if index + 1 >= len(arguments):
                return None
            return arguments[index + 1]
        prefix = option + "="
        if argument.startswith(prefix):
            return argument[len(prefix) :]
    return None


def _ancestors(path: Path) -> tuple[Path, ...]:
    resolved = path.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    return (resolved, *resolved.parents)


def _protocol_script(root: Path, script_name: str) -> tuple[Path, Path] | None:
    vendored_script = root / "tools" / "polaris" / "scripts" / script_name
    if vendored_script.is_file() and (root / "tools" / "polaris" / "VERSION").is_file():
        return vendored_script, root
    source_script = root / "scripts" / script_name
    if source_script.is_file() and (root / "VERSION").is_file():
        vendored_root = root.parent.name == "tools" and root.name == "polaris"
        repository = root.parent.parent if vendored_root else root
        return source_script, repository
    return None


def _resolve_script(
    command: str, arguments: Sequence[str], cwd: Path
) -> tuple[Path, list[str]]:
    script_name = COMMANDS[command][0]
    if command == "vendor":
        explicit_source = _option_value(arguments, "--source")
        roots = (
            (Path(explicit_source).resolve(),)
            if explicit_source is not None
            else _ancestors(cwd)
        )
        for root in roots:
            resolved = _protocol_script(root, script_name)
            if resolved is not None:
                return resolved[0], list(arguments)
        raise FileNotFoundError(
            "cannot locate a Polaris protocol source for vendor; "
            "run from a Polaris source/vendored repository or pass --source"
        )

    explicit_repo = _option_value(arguments, "--repo")
    roots = (
        (Path(explicit_repo).resolve(),)
        if explicit_repo is not None
        else _ancestors(cwd)
    )
    for root in roots:
        resolved = _protocol_script(root, script_name)
        if resolved is None:
            continue
        script, repository = resolved
        forwarded = list(arguments)
        if explicit_repo is None:
            forwarded.extend(["--repo", str(repository)])
        return script, forwarded
    raise FileNotFoundError(
        "cannot locate tools/polaris for this repository; "
        "run inside an initialized vendored project or pass --repo"
    )


def dispatch(command: str, arguments: Sequence[str], cwd: Path | None = None) -> int:
    if command not in COMMANDS:
        raise ValueError(f"unknown Polaris command: {command}")
    script, forwarded = _resolve_script(command, arguments, cwd or Path.cwd())
    completed = subprocess.run([sys.executable, str(script), *forwarded])
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _parser()
    if not arguments or arguments[0] in {"-h", "--help"}:
        parser.print_help()
        return 0
    command = arguments[0]
    if command not in COMMANDS:
        parser.error(f"unknown command: {command}")
    try:
        return dispatch(command, arguments[1:])
    except KeyboardInterrupt:
        return 130
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
