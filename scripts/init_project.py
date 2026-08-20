#!/usr/bin/env python3
"""Initialize repo-native Polaris authority state without overwriting files."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from internal.host_adapters import adapter_file_target, load_host_adapters
from internal.polaris_core import (
    InputFailure,
    ensure_gitignore_rule,
    protocol_root,
    read_json,
    run_main,
    write_json_atomic,
)
from internal.task_layout import (
    ARCHIVED_RUNTIME_IGNORE_PATTERN,
    RUNTIME_IGNORE_PATTERN,
    TASKS_ROOT,
)


def initialize(repo: Path, project_id: str) -> dict[str, str]:
    root = protocol_root(repo)
    polaris = repo / ".polaris"
    if polaris.exists():
        raise InputFailure(f"project is already initialized: {polaris}")
    (repo / TASKS_ROOT).mkdir(parents=True)
    (polaris / "decisions").mkdir()
    (polaris / "explorations").mkdir()
    template = read_json(root / "templates" / "project.json")
    template["project_id"] = project_id
    write_json_atomic(polaris / "project.json", template)
    write_json_atomic(
        polaris / "task-locations.json",
        read_json(root / "templates" / "task-locations.json"),
    )
    shutil.copyfile(root / "workflow" / "default-workflow.json", polaris / "workflow.json")
    index = read_json(root / "templates" / "project-index.json")
    index["project_id"] = project_id
    write_json_atomic(polaris / "project-index.json", index)
    agents_path = repo / "AGENTS.md"
    if not agents_path.exists():
        shutil.copyfile(root / "templates" / "AGENTS.md", agents_path)
    for adapter in load_host_adapters(root):
        for item in adapter["files"]:
            if item["overwrite"]:
                continue
            destination = adapter_file_target(repo, item)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(adapter["adapter_root"] / item["source"], destination)
    ensure_gitignore_rule(repo, RUNTIME_IGNORE_PATTERN)
    ensure_gitignore_rule(repo, ARCHIVED_RUNTIME_IGNORE_PATTERN)
    return {"message": f"initialized Polaris project {project_id}"}


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("project_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: initialize(args.repo.resolve(), args.project_id), args.json)


if __name__ == "__main__":
    sys.exit(main())
