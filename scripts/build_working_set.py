#!/usr/bin/env python3
"""Generate or refresh a bounded Working Set from explicit dependency reasons."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from polaris_core import (
    RuleFailure,
    current_work_item_path,
    read_json,
    run_main,
    task_dir,
    write_text_atomic,
)


SECTIONS = ["Documents", "Code", "Tests", "Decisions", "Explorations", "Unknowns"]
ENTRY = re.compile(r"^-\s+`([^`]+)`\s+—\s+(.+?)\s+—\s+(.+)$")


def _existing(path: Path) -> dict[str, dict[str, tuple[str, str]]]:
    result = {section: {} for section in SECTIONS}
    if not path.is_file():
        return result
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        match = ENTRY.fullmatch(line)
        if match and section in result:
            result[section][match.group(1)] = (match.group(2), match.group(3))
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
    state = read_json(directory / "state.json")
    work_item_path = current_work_item_path(directory, state["current_revision"])
    work_item = read_json(work_item_path)
    destination = directory / "WORKING_SET.md"
    entries = {section: {} for section in SECTIONS} if force else _existing(destination)

    _add(entries, "Documents", "AGENTS.md", "project rules", "recovery bootstrap")
    _add(
        entries,
        "Documents",
        ".polaris/project-index.md",
        "bounded project recovery map",
        "recovery bootstrap",
    )
    _add(
        entries,
        "Documents",
        work_item_path.relative_to(repo).as_posix(),
        "frozen execution contract",
        "task state",
    )
    _add(
        entries,
        "Documents",
        directory.joinpath("PLAN.md").relative_to(repo).as_posix(),
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

    for path in sorted((directory / "explorations").glob("EXP-*.json")):
        _add(
            entries,
            "Explorations",
            path.relative_to(repo).as_posix(),
            "task-local failed exploration",
            "task exploration index",
        )
    modules = set(work_item["affected_modules"])
    for path in _project_explorations(repo, modules):
        _add(
            entries,
            "Explorations",
            path.relative_to(repo).as_posix(),
            "project exploration matching an affected module",
            "work-item.affected_modules",
        )
    for value in explicit_entries or []:
        _add(entries, *_parse_explicit(value))
    for path in drop_paths or []:
        for section in SECTIONS:
            entries[section].pop(path, None)

    lines = [
        "# Working Set",
        "",
        f"Generated for `{task_id}@r{state['current_revision']:03d}`. Entries are `path — reason — discovered_from`.",
        "",
    ]
    total = 0
    for section in SECTIONS:
        lines.extend([f"## {section}", ""])
        if entries[section]:
            for path, (reason, source) in sorted(entries[section].items()):
                lines.append(f"- `{path}` — {reason} — {source}")
                total += 1
        else:
            lines.append("- None")
        lines.append("")
    write_text_atomic(destination, "\n".join(lines))
    return {
        "message": f"refreshed bounded Working Set with {total} entries",
        "path": str(destination),
        "entries": total,
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
