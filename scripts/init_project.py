#!/usr/bin/env python3
"""Initialize repo-native Polaris authority state without overwriting files."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from polaris_core import (
    InputFailure,
    ensure_gitignore_rule,
    protocol_root,
    read_json,
    run_main,
    write_json_atomic,
)


def initialize(repo: Path, project_id: str) -> dict[str, str]:
    root = protocol_root(repo)
    polaris = repo / ".polaris"
    if polaris.exists():
        raise InputFailure(f"project is already initialized: {polaris}")
    (polaris / "tasks").mkdir(parents=True)
    (polaris / "decisions").mkdir()
    (polaris / "explorations").mkdir()
    template = read_json(root / "templates" / "project.json")
    template["project_id"] = project_id
    write_json_atomic(polaris / "project.json", template)
    shutil.copyfile(root / "workflow" / "default-workflow.json", polaris / "workflow.json")
    shutil.copyfile(root / "templates" / "project-index.md", polaris / "project-index.md")
    agents_path = repo / "AGENTS.md"
    if not agents_path.exists():
        shutil.copyfile(root / "templates" / "AGENTS.md", agents_path)
    ensure_gitignore_rule(repo, ".polaris/tasks/*/runtime/")
    return {"message": f"initialized Polaris project {project_id}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: initialize(args.repo.resolve(), args.project_id), args.json)


if __name__ == "__main__":
    sys.exit(main())
