#!/usr/bin/env python3
"""Vendor Polaris Skills and deterministic protocol files into a target repository."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any

from materialize_task_layout import materialize_template_tree
from internal.host_adapters import (
    adapter_file_target,
    adapter_skill_target,
    discover_skills,
    load_host_adapters,
    render_skill,
)
from internal.install_manifest import (
    INSTALL_MANIFEST_PATH,
    build_install_manifest,
    install_manifest_paths,
    read_install_manifest,
    validate_install_manifest,
    write_install_manifest,
)
from internal.polaris_core import (
    InputFailure,
    RuleFailure,
    ensure_gitignore_rule,
    process_is_running,
    run_main,
    utc_now,
    write_json_atomic,
    write_text_atomic,
)
from internal.path_security import (
    confined_target,
    require_regular_file,
    require_regular_tree,
)
from internal.task_layout import RUNTIME_IGNORE_PATTERN


TRANSACTION_VERSION = 1
TRANSACTION_PREFIX = "polaris-vendor-transaction-"


def ignore_generated(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}


def _polaris_destinations(
    target: Path, adapters: list[dict[str, Any]], skills: tuple[str, ...]
) -> list[Path]:
    destinations = [target / "tools" / "polaris"]
    for adapter in adapters:
        skill_target = adapter_skill_target(target, adapter)
        destinations.extend(
            confined_target(target, skill_target / name, "host Skill destination")
            for name in skills
        )
        destinations.extend(
            adapter_file_target(target, item)
            for item in adapter["files"]
            if item["overwrite"]
        )
    return destinations


def _transaction_directory_prefix(target: Path) -> str:
    return f".{target.name}-{TRANSACTION_PREFIX}"


def _transaction_directories(target: Path) -> list[Path]:
    prefix = _transaction_directory_prefix(target)
    return sorted(
        path for path in target.parent.iterdir() if path.name.startswith(prefix)
    )


def _safe_transaction_relative(value: object) -> Path:
    if not isinstance(value, str):
        raise InputFailure("vendor transaction path must be a string")
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise InputFailure(f"vendor transaction path is unsafe: {value}")
    return relative


def _read_transaction_journal(
    transaction_root: Path, target: Path
) -> dict[str, Any]:
    if transaction_root.is_symlink() or not transaction_root.is_dir():
        raise InputFailure(
            f"vendor transaction is not a regular directory: {transaction_root}"
        )
    journal_path = transaction_root / "journal.json"
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InputFailure(
            f"vendor transaction journal is missing or invalid: {journal_path}"
        ) from exc
    if not isinstance(journal, dict):
        raise InputFailure(f"vendor transaction journal is invalid: {journal_path}")
    required = {
        "transaction_version",
        "target",
        "status",
        "hostname",
        "pid",
        "created_at",
        "affected",
    }
    if set(journal) != required:
        raise InputFailure(f"vendor transaction journal has invalid fields: {journal_path}")
    if journal["transaction_version"] != TRANSACTION_VERSION:
        raise InputFailure(f"unsupported vendor transaction version: {journal_path}")
    if journal["target"] != str(target):
        raise InputFailure(f"vendor transaction target mismatch: {journal_path}")
    if journal["status"] not in {"STAGING", "PREPARED", "APPLYING", "COMMITTED"}:
        raise InputFailure(f"vendor transaction status is invalid: {journal_path}")
    if not isinstance(journal["hostname"], str) or not journal["hostname"]:
        raise InputFailure(f"vendor transaction hostname is invalid: {journal_path}")
    if not isinstance(journal["pid"], int) or journal["pid"] < 1:
        raise InputFailure(f"vendor transaction PID is invalid: {journal_path}")
    if not isinstance(journal["created_at"], str) or not journal["created_at"]:
        raise InputFailure(f"vendor transaction timestamp is invalid: {journal_path}")
    affected = journal["affected"]
    if not isinstance(affected, list):
        raise InputFailure(f"vendor transaction affected list is invalid: {journal_path}")
    seen: set[str] = set()
    for item in affected:
        if not isinstance(item, dict) or set(item) != {"path", "kind"}:
            raise InputFailure(
                f"vendor transaction affected entry is invalid: {journal_path}"
            )
        relative = _safe_transaction_relative(item["path"])
        if relative.as_posix() in seen or item["kind"] not in {
            "missing",
            "file",
            "directory",
        }:
            raise InputFailure(
                f"vendor transaction affected entry is invalid: {journal_path}"
            )
        seen.add(relative.as_posix())
        confined_target(target, target / relative, "vendor transaction target")
    return journal


def _write_transaction_journal(
    transaction_root: Path, journal: dict[str, Any], status: str
) -> None:
    updated = dict(journal)
    updated["status"] = status
    write_json_atomic(transaction_root / "journal.json", updated)
    journal.clear()
    journal.update(updated)


def _remove_path(path: Path) -> None:
    if path.is_symlink():
        raise RuleFailure(f"vendor transaction refuses to remove a symlink: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        if not path.is_file():
            raise RuleFailure(
                f"vendor transaction target is not a regular file or directory: {path}"
            )
        path.unlink()


def _copy_install_path(source: Path, destination: Path) -> None:
    """Copy one staged output into place; kept separate as an apply fault boundary."""
    if source.is_symlink():
        raise RuleFailure(f"staged vendor output must not be a symlink: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    elif source.is_file():
        shutil.copy2(source, destination)
    else:
        raise RuleFailure(f"staged vendor output is not regular: {source}")


def _restore_copy(source: Path, destination: Path, kind: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "directory":
        if source.is_symlink() or not source.is_dir():
            raise InputFailure(f"vendor transaction directory backup is missing: {source}")
        shutil.copytree(source, destination)
    else:
        if source.is_symlink() or not source.is_file():
            raise InputFailure(f"vendor transaction file backup is missing: {source}")
        shutil.copy2(source, destination)


def _restore_transaction(
    transaction_root: Path, target: Path, journal: dict[str, Any]
) -> None:
    backup_root = transaction_root / "backup"
    for item in journal["affected"]:
        relative = _safe_transaction_relative(item["path"])
        destination = confined_target(target, target / relative, "vendor rollback target")
        _remove_path(destination)
        if item["kind"] != "missing":
            _restore_copy(backup_root / relative, destination, item["kind"])


def _recover_vendor_transactions(target: Path) -> None:
    for transaction_root in _transaction_directories(target):
        journal = _read_transaction_journal(transaction_root, target)
        if (
            journal["hostname"] == socket.gethostname()
            and process_is_running(journal["pid"])
        ):
            raise InputFailure(
                f"another vendor transaction is still running: {transaction_root}"
            )
        if journal["hostname"] != socket.gethostname():
            raise InputFailure(
                f"vendor transaction belongs to another host: {transaction_root}"
            )
        if journal["status"] in {"PREPARED", "APPLYING"}:
            _restore_transaction(transaction_root, target, journal)
        shutil.rmtree(transaction_root)


def _stage_install(
    source: Path,
    target: Path,
    stage: Path,
    adapters: list[dict[str, Any]],
    skills: tuple[str, ...],
) -> dict[str, Any]:
    managed_paths: list[Path] = []
    preserved_paths: list[Path] = []
    for adapter in adapters:
        skill_target = adapter_skill_target(stage, adapter)
        for name in skills:
            source_skill = source / "skills" / name
            destination = confined_target(
                stage, skill_target / name, "staged host Skill destination"
            )
            shutil.copytree(source_skill, destination, ignore=ignore_generated)
            skill_path = destination / "SKILL.md"
            write_text_atomic(
                skill_path,
                render_skill(
                    skill_path.read_text(encoding="utf-8"),
                    name,
                    adapter,
                    set(skills),
                ),
            )
            overlay_root = adapter["skill_overlay_root"]
            if overlay_root is not None:
                overlay = adapter["adapter_root"] / overlay_root / name
                if overlay.is_dir():
                    shutil.copytree(overlay, destination, dirs_exist_ok=True)
            managed_paths.extend(path for path in destination.rglob("*") if path.is_file())
        for item in adapter["files"]:
            target_path = adapter_file_target(target, item)
            destination = adapter_file_target(stage, item)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if target_path.exists() and not item["overwrite"]:
                require_regular_file(target_path, "preserved host adapter file")
                shutil.copy2(target_path, destination)
            else:
                shutil.copy2(adapter["adapter_root"] / item["source"], destination)
            if item["overwrite"]:
                managed_paths.append(destination)
            else:
                preserved_paths.append(destination)

    tools_target = confined_target(
        stage, stage / "tools" / "polaris", "staged vendored protocol target"
    )
    tools_target.mkdir(parents=True)
    for name in ("VERSION", "pyproject.toml", "polaris_cli.py"):
        require_regular_file(source / name, f"Polaris {name} source")
        shutil.copy2(source / name, tools_target / name)
    for name in ("hosts", "scripts", "schemas", "skills", "templates", "workflow"):
        require_regular_tree(source / name, f"Polaris {name} source")
        shutil.copytree(source / name, tools_target / name, ignore=ignore_generated)
    materialize_template_tree(tools_target)

    target_gitignore = confined_target(target, target / ".gitignore", "preserved .gitignore")
    staged_gitignore = stage / ".gitignore"
    if target_gitignore.exists():
        require_regular_file(target_gitignore, "preserved .gitignore")
        shutil.copy2(target_gitignore, staged_gitignore)
    ensure_gitignore_rule(stage, RUNTIME_IGNORE_PATTERN)
    preserved_paths.append(staged_gitignore)

    managed_paths.extend(path for path in tools_target.rglob("*") if path.is_file())
    version = (tools_target / "VERSION").read_text(encoding="utf-8").strip()
    manifest = build_install_manifest(stage, version, managed_paths, preserved_paths)
    write_install_manifest(stage, manifest)
    validate_install_manifest(stage, tools_target)
    return manifest


def _collapse_affected_paths(target: Path, paths: list[Path]) -> list[Path]:
    confined = {
        confined_target(target, path, "vendor transaction affected path")
        for path in paths
    }
    collapsed: list[Path] = []
    for path in sorted(confined, key=lambda value: (len(value.parts), str(value))):
        if path == target:
            raise RuleFailure("vendor transaction must not replace the repository root")
        if any(parent == path or parent in path.parents for parent in collapsed):
            continue
        collapsed.append(path)
    return collapsed


def _affected_paths(
    target: Path,
    stage: Path,
    adapters: list[dict[str, Any]],
    skills: tuple[str, ...],
    staged_manifest: dict[str, Any],
    previous_manifest: dict[str, Any] | None,
) -> list[Path]:
    paths = _polaris_destinations(target, adapters, skills)
    for staged_path in install_manifest_paths(stage, staged_manifest, "managed_files"):
        paths.append(target / staged_path.relative_to(stage))
    for staged_path in install_manifest_paths(stage, staged_manifest, "preserved_files"):
        paths.append(target / staged_path.relative_to(stage))
    if previous_manifest is not None:
        paths.extend(install_manifest_paths(target, previous_manifest, "managed_files"))
    return _collapse_affected_paths(target, paths)


def _backup_affected_paths(
    target: Path, backup_root: Path, affected: list[Path]
) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in affected:
        relative = path.relative_to(target)
        if path.is_symlink():
            raise RuleFailure(f"vendor transaction target must not be a symlink: {path}")
        if path.is_dir():
            kind = "directory"
            shutil.copytree(path, backup_root / relative)
        elif path.exists():
            if not path.is_file():
                raise RuleFailure(f"vendor transaction target is not regular: {path}")
            kind = "file"
            destination = backup_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        else:
            kind = "missing"
        entries.append({"path": relative.as_posix(), "kind": kind})
    return entries


def _prune_empty_parents(path: Path, target: Path) -> None:
    parent = path.parent
    while parent != target:
        try:
            parent.rmdir()
        except OSError:
            break
        parent = parent.parent


def _apply_staged_install(stage: Path, target: Path, affected: list[Path]) -> None:
    for destination in affected:
        relative = destination.relative_to(target)
        staged_path = stage / relative
        _remove_path(destination)
        if staged_path.exists():
            _copy_install_path(staged_path, destination)
        else:
            _prune_empty_parents(destination, target)


def vendor(
    source: Path,
    target: Path,
    force: bool,
    discard_managed_changes: bool = False,
) -> dict[str, str]:
    source = source.absolute()
    target = target.absolute()
    if discard_managed_changes and not force:
        raise InputFailure("--discard-managed-changes requires --force")
    if not (target / ".git").exists():
        raise InputFailure(f"target is not a Git repository: {target}")
    confined_target(target, target, "target repository")
    _recover_vendor_transactions(target)

    skills = discover_skills(source)
    adapters = load_host_adapters(source)
    manifest_path = target / INSTALL_MANIFEST_PATH
    previous_manifest = (
        read_install_manifest(target, source) if manifest_path.is_file() else None
    )
    if not force and any(
        path.exists() for path in _polaris_destinations(target, adapters, skills)
    ):
        raise InputFailure("vendored Polaris files already exist; use --force to update")
    if force and previous_manifest is not None and not discard_managed_changes:
        validate_install_manifest(target, target / "tools" / "polaris")

    transaction_root = target.parent / (
        _transaction_directory_prefix(target) + "active"
    )
    try:
        transaction_root.mkdir()
    except FileExistsError as exc:
        raise InputFailure(
            f"another vendor transaction started concurrently: {transaction_root}"
        ) from exc
    stage = transaction_root / "stage"
    backup_root = transaction_root / "backup"
    stage.mkdir()
    backup_root.mkdir()
    journal: dict[str, Any] = {
        "transaction_version": TRANSACTION_VERSION,
        "target": str(target),
        "status": "STAGING",
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "created_at": utc_now(),
        "affected": [],
    }
    write_json_atomic(transaction_root / "journal.json", journal)
    try:
        staged_manifest = _stage_install(source, target, stage, adapters, skills)
        affected = _affected_paths(
            target, stage, adapters, skills, staged_manifest, previous_manifest
        )
        journal["affected"] = _backup_affected_paths(target, backup_root, affected)
        _write_transaction_journal(transaction_root, journal, "PREPARED")
        _write_transaction_journal(transaction_root, journal, "APPLYING")
        _apply_staged_install(stage, target, affected)
        validate_install_manifest(target, target / "tools" / "polaris")
        _write_transaction_journal(transaction_root, journal, "COMMITTED")
    except Exception as original:
        if journal["status"] in {"PREPARED", "APPLYING"}:
            try:
                _restore_transaction(transaction_root, target, journal)
            except Exception as rollback_error:
                raise InputFailure(
                    "vendored update failed and rollback could not complete; "
                    f"recover from {transaction_root}: {rollback_error}"
                ) from original
        shutil.rmtree(transaction_root)
        raise
    shutil.rmtree(transaction_root)
    return {"message": f"vendored Polaris into {target}", "target": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("target", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--discard-managed-changes", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: vendor(
            args.source.resolve(),
            args.target.resolve(),
            args.force,
            args.discard_managed_changes,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
