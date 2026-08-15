"""Deterministic Review and finding lifecycle checks.

The imported names are intentionally re-exported for compatibility with the
original single-module protocol API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from artifact_protocol import (
    artifact_path,
    load_registered,
    normalized_reference,
    state_reference,
)
from polaris_core import RuleFailure, validate_json_file
from review_handoff_protocol import (
    INDEPENDENT_ISOLATION_MODES,
    MAX_REVIEW_ATTEMPTS,
    REQUIRED_PACKAGE_ROLES,
    validate_handoff,
)
from review_response_protocol import validate_review_response


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip() != "TODO"


def validate_review(
    repo: Path,
    root: Path,
    directory: Path,
    state: dict[str, Any],
    review: dict[str, Any],
    work_item: dict[str, Any],
) -> None:
    handoff = validate_handoff(repo, root, directory, state)
    handoff_reference = state_reference(directory, state, "review_handoff")
    assert handoff_reference is not None
    subject = state["subject"]
    if (
        review["task_id"] != state["task_id"]
        or review["work_item_revision"] != state["current_revision"]
        or review["artifact_attempt"] != handoff["artifact_attempt"]
        or review["implementer_session_id"] != handoff["implementer_session_id"]
    ):
        raise RuleFailure("Review identity does not match its handoff")
    if not _nonempty(review["reviewer_session_id"]):
        raise RuleFailure("Review requires a real reviewer session ID")
    if (
        review["handoff_path"] != handoff_reference["path"]
        or review["handoff_sha256"] != handoff_reference["sha256"]
    ):
        raise RuleFailure("Review does not bind the registered handoff")
    if (
        review["subject_base_commit"] != subject["base_commit"]
        or review["subject_head_commit"] != subject["head_commit"]
        or review["subject_diff_hash"] != subject["diff_hash"]
    ):
        raise RuleFailure("Review targets the wrong subject")

    attestation = review["isolation_attestation"]
    if attestation["mode"] != handoff["required_isolation"]:
        raise RuleFailure("Reviewer isolation attestation does not satisfy the handoff")
    if not attestation["reviewed_from_handoff_only"]:
        raise RuleFailure("Reviewer must attest to using only the frozen handoff package")
    if (
        attestation["mode"] in INDEPENDENT_ISOLATION_MODES
        and attestation["chat_history_inherited"]
    ):
        raise RuleFailure("an independent Reviewer context cannot inherit implementation chat")
    if state["rigor"] in {"R1", "R2"}:
        if (
            attestation["mode"] not in INDEPENDENT_ISOLATION_MODES
            or attestation["chat_history_inherited"]
            or review["reviewer_session_id"] == review["implementer_session_id"]
        ):
            raise RuleFailure("R1/R2 Review lacks independent-session attestation")

    prior_reference = handoff["previous_review"]
    if review["supersedes_review"] != prior_reference:
        raise RuleFailure("Review supersedes_review does not match the handoff")
    prior_findings: dict[str, dict[str, Any]] = {}
    response_ids: set[str] = set()
    if prior_reference is not None:
        prior = validate_json_file(
            directory / prior_reference["path"],
            root / "schemas" / "review.schema.json",
        )
        prior_findings = {item["id"]: item for item in prior["findings"]}
        if prior["verdict"] == "REJECT":
            response, _ = load_registered(
                root,
                directory,
                state,
                "review_response",
                "review-response.schema.json",
            )
            response_ids = {item["finding_id"] for item in response["responses"]}

    finding_ids = [item["id"] for item in review["findings"]]
    if len(finding_ids) != len(set(finding_ids)):
        raise RuleFailure("Review contains duplicate finding IDs")
    current_findings = {item["id"]: item for item in review["findings"]}
    if set(prior_findings) - set(current_findings):
        raise RuleFailure("follow-up Review must carry every prior finding ID")

    acceptance_ids = {item["id"] for item in work_item["acceptance"]}
    max_prior_number = max(
        (int(finding_id.split("-")[1]) for finding_id in prior_findings), default=0
    )
    stable_fields = {
        "introduced_in_attempt",
        "category",
        "acceptance_id",
        "scope_violation",
        "blocking",
        "severity",
        "claim",
        "required_action",
    }
    for finding in review["findings"]:
        if finding["acceptance_id"] is not None and finding["acceptance_id"] not in acceptance_ids:
            raise RuleFailure(f"finding references unknown acceptance ID: {finding['id']}")
        must_block = (
            finding["severity"] in {"critical", "high"}
            or finding["acceptance_id"] is not None
            or finding["scope_violation"]
        )
        if must_block and not finding["blocking"]:
            raise RuleFailure(f"finding must be blocking: {finding['id']}")
        previous = prior_findings.get(finding["id"])
        if previous is None:
            number = int(finding["id"].split("-")[1])
            if number <= max_prior_number:
                raise RuleFailure(f"new finding ID is not monotonic: {finding['id']}")
            if (
                finding["introduced_in_attempt"] != review["artifact_attempt"]
                or finding["status"] != "open"
                or finding["reviewer_resolution"] is not None
            ):
                raise RuleFailure(f"new finding has an invalid initial lifecycle: {finding['id']}")
        else:
            if any(finding[field] != previous[field] for field in stable_fields):
                raise RuleFailure(f"stable finding fields changed: {finding['id']}")
            if (
                previous["status"] == "open"
                and prior_reference is not None
                and prior["verdict"] == "REJECT"
                and finding["id"] not in response_ids
            ):
                raise RuleFailure(f"prior open finding lacks an author response: {finding['id']}")
            if not _nonempty(finding["reviewer_resolution"]):
                raise RuleFailure(f"carried finding lacks Reviewer resolution: {finding['id']}")

    open_blocking = [
        item for item in review["findings"] if item["status"] == "open" and item["blocking"]
    ]
    if review["verdict"] == "ACCEPT" and open_blocking:
        raise RuleFailure("Review cannot ACCEPT with open blocking findings")
    if review["verdict"] == "REJECT" and not open_blocking:
        raise RuleFailure("Review REJECT requires at least one open blocking finding")
