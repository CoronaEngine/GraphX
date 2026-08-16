"""Read-only, aggregate diagnostics for an initialized Polaris repository."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .install_manifest import validate_install_manifest
from .code_intelligence_protocol import validate_static_configuration
from .migration_protocol import validate_completed_migrations
from .polaris_core import (
    InputFailure,
    RuleFailure,
    protocol_root,
    read_json,
    require_protocol_compatible,
    validate_json_file,
)
from .recovery_protocol import project_index_value
from .task_layout import ARCHIVED_RUNTIME_IGNORE_PATTERN, RUNTIME_IGNORE_PATTERN
from .task_location_protocol import validate_task_locations


DOCTOR_VERSION = 1
MINIMUM_PYTHON = (3, 10)
DoctorOutcome = tuple[str, str, list[str]]


def _git(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
    except OSError as exc:
        raise InputFailure(f"cannot execute Git: {exc}") from exc
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise InputFailure(message or f"Git exited with {completed.returncode}")
    return completed.stdout.strip()


def _outcome(status: str, message: str, *evidence: str) -> DoctorOutcome:
    return status, message, list(evidence)


def _check_value(
    check_id: str,
    label: str,
    status: str,
    message: str,
    evidence: list[str],
    actions: list[str],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": status,
        "message": message,
        "evidence": evidence,
        "actions": actions,
    }


def _run_check(
    check_id: str,
    label: str,
    action: Callable[[], DoctorOutcome],
    failure_action: str,
) -> dict[str, Any]:
    try:
        status, message, evidence = action()
        actions = [failure_action] if status == "WARN" else []
        return _check_value(check_id, label, status, message, evidence, actions)
    except (InputFailure, RuleFailure, OSError, subprocess.SubprocessError) as exc:
        return _check_value(
            check_id,
            label,
            "FAIL",
            "diagnostic rule failed",
            [str(exc)],
            [failure_action],
        )


def _dependency_warning(
    check_id: str, label: str, dependency: str
) -> dict[str, Any]:
    return _check_value(
        check_id,
        label,
        "WARN",
        f"check was not run because {dependency} did not pass",
        [f"dependency={dependency}"],
        [f"Resolve {dependency} first, then rerun doctor_project.py."],
    )


def _runtime_check() -> DoctorOutcome:
    current = sys.version_info[:3]
    if current < MINIMUM_PYTHON:
        raise RuleFailure(
            f"Python {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer is required"
        )
    git_version = _git(Path.cwd(), "--version")
    return _outcome(
        "PASS",
        "required local executables are available",
        f"python={current[0]}.{current[1]}.{current[2]}",
        git_version,
    )


def _repository_check(repo: Path) -> DoctorOutcome:
    if repo.is_symlink() or not repo.is_dir():
        raise RuleFailure(f"repository root is not a regular directory: {repo}")
    git_root = Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()
    if git_root != repo.resolve():
        raise RuleFailure(f"--repo must identify the Git repository root: {git_root}")
    return _outcome("PASS", "Git repository root is usable", str(repo))


def _protocol_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    root = protocol_root(repo)
    version_path = root / "VERSION"
    if root.is_symlink() or not root.is_dir() or not version_path.is_file():
        raise RuleFailure(f"Polaris protocol root is incomplete: {root}")
    version = version_path.read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise RuleFailure(f"Polaris VERSION is invalid: {version!r}")
    mode = "vendored" if root == repo / "tools" / "polaris" else "source"
    context.update({"root": root, "version": version, "mode": mode})
    status = "PASS" if mode == "vendored" else "WARN"
    message = (
        "repository uses its vendored Polaris protocol"
        if mode == "vendored"
        else "repository is using the source checkout protocol, not a vendored install"
    )
    return _outcome(status, message, f"mode={mode}", f"version={version}")


def _authority_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    root = context["root"]
    project = validate_json_file(
        repo / ".polaris" / "project.json", root / "schemas" / "project.schema.json"
    )
    workflow = validate_json_file(
        repo / ".polaris" / "workflow.json",
        root / "schemas" / "workflow.schema.json",
    )
    context.update({"project": project, "workflow": workflow})
    compatible = require_protocol_compatible(repo)
    return _outcome(
        "PASS",
        "project Authority versions are compatible",
        f"project={project['project_id']}",
        f"polaris_version={compatible['polaris_version']}",
        f"workflow_version={compatible['workflow_version']}",
    )


def _install_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    if context["mode"] != "vendored":
        return _outcome(
            "WARN",
            "install manifest check is unavailable without a vendored protocol",
            "expected=tools/polaris/install-manifest.json",
        )
    manifest = validate_install_manifest(repo, context["root"])
    return _outcome(
        "PASS",
        "vendored install manifest is intact",
        f"managed_files={len(manifest['managed_files'])}",
        f"preserved_files={len(manifest['preserved_files'])}",
    )


def _migration_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    validate_completed_migrations(repo, context["root"])
    migrations_root = repo / ".polaris" / "migrations"
    count = len(list(migrations_root.glob("MIG-*.json")))
    return _outcome(
        "PASS", "migration records are complete and consistent", f"records={count}"
    )


def _code_intelligence_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    result = validate_static_configuration(repo, context["root"])
    return _outcome(
        "PASS",
        "optional Code Intelligence configuration is valid",
        f"mode={result['mode']}",
        f"configured={str(result['configured']).lower()}",
        "providers=" + ",".join(result["providers"]),
        "runtime MCP availability is checked by the Code Intelligence Skill",
    )


def _location_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    project = context["project"]
    locations = validate_task_locations(repo, project["active_tasks"])
    context["locations"] = locations
    return _outcome(
        "PASS",
        "task location registry matches the project",
        f"registered_tasks={len(locations)}",
    )


def _index_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    root = context["root"]
    actual = validate_json_file(
        repo / ".polaris" / "project-index.json",
        root / "schemas" / "project-index.schema.json",
    )
    expected = project_index_value(repo)
    if actual != expected:
        raise RuleFailure("project recovery index is stale")
    return _outcome(
        "PASS",
        "project recovery index matches current task state",
        f"tasks={len(actual['tasks'])}",
    )


def _gitignore_check(repo: Path) -> DoctorOutcome:
    path = repo / ".gitignore"
    if not path.is_file():
        raise RuleFailure(".gitignore is missing")
    rules = {line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines()}
    required = {RUNTIME_IGNORE_PATTERN, ARCHIVED_RUNTIME_IGNORE_PATTERN}
    missing = sorted(required - rules)
    if missing:
        raise RuleFailure(f"runtime ignore rules are missing: {missing}")
    return _outcome("PASS", "task runtime directories are ignored", *sorted(required))


def _residue_check(repo: Path, context: dict[str, Any]) -> DoctorOutcome:
    transaction_prefix = f".{repo.name}-polaris-vendor-transaction-"
    transactions = sorted(
        path
        for path in repo.parent.iterdir()
        if path.name.startswith(transaction_prefix)
    )
    locks: list[Path] = []
    for directory in context.get("locations", {}).values():
        lock_path = directory / ".transition.lock"
        if lock_path.exists():
            locks.append(lock_path)
    evidence = [f"vendor_transaction={path}" for path in transactions]
    evidence.extend(f"task_lock={path}" for path in sorted(locks))
    if evidence:
        return _outcome(
            "WARN",
            "operation residue requires owner-aware review",
            *evidence,
        )
    return _outcome("PASS", "no vendor transaction or task lock residue was found")


def _task_check(repo: Path, task_id: str) -> DoctorOutcome:
    from validate_task import validate as validate_task

    validate_task(repo, task_id)
    return _outcome(
        "PASS",
        f"{task_id} Authority and artifacts are valid",
        f"task_id={task_id}",
    )


def _project_validation_check(repo: Path) -> DoctorOutcome:
    from validate_project import validate as validate_project

    validate_project(repo)
    return _outcome("PASS", "full project validation passed")


def diagnose_project(repo: Path) -> dict[str, Any]:
    """Run every safe diagnostic and never mutate repository authority state."""
    repo = repo.resolve()
    context: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []

    checks.append(
        _run_check(
            "runtime",
            "Runtime prerequisites",
            _runtime_check,
            "Install Python 3.10 or newer and Git, then rerun the Doctor.",
        )
    )
    checks.append(
        _run_check(
            "repository",
            "Repository root",
            lambda: _repository_check(repo),
            "Run the Doctor with --repo set to a regular Git repository root.",
        )
    )
    checks.append(
        _run_check(
            "protocol",
            "Polaris protocol",
            lambda: _protocol_check(repo, context),
            "Vendor a complete Polaris protocol into the repository.",
        )
    )

    if "root" not in context:
        for check_id, label in (
            ("authority", "Project Authority"),
            ("install_manifest", "Vendored install"),
            ("migrations", "Migration records"),
            ("code_intelligence", "Code Intelligence"),
            ("task_locations", "Task locations"),
            ("project_index", "Project recovery index"),
            ("project_validation", "Integrated project validation"),
        ):
            checks.append(_dependency_warning(check_id, label, "protocol"))
    else:
        checks.append(
            _run_check(
                "authority",
                "Project Authority",
                lambda: _authority_check(repo, context),
                "Inspect project/workflow versions and run the explicit migration if required.",
            )
        )
        checks.append(
            _run_check(
                "install_manifest",
                "Vendored install",
                lambda: _install_check(repo, context),
                "Review managed-file changes and rerun vendor_project.py with the intended upgrade options.",
            )
        )
        checks.append(
            _run_check(
                "migrations",
                "Migration records",
                lambda: _migration_check(repo, context),
                "Resume the matching migrate_project.py operation; do not edit migration events manually.",
            )
        )
        checks.append(
            _run_check(
                "code_intelligence",
                "Code Intelligence",
                lambda: _code_intelligence_check(repo, context),
                "Correct or remove .polaris/code-intelligence.json; provider installation is optional.",
            )
        )
        if "project" in context:
            checks.append(
                _run_check(
                    "task_locations",
                    "Task locations",
                    lambda: _location_check(repo, context),
                    "Restore the registered task root or correct task-locations.json after confirming the physical move.",
                )
            )
            checks.append(
                _run_check(
                    "project_index",
                    "Project recovery index",
                    lambda: _index_check(repo, context),
                    "Run refresh_project_index.py after resolving task Authority errors.",
                )
            )
            for task_id in sorted(context["project"]["active_tasks"]):
                checks.append(
                    _run_check(
                        f"task:{task_id}",
                        f"Task {task_id}",
                        lambda task_id=task_id: _task_check(repo, task_id),
                        "Use validate_task.py evidence and the authorized recovery or transition script; do not edit state.json directly.",
                    )
                )
            checks.append(
                _run_check(
                    "project_validation",
                    "Integrated project validation",
                    lambda: _project_validation_check(repo),
                    "Resolve the preceding failed checks, then rerun validate_project.py.",
                )
            )
        else:
            for check_id, label in (
                ("task_locations", "Task locations"),
                ("project_index", "Project recovery index"),
                ("project_validation", "Integrated project validation"),
            ):
                checks.append(_dependency_warning(check_id, label, "authority"))

    checks.append(
        _run_check(
            "runtime_ignore",
            "Runtime ignore rules",
            lambda: _gitignore_check(repo),
            "Add the exact active and archived task runtime rules to .gitignore.",
        )
    )
    checks.append(
        _run_check(
            "operation_residue",
            "Operation residue",
            lambda: _residue_check(repo, context),
            "Resume the owning operation and do not delete locks or transaction directories blindly.",
        )
    )

    passed = sum(item["status"] == "PASS" for item in checks)
    warnings = sum(item["status"] == "WARN" for item in checks)
    failed = sum(item["status"] == "FAIL" for item in checks)
    status = "FAIL" if failed else "WARN" if warnings else "PASS"
    message = (
        f"Doctor completed {len(checks)} checks: "
        f"{passed} passed, {warnings} warnings, {failed} failed"
    )
    return {
        "doctor_version": DOCTOR_VERSION,
        "status": status,
        "message": message,
        "repository": str(repo),
        "mode": context.get("mode", "unknown"),
        "summary": {
            "total": len(checks),
            "passed": passed,
            "warnings": warnings,
            "failed": failed,
        },
        "checks": checks,
    }
