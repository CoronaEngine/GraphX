#!/usr/bin/env python3
"""Validate project-level Polaris layout, versions, and active tasks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from polaris_core import RuleFailure, protocol_root, read_json, run_main, validate_json_file
from validate_task import validate as validate_task


EXPECTED_SKILLS = {
    "engineering-task",
    "requirement-analysis",
    "architecture-planning",
    "implementation",
    "adversarial-review",
    "validation",
    "documentation-sync",
}


def validate(repo: Path) -> dict[str, object]:
    root = protocol_root(repo)
    polaris = repo / ".polaris"
    project = validate_json_file(
        polaris / "project.json", root / "schemas" / "project.schema.json"
    )
    workflow = validate_json_file(
        polaris / "workflow.json", root / "schemas" / "workflow.schema.json"
    )
    states = workflow["states"]
    if len(states) != len(set(states)):
        raise RuleFailure("workflow contains duplicate states")
    if workflow["initial_state"] not in states or not set(workflow["terminal_states"]).issubset(states):
        raise RuleFailure("workflow initial or terminal states are not declared")
    events: set[str] = set()
    for transition in workflow["transitions"]:
        required = {"event", "from", "to", "gate"}
        if not required.issubset(transition):
            raise RuleFailure(f"workflow transition lacks fields: {transition}")
        if transition["event"] in events:
            raise RuleFailure(f"workflow event is duplicated: {transition['event']}")
        events.add(transition["event"])
        if not set(transition["from"]).issubset(states):
            raise RuleFailure(f"workflow transition has unknown source: {transition['event']}")
        if transition["to"] != "$blocked_from" and transition["to"] not in states:
            raise RuleFailure(f"workflow transition has unknown destination: {transition['event']}")
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if project["polaris_version"] != version:
        raise RuleFailure("project Polaris version does not match vendored protocol")
    if project["workflow_version"] != workflow["workflow_version"]:
        raise RuleFailure("project and workflow versions do not match")

    vendored_skills = repo / ".agents" / "skills"
    if root == repo / "tools" / "polaris":
        missing = [
            name for name in sorted(EXPECTED_SKILLS) if not (vendored_skills / name / "SKILL.md").is_file()
        ]
        if missing:
            raise RuleFailure(f"missing vendored Skills: {', '.join(missing)}")

    task_root = polaris / "tasks"
    listed = set(project["active_tasks"])
    actual = {path.name for path in task_root.glob("TASK-[0-9][0-9][0-9][0-9]") if path.is_dir()}
    orphaned = actual - listed
    missing = listed - actual
    if orphaned or missing:
        raise RuleFailure(
            f"task index mismatch; orphaned={sorted(orphaned)}, missing={sorted(missing)}"
        )
    for task_id in sorted(listed):
        validate_task(repo, task_id)
    return {
        "message": f"project {project['project_id']} is valid",
        "project": project["project_id"],
        "active_tasks": len(listed),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: validate(args.repo.resolve()), args.json)


if __name__ == "__main__":
    sys.exit(main())
