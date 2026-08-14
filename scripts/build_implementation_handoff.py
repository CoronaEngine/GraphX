#!/usr/bin/env python3
"""Build an immutable package for a fresh Implementer task."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from implementation_protocol import expected_attempt, validate_handoff_value
from polaris_core import (
    InputFailure,
    RuleFailure,
    current_work_item_path,
    directory_sha256,
    file_sha256,
    protocol_root,
    read_json,
    run_main,
    task_dir,
    utc_now,
    validate_json_file,
    write_json_atomic,
)
from review_protocol import normalized_reference
from working_set_protocol import validate_working_set


def _entry(repo: Path, role: str, path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(repo.resolve()).as_posix()
    except ValueError as exc:
        raise RuleFailure(f"Implementation package path escapes repository: {path}") from exc
    if resolved.is_file():
        kind = "file"
        digest = file_sha256(resolved)
    elif resolved.is_dir():
        kind = "directory"
        digest = directory_sha256(resolved)
    else:
        raise RuleFailure(f"Implementation package path does not exist: {path}")
    return {"role": role, "path": relative, "kind": kind, "sha256": digest}


def build(repo: Path, task_id: str) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = read_json(directory / "state.json")
    if state["status"] != "IMPLEMENTING":
        raise RuleFailure("Implementation handoff can only be built from IMPLEMENTING")
    revision = state["current_revision"]
    attempt, previous_review, base_commit = expected_attempt(root, directory, state)
    plan = normalized_reference(directory, state["artifacts"].get("plan"))
    working_set = normalized_reference(
        directory, state["artifacts"].get("working_set")
    )
    package = [
        _entry(repo, "project_rules", repo / "AGENTS.md"),
        _entry(repo, "work_item", current_work_item_path(directory, revision)),
        _entry(repo, "plan", directory / plan["path"]),
        _entry(repo, "working_set", directory / working_set["path"]),
    ]
    if previous_review is not None:
        package.append(
            _entry(repo, "previous_review", directory / previous_review["path"])
        )
    seen_paths = {entry["path"] for entry in package}
    working_set_path = directory / working_set["path"]
    working_set_value = validate_working_set(repo, task_id, working_set_path)
    for working_entry in working_set_value["entries"]:
        raw_path = working_entry["path"]
        if raw_path == ".polaris/project-index.json":
            continue
        candidate = (repo / raw_path).resolve()
        try:
            candidate.relative_to(repo.resolve())
        except ValueError as exc:
            raise RuleFailure(
                f"Working Set path escapes repository: {raw_path}"
            ) from exc
        if candidate.exists():
            entry = _entry(repo, "working_set_reference", candidate)
            if entry["path"] not in seen_paths:
                package.append(entry)
                seen_paths.add(entry["path"])
    handoff = {
        "task_id": task_id,
        "work_item_revision": revision,
        "artifact_attempt": attempt,
        "rigor": state["rigor"],
        "created_at": utc_now(),
        "preferred_isolation": "fresh_session",
        "subject_base_commit": base_commit,
        "previous_review": previous_review,
        "output_path": f"implementations/r{revision:03d}/attempt-{attempt:03d}.json",
        "progress_json_path": f".polaris/tasks/{task_id}/runtime/progress.json",
        "package": package,
    }
    path = (
        directory
        / "implementations"
        / f"r{revision:03d}"
        / f"handoff-{attempt:03d}.json"
    )
    if path.exists():
        existing = validate_json_file(
            path, root / "schemas" / "implementation-handoff.schema.json"
        )
        validate_handoff_value(repo, root, directory, state, existing, True)
        return {
            "message": f"reused Implementation handoff attempt {attempt}",
            "path": str(path),
            "artifact_attempt": attempt,
        }
    write_json_atomic(path, handoff)
    validate_json_file(path, root / "schemas" / "implementation-handoff.schema.json")
    validate_handoff_value(repo, root, directory, state, handoff, True)
    return {
        "message": f"built Implementation handoff attempt {attempt}",
        "path": str(path),
        "artifact_attempt": attempt,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: build(args.repo.resolve(), args.task_id), args.json)


if __name__ == "__main__":
    sys.exit(main())
