"""Deterministic reviewer handoff, session, and finding lifecycle checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from polaris_core import (
    RuleFailure,
    current_work_item_path,
    directory_sha256,
    file_sha256,
    read_json,
    validate_json_file,
)


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


def artifact_path(directory: Path, reference: Any) -> Path:
    raw = (
        reference
        if isinstance(reference, str)
        else reference.get("path")
        if isinstance(reference, dict)
        else None
    )
    if not isinstance(raw, str):
        raise RuleFailure(f"invalid artifact reference: {reference!r}")
    path = (directory / raw).resolve()
    try:
        path.relative_to(directory.resolve())
    except ValueError as exc:
        raise RuleFailure(f"artifact escapes task directory: {raw}") from exc
    return path


def normalized_reference(directory: Path, reference: Any) -> dict[str, str]:
    path = artifact_path(directory, reference)
    if not path.is_file():
        raise RuleFailure(f"artifact does not exist: {path}")
    actual_hash = file_sha256(path)
    if isinstance(reference, dict) and reference.get("sha256") != actual_hash:
        raise RuleFailure(f"artifact changed after registration: {path}")
    return {
        "path": path.relative_to(directory.resolve()).as_posix(),
        "sha256": actual_hash,
    }


def state_reference(
    directory: Path, state: dict[str, Any], name: str, required: bool = True
) -> dict[str, str] | None:
    reference = state["artifacts"].get(name)
    if reference is None:
        if required:
            raise RuleFailure(f"state requires artifact: {name}")
        return None
    return normalized_reference(directory, reference)


def _load_registered(
    root: Path,
    directory: Path,
    state: dict[str, Any],
    name: str,
    schema_name: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    reference = state_reference(directory, state, name)
    assert reference is not None
    value = validate_json_file(
        directory / reference["path"], root / "schemas" / schema_name
    )
    return value, reference


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


def validate_handoff(
    repo: Path,
    root: Path,
    directory: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    handoff, _ = _load_registered(
        root,
        directory,
        state,
        "review_handoff",
        "review-handoff.schema.json",
    )
    implementation, _ = _load_registered(
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
    missing_roles = REQUIRED_PACKAGE_ROLES - roles
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
        "work_item": current_work_item_path(
            directory, state["current_revision"]
        ).relative_to(repo).as_posix(),
        "plan": (directory / plan_reference["path"]).relative_to(repo).as_posix(),
        "working_set": (
            directory / working_set_reference["path"]
        ).relative_to(repo).as_posix(),
        "implementation": (
            directory / implementation_reference["path"]
        ).relative_to(repo).as_posix(),
        "knowledge_delta": (
            directory / knowledge_reference["path"]
        ).relative_to(repo).as_posix(),
        "evidence": (
            directory / "evidence" / f"r{state['current_revision']:03d}"
        ).relative_to(repo).as_posix(),
    }
    if prior_reference is not None:
        expected_paths["previous_review"] = (
            directory / prior_reference["path"]
        ).relative_to(repo).as_posix()
        response_reference = state_reference(
            directory, state, "review_response", required=False
        )
        if response_reference is not None:
            expected_paths["review_response"] = (
                directory / response_reference["path"]
            ).relative_to(repo).as_posix()
    for role, expected_path in expected_paths.items():
        entries = items_by_role.get(role, [])
        if len(entries) != 1 or entries[0]["path"] != expected_path:
            raise RuleFailure(f"review handoff role {role} targets the wrong path")

    repo_root = repo.resolve()
    for item in handoff["package"]:
        path = (repo_root / item["path"]).resolve()
        try:
            path.relative_to(repo_root)
        except ValueError as exc:
            raise RuleFailure(f"review package path escapes repository: {item['path']}") from exc
        if item["kind"] == "file":
            if not path.is_file() or item["sha256"] != file_sha256(path):
                raise RuleFailure(f"review package file changed or is missing: {item['path']}")
        elif not path.is_dir() or item["sha256"] != directory_sha256(path):
            raise RuleFailure(f"review package directory changed or is missing: {item['path']}")
    return handoff


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
            response, _ = _load_registered(
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
