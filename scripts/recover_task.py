#!/usr/bin/env python3
"""Recover only the bounded state needed for a fresh Polaris session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from implementation_protocol import validate_progress
from polaris_core import (
    InputFailure,
    RuleFailure,
    current_work_item_path,
    read_json,
    run_main,
    task_dir,
)
from recovery_protocol import (
    recommended_action,
    refresh_project_index,
)
from working_set_protocol import validate_working_set, working_set_entries
from validate_project import validate as validate_project
from validate_task import validate as validate_task


def recover(repo: Path, task_id: str) -> dict[str, Any]:
    refresh_project_index(repo)
    validate_project(repo)
    validate_task(repo, task_id)
    directory = task_dir(repo, task_id)
    state = read_json(directory / "state.json")
    work_item = read_json(current_work_item_path(directory, state["current_revision"]))
    events_path = directory / "events.jsonl"
    last_event = None
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last_event = json.loads(line)
    blocker = state.get("blocker")
    work_item_path = current_work_item_path(directory, state["current_revision"])
    working_set_path = directory / "working-set.json"
    minimum_entries = [
        {
            "section": "Bootstrap",
            "path": "AGENTS.md",
            "reason": "project rules",
            "discovered_from": "fixed recovery order",
        },
        {
            "section": "Bootstrap",
            "path": ".polaris/project-index.json",
            "reason": "bounded project recovery map",
            "discovered_from": "fixed recovery order",
        },
        {
            "section": "Bootstrap",
            "path": (directory / "state.json").relative_to(repo).as_posix(),
            "reason": "current authority projection",
            "discovered_from": "active task index",
        },
        {
            "section": "Bootstrap",
            "path": work_item_path.relative_to(repo).as_posix(),
            "reason": "frozen execution contract",
            "discovered_from": "current task revision",
        },
        {
            "section": "Bootstrap",
            "path": working_set_path.relative_to(repo).as_posix(),
            "reason": "bounded task context cache",
            "discovered_from": "fixed recovery order",
        },
    ]
    known_paths = {item["path"] for item in minimum_entries}
    working_set_status: dict[str, Any]
    try:
        working_set = validate_working_set(repo, task_id, working_set_path)
        minimum_entries.extend(
            item
            for item in working_set_entries(working_set)
            if item["path"] not in known_paths
        )
        working_set_status = {"available": True}
    except (RuleFailure, InputFailure) as exc:
        working_set_status = {"available": False, "reason": str(exc)}
    live_progress: dict[str, Any] | None = None
    if state["status"] in {"IMPLEMENTING", "IMPLEMENTED"}:
        progress_path = directory / "runtime" / "progress.json"
        if progress_path.is_file():
            try:
                progress = validate_progress(repo, task_id)
                live_progress = {
                    "available": True,
                    "path": progress_path.relative_to(repo).as_posix(),
                    "value": progress,
                }
            except (RuleFailure, InputFailure) as exc:
                live_progress = {
                    "available": False,
                    "path": progress_path.relative_to(repo).as_posix(),
                    "reason": str(exc),
                }
    return {
        "message": f"recovered {task_id} at {state['status']} without chat history",
        "task": {
            "task_id": task_id,
            "work_item_revision": state["current_revision"],
            "title": work_item["title"],
            "rigor": state["rigor"],
        },
        "state": {
            "status": state["status"],
            "blocker": blocker,
            "last_event": {
                "sequence": last_event["sequence"],
                "event": last_event["event"],
                "from": last_event["from"],
                "to": last_event["to"],
            },
        },
        "recommended_next_action": recommended_action(state),
        "live_implementation_progress": live_progress,
        "minimum_working_set": {
            "path": str(working_set_path),
            **working_set_status,
            "entries": minimum_entries,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: recover(args.repo.resolve(), args.task_id), args.json)


if __name__ == "__main__":
    sys.exit(main())
