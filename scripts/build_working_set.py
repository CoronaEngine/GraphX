#!/usr/bin/env python3
"""Generate a bounded Working Set skeleton from the frozen Work Item."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from polaris_core import InputFailure, current_work_item_path, read_json, run_main, task_dir


def build(repo: Path, task_id: str, force: bool) -> dict[str, str]:
    directory = task_dir(repo, task_id)
    state = read_json(directory / "state.json")
    work_item = read_json(current_work_item_path(directory, state["current_revision"]))
    destination = directory / "WORKING_SET.md"
    if destination.exists() and not force:
        current = destination.read_text(encoding="utf-8")
        if current.strip() and current.strip() != "# Working Set":
            raise InputFailure(f"working set already exists; use --force to regenerate: {destination}")
    modules = "\n".join(
        f"- `{module}` — declared by Work Item affected_modules"
        for module in work_item["affected_modules"]
    ) or "- None declared"
    unknowns = "\n".join(f"- {item}" for item in work_item["known_unknowns"]) or "- None"
    content = f"""# Working Set

Generated for `{task_id}@r{state['current_revision']:03d}`. Keep entries as `path — reason — discovered_from`.

## Documents

- `AGENTS.md` — project rules — recovery bootstrap

## Code

{modules}

## Tests

- Locate tests mapped to each acceptance criterion.

## Decisions

- Load only decisions referenced by the Work Item or affected modules.

## Explorations

- Load only explorations matching a current module or hypothesis.

## Unknowns

{unknowns}
"""
    destination.write_text(content, encoding="utf-8", newline="\n")
    return {"message": f"generated {destination}", "path": str(destination)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: build(args.repo.resolve(), args.task_id, args.force), args.json
    )


if __name__ == "__main__":
    sys.exit(main())
