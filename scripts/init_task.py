#!/usr/bin/env python3
"""Create a DRAFT task, immutable r001 Work Item template, and INIT event."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from polaris_core import (
    InputFailure,
    append_jsonl,
    full_commit,
    protocol_root,
    read_json,
    run_main,
    task_dir,
    utc_now,
    write_json_atomic,
)
from recovery_protocol import refresh_project_index


def initialize(repo: Path, task_id: str, rigor: str) -> dict[str, str]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    if directory.exists():
        raise InputFailure(f"task already exists: {directory}")
    project_path = repo / ".polaris" / "project.json"
    project = read_json(project_path)
    state = read_json(root / "templates" / "task" / "state.json")
    state.update({"task_id": task_id, "rigor": rigor})
    work_item = read_json(root / "templates" / "task" / "work-item.json")
    work_item.update({"id": task_id, "rigor": rigor, "base_commit": full_commit(repo)})

    (directory / "revisions").mkdir(parents=True)
    (directory / "implementations" / "r001").mkdir(parents=True)
    (directory / "knowledge" / "r001").mkdir(parents=True)
    (directory / "reviews" / "r001").mkdir(parents=True)
    (directory / "validations" / "r001").mkdir(parents=True)
    (directory / "results" / "r001").mkdir(parents=True)
    (directory / "evidence" / "r001").mkdir(parents=True)
    (directory / "explorations").mkdir(parents=True)
    write_json_atomic(directory / "state.json", state)
    write_json_atomic(directory / "revisions" / "work-item-r001.json", work_item)
    working_set = read_json(root / "templates" / "task" / "working-set.json")
    working_set["task_id"] = task_id
    write_json_atomic(directory / "working-set.json", working_set)
    shutil.copyfile(root / "templates" / "task" / "PLAN.md", directory / "PLAN.md")

    event = {
        "sequence": 0,
        "timestamp": utc_now(),
        "event": "INIT_TASK",
        "from": None,
        "to": "DRAFT",
        "task_id": task_id,
        "polaris_version": state["polaris_version"],
        "workflow_version": state["workflow_version"],
        "current_revision": 1,
        "rigor": rigor,
        "blocked_from": None,
        "blocker": None,
        "artifacts": {},
        "subject": None,
    }
    append_jsonl(directory / "events.jsonl", event)
    project.setdefault("active_tasks", []).append(task_id)
    write_json_atomic(project_path, project)
    refresh_project_index(repo)
    return {"message": f"initialized {task_id} at DRAFT", "task": task_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--rigor", choices=["R0", "R1", "R2"], default="R1")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: initialize(args.repo.resolve(), args.task_id, args.rigor), args.json
    )


if __name__ == "__main__":
    sys.exit(main())
