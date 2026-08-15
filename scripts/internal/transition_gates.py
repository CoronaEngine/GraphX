"""Deterministic workflow gate checks for Polaris transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .implementation_protocol import (
    step_results,
    validate_handoff as validate_implementation_handoff,
    validate_progress,
)
from .polaris_core import (
    RuleFailure,
    current_work_item_path,
    file_sha256,
    full_commit,
    subject_diff_hash,
    validate_json_file,
)
from .review_protocol import validate_handoff, validate_review, validate_review_response
from .working_set_protocol import validate_working_set


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
            or implementation["implementation_handoff_path"] != handoff_reference["path"]
            or implementation["implementation_handoff_sha256"] != handoff_reference["sha256"]
            or implementation["subject_base_commit"] != state["subject"]["base_commit"]
            or implementation["subject_head_commit"] != state["subject"]["head_commit"]
            or implementation["subject_diff_hash"] != state["subject"]["diff_hash"]
        ):
            raise RuleFailure("Implementation targets the wrong revision or subject")
        progress = validate_progress(repo, state["task_id"])
        if progress["phase"] != "CHECKPOINTING":
            raise RuleFailure("FINISH_IMPLEMENTATION requires CHECKPOINTING live progress")
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
            artifact_file(directory, state, "result"),
            root / "schemas" / "result.schema.json",
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
