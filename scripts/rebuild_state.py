#!/usr/bin/env python3
"""Rebuild state.json from the append-only Polaris event ledger."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from internal.polaris_core import (
    rebuild_state_value,
    require_protocol_compatible,
    run_main,
    task_dir,
    write_json_atomic,
)
from internal.recovery_protocol import refresh_project_index
from internal.task_layout import events_path, state_path


def rebuild(repo: Path, task_id: str, check_only: bool) -> dict[str, object]:
    directory = task_dir(repo, task_id)
    state = rebuild_state_value(events_path(directory))
    destination = state_path(directory)
    if not check_only:
        require_protocol_compatible(repo, state)
        write_json_atomic(destination, state)
        refresh_project_index(repo)
    return {
        "message": f"{task_id} state {'checked' if check_only else 'rebuilt'} at sequence {state['sequence']}",
        "task": task_id,
        "sequence": state["sequence"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: rebuild(args.repo.resolve(), args.task_id, args.check), args.json
    )


if __name__ == "__main__":
    sys.exit(main())
