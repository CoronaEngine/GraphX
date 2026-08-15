#!/usr/bin/env python3
"""Create a DRAFT task, immutable r001 Work Item template, and INIT event."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from internal.polaris_core import (
    InputFailure,
    append_jsonl,
    full_commit,
    protocol_root,
    read_json,
    require_protocol_compatible,
    run_main,
    task_dir,
    utc_now,
    write_json_atomic,
)
from internal.recovery_protocol import refresh_project_index
from internal.plan_decision_protocol import empty_plan_decisions
from materialize_task_layout import materialize_task_directories
from internal.task_layout import (
    events_path,
    plan_decisions_path,
    plan_path,
    state_path,
    template_source_path,
    work_item_path,
    working_set_path,
)


def initialize(repo: Path, task_id: str, rigor: str) -> dict[str, str]:
    root = protocol_root(repo)
    require_protocol_compatible(repo)
    directory = task_dir(repo, task_id)
    if directory.exists():
        raise InputFailure(f"task already exists: {directory}")
    project_path = repo / ".polaris" / "project.json"
    project = read_json(project_path)
    state = read_json(template_source_path(root, "state"))
    state.update({"task_id": task_id, "rigor": rigor})
    work_item = read_json(template_source_path(root, "work_item"))
    work_item.update({"id": task_id, "rigor": rigor, "base_commit": full_commit(repo)})

    materialize_task_directories(directory, 1)
    write_json_atomic(state_path(directory), state)
    write_json_atomic(work_item_path(directory, 1), work_item)
    working_set = read_json(template_source_path(root, "working_set"))
    working_set["task_id"] = task_id
    write_json_atomic(working_set_path(directory), working_set)
    shutil.copyfile(template_source_path(root, "plan"), plan_path(directory))
    write_json_atomic(
        plan_decisions_path(directory),
        empty_plan_decisions(task_id, 1, plan_path(directory)),
    )

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
    append_jsonl(events_path(directory), event)
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
