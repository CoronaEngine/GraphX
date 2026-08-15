#!/usr/bin/env python3
"""Vendor Polaris Skills and deterministic protocol files into a target repository."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

from materialize_task_layout import materialize_template_tree
from internal.host_adapters import (
    adapter_file_target,
    adapter_skill_target,
    load_host_adapters,
    render_skill,
)
from internal.install_manifest import (
    INSTALL_MANIFEST_PATH,
    build_install_manifest,
    read_install_manifest,
    remove_managed_files,
    validate_install_manifest,
    write_install_manifest,
)
from internal.polaris_core import InputFailure, ensure_gitignore_rule, run_main
from internal.task_layout import RUNTIME_IGNORE_PATTERN


SKILLS = [
    "engineering-task",
    "requirement-analysis",
    "architecture-planning",
    "implementation",
    "adversarial-review",
    "validation",
    "documentation-sync",
]


def ignore_generated(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}


def _polaris_destinations(
    target: Path, adapters: list[dict[str, Any]]
) -> list[Path]:
    destinations = [target / "tools" / "polaris"]
    for adapter in adapters:
        skill_target = adapter_skill_target(target, adapter)
        destinations.extend(skill_target / name for name in SKILLS)
        destinations.extend(
            adapter_file_target(target, item)
            for item in adapter["files"]
            if item["overwrite"]
        )
    return destinations


def vendor(source: Path, target: Path, force: bool) -> dict[str, str]:
    if not (target / ".git").exists():
        raise InputFailure(f"target is not a Git repository: {target}")
    adapters = load_host_adapters(source)
    tools_target = target / "tools" / "polaris"
    manifest_path = target / INSTALL_MANIFEST_PATH
    previous_manifest = (
        read_install_manifest(target, source) if manifest_path.is_file() else None
    )
    if not force and any(
        path.exists() for path in _polaris_destinations(target, adapters)
    ):
        raise InputFailure("vendored Polaris files already exist; use --force to update")
    if force and previous_manifest is not None:
        remove_managed_files(target, previous_manifest)

    managed_paths: list[Path] = []
    preserved_paths: list[Path] = []
    for adapter in adapters:
        skill_target = adapter_skill_target(target, adapter)
        for name in SKILLS:
            source_skill = source / "skills" / name
            destination = skill_target / name
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source_skill, destination, ignore=ignore_generated)
            skill_path = destination / "SKILL.md"
            skill_path.write_text(
                render_skill(
                    skill_path.read_text(encoding="utf-8"),
                    name,
                    adapter,
                    set(SKILLS),
                ),
                encoding="utf-8",
            )
            overlay_root = adapter["skill_overlay_root"]
            if overlay_root is not None:
                overlay = adapter["adapter_root"] / overlay_root / name
                if overlay.is_dir():
                    shutil.copytree(overlay, destination, dirs_exist_ok=True)
            managed_paths.extend(path for path in destination.rglob("*") if path.is_file())
        for item in adapter["files"]:
            destination = adapter_file_target(target, item)
            if destination.exists() and not item["overwrite"]:
                preserved_paths.append(destination)
                continue
            if destination.exists():
                destination.unlink()
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(adapter["adapter_root"] / item["source"], destination)
            if item["overwrite"]:
                managed_paths.append(destination)
            else:
                preserved_paths.append(destination)

    if tools_target.exists():
        shutil.rmtree(tools_target)
    tools_target.mkdir(parents=True)
    shutil.copyfile(source / "VERSION", tools_target / "VERSION")
    for name in ("hosts", "scripts", "schemas", "templates", "workflow"):
        shutil.copytree(source / name, tools_target / name, ignore=ignore_generated)
    materialize_template_tree(tools_target)
    ensure_gitignore_rule(target, RUNTIME_IGNORE_PATTERN)
    preserved_paths.append(target / ".gitignore")
    managed_paths.extend(
        path
        for path in tools_target.rglob("*")
        if path.is_file() and path != manifest_path
    )
    version = (tools_target / "VERSION").read_text(encoding="utf-8").strip()
    manifest = build_install_manifest(
        target, version, managed_paths, preserved_paths
    )
    write_install_manifest(target, manifest)
    validate_install_manifest(target, tools_target)
    return {"message": f"vendored Polaris into {target}", "target": str(target)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: vendor(args.source.resolve(), args.target.resolve(), args.force), args.json
    )


if __name__ == "__main__":
    sys.exit(main())
