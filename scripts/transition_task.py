#!/usr/bin/env python3
"""Apply one legal Polaris workflow transition and append its event."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from internal.polaris_core import (
    RuleFailure,
    acquire_lock,
    append_jsonl,
    protocol_root,
    read_json,
    rebuild_state_value,
    release_lock,
    run_main,
    task_dir,
    write_json_atomic,
)
from internal.recovery_protocol import refresh_project_index
from internal.task_layout import events_path as task_events_path
from internal.task_layout import state_path as task_state_path
from internal.transition_effects import (
    apply_event_effects,
    build_event,
    parse_artifacts,
    prepare_next_state,
    resolve_destination,
)
from internal.transition_gates import check_gate


def _transition_rule(
    workflow: dict[str, Any], event_name: str, status: str
) -> dict[str, Any]:
    candidates = [
        item for item in workflow["transitions"] if item["event"] == event_name
    ]
    if not candidates:
        raise RuleFailure(f"unknown workflow event: {event_name}")
    rule = next((item for item in candidates if status in item["from"]), None)
    if rule is None:
        raise RuleFailure(f"{event_name} is illegal from {status}")
    return rule


def transition(
    repo: Path,
    task_id: str,
    event_name: str,
    artifact_values: list[str],
    revision: int | None,
    subject_base: str | None,
    subject_head: str | None,
    blocker_type: str | None,
    reason: str | None,
    decision_owner: str | None,
) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    lock_path = directory / ".transition.lock"
    descriptor = acquire_lock(lock_path)
    try:
        state_path = task_state_path(directory)
        state = read_json(state_path)
        if rebuild_state_value(task_events_path(directory)) != state:
            raise RuleFailure("state.json differs from events.jsonl; rebuild before transition")

        workflow = read_json(repo / ".polaris" / "workflow.json")
        rule = _transition_rule(workflow, event_name, state["status"])
        next_state, submitted_artifacts, blocker = prepare_next_state(
            repo,
            directory,
            state,
            event_name,
            artifact_values,
            revision,
            subject_base,
            subject_head,
            blocker_type,
            reason,
            decision_owner,
        )
        destination = resolve_destination(rule, state)

        check_gate(
            repo,
            root,
            directory,
            next_state,
            rule["gate"],
            blocker,
            workflow,
        )
        destination = apply_event_effects(
            root,
            directory,
            state,
            next_state,
            event_name,
            destination,
            rule,
        )

        next_state["status"] = destination
        next_state["sequence"] = state["sequence"] + 1
        event = build_event(
            state,
            next_state,
            task_id,
            event_name,
            rule["gate"],
            destination,
            submitted_artifacts,
        )
        append_jsonl(task_events_path(directory), event)
        write_json_atomic(state_path, next_state)
        refresh_project_index(repo)
        return {
            "message": f"{task_id}: {state['status']} -> {destination}",
            "task": task_id,
            "from": state["status"],
            "to": destination,
            "sequence": next_state["sequence"],
        }
    finally:
        release_lock(lock_path, descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("event")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--revision", type=int)
    parser.add_argument("--subject-base")
    parser.add_argument("--subject-head")
    parser.add_argument("--blocker-type")
    parser.add_argument("--reason")
    parser.add_argument("--decision-owner")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: transition(
            args.repo.resolve(),
            args.task_id,
            args.event,
            args.artifact,
            args.revision,
            args.subject_base,
            args.subject_head,
            args.blocker_type,
            args.reason,
            args.decision_owner,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
