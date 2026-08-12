#!/usr/bin/env python3
"""Create the next immutable Work Item revision without changing task state."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from polaris_core import (
    InputFailure,
    current_work_item_path,
    full_commit,
    read_json,
    run_main,
    task_dir,
    write_json_atomic,
)


def create(repo: Path, task_id: str) -> dict[str, object]:
    directory = task_dir(repo, task_id)
    state = read_json(directory / "state.json")
    revision = state["current_revision"] + 1
    destination = current_work_item_path(directory, revision)
    if destination.exists():
        raise InputFailure(f"revision already exists: {destination}")
    value = copy.deepcopy(read_json(current_work_item_path(directory, state["current_revision"])))
    value["revision"] = revision
    value["base_commit"] = full_commit(repo)
    value["known_unknowns"] = ["Review and freeze changes for this revision"]
    write_json_atomic(destination, value)
    markdown = directory / "revisions" / f"WORK_ITEM-r{revision:03d}.md"
    markdown.write_text(
        "# Work Item\n\n"
        f"Readable projection for `{task_id}@r{revision:03d}`. "
        f"The matching JSON file is authoritative.\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "message": f"created {task_id}@r{revision:03d}; edit and freeze it before NEW_REVISION",
        "task": task_id,
        "revision": revision,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: create(args.repo.resolve(), args.task_id), args.json)


if __name__ == "__main__":
    sys.exit(main())
