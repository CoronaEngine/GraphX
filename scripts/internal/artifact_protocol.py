"""Safe loading and normalization of registered Polaris artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .polaris_core import RuleFailure, file_sha256, validate_json_file


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


def load_registered(
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
