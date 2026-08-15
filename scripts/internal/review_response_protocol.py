"""Validation of author responses to a rejected Polaris Review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_protocol import state_reference
from .polaris_core import RuleFailure, validate_json_file


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "TODO"


def validate_review_response(
    root: Path,
    directory: Path,
    state: dict[str, Any],
    implementation: dict[str, Any],
) -> dict[str, Any] | None:
    prior_reference = state_reference(directory, state, "prior_review", required=False)
    response_reference = state_reference(
        directory, state, "review_response", required=False
    )
    if prior_reference is None:
        if response_reference is not None:
            raise RuleFailure("review_response is invalid without a prior rejected Review")
        return None
    prior = validate_json_file(
        directory / prior_reference["path"], root / "schemas" / "review.schema.json"
    )
    if prior["verdict"] != "REJECT":
        if response_reference is not None:
            raise RuleFailure("review_response may only target a rejected Review")
        return None
    if response_reference is None:
        raise RuleFailure("Review rework requires a review_response artifact")
    response = validate_json_file(
        directory / response_reference["path"],
        root / "schemas" / "review-response.schema.json",
    )
    expected_identity = (
        state["task_id"],
        state["current_revision"],
        implementation["artifact_attempt"],
        implementation["implementer_session_id"],
    )
    actual_identity = (
        response["task_id"],
        response["work_item_revision"],
        response["artifact_attempt"],
        response["implementer_session_id"],
    )
    if actual_identity != expected_identity:
        raise RuleFailure("review_response identity does not match the rework Implementation")
    if response["artifact_attempt"] != prior["artifact_attempt"] + 1:
        raise RuleFailure("review_response attempt must immediately follow the rejected Review")
    if (
        response["prior_review_path"] != prior_reference["path"]
        or response["prior_review_sha256"] != prior_reference["sha256"]
    ):
        raise RuleFailure("review_response does not bind the registered prior Review")
    if (
        response["subject_base_commit"] != implementation["subject_base_commit"]
        or response["subject_head_commit"] != implementation["subject_head_commit"]
        or response["subject_diff_hash"] != implementation["subject_diff_hash"]
    ):
        raise RuleFailure("review_response targets the wrong Implementation subject")

    expected_findings = {
        finding["id"] for finding in prior["findings"] if finding["status"] == "open"
    }
    responses = response["responses"]
    response_ids = [item["finding_id"] for item in responses]
    if len(response_ids) != len(set(response_ids)):
        raise RuleFailure("review_response contains duplicate finding IDs")
    if set(response_ids) != expected_findings:
        raise RuleFailure("review_response must answer every open prior finding exactly once")
    if any(
        not _nonempty(item["response"]) or not _nonempty(item["evidence"])
        for item in responses
    ):
        raise RuleFailure("every Review response requires a concrete response and evidence")
    return response
