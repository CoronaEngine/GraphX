"""Create, validate, and clean Polaris-owned vendored files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .polaris_core import (
    InputFailure,
    RuleFailure,
    file_sha256,
    validate_json_file,
    write_json_atomic,
)


INSTALL_MANIFEST_PATH = Path("tools/polaris/install-manifest.json")


def _safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuleFailure(f"install manifest path must be repository-relative: {value}")
    return path


def _relative(repo: Path, path: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise InputFailure(f"managed install path escapes target repository: {path}") from exc


def read_install_manifest(repo: Path, protocol_root: Path) -> dict[str, Any]:
    return validate_json_file(
        repo / INSTALL_MANIFEST_PATH,
        protocol_root / "schemas" / "install-manifest.schema.json",
    )


def build_install_manifest(
    repo: Path,
    polaris_version: str,
    managed_paths: Iterable[Path],
    preserved_paths: Iterable[Path],
) -> dict[str, Any]:
    managed: dict[str, str] = {}
    for path in managed_paths:
        relative = _relative(repo, path)
        if relative == INSTALL_MANIFEST_PATH.as_posix():
            continue
        if not path.is_file():
            raise InputFailure(f"managed vendored file is missing: {path}")
        managed[relative] = file_sha256(path)
    preserved = sorted({_relative(repo, path) for path in preserved_paths})
    overlap = set(managed) & set(preserved)
    if overlap:
        raise RuleFailure(
            f"install manifest mixes managed and preserved files: {', '.join(sorted(overlap))}"
        )
    return {
        "manifest_version": 1,
        "polaris_version": polaris_version,
        "managed_files": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(managed.items())
        ],
        "preserved_files": preserved,
    }


def write_install_manifest(repo: Path, manifest: dict[str, Any]) -> None:
    write_json_atomic(repo / INSTALL_MANIFEST_PATH, manifest)


def validate_install_manifest(repo: Path, protocol_root: Path) -> dict[str, Any]:
    manifest = read_install_manifest(repo, protocol_root)
    version = (protocol_root / "VERSION").read_text(encoding="utf-8").strip()
    if manifest["polaris_version"] != version:
        raise RuleFailure("install manifest Polaris version does not match vendored protocol")
    managed_paths = [item["path"] for item in manifest["managed_files"]]
    if len(managed_paths) != len(set(managed_paths)):
        raise RuleFailure("install manifest contains duplicate managed paths")
    preserved_paths = manifest["preserved_files"]
    if set(managed_paths) & set(preserved_paths):
        raise RuleFailure("install manifest path is both managed and preserved")
    for item in manifest["managed_files"]:
        path = repo / _safe_relative_path(item["path"])
        if not path.is_file():
            raise RuleFailure(f"managed vendored file is missing: {item['path']}")
        if file_sha256(path) != item["sha256"]:
            raise RuleFailure(f"managed vendored file hash mismatch: {item['path']}")
    for value in preserved_paths:
        path = repo / _safe_relative_path(value)
        if not path.is_file():
            raise RuleFailure(f"preserved vendored file is missing: {value}")
    return manifest


def remove_managed_files(repo: Path, manifest: dict[str, Any]) -> None:
    """Remove only files claimed as managed by a previous manifest."""
    for item in sorted(
        manifest["managed_files"],
        key=lambda value: len(Path(value["path"]).parts),
        reverse=True,
    ):
        relative = _safe_relative_path(item["path"])
        path = repo / relative
        if path.is_symlink() or path.is_file():
            path.unlink()
        parent = path.parent
        while parent != repo:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
