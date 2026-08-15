"""Resolve stable logical task references through movable physical task roots."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .path_security import confined_target
from .polaris_core import (
    InputFailure,
    RuleFailure,
    protocol_root,
    read_json,
    validate_json_file,
    write_json_atomic,
)
from .task_layout import TASKS_ROOT, task_root_relative_path


TASK_LOCATIONS_PATH = Path(".polaris/task-locations.json")
TASK_ID_PATTERN = re.compile(r"^TASK-[0-9]{4}$")


def task_locations_path(repo: Path) -> Path:
    return repo / TASK_LOCATIONS_PATH


def _validate_location_path(repo: Path, task_id: str, raw_path: str) -> Path:
    if "\\" in raw_path:
        raise RuleFailure(f"task location must use POSIX separators: {raw_path}")
    relative = Path(raw_path)
    if (
        relative.is_absolute()
        or relative.as_posix() != raw_path
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not relative.parts
        or relative.parts[0] != ".polaris"
        or relative.name != task_id
    ):
        raise RuleFailure(f"invalid physical location for {task_id}: {raw_path}")
    return confined_target(repo, repo / relative, f"physical location for {task_id}")


def load_task_locations(repo: Path, *, required: bool = True) -> dict[str, Path]:
    path = task_locations_path(repo)
    if not path.exists():
        if required:
            raise InputFailure(f"missing task location registry: {path}")
        return {}
    if path.is_symlink():
        raise RuleFailure(f"task location registry must not be a symlink: {path}")
    value = validate_json_file(
        path, protocol_root(repo) / "schemas" / "task-locations.schema.json"
    )
    locations: dict[str, Path] = {}
    physical_paths: set[Path] = set()
    for item in value["locations"]:
        task_id = item["task_id"]
        if task_id in locations:
            raise RuleFailure(f"duplicate task location identity: {task_id}")
        physical = _validate_location_path(repo, task_id, item["path"])
        if physical in physical_paths:
            raise RuleFailure(f"multiple tasks share physical location: {physical}")
        for existing in physical_paths:
            try:
                physical.relative_to(existing)
                overlaps = True
            except ValueError:
                try:
                    existing.relative_to(physical)
                    overlaps = True
                except ValueError:
                    overlaps = False
            if overlaps:
                raise RuleFailure(
                    f"task locations must not be nested: {physical}, {existing}"
                )
        locations[task_id] = physical
        physical_paths.add(physical)
    return locations


def task_location_value(task_ids: Iterable[str]) -> dict[str, Any]:
    return {
        "registry_version": 1,
        "locations": [
            {
                "task_id": task_id,
                "path": task_root_relative_path(task_id).as_posix(),
            }
            for task_id in sorted(task_ids)
        ],
    }


def initialize_task_locations(repo: Path, task_ids: Iterable[str]) -> dict[str, Path]:
    """Backfill the canonical registry for a project created before it existed."""
    path = task_locations_path(repo)
    expected_ids = set(task_ids)
    if path.exists():
        locations = load_task_locations(repo)
        if set(locations) != expected_ids:
            raise RuleFailure("task location registry differs from the project task list")
        return locations
    value = task_location_value(expected_ids)
    for item in value["locations"]:
        physical = _validate_location_path(repo, item["task_id"], item["path"])
        if not physical.is_dir():
            raise RuleFailure(f"task location does not exist: {physical}")
    write_json_atomic(path, value)
    return load_task_locations(repo)


def register_task_location(repo: Path, task_id: str, directory: Path) -> None:
    if TASK_ID_PATTERN.fullmatch(task_id) is None:
        raise InputFailure(f"invalid task id: {task_id}")
    locations = load_task_locations(repo)
    if task_id in locations:
        raise RuleFailure(f"task already has a physical location: {task_id}")
    physical = confined_target(repo, directory, f"physical location for {task_id}")
    if physical.name != task_id or not physical.is_dir():
        raise RuleFailure(f"invalid new task location: {physical}")
    relative = physical.relative_to(repo.absolute()).as_posix()
    _validate_location_path(repo, task_id, relative)
    value = validate_json_file(
        task_locations_path(repo),
        protocol_root(repo) / "schemas" / "task-locations.schema.json",
    )
    value["locations"].append({"task_id": task_id, "path": relative})
    value["locations"].sort(key=lambda item: item["task_id"])
    write_json_atomic(task_locations_path(repo), value)


def canonical_task_directory(repo: Path, task_id: str) -> Path:
    """Return the only physical location allowed when creating a new task."""
    if TASK_ID_PATTERN.fullmatch(task_id) is None:
        raise InputFailure(f"invalid task id: {task_id}")
    return confined_target(
        repo,
        repo / task_root_relative_path(task_id),
        f"canonical task location for {task_id}",
    )


def resolve_task_directory(repo: Path, task_id: str) -> Path:
    if TASK_ID_PATTERN.fullmatch(task_id) is None:
        raise InputFailure(f"invalid task id: {task_id}")
    registry_exists = task_locations_path(repo).exists()
    locations = load_task_locations(repo, required=False)
    if not registry_exists:
        project_path = repo / ".polaris" / "project.json"
        if project_path.is_file():
            project_version = read_json(project_path).get("polaris_version")
            protocol_version = (
                protocol_root(repo) / "VERSION"
            ).read_text(encoding="utf-8").strip()
            if project_version == protocol_version:
                raise InputFailure(
                    f"missing task location registry: {task_locations_path(repo)}"
                )
        return confined_target(
            repo,
            repo / task_root_relative_path(task_id),
            f"legacy task location for {task_id}",
        )
    if task_id not in locations:
        raise InputFailure(f"task has no registered physical location: {task_id}")
    return locations[task_id]


def logical_repo_path(repo: Path, path: Path) -> str:
    """Return a stable repo path, replacing physical task roots with logical roots."""
    resolved = path.resolve()
    repo_root = repo.resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise RuleFailure(f"path escapes repository: {path}") from exc
    locations = load_task_locations(repo, required=False)
    for task_id, physical in locations.items():
        try:
            suffix = resolved.relative_to(physical.resolve())
        except ValueError:
            continue
        return (task_root_relative_path(task_id) / suffix).as_posix()
    return resolved.relative_to(repo_root).as_posix()


def resolve_repo_reference(repo: Path, raw_path: str) -> Path:
    """Resolve a stable logical repo path without exposing physical task placement."""
    if "\\" in raw_path:
        raise RuleFailure(f"repository reference must use POSIX separators: {raw_path}")
    relative = Path(raw_path)
    if (
        relative.is_absolute()
        or relative.as_posix() != raw_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise RuleFailure(f"invalid repository reference: {raw_path}")
    parts = relative.parts
    if len(parts) >= 3 and parts[:2] == TASKS_ROOT.parts:
        task_id = parts[2]
        if TASK_ID_PATTERN.fullmatch(task_id) is None:
            raise RuleFailure(f"invalid logical task reference: {raw_path}")
        directory = resolve_task_directory(repo, task_id)
        target = directory.joinpath(*parts[3:])
        return confined_target(directory, target, f"logical task reference {raw_path}")
    return confined_target(repo, repo / relative, f"repository reference {raw_path}")


def validate_task_locations(
    repo: Path, expected_task_ids: Iterable[str]
) -> dict[str, Path]:
    locations = load_task_locations(repo)
    expected = set(expected_task_ids)
    if set(locations) != expected:
        raise RuleFailure(
            "task location registry mismatch; "
            f"registered={sorted(locations)}, expected={sorted(expected)}"
        )
    for task_id, directory in locations.items():
        if not directory.is_dir():
            raise RuleFailure(f"registered task location is missing: {task_id}")
    canonical_root = repo / TASKS_ROOT
    registered_paths = set(locations.values())
    unregistered = {
        path.name
        for path in canonical_root.glob("TASK-[0-9][0-9][0-9][0-9]")
        if path.is_dir() and path.absolute() not in registered_paths
    }
    if unregistered:
        raise RuleFailure(
            f"canonical task root contains unregistered tasks: {sorted(unregistered)}"
        )
    return locations
