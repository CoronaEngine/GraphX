#!/usr/bin/env python3
"""Build an immutable, repository-only package for an isolated Reviewer."""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

from internal.polaris_core import (
    acquire_lock,
    InputFailure,
    RuleFailure,
    current_work_item_path,
    directory_sha256,
    file_sha256,
    full_commit,
    protocol_root,
    read_json,
    rebuild_state_value,
    release_lock,
    require_protocol_compatible,
    run_main,
    task_dir,
    subject_diff_hash,
    utc_now,
    validate_json_file,
    write_json_atomic,
)
from internal.artifact_protocol import normalized_reference
from internal.code_intelligence_protocol import record_reference
from internal.task_location_protocol import logical_repo_path, resolve_repo_reference
from internal.review_protocol import MAX_REVIEW_ATTEMPTS
from internal.task_layout import events_path, evidence_dir, review_handoff_path, state_path
from internal.transition_gates import check_gate
from internal.working_set_protocol import validate_working_set


def _repo_relative(repo: Path, path: Path) -> str:
    return logical_repo_path(repo, path)


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


def _code_intelligence_entry(
    repo: Path,
    directory: Path,
    task_id: str,
    artifact: dict[str, Any],
    role: str,
) -> dict[str, Any] | None:
    reference = artifact.get("code_intelligence")
    if reference is None:
        return None
    record_reference(repo, task_id, reference)
    return _entry(repo, role, directory / reference["path"])


def _build_locked(
    repo: Path,
    task_id: str,
    implementer_session_id: str,
    isolation_mode: str | None,
    implementation_path: Path | None = None,
    knowledge_path: Path | None = None,
    subject_base: str | None = None,
    subject_head: str | None = None,
    review_response_path: Path | None = None,
) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    stored_state = read_json(state_path(directory))
    require_protocol_compatible(repo, stored_state)
    if stored_state["status"] != "IMPLEMENTING":
        raise RuleFailure("review handoff can only be built from IMPLEMENTING")
    supplied = (implementation_path, knowledge_path, subject_base, subject_head)
    if any(value is not None for value in supplied) and not all(
        value is not None for value in supplied
    ):
        raise InputFailure(
            "review handoff requires implementation, knowledge, subject base, and subject head"
        )
    state = copy.deepcopy(stored_state)
    if all(value is not None for value in supplied):
        base = full_commit(repo, str(subject_base))
        head = full_commit(repo, str(subject_head))
        for name, supplied_path in (
            ("implementation", implementation_path),
            ("knowledge_delta", knowledge_path),
        ):
            assert supplied_path is not None
            resolved = supplied_path.resolve()
            try:
                relative = resolved.relative_to(directory.resolve())
            except ValueError as exc:
                raise RuleFailure(
                    f"review handoff artifact must be inside the task directory: {resolved}"
                ) from exc
            if not resolved.is_file():
                raise RuleFailure(f"review handoff artifact does not exist: {resolved}")
            state["artifacts"][name] = {
                "path": relative.as_posix(),
                "sha256": file_sha256(resolved),
            }
        state["subject"] = {
            "base_commit": base,
            "head_commit": head,
            "diff_hash": subject_diff_hash(repo, base, head),
        }
    if review_response_path is not None:
        resolved_response = review_response_path.resolve()
        try:
            relative_response = resolved_response.relative_to(directory.resolve())
        except ValueError as exc:
            raise RuleFailure(
                f"review response must be inside the task directory: {resolved_response}"
            ) from exc
        if not resolved_response.is_file():
            raise RuleFailure(f"review response does not exist: {resolved_response}")
        state["artifacts"]["review_response"] = {
            "path": relative_response.as_posix(),
            "sha256": file_sha256(resolved_response),
        }
    workflow = read_json(repo / ".polaris" / "workflow.json")
    check_gate(repo, root, directory, state, "implementation_ready", None, workflow)
    check_gate(repo, root, directory, state, "docs_ready", None, workflow)
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
    implementation_intelligence = _code_intelligence_entry(
        repo, directory, task_id, implementation, "implementation_code_intelligence"
    )
    knowledge = validate_json_file(
        directory / normalized_reference(
            directory, state["artifacts"]["knowledge_delta"]
        )["path"],
        root / "schemas" / "knowledge-delta.schema.json",
    )
    documentation_intelligence = _code_intelligence_entry(
        repo, directory, task_id, knowledge, "documentation_code_intelligence"
    )
    package.extend(
        item
        for item in (implementation_intelligence, documentation_intelligence)
        if item is not None
    )
    if state["artifacts"].get("plan_decisions") is not None:
        package.append(
            _artifact_entry(
                repo,
                directory,
                state,
                "plan_decisions",
                "plan_decisions",
            )
        )
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
        candidate = resolve_repo_reference(repo, raw_path)
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
    if path.exists() and stored_state["artifacts"].get("review_handoff") is not None:
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


def build(
    repo: Path,
    task_id: str,
    implementer_session_id: str,
    isolation_mode: str | None,
    implementation_path: Path | None = None,
    knowledge_path: Path | None = None,
    subject_base: str | None = None,
    subject_head: str | None = None,
    review_response_path: Path | None = None,
) -> dict[str, Any]:
    """Build while excluding task transitions and rejecting stale projections."""
    directory = task_dir(repo, task_id)
    lock_path = directory / ".transition.lock"
    descriptor = acquire_lock(lock_path)
    try:
        stored_state = read_json(state_path(directory))
        if rebuild_state_value(events_path(directory)) != stored_state:
            raise RuleFailure(
                "state.json differs from events.jsonl; rebuild before building Review handoff"
            )
        return _build_locked(
            repo,
            task_id,
            implementer_session_id,
            isolation_mode,
            implementation_path,
            knowledge_path,
            subject_base,
            subject_head,
            review_response_path,
        )
    finally:
        release_lock(lock_path, descriptor)


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
    parser.add_argument("--implementation", type=Path)
    parser.add_argument("--knowledge-delta", type=Path)
    parser.add_argument("--subject-base")
    parser.add_argument("--subject-head")
    parser.add_argument("--review-response", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: build(
            args.repo.resolve(),
            args.task_id,
            args.implementer_session_id,
            args.isolation,
            args.implementation,
            args.knowledge_delta,
            args.subject_base,
            args.subject_head,
            args.review_response,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
