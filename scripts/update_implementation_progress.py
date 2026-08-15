#!/usr/bin/env python3
"""Apply a validated event to ignored live Implementation progress."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

from internal.implementation_protocol import validate_handoff, validate_progress_value
from internal.polaris_core import (
    InputFailure,
    RuleFailure,
    protocol_root,
    read_json,
    require_protocol_compatible,
    run_main,
    task_dir,
    utc_now,
    write_json_atomic,
)
from internal.task_layout import state_path, task_root_relative_path
from internal.task_location_protocol import resolve_repo_reference


PHASES = (
    "QUEUED", "IMPLEMENTING", "TESTING", "CHECKPOINTING",
    "DOCUMENTING", "COMPLETED", "BLOCKED", "FAILED",
)
EVENTS = (
    "INITIALIZE", "DEFINE_STEPS", "START_STEP", "COMPLETE_STEP",
    "BLOCK_STEP", "RESUME_STEP", "SKIP_STEP", "APPEND_STEP",
    "ADD_CHECK", "SET_PHASE",
)


def _base_progress(
    task_id: str,
    state: dict[str, Any],
    handoff: dict[str, Any],
    reference: dict[str, str],
    implementation_task: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "work_item_revision": state["current_revision"],
        "artifact_attempt": handoff["artifact_attempt"],
        "implementation_task": implementation_task,
        "implementer_session_id": "Pending",
        "handoff_path": (
            task_root_relative_path(task_id) / reference["path"]
        ).as_posix(),
        "handoff_sha256": reference["sha256"],
        "phase": "QUEUED",
        "current_step_id": None,
        "implementation_steps": [],
        "checks": [],
        "blocker": None,
        "user_action": None,
        "updated_at": utc_now(),
    }


def _step(progress: dict[str, Any], step_id: str | None) -> dict[str, Any]:
    if not step_id:
        raise InputFailure("this progress event requires --step-id")
    for item in progress["implementation_steps"]:
        if item["id"] == step_id:
            return item
    raise RuleFailure(f"unknown Implementation step: {step_id}")


def _first_pending(progress: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (item for item in progress["implementation_steps"] if item["status"] == "PENDING"),
        None,
    )


def _new_step(index: int, title: str | None, acceptance_ids: list[str]) -> dict[str, Any]:
    if not title or not title.strip():
        raise InputFailure("Implementation step title must be non-empty")
    if not acceptance_ids:
        raise InputFailure("Implementation step requires at least one acceptance ID")
    return {
        "id": f"STEP-{index:03d}",
        "title": title.strip(),
        "status": "PENDING",
        "acceptance_ids": list(dict.fromkeys(acceptance_ids)),
        "result": None,
    }


def update(
    repo: Path,
    task_id: str,
    implementation_task: str,
    implementer_session_id: str,
    event: str,
    *,
    phase: str | None = None,
    step_id: str | None = None,
    step_title: str | None = None,
    acceptance_ids: list[str] | None = None,
    result: str | None = None,
    defined_steps: list[dict[str, Any]] | None = None,
    checks: list[str] | None = None,
    blocker: str | None = None,
    user_action: str | None = None,
) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    require_protocol_compatible(repo, state)
    if state["status"] not in {"IMPLEMENTING", "IMPLEMENTED"}:
        raise RuleFailure("Implementation progress can only update while IMPLEMENTING or IMPLEMENTED")
    handoff, reference = validate_handoff(repo, root, directory, state)
    progress_path = resolve_repo_reference(repo, handoff["progress_json_path"])
    existing = read_json(progress_path) if progress_path.exists() else None

    if event == "INITIALIZE":
        if existing and existing.get("artifact_attempt") == handoff["artifact_attempt"]:
            validate_progress_value(repo, root, task_id, state, handoff, reference, existing)
            return {
                "message": f"reused {task_id} Implementation progress",
                "progress": str(progress_path),
                "value": existing,
            }
        progress = _base_progress(task_id, state, handoff, reference, implementation_task)
    else:
        if not existing or existing.get("artifact_attempt") != handoff["artifact_attempt"]:
            raise RuleFailure("INITIALIZE the current Implementation attempt first")
        validate_progress_value(repo, root, task_id, state, handoff, reference, existing)
        previous_session = existing["implementer_session_id"]
        if previous_session not in {"Pending", implementer_session_id}:
            raise RuleFailure("another Implementer session owns this progress attempt")
        if implementer_session_id == "Pending":
            raise RuleFailure("active progress requires a real Implementer session ID")
        progress = copy.deepcopy(existing)
        progress["implementer_session_id"] = implementer_session_id
        if progress["phase"] in {"COMPLETED", "FAILED"}:
            raise RuleFailure(f"{progress['phase']} progress is terminal")

        if event == "DEFINE_STEPS":
            if progress["phase"] != "QUEUED" or progress["implementation_steps"]:
                raise RuleFailure("Implementation steps may be defined only once after INITIALIZE")
            if not defined_steps:
                raise InputFailure("DEFINE_STEPS requires at least one step")
            progress["implementation_steps"] = [
                _new_step(index, item.get("title"), item.get("acceptance_ids", []))
                for index, item in enumerate(defined_steps, 1)
            ]
            progress["phase"] = "IMPLEMENTING"
        elif event == "APPEND_STEP":
            if progress["phase"] not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("APPEND_STEP is not allowed in the current phase")
            progress["implementation_steps"].append(
                _new_step(
                    len(progress["implementation_steps"]) + 1,
                    step_title,
                    acceptance_ids or [],
                )
            )
        elif event == "START_STEP":
            if progress["phase"] not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("START_STEP is not allowed in the current phase")
            if phase is not None and phase not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("START_STEP phase must be IMPLEMENTING or TESTING")
            if progress["current_step_id"] is not None:
                raise RuleFailure("finish or block the current step before starting another")
            target = _step(progress, step_id)
            if target is not _first_pending(progress):
                raise RuleFailure("only the first pending Implementation step may start")
            target["status"] = "IN_PROGRESS"
            progress["current_step_id"] = target["id"]
            progress["phase"] = phase or "IMPLEMENTING"
        elif event == "COMPLETE_STEP":
            if progress["phase"] not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("COMPLETE_STEP is not allowed in the current phase")
            if phase is not None and phase not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("COMPLETE_STEP phase must be IMPLEMENTING or TESTING")
            target = _step(progress, step_id)
            if target["status"] != "IN_PROGRESS" or progress["current_step_id"] != target["id"]:
                raise RuleFailure("only the current in-progress step may complete")
            if not result or not result.strip():
                raise InputFailure("COMPLETE_STEP requires a non-empty result")
            target["status"] = "COMPLETED"
            target["result"] = result.strip()
            progress["current_step_id"] = None
            if phase is not None:
                progress["phase"] = phase
        elif event == "SKIP_STEP":
            if progress["phase"] not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("SKIP_STEP is not allowed in the current phase")
            if progress["current_step_id"] is not None:
                raise RuleFailure("finish or block the current step before skipping another")
            target = _step(progress, step_id)
            if target is not _first_pending(progress):
                raise RuleFailure("only the first pending Implementation step may be skipped")
            if not result or not result.strip():
                raise InputFailure("SKIP_STEP requires a non-empty reason")
            target["status"] = "SKIPPED"
            target["result"] = result.strip()
        elif event == "BLOCK_STEP":
            if progress["phase"] not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("BLOCK_STEP is not allowed in the current phase")
            target = _step(progress, step_id)
            if target["status"] != "IN_PROGRESS" or progress["current_step_id"] != target["id"]:
                raise RuleFailure("only the current in-progress step may be blocked")
            if not blocker or not user_action:
                raise RuleFailure("BLOCK_STEP requires blocker and user_action")
            target["status"] = "BLOCKED"
            progress["phase"] = "BLOCKED"
            progress["blocker"] = blocker
            progress["user_action"] = user_action
        elif event == "RESUME_STEP":
            if progress["phase"] != "BLOCKED":
                raise RuleFailure("RESUME_STEP requires BLOCKED progress")
            if phase is not None and phase not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("RESUME_STEP phase must be IMPLEMENTING or TESTING")
            target = _step(progress, step_id)
            if target["status"] != "BLOCKED" or progress["current_step_id"] != target["id"]:
                raise RuleFailure("only the current blocked step may resume")
            target["status"] = "IN_PROGRESS"
            progress["phase"] = phase or "IMPLEMENTING"
            progress["blocker"] = None
            progress["user_action"] = None
        elif event == "ADD_CHECK":
            if progress["phase"] not in {
                "IMPLEMENTING", "TESTING", "CHECKPOINTING", "DOCUMENTING"
            }:
                raise RuleFailure("ADD_CHECK is not allowed in the current phase")
            if phase is not None and phase not in {"IMPLEMENTING", "TESTING"}:
                raise RuleFailure("ADD_CHECK may change phase only to IMPLEMENTING or TESTING")
            additions = checks or []
            if not additions or any(not item.strip() for item in additions):
                raise InputFailure("ADD_CHECK requires non-empty check results")
            progress["checks"].extend(item.strip() for item in additions)
            if phase is not None:
                progress["phase"] = phase
        elif event == "SET_PHASE":
            if phase is None:
                raise InputFailure("SET_PHASE requires --phase")
            allowed = {
                "IMPLEMENTING": {"IMPLEMENTING", "TESTING", "CHECKPOINTING", "FAILED"},
                "TESTING": {"IMPLEMENTING", "TESTING", "CHECKPOINTING", "FAILED"},
                "CHECKPOINTING": {"CHECKPOINTING", "DOCUMENTING", "FAILED"},
                "DOCUMENTING": {"DOCUMENTING", "COMPLETED", "FAILED"},
            }
            if phase not in allowed.get(progress["phase"], set()):
                raise RuleFailure(
                    f"SET_PHASE cannot move {progress['phase']} progress to {phase}"
                )
            if phase in {"DOCUMENTING", "COMPLETED"} and state["status"] != "IMPLEMENTED":
                raise RuleFailure(f"{phase} progress requires task state IMPLEMENTED")
            progress["phase"] = phase
            if phase == "FAILED":
                if not blocker or not user_action:
                    raise InputFailure("FAILED requires blocker and user_action")
                progress["blocker"] = blocker
                progress["user_action"] = user_action
        else:
            raise InputFailure(f"unknown progress event: {event}")

    progress["updated_at"] = utc_now()
    validate_progress_value(repo, root, task_id, state, handoff, reference, progress)
    write_json_atomic(progress_path, progress)
    return {
        "message": f"applied {event} to {task_id} Implementation progress",
        "progress": str(progress_path),
        "value": progress,
    }


def _parse_defined_step(value: str) -> dict[str, Any]:
    if "::" not in value:
        raise argparse.ArgumentTypeError("use TITLE::AC-01,AC-02")
    title, raw_ids = value.split("::", 1)
    ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
    if not title.strip() or not ids:
        raise argparse.ArgumentTypeError("use TITLE::AC-01,AC-02")
    return {"title": title.strip(), "acceptance_ids": ids}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--implementation-task", required=True)
    parser.add_argument("--implementer-session-id", required=True)
    parser.add_argument("--event", required=True, choices=EVENTS)
    parser.add_argument("--phase", choices=PHASES)
    parser.add_argument("--step-id")
    parser.add_argument("--step-title")
    parser.add_argument("--acceptance-id", action="append", default=[])
    parser.add_argument("--result")
    parser.add_argument("--define-step", action="append", type=_parse_defined_step, default=[])
    parser.add_argument("--check", action="append", default=[])
    parser.add_argument("--blocker")
    parser.add_argument("--user-action")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: update(
            args.repo.resolve(), args.task_id, args.implementation_task,
            args.implementer_session_id, args.event, phase=args.phase,
            step_id=args.step_id, step_title=args.step_title,
            acceptance_ids=args.acceptance_id, result=args.result,
            defined_steps=args.define_step, checks=args.check,
            blocker=args.blocker, user_action=args.user_action,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
