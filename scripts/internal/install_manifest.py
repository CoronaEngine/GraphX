"""Create and validate the ownership manifest for vendored Polaris files."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from .path_security import confined_target
from .polaris_core import (
    InputFailure,
    RuleFailure,
    file_sha256,
    validate_json_file,
    write_json_atomic,
)


INSTALL_MANIFEST_PATH = Path("tools/polaris/install-manifest.json")
MANIFEST_VERSION = 2
BYTE_HASH_MODE = "byte_sha256"
TEXT_HASH_MODE = "text_lf_sha256"
TEXT_FILE_NAMES = frozenset({"VERSION"})
TEXT_FILE_SUFFIXES = frozenset(
    {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
)


def managed_hash_mode(path: Path) -> str:
    """Choose a deterministic hash mode without treating unknown assets as text."""
    if path.name in TEXT_FILE_NAMES or path.suffix.lower() in TEXT_FILE_SUFFIXES:
        return TEXT_HASH_MODE
    return BYTE_HASH_MODE


def _canonical_text_bytes(path: Path) -> bytes:
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputFailure(f"managed text file is not UTF-8: {path}") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def managed_file_sha256(path: Path, hash_mode: str) -> str:
    if hash_mode == BYTE_HASH_MODE:
        return file_sha256(path)
    if hash_mode == TEXT_HASH_MODE:
        return _bytes_sha256(_canonical_text_bytes(path))
    raise RuleFailure(f"unsupported managed file hash mode: {hash_mode}")


def _legacy_hash_matches(path: Path, expected: str) -> bool:
    """Accept only newline-equivalent forms of known text files from v1 manifests."""
    if file_sha256(path) == expected:
        return True
    if managed_hash_mode(path) != TEXT_HASH_MODE:
        return False
    canonical = _canonical_text_bytes(path)
    crlf = canonical.replace(b"\n", b"\r\n")
    return expected in {_bytes_sha256(canonical), _bytes_sha256(crlf)}


def _validate_manifest_hash_contract(manifest: dict[str, Any]) -> None:
    version = manifest["manifest_version"]
    if version not in {1, MANIFEST_VERSION}:
        raise RuleFailure(f"unsupported install manifest version: {version}")
    for item in manifest["managed_files"]:
        hash_mode = item.get("hash_mode")
        if version == 1 and hash_mode is not None:
            raise RuleFailure("install manifest v1 must not declare hash_mode")
        if version == MANIFEST_VERSION and hash_mode is None:
            raise RuleFailure("install manifest v2 managed file lacks hash_mode")


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
    manifest = validate_json_file(
        confined_target(
            repo,
            repo / INSTALL_MANIFEST_PATH,
            "vendored install manifest",
        ),
        protocol_root / "schemas" / "install-manifest.schema.json",
    )
    _validate_manifest_hash_contract(manifest)
    return manifest


def build_install_manifest(
    repo: Path,
    polaris_version: str,
    managed_paths: Iterable[Path],
    preserved_paths: Iterable[Path],
) -> dict[str, Any]:
    managed: dict[str, tuple[str, str]] = {}
    for path in managed_paths:
        path = confined_target(repo, path, "managed vendored file")
        relative = _relative(repo, path)
        if relative == INSTALL_MANIFEST_PATH.as_posix():
            continue
        if not path.is_file():
            raise InputFailure(f"managed vendored file is missing: {path}")
        hash_mode = managed_hash_mode(path)
        managed[relative] = (hash_mode, managed_file_sha256(path, hash_mode))
    preserved = sorted(
        {
            _relative(repo, confined_target(repo, path, "preserved vendored file"))
            for path in preserved_paths
        }
    )
    overlap = set(managed) & set(preserved)
    if overlap:
        raise RuleFailure(
            f"install manifest mixes managed and preserved files: {', '.join(sorted(overlap))}"
        )
    return {
        "manifest_version": MANIFEST_VERSION,
        "polaris_version": polaris_version,
        "managed_files": [
            {"path": path, "hash_mode": hash_mode, "sha256": digest}
            for path, (hash_mode, digest) in sorted(managed.items())
        ],
        "preserved_files": preserved,
    }


def write_install_manifest(repo: Path, manifest: dict[str, Any]) -> None:
    write_json_atomic(
        confined_target(
            repo,
            repo / INSTALL_MANIFEST_PATH,
            "vendored install manifest",
        ),
        manifest,
    )


def install_manifest_paths(
    repo: Path, manifest: dict[str, Any], field: str
) -> tuple[Path, ...]:
    if field == "managed_files":
        values = [item["path"] for item in manifest[field]]
    elif field == "preserved_files":
        values = manifest[field]
    else:
        raise InputFailure(f"unsupported install manifest path field: {field}")
    return tuple(
        confined_target(
            repo,
            repo / _safe_relative_path(value),
            f"install manifest {field}",
        )
        for value in values
    )


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
        path = confined_target(
            repo,
            repo / _safe_relative_path(item["path"]),
            "managed vendored file",
        )
        if not path.is_file():
            raise RuleFailure(f"managed vendored file is missing: {item['path']}")
        if manifest["manifest_version"] == 1:
            matches = _legacy_hash_matches(path, item["sha256"])
        else:
            expected_mode = managed_hash_mode(path)
            if item["hash_mode"] != expected_mode:
                raise RuleFailure(
                    f"managed vendored file hash mode mismatch: {item['path']}"
                )
            matches = (
                managed_file_sha256(path, item["hash_mode"]) == item["sha256"]
            )
        if not matches:
            raise RuleFailure(f"managed vendored file hash mismatch: {item['path']}")
    for value in preserved_paths:
        path = confined_target(
            repo,
            repo / _safe_relative_path(value),
            "preserved vendored file",
        )
        if not path.is_file():
            raise RuleFailure(f"preserved vendored file is missing: {value}")
    return manifest
