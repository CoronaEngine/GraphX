"""Deterministic implementation handoff and live-progress checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .polaris_core import (
    RuleFailure,
    current_work_item_path,
    directory_sha256,
    file_sha256,
    full_commit,
    protocol_root,
    read_json,
    task_dir,
    validate_json_file,
    validate_schema,
)
from .artifact_protocol import normalized_reference
from .task_layout import (
    implementation_relative_path,
    state_path,
    task_repo_relative_path,
    task_root_relative_path,
)


REQUIRED_PACKAGE_ROLES = {
    "project_rules",
    "work_item",
    "plan",
    "working_set",
}


def expected_attempt(
    root: Path, directory: Path, state: dict[str, Any]
) -> tuple[int, dict[str, str] | None, str]:
    revision = state["current_revision"]
    work_item = validate_json_file(
        current_work_item_path(directory, revision),
        root / "schemas" / "work-item.schema.json",
    )
    prior = state["artifacts"].get("prior_review")
    if prior is None:
        return 1, None, work_item["base_commit"]
    reference = normalized_reference(directory, prior)
    review = validate_json_file(
        directory / reference["path"], root / "schemas" / "review.schema.json"
    )
    return review["artifact_attempt"] + 1, reference, review["subject_base_commit"]


def _validate_package(repo: Path, package: list[dict[str, Any]]) -> None:
    roles = {entry["role"] for entry in package}
    missing = REQUIRED_PACKAGE_ROLES - roles
    if missing:
        raise RuleFailure(
            "Implementation handoff package lacks roles: " + ", ".join(sorted(missing))
        )
    core_roles = [entry["role"] for entry in package if entry["role"] != "working_set_reference"]
    if len(core_roles) != len(set(core_roles)):
        raise RuleFailure("Implementation handoff package contains duplicate core roles")
    paths = [entry["path"] for entry in package]
    if len(paths) != len(set(paths)):
        raise RuleFailure("Implementation handoff package contains duplicate paths")
    for entry in package:
        path = (repo / entry["path"]).resolve()
        try:
            path.relative_to(repo.resolve())
        except ValueError as exc:
            raise RuleFailure(
                f"Implementation handoff path escapes repository: {entry['path']}"
            ) from exc
        if entry["kind"] == "file" and path.is_file():
            actual_hash = file_sha256(path)
        elif entry["kind"] == "directory" and path.is_dir():
            actual_hash = directory_sha256(path)
        else:
            raise RuleFailure(f"Implementation handoff package kind changed: {entry['path']}")
        if actual_hash != entry["sha256"]:
            raise RuleFailure(
                f"Implementation handoff package entry changed: {entry['path']}"
            )


def validate_handoff_value(
    repo: Path,
    root: Path,
    directory: Path,
    state: dict[str, Any],
    handoff: dict[str, Any],
    verify_package: bool = True,
) -> None:
    revision = state["current_revision"]
    attempt, previous_review, base_commit = expected_attempt(root, directory, state)
    if (
        handoff["task_id"] != state["task_id"]
        or handoff["work_item_revision"] != revision
        or handoff["artifact_attempt"] != attempt
        or handoff["rigor"] != state["rigor"]
    ):
        raise RuleFailure("Implementation handoff targets the wrong task, revision, or attempt")
    if handoff["preferred_isolation"] != "fresh_session":
        raise RuleFailure("Implementation handoff must prefer a fresh session")
    if handoff["subject_base_commit"] != full_commit(repo, base_commit):
        raise RuleFailure("Implementation handoff has the wrong subject base commit")
    if handoff["previous_review"] != previous_review:
        raise RuleFailure("Implementation handoff does not bind the current prior Review")
    expected_output = implementation_relative_path(revision, attempt).as_posix()
    if handoff["output_path"] != expected_output:
        raise RuleFailure("Implementation handoff has a non-deterministic output path")
    expected_progress = task_repo_relative_path(
        state["task_id"], "progress"
    ).as_posix()
    if handoff["progress_json_path"] != expected_progress:
        raise RuleFailure("Implementation handoff has the wrong progress JSON path")
    roles = {entry["role"] for entry in handoff["package"]}
    missing = REQUIRED_PACKAGE_ROLES - roles
    if missing:
        raise RuleFailure(
            "Implementation handoff package lacks roles: " + ", ".join(sorted(missing))
        )
    if verify_package:
        _validate_package(repo, handoff["package"])

    package = {entry["role"]: entry for entry in handoff["package"]}
    work_item_path = current_work_item_path(directory, revision)
    expected_paths = {
        "project_rules": repo / "AGENTS.md",
        "work_item": work_item_path,
        "plan": directory / normalized_reference(directory, state["artifacts"]["plan"])["path"],
        "working_set": directory
        / normalized_reference(directory, state["artifacts"]["working_set"])["path"],
    }
    if previous_review is not None:
        expected_paths["previous_review"] = directory / previous_review["path"]
    elif "previous_review" in package:
        raise RuleFailure("Initial Implementation handoff must not include a previous Review")
    for role, path in expected_paths.items():
        entry = package.get(role)
        if entry is None:
            raise RuleFailure(f"Implementation handoff package lacks role: {role}")
        expected_path = path.resolve().relative_to(repo.resolve()).as_posix()
        if entry["path"] != expected_path or (
            verify_package and entry["sha256"] != file_sha256(path)
        ):
            raise RuleFailure(f"Implementation handoff package has the wrong {role}")


def validate_handoff(
    repo: Path,
    root: Path,
    directory: Path,
    state: dict[str, Any],
    verify_package: bool = False,
) -> tuple[dict[str, Any], dict[str, str]]:
    reference = normalized_reference(
        directory, state["artifacts"].get("implementation_handoff")
    )
    handoff = validate_json_file(
        directory / reference["path"],
        root / "schemas" / "implementation-handoff.schema.json",
    )
    validate_handoff_value(repo, root, directory, state, handoff, verify_package)
    return handoff, reference


def validate_progress_value(
    repo: Path,
    root: Path,
    task_id: str,
    state: dict[str, Any],
    handoff: dict[str, Any],
    reference: dict[str, str],
    progress: dict[str, Any],
) -> None:
    errors = validate_schema(
        progress, read_json(root / "schemas" / "implementation-progress.schema.json")
    )
    if errors:
        raise RuleFailure("Live progress failed schema validation:\n- " + "\n- ".join(errors))
    if (
        progress["task_id"] != task_id
        or progress["work_item_revision"] != state["current_revision"]
        or progress["artifact_attempt"] != handoff["artifact_attempt"]
        or progress["handoff_path"]
        != (task_root_relative_path(task_id) / reference["path"]).as_posix()
        or progress["handoff_sha256"] != reference["sha256"]
    ):
        raise RuleFailure("Live progress targets the wrong Implementation handoff")
    expected_title = (
        f"Polaris Implement · {task_id} · r{state['current_revision']:03d} · "
        f"attempt {handoff['artifact_attempt']}"
    )
    if progress["implementation_task"] != expected_title:
        raise RuleFailure("Live progress has the wrong deterministic task title")
    if progress["phase"] != "QUEUED" and progress["implementer_session_id"] == "Pending":
        raise RuleFailure("active progress requires a real Implementer session ID")
    steps = progress["implementation_steps"]
    expected_ids = [f"STEP-{index:03d}" for index in range(1, len(steps) + 1)]
    if [step["id"] for step in steps] != expected_ids:
        raise RuleFailure("Implementation step IDs must be unique and sequential")
    work_item = validate_json_file(
        current_work_item_path(task_dir(repo, task_id), state["current_revision"]),
        root / "schemas" / "work-item.schema.json",
    )
    acceptance_ids = {item["id"] for item in work_item["acceptance"]}
    terminal_prefix = True
    pending_seen = False
    active: list[dict[str, Any]] = []
    for step in steps:
        if not step["title"].strip():
            raise RuleFailure(f"{step['id']} requires a non-empty title")
        unknown = set(step["acceptance_ids"]) - acceptance_ids
        if unknown:
            raise RuleFailure(
                f"{step['id']} references unknown acceptance IDs: "
                + ", ".join(sorted(unknown))
            )
        terminal = step["status"] in {"COMPLETED", "SKIPPED"}
        if terminal and (not isinstance(step["result"], str) or not step["result"].strip()):
            raise RuleFailure(f"terminal {step['id']} requires a result")
        if not terminal and step["result"] is not None:
            raise RuleFailure(f"non-terminal {step['id']} cannot have a result")
        if step["status"] in {"IN_PROGRESS", "BLOCKED"}:
            if pending_seen:
                raise RuleFailure("Implementation steps cannot start after a pending step")
            active.append(step)
            terminal_prefix = False
        elif step["status"] == "PENDING":
            pending_seen = True
            terminal_prefix = False
        elif not terminal_prefix:
            raise RuleFailure("Implementation steps cannot skip or reorder earlier work")
    if len(active) > 1:
        raise RuleFailure("Only one Implementation step may be active")
    active_id = active[0]["id"] if active else None
    if progress["current_step_id"] != active_id:
        raise RuleFailure("current_step_id must identify the active Implementation step")
    if progress["phase"] == "QUEUED" and (steps or active_id is not None):
        raise RuleFailure("QUEUED progress cannot contain defined steps")
    if progress["phase"] == "QUEUED" and progress["implementer_session_id"] != "Pending":
        raise RuleFailure("QUEUED progress must remain unowned")
    if progress["phase"] != "QUEUED" and not steps:
        raise RuleFailure("active progress requires defined Implementation steps")
    if progress["phase"] == "BLOCKED":
        if not active or active[0]["status"] != "BLOCKED":
            raise RuleFailure("BLOCKED progress requires a blocked current step")
        if not progress["blocker"] or not progress["user_action"]:
            raise RuleFailure("BLOCKED progress requires blocker and user_action")
    elif progress["phase"] == "FAILED":
        if not progress["blocker"] or not progress["user_action"]:
            raise RuleFailure("FAILED progress requires blocker and user_action")
    elif progress["blocker"] is not None or progress["user_action"] is not None:
        raise RuleFailure("only BLOCKED or FAILED progress may retain a blocker")
    if progress["phase"] in {"CHECKPOINTING", "DOCUMENTING", "COMPLETED"}:
        if any(step["status"] not in {"COMPLETED", "SKIPPED"} for step in steps):
            raise RuleFailure(f"{progress['phase']} requires all steps to be terminal")
        if active_id is not None:
            raise RuleFailure(f"{progress['phase']} cannot retain a current step")


def step_results(progress: dict[str, Any]) -> list[dict[str, str]]:
    """Project terminal live steps into the immutable Implementation artifact."""
    return [
        {"id": step["id"], "status": step["status"], "result": step["result"]}
        for step in progress["implementation_steps"]
        if step["status"] in {"COMPLETED", "SKIPPED"}
    ]


def validate_progress(repo: Path, task_id: str) -> dict[str, Any]:
    root = protocol_root(repo)
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    if state["status"] not in {"IMPLEMENTING", "IMPLEMENTED"}:
        raise RuleFailure(
            "Live implementation progress is valid only while IMPLEMENTING or IMPLEMENTED"
        )
    handoff, reference = validate_handoff(repo, root, directory, state)
    path = repo / handoff["progress_json_path"]
    progress = validate_json_file(
        path, root / "schemas" / "implementation-progress.schema.json"
    )
    validate_progress_value(repo, root, task_id, state, handoff, reference, progress)
    return progress
