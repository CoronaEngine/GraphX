"""Candidate-state construction and event-specific effects for transitions."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from artifact_protocol import load_registered, normalized_reference
from polaris_core import (
    RuleFailure,
    current_work_item_path,
    file_sha256,
    full_commit,
    read_json,
    subject_diff_hash,
    utc_now,
)
from review_protocol import MAX_REVIEW_ATTEMPTS


IMPLEMENTATION_DOWNSTREAM_ARTIFACTS = frozenset(
    {
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
    }
)
REVIEW_PACKAGE_ARTIFACTS = frozenset({"review", "review_2", "review_handoff"})
PLAN_REWORK_ARTIFACTS = frozenset({"plan", "working_set"})


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


def prepare_next_state(
    repo: Path,
    directory: Path,
    state: dict[str, Any],
    event_name: str,
    artifact_values: list[str],
    revision: int | None,
    subject_base: str | None,
    subject_head: str | None,
    blocker_type: str | None,
    reason: str | None,
    decision_owner: str | None,
) -> tuple[dict[str, Any], dict[str, dict[str, str]], dict[str, str] | None]:
    next_state = copy.deepcopy(state)
    submitted_artifacts = parse_artifacts(artifact_values, directory)
    next_state["artifacts"].update(submitted_artifacts)

    if revision is not None:
        if event_name != "NEW_REVISION" or revision != state["current_revision"] + 1:
            raise RuleFailure("--revision must be exactly current+1 for NEW_REVISION")
        next_state["current_revision"] = revision
        next_state["artifacts"] = {}
        next_state["subject"] = None
        work_item = current_work_item_path(directory, revision)
        next_state["rigor"] = read_json(work_item)["rigor"]

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
    return next_state, submitted_artifacts, blocker


def resolve_destination(transition_rule: dict[str, Any], state: dict[str, Any]) -> str:
    destination = transition_rule["to"]
    if destination == "$blocked_from":
        destination = state.get("blocked_from")
        if not destination:
            raise RuleFailure("cannot resolve BLOCKED state without blocked_from")
    return destination


def _discard_artifacts(state: dict[str, Any], names: frozenset[str]) -> None:
    for name in names:
        state["artifacts"].pop(name, None)


def apply_event_effects(
    root: Path,
    directory: Path,
    state: dict[str, Any],
    next_state: dict[str, Any],
    event_name: str,
    destination: str,
    transition_rule: dict[str, Any],
) -> str:
    if event_name == "REJECT_REVIEW":
        review, _ = load_registered(
            root, directory, next_state, "review", "review.schema.json"
        )
        next_state["artifacts"]["prior_review"] = normalized_reference(
            directory, next_state["artifacts"]["review"]
        )
        max_attempts = transition_rule.get("max_attempts", MAX_REVIEW_ATTEMPTS)
        if review["artifact_attempt"] >= max_attempts:
            destination = transition_rule.get("on_max_attempts_to", "BLOCKED")
            next_state["blocked_from"] = state["status"]
            next_state["blocker"] = {
                "type": "review_dispute",
                "reason": f"Review remained rejected after {max_attempts} attempts",
                "decision_owner": "human",
            }

    if event_name == "REJECT_REVIEW" and destination == "IMPLEMENTING":
        _discard_artifacts(next_state, IMPLEMENTATION_DOWNSTREAM_ARTIFACTS)
        next_state["subject"] = None
    elif event_name == "REJECT_REVIEW":
        _discard_artifacts(next_state, REVIEW_PACKAGE_ARTIFACTS)
    elif event_name == "FAIL_IMPLEMENTATION":
        prior_review = next_state["artifacts"].get("review")
        if prior_review is not None:
            next_state["artifacts"]["prior_review"] = normalized_reference(
                directory, prior_review
            )
        _discard_artifacts(next_state, IMPLEMENTATION_DOWNSTREAM_ARTIFACTS)
        next_state["subject"] = None
    elif event_name == "FAIL_PLAN":
        prior_review = next_state["artifacts"].get("review")
        next_state["artifacts"] = {
            key: value
            for key, value in next_state["artifacts"].items()
            if key in PLAN_REWORK_ARTIFACTS
        }
        if prior_review is not None:
            next_state["artifacts"]["prior_review"] = normalized_reference(
                directory, prior_review
            )
        next_state["subject"] = None
    elif event_name == "RESOLVE_BLOCK":
        next_state["blocked_from"] = None
        next_state["blocker"] = None
    return destination


def build_event(
    state: dict[str, Any],
    next_state: dict[str, Any],
    task_id: str,
    event_name: str,
    gate: str,
    destination: str,
    submitted_artifacts: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "sequence": next_state["sequence"],
        "timestamp": utc_now(),
        "event": event_name,
        "gate": gate,
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
