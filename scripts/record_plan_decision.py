#!/usr/bin/env python3
"""Record one Human selection and bind it to the current Plan decision register."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from internal.path_security import confined_target
from internal.plan_decision_protocol import validate_plan_decisions
from internal.polaris_core import (
    InputFailure,
    RuleFailure,
    acquire_lock,
    file_sha256,
    protocol_root,
    read_json,
    release_lock,
    require_protocol_compatible,
    run_main,
    task_dir,
    utc_now,
    validate_json_file,
    write_json_atomic,
)
from internal.task_layout import plan_decisions_path, plan_path, state_path


def _next_decision_path(repo: Path) -> Path:
    decisions_directory = confined_target(
        repo, repo / ".polaris" / "decisions", "decision directory"
    )
    if not decisions_directory.is_dir():
        raise InputFailure(f"missing decision directory: {decisions_directory}")
    highest = 0
    for path in decisions_directory.iterdir():
        if path.is_symlink():
            raise RuleFailure(f"decision directory must not contain symlinks: {path}")
        match = re.fullmatch(r"CD-([0-9]{4})\.json", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    if highest >= 9999:
        raise RuleFailure("Plan decision authority ID space is exhausted")
    return decisions_directory / f"CD-{highest + 1:04d}.json"


def _record(
    repo: Path,
    task_id: str,
    plan_decision_id: str,
    option_id: str,
    approved_by: str,
) -> dict[str, str]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    require_protocol_compatible(repo, state)
    blocker = state.get("blocker")
    if (
        state["status"] != "BLOCKED"
        or not isinstance(blocker, dict)
        or blocker.get("type") != "plan_decision"
        or blocker.get("decision_owner") != "human"
    ):
        raise RuleFailure("Plan selections may be recorded only at a Human plan_decision block")
    if not approved_by.strip():
        raise InputFailure("--approved-by must identify the Human decision owner")

    plan_file = confined_target(repo, plan_path(directory), "Plan")
    register_file = confined_target(
        repo, plan_decisions_path(directory), "Plan decision register"
    )
    register = validate_json_file(
        register_file, root / "schemas" / "plan-decisions.schema.json"
    )
    if (
        register["task_id"] != task_id
        or register["work_item_revision"] != state["current_revision"]
        or register["plan"]
        != {"path": plan_file.name, "sha256": file_sha256(plan_file)}
    ):
        raise RuleFailure("Plan decision register does not bind the current task and Plan")
    projected_state = dict(state)
    projected_state["artifacts"] = {
        **state["artifacts"],
        "plan": {"path": plan_file.name, "sha256": file_sha256(plan_file)},
        "plan_decisions": {
            "path": register_file.name,
            "sha256": file_sha256(register_file),
        },
    }
    validate_plan_decisions(repo, root, directory, projected_state, False)
    matches = [
        decision
        for decision in register["decisions"]
        if decision["decision_id"] == plan_decision_id
    ]
    if len(matches) != 1:
        raise RuleFailure(f"unknown or duplicate Plan decision: {plan_decision_id}")
    decision = matches[0]
    if decision["status"] != "PENDING" or decision["resolution"] is not None:
        raise RuleFailure(f"Plan decision is not pending: {plan_decision_id}")
    option_ids = {option["option_id"] for option in decision["options"]}
    if option_id not in option_ids:
        raise RuleFailure(f"unknown option for {plan_decision_id}: {option_id}")

    authority_path = _next_decision_path(repo)
    if authority_path.exists():
        raise RuleFailure(f"decision authority already exists: {authority_path}")
    authority = {
        "decision_id": authority_path.stem,
        "task_id": task_id,
        "plan_decision_id": plan_decision_id,
        "approved_by": approved_by.strip(),
        "approved_at": utc_now(),
        "approval_gate": "plan_decision",
        "work_item_revision": state["current_revision"],
        "plan_hash": register["plan"]["sha256"],
        "subject_diff_hash": None,
        "decision": option_id,
    }
    write_json_atomic(authority_path, authority)
    validate_json_file(authority_path, root / "schemas" / "decision.schema.json")
    decision["status"] = "RESOLVED"
    decision["resolution"] = {
        "selected_option_id": option_id,
        "decision_path": authority_path.relative_to(repo).as_posix(),
        "decision_sha256": file_sha256(authority_path),
    }
    write_json_atomic(register_file, register)

    projected_state["artifacts"] = {
        **state["artifacts"],
        "plan": {"path": plan_file.name, "sha256": file_sha256(plan_file)},
        "plan_decisions": {
            "path": register_file.name,
            "sha256": file_sha256(register_file),
        },
    }
    validate_plan_decisions(repo, root, directory, projected_state, False)
    return {
        "message": f"recorded {plan_decision_id} as {option_id}",
        "decision": authority_path.relative_to(repo).as_posix(),
        "register": register_file.relative_to(repo).as_posix(),
    }


def record(
    repo: Path,
    task_id: str,
    plan_decision_id: str,
    option_id: str,
    approved_by: str,
) -> dict[str, str]:
    directory = task_dir(repo, task_id)
    lock_path = directory / ".transition.lock"
    descriptor = acquire_lock(lock_path)
    try:
        return _record(
            repo,
            task_id,
            plan_decision_id,
            option_id,
            approved_by,
        )
    finally:
        release_lock(lock_path, descriptor)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("plan_decision_id")
    parser.add_argument("option_id")
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: record(
            args.repo.resolve(),
            args.task_id,
            args.plan_decision_id,
            args.option_id,
            args.approved_by,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
