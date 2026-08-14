#!/usr/bin/env python3
"""Apply one legal Polaris workflow transition and append its event."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

from polaris_core import (
    RuleFailure,
    acquire_lock,
    append_jsonl,
    current_work_item_path,
    file_sha256,
    full_commit,
    protocol_root,
    read_json,
    rebuild_state_value,
    release_lock,
    run_main,
    subject_diff_hash,
    task_dir,
    utc_now,
    validate_json_file,
    write_json_atomic,
)
from recovery_protocol import refresh_project_index
from implementation_protocol import (
    step_results,
    validate_handoff as validate_implementation_handoff,
    validate_progress,
)
from review_protocol import (
    MAX_REVIEW_ATTEMPTS,
    normalized_reference,
    validate_handoff,
    validate_review,
    validate_review_response,
)
from working_set_protocol import validate_working_set


def parse_artifacts(values: list[str], directory: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for value in values:
        if "=" not in value:
            raise RuleFailure(f"artifact must be NAME=PATH: {value}")
        name, raw_path = value.split("=", 1)
        path = Path(raw_path)
        if not path.is_absolute():
            path = directory / path
        path = path.resolve()
        try:
            relative = path.relative_to(directory.resolve())
        except ValueError as exc:
            raise RuleFailure(f"artifact must be inside the task directory: {path}") from exc
        if not path.is_file():
            raise RuleFailure(f"artifact does not exist: {path}")
        result[name] = {"path": relative.as_posix(), "sha256": file_sha256(path)}
    return result


def artifact_file(directory: Path, state: dict[str, Any], name: str) -> Path:
    reference = state["artifacts"].get(name)
    if not reference:
        raise RuleFailure(f"gate requires artifact: {name}")
    raw_path = reference if isinstance(reference, str) else reference.get("path")
    if not isinstance(raw_path, str):
        raise RuleFailure(f"invalid artifact reference: {name}")
    path = directory / raw_path
    if not path.is_file():
        raise RuleFailure(f"artifact does not exist: {path}")
    if isinstance(reference, dict) and reference.get("sha256") != file_sha256(path):
        raise RuleFailure(f"artifact content changed after registration: {name}")
    return path


def load_review(
    root: Path, directory: Path, state: dict[str, Any], name: str = "review"
) -> dict[str, Any]:
    return validate_json_file(
        artifact_file(directory, state, name), root / "schemas" / "review.schema.json"
    )


def load_validation(root: Path, directory: Path, state: dict[str, Any]) -> dict[str, Any]:
    return validate_json_file(
        artifact_file(directory, state, "validation"),
        root / "schemas" / "validation.schema.json",
    )


def check_subject(repo: Path, subject: Any) -> None:
    if not isinstance(subject, dict):
        raise RuleFailure("gate requires --subject-base and --subject-head")
    base = full_commit(repo, subject.get("base_commit", ""))
    head = full_commit(repo, subject.get("head_commit", ""))
    actual = subject_diff_hash(repo, base, head)
    if subject.get("diff_hash") != actual:
        raise RuleFailure("subject diff hash does not match Git")


def check_gate(
    repo: Path,
    root: Path,
    directory: Path,
    state: dict[str, Any],
    gate: str,
    blocker: dict[str, str] | None,
    workflow: dict[str, Any],
) -> None:
    revision = state["current_revision"]
    work_item_path = current_work_item_path(directory, revision)
    work_item = validate_json_file(work_item_path, root / "schemas" / "work-item.schema.json")
    if work_item["id"] != state["task_id"] or work_item["revision"] != revision:
        raise RuleFailure("Work Item does not match current task revision")

    if gate == "work_item_ready":
        required_text = [work_item["title"], work_item["goal"], work_item["motivation"]]
        if any(not value.strip() or value.strip() == "TODO" for value in required_text):
            raise RuleFailure("Work Item still contains unresolved required text")
        if not work_item["scope"]["in"] or not work_item["acceptance"]:
            raise RuleFailure("Work Item requires non-empty in-scope and acceptance entries")
        for criterion in work_item["acceptance"]:
            for field in ("statement", "evidence"):
                value = criterion[field].strip()
                if not value or value.upper() == "TODO":
                    raise RuleFailure(
                        f"Acceptance {criterion['id']} has unresolved {field}"
                    )
        if work_item["known_unknowns"]:
            raise RuleFailure("Work Item has unresolved known_unknowns")
        dispatch = work_item.get("review_dispatch")
        if not isinstance(dispatch, dict) or not dispatch.get("authorized"):
            raise RuleFailure("Work Item requires explicit Review task dispatch authorization")
        implementation_dispatch = work_item.get("implementation_dispatch")
        if not isinstance(implementation_dispatch, dict) or not implementation_dispatch.get(
            "authorized"
        ):
            raise RuleFailure(
                "Work Item requires explicit Implementation task dispatch authorization"
            )
        if any(work_item["risk_flags"].values()) and work_item["rigor"] != "R2":
            raise RuleFailure("true risk flags require rigor R2")
        full_commit(repo, work_item["base_commit"])
    elif gate == "plan_ready":
        artifact_file(directory, state, "plan")
        working_set_path = artifact_file(directory, state, "working_set")
        validate_working_set(repo, state["task_id"], working_set_path)
    elif gate == "implementation_approved":
        if state["rigor"] == "R2":
            artifact_file(directory, state, "pre_approval")
    elif gate == "implementation_handoff_ready":
        validate_implementation_handoff(repo, root, directory, state, True)
    elif gate == "implementation_ready":
        handoff, handoff_reference = validate_implementation_handoff(
            repo, root, directory, state
        )
        implementation = validate_json_file(
            artifact_file(directory, state, "implementation"),
            root / "schemas" / "implementation.schema.json",
        )
        if not implementation["implementer_session_id"].strip() or implementation[
            "implementer_session_id"
        ].strip() == "TODO":
            raise RuleFailure("Implementation requires a real implementer session ID")
        check_subject(repo, state.get("subject"))
        if (
            implementation["work_item_revision"] != revision
            or implementation["task_id"] != state["task_id"]
            or implementation["artifact_attempt"] != handoff["artifact_attempt"]
            or implementation["implementation_handoff_path"]
            != handoff_reference["path"]
            or implementation["implementation_handoff_sha256"]
            != handoff_reference["sha256"]
            or implementation["subject_base_commit"] != state["subject"]["base_commit"]
            or implementation["subject_head_commit"] != state["subject"]["head_commit"]
            or implementation["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("Implementation targets the wrong revision or subject")
        progress = validate_progress(repo, state["task_id"])
        if progress["phase"] != "CHECKPOINTING":
            raise RuleFailure(
                "FINISH_IMPLEMENTATION requires CHECKPOINTING live progress"
            )
        if progress["implementer_session_id"] != implementation["implementer_session_id"]:
            raise RuleFailure("Implementation and live progress have different sessions")
        if implementation["step_results"] != step_results(progress):
            raise RuleFailure("Implementation step_results do not match live progress")
        validate_review_response(root, directory, state, implementation)
    elif gate == "docs_ready":
        knowledge_path = artifact_file(directory, state, "knowledge_delta")
        knowledge = validate_json_file(
            knowledge_path,
            root / "schemas" / "knowledge-delta.schema.json",
        )
        if any(entry["status"] == "STALE" for entry in knowledge["entries"]):
            raise RuleFailure("Knowledge Delta contains unresolved STALE entries")
        check_subject(repo, state.get("subject"))
        if (
            knowledge["task_id"] != state["task_id"]
            or knowledge["work_item_revision"] != revision
            or knowledge["subject_base_commit"] != state["subject"]["base_commit"]
            or knowledge["subject_head_commit"] != state["subject"]["head_commit"]
            or knowledge["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("Knowledge Delta targets the wrong final documentation subject")
        from check_docs import check as check_documentation

        check_documentation(
            repo,
            state["task_id"],
            knowledge_path,
            state["subject"]["base_commit"],
            state["subject"]["head_commit"],
        )
    elif gate == "review_package_ready":
        artifact_file(directory, state, "knowledge_delta")
        check_subject(repo, state.get("subject"))
        validate_handoff(repo, root, directory, state)
    elif gate in {"review_accepted", "review_rejected"}:
        expected = "ACCEPT" if gate == "review_accepted" else "REJECT"
        names = ["review"]
        if expected == "ACCEPT" and any(
            work_item["risk_flags"].get(flag, False)
            for flag in workflow.get("two_reviewer_risk_flags", [])
        ):
            names.append("review_2")
        reviews = [load_review(root, directory, state, name) for name in names]
        reviewer_ids: set[str] = set()
        for review in reviews:
            if review["verdict"] != expected:
                raise RuleFailure(f"Review verdict must be {expected}")
            validate_review(repo, root, directory, state, review, work_item)
            if review["reviewer_session_id"] in reviewer_ids:
                raise RuleFailure("required Reviews must come from distinct Reviewer sessions")
            reviewer_ids.add(review["reviewer_session_id"])
    elif gate == "validation_ready":
        names = ["review"]
        if any(
            work_item["risk_flags"].get(flag, False)
            for flag in workflow.get("two_reviewer_risk_flags", [])
        ):
            names.append("review_2")
        for name in names:
            review = load_review(root, directory, state, name)
            if review["verdict"] != "ACCEPT":
                raise RuleFailure("Validation requires all mandated Reviews to ACCEPT")
            validate_review(repo, root, directory, state, review, work_item)
    elif gate == "validation_passed":
        validation = load_validation(root, directory, state)
        if validation["verdict"] != "PASS":
            raise RuleFailure("Validation verdict must be PASS")
        expected = {item["id"] for item in work_item["acceptance"]}
        actual = {
            item["acceptance_id"]
            for item in validation["acceptance_results"]
            if item["result"] == "PASS"
        }
        if expected != actual:
            raise RuleFailure("Validation must PASS every acceptance criterion")
        if validation["subject_diff_hash"] != state["subject"]["diff_hash"]:
            raise RuleFailure("Validation targets the wrong subject")
    elif gate in {"validation_failed_implementation", "validation_failed_plan"}:
        validation = load_validation(root, directory, state)
        if validation["verdict"] != "FAIL":
            raise RuleFailure("failure transition requires a FAIL Validation")
        if (
            validation["task_id"] != state["task_id"]
            or validation["work_item_revision"] != revision
            or validation["subject_base_commit"] != state["subject"]["base_commit"]
            or validation["subject_head_commit"] != state["subject"]["head_commit"]
            or validation["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("failed Validation targets the wrong revision or subject")
    elif gate == "closure_ready":
        result = validate_json_file(
            artifact_file(directory, state, "result"), root / "schemas" / "result.schema.json"
        )
        if result["subject_diff_hash"] != state["subject"]["diff_hash"]:
            raise RuleFailure("Result targets the wrong subject")
        if state["rigor"] == "R2":
            artifact_file(directory, state, "final_approval")
    elif gate == "new_revision_ready":
        validate_json_file(work_item_path, root / "schemas" / "work-item.schema.json")
    elif gate == "blocker_recorded":
        if not blocker or not all(blocker.get(key) for key in ("type", "reason", "decision_owner")):
            raise RuleFailure("BLOCK requires blocker type, reason, and decision owner")
    elif gate == "blocker_resolved":
        if state.get("blocked_from") is None:
            raise RuleFailure("BLOCKED state has no blocked_from state")
    elif gate == "human_cancelled":
        artifact_file(directory, state, "cancel_decision")


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
        state_path = directory / "state.json"
        state = read_json(state_path)
        if rebuild_state_value(directory / "events.jsonl") != state:
            raise RuleFailure("state.json differs from events.jsonl; rebuild before transition")
        workflow = read_json(repo / ".polaris" / "workflow.json")
        candidates = [item for item in workflow["transitions"] if item["event"] == event_name]
        if not candidates:
            raise RuleFailure(f"unknown workflow event: {event_name}")
        transition_rule = next(
            (item for item in candidates if state["status"] in item["from"]), None
        )
        if transition_rule is None:
            raise RuleFailure(f"{event_name} is illegal from {state['status']}")

        next_state = copy.deepcopy(state)
        submitted_artifacts = parse_artifacts(artifact_values, directory)
        next_state["artifacts"].update(submitted_artifacts)
        if revision is not None:
            if event_name != "NEW_REVISION" or revision != state["current_revision"] + 1:
                raise RuleFailure("--revision must be exactly current+1 for NEW_REVISION")
            next_state["current_revision"] = revision
            next_state["artifacts"] = {}
            next_state["subject"] = None
            work_item = read_json(current_work_item_path(directory, revision))
            next_state["rigor"] = work_item["rigor"]
        if subject_base or subject_head:
            if not subject_base or not subject_head:
                raise RuleFailure("provide both --subject-base and --subject-head")
            base = full_commit(repo, subject_base)
            head = full_commit(repo, subject_head)
            next_state["subject"] = {
                "base_commit": base,
                "head_commit": head,
                "diff_hash": subject_diff_hash(repo, base, head),
            }

        blocker = None
        if event_name == "BLOCK":
            blocker = {
                "type": blocker_type or "",
                "reason": reason or "",
                "decision_owner": decision_owner or "",
            }
            next_state["blocked_from"] = state["status"]
            next_state["blocker"] = blocker

        destination = transition_rule["to"]
        if destination == "$blocked_from":
            destination = state.get("blocked_from")
            if not destination:
                raise RuleFailure("cannot resolve BLOCKED state without blocked_from")

        check_gate(
            repo,
            root,
            directory,
            next_state,
            transition_rule["gate"],
            blocker,
            workflow,
        )

        if event_name == "REJECT_REVIEW":
            review = load_review(root, directory, next_state)
            prior_reference = normalized_reference(
                directory, next_state["artifacts"]["review"]
            )
            next_state["artifacts"]["prior_review"] = prior_reference
            max_attempts = transition_rule.get(
                "max_attempts", MAX_REVIEW_ATTEMPTS
            )
            if review["artifact_attempt"] >= max_attempts:
                destination = transition_rule.get("on_max_attempts_to", "BLOCKED")
                next_state["blocked_from"] = state["status"]
                next_state["blocker"] = {
                    "type": "review_dispute",
                    "reason": f"Review remained rejected after {max_attempts} attempts",
                    "decision_owner": "human",
                }

        if event_name == "REJECT_REVIEW" and destination == "IMPLEMENTING":
            for key in (
                "implementation",
                "implementation_handoff",
                "knowledge_delta",
                "review",
                "review_2",
                "review_handoff",
                "review_response",
                "validation",
                "result",
                "final_approval",
            ):
                next_state["artifacts"].pop(key, None)
            next_state["subject"] = None
        elif event_name == "REJECT_REVIEW":
            next_state["artifacts"].pop("review", None)
            next_state["artifacts"].pop("review_2", None)
            next_state["artifacts"].pop("review_handoff", None)
        elif event_name == "FAIL_IMPLEMENTATION":
            prior_review = next_state["artifacts"].get("review")
            if prior_review is not None:
                next_state["artifacts"]["prior_review"] = normalized_reference(
                    directory, prior_review
                )
            for key in (
                "implementation",
                "implementation_handoff",
                "knowledge_delta",
                "review",
                "review_2",
                "review_handoff",
                "review_response",
                "validation",
                "result",
                "final_approval",
            ):
                next_state["artifacts"].pop(key, None)
            next_state["subject"] = None
        elif event_name == "FAIL_PLAN":
            prior_review = next_state["artifacts"].get("review")
            next_state["artifacts"] = {
                key: value
                for key, value in next_state["artifacts"].items()
                if key in {"plan", "working_set"}
            }
            if prior_review is not None:
                next_state["artifacts"]["prior_review"] = normalized_reference(
                    directory, prior_review
                )
            next_state["subject"] = None
        elif event_name == "RESOLVE_BLOCK":
            next_state["blocked_from"] = None
            next_state["blocker"] = None

        next_state["status"] = destination
        next_state["sequence"] = state["sequence"] + 1
        event = {
            "sequence": next_state["sequence"],
            "timestamp": utc_now(),
            "event": event_name,
            "gate": transition_rule["gate"],
            "from": state["status"],
            "to": destination,
            "task_id": task_id,
            "polaris_version": next_state["polaris_version"],
            "workflow_version": next_state["workflow_version"],
            "current_revision": next_state["current_revision"],
            "rigor": next_state["rigor"],
            "blocked_from": next_state["blocked_from"],
            "blocker": next_state["blocker"],
            "artifacts": next_state["artifacts"],
            "subject": next_state["subject"],
            "submitted_artifacts": submitted_artifacts,
        }
        append_jsonl(directory / "events.jsonl", event)
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
