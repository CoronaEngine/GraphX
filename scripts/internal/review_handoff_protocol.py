"""Validation of frozen Polaris Reviewer handoff packages."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_protocol import load_registered, state_reference
from .polaris_core import (
    RuleFailure,
    current_work_item_path,
    directory_sha256,
    file_sha256,
    validate_json_file,
)
from .review_response_protocol import validate_review_response
from .task_layout import evidence_dir
from .task_location_protocol import logical_repo_path, resolve_repo_reference


MAX_REVIEW_ATTEMPTS = 3
INDEPENDENT_ISOLATION_MODES = {"fresh_session", "isolated_reviewer_agent"}
REQUIRED_PACKAGE_ROLES = {
    "project_rules",
    "work_item",
    "plan",
    "working_set",
    "implementation",
    "knowledge_delta",
    "evidence",
}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "TODO"


def validate_handoff(
    repo: Path,
    root: Path,
    directory: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    handoff, _ = load_registered(
        root,
        directory,
        state,
        "review_handoff",
        "review-handoff.schema.json",
    )
    implementation, _ = load_registered(
        root,
        directory,
        state,
        "implementation",
        "implementation.schema.json",
    )
    subject = state.get("subject")
    if not isinstance(subject, dict):
        raise RuleFailure("review handoff requires a frozen subject")
    if (
        handoff["task_id"] != state["task_id"]
        or handoff["work_item_revision"] != state["current_revision"]
        or handoff["rigor"] != state["rigor"]
        or handoff["artifact_attempt"] != implementation["artifact_attempt"]
        or handoff["implementer_session_id"]
        != implementation["implementer_session_id"]
    ):
        raise RuleFailure("review handoff identity does not match task and Implementation")
    if not _nonempty(handoff["implementer_session_id"]):
        raise RuleFailure("review handoff requires a real implementer session ID")
    if handoff["artifact_attempt"] > MAX_REVIEW_ATTEMPTS:
        raise RuleFailure("Review attempt limit exceeded; escalate to the Decision Owner")
    if (
        handoff["subject_base_commit"] != subject["base_commit"]
        or handoff["subject_head_commit"] != subject["head_commit"]
        or handoff["subject_diff_hash"] != subject["diff_hash"]
    ):
        raise RuleFailure("review handoff targets the wrong subject")
    if state["rigor"] in {"R1", "R2"}:
        if handoff["required_isolation"] not in INDEPENDENT_ISOLATION_MODES:
            raise RuleFailure("R1/R2 handoff must require a fresh or isolated Reviewer")
    elif handoff["required_isolation"] not in (
        INDEPENDENT_ISOLATION_MODES | {"r0_isolated_same_session"}
    ):
        raise RuleFailure("invalid R0 Review isolation mode")

    prior_reference = state_reference(directory, state, "prior_review", required=False)
    if handoff["previous_review"] != prior_reference:
        raise RuleFailure("review handoff previous_review does not match task state")
    if prior_reference is not None:
        prior = validate_json_file(
            directory / prior_reference["path"],
            root / "schemas" / "review.schema.json",
        )
        if handoff["artifact_attempt"] != prior["artifact_attempt"] + 1:
            raise RuleFailure("review handoff attempt must immediately follow prior Review")
        if prior["verdict"] == "REJECT":
            validate_review_response(root, directory, state, implementation)
        elif state_reference(
            directory, state, "review_response", required=False
        ) is not None:
            raise RuleFailure("an accepted prior Review must not have an author response")
    elif state_reference(directory, state, "review_response", required=False) is not None:
        raise RuleFailure("initial Review handoff cannot contain a review_response")

    items_by_role: dict[str, list[dict[str, Any]]] = {}
    for item in handoff["package"]:
        items_by_role.setdefault(item["role"], []).append(item)
    roles = set(items_by_role)
    required_roles = set(REQUIRED_PACKAGE_ROLES)
    if state["artifacts"].get("plan_decisions") is not None:
        required_roles.add("plan_decisions")
    missing_roles = required_roles - roles
    if missing_roles:
        raise RuleFailure(f"review handoff lacks package roles: {sorted(missing_roles)}")
    duplicate_roles = {
        role
        for role, items in items_by_role.items()
        if role != "working_set_reference" and len(items) != 1
    }
    if duplicate_roles:
        raise RuleFailure(f"review handoff duplicates singleton roles: {sorted(duplicate_roles)}")

    plan_reference = state_reference(directory, state, "plan")
    working_set_reference = state_reference(directory, state, "working_set")
    implementation_reference = state_reference(directory, state, "implementation")
    knowledge_reference = state_reference(directory, state, "knowledge_delta")
    assert all(
        reference is not None
        for reference in (
            plan_reference,
            working_set_reference,
            implementation_reference,
            knowledge_reference,
        )
    )
    expected_paths = {
        "project_rules": "AGENTS.md",
        "work_item": logical_repo_path(
            repo, current_work_item_path(directory, state["current_revision"])
        ),
        "plan": logical_repo_path(repo, directory / plan_reference["path"]),
        "working_set": logical_repo_path(
            repo, directory / working_set_reference["path"]
        ),
        "implementation": logical_repo_path(
            repo, directory / implementation_reference["path"]
        ),
        "knowledge_delta": logical_repo_path(
            repo, directory / knowledge_reference["path"]
        ),
        "evidence": logical_repo_path(
            repo, evidence_dir(directory, state["current_revision"])
        ),
    }
    plan_decisions_reference = state_reference(
        directory, state, "plan_decisions", required=False
    )
    if plan_decisions_reference is not None:
        expected_paths["plan_decisions"] = logical_repo_path(
            repo, directory / plan_decisions_reference["path"]
        )
    elif "plan_decisions" in items_by_role:
        raise RuleFailure("legacy review handoff must not invent Plan decisions")
    if prior_reference is not None:
        expected_paths["previous_review"] = logical_repo_path(
            repo, directory / prior_reference["path"]
        )
        response_reference = state_reference(
            directory, state, "review_response", required=False
        )
        if response_reference is not None:
            expected_paths["review_response"] = logical_repo_path(
                repo, directory / response_reference["path"]
            )
    for role, expected_path in expected_paths.items():
        entries = items_by_role.get(role, [])
        if len(entries) != 1 or entries[0]["path"] != expected_path:
            raise RuleFailure(f"review handoff role {role} targets the wrong path")

    for item in handoff["package"]:
        path = resolve_repo_reference(repo, item["path"])
        if item["kind"] == "file":
            if not path.is_file() or item["sha256"] != file_sha256(path):
                raise RuleFailure(f"review package file changed or is missing: {item['path']}")
        elif not path.is_dir() or item["sha256"] != directory_sha256(path):
            raise RuleFailure(f"review package directory changed or is missing: {item['path']}")
    return handoff
