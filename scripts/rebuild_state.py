#!/usr/bin/env python3
"""Rebuild state.json from the append-only Polaris event ledger."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from polaris_core import rebuild_state_value, run_main, task_dir, write_json_atomic
from recovery_protocol import refresh_project_index


def rebuild(repo: Path, task_id: str, check_only: bool) -> dict[str, object]:
    directory = task_dir(repo, task_id)
    state = rebuild_state_value(directory / "events.jsonl")
    state_path = directory / "state.json"
    if not check_only:
        write_json_atomic(state_path, state)
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
