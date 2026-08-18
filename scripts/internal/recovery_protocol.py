"""Small, deterministic indexes used by fresh-session recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .polaris_core import current_work_item_path, read_json, task_dir, write_json_atomic
from .task_layout import state_path


NEXT_ACTIONS = {
    "DRAFT": "complete and freeze the Work Item, then QUALIFY",
    "QUALIFIED": "refresh the bounded Working Set, finish PLAN.md, then PLAN",
    "PLANNED": "build the Implementer handoff and register it atomically with START_IMPLEMENTATION",
    "IMPLEMENTING": "complete implementation and documentation, then build the Review handoff and START_REVIEW",
    "REVIEWING": "use a fresh or isolated Reviewer session to review only the registered handoff",
    "VALIDATING": "run reproducible acceptance checks; PASS_AND_CLOSE for R0/R1 or PASS_VALIDATION for R2",
    "VERIFIED": "obtain R2 final approval, write the Result, and request CLOSE through the mechanical gate",
    "BLOCKED": "resolve the recorded blocker with its Decision Owner, then RESOLVE_BLOCK or create a new revision",
    "CLOSED": "no action; the task is closed",
    "CANCELLED": "no action; the task is cancelled",
}


def recommended_action(state: dict[str, Any]) -> str:
    if (
        state["status"] == "BLOCKED"
        and state.get("blocker", {}).get("type") == "review_dispute"
    ):
        return "have the Human Decision Owner choose NEW_REVISION or CANCEL"
    if (
        state["status"] == "IMPLEMENTING"
        and "implementation_handoff" not in state["artifacts"]
    ):
        return (
            "build the next Implementer handoff and register it atomically with "
            "START_IMPLEMENTATION"
        )
    return NEXT_ACTIONS.get(state["status"], "inspect the workflow before acting")


def project_index_value(repo: Path) -> dict[str, Any]:
    project = read_json(repo / ".polaris" / "project.json")
    rows: list[dict[str, Any]] = []
    for task_id in sorted(project["active_tasks"]):
        directory = task_dir(repo, task_id)
        state = read_json(state_path(directory))
        work_item = read_json(current_work_item_path(directory, state["current_revision"]))
        rows.append(
            {
                "task_id": task_id,
                "revision": state["current_revision"],
                "status": state["status"],
                "title": work_item["title"],
                "blocker": state.get("blocker"),
                "next_action": recommended_action(state),
            }
        )

    executable = [
        row for row in rows if row["status"] not in {"BLOCKED", "CLOSED", "CANCELLED"}
    ]
    recommended = executable[0] if executable else (rows[0] if rows else None)
    return {
        "project_id": project["project_id"],
        "recommended_task": recommended["task_id"] if recommended else None,
        "recommended_next_action": (
            recommended["next_action"] if recommended else "initialize a task"
        ),
        "tasks": rows,
        "links": {
            "project_rules": "AGENTS.md",
            "authority_state": ".polaris/project.json",
            "workflow": ".polaris/workflow.json",
        },
    }


def refresh_project_index(repo: Path) -> dict[str, Any]:
    value = project_index_value(repo)
    write_json_atomic(repo / ".polaris" / "project-index.json", value)
    return value
