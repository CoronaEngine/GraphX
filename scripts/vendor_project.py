#!/usr/bin/env python3
"""Vendor Polaris Skills and deterministic protocol files into a target repository."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from polaris_core import InputFailure, run_main


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


def vendor(source: Path, target: Path, force: bool) -> dict[str, str]:
    if not (target / ".git").exists():
        raise InputFailure(f"target is not a Git repository: {target}")
    skill_target = target / ".agents" / "skills"
    tools_target = target / "tools" / "polaris"
    if not force and (skill_target.exists() or tools_target.exists()):
        raise InputFailure("vendored Polaris files already exist; use --force to update")

    for name in SKILLS:
        destination = skill_target / name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source / "skills" / name, destination, ignore=ignore_generated)

    if tools_target.exists():
        shutil.rmtree(tools_target)
    tools_target.mkdir(parents=True)
    shutil.copyfile(source / "VERSION", tools_target / "VERSION")
    for name in ("scripts", "schemas", "templates", "workflow"):
        shutil.copytree(source / name, tools_target / name, ignore=ignore_generated)
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
