"""Provider-neutral, best-effort Code Intelligence configuration and evidence."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Iterable

from .path_security import confined_target, require_regular_file, require_regular_tree
from .polaris_core import (
    InputFailure,
    RuleFailure,
    file_sha256,
    full_commit,
    git,
    protocol_root,
    read_json,
    subject_diff_hash,
    task_dir,
    validate_json_file,
    validate_schema,
    write_json_atomic,
)
from .task_location_protocol import resolve_repo_reference
from .task_layout import code_intelligence_record_path, state_path


CONFIG_PATH = Path(".polaris/code-intelligence.json")
OPERATIONS = {
    "symbol_search",
    "context",
    "dependencies",
    "call_graph",
    "impact",
    "review_context",
    "refresh_files",
    "refresh_workspace",
}
STAGE_NAMES = {
    "PLANNING": "planning",
    "IMPLEMENTATION": "implementation-{attempt:03d}",
    "DOCUMENTATION_SYNC": "documentation-sync-{attempt:03d}",
    "REVIEW": "review-{attempt:03d}-slot-{reviewer_slot}",
}


def _validate_pattern(value: str) -> None:
    if "\\" in value:
        raise RuleFailure(f"Code Intelligence pattern must use POSIX separators: {value}")
    path = Path(value)
    if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise RuleFailure(f"unsafe Code Intelligence pattern: {value}")


def load_config(repo: Path, root: Path | None = None) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    config_path = repo / CONFIG_PATH
    if config_path.exists():
        require_regular_file(config_path, "Code Intelligence project configuration")
        value = validate_json_file(
            config_path, root / "schemas" / "code-intelligence-config.schema.json"
        )
    else:
        value = validate_json_file(
            root / "templates" / "code-intelligence.json",
            root / "schemas" / "code-intelligence-config.schema.json",
        )
    for pattern in (*value["include"], *value["exclude"]):
        _validate_pattern(pattern)
    return value


def load_providers(root: Path) -> dict[str, dict[str, Any]]:
    providers_root = root / "providers" / "code-intelligence"
    require_regular_tree(providers_root, "Code Intelligence provider descriptors")
    schema = root / "schemas" / "code-intelligence-provider.schema.json"
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(providers_root.glob("*.json")):
        require_regular_file(path, "Code Intelligence provider descriptor")
        value = validate_json_file(path, schema)
        provider_id = value["provider_id"]
        if path.stem != provider_id:
            raise RuleFailure(
                f"Code Intelligence provider filename does not match ID: {path}"
            )
        if provider_id in result:
            raise RuleFailure(f"duplicate Code Intelligence provider: {provider_id}")
        if not value["operations"]:
            raise RuleFailure(f"Code Intelligence provider has no operations: {provider_id}")
        if set(value["operations"]) - OPERATIONS:
            raise RuleFailure(f"Code Intelligence provider has unknown operations: {provider_id}")
        result[provider_id] = value
    if not result:
        raise RuleFailure("no Code Intelligence provider descriptors found")
    return result


def select_provider(
    repo: Path, available_tools: Iterable[str], root: Path | None = None
) -> dict[str, Any] | None:
    root = protocol_root(repo) if root is None else root
    config = load_config(repo, root)
    if config["mode"] == "disabled":
        return None
    providers = load_providers(root)
    configured_priority = config["provider_priority"]
    priority = configured_priority + [
        provider_id
        for provider_id in sorted(providers)
        if provider_id not in configured_priority
    ]
    available = set(available_tools)
    for provider_id in priority:
        descriptor = providers.get(provider_id)
        if descriptor is None:
            raise RuleFailure(f"unknown configured Code Intelligence provider: {provider_id}")
        operations = {
            operation: tool
            for operation, tool in descriptor["operations"].items()
            if tool in available
        }
        if operations:
            return {
                "provider_id": provider_id,
                "provider_version": descriptor["provider_version"],
                "transport": descriptor["transport"],
                "operations": operations,
            }
    return None


def validate_static_configuration(repo: Path, root: Path | None = None) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    config = load_config(repo, root)
    providers = load_providers(root)
    unknown = set(config["provider_priority"]) - set(providers)
    if unknown:
        raise RuleFailure(
            "Code Intelligence configuration references unknown providers: "
            + ", ".join(sorted(unknown))
        )
    return {
        "mode": config["mode"],
        "configured": (repo / CONFIG_PATH).is_file(),
        "providers": sorted(providers),
    }


def _matches_scope(path: str, config: dict[str, Any]) -> bool:
    included = not config["include"] or any(
        fnmatch.fnmatchcase(path, pattern) for pattern in config["include"]
    )
    excluded = any(fnmatch.fnmatchcase(path, pattern) for pattern in config["exclude"])
    return included and not excluded


def _eligible(path: str, extensions: set[str], config: dict[str, Any]) -> bool:
    return Path(path).suffix.lower() in extensions and _matches_scope(path, config)


def plan_refresh(
    repo: Path,
    base_commit: str,
    head_commit: str,
    provider_id: str,
    root: Path | None = None,
) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    config = load_config(repo, root)
    providers = load_providers(root)
    if provider_id not in providers:
        raise RuleFailure(f"unknown Code Intelligence provider: {provider_id}")
    base = full_commit(repo, base_commit)
    head = full_commit(repo, head_commit)
    extensions = {item.lower() for item in providers[provider_id]["file_extensions"]}
    changes: list[dict[str, Any]] = []
    requires_workspace = False
    output = git(repo, "diff", "--name-status", "--find-renames", base, head)
    for line in output.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        status = parts[0]
        if status.startswith("R") and len(parts) == 3:
            old_path, new_path = parts[1], parts[2]
            if not (_eligible(old_path, extensions, config) or _eligible(new_path, extensions, config)):
                continue
            resolve_repo_reference(repo, old_path)
            new_target = resolve_repo_reference(repo, new_path)
            changes.append(
                {
                    "path": new_path,
                    "change": "RENAMED",
                    "sha256": file_sha256(new_target) if new_target.is_file() else None,
                }
            )
            requires_workspace = True
            continue
        if len(parts) != 2:
            continue
        raw_path = parts[1]
        if not _eligible(raw_path, extensions, config):
            continue
        target = resolve_repo_reference(repo, raw_path)
        if status.startswith("D"):
            change = "DELETED"
            digest = None
            requires_workspace = True
        elif status.startswith("A"):
            change = "ADDED"
            digest = file_sha256(target) if target.is_file() else None
        else:
            change = "MODIFIED"
            digest = file_sha256(target) if target.is_file() else None
        changes.append({"path": raw_path, "change": change, "sha256": digest})
    operation = "refresh_workspace" if requires_workspace else "refresh_files"
    return {
        "operation": operation,
        "paths": changes,
        "status": "SKIPPED" if not changes else "PENDING",
        "base_commit": base,
        "head_commit": head,
        "diff_hash": subject_diff_hash(repo, base, head),
    }


def _record_name(value: dict[str, Any]) -> str:
    stage = value["stage"]
    attempt = value["artifact_attempt"]
    reviewer_slot = value["reviewer_slot"]
    if stage == "PLANNING":
        if attempt is not None or reviewer_slot is not None:
            raise RuleFailure("Planning Code Intelligence record cannot have attempt or slot")
    elif stage == "REVIEW":
        if attempt is None or reviewer_slot not in {1, 2}:
            raise RuleFailure("Review Code Intelligence record requires attempt and slot")
    elif attempt is None or reviewer_slot is not None:
        raise RuleFailure(f"{stage} Code Intelligence record requires only an attempt")
    return STAGE_NAMES[stage].format(
        attempt=attempt or 1, reviewer_slot=reviewer_slot or 1
    )


def validate_record_value(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    schema = read_json(root / "schemas" / "code-intelligence-record.schema.json")
    errors = validate_schema(value, schema)
    if errors:
        raise RuleFailure(
            "Code Intelligence record failed schema validation:\n- "
            + "\n- ".join(errors)
        )
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    if value["task_id"] != task_id or value["work_item_revision"] != state["current_revision"]:
        raise RuleFailure("Code Intelligence record targets the wrong task revision")
    _record_name(value)
    target = value["target"]
    base = full_commit(repo, target["base_commit"])
    if target["head_commit"] is None:
        if target["diff_hash"] is not None:
            raise RuleFailure("base-only Code Intelligence target cannot have a diff hash")
    else:
        head = full_commit(repo, target["head_commit"])
        if target["diff_hash"] != subject_diff_hash(repo, base, head):
            raise RuleFailure("Code Intelligence target diff hash is stale")
    if value["status"] in {"USED", "FAILED"} and value["provider"] is None:
        raise RuleFailure("used or failed Code Intelligence record requires a provider")
    provider = value["provider"]
    if provider is not None:
        descriptors = load_providers(root)
        descriptor = descriptors.get(provider["id"])
        if (
            descriptor is None
            or provider["descriptor_version"] != descriptor["provider_version"]
            or provider["transport"] != descriptor["transport"]
            or not set(provider["available_operations"]).issubset(
                descriptor["operations"]
            )
        ):
            raise RuleFailure("Code Intelligence record names an invalid provider capability set")
    query_ids = [item["id"] for item in value["queries"]]
    expected_ids = [f"CIQ-{index:03d}" for index in range(1, len(query_ids) + 1)]
    if query_ids != expected_ids:
        raise RuleFailure("Code Intelligence query IDs must be sequential")
    for query in value["queries"]:
        if (
            provider is not None
            and query["status"] != "UNAVAILABLE"
            and query["operation"] not in provider["available_operations"]
        ):
            raise RuleFailure(f"query used an unavailable provider operation: {query['id']}")
        if query["status"] == "SUCCESS" and query["response_sha256"] is None:
            raise RuleFailure(f"successful query lacks response hash: {query['id']}")
        if query["status"] == "FAILED" and not query["error"]:
            raise RuleFailure(f"failed query lacks error: {query['id']}")
        for symbol in query["symbols"]:
            path = resolve_repo_reference(repo, symbol["path"])
            if not path.is_file():
                raise RuleFailure(f"Code Intelligence symbol path is not a file: {symbol['path']}")
    refresh = value["refresh"]
    if refresh is not None:
        if value["stage"] not in {"IMPLEMENTATION", "DOCUMENTATION_SYNC"}:
            raise RuleFailure("only Implementation or Documentation Sync may refresh an index")
        if (
            provider is not None
            and refresh["status"] not in {"UNAVAILABLE", "SKIPPED"}
            and refresh["operation"] not in provider["available_operations"]
        ):
            raise RuleFailure("refresh used an unavailable provider operation")
        changes = {item["change"] for item in refresh["paths"]}
        if changes & {"DELETED", "RENAMED"} and refresh["operation"] != "refresh_workspace":
            raise RuleFailure("deleted or renamed code requires workspace refresh")
        if refresh["status"] == "SUCCESS" and refresh["response_sha256"] is None:
            raise RuleFailure("successful Code Intelligence refresh lacks response hash")
        if refresh["status"] == "FAILED" and not refresh["error"]:
            raise RuleFailure("failed Code Intelligence refresh lacks error")
        if refresh["status"] == "SUCCESS":
            if refresh["freshness"] not in {
                "refresh_acknowledged",
                "spot_checked",
            }:
                raise RuleFailure("successful Code Intelligence refresh lacks freshness evidence")
        elif refresh["freshness"] != "not_verified":
            raise RuleFailure("unsuccessful Code Intelligence refresh cannot claim freshness")
        for item in refresh["paths"]:
            path = resolve_repo_reference(repo, item["path"])
            if item["change"] in {"ADDED", "MODIFIED", "RENAMED"}:
                if not path.is_file() or item["sha256"] != file_sha256(path):
                    raise RuleFailure(f"Code Intelligence refresh hash is stale: {item['path']}")
            elif item["sha256"] is not None:
                raise RuleFailure("deleted Code Intelligence path cannot have a hash")
    observed_statuses = {item["status"] for item in value["queries"]}
    refresh_status = refresh["status"] if refresh is not None else None
    if value["status"] == "FAILED" and (
        "FAILED" not in observed_statuses and refresh_status != "FAILED"
    ):
        raise RuleFailure("failed Code Intelligence record lacks a failed operation")
    if value["status"] == "USED" and (
        not observed_statuses.intersection({"SUCCESS", "EMPTY"})
        and refresh_status != "SUCCESS"
    ):
        raise RuleFailure("used Code Intelligence record lacks a successful operation")
    if value["status"] == "UNAVAILABLE" and (
        observed_statuses.intersection({"SUCCESS", "EMPTY", "FAILED"})
        or refresh_status in {"SUCCESS", "FAILED"}
    ):
        raise RuleFailure("unavailable Code Intelligence record contains an attempted operation")
    return value


def record(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    value = validate_record_value(repo, task_id, value, root)
    directory = task_dir(repo, task_id)
    destination = code_intelligence_record_path(
        directory, value["work_item_revision"], _record_name(value)
    )
    if destination.exists():
        raise InputFailure(f"Code Intelligence record is immutable: {destination}")
    write_json_atomic(destination, value)
    validate_json_file(
        destination, root / "schemas" / "code-intelligence-record.schema.json"
    )
    return {
        "message": f"recorded optional Code Intelligence evidence for {value['stage']}",
        "path": str(destination),
        "status": value["status"],
    }


def record_reference(repo: Path, task_id: str, reference: Any) -> dict[str, Any]:
    if reference is None:
        return {}
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise RuleFailure("invalid Code Intelligence record reference")
    directory = task_dir(repo, task_id)
    path = confined_target(directory, directory / reference["path"], "Code Intelligence record")
    if not path.is_file() or file_sha256(path) != reference["sha256"]:
        raise RuleFailure("Code Intelligence record reference changed or is missing")
    value = validate_record_value(repo, task_id, read_json(path))
    expected = code_intelligence_record_path(
        directory, value["work_item_revision"], _record_name(value)
    )
    if path != expected:
        raise RuleFailure("Code Intelligence record reference uses a non-canonical path")
    return value
