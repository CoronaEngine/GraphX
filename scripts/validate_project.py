#!/usr/bin/env python3
"""Validate project-level Polaris layout, versions, and active tasks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from internal.host_adapters import (
    adapter_file_target,
    adapter_skill_target,
    load_host_adapters,
)
from internal.install_manifest import validate_install_manifest
from internal.migration_protocol import validate_completed_migrations
from internal.polaris_core import RuleFailure, protocol_root, read_json, run_main, validate_json_file
from internal.recovery_protocol import project_index_value
from internal.task_layout import TASKS_ROOT
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
    index = validate_json_file(
        polaris / "project-index.json", root / "schemas" / "project-index.schema.json"
    )
    if index["project_id"] != project["project_id"]:
        raise RuleFailure("project recovery index targets the wrong project")
    if index != project_index_value(repo):
        raise RuleFailure("project recovery index is stale")

    for transition in workflow["transitions"]:
        alternate = transition.get("on_max_attempts_to")
        if alternate is not None and alternate not in states:
            raise RuleFailure(
                f"workflow transition has unknown max-attempt destination: {transition['event']}"
            )
        max_attempts = transition.get("max_attempts")
        if max_attempts is not None and (
            not isinstance(max_attempts, int) or max_attempts < 1
        ):
            raise RuleFailure(
                f"workflow transition has invalid max_attempts: {transition['event']}"
            )

    if root == repo / "tools" / "polaris":
        install_manifest = validate_install_manifest(repo, root)
        validate_completed_migrations(repo, root)
        managed_paths = {
            item["path"] for item in install_manifest["managed_files"]
        }
        preserved_paths = set(install_manifest["preserved_files"])
        for adapter in load_host_adapters(root):
            vendored_skills = adapter_skill_target(repo, adapter)
            missing = [
                name
                for name in sorted(EXPECTED_SKILLS)
                if not (vendored_skills / name / "SKILL.md").is_file()
            ]
            if missing:
                raise RuleFailure(
                    f"missing {adapter['display_name']} vendored Skills: "
                    f"{', '.join(missing)}"
                )
            untracked_skills = [
                (vendored_skills / name / "SKILL.md").relative_to(repo).as_posix()
                for name in sorted(EXPECTED_SKILLS)
                if (vendored_skills / name / "SKILL.md").relative_to(repo).as_posix()
                not in managed_paths
            ]
            if untracked_skills:
                raise RuleFailure(
                    f"unmanaged {adapter['display_name']} vendored Skills: "
                    f"{', '.join(untracked_skills)}"
                )
            missing_files = [
                item["target"]
                for item in adapter["files"]
                if not adapter_file_target(repo, item).is_file()
            ]
            if missing_files:
                raise RuleFailure(
                    f"missing {adapter['display_name']} adapter files: "
                    f"{', '.join(missing_files)}"
                )
            for item in adapter["files"]:
                relative = adapter_file_target(repo, item).relative_to(repo).as_posix()
                expected_paths = managed_paths if item["overwrite"] else preserved_paths
                if relative not in expected_paths:
                    ownership = "managed" if item["overwrite"] else "preserved"
                    raise RuleFailure(
                        f"{adapter['display_name']} adapter file is not {ownership}: "
                        f"{relative}"
                    )

    task_root = repo / TASKS_ROOT
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
    exploration_schema = root / "schemas" / "exploration.schema.json"
    for exploration_path in sorted((polaris / "explorations").glob("EXP-*.json")):
        exploration = validate_json_file(exploration_path, exploration_schema)
        if exploration["scope"] != "project" or not exploration["promoted_from"]:
            raise RuleFailure(f"invalid project exploration scope: {exploration_path}")
        source_path = (repo / exploration["promoted_from"]).resolve()
        try:
            source_path.relative_to(repo.resolve())
        except ValueError as exc:
            raise RuleFailure(
                f"project exploration source escapes repository: {exploration_path}"
            ) from exc
        if not source_path.is_file():
            raise RuleFailure(f"project exploration source is missing: {source_path}")
        source = validate_json_file(source_path, exploration_schema)
        expected = dict(source)
        expected["scope"] = "project"
        expected["promoted_from"] = exploration["promoted_from"]
        if exploration != expected:
            raise RuleFailure(
                f"project exploration differs from its promoted source: {exploration_path}"
            )
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
