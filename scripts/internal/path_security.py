"""Filesystem confinement checks shared by vendoring and install validation."""

from __future__ import annotations

from pathlib import Path

from .polaris_core import RuleFailure


def require_regular_tree(root: Path, label: str) -> None:
    """Reject symlinks and special files anywhere in a source tree."""
    if root.is_symlink():
        raise RuleFailure(f"{label} must not be a symlink: {root}")
    if not root.is_dir():
        raise RuleFailure(f"{label} is missing: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuleFailure(f"{label} must not contain symlinks: {path}")
        if not path.is_dir() and not path.is_file():
            raise RuleFailure(f"{label} must contain only regular files: {path}")


def require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink():
        raise RuleFailure(f"{label} must not be a symlink: {path}")
    if not path.is_file():
        raise RuleFailure(f"{label} is missing: {path}")


def confined_target(repo: Path, path: Path, label: str) -> Path:
    """Require a lexical in-repo target with no existing symlink component."""
    repo = repo.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(repo)
    except ValueError as exc:
        raise RuleFailure(f"{label} escapes target repository: {path}") from exc
    cursor = repo
    if cursor.is_symlink():
        raise RuleFailure(f"target repository must not be a symlink: {repo}")
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise RuleFailure(f"{label} crosses a symlink: {cursor}")
    return path
