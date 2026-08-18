"""Bound one CodeGraph explore call to an auditable Polaris freshness window."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .code_intelligence_protocol import (
    _project_marker_path,
    _record_name,
    load_config,
    load_providers,
)
from .codegraph_adapter import (
    classify_response,
    inspect_status,
    run_explore,
    synchronize_observed_status,
)
from .implementation_protocol import validate_handoff as validate_implementation_handoff
from .path_security import confined_target
from .polaris_core import (
    InputFailure,
    RuleFailure,
    file_sha256,
    full_commit,
    protocol_root,
    read_json,
    require_protocol_compatible,
    subject_diff_hash,
    task_dir,
    utc_now,
    validate_json_file,
    write_json_atomic,
    write_text_atomic,
)
from .review_handoff_protocol import validate_handoff as validate_review_handoff
from .task_layout import state_path, task_relative_path, work_item_path


QUERY_ID_PATTERN = re.compile(r"^CIQ-(?P<number>[0-9]{3})$")
STAGE_STATUSES = {
    "PLANNING": {"QUALIFIED"},
    "IMPLEMENTATION": {"IMPLEMENTING"},
    "DOCUMENTATION_SYNC": {"IMPLEMENTING"},
    "REVIEW": {"REVIEWING"},
}
_INDEX_FALLBACK = {
    "scope": "INDEX",
    "path": None,
    "reason": "STATUS_UNREADABLE",
    "fallback": "SEARCH_SOURCE",
    "observed_sha256": None,
}


def _target(base: str, head: str | None, diff_hash: str | None) -> dict[str, str | None]:
    return {"base_commit": base, "head_commit": head, "diff_hash": diff_hash}


def _validated_subject(repo: Path, subject: Any, fallback_base: str) -> dict[str, str | None]:
    if subject is None:
        base = full_commit(repo, fallback_base)
        head = full_commit(repo)
        return _target(base, head, subject_diff_hash(repo, base, head))
    if not isinstance(subject, dict):
        raise RuleFailure("CodeGraph stage context has an invalid subject")
    base = full_commit(repo, subject.get("base_commit", ""))
    head = full_commit(repo, subject.get("head_commit", ""))
    digest = subject_diff_hash(repo, base, head)
    if subject.get("diff_hash") != digest:
        raise RuleFailure("CodeGraph stage context subject diff hash is stale")
    return _target(base, head, digest)


def resolve_stage_context(repo: Path, task_id: str, stage: str) -> dict[str, Any]:
    """Resolve one stage identity from validated frozen task artifacts."""
    if stage not in STAGE_STATUSES:
        raise InputFailure(f"invalid CodeGraph stage: {stage}")
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = validate_json_file(state_path(directory), root / "schemas/task-state.schema.json")
    require_protocol_compatible(repo, state)
    if state["task_id"] != task_id:
        raise RuleFailure("CodeGraph stage context targets the wrong task")
    if state["status"] not in STAGE_STATUSES[stage]:
        raise RuleFailure(
            f"CodeGraph stage {stage} is inconsistent with task status {state['status']}"
        )
    revision = state["current_revision"]
    work_item = validate_json_file(
        work_item_path(directory, revision), root / "schemas/work-item.schema.json"
    )
    if work_item["id"] != task_id or work_item["revision"] != revision:
        raise RuleFailure("CodeGraph stage context has the wrong frozen Work Item")

    attempt: int | None = None
    reviewer_slot: int | None = None
    if stage == "PLANNING":
        target = _target(full_commit(repo, work_item["base_commit"]), None, None)
    elif stage in {"IMPLEMENTATION", "DOCUMENTATION_SYNC"}:
        handoff, _reference = validate_implementation_handoff(
            repo, root, directory, state
        )
        attempt = handoff["artifact_attempt"]
        target = _validated_subject(repo, state.get("subject"), handoff["subject_base_commit"])
    else:
        handoff = validate_review_handoff(repo, root, directory, state)
        attempt = handoff["artifact_attempt"]
        target = _target(
            full_commit(repo, handoff["subject_base_commit"]),
            full_commit(repo, handoff["subject_head_commit"]),
            handoff["subject_diff_hash"],
        )
        if target["diff_hash"] != subject_diff_hash(
            repo, str(target["base_commit"]), str(target["head_commit"])
        ):
            raise RuleFailure("CodeGraph Review handoff diff hash is stale")
        if state["artifacts"].get("review_2") is not None:
            raise RuleFailure("CodeGraph Review already has both reviewer slots")
        reviewer_slot = 2 if state["artifacts"].get("review") is not None else 1

    identity = {
        "stage": stage,
        "artifact_attempt": attempt,
        "reviewer_slot": reviewer_slot,
    }
    return {
        "task_id": task_id,
        "work_item_revision": revision,
        "stage": stage,
        "artifact_attempt": attempt,
        "reviewer_slot": reviewer_slot,
        "record_name": _record_name(identity),
        "target": target,
    }


def _validated_query_id(query_id: str) -> int:
    match = QUERY_ID_PATTERN.fullmatch(query_id) if isinstance(query_id, str) else None
    if match is None or match["number"] == "000":
        raise InputFailure(f"invalid CodeGraph query id: {query_id}")
    return int(match["number"])


def _proxy_path(
    repo: Path,
    task_id: str,
    context: dict[str, Any],
    query_id: str,
    artifact: str,
) -> Path:
    _validated_query_id(query_id)
    if context.get("task_id") != task_id:
        raise RuleFailure("CodeGraph proxy context targets the wrong task")
    record_name = context.get("record_name")
    if not isinstance(record_name, str) or re.fullmatch(
        r"(?:planning|implementation-[0-9]{3}|documentation-sync-[0-9]{3}|review-[0-9]{3}-slot-[12])",
        record_name,
    ) is None:
        raise RuleFailure("CodeGraph proxy context has an invalid record name")
    directory = task_dir(repo, task_id)
    relative = task_relative_path(
        artifact, record_name=record_name, query_id=query_id
    )
    return confined_target(directory, directory / relative, "CodeGraph proxy evidence")


def proxy_bundle_path(
    repo: Path, task_id: str, context: dict[str, Any], query_id: str
) -> Path:
    """Return the next immutable bundle path for this stage record."""
    number = _validated_query_id(query_id)
    destination = _proxy_path(
        repo, task_id, context, query_id, "code_intelligence_proxy_bundle"
    )
    parent = destination.parent
    confined_target(task_dir(repo, task_id), parent, "CodeGraph proxy runtime directory")
    existing_numbers: list[int] = []
    if parent.exists():
        if not parent.is_dir():
            raise RuleFailure("CodeGraph proxy runtime path is not a directory")
        for path in parent.glob("CIQ-*.json"):
            match = QUERY_ID_PATTERN.fullmatch(path.stem)
            if match is None or path.is_symlink() or not path.is_file():
                raise RuleFailure(f"invalid CodeGraph proxy bundle path: {path}")
            existing_numbers.append(int(match["number"]))
    expected_numbers = list(range(1, len(existing_numbers) + 1))
    if sorted(existing_numbers) != expected_numbers:
        raise RuleFailure("existing CodeGraph proxy query IDs are not sequential")
    expected = len(existing_numbers) + 1
    if expected > 999:
        raise InputFailure("CodeGraph proxy query limit exceeded for this stage")
    if number != expected:
        raise InputFailure(f"CodeGraph query id must be the next sequential ID CIQ-{expected:03d}")
    if destination.exists() or destination.is_symlink():
        raise InputFailure(f"CodeGraph proxy bundle is immutable: {destination}")
    return destination


def _unavailable_status(reason: str) -> dict[str, Any]:
    return {
        "status": "UNAVAILABLE",
        "checked_at": utc_now(),
        "basis": ["NONE"],
        "stale_points": [],
        "status_response_sha256": None,
        "error": reason[:240],
        "needs_sync": False,
        "pending_changes": None,
    }


def _pending_point() -> dict[str, Any]:
    return {**_INDEX_FALLBACK, "reason": "PENDING_CHANGES"}


def _observation_points(observation: dict[str, Any] | None) -> list[dict[str, Any]]:
    if observation is None:
        return []
    points = list(observation.get("stale_points", []))
    pending = observation.get("pending_changes")
    if isinstance(pending, dict) and any(pending.get(key, 0) for key in ("added", "modified", "removed")):
        if _pending_point() not in points:
            points.append(_pending_point())
    return points


def _is_unknown(observation: dict[str, Any] | None) -> bool:
    return observation is not None and observation.get("status") == "NOT_VERIFIED"


def _successful_statuses(*observations: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        item
        for item in observations
        if item is not None and isinstance(item.get("pending_changes"), dict)
    ]


def _pending_counts(*observations: dict[str, Any] | None) -> dict[str, int]:
    values = _successful_statuses(*observations)
    return {
        key: max((item["pending_changes"][key] for item in values), default=0)
        for key in ("added", "modified", "removed")
    }


def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def _unsafe_response(classification: dict[str, Any]) -> bool:
    error = str(classification.get("error") or "").lower()
    return classification.get("classification") == "NOT_VERIFIED" and any(
        token in error
        for token in (
            "path",
            "symlink",
            "regular file",
            "escapes",
            "repository reference",
        )
    )


def _delivery(
    effective_pre: dict[str, Any],
    query_result: dict[str, Any],
    classification: dict[str, Any] | None,
    post_status: dict[str, Any] | None,
    *,
    forced_unknown: str | None = None,
) -> dict[str, Any]:
    checked_at = (
        (post_status or {}).get("checked_at")
        or (classification or {}).get("checked_at")
        or query_result.get("checked_at")
        or effective_pre.get("checked_at")
        or utc_now()
    )
    points = _deduplicate([
        *_observation_points(effective_pre),
        *((classification or {}).get("stale_points", [])),
        *_observation_points(post_status),
    ])
    known_stale = any(
        point.get("reason") != "STATUS_UNREADABLE" for point in points
    ) or effective_pre.get("status") in {"PARTIAL_STALE", "INDEX_STALE"} or (
        post_status is not None
        and post_status.get("status") in {"PARTIAL_STALE", "INDEX_STALE"}
    ) or (classification or {}).get("classification") in {"PARTIAL_STALE", "INDEX_STALE"}
    unknown = (
        forced_unknown is not None
        or query_result.get("status") != "SUCCESS"
        or _is_unknown(effective_pre)
        or post_status is None
        or _is_unknown(post_status)
        or (classification or {}).get("classification") == "NOT_VERIFIED"
    )
    errors = [
        forced_unknown,
        effective_pre.get("error"),
        query_result.get("error"),
        (classification or {}).get("error"),
        (post_status or {}).get("error"),
    ]
    error = next((str(item)[:240] for item in errors if item), None)
    if known_stale:
        index_points = [point for point in points if point.get("scope") == "INDEX"]
        state = "STALE"
        record_status = "INDEX_STALE" if index_points else "PARTIAL_STALE"
        reason = next(
            (
                str(point["reason"])
                for point in points
                if point.get("reason") != "STATUS_UNREADABLE"
            ),
            "INDEX_STALE",
        )
        actions = {point.get("fallback") for point in points}
        required_fallback = (
            "SEARCH_SOURCE"
            if index_points or len(actions) != 1
            else str(next(iter(actions)))
        )
        usage = "NAVIGATION_ONLY"
    elif unknown:
        state = "UNKNOWN"
        record_status = "NOT_VERIFIED"
        if not any(point.get("reason") == "STATUS_UNREADABLE" for point in points):
            points.append(dict(_INDEX_FALLBACK))
        if forced_unknown:
            reason = "RESPONSE_INTEGRITY_UNVERIFIED"
        elif _is_unknown(effective_pre):
            reason = (
                "PROJECT_MISMATCH"
                if "different project" in str(effective_pre.get("error", "")).lower()
                else "STATUS_UNREADABLE"
            )
        elif query_result.get("status") != "SUCCESS":
            reason = "EXPLORE_FAILED"
        elif (classification or {}).get("classification") == "NOT_VERIFIED":
            reason = "RESPONSE_NOT_VERIFIED"
        else:
            reason = "POST_STATUS_UNREADABLE"
        required_fallback = "SEARCH_SOURCE"
        usage = "NAVIGATION_ONLY"
    else:
        state = "CURRENT"
        record_status = "CURRENT_AT_CHECK"
        reason = "VERIFIED_WINDOW"
        required_fallback = "NONE"
        usage = "NON_AUTHORITATIVE_CONTEXT"
    return {
        "state": state,
        "record_status": record_status,
        "reason": reason,
        "checked_at": checked_at,
        "usage": usage,
        "required_fallback": required_fallback,
        "stale_points": points,
        "pending_changes": _pending_counts(effective_pre, post_status),
        "error": error,
    }


def _bundle_base(
    repo: Path,
    context: dict[str, Any],
    query_id: str,
    purpose: str,
    query: str,
    descriptor: dict[str, Any],
) -> dict[str, Any]:
    project = read_json(repo / ".polaris/project.json")
    return {
        "bundle_version": 1,
        "proxy": {
            "server_id": "polaris-codegraph",
            "tool": "polaris_codegraph_explore",
        },
        "provider": {
            "id": descriptor["provider_id"],
            "descriptor_version": descriptor["provider_version"],
        },
        "repository": {
            "project_id": project["project_id"],
            "root_sha256": hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest(),
        },
        "task_context": context,
        "query": {
            "id": query_id,
            "purpose": purpose,
            "text": query,
            "status": "UNAVAILABLE",
            "response_sha256": None,
            "error": None,
        },
        "pre_status": None,
        "sync": None,
        "post_sync_status": None,
        "response_classification": None,
        "post_query_status": None,
        "delivery": None,
        "response_path": None,
    }


def _write_bundle(path: Path, bundle: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise InputFailure(f"CodeGraph proxy bundle is immutable: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    confined_target(path.parents[3], path, "CodeGraph proxy evidence")
    write_json_atomic(path, bundle)


def execute_proxy_query(
    repo: Path,
    task_id: str,
    stage: str,
    query_id: str,
    purpose: str,
    query: str,
    sync_if_needed: bool,
    *,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Execute one immutable CodeGraph query window and persist its evidence."""
    if not isinstance(purpose, str) or not purpose.strip() or len(purpose) > 240:
        raise InputFailure("CodeGraph query purpose must contain 1 to 240 characters")
    if not isinstance(query, str) or not query.strip() or len(query) > 8000:
        raise InputFailure("CodeGraph query must contain 1 to 8000 characters")
    if not isinstance(sync_if_needed, bool):
        raise InputFailure("sync_if_needed must be a boolean")
    repo = repo.absolute()
    if repo.is_symlink() or not repo.is_dir():
        raise RuleFailure("CodeGraph proxy repository root must be a fixed real directory")
    repo = repo.resolve()
    context = resolve_stage_context(repo, task_id, stage)
    bundle_path = proxy_bundle_path(repo, task_id, context, query_id)
    response_path = _proxy_path(
        repo, task_id, context, query_id, "code_intelligence_proxy_response"
    )
    if response_path.exists() or response_path.is_symlink():
        raise InputFailure(f"CodeGraph proxy response is immutable: {response_path}")
    root = protocol_root(repo)
    descriptor = load_providers(root)["codegraph"]
    bundle = _bundle_base(repo, context, query_id, purpose.strip(), query, descriptor)

    config = load_config(repo, root)
    marker = _project_marker_path(repo, descriptor["project_marker"])
    unavailable_reason: str | None = None
    if config["mode"] == "disabled":
        unavailable_reason = "POLICY_DISABLED"
    elif not marker.is_dir() or marker.is_symlink():
        unavailable_reason = "MARKER_UNAVAILABLE"
    elif shutil.which(descriptor["cli"]["executable"]) is None:
        unavailable_reason = "CLI_UNAVAILABLE"
    if unavailable_reason is not None:
        pre_status = _unavailable_status(unavailable_reason)
        bundle["pre_status"] = pre_status
        bundle["query"]["error"] = unavailable_reason
        bundle["delivery"] = {
            "state": "UNAVAILABLE",
            "record_status": "UNAVAILABLE",
            "reason": unavailable_reason,
            "checked_at": pre_status["checked_at"],
            "usage": "NO_GRAPH",
            "required_fallback": "SEARCH_SOURCE",
            "stale_points": [],
            "pending_changes": {"added": 0, "modified": 0, "removed": 0},
            "error": unavailable_reason,
        }
        _write_bundle(bundle_path, bundle)
        return {
            "bundle": bundle,
            "bundle_path": bundle_path,
            "response": None,
            "envelope": render_freshness_envelope(bundle),
        }

    pre_status = inspect_status(repo, descriptor, runner=runner)
    bundle["pre_status"] = pre_status
    effective_pre = pre_status
    if sync_if_needed and pre_status.get("needs_sync"):
        synchronized = synchronize_observed_status(
            repo, descriptor, pre_status, runner=runner
        )
        bundle["sync"] = synchronized["sync"]
        effective_pre = synchronized["freshness"]
        bundle["post_sync_status"] = effective_pre

    if effective_pre["status"] in {"UNAVAILABLE", "NOT_VERIFIED"}:
        bundle["query"]["status"] = (
            "UNAVAILABLE" if effective_pre["status"] == "UNAVAILABLE" else "FAILED"
        )
        bundle["query"]["error"] = effective_pre.get("error")
        if effective_pre["status"] == "UNAVAILABLE":
            bundle["delivery"] = {
                "state": "UNAVAILABLE",
                "record_status": "UNAVAILABLE",
                "reason": "PROVIDER_UNAVAILABLE",
                "checked_at": effective_pre["checked_at"],
                "usage": "NO_GRAPH",
                "required_fallback": "SEARCH_SOURCE",
                "stale_points": [],
                "pending_changes": {"added": 0, "modified": 0, "removed": 0},
                "error": effective_pre.get("error"),
            }
        else:
            bundle["delivery"] = _delivery(
                effective_pre,
                bundle["query"],
                None,
                None,
            )
        _write_bundle(bundle_path, bundle)
        return {
            "bundle": bundle,
            "bundle_path": bundle_path,
            "response": None,
            "envelope": render_freshness_envelope(bundle),
        }

    query_result = run_explore(repo, descriptor, query, runner=runner)
    bundle["query"].update({
        "status": query_result["status"],
        "response_sha256": query_result["response_sha256"],
        "error": query_result["error"],
    })
    response: str | None = query_result.get("response")
    classification: dict[str, Any] | None = None
    post_status: dict[str, Any] | None = None
    forced_unknown: str | None = None
    if query_result["status"] == "SUCCESS" and response is not None:
        actual_digest = hashlib.sha256(response.encode("utf-8")).hexdigest()
        if actual_digest != query_result["response_sha256"]:
            forced_unknown = "CodeGraph response digest mismatch"
            response = None
        else:
            classification = classify_response(repo, response)
            bundle["response_classification"] = classification
            if classification.get("response_sha256") != actual_digest:
                forced_unknown = "CodeGraph classification digest mismatch"
                response = None
            elif _unsafe_response(classification):
                forced_unknown = "CodeGraph response contains an unsafe repository path"
                response = None
            else:
                response_path.parent.mkdir(parents=True, exist_ok=True)
                confined_target(task_dir(repo, task_id), response_path, "CodeGraph response")
                write_text_atomic(response_path, response)
                if file_sha256(response_path) != actual_digest:
                    forced_unknown = "persisted CodeGraph response digest mismatch"
                    response_path.unlink()
                    response = None
                else:
                    bundle["response_path"] = response_path.relative_to(
                        task_dir(repo, task_id)
                    ).as_posix()
            post_status = inspect_status(repo, descriptor, runner=runner)
            bundle["post_query_status"] = post_status

    bundle["delivery"] = _delivery(
        effective_pre,
        bundle["query"],
        classification,
        post_status,
        forced_unknown=forced_unknown,
    )
    if response is None:
        bundle["response_path"] = None
    _write_bundle(bundle_path, bundle)
    return {
        "bundle": bundle,
        "bundle_path": bundle_path,
        "response": response,
        "envelope": render_freshness_envelope(bundle),
    }


def render_freshness_envelope(bundle: dict[str, Any]) -> str:
    """Render the finite freshness block that must precede graph content."""
    delivery = bundle["delivery"]
    pending = delivery.get("pending_changes") or {}
    error = " ".join(str(delivery.get("error") or "").split())[:240]
    bundle_path = task_relative_path(
        "code_intelligence_proxy_bundle",
        record_name=bundle["task_context"]["record_name"],
        query_id=bundle["query"]["id"],
    ).as_posix()
    lines = [
        "[POLARIS_CODEGRAPH_FRESHNESS]",
        f"state: {delivery['state']}",
        f"record_status: {delivery['record_status']}",
        f"reason: {delivery['reason']}",
        f"checked_at: {delivery['checked_at']}",
        f"pending_added: {pending.get('added', 0)}",
        f"pending_modified: {pending.get('modified', 0)}",
        f"pending_removed: {pending.get('removed', 0)}",
        f"usage: {delivery['usage']}",
        f"required_fallback: {delivery['required_fallback']}",
        f"evidence_bundle: {bundle_path}",
    ]
    if error:
        lines.append(f"error: {error}")
    lines.append("[/POLARIS_CODEGRAPH_FRESHNESS]")
    return "\n".join(lines) + "\n"
