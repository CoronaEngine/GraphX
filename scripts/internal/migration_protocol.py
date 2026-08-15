"""Explicit, adjacent-version migration protocol for vendored Polaris projects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .polaris_core import (
    InputFailure,
    RuleFailure,
    acquire_migration_lock,
    append_jsonl,
    load_events_checked,
    read_json,
    rebuild_state_value,
    release_lock,
    task_dir,
    utc_now,
    validate_json_file,
    write_json_atomic,
)
from .recovery_protocol import refresh_project_index
from .task_layout import events_path, state_path


MIGRATIONS_ROOT = Path(".polaris/migrations")


def load_migration_protocol(protocol_root: Path) -> dict[str, Any]:
    protocol = validate_json_file(
        protocol_root / "workflow" / "migrations.json",
        protocol_root / "schemas" / "migration-protocol.schema.json",
    )
    identifiers = [step["migration_id"] for step in protocol["steps"]]
    if len(identifiers) != len(set(identifiers)):
        raise RuleFailure("migration protocol contains duplicate migration IDs")
    routes = [
        (step["from_polaris_version"], step["to_polaris_version"])
        for step in protocol["steps"]
    ]
    if len(routes) != len(set(routes)):
        raise RuleFailure("migration protocol contains duplicate version routes")
    for step in protocol["steps"]:
        if step["from_polaris_version"] == step["to_polaris_version"]:
            raise RuleFailure(f"migration route does not advance: {step['migration_id']}")
        if step["from_workflow_version"] != step["to_workflow_version"]:
            raise RuleFailure(
                "v1 migration protocol cannot change workflow versions: "
                f"{step['migration_id']}"
            )
    return protocol


def migration_record_path(repo: Path, migration_id: str) -> Path:
    return repo / MIGRATIONS_ROOT / f"MIG-{migration_id}.json"


def load_migration_records(repo: Path, protocol_root: Path) -> list[dict[str, Any]]:
    schema = protocol_root / "schemas" / "migration-record.schema.json"
    records = [
        validate_json_file(path, schema)
        for path in sorted((repo / MIGRATIONS_ROOT).glob("MIG-*.json"))
    ]
    identifiers = [record["migration_id"] for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise RuleFailure("project contains duplicate migration IDs")
    in_progress = [record for record in records if record["status"] == "IN_PROGRESS"]
    if len(in_progress) > 1:
        raise RuleFailure("project contains multiple in-progress migrations")
    for record in records:
        task_ids = [item["task_id"] for item in record["tasks"]]
        if len(task_ids) != len(set(task_ids)):
            raise RuleFailure(
                f"migration record contains duplicate tasks: {record['migration_id']}"
            )
        if any(
            item["migration_sequence"] != item["source_sequence"] + 1
            for item in record["tasks"]
        ):
            raise RuleFailure(
                f"migration record contains a non-adjacent task sequence: "
                f"{record['migration_id']}"
            )
        if record["status"] == "COMPLETED" and record["completed_at"] is None:
            raise RuleFailure(
                f"completed migration lacks completion time: {record['migration_id']}"
            )
        if record["status"] == "IN_PROGRESS" and record["completed_at"] is not None:
            raise RuleFailure(
                f"in-progress migration has completion time: {record['migration_id']}"
            )
    return records


def validate_completed_migrations(repo: Path, protocol_root: Path) -> None:
    protocol = load_migration_protocol(protocol_root)
    for record in load_migration_records(repo, protocol_root):
        _step_for_record(protocol, record)
        if record["status"] != "COMPLETED":
            raise RuleFailure(
                f"migration is incomplete; resume migrate_project.py: "
                f"{record['migration_id']}"
            )
        for item in record["tasks"]:
            directory = task_dir(repo, item["task_id"])
            events = load_events_checked(events_path(directory))
            sequence = item["migration_sequence"]
            if sequence >= len(events):
                raise RuleFailure(
                    f"migration event is missing for {item['task_id']}: "
                    f"{record['migration_id']}"
                )
            event = events[sequence]
            prior = events[sequence - 1]
            if (
                event.get("event") != "MIGRATE_POLARIS"
                or event.get("migration_id") != record["migration_id"]
                or event.get("polaris_version") != record["to_polaris_version"]
                or event.get("workflow_version") != record["to_workflow_version"]
                or event.get("from") != event.get("to")
                or prior.get("polaris_version")
                != record["from_polaris_version"]
                or prior.get("workflow_version")
                != record["from_workflow_version"]
            ):
                raise RuleFailure(
                    f"invalid migration event for {item['task_id']}: "
                    f"{record['migration_id']}"
                )


def _migration_event(
    state: dict[str, Any], step: dict[str, Any], timestamp: str
) -> dict[str, Any]:
    return {
        "sequence": state["sequence"] + 1,
        "timestamp": timestamp,
        "event": "MIGRATE_POLARIS",
        "gate": "explicit_protocol_migration",
        "from": state["status"],
        "to": state["status"],
        "task_id": state["task_id"],
        "polaris_version": step["to_polaris_version"],
        "workflow_version": step["to_workflow_version"],
        "current_revision": state["current_revision"],
        "rigor": state["rigor"],
        "blocked_from": state.get("blocked_from"),
        "blocker": state.get("blocker"),
        "artifacts": state["artifacts"],
        "subject": state.get("subject"),
        "migration_id": step["migration_id"],
    }


def _step_for_record(
    protocol: dict[str, Any], record: dict[str, Any]
) -> dict[str, Any]:
    step = next(
        (
            item
            for item in protocol["steps"]
            if item["migration_id"] == record["migration_id"]
        ),
        None,
    )
    if step is None:
        raise RuleFailure(
            f"in-progress migration is not supported by this version: "
            f"{record['migration_id']}"
        )
    for key in (
        "from_polaris_version",
        "to_polaris_version",
        "from_workflow_version",
        "to_workflow_version",
    ):
        if record[key] != step[key]:
            raise RuleFailure(
                f"migration record differs from protocol step: {record['migration_id']}"
            )
    return step


def _new_record(
    repo: Path,
    project: dict[str, Any],
    step: dict[str, Any],
    timestamp: str,
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for task_id in sorted(project["active_tasks"]):
        directory = task_dir(repo, task_id)
        state = read_json(state_path(directory))
        if rebuild_state_value(events_path(directory)) != state:
            raise RuleFailure(f"task state differs from events before migration: {task_id}")
        if state["polaris_version"] != step["from_polaris_version"]:
            raise RuleFailure(f"task has the wrong Polaris version: {task_id}")
        if state["workflow_version"] != step["from_workflow_version"]:
            raise RuleFailure(f"task has the wrong workflow version: {task_id}")
        tasks.append(
            {
                "task_id": task_id,
                "source_sequence": state["sequence"],
                "migration_sequence": state["sequence"] + 1,
            }
        )
    return {
        "record_version": 1,
        "migration_id": step["migration_id"],
        "from_polaris_version": step["from_polaris_version"],
        "to_polaris_version": step["to_polaris_version"],
        "from_workflow_version": step["from_workflow_version"],
        "to_workflow_version": step["to_workflow_version"],
        "status": "IN_PROGRESS",
        "started_at": timestamp,
        "completed_at": None,
        "tasks": tasks,
    }


def migrate_project(repo: Path, protocol_root: Path) -> dict[str, Any]:
    project_path = repo / ".polaris" / "project.json"
    project = validate_json_file(
        project_path, protocol_root / "schemas" / "project.schema.json"
    )
    workflow = validate_json_file(
        repo / ".polaris" / "workflow.json",
        protocol_root / "schemas" / "workflow.schema.json",
    )
    target_version = (protocol_root / "VERSION").read_text(encoding="utf-8").strip()
    protocol = load_migration_protocol(protocol_root)
    records = load_migration_records(repo, protocol_root)
    incomplete = next(
        (record for record in records if record["status"] == "IN_PROGRESS"), None
    )

    if incomplete is not None:
        step = _step_for_record(protocol, incomplete)
        record = incomplete
        if project["polaris_version"] not in {
            step["from_polaris_version"],
            step["to_polaris_version"],
        }:
            raise RuleFailure("project version is outside the in-progress migration")
        if project["workflow_version"] != step["from_workflow_version"]:
            raise RuleFailure("project workflow version changed during migration")
        if workflow["workflow_version"] != step["from_workflow_version"]:
            raise RuleFailure("frozen workflow changed during migration")
    elif project["polaris_version"] == target_version:
        return {
            "message": f"project already uses Polaris {target_version}",
            "from": target_version,
            "to": target_version,
            "migrated_tasks": 0,
        }
    else:
        step = next(
            (
                item
                for item in protocol["steps"]
                if item["from_polaris_version"] == project["polaris_version"]
                and item["to_polaris_version"] == target_version
            ),
            None,
        )
        if step is None:
            raise RuleFailure(
                f"no explicit adjacent migration from {project['polaris_version']} "
                f"to {target_version}"
            )
        if project["workflow_version"] != step["from_workflow_version"]:
            raise RuleFailure("project workflow version does not match migration source")
        if workflow["workflow_version"] != step["from_workflow_version"]:
            raise RuleFailure("frozen workflow does not match migration source")
        if any(
            record["migration_id"] == step["migration_id"] for record in records
        ):
            raise RuleFailure(
                f"completed migration cannot be replayed: {step['migration_id']}"
            )
        record = _new_record(repo, project, step, utc_now())

    if target_version != step["to_polaris_version"]:
        raise RuleFailure("migration target does not match vendored Polaris version")
    if set(project["active_tasks"]) != {
        item["task_id"] for item in record["tasks"]
    }:
        raise RuleFailure("project task list changed during migration")

    locks: list[tuple[Path, int]] = []
    try:
        for item in record["tasks"]:
            lock_path = task_dir(repo, item["task_id"]) / ".transition.lock"
            locks.append(
                (
                    lock_path,
                    acquire_migration_lock(
                        lock_path, record["migration_id"], item["task_id"]
                    ),
                )
            )
        record_path = migration_record_path(repo, record["migration_id"])
        if incomplete is None:
            write_json_atomic(record_path, record)

        for item in record["tasks"]:
            directory = task_dir(repo, item["task_id"])
            ledger_path = events_path(directory)
            events = load_events_checked(ledger_path)
            sequence = item["migration_sequence"]
            if len(events) == sequence:
                state = rebuild_state_value(ledger_path)
                if (
                    state["sequence"] != item["source_sequence"]
                    or state["polaris_version"] != step["from_polaris_version"]
                    or state["workflow_version"] != step["from_workflow_version"]
                ):
                    raise RuleFailure(
                        f"task changed after migration preflight: {item['task_id']}"
                    )
                append_jsonl(
                    ledger_path,
                    _migration_event(state, step, record["started_at"]),
                )
                events = load_events_checked(ledger_path)
            if len(events) != sequence + 1:
                raise RuleFailure(
                    f"task advanced during migration: {item['task_id']}"
                )
            event = events[sequence]
            if (
                event.get("event") != "MIGRATE_POLARIS"
                or event.get("migration_id") != record["migration_id"]
                or event.get("polaris_version") != step["to_polaris_version"]
            ):
                raise RuleFailure(
                    f"task has an unexpected migration event: {item['task_id']}"
                )
            write_json_atomic(state_path(directory), rebuild_state_value(ledger_path))

        project["polaris_version"] = step["to_polaris_version"]
        project["workflow_version"] = step["to_workflow_version"]
        write_json_atomic(project_path, project)
        refresh_project_index(repo)
        record["status"] = "COMPLETED"
        record["completed_at"] = utc_now()
        write_json_atomic(record_path, record)
    finally:
        for lock_path, descriptor in reversed(locks):
            release_lock(lock_path, descriptor)

    return {
        "message": f"migrated project with {record['migration_id']}",
        "from": record["from_polaris_version"],
        "to": record["to_polaris_version"],
        "migrated_tasks": len(record["tasks"]),
        "record": str(record_path),
    }
