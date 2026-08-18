"""Deterministic workflow gate checks for Polaris transitions."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .implementation_protocol import validate_handoff as validate_implementation_handoff
from .code_intelligence_protocol import record_reference
from .polaris_core import (
    RuleFailure,
    current_work_item_path,
    file_sha256,
    full_commit,
    subject_diff_hash,
    validate_json_file,
)
from .review_protocol import validate_handoff, validate_review, validate_review_response
from .plan_decision_protocol import validate_plan_decisions
from .working_set_protocol import validate_working_set
from .validation_protocol import (
    validate_acceptance_coverage,
    validate_acceptance_ids,
    validate_validation_identity,
)


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
        raise RuleFailure(f"artifact {name} changed after it was registered")
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
        validate_acceptance_ids(work_item)
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
        artifact_file(directory, state, "plan_decisions")
        validate_plan_decisions(repo, root, directory, state, True)
        working_set_path = artifact_file(directory, state, "working_set")
        validate_working_set(repo, state["task_id"], working_set_path)
    elif gate == "implementation_start_ready":
        if state["rigor"] == "R2":
            artifact_file(directory, state, "pre_approval")
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
        intelligence = record_reference(
            repo, state["task_id"], implementation.get("code_intelligence")
        )
        if intelligence and (
            intelligence["stage"] != "IMPLEMENTATION"
            or intelligence["artifact_attempt"] != implementation["artifact_attempt"]
            or intelligence["target"]["base_commit"]
            != implementation["subject_base_commit"]
            or intelligence["target"]["head_commit"]
            != implementation["subject_head_commit"]
            or intelligence["target"]["diff_hash"]
            != implementation["subject_diff_hash"]
        ):
            raise RuleFailure("Implementation Code Intelligence record targets the wrong subject")
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
        intelligence = record_reference(
            repo, state["task_id"], knowledge.get("code_intelligence")
        )
        if intelligence and (
            intelligence["stage"] != "DOCUMENTATION_SYNC"
            or intelligence["artifact_attempt"] != knowledge["artifact_attempt"]
            or intelligence["target"]["base_commit"]
            != knowledge["subject_base_commit"]
            or intelligence["target"]["head_commit"]
            != knowledge["subject_head_commit"]
            or intelligence["target"]["diff_hash"]
            != knowledge["subject_diff_hash"]
        ):
            raise RuleFailure("Knowledge Delta Code Intelligence record targets the wrong subject")
        from check_docs import check as check_documentation

        check_documentation(
            repo,
            state["task_id"],
            knowledge_path,
            state["subject"]["base_commit"],
            state["subject"]["head_commit"],
        )
    elif gate == "review_start_ready":
        check_gate(
            repo, root, directory, state, "implementation_ready", blocker, workflow
        )
        check_gate(repo, root, directory, state, "docs_ready", blocker, workflow)
        check_gate(
            repo, root, directory, state, "review_package_ready", blocker, workflow
        )
    elif gate == "review_package_ready":
        artifact_file(directory, state, "knowledge_delta")
        check_subject(repo, state.get("subject"))
        validate_handoff(repo, root, directory, state)
    elif gate == "review_accepted":
        names = ["review"]
        if any(
            work_item["risk_flags"].get(flag, False)
            for flag in workflow.get("two_reviewer_risk_flags", [])
        ):
            names.append("review_2")
        reviews = [load_review(root, directory, state, name) for name in names]
        reviewer_ids: set[str] = set()
        for review in reviews:
            if review["verdict"] != "ACCEPT":
                raise RuleFailure("Review verdict must be ACCEPT")
            validate_review(repo, root, directory, state, review, work_item)
            if review["reviewer_session_id"] in reviewer_ids:
                raise RuleFailure("required Reviews must come from distinct Reviewer sessions")
            reviewer_ids.add(review["reviewer_session_id"])
    elif gate == "review_rejected":
        requires_two = any(
            work_item["risk_flags"].get(flag, False)
            for flag in workflow.get("two_reviewer_risk_flags", [])
        )
        names = ["review"]
        if requires_two and "review_2" in state["artifacts"]:
            names.append("review_2")
        elif not requires_two and "review_2" in state["artifacts"]:
            raise RuleFailure("review_2 is reserved for high-risk two-Reviewer flow")
        reviews = [load_review(root, directory, state, name) for name in names]
        reviewer_ids: set[str] = set()
        for review in reviews:
            validate_review(repo, root, directory, state, review, work_item)
            if review["reviewer_session_id"] in reviewer_ids:
                raise RuleFailure("required Reviews must come from distinct Reviewer sessions")
            reviewer_ids.add(review["reviewer_session_id"])
        verdicts = [review["verdict"] for review in reviews]
        allowed = [["REJECT"]]
        if requires_two:
            allowed.append(["ACCEPT", "REJECT"])
        if verdicts not in allowed:
            raise RuleFailure(
                "Review rejection requires slot 1 REJECT or slot 1 ACCEPT followed by "
                "slot 2 REJECT"
            )
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
    elif gate in {"validation_passed", "validation_passed_and_closure_ready"}:
        if gate == "validation_passed" and state["rigor"] != "R2":
            raise RuleFailure("R0/R1 must use PASS_AND_CLOSE")
        if gate == "validation_passed_and_closure_ready" and state["rigor"] == "R2":
            raise RuleFailure("R2 must pass Validation before final approval and closure")
        validation = load_validation(root, directory, state)
        if validation["verdict"] != "PASS":
            raise RuleFailure("Validation verdict must be PASS")
        validate_acceptance_coverage(work_item, validation)
        implementation = validate_json_file(
            artifact_file(directory, state, "implementation"),
            root / "schemas" / "implementation.schema.json",
        )
        validate_validation_identity(
            state, validation, implementation["artifact_attempt"]
        )
        if gate == "validation_passed_and_closure_ready":
            from validate_task import validate_projection

            candidate = copy.deepcopy(state)
            candidate["status"] = "CLOSED"
            validate_projection(repo, state["task_id"], candidate)
    elif gate in {"validation_failed_implementation", "validation_failed_plan"}:
        validation = load_validation(root, directory, state)
        if validation["verdict"] != "FAIL":
            raise RuleFailure("failure transition requires a FAIL Validation")
        implementation = validate_json_file(
            artifact_file(directory, state, "implementation"),
            root / "schemas" / "implementation.schema.json",
        )
        validate_validation_identity(
            state, validation, implementation["artifact_attempt"]
        )
    elif gate == "closure_ready":
        if state["rigor"] != "R2":
            raise RuleFailure("only R2 closes from VERIFIED")
        artifact_file(directory, state, "final_approval")
        from validate_task import validate_projection

        candidate = copy.deepcopy(state)
        candidate["status"] = "CLOSED"
        validate_projection(repo, state["task_id"], candidate)
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
