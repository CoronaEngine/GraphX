#!/usr/bin/env python3
"""Validate one Polaris task and its current authority projection."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from polaris_core import (
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


ORDER = [
    "DRAFT",
    "QUALIFIED",
    "PLANNED",
    "IMPLEMENTING",
    "IMPLEMENTED",
    "DOCS_SYNCED",
    "REVIEWING",
    "REVIEWED",
    "VALIDATING",
    "VERIFIED",
    "CLOSED",
]


def at_least(status: str, threshold: str) -> bool:
    return status in ORDER and ORDER.index(status) >= ORDER.index(threshold)


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


def validate(repo: Path, task_id: str) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state_path = directory / "state.json"
    state = validate_json_file(state_path, root / "schemas" / "task-state.schema.json")
    event_schema = read_json(root / "schemas" / "event.schema.json")
    for event in load_events_checked(directory / "events.jsonl"):
        errors = validate_schema(event, event_schema)
        if errors:
            raise RuleFailure(
                f"event {event.get('sequence')} failed schema validation:\n- "
                + "\n- ".join(errors)
            )
    rebuilt = rebuild_state_value(directory / "events.jsonl")
    if rebuilt != state:
        raise RuleFailure("state.json does not match the state reconstructed from events.jsonl")

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

    status = state["status"]
    if at_least(status, "PLANNED"):
        require_artifact(state, directory, "plan")
        require_artifact(state, directory, "working_set")
    if at_least(status, "IMPLEMENTED"):
        implementation_path = require_artifact(state, directory, "implementation")
        implementation = validate_json_file(
            implementation_path, root / "schemas" / "implementation.schema.json"
        )
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
        if (
            implementation["work_item_revision"] != state["current_revision"]
            or implementation["subject_head_commit"] != subject["head_commit"]
            or implementation["subject_diff_hash"] != subject["diff_hash"]
        ):
            raise RuleFailure("Implementation artifact targets the wrong revision or subject")
    if at_least(status, "DOCS_SYNCED"):
        knowledge_path = require_artifact(state, directory, "knowledge_delta")
        knowledge = validate_json_file(
            knowledge_path, root / "schemas" / "knowledge-delta.schema.json"
        )
        if knowledge["work_item_revision"] != state["current_revision"]:
            raise RuleFailure("Knowledge Delta targets an obsolete Work Item revision")
        if any(entry["status"] == "STALE" for entry in knowledge["entries"]):
            raise RuleFailure("Knowledge Delta contains unresolved STALE entries")
    if at_least(status, "REVIEWED"):
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
                raise RuleFailure("REVIEWED requires every mandated Review to ACCEPT")
            if review["work_item_revision"] != state["current_revision"]:
                raise RuleFailure("Review targets an obsolete Work Item revision")
            subject = state["subject"]
            if (
                review["subject_head_commit"] != subject["head_commit"]
                or review["subject_diff_hash"] != subject["diff_hash"]
            ):
                raise RuleFailure("Review targets the wrong subject")
            if state["rigor"] in {"R1", "R2"} and review["implementer_session_id"] == review["reviewer_session_id"]:
                raise RuleFailure("R1/R2 Review must use an independent session")
            if review["reviewer_session_id"] in reviewer_ids:
                raise RuleFailure("mandated Reviews must use distinct Reviewer sessions")
            reviewer_ids.add(review["reviewer_session_id"])
            blocking = [
                finding
                for finding in review["findings"]
                if finding["status"] == "open"
                and finding["severity"] in {"critical", "high"}
            ]
            if blocking:
                raise RuleFailure("accepted Review still has blocking findings")
    if at_least(status, "VERIFIED"):
        validation_path = require_artifact(state, directory, "validation")
        validation = validate_json_file(
            validation_path, root / "schemas" / "validation.schema.json"
        )
        if validation["verdict"] != "PASS":
            raise RuleFailure("VERIFIED requires a PASS Validation")
        expected = {item["id"] for item in work_item["acceptance"]}
        actual = {
            item["acceptance_id"]
            for item in validation["acceptance_results"]
            if item["result"] == "PASS"
        }
        if actual != expected:
            raise RuleFailure("Validation does not PASS every acceptance criterion exactly once")
        if validation["subject_diff_hash"] != state["subject"]["diff_hash"]:
            raise RuleFailure("Validation targets the wrong subject")
    if status == "CLOSED":
        result_path = require_artifact(state, directory, "result")
        result = validate_json_file(result_path, root / "schemas" / "result.schema.json")
        if (
            result["work_item_revision"] != state["current_revision"]
            or result["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("Result targets the wrong revision or subject")
        if state["rigor"] == "R2":
            require_artifact(state, directory, "final_approval")

    return {"message": f"{task_id} is valid at {status}", "task": task_id, "state": status}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: validate(args.repo.resolve(), args.task_id), args.json)


if __name__ == "__main__":
    sys.exit(main())
