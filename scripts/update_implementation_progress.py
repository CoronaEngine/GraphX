#!/usr/bin/env python3
"""Atomically update the ignored live Implementation progress snapshot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from implementation_protocol import (
    validate_handoff,
    validate_progress,
    validate_progress_value,
)
from polaris_core import (
    RuleFailure,
    protocol_root,
    read_json,
    run_main,
    task_dir,
    utc_now,
    write_json_atomic,
)


PHASES = (
    "QUEUED",
    "IMPLEMENTING",
    "TESTING",
    "CHECKPOINTING",
    "DOCUMENTING",
    "COMPLETED",
    "BLOCKED",
    "FAILED",
)


def update(
    repo: Path,
    task_id: str,
    implementation_task: str,
    implementer_session_id: str,
    phase: str,
    current_action: str,
    completed_steps: list[str],
    remaining_steps: list[str],
    checks: list[str],
    blocker: str | None,
    user_action: str | None,
) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = read_json(directory / "state.json")
    if state["status"] not in {"IMPLEMENTING", "IMPLEMENTED"}:
        raise RuleFailure(
            "Implementation progress can only update while IMPLEMENTING or IMPLEMENTED"
        )
    handoff, reference = validate_handoff(repo, root, directory, state)
    progress_path = repo / handoff["progress_json_path"]
    if progress_path.exists():
        existing = read_json(progress_path)
        if existing.get("artifact_attempt") == handoff["artifact_attempt"]:
            previous_session = existing.get("implementer_session_id")
            if previous_session not in {"Pending", implementer_session_id}:
                raise RuleFailure("another Implementer session owns this progress attempt")
    progress = {
        "task_id": task_id,
        "work_item_revision": state["current_revision"],
        "artifact_attempt": handoff["artifact_attempt"],
        "implementation_task": implementation_task,
        "implementer_session_id": implementer_session_id,
        "handoff_path": f".polaris/tasks/{task_id}/{reference['path']}",
        "handoff_sha256": reference["sha256"],
        "phase": phase,
        "current_action": current_action,
        "completed_steps": completed_steps,
        "remaining_steps": remaining_steps,
        "checks": checks,
        "blocker": blocker,
        "user_action": user_action,
        "updated_at": utc_now(),
    }
    validate_progress_value(
        repo, root, task_id, state, handoff, reference, progress
    )
    write_json_atomic(progress_path, progress)
    validate_progress(repo, task_id)
    return {
        "message": f"updated {task_id} Implementation progress to {phase}",
        "progress": str(progress_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--implementation-task", required=True)
    parser.add_argument("--implementer-session-id", required=True)
    parser.add_argument("--phase", required=True, choices=PHASES)
    parser.add_argument("--current-action", required=True)
    parser.add_argument("--completed", action="append", default=[])
    parser.add_argument("--remaining", action="append", default=[])
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--blocker")
    parser.add_argument("--user-action")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: update(
            args.repo.resolve(),
            args.task_id,
            args.implementation_task,
            args.implementer_session_id,
            args.phase,
            args.current_action,
            args.completed,
            args.remaining,
            args.check,
            args.blocker,
            args.user_action,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
