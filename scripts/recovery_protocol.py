"""Small, deterministic projections used by fresh-session recovery."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from polaris_core import read_json, task_dir, write_text_atomic


NEXT_ACTIONS = {
    "DRAFT": "complete and freeze the Work Item, then QUALIFY",
    "QUALIFIED": "refresh the bounded Working Set, finish PLAN.md, then PLAN",
    "PLANNED": "satisfy any pre-approval and START_IMPLEMENTATION",
    "IMPLEMENTING": "finish the scoped implementation or Review rework and record evidence",
    "IMPLEMENTED": "synchronize documentation and durable knowledge, then SYNC_DOCS",
    "DOCS_SYNCED": "build the immutable Review handoff, START_REVIEW, then stop the implementer session",
    "REVIEWING": "use a fresh or isolated Reviewer session to review only the registered handoff",
    "REVIEWED": "prepare the acceptance evidence plan and START_VALIDATION",
    "VALIDATING": "run reproducible acceptance checks and record PASS or the correct failure edge",
    "VERIFIED": "write the Result artifact and request CLOSE through the mechanical gate",
    "BLOCKED": "resolve the recorded blocker with its Decision Owner, then RESOLVE_BLOCK or create a new revision",
    "CLOSED": "no action; the task is closed",
    "CANCELLED": "no action; the task is cancelled",
}


WORKING_SET_ENTRY = re.compile(r"^-\s+`([^`]+)`\s+—\s+(.+?)\s+—\s+(.+)$")


def recommended_action(state: dict[str, Any]) -> str:
    return NEXT_ACTIONS.get(state["status"], "inspect the workflow before acting")


def working_set_entries(path: Path) -> list[dict[str, str]]:
    section = ""
    entries: list[dict[str, str]] = []
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        match = WORKING_SET_ENTRY.fullmatch(line)
        if match:
            entries.append(
                {
                    "section": section,
                    "path": match.group(1),
                    "reason": match.group(2),
                    "discovered_from": match.group(3),
                }
            )
    return entries


def refresh_project_index(repo: Path) -> dict[str, Any]:
    project = read_json(repo / ".polaris" / "project.json")
    rows: list[dict[str, Any]] = []
    for task_id in sorted(project["active_tasks"]):
        directory = task_dir(repo, task_id)
        state = read_json(directory / "state.json")
        work_item = read_json(
            directory
            / "revisions"
            / f"work-item-r{state['current_revision']:03d}.json"
        )
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
    lines = [
        "# Project Recovery Map",
        "",
        "## Project",
        "",
        f"- Project: `{project['project_id']}`",
        f"- Active task records: {len(rows)}",
        "- Recommended next action: "
        + (
            f"`{recommended['task_id']}@r{recommended['revision']:03d}` — {recommended['next_action']}"
            if recommended
            else "initialize a task"
        ),
        "",
        "## Tasks",
        "",
    ]
    if rows:
        for row in rows:
            lines.append(
                f"- `{row['task_id']}@r{row['revision']:03d}` — {row['status']} — {row['title']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Blockers", ""])
    blockers = [row for row in rows if row["blocker"]]
    if blockers:
        for row in blockers:
            blocker = row["blocker"]
            lines.append(
                f"- `{row['task_id']}` — {blocker['type']} — {blocker['reason']} — owner: {blocker['decision_owner']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Executable", ""])
    if executable:
        for row in executable:
            lines.append(f"- `{row['task_id']}` — {row['next_action']}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Links",
            "",
            "- Project rules: `AGENTS.md`",
            "- Authority state: `.polaris/project.json`",
            "- Workflow: `.polaris/workflow.json`",
            "",
        ]
    )
    write_text_atomic(repo / ".polaris" / "project-index.md", "\n".join(lines))
    return {
        "tasks": rows,
        "recommended_task": recommended["task_id"] if recommended else None,
    }
