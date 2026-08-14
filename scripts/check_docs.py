#!/usr/bin/env python3
"""Ensure Knowledge Delta accounts for every changed subject path."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from polaris_core import (
    RuleFailure,
    full_commit,
    git,
    protocol_root,
    read_json,
    run_main,
    subject_diff_hash,
    task_dir,
    validate_json_file,
)
from task_layout import state_path


def check(
    repo: Path,
    task_id: str,
    knowledge_path: Path | None,
    subject_base: str | None = None,
    subject_head: str | None = None,
) -> dict[str, object]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    if knowledge_path is None:
        reference = state["artifacts"].get("knowledge_delta")
        if not reference:
            raise RuleFailure("state has no knowledge_delta artifact")
        raw = reference if isinstance(reference, str) else reference.get("path")
        knowledge_path = directory / raw
    elif not knowledge_path.is_absolute():
        knowledge_path = directory / knowledge_path
    knowledge = validate_json_file(
        knowledge_path, root / "schemas" / "knowledge-delta.schema.json"
    )
    if knowledge["task_id"] != task_id or knowledge["work_item_revision"] != state["current_revision"]:
        raise RuleFailure("Knowledge Delta targets the wrong task revision")
    stale = [entry["path"] for entry in knowledge["entries"] if entry["status"] == "STALE"]
    if stale:
        raise RuleFailure(f"Knowledge Delta has unresolved STALE entries: {stale}")
    if subject_base is not None or subject_head is not None:
        if not subject_base or not subject_head:
            raise RuleFailure("provide both subject_base and subject_head")
        base = full_commit(repo, subject_base)
        head = full_commit(repo, subject_head)
        subject = {
            "base_commit": base,
            "head_commit": head,
            "diff_hash": subject_diff_hash(repo, base, head),
        }
    else:
        subject = state.get("subject")
        if not isinstance(subject, dict):
            raise RuleFailure("task has no frozen subject")
    if (
        knowledge["subject_base_commit"] != subject["base_commit"]
        or knowledge["subject_head_commit"] != subject["head_commit"]
        or knowledge["subject_diff_hash"] != subject["diff_hash"]
    ):
        raise RuleFailure("Knowledge Delta targets the wrong documentation subject")
    changed = set(
        filter(
            None,
            git(repo, "diff", "--name-only", subject["base_commit"], subject["head_commit"]).splitlines(),
        )
    )
    covered = {
        changed_path
        for entry in knowledge["entries"]
        for changed_path in entry["changed_paths"]
    }
    unexplained = changed - covered
    unknown = covered - changed
    if unexplained or unknown:
        raise RuleFailure(
            f"Knowledge Delta path mismatch; unexplained={sorted(unexplained)}, unknown={sorted(unknown)}"
        )
    return {"message": f"documentation impact covers {len(changed)} changed paths", "changed_paths": len(changed)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument("--subject-base")
    parser.add_argument("--subject-head")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(
        lambda: check(
            args.repo.resolve(),
            args.task_id,
            args.knowledge,
            args.subject_base,
            args.subject_head,
        ),
        args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
