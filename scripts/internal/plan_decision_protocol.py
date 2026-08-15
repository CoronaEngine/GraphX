"""Validation for Human-owned decisions made while preparing a Plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifact_protocol import normalized_reference
from .path_security import confined_target
from .polaris_core import RuleFailure, file_sha256, validate_json_file


def empty_plan_decisions(task_id: str, revision: int, plan_path: Path) -> dict[str, Any]:
    """Build a register that explicitly states that the Plan needs no Human choice."""
    return {
        "register_version": 1,
        "task_id": task_id,
        "work_item_revision": revision,
        "plan": {
            "path": plan_path.name,
            "sha256": file_sha256(plan_path),
        },
        "decisions": [],
    }


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _decision_file(repo: Path, raw_path: str) -> Path:
    expected_root = repo / ".polaris" / "decisions"
    path = confined_target(repo, repo / Path(raw_path), "Plan decision authority")
    if path.parent != expected_root.absolute():
        raise RuleFailure("Plan decision authority must be a direct CD file")
    if not path.is_file():
        raise RuleFailure(f"Plan decision authority does not exist: {path}")
    return path


def validate_plan_decisions(
    repo: Path,
    root: Path,
    directory: Path,
    state: dict[str, Any],
    require_resolved: bool,
) -> dict[str, Any]:
    """Validate identity, Plan binding, choices, and immutable decision authority."""
    plan_reference = normalized_reference(directory, state["artifacts"].get("plan"))
    register_reference = normalized_reference(
        directory, state["artifacts"].get("plan_decisions")
    )
    plan_path = directory / plan_reference["path"]
    register_path = directory / register_reference["path"]
    register = validate_json_file(
        register_path, root / "schemas" / "plan-decisions.schema.json"
    )
    if (
        register["task_id"] != state["task_id"]
        or register["work_item_revision"] != state["current_revision"]
    ):
        raise RuleFailure("Plan decision register targets the wrong task revision")
    if register["plan"] != plan_reference:
        raise RuleFailure("Plan decision register does not bind the registered Plan")
    if file_sha256(plan_path) != register["plan"]["sha256"]:
        raise RuleFailure("Plan changed after its decision register was prepared")

    decision_ids: set[str] = set()
    for decision in register["decisions"]:
        decision_id = decision["decision_id"]
        if decision_id in decision_ids:
            raise RuleFailure(f"duplicate Plan decision ID: {decision_id}")
        decision_ids.add(decision_id)
        if not _nonblank(decision["question"]):
            raise RuleFailure(f"{decision_id} requires a non-empty question")
        options = decision["options"]
        if len(options) > 3:
            raise RuleFailure(f"{decision_id} may offer at most three options")
        option_ids = [option["option_id"] for option in options]
        if len(option_ids) != len(set(option_ids)):
            raise RuleFailure(f"{decision_id} contains duplicate option IDs")
        for option in options:
            if not _nonblank(option["label"]) or not _nonblank(option["consequence"]):
                raise RuleFailure(f"{decision_id} options require labels and consequences")
        recommended = decision["recommended_option_id"]
        if recommended != option_ids[0]:
            raise RuleFailure(f"{decision_id} must list its recommended option first")
        if not options[0]["label"].endswith("(Recommended)"):
            raise RuleFailure(
                f"{decision_id} recommended option label must end with (Recommended)"
            )

        resolution = decision["resolution"]
        if decision["status"] == "PENDING":
            if resolution is not None:
                raise RuleFailure(f"pending {decision_id} cannot have a resolution")
            if require_resolved:
                raise RuleFailure(f"Plan requires Human decision: {decision_id}")
            continue
        if resolution is None:
            raise RuleFailure(f"resolved {decision_id} requires a resolution")
        selected = resolution["selected_option_id"]
        if selected not in option_ids:
            raise RuleFailure(f"{decision_id} selected an unknown option")
        decision_path = _decision_file(repo, resolution["decision_path"])
        if file_sha256(decision_path) != resolution["decision_sha256"]:
            raise RuleFailure(f"Plan decision authority changed: {decision_id}")
        authority = validate_json_file(
            decision_path, root / "schemas" / "decision.schema.json"
        )
        if (
            authority["decision_id"] != decision_path.stem
            or authority.get("task_id") != state["task_id"]
            or authority.get("plan_decision_id") != decision_id
            or authority["approval_gate"] != "plan_decision"
            or authority["work_item_revision"] != state["current_revision"]
            or authority["plan_hash"] != plan_reference["sha256"]
            or authority["subject_diff_hash"] is not None
            or authority["decision"] != selected
        ):
            raise RuleFailure(f"Plan decision authority does not match {decision_id}")
        if not _nonblank(authority["approved_by"]) or not _nonblank(
            authority["approved_at"]
        ):
            raise RuleFailure(f"Plan decision authority is incomplete: {decision_id}")
    return register
