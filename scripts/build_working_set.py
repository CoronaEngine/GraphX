#!/usr/bin/env python3
"""Generate or refresh a bounded Working Set from explicit dependency reasons."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from internal.polaris_core import (
    RuleFailure,
    current_work_item_path,
    protocol_root,
    read_json,
    require_protocol_compatible,
    run_main,
    task_dir,
    validate_json_file,
    write_json_atomic,
)
from internal.working_set_protocol import SECTIONS, validate_working_set_value
from internal.task_location_protocol import logical_repo_path
from internal.task_layout import explorations_dir, plan_path, state_path, working_set_path


def _existing(
    repo: Path,
    path: Path,
    current_revision: int,
) -> dict[str, dict[str, tuple[str, str]]]:
    result = {section: {} for section in SECTIONS}
    if not path.is_file():
        return result
    value = validate_json_file(
        path, protocol_root(repo) / "schemas" / "working-set.schema.json"
    )
    if value["work_item_revision"] != current_revision:
        return result
    for entry in value["entries"]:
        result[entry["section"]][entry["path"]] = (
            entry["reason"],
            entry["discovered_from"],
        )
    return result


def _add(
    entries: dict[str, dict[str, tuple[str, str]]],
    section: str,
    path: str,
    reason: str,
    discovered_from: str,
) -> None:
    if section not in entries:
        raise RuleFailure(f"unknown Working Set section: {section}")
    if not all(value.strip() for value in (path, reason, discovered_from)):
        raise RuleFailure("Working Set entries require path, reason, and discovered_from")
    entries[section][path] = (reason, discovered_from)


def _parse_explicit(value: str) -> tuple[str, str, str, str]:
    parts = value.split("|", 3)
    if len(parts) != 4:
        raise RuleFailure(
            "--entry must be SECTION|PATH|REASON|DISCOVERED_FROM"
        )
    return parts[0], parts[1], parts[2], parts[3]


def _project_explorations(repo: Path, modules: set[str]) -> list[Path]:
    matches: list[Path] = []
    for path in sorted((repo / ".polaris" / "explorations").glob("EXP-*.json")):
        value = read_json(path)
        module = value.get("module")
        if isinstance(module, str) and module in modules:
            matches.append(path)
    return matches


def build(
    repo: Path,
    task_id: str,
    force: bool,
    explicit_entries: list[str] | None = None,
    drop_paths: list[str] | None = None,
) -> dict[str, Any]:
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    require_protocol_compatible(repo, state)
    work_item_path = current_work_item_path(directory, state["current_revision"])
    work_item = read_json(work_item_path)
    destination = working_set_path(directory)
    entries = (
        {section: {} for section in SECTIONS}
        if force
        else _existing(repo, destination, state["current_revision"])
    )

    _add(entries, "Documents", "AGENTS.md", "project rules", "recovery bootstrap")
    _add(
        entries,
        "Documents",
        ".polaris/project-index.json",
        "bounded project recovery map",
        "recovery bootstrap",
    )
    _add(
        entries,
        "Documents",
        logical_repo_path(repo, work_item_path),
        "frozen execution contract",
        "task state",
    )
    _add(
        entries,
        "Documents",
        logical_repo_path(repo, plan_path(directory)),
        "delta plan and acceptance mapping",
        "task state",
    )
    for module in work_item["affected_modules"]:
        _add(entries, "Code", module, "affected module entry point", "work-item.affected_modules")
    for acceptance in work_item["acceptance"]:
        _add(
            entries,
            "Tests",
            f"<{acceptance['id']}-evidence>",
            acceptance["evidence"],
            f"work-item.acceptance.{acceptance['id']}",
        )
    for unknown in work_item["known_unknowns"]:
        _add(
            entries,
            "Unknowns",
            f"<{unknown}>",
            "unresolved question",
            "work-item.known_unknowns",
        )

    for path in sorted(explorations_dir(directory).glob("EXP-*.json")):
        _add(
            entries,
            "Explorations",
            logical_repo_path(repo, path),
            "task-local failed exploration",
            "task exploration index",
        )
    modules = set(work_item["affected_modules"])
    for path in _project_explorations(repo, modules):
        _add(
            entries,
            "Explorations",
            logical_repo_path(repo, path),
            "project exploration matching an affected module",
            "work-item.affected_modules",
        )
    for value in explicit_entries or []:
        _add(entries, *_parse_explicit(value))
    for path in drop_paths or []:
        for section in SECTIONS:
            entries[section].pop(path, None)

    output_entries: list[dict[str, str]] = []
    for section in SECTIONS:
        for path, (reason, source) in sorted(entries[section].items()):
            output_entries.append(
                {
                    "section": section,
                    "path": path,
                    "reason": reason,
                    "discovered_from": source,
                }
            )
    value = {
        "task_id": task_id,
        "work_item_revision": state["current_revision"],
        "entries": output_entries,
    }
    validate_working_set_value(repo, task_id, state, value)
    write_json_atomic(destination, value)
    return {
        "message": f"refreshed bounded Working Set with {len(output_entries)} entries",
        "path": str(destination),
        "entries": len(output_entries),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--force",
        action="store_true",
        help="reset prior cache entries before regenerating",
    )
    parser.add_argument(
        "--entry",
        action="append",
        default=[],
        help="SECTION|PATH|REASON|DISCOVERED_FROM",
    )
    parser.add_argument("--drop", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: build(
            args.repo.resolve(),
            args.task_id,
            args.force,
            args.entry,
            args.drop,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
