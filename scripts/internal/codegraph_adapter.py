"""Normalize CodeGraph CLI status and perform one bounded synchronization."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .polaris_core import InputFailure, RuleFailure, file_sha256
from .task_location_protocol import resolve_repo_reference


Runner = Callable[..., subprocess.CompletedProcess[str]]

_PENDING_KEYS = ("added", "modified", "removed")
_INDEX_REASONS = {
    "partial": "INDEX_PARTIAL",
    "indexing": "INDEX_INDEXING",
    "failed": "INDEX_FAILED",
}
FRESHNESS_ORDER = {
    "CURRENT_AT_CHECK": 0,
    "PARTIAL_STALE": 1,
    "NOT_VERIFIED": 2,
    "INDEX_STALE": 3,
    "UNAVAILABLE": 4,
}

_PARTIAL_BANNER_HEADER = (
    "⚠️ Some files referenced below were edited since the last index sync —\n"
    "their codegraph entries may be stale:\n"
)
_PARTIAL_BANNER_FOOTER = (
    "For accurate content of those specific files, Read them directly."
)
_PARTIAL_BANNER_ROW = re.compile(
    r"^  - (?P<path>.+) \(edited [^\n()]+, pending sync\)$"
)
_DISABLED_BANNER = "⚠️ CodeGraph auto-sync is DISABLED — the index is frozen."


def _checked_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _index_point(reason: str) -> dict[str, Any]:
    return {
        "scope": "INDEX",
        "path": None,
        "reason": reason,
        "fallback": "SEARCH_SOURCE",
        "observed_sha256": None,
    }


def _error_summary(error: BaseException | str) -> str:
    message = str(error).strip()
    return message[:240] if message else type(error).__name__


def _freshness(
    status: str,
    checked_at: str,
    *,
    basis: list[str],
    stale_points: list[dict[str, Any]],
    status_response_sha256: str | None,
    error: str | None,
    needs_sync: bool,
    pending_changes: dict[str, int] | None,
) -> dict[str, Any]:
    return {
        "status": status,
        "checked_at": checked_at,
        "basis": basis,
        "stale_points": stale_points,
        "status_response_sha256": status_response_sha256,
        "error": error,
        "needs_sync": needs_sync,
        "pending_changes": pending_changes,
    }


def _not_verified(
    checked_at: str,
    error: BaseException | str,
    response_sha256: str | None = None,
) -> dict[str, Any]:
    return _freshness(
        "NOT_VERIFIED",
        checked_at,
        basis=["STATUS_JSON"],
        stale_points=[_index_point("STATUS_UNREADABLE")],
        status_response_sha256=response_sha256,
        error=_error_summary(error),
        needs_sync=False,
        pending_changes=None,
    )


def _unavailable(checked_at: str, error: str) -> dict[str, Any]:
    return _freshness(
        "UNAVAILABLE",
        checked_at,
        basis=["NONE"],
        stale_points=[],
        status_response_sha256=None,
        error=error,
        needs_sync=False,
        pending_changes=None,
    )


def _response_result(
    classification: str,
    checked_at: str,
    *,
    stale_points: list[dict[str, Any]],
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "classification": classification,
        "checked_at": checked_at,
        "basis": ["RESPONSE_BANNER"],
        "stale_points": stale_points,
        "response_sha256": None,
        "error": error,
    }


def _response_not_verified(checked_at: str, error: BaseException | str) -> dict[str, Any]:
    return _response_result(
        "NOT_VERIFIED",
        checked_at,
        stale_points=[_index_point("STATUS_UNREADABLE")],
        error=_error_summary(error),
    )


def _response_file_point(repo: Path, raw_path: str) -> dict[str, Any]:
    target = resolve_repo_reference(repo, raw_path)
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise ValueError(f"CodeGraph stale path is not a regular file: {raw_path}")
        fallback = "READ_SOURCE"
        observed_sha256: str | None = file_sha256(target)
    else:
        fallback = "INSPECT_GIT_DIFF"
        observed_sha256 = None
    return {
        "scope": "FILE",
        "path": raw_path,
        "reason": "PENDING_SYNC",
        "fallback": fallback,
        "observed_sha256": observed_sha256,
    }


def classify_response(
    repo: Path,
    response: str,
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Classify only documented banners beginning at response byte zero.

    Leading whitespace and a UTF-8 BOM are not accepted as an official banner.
    """
    checked_at = _checked_at() if checked_at is None else checked_at
    if not isinstance(response, str):
        return _response_not_verified(checked_at, "CodeGraph response is not text")
    response_sha256 = hashlib.sha256(response.encode("utf-8")).hexdigest()
    normalized = response.replace("\r\n", "\n").replace("\r", "\n")
    if normalized.startswith(_DISABLED_BANNER):
        result = _response_result(
            "INDEX_STALE",
            checked_at,
            stale_points=[_index_point("AUTO_SYNC_DISABLED")],
        )
        result["response_sha256"] = response_sha256
        return result

    if not normalized.startswith(_PARTIAL_BANNER_HEADER):
        result = _response_result("NONE", checked_at, stale_points=[])
        result["response_sha256"] = response_sha256
        return result

    listed = normalized[len(_PARTIAL_BANNER_HEADER) :]
    footer_index = listed.find(_PARTIAL_BANNER_FOOTER)
    if footer_index < 0:
        result = _response_not_verified(checked_at, "malformed CodeGraph stale banner")
        result["response_sha256"] = response_sha256
        return result
    rows = listed[:footer_index].splitlines()
    if not rows or any(_PARTIAL_BANNER_ROW.fullmatch(row) is None for row in rows):
        result = _response_not_verified(checked_at, "malformed CodeGraph stale banner")
        result["response_sha256"] = response_sha256
        return result
    try:
        stale_points = [
            _response_file_point(repo, _PARTIAL_BANNER_ROW.fullmatch(row)["path"])
            for row in rows
        ]
    except (InputFailure, RuleFailure, OSError, ValueError) as error:
        result = _response_not_verified(checked_at, error)
        result["response_sha256"] = response_sha256
        return result
    result = _response_result("PARTIAL_STALE", checked_at, stale_points=stale_points)
    result["response_sha256"] = response_sha256
    return result


def _unique_items(items: list[Any]) -> list[Any]:
    result: list[Any] = []
    for item in items:
        if item not in result:
            result.append(item)
    return result


def merge_freshness(
    status_result: dict[str, Any], response_result: dict[str, Any]
) -> dict[str, Any]:
    """Merge an inspected status with one explore-response freshness conclusion."""
    status = status_result.get("status")
    classification = response_result.get("classification")
    if status not in FRESHNESS_ORDER or classification not in {
        "NONE",
        "PARTIAL_STALE",
        "INDEX_STALE",
        "NOT_VERIFIED",
    }:
        raise ValueError("unrecognized CodeGraph freshness result")

    response_status = status if classification == "NONE" else classification
    merged_status = max((status, response_status), key=FRESHNESS_ORDER.__getitem__)
    status_basis = status_result.get("basis", [])
    response_basis = response_result.get("basis", [])
    include_response_basis = classification != "NONE" or (
        status not in {"NOT_VERIFIED", "UNAVAILABLE"}
        and "STATUS_JSON" in status_basis
    )
    basis = _unique_items(
        [*status_basis, *(response_basis if include_response_basis else [])]
    )
    return {
        **status_result,
        "status": merged_status,
        "checked_at": response_result.get("checked_at")
        or status_result.get("checked_at"),
        "basis": basis,
        "stale_points": _unique_items(
            [*status_result.get("stale_points", []), *response_result.get("stale_points", [])]
        ),
        "response_sha256": response_result.get("response_sha256"),
        "error": status_result.get("error") or response_result.get("error"),
    }


def _marker_path(repo: Path, descriptor: dict[str, Any]) -> Path | None:
    marker = descriptor.get("project_marker")
    if not isinstance(marker, str):
        return None
    marker_path = Path(marker)
    if (
        marker_path.is_absolute()
        or len(marker_path.parts) != 1
        or marker_path.parts[0] in {".", ".."}
    ):
        return None
    return repo / marker_path


def _validated_timeout(timeout_seconds: Any) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("CodeGraph timeout must be a positive finite number")
    try:
        timeout = float(timeout_seconds)
    except OverflowError as error:
        raise ValueError("CodeGraph timeout must be a positive finite number") from error
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("CodeGraph timeout must be a positive finite number")
    return timeout


def _run_cli(
    repo: Path,
    descriptor: dict[str, Any],
    args_key: str,
    timeout_seconds: float,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    timeout = _validated_timeout(timeout_seconds)
    command = [descriptor["cli"]["executable"], *descriptor["cli"][args_key]]
    return runner(
        command,
        cwd=repo,
        check=False,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
    )


def _stdout_and_hash(completed: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    raw = completed.stdout
    if not isinstance(raw, str):
        raise UnicodeError("CodeGraph status output was not UTF-8 text")
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _pending_changes(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("pendingChanges must be an object")
    result: dict[str, int] = {}
    for key in _PENDING_KEYS:
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"pendingChanges.{key} must be a non-negative integer")
        result[key] = count
    return result


def _status_result(
    repo: Path,
    payload: Any,
    checked_at: str,
    response_sha256: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("CodeGraph status JSON must be an object")
    if payload.get("initialized") is not True:
        raise ValueError("CodeGraph status is not initialized")

    project_path = payload.get("projectPath")
    if not isinstance(project_path, str) or not project_path:
        raise ValueError("CodeGraph status projectPath must be a path")
    try:
        if Path(project_path).resolve() != repo.resolve():
            raise ValueError("CodeGraph status belongs to a different project")
    except (OSError, RuntimeError) as error:
        raise ValueError("CodeGraph status projectPath could not be resolved") from error

    pending = _pending_changes(payload.get("pendingChanges"))
    worktree_mismatch = payload.get("worktreeMismatch")
    if worktree_mismatch is not None and not isinstance(worktree_mismatch, Mapping):
        raise ValueError("worktreeMismatch must be null or an object")

    index = payload.get("index")
    if not isinstance(index, Mapping):
        raise ValueError("index must be an object")
    state = index.get("state")
    if state is not None and not isinstance(state, str):
        raise ValueError("index.state must be a string or null")
    pending_refs = index.get("pendingRefs")
    if (
        isinstance(pending_refs, bool)
        or not isinstance(pending_refs, int)
        or pending_refs < 0
    ):
        raise ValueError("index.pendingRefs must be a non-negative integer")
    reindex_recommended = index.get("reindexRecommended")
    if not isinstance(reindex_recommended, bool):
        raise ValueError("index.reindexRecommended must be a boolean")

    stale_reasons: list[str] = []
    if worktree_mismatch is not None:
        stale_reasons.append("WORKTREE_MISMATCH")
    if state in _INDEX_REASONS:
        stale_reasons.append(_INDEX_REASONS[state])
    elif state not in {None, "complete"}:
        raise ValueError("index.state is not recognized")
    if pending_refs:
        stale_reasons.append("PENDING_REFERENCES")
    if reindex_recommended:
        stale_reasons.append("REINDEX_RECOMMENDED")

    if stale_reasons:
        return _freshness(
            "INDEX_STALE",
            checked_at,
            basis=["STATUS_JSON"],
            stale_points=[_index_point(reason) for reason in stale_reasons],
            status_response_sha256=response_sha256,
            error=None,
            needs_sync=False,
            pending_changes=pending,
        )

    return _freshness(
        "CURRENT_AT_CHECK",
        checked_at,
        basis=["STATUS_JSON"],
        stale_points=[],
        status_response_sha256=response_sha256,
        error=None,
        needs_sync=any(pending.values()),
        pending_changes=pending,
    )


def inspect_status(
    repo: Path,
    descriptor: dict[str, Any],
    *,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    """Inspect one CodeGraph status response without changing the graph."""
    checked_at = _checked_at()
    try:
        timeout = _validated_timeout(timeout_seconds)
    except ValueError as error:
        return _not_verified(checked_at, error)
    marker = _marker_path(repo, descriptor)
    if marker is None:
        return _not_verified(checked_at, "CodeGraph descriptor has an unsafe project marker")
    if not marker.is_dir() or marker.is_symlink():
        return _unavailable(checked_at, "CodeGraph project marker is unavailable")
    try:
        completed = _run_cli(repo, descriptor, "status_args", timeout, runner)
        raw, response_sha256 = _stdout_and_hash(completed)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        return _not_verified(checked_at, error)
    except (KeyError, TypeError, ValueError) as error:
        return _not_verified(checked_at, error)
    if completed.returncode != 0:
        return _not_verified(
            checked_at,
            f"CodeGraph status exited with {completed.returncode}",
            response_sha256,
        )
    try:
        return _status_result(repo, json.loads(raw), checked_at, response_sha256)
    except (json.JSONDecodeError, OSError, RuntimeError, TypeError, ValueError) as error:
        return _not_verified(checked_at, error, response_sha256)


def _sync_result(status: str, response_sha256: str | None, error: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "response_sha256": response_sha256,
        "error": error,
    }


def _sync_failed(
    freshness: dict[str, Any],
    sync: dict[str, Any],
) -> dict[str, Any]:
    points = [*freshness["stale_points"], _index_point("SYNC_FAILED")]
    return {
        "freshness": {
            **freshness,
            "status": "INDEX_STALE",
            "stale_points": points,
            "needs_sync": False,
            "error": sync["error"] or freshness["error"],
        },
        "sync": sync,
    }


def sync_if_needed(
    repo: Path,
    descriptor: dict[str, Any],
    *,
    runner: Runner = subprocess.run,
    status_timeout_seconds: float = 15,
    sync_timeout_seconds: float = 120,
) -> dict[str, Any]:
    """Synchronize at most once, then inspect status at most once more."""
    try:
        status_timeout = _validated_timeout(status_timeout_seconds)
        sync_timeout = _validated_timeout(sync_timeout_seconds)
    except ValueError as error:
        freshness = _not_verified(_checked_at(), error)
        return {"freshness": freshness, "sync": _sync_result("SKIPPED", None, None)}
    initial = inspect_status(
        repo, descriptor, runner=runner, timeout_seconds=status_timeout
    )
    skipped = _sync_result("SKIPPED", None, None)
    unavailable = _sync_result("UNAVAILABLE", None, None)
    if initial["status"] == "UNAVAILABLE" or _marker_path(repo, descriptor) is None:
        return {"freshness": initial, "sync": unavailable}
    if not initial["needs_sync"]:
        return {"freshness": initial, "sync": skipped}

    try:
        completed = _run_cli(repo, descriptor, "sync_args", sync_timeout, runner)
        _, response_sha256 = _stdout_and_hash(completed)
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        return _sync_failed(initial, _sync_result("FAILED", None, _error_summary(error)))
    except (KeyError, TypeError, ValueError) as error:
        return _sync_failed(initial, _sync_result("FAILED", None, _error_summary(error)))
    if completed.returncode != 0:
        return _sync_failed(
            initial,
            _sync_result(
                "FAILED",
                response_sha256,
                f"CodeGraph sync exited with {completed.returncode}",
            ),
        )

    sync = _sync_result("SUCCESS", response_sha256, None)
    rechecked = inspect_status(
        repo, descriptor, runner=runner, timeout_seconds=status_timeout
    )
    if rechecked["status"] != "CURRENT_AT_CHECK" or rechecked["needs_sync"]:
        return _sync_failed(
            rechecked,
            _sync_result(
                "FAILED",
                response_sha256,
                "CodeGraph post-sync status is not current",
            ),
        )
    rechecked["basis"] = [*rechecked["basis"], "SYNC_ACKNOWLEDGED"]
    return {"freshness": rechecked, "sync": sync}
