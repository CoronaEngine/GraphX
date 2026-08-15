#!/usr/bin/env python3
"""Build an immutable, repository-only package for an isolated Reviewer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from internal.polaris_core import (
    InputFailure,
    RuleFailure,
    current_work_item_path,
    directory_sha256,
    file_sha256,
    protocol_root,
    read_json,
    run_main,
    task_dir,
    utc_now,
    validate_json_file,
    write_json_atomic,
)
from internal.artifact_protocol import normalized_reference
from internal.review_protocol import MAX_REVIEW_ATTEMPTS
from internal.task_layout import evidence_dir, review_handoff_path, state_path
from internal.working_set_protocol import validate_working_set


def _repo_relative(repo: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise RuleFailure(f"review package path escapes repository: {path}") from exc


def _entry(repo: Path, role: str, path: Path) -> dict[str, Any]:
    if path.is_file():
        return {
            "role": role,
            "path": _repo_relative(repo, path),
            "kind": "file",
            "sha256": file_sha256(path),
        }
    if path.is_dir():
        return {
            "role": role,
            "path": _repo_relative(repo, path),
            "kind": "directory",
            "sha256": directory_sha256(path),
        }
    raise RuleFailure(f"review package path does not exist: {path}")


def _artifact_entry(
    repo: Path,
    directory: Path,
    state: dict[str, Any],
    name: str,
    role: str,
) -> dict[str, Any]:
    reference = state["artifacts"].get(name)
    if reference is None:
        raise RuleFailure(f"review handoff requires artifact: {name}")
    normalized = normalized_reference(directory, reference)
    return _entry(repo, role, directory / normalized["path"])


def build(
    repo: Path,
    task_id: str,
    implementer_session_id: str,
    isolation_mode: str | None,
) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    if state["status"] != "DOCS_SYNCED":
        raise RuleFailure("review handoff can only be built from DOCS_SYNCED")
    implementation_reference = normalized_reference(
        directory, state["artifacts"].get("implementation")
    )
    implementation = validate_json_file(
        directory / implementation_reference["path"],
        root / "schemas" / "implementation.schema.json",
    )
    if implementation["implementer_session_id"] != implementer_session_id:
        raise RuleFailure("implementer session ID does not match the Implementation artifact")

    attempt = implementation["artifact_attempt"]
    if attempt > MAX_REVIEW_ATTEMPTS:
        raise RuleFailure("Review attempt limit exceeded; escalate to the Decision Owner")

    if isolation_mode is None:
        isolation_mode = (
            "r0_isolated_same_session" if state["rigor"] == "R0" else "fresh_session"
        )
    if state["rigor"] in {"R1", "R2"} and isolation_mode not in {
        "fresh_session",
        "isolated_reviewer_agent",
    }:
        raise RuleFailure("R1/R2 requires a fresh session or isolated reviewer agent")

    subject = state.get("subject")
    if not isinstance(subject, dict):
        raise RuleFailure("review handoff requires a frozen subject")
    previous_review = None
    prior = state["artifacts"].get("prior_review")
    if prior is not None:
        previous_review = normalized_reference(directory, prior)
        prior_value = validate_json_file(
            directory / previous_review["path"], root / "schemas" / "review.schema.json"
        )
        if attempt != prior_value["artifact_attempt"] + 1:
            raise RuleFailure("next handoff must immediately follow the prior Review")
        response = state["artifacts"].get("review_response")
        if prior_value["verdict"] == "REJECT" and response is None:
            raise RuleFailure("Review rework requires a registered review_response")
        if prior_value["verdict"] == "ACCEPT" and response is not None:
            raise RuleFailure("accepted prior Review must not have a review_response")
    elif attempt != 1:
        raise RuleFailure("an initial Review handoff must use artifact attempt 1")

    revision = state["current_revision"]
    plan_reference = normalized_reference(directory, state["artifacts"].get("plan"))
    working_set_reference = normalized_reference(
        directory, state["artifacts"].get("working_set")
    )
    working_set = directory / working_set_reference["path"]
    working_set_value = validate_working_set(repo, task_id, working_set)
    package = [
        _entry(repo, "project_rules", repo / "AGENTS.md"),
        _entry(repo, "work_item", current_work_item_path(directory, revision)),
        _entry(repo, "plan", directory / plan_reference["path"]),
        _entry(repo, "working_set", working_set),
        _artifact_entry(repo, directory, state, "implementation", "implementation"),
        _artifact_entry(repo, directory, state, "knowledge_delta", "knowledge_delta"),
        _entry(repo, "evidence", evidence_dir(directory, revision)),
    ]
    if previous_review is not None:
        package.append(_entry(repo, "previous_review", directory / previous_review["path"]))
        if state["artifacts"].get("review_response") is not None:
            package.append(
                _artifact_entry(repo, directory, state, "review_response", "review_response")
            )

    seen_paths = {item["path"] for item in package}
    for working_entry in working_set_value["entries"]:
        raw_path = working_entry["path"]
        if raw_path == ".polaris/project-index.json":
            continue
        candidate = (repo / raw_path).resolve()
        try:
            candidate.relative_to(repo.resolve())
        except ValueError as exc:
            raise RuleFailure(f"Working Set path escapes repository: {raw_path}") from exc
        if candidate.exists():
            item = _entry(repo, "working_set_reference", candidate)
            if item["path"] not in seen_paths:
                package.append(item)
                seen_paths.add(item["path"])

    handoff = {
        "task_id": task_id,
        "work_item_revision": revision,
        "artifact_attempt": attempt,
        "rigor": state["rigor"],
        "created_at": utc_now(),
        "implementer_session_id": implementer_session_id,
        "required_isolation": isolation_mode,
        "subject_base_commit": subject["base_commit"],
        "subject_head_commit": subject["head_commit"],
        "subject_diff_hash": subject["diff_hash"],
        "previous_review": previous_review,
        "package": package,
    }
    path = review_handoff_path(directory, revision, attempt)
    if path.exists():
        raise InputFailure(f"review handoff is immutable and already exists: {path}")
    write_json_atomic(path, handoff)
    validate_json_file(path, root / "schemas" / "review-handoff.schema.json")
    return {
        "message": f"built Review handoff attempt {attempt}; stop the implementer session",
        "path": str(path),
        "artifact_attempt": attempt,
        "required_isolation": isolation_mode,
        "next_action": (
            "open a new host session or isolated reviewer worker, then load only this handoff"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--implementer-session-id", required=True)
    parser.add_argument(
        "--isolation",
        choices=[
            "fresh_session",
            "isolated_reviewer_agent",
            "r0_isolated_same_session",
        ],
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: build(
            args.repo.resolve(),
            args.task_id,
            args.implementer_session_id,
            args.isolation,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
