#!/usr/bin/env python3
"""Record an immutable failed exploration and optionally promote it project-wide."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from polaris_core import (
    InputFailure,
    RuleFailure,
    protocol_root,
    read_json,
    run_main,
    task_dir,
    utc_now,
    validate_json_file,
    write_json_atomic,
)


EXPLORATION_ID = re.compile(r"^EXP-([0-9]{4})\.json$")


def _next_id(repo: Path) -> str:
    numbers: list[int] = []
    roots = [repo / ".polaris" / "explorations"]
    roots.extend((repo / ".polaris" / "tasks").glob("TASK-*/explorations"))
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.glob("EXP-*.json"):
            match = EXPLORATION_ID.fullmatch(path.name)
            if match:
                numbers.append(int(match.group(1)))
    return f"EXP-{max(numbers, default=0) + 1:04d}"


def record(
    repo: Path,
    task_id: str,
    module: str,
    hypothesis: str,
    attempt: str,
    evidence: str,
    outcome: str,
    failed_because: str,
    retry_when: str,
    related: list[str] | None = None,
) -> dict[str, Any]:
    if outcome not in {"rejected", "inconclusive"}:
        raise RuleFailure("exploration outcome must be rejected or inconclusive")
    required_text = {
        "module": module,
        "hypothesis": hypothesis,
        "attempt": attempt,
        "evidence": evidence,
        "failed_because": failed_because,
        "retry_when": retry_when,
    }
    missing = [name for name, value in required_text.items() if not value.strip()]
    if missing:
        raise RuleFailure(f"exploration requires non-empty fields: {missing}")
    directory = task_dir(repo, task_id)
    state = read_json(directory / "state.json")
    exploration_id = _next_id(repo)
    value = {
        "id": exploration_id,
        "scope": "task",
        "task": f"{task_id}@r{state['current_revision']:03d}",
        "module": module,
        "hypothesis": hypothesis,
        "attempt": attempt,
        "evidence": evidence,
        "outcome": outcome,
        "failed_because": failed_because,
        "retry_when": retry_when,
        "related": related or [],
        "recorded_at": utc_now(),
        "promoted_from": None,
    }
    path = directory / "explorations" / f"{exploration_id}.json"
    if path.exists():
        raise InputFailure(f"exploration is immutable and already exists: {path}")
    write_json_atomic(path, value)
    validate_json_file(
        path, protocol_root(repo) / "schemas" / "exploration.schema.json"
    )
    return {
        "message": f"recorded {exploration_id} for {value['task']}",
        "exploration_id": exploration_id,
        "path": str(path),
    }


def promote(repo: Path, task_id: str, exploration_id: str) -> dict[str, Any]:
    if re.fullmatch(r"EXP-[0-9]{4}", exploration_id) is None:
        raise InputFailure(f"invalid exploration ID: {exploration_id}")
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    source = directory / "explorations" / f"{exploration_id}.json"
    value = validate_json_file(source, root / "schemas" / "exploration.schema.json")
    if value["scope"] != "task" or not value["task"].startswith(f"{task_id}@"):
        raise RuleFailure("only a task-local exploration can be promoted by its task")
    destination = repo / ".polaris" / "explorations" / f"{exploration_id}.json"
    if destination.exists():
        raise InputFailure(f"project exploration is immutable and already exists: {destination}")
    promoted = dict(value)
    promoted["scope"] = "project"
    promoted["promoted_from"] = source.relative_to(repo).as_posix()
    write_json_atomic(destination, promoted)
    validate_json_file(destination, root / "schemas" / "exploration.schema.json")
    return {
        "message": f"promoted {exploration_id} to project knowledge",
        "exploration_id": exploration_id,
        "path": str(destination),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--promote")
    parser.add_argument("--module")
    parser.add_argument("--hypothesis")
    parser.add_argument("--attempt")
    parser.add_argument("--evidence")
    parser.add_argument("--outcome", choices=["rejected", "inconclusive"])
    parser.add_argument("--failed-because")
    parser.add_argument("--retry-when")
    parser.add_argument("--related", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.promote:
        action = lambda: promote(args.repo.resolve(), args.task_id, args.promote)
    else:
        required = {
            "--module": args.module,
            "--hypothesis": args.hypothesis,
            "--attempt": args.attempt,
            "--evidence": args.evidence,
            "--outcome": args.outcome,
            "--failed-because": args.failed_because,
            "--retry-when": args.retry_when,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            parser.error("recording requires " + ", ".join(missing))
        action = lambda: record(
            args.repo.resolve(),
            args.task_id,
            args.module,
            args.hypothesis,
            args.attempt,
            args.evidence,
            args.outcome,
            args.failed_because,
            args.retry_when,
            args.related,
        )
    return run_main(action, args.json)


if __name__ == "__main__":
    sys.exit(main())
