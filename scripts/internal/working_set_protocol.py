"""Validate and expose the structured bounded Working Set."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .polaris_core import (
    RuleFailure,
    protocol_root,
    read_json,
    task_dir,
    validate_schema,
)
from .task_layout import state_path, working_set_path
from .task_location_protocol import resolve_repo_reference


SECTIONS = ["Documents", "Code", "Tests", "Decisions", "Explorations", "Unknowns"]


def validate_working_set_value(
    repo: Path,
    task_id: str,
    state: dict[str, Any],
    value: dict[str, Any],
) -> dict[str, Any]:
    schema = read_json(protocol_root(repo) / "schemas" / "working-set.schema.json")
    errors = validate_schema(value, schema)
    if errors:
        raise RuleFailure("Working Set failed schema validation:\n- " + "\n- ".join(errors))
    if value["task_id"] != task_id:
        raise RuleFailure("Working Set targets the wrong task")
    if value["work_item_revision"] != state["current_revision"]:
        raise RuleFailure("Working Set targets the wrong Work Item revision")

    seen_paths: set[str] = set()
    for entry in value["entries"]:
        raw_path = entry["path"]
        if not entry["reason"].strip() or not entry["discovered_from"].strip():
            raise RuleFailure(
                f"Working Set entry lacks a dependency reason or discovery source: {raw_path}"
            )
        if raw_path in seen_paths:
            raise RuleFailure(f"Working Set contains duplicate path: {raw_path}")
        seen_paths.add(raw_path)
        if raw_path.startswith("<") and raw_path.endswith(">"):
            continue
        target = resolve_repo_reference(repo, raw_path)
        if entry["discovered_from"].startswith("CIQ-") and not target.exists():
            raise RuleFailure(f"Working Set path does not exist: {raw_path}")
    return value


def validate_working_set(
    repo: Path,
    task_id: str,
    path: Path | None = None,
) -> dict[str, Any]:
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    if path is None:
        path = working_set_path(directory)
    elif not path.is_absolute():
        path = directory / path
    return validate_working_set_value(repo, task_id, state, read_json(path))


def working_set_entries(value: dict[str, Any]) -> list[dict[str, str]]:
    return list(value["entries"])
