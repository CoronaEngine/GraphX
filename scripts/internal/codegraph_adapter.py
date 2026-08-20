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
    "⚠️ Some files referenced below were edited since the last index sync — "
    "their codegraph entries may be stale:\n"
)
_LEGACY_PARTIAL_BANNER_HEADER = _PARTIAL_BANNER_HEADER.replace(" — ", " —\n")
_PARTIAL_BANNER_FOOTER = (
    "For accurate content of those specific files, Read them directly."
)
_PARTIAL_BANNER_ROW = re.compile(
    r"^  - (?P<path>.+) \(edited [^\n()]+, "
    r"(?:pending sync|indexing in progress)\)$"
)
_DISABLED_BANNER_PREFIX = "⚠️ CodeGraph auto-sync is DISABLED —"
_WORKTREE_BANNER_PREFIX = (
    "⚠ CodeGraph results below come from a different git worktree"
)
_DRIFTED_FILE_HEADER = re.compile(
    r"^\*\*`(?P<path>[^`]+)`\*\* — .*⚠ changed "
    r"(?:since last index sync|on disk after the last index sync)"
)
_DRIFTED_PROJECT_TAIL_PREFIX = "> ⚠ Changed on disk after the last index sync:"
_PROJECT_PENDING_FOOTER = re.compile(
    r"^\(Note: (?P<count>[1-9][0-9]*) file\(s\) elsewhere in this project "
    r"are pending index sync but were not referenced above:$"
)
_PROJECT_PENDING_ROW = re.compile(r"^  - .+ \(edited [0-9]+ms ago\)$")
_PROJECT_PENDING_MORE = re.compile(r"^  - …and (?P<count>[1-9][0-9]*) more$")
_FILE_SECTION_HEADER = re.compile(r"^\*\*`[^`]+`\*\*(?: — .*)?$")
_EXPLICIT_WARNING_FRAMING = re.compile(
    r"(?:⚠|^\s*warning\s*:|^\s+pending[- ]sync(?:\s*:|\s+required\b))",
    re.IGNORECASE,
)
_PARTIAL_HEADER_VARIANTS = tuple(
    tuple(value.rstrip("\n").splitlines())
    for value in (_PARTIAL_BANNER_HEADER, _LEGACY_PARTIAL_BANNER_HEADER)
)


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


def _response_not_verified(
    checked_at: str,
    error: BaseException | str,
    *,
    stale_points: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    points = list(stale_points or [])
    unreadable = _index_point("STATUS_UNREADABLE")
    if unreadable not in points:
        points.append(unreadable)
    return _response_result(
        "NOT_VERIFIED",
        checked_at,
        stale_points=points,
        error=_error_summary(error),
    )


def _normalize_banner_path(raw_path: str) -> str:
    """Translate a safe Windows-relative banner path to portable POSIX form."""
    if (
        not raw_path
        or raw_path.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", raw_path) is not None
    ):
        raise ValueError(f"invalid CodeGraph stale path: {raw_path}")
    normalized = raw_path.replace("\\", "/")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ValueError(f"invalid CodeGraph stale path: {raw_path}")
    return normalized


def _response_file_point(repo: Path, raw_path: str) -> dict[str, Any]:
    path = _normalize_banner_path(raw_path)
    target = resolve_repo_reference(repo, path)
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
        "path": path,
        "reason": "PENDING_SYNC",
        "fallback": fallback,
        "observed_sha256": observed_sha256,
    }


def _framing_lines(response: str) -> tuple[list[str], bool]:
    """Return response lines outside fences and whether every fence closed."""
    lines: list[str] = []
    inside_fence = False
    for line in response.splitlines():
        if line.startswith("```"):
            inside_fence = not inside_fence
            continue
        if not inside_fence:
            lines.append(line)
    return lines, not inside_fence


def _with_response_sha256(result: dict[str, Any], response_sha256: str) -> dict[str, Any]:
    result["response_sha256"] = response_sha256
    return result


def _partial_header_length(lines: list[str], index: int) -> int:
    for header in _PARTIAL_HEADER_VARIANTS:
        if tuple(lines[index : index + len(header)]) == header:
            return len(header)
    return 0


def _append_unique_point(
    points: list[dict[str, Any]], point: dict[str, Any]
) -> None:
    if point not in points:
        points.append(point)


def _last_paragraph_start(lines: list[str]) -> int:
    end = len(lines)
    while end > 0 and lines[end - 1] == "":
        end -= 1
    start = end
    while start > 0 and lines[start - 1] != "":
        start -= 1
    return start


def classify_response(
    repo: Path,
    response: str,
    *,
    checked_at: str | None = None,
) -> dict[str, Any]:
    """Classify recognized freshness regions outside source-code fences.

    Leading whitespace and a UTF-8 BOM are not accepted as an official banner.
    """
    checked_at = _checked_at() if checked_at is None else checked_at
    if not isinstance(response, str):
        return _response_not_verified(checked_at, "CodeGraph response is not text")
    response_sha256 = hashlib.sha256(response.encode("utf-8")).hexdigest()
    normalized = response.replace("\r\n", "\n").replace("\r", "\n")
    framing, fences_balanced = _framing_lines(normalized)
    stale_points: list[dict[str, Any]] = []
    parse_error: str | None = None

    # Parse only consecutive recognized banners at the top. CodeGraph composes
    # the pending/degraded wrapper around the worktree notice, so more than one
    # banner can legitimately precede the first graph-result line.
    index = 0
    while index < len(framing):
        partial_header_length = _partial_header_length(framing, index)
        if partial_header_length:
            header_index = index
            index += partial_header_length
            matches: list[re.Match[str]] = []
            while index < len(framing):
                match = _PARTIAL_BANNER_ROW.fullmatch(framing[index])
                if match is None:
                    break
                matches.append(match)
                index += 1
            footer_present = (
                index < len(framing)
                and framing[index].startswith(_PARTIAL_BANNER_FOOTER)
            )
            if not matches or not footer_present:
                parse_error = parse_error or "malformed CodeGraph stale banner"
                index = header_index + partial_header_length
                while index < len(framing) and framing[index] != "":
                    index += 1
            else:
                index += 1
                for match in matches:
                    try:
                        _append_unique_point(
                            stale_points,
                            _response_file_point(repo, match["path"]),
                        )
                    except (InputFailure, RuleFailure, OSError, ValueError) as error:
                        parse_error = parse_error or _error_summary(error)
        elif framing[index].startswith(_DISABLED_BANNER_PREFIX):
            _append_unique_point(
                stale_points, _index_point("AUTO_SYNC_DISABLED")
            )
            index += 1
            if index < len(framing) and framing[index].startswith("  Reason: "):
                index += 1
        elif framing[index].startswith(_WORKTREE_BANNER_PREFIX):
            _append_unique_point(
                stale_points, _index_point("WORKTREE_MISMATCH")
            )
            index += 1
        else:
            break
        while index < len(framing) and framing[index] == "":
            index += 1

    # A known banner outside the top region is malformed framing, not ordinary
    # prose. This retains the legacy wrapped-banner safety behavior.
    for line_index in range(index, len(framing)):
        line = framing[line_index]
        worktree_mismatch = line.startswith(_WORKTREE_BANNER_PREFIX)
        if worktree_mismatch:
            _append_unique_point(
                stale_points, _index_point("WORKTREE_MISMATCH")
            )
        if (
            _partial_header_length(framing, line_index)
            or line.startswith(_DISABLED_BANNER_PREFIX)
            or worktree_mismatch
        ):
            parse_error = parse_error or "misplaced CodeGraph freshness banner"

    # Recognized per-file headers may occur between source fences throughout an
    # explore response. Generic words in prose and source are intentionally not
    # inspected.
    for line in framing:
        drifted = _DRIFTED_FILE_HEADER.match(line)
        if drifted is not None:
            try:
                _append_unique_point(
                    stale_points,
                    _response_file_point(repo, drifted["path"]),
                )
            except (InputFailure, RuleFailure, OSError, ValueError) as error:
                parse_error = parse_error or _error_summary(error)
        elif (
            _FILE_SECTION_HEADER.fullmatch(line)
            and _EXPLICIT_WARNING_FRAMING.search(line)
        ):
            parse_error = parse_error or "unrecognized CodeGraph file warning"

    # The current project-level pending footer is a final parenthesized region.
    # Validate its rows and count so similar prose cannot masquerade as framing.
    pending_footer_lines: set[int] = set()
    for footer_index, line in enumerate(framing):
        footer_match = _PROJECT_PENDING_FOOTER.fullmatch(line)
        if footer_match is None:
            continue
        tail_end = len(framing)
        while tail_end > footer_index + 1 and framing[tail_end - 1] == "":
            tail_end -= 1
        rows = framing[footer_index + 1 : tail_end]
        valid = bool(rows) and rows[-1].endswith(")")
        normalized_rows = list(rows)
        if valid:
            normalized_rows[-1] = normalized_rows[-1][:-1]
            observed_count = 0
            saw_more = False
            for row_index, row in enumerate(normalized_rows):
                if _PROJECT_PENDING_ROW.fullmatch(row):
                    if saw_more:
                        valid = False
                        break
                    observed_count += 1
                    continue
                more = _PROJECT_PENDING_MORE.fullmatch(row)
                if more is None or row_index != len(normalized_rows) - 1:
                    valid = False
                    break
                saw_more = True
                observed_count += int(more["count"])
            valid = valid and observed_count == int(footer_match["count"])
        if not valid:
            parse_error = parse_error or "malformed CodeGraph pending footer"
            continue
        pending_footer_lines.update(range(footer_index, tail_end))
        _append_unique_point(stale_points, _index_point("PENDING_CHANGES"))

    footer_start = _last_paragraph_start(framing)
    for line_index, line in enumerate(framing):
        if line.startswith(_DRIFTED_PROJECT_TAIL_PREFIX):
            if line_index < footer_start:
                parse_error = parse_error or "misplaced CodeGraph freshness footer"
            else:
                _append_unique_point(
                    stale_points, _index_point("PENDING_CHANGES")
                )

    # Unknown warning-like syntax is conservative only in framing positions:
    # the first top content line, recognized file headers, and a distinct final
    # epilogue paragraph. Ordinary non-framing prose is not keyword-scanned.
    first_content = next(
        (
            line_index
            for line_index in range(index, len(framing))
            if framing[line_index] != ""
        ),
        None,
    )
    if first_content is not None:
        line = framing[first_content]
        if (
            _DRIFTED_FILE_HEADER.match(line) is None
            and _PROJECT_PENDING_FOOTER.fullmatch(line) is None
            and not line.startswith(_DRIFTED_PROJECT_TAIL_PREFIX)
            and _EXPLICIT_WARNING_FRAMING.search(line)
        ):
            parse_error = parse_error or "unrecognized CodeGraph freshness warning"
    if footer_start > 0:
        for line_index in range(footer_start, len(framing)):
            line = framing[line_index]
            if (
                line_index not in pending_footer_lines
                and _DRIFTED_FILE_HEADER.match(line) is None
                and not line.startswith(_DRIFTED_PROJECT_TAIL_PREFIX)
                and _EXPLICIT_WARNING_FRAMING.search(line)
            ):
                parse_error = parse_error or "unrecognized CodeGraph freshness warning"

    if not fences_balanced:
        parse_error = parse_error or "unclosed CodeGraph Markdown fence"

    if parse_error is not None:
        result = _response_not_verified(
            checked_at, parse_error, stale_points=stale_points
        )
    elif any(point.get("scope") == "INDEX" for point in stale_points):
        result = _response_result(
            "INDEX_STALE", checked_at, stale_points=stale_points
        )
    elif stale_points:
        result = _response_result(
            "PARTIAL_STALE", checked_at, stale_points=stale_points
        )
    else:
        result = _response_result("NONE", checked_at, stale_points=[])
    return _with_response_sha256(result, response_sha256)


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

    # An unavailable provider cannot yield auditable CodeGraph response evidence.
    # Keep this result directly projectable to the v2 provider-neutral shape even
    # if a caller has already classified a response before learning availability.
    if status == "UNAVAILABLE":
        return {
            **status_result,
            "status": "UNAVAILABLE",
            "basis": ["NONE"],
            "stale_points": [],
            "response_sha256": None,
        }

    response_status = status if classification == "NONE" else classification
    merged_points = _unique_items(
        [
            *status_result.get("stale_points", []),
            *response_result.get("stale_points", []),
        ]
    )
    explicit_stale = any(
        point.get("reason") != "STATUS_UNREADABLE" for point in merged_points
    )
    if explicit_stale:
        merged_status = (
            "INDEX_STALE"
            if (
                status == "INDEX_STALE"
                or classification == "INDEX_STALE"
                or any(point.get("scope") == "INDEX" for point in merged_points)
            )
            else "PARTIAL_STALE"
        )
    else:
        merged_status = max(
            (status, response_status), key=FRESHNESS_ORDER.__getitem__
        )
    status_basis = status_result.get("basis", [])
    response_basis = response_result.get("basis", [])
    include_response_basis = merged_status != "UNAVAILABLE" and (
        classification != "NONE" or (
            status not in {"NOT_VERIFIED", "UNAVAILABLE"}
            and "STATUS_JSON" in status_basis
        )
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
        "stale_points": merged_points,
        "response_sha256": (
            response_result.get("response_sha256") if include_response_basis else None
        ),
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
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    timeout = _validated_timeout(timeout_seconds)
    command = [
        descriptor["cli"]["executable"],
        *descriptor["cli"][args_key],
        *(extra_args or []),
    ]
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
            needs_sync=any(pending.values()),
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
        return _unavailable(checked_at, "CodeGraph descriptor has an unsafe project marker")
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


def run_explore(
    repo: Path,
    descriptor: dict[str, Any],
    query: str,
    *,
    runner: Runner = subprocess.run,
    timeout_seconds: float = 60,
) -> dict[str, Any]:
    """Run exactly one bounded CodeGraph explore command in ``repo``."""
    checked_at = _checked_at()
    if not isinstance(query, str) or not query.strip():
        return {
            "status": "FAILED",
            "checked_at": checked_at,
            "response": None,
            "response_sha256": None,
            "error": "CodeGraph query must not be blank",
        }
    try:
        completed = _run_cli(
            repo,
            descriptor,
            "explore_args",
            timeout_seconds,
            runner,
            extra_args=[query],
        )
        raw, response_sha256 = _stdout_and_hash(completed)
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as error:
        return {
            "status": "FAILED",
            "checked_at": checked_at,
            "response": None,
            "response_sha256": None,
            "error": _error_summary(error),
        }
    if completed.returncode != 0:
        return {
            "status": "FAILED",
            "checked_at": checked_at,
            "response": None,
            "response_sha256": response_sha256,
            "error": f"CodeGraph explore exited with {completed.returncode}",
        }
    return {
        "status": "SUCCESS",
        "checked_at": checked_at,
        "response": raw,
        "response_sha256": response_sha256,
        "error": None,
    }


def _sync_result(status: str, response_sha256: str | None, error: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "response_sha256": response_sha256,
        "error": error,
    }


def _sync_failed(
    freshness: dict[str, Any],
    sync: dict[str, Any],
    *,
    post_sync_status: dict[str, Any] | None = None,
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
        "post_sync_status": post_sync_status,
    }


def synchronize_observed_status(
    repo: Path,
    descriptor: dict[str, Any],
    initial: dict[str, Any],
    *,
    runner: Runner = subprocess.run,
    status_timeout_seconds: float = 15,
    sync_timeout_seconds: float = 120,
    force_attempt: bool = False,
) -> dict[str, Any]:
    """Synchronize one already-observed status at most once, then recheck once."""
    try:
        if type(force_attempt) is not bool:
            raise ValueError("CodeGraph forced sync policy must be a boolean")
        status_timeout = _validated_timeout(status_timeout_seconds)
        sync_timeout = _validated_timeout(sync_timeout_seconds)
    except ValueError as error:
        freshness = _not_verified(_checked_at(), error)
        return {
            "freshness": freshness,
            "sync": _sync_result("SKIPPED", None, None),
            "post_sync_status": None,
        }
    skipped = _sync_result("SKIPPED", None, None)
    unavailable = _sync_result("UNAVAILABLE", None, None)
    if initial["status"] == "UNAVAILABLE" or _marker_path(repo, descriptor) is None:
        return {"freshness": initial, "sync": unavailable, "post_sync_status": None}
    if not force_attempt and not initial["needs_sync"]:
        return {"freshness": initial, "sync": skipped, "post_sync_status": None}

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
            post_sync_status=rechecked,
        )
    rechecked["basis"] = [*rechecked["basis"], "SYNC_ACKNOWLEDGED"]
    return {"freshness": rechecked, "sync": sync, "post_sync_status": rechecked}


def sync_if_needed(
    repo: Path,
    descriptor: dict[str, Any],
    *,
    runner: Runner = subprocess.run,
    status_timeout_seconds: float = 15,
    sync_timeout_seconds: float = 120,
) -> dict[str, Any]:
    """Inspect once, synchronize at most once, then inspect at most once more."""
    try:
        status_timeout = _validated_timeout(status_timeout_seconds)
        sync_timeout = _validated_timeout(sync_timeout_seconds)
    except ValueError as error:
        freshness = _not_verified(_checked_at(), error)
        return {"freshness": freshness, "sync": _sync_result("SKIPPED", None, None)}
    initial = inspect_status(
        repo, descriptor, runner=runner, timeout_seconds=status_timeout
    )
    result = synchronize_observed_status(
        repo,
        descriptor,
        initial,
        runner=runner,
        status_timeout_seconds=status_timeout,
        sync_timeout_seconds=sync_timeout,
    )
    return {"freshness": result["freshness"], "sync": result["sync"]}
