"""Shared standard-library helpers for Polaris v0.1 scripts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .task_layout import work_item_path as current_work_item_path


SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "additionalProperties",
    "const",
    "enum",
    "items",
    "minItems",
    "minLength",
    "minimum",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
    "uniqueItems",
}


class RuleFailure(Exception):
    """The input is readable but violates a Polaris rule (exit 1)."""


class InputFailure(Exception):
    """The input or environment is unusable (exit 2)."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        # Accept a UTF-8 BOM because Windows editors and PowerShell commonly emit it.
        # Polaris writers still produce canonical UTF-8 without a BOM.
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise InputFailure(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InputFailure(f"invalid JSON in {path}: {exc}") from exc


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", delete=False, dir=path.parent
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, indent=4, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", delete=False, dir=path.parent
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(value)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def ensure_gitignore_rule(repo: Path, rule: str) -> bool:
    """Append one exact ignore rule without disturbing existing user entries."""
    path = repo / ".gitignore"
    existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    if rule in {line.strip() for line in existing.splitlines()}:
        return False
    prefix = existing
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    write_text_atomic(path, prefix + rule + "\n")
    return True


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise InputFailure(f"missing file: {path}")
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise InputFailure(
                    f"invalid JSONL in {path} at line {line_number}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise InputFailure(f"event at {path}:{line_number} is not an object")
            events.append(value)
    return events


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def directory_sha256(path: Path) -> str:
    """Hash a directory snapshot by sorted relative path and file content hash."""
    if not path.is_dir():
        raise InputFailure(f"not a directory: {path}")
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(file_sha256(child)))
    return digest.hexdigest()


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, text=True, encoding="utf-8", capture_output=True
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise InputFailure(f"git {' '.join(args)} failed: {message}")
    return completed.stdout.strip()


def full_commit(repo: Path, revision: str = "HEAD") -> str:
    result = git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not re.fullmatch(r"[0-9a-f]{40}", result):
        raise InputFailure(f"not a full commit SHA: {result}")
    return result


def subject_diff_hash(repo: Path, base_commit: str, head_commit: str) -> str:
    """Hash Git's binary-safe patch representation for the subject commits."""
    completed = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff", base_commit, head_commit],
        cwd=repo,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise InputFailure(completed.stderr.decode("utf-8", errors="replace").strip())
    return hashlib.sha256(completed.stdout).hexdigest()


def protocol_root(repo: Path) -> Path:
    vendored = repo / "tools" / "polaris"
    if vendored.is_dir():
        return vendored
    return Path(__file__).resolve().parent.parent.parent


def workflow_path(repo: Path) -> Path:
    project_workflow = repo / ".polaris" / "workflow.json"
    if project_workflow.exists():
        return project_workflow
    return protocol_root(repo) / "workflow" / "default-workflow.json"


def require_protocol_compatible(
    repo: Path, state: dict[str, Any] | None = None
) -> dict[str, str]:
    """Reject normal writes while project, task, workflow, and tools disagree."""
    root = protocol_root(repo)
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    project = read_json(repo / ".polaris" / "project.json")
    workflow = read_json(repo / ".polaris" / "workflow.json")
    if project.get("polaris_version") != version:
        raise RuleFailure(
            "project Polaris version does not match vendored protocol; "
            "run the explicit migration before writing"
        )
    workflow_version = project.get("workflow_version")
    if not isinstance(workflow_version, str):
        raise RuleFailure("project workflow version is missing or invalid")
    if workflow.get("workflow_version") != workflow_version:
        raise RuleFailure("project and frozen workflow versions do not match")
    if state is not None:
        if state.get("polaris_version") != version:
            raise RuleFailure("task Polaris version does not match vendored protocol")
        if state.get("workflow_version") != workflow_version:
            raise RuleFailure("task workflow version does not match project workflow")
    return {
        "polaris_version": version,
        "workflow_version": workflow_version,
    }


def task_dir(repo: Path, task_id: str) -> Path:
    if not re.fullmatch(r"TASK-[0-9]{4}", task_id):
        raise InputFailure(f"invalid task id: {task_id}")
    from .task_location_protocol import resolve_task_directory

    return resolve_task_directory(repo, task_id)


def _matches_type(value: Any, expected: str) -> bool:
    mapping = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if expected not in mapping:
        raise InputFailure(f"unsupported schema type: {expected}")
    if expected in {"integer", "number"} and isinstance(value, bool):
        return False
    return isinstance(value, mapping[expected])


def _json_equal(left: Any, right: Any) -> bool:
    """Compare values using JSON Schema instance equality, not Python coercion."""
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        return (
            isinstance(left, (int, float))
            and not isinstance(left, bool)
            and isinstance(right, (int, float))
            and not isinstance(right, bool)
            and left == right
        )
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, str) or isinstance(right, str):
        return isinstance(left, str) and isinstance(right, str) and left == right
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(a, b) for a, b in zip(left, right))
        )
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict)
            and isinstance(right, dict)
            and left.keys() == right.keys()
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    return False


def validate_schema(value: Any, schema: dict[str, Any], location: str = "$") -> list[str]:
    """Validate the deliberately limited Polaris v0.1 schema subset."""
    unsupported = set(schema) - SUPPORTED_SCHEMA_KEYWORDS
    if unsupported:
        raise InputFailure(
            f"unsupported schema keyword at {location}: "
            f"{', '.join(sorted(unsupported))}"
        )
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, choice) for choice in choices):
            return [f"{location}: expected type {expected}"]

    if "enum" in schema and not any(
        _json_equal(value, candidate) for candidate in schema["enum"]
    ):
        errors.append(f"{location}: value {value!r} is not in enum")

    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{location}: value {value!r} does not equal const {schema['const']!r}")

    if isinstance(value, str) and "minLength" in schema:
        if len(value) < schema["minLength"]:
            errors.append(
                f"{location}: string length is below minLength {schema['minLength']}"
            )

    if isinstance(value, str) and "pattern" in schema:
        if re.fullmatch(schema["pattern"], value) is None:
            errors.append(f"{location}: value does not match {schema['pattern']}")

    if _matches_type(value, "number") and "minimum" in schema:
        if value < schema["minimum"]:
            errors.append(f"{location}: value is below minimum {schema['minimum']}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{location}: missing required property {key}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{location}: unexpected property {key}")
        for key, child_schema in properties.items():
            if key in value:
                errors.extend(validate_schema(value[key], child_schema, f"{location}.{key}"))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(
                f"{location}: item count is below minItems {schema['minItems']}"
            )
        if schema.get("uniqueItems") is True:
            duplicate = next(
                (
                    (left, right)
                    for right in range(1, len(value))
                    for left in range(right)
                    if _json_equal(value[left], value[right])
                ),
                None,
            )
            if duplicate is not None:
                errors.append(
                    f"{location}: items at indexes {duplicate[0]} and "
                    f"{duplicate[1]} are not unique"
                )
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(
                    validate_schema(item, schema["items"], f"{location}[{index}]")
                )
    return errors


def validate_json_file(path: Path, schema_path: Path) -> dict[str, Any]:
    value = read_json(path)
    schema = read_json(schema_path)
    errors = validate_schema(value, schema)
    if errors:
        raise RuleFailure(f"{path} failed schema validation:\n- " + "\n- ".join(errors))
    return value


def load_events_checked(path: Path) -> list[dict[str, Any]]:
    events = read_jsonl(path)
    if not events:
        raise InputFailure(f"event ledger is empty: {path}")
    for expected, event in enumerate(events):
        if event.get("sequence") != expected:
            raise InputFailure(
                f"event sequence is broken at index {expected}: {event.get('sequence')!r}"
            )
        if expected == 0:
            if event.get("event") != "INIT_TASK" or event.get("from") is not None:
                raise InputFailure("event 0 must be INIT_TASK from null")
        elif event.get("from") != events[expected - 1].get("to"):
            raise InputFailure(f"event {expected} does not continue the prior state")
    return events


def state_from_event(event: dict[str, Any]) -> dict[str, Any]:
    required = [
        "task_id",
        "polaris_version",
        "workflow_version",
        "current_revision",
        "to",
        "rigor",
        "sequence",
        "artifacts",
    ]
    missing = [key for key in required if key not in event]
    if missing:
        raise InputFailure(f"event {event.get('sequence')} lacks state fields: {missing}")
    return {
        "task_id": event["task_id"],
        "polaris_version": event["polaris_version"],
        "workflow_version": event["workflow_version"],
        "current_revision": event["current_revision"],
        "status": event["to"],
        "rigor": event["rigor"],
        "sequence": event["sequence"],
        "blocked_from": event.get("blocked_from"),
        "blocker": event.get("blocker"),
        "artifacts": event["artifacts"],
        "subject": event.get("subject"),
    }


def rebuild_state_value(events_path: Path) -> dict[str, Any]:
    events = load_events_checked(events_path)
    return state_from_event(events[-1])


def acquire_lock(path: Path) -> int:
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise InputFailure(f"task is locked: {path}") from exc


def process_is_running(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, wintypes.LPDWORD]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _write_lock_owner(descriptor: int, owner: dict[str, Any]) -> None:
    payload = (json.dumps(owner, indent=4, ensure_ascii=False) + "\n").encode("utf-8")
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        remaining = remaining[written:]
    os.fsync(descriptor)


def acquire_migration_lock(path: Path, migration_id: str, task_id: str) -> int:
    """Acquire a task lock, reclaiming only this migration's dead local owner."""
    owner = {
        "lock_version": 1,
        "kind": "polaris_migration",
        "migration_id": migration_id,
        "task_id": task_id,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "created_at": utc_now(),
    }
    try:
        descriptor = acquire_lock(path)
    except InputFailure as exc:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            raise InputFailure(
                f"task lock is not a recoverable migration lock: {path}"
            ) from exc
        if not isinstance(existing, dict):
            raise InputFailure(
                f"task lock is not a recoverable migration lock: {path}"
            ) from exc
        identity = (
            existing.get("lock_version") == 1
            and existing.get("kind") == "polaris_migration"
            and existing.get("migration_id") == migration_id
            and existing.get("task_id") == task_id
        )
        if not identity or existing.get("hostname") != owner["hostname"]:
            raise InputFailure(
                f"task lock belongs to another owner or migration: {path}"
            ) from exc
        pid = existing.get("pid")
        if not isinstance(pid, int) or pid < 1:
            raise InputFailure(f"migration lock has an invalid owner PID: {path}") from exc
        if process_is_running(pid):
            raise InputFailure(f"migration lock owner is still running: {path}") from exc
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        descriptor = acquire_lock(path)
    try:
        _write_lock_owner(descriptor, owner)
    except Exception:
        release_lock(path, descriptor)
        raise
    return descriptor


def release_lock(path: Path, descriptor: int) -> None:
    os.close(descriptor)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    status = payload.get("status", "UNKNOWN")
    message = payload.get("message", "")
    print(f"{status}: {message}" if message else status)


def run_main(action: Any, as_json: bool) -> int:
    try:
        payload = action()
        emit({"status": "PASS", **(payload or {})}, as_json)
        return 0
    except RuleFailure as exc:
        emit({"status": "FAIL", "message": str(exc)}, as_json)
        return 1
    except (InputFailure, OSError) as exc:
        emit({"status": "ERROR", "message": str(exc)}, as_json)
        return 2
