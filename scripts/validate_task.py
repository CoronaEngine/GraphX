#!/usr/bin/env python3
"""Validate one Polaris task and its current authority projection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from internal.polaris_core import (
    RuleFailure,
    current_work_item_path,
    file_sha256,
    full_commit,
    load_events_checked,
    protocol_root,
    read_json,
    rebuild_state_value,
    run_main,
    subject_diff_hash,
    task_dir,
    validate_json_file,
    validate_schema,
)
from internal.implementation_protocol import validate_handoff as validate_implementation_handoff
from internal.artifact_protocol import normalized_reference
from internal.code_intelligence_protocol import record_reference
from internal.review_protocol import validate_handoff, validate_review, validate_review_response
from internal.plan_decision_protocol import validate_plan_decisions
from internal.working_set_protocol import validate_working_set
from internal.task_layout import events_path, explorations_dir
from internal.task_layout import state_path as task_state_path


ORDER = [
    "DRAFT",
    "QUALIFIED",
    "PLANNED",
    "IMPLEMENTING",
    "REVIEWING",
    "VALIDATING",
    "VERIFIED",
    "CLOSED",
]


def at_least(status: str, threshold: str) -> bool:
    return status in ORDER and ORDER.index(status) >= ORDER.index(threshold)


def authority_status(state: dict[str, Any]) -> str:
    """Return the durable stage whose invariants a projection must satisfy."""
    status = state["status"]
    if status == "BLOCKED":
        blocked_from = state.get("blocked_from")
        return blocked_from if blocked_from in ORDER else "DRAFT"
    if status == "CANCELLED":
        return "DRAFT"
    return status


def artifact_path(directory: Path, reference: Any) -> Path:
    if isinstance(reference, str):
        return directory / reference
    if isinstance(reference, dict) and isinstance(reference.get("path"), str):
        return directory / reference["path"]
    raise RuleFailure(f"invalid artifact reference: {reference!r}")


def require_artifact(state: dict[str, Any], directory: Path, name: str) -> Path:
    if name not in state["artifacts"]:
        raise RuleFailure(f"state {state['status']} requires artifact: {name}")
    path = artifact_path(directory, state["artifacts"][name])
    if not path.is_file():
        raise RuleFailure(f"artifact {name} does not exist: {path}")
    reference = state["artifacts"][name]
    if isinstance(reference, dict) and reference.get("sha256") != file_sha256(path):
        raise RuleFailure(f"artifact {name} changed after it was registered")
    return path


def validate_projection(
    repo: Path, task_id: str, state: dict[str, Any]
) -> dict[str, Any]:
    """Validate a prospective authority projection without reading its event log."""
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state_errors = validate_schema(
        state, read_json(root / "schemas" / "task-state.schema.json")
    )
    if state_errors:
        raise RuleFailure("candidate task state failed schema validation:\n- " + "\n- ".join(state_errors))

    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    workflow = read_json(repo / ".polaris" / "workflow.json")
    if state["polaris_version"] != version:
        raise RuleFailure("task Polaris version does not match vendored protocol version")
    if state["workflow_version"] != workflow.get("workflow_version"):
        raise RuleFailure("task workflow version does not match project workflow version")

    work_item_path = current_work_item_path(directory, state["current_revision"])
    work_item = validate_json_file(work_item_path, root / "schemas" / "work-item.schema.json")
    if work_item["id"] != task_id or work_item["revision"] != state["current_revision"]:
        raise RuleFailure("current Work Item identity or revision does not match state")
    if work_item["rigor"] != state["rigor"]:
        raise RuleFailure("Work Item rigor does not match task state")
    if any(work_item["risk_flags"].values()) and state["rigor"] != "R2":
        raise RuleFailure("a true risk flag requires rigor R2")
    full_commit(repo, work_item["base_commit"])

    exploration_schema = root / "schemas" / "exploration.schema.json"
    for exploration_path in sorted(explorations_dir(directory).glob("EXP-*.json")):
        exploration = validate_json_file(exploration_path, exploration_schema)
        if exploration["scope"] != "task" or not exploration["task"].startswith(
            f"{task_id}@"
        ):
            raise RuleFailure(f"invalid task exploration scope: {exploration_path}")

    if "prior_review" in state["artifacts"]:
        prior_reference = normalized_reference(
            directory, state["artifacts"]["prior_review"]
        )
        validate_json_file(
            directory / prior_reference["path"], root / "schemas" / "review.schema.json"
        )

    projected_status = state["status"]
    status = authority_status(state)
    if at_least(status, "PLANNED"):
        require_artifact(state, directory, "plan")
        working_set_path = require_artifact(state, directory, "working_set")
        validate_working_set(repo, task_id, working_set_path)
        if "plan_decisions" in state["artifacts"]:
            require_artifact(state, directory, "plan_decisions")
            validate_plan_decisions(repo, root, directory, state, True)
    if at_least(status, "IMPLEMENTING"):
        validate_implementation_handoff(repo, root, directory, state)
        if state["rigor"] == "R2":
            require_artifact(state, directory, "pre_approval")
    if at_least(status, "REVIEWING"):
        handoff, handoff_reference = validate_implementation_handoff(
            repo, root, directory, state
        )
        implementation_path = require_artifact(state, directory, "implementation")
        implementation = validate_json_file(
            implementation_path, root / "schemas" / "implementation.schema.json"
        )
        if not implementation["implementer_session_id"].strip() or implementation[
            "implementer_session_id"
        ].strip() == "TODO":
            raise RuleFailure("Implementation requires a real implementer session ID")
        subject = state.get("subject")
        if not isinstance(subject, dict):
            raise RuleFailure(f"state {status} requires a frozen subject")
        required = {"base_commit", "head_commit", "diff_hash"}
        if not required.issubset(subject):
            raise RuleFailure("subject lacks base_commit, head_commit, or diff_hash")
        base = full_commit(repo, subject["base_commit"])
        head = full_commit(repo, subject["head_commit"])
        if subject_diff_hash(repo, base, head) != subject["diff_hash"]:
            raise RuleFailure("subject diff hash does not match Git commits")
        identity_mismatch = (
            implementation["task_id"] != task_id
            or implementation["work_item_revision"] != state["current_revision"]
            or implementation["artifact_attempt"] != handoff["artifact_attempt"]
            or implementation["implementation_handoff_path"]
            != handoff_reference["path"]
            or implementation["implementation_handoff_sha256"]
            != handoff_reference["sha256"]
            or implementation["subject_base_commit"] != subject["base_commit"]
            or implementation["subject_head_commit"] != subject["head_commit"]
            or implementation["subject_diff_hash"] != subject["diff_hash"]
        )
        if identity_mismatch:
            raise RuleFailure("Implementation artifact targets the wrong revision or subject")
        implementation_intelligence = record_reference(
            repo, task_id, implementation.get("code_intelligence")
        )
        if implementation_intelligence and (
            implementation_intelligence["stage"] != "IMPLEMENTATION"
            or implementation_intelligence["artifact_attempt"]
            != implementation["artifact_attempt"]
            or implementation_intelligence["target"]["base_commit"]
            != implementation["subject_base_commit"]
            or implementation_intelligence["target"]["head_commit"]
            != implementation["subject_head_commit"]
            or implementation_intelligence["target"]["diff_hash"]
            != implementation["subject_diff_hash"]
        ):
            raise RuleFailure("Implementation Code Intelligence record targets the wrong subject")
        validate_review_response(root, directory, state, implementation)

        knowledge_path = require_artifact(state, directory, "knowledge_delta")
        knowledge = validate_json_file(
            knowledge_path, root / "schemas" / "knowledge-delta.schema.json"
        )
        if knowledge["work_item_revision"] != state["current_revision"]:
            raise RuleFailure("Knowledge Delta targets an obsolete Work Item revision")
        if (
            knowledge["task_id"] != task_id
            or knowledge["artifact_attempt"] != implementation["artifact_attempt"]
            or knowledge["subject_base_commit"] != state["subject"]["base_commit"]
            or knowledge["subject_head_commit"] != state["subject"]["head_commit"]
            or knowledge["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("Knowledge Delta targets the wrong final documentation subject")
        if any(entry["status"] == "STALE" for entry in knowledge["entries"]):
            raise RuleFailure("Knowledge Delta contains unresolved STALE entries")
        knowledge_intelligence = record_reference(
            repo, task_id, knowledge.get("code_intelligence")
        )
        if knowledge_intelligence and (
            knowledge_intelligence["stage"] != "DOCUMENTATION_SYNC"
            or knowledge_intelligence["artifact_attempt"]
            != knowledge["artifact_attempt"]
            or knowledge_intelligence["target"]["base_commit"]
            != knowledge["subject_base_commit"]
            or knowledge_intelligence["target"]["head_commit"]
            != knowledge["subject_head_commit"]
            or knowledge_intelligence["target"]["diff_hash"]
            != knowledge["subject_diff_hash"]
        ):
            raise RuleFailure("Knowledge Delta Code Intelligence record targets the wrong subject")

        validate_handoff(repo, root, directory, state)
    if at_least(status, "VALIDATING"):
        review_names = ["review"]
        if any(
            work_item["risk_flags"].get(flag, False)
            for flag in workflow.get("two_reviewer_risk_flags", [])
        ):
            review_names.append("review_2")
        reviewer_ids: set[str] = set()
        for name in review_names:
            review_path = require_artifact(state, directory, name)
            review = validate_json_file(review_path, root / "schemas" / "review.schema.json")
            if review["verdict"] != "ACCEPT":
                raise RuleFailure("VALIDATING requires every mandated Review to ACCEPT")
            validate_review(repo, root, directory, state, review, work_item)
            if review["reviewer_session_id"] in reviewer_ids:
                raise RuleFailure("mandated Reviews must use distinct Reviewer sessions")
            reviewer_ids.add(review["reviewer_session_id"])
    if at_least(status, "VERIFIED"):
        validation_path = require_artifact(state, directory, "validation")
        validation = validate_json_file(
            validation_path, root / "schemas" / "validation.schema.json"
        )
        if validation["verdict"] != "PASS":
            raise RuleFailure("VERIFIED requires a PASS Validation")
        expected = {item["id"] for item in work_item["acceptance"]}
        actual = [
            item["acceptance_id"]
            for item in validation["acceptance_results"]
            if item["result"] == "PASS"
        ]
        if len(actual) != len(expected) or set(actual) != expected:
            raise RuleFailure("Validation does not PASS every acceptance criterion exactly once")
        if (
            validation["task_id"] != task_id
            or validation["work_item_revision"] != state["current_revision"]
            or validation["artifact_attempt"] != implementation["artifact_attempt"]
            or validation["subject_base_commit"] != state["subject"]["base_commit"]
            or validation["subject_head_commit"] != state["subject"]["head_commit"]
            or validation["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("Validation targets the wrong revision or subject")
    if status == "CLOSED":
        result_path = require_artifact(state, directory, "result")
        result = validate_json_file(result_path, root / "schemas" / "result.schema.json")
        if (
            result["task_id"] != task_id
            or result["work_item_revision"] != state["current_revision"]
            or result["subject_base_commit"] != state["subject"]["base_commit"]
            or result["subject_head_commit"] != state["subject"]["head_commit"]
            or result["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("Result targets the wrong revision or subject")
        if state["rigor"] == "R2":
            require_artifact(state, directory, "final_approval")

    return {
        "message": f"{task_id} is valid at {projected_status}",
        "task": task_id,
        "state": projected_status,
    }


def validate(repo: Path, task_id: str) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state_file = task_state_path(directory)
    state = validate_json_file(state_file, root / "schemas" / "task-state.schema.json")
    event_schema = read_json(root / "schemas" / "event.schema.json")
    for event in load_events_checked(events_path(directory)):
        errors = validate_schema(event, event_schema)
        if errors:
            raise RuleFailure(
                f"event {event.get('sequence')} failed schema validation:\n- "
                + "\n- ".join(errors)
            )
    rebuilt = rebuild_state_value(events_path(directory))
    if rebuilt != state:
        raise RuleFailure("state.json does not match the state reconstructed from events.jsonl")
    return validate_projection(repo, task_id, state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: validate(args.repo.resolve(), args.task_id), args.json)


if __name__ == "__main__":
    sys.exit(main())
