"""Provider-neutral, best-effort Code Intelligence configuration and evidence."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable

from .path_security import confined_target, require_regular_file, require_regular_tree
from .polaris_core import (
    InputFailure,
    RuleFailure,
    file_sha256,
    full_commit,
    protocol_root,
    read_json,
    subject_diff_hash,
    task_dir,
    utc_now,
    validate_json_file,
    validate_schema,
    write_json_atomic,
)
from .task_location_protocol import resolve_repo_reference
from .task_layout import (
    code_intelligence_record_path,
    code_intelligence_runtime_dir,
    state_path,
    task_relative_path,
)


CONFIG_PATH = Path(".polaris/code-intelligence.json")
OPERATIONS = {
    "explore",
    "status",
    "sync",
}
STAGE_NAMES = {
    "PLANNING": "planning",
    "IMPLEMENTATION": "implementation-{attempt:03d}",
    "DOCUMENTATION_SYNC": "documentation-sync-{attempt:03d}",
    "REVIEW": "review-{attempt:03d}-slot-{reviewer_slot}",
}
LEGACY_WORKSPACE_REFRESH = "refresh_" + "workspace"
LEGACY_REFRESH_ACKNOWLEDGED = "refresh_" + "acknowledged"
LEGACY_SPOT_CHECKED = "spot_" + "checked"
LEGACY_NOT_VERIFIED = "not_" + "verified"
MAX_SEARCH_SOURCE_RESULTS = 100


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


def _project_marker_path(repo: Path, marker: str) -> Path:
    path = Path(marker)
    if path.is_absolute() or len(path.parts) != 1 or path.parts[0] in {".", ".."}:
        raise RuleFailure(f"unsafe Code Intelligence project marker: {marker}")
    target = repo / path
    if target.is_symlink():
        raise RuleFailure(f"Code Intelligence project marker must not be a symlink: {target}")
    return target


def select_provider(
    repo: Path,
    available_tools: Iterable[str],
    root: Path | None = None,
    available_executables: Iterable[str] = (),
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
    executables = set(available_executables)
    for provider_id in priority:
        descriptor = providers.get(provider_id)
        if descriptor is None:
            raise RuleFailure(f"unknown configured Code Intelligence provider: {provider_id}")
        if not _project_marker_path(repo, descriptor["project_marker"]).is_dir():
            continue
        operations = {
            operation: tool
            for operation, tool in descriptor["operations"].items()
            if tool in available
        }
        cli_available = descriptor["cli"]["executable"] in executables
        if operations or cli_available:
            return {
                "provider_id": provider_id,
                "provider_version": descriptor["provider_version"],
                "transport": descriptor["transport"],
                "operations": operations,
                "cli_available": cli_available,
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


def add_provider(
    repo: Path, provider_id: str, root: Path | None = None
) -> dict[str, Any]:
    """Configure one Provider without probing or initializing its runtime."""
    root = protocol_root(repo) if root is None else root
    validate_static_configuration(repo, root)
    providers = load_providers(root)
    if provider_id not in providers:
        raise InputFailure(
            f"unknown Code Intelligence provider: {provider_id}; "
            f"available providers: {', '.join(sorted(providers))}"
        )
    config = load_config(repo, root)
    priority = [
        provider_id,
        *(item for item in config["provider_priority"] if item != provider_id),
    ]
    changed = config["mode"] != "auto_optional" or priority != config["provider_priority"]
    config["mode"] = "auto_optional"
    config["provider_priority"] = priority
    errors = validate_schema(
        config, read_json(root / "schemas" / "code-intelligence-config.schema.json")
    )
    if errors:
        raise RuleFailure(
            "Code Intelligence configuration failed schema validation:\n- "
            + "\n- ".join(errors)
        )
    destination = repo / CONFIG_PATH
    if not destination.is_file():
        changed = True
    if changed:
        write_json_atomic(destination, config)
    return {
        "message": (
            f"added {providers[provider_id]['display_name']} to Polaris Code Intelligence; "
            "Provider initialization remains the user's decision; "
            "runtime availability will be checked by the next workflow; "
            "fallback remains enabled"
        ),
        "provider": provider_id,
        "configuration": CONFIG_PATH.as_posix(),
        "mode": config["mode"],
        "provider_priority": config["provider_priority"],
        "changed": changed,
        "runtime_status": "checked_by_next_workflow",
        "fallback": "enabled",
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


def _validate_legacy_record_value(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    root: Path,
    require_current_revision: bool,
) -> dict[str, Any]:
    schema = read_json(root / "schemas" / "code-intelligence-record-v1.schema.json")
    errors = validate_schema(value, schema)
    if errors:
        raise RuleFailure(
            "Code Intelligence record failed schema validation:\n- "
            + "\n- ".join(errors)
        )
    if value["task_id"] != task_id:
        raise RuleFailure("Code Intelligence record targets the wrong task revision")
    if require_current_revision:
        directory = task_dir(repo, task_id)
        state = read_json(state_path(directory))
        if value["work_item_revision"] != state["current_revision"]:
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
        if changes & {"DELETED", "RENAMED"} and refresh["operation"] != LEGACY_WORKSPACE_REFRESH:
            raise RuleFailure("deleted or renamed code requires workspace refresh")
        if refresh["status"] == "SUCCESS" and refresh["response_sha256"] is None:
            raise RuleFailure("successful Code Intelligence refresh lacks response hash")
        if refresh["status"] == "FAILED" and not refresh["error"]:
            raise RuleFailure("failed Code Intelligence refresh lacks error")
        if refresh["status"] == "SUCCESS":
            if refresh["freshness"] not in {
                LEGACY_REFRESH_ACKNOWLEDGED,
                LEGACY_SPOT_CHECKED,
            }:
                raise RuleFailure("successful Code Intelligence refresh lacks freshness evidence")
        elif refresh["freshness"] != LEGACY_NOT_VERIFIED:
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


def validate_legacy_record_value(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate legacy evidence only when it names the task's current revision."""
    root = protocol_root(repo) if root is None else root
    return _validate_legacy_record_value(repo, task_id, value, root, True)


def validate_historical_legacy_record_value(
    repo: Path,
    task_id: str,
    path: Path,
    value: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate an immutable v1 record at its canonical historical location."""
    root = protocol_root(repo) if root is None else root
    value = _validate_legacy_record_value(repo, task_id, value, root, False)
    directory = task_dir(repo, task_id)
    expected = code_intelligence_record_path(
        directory, value["work_item_revision"], _record_name(value)
    )
    if path != expected:
        raise RuleFailure("Code Intelligence record reference uses a non-canonical path")
    return value


def _validate_record_identity(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    *,
    require_current_revision: bool = True,
) -> tuple[Path, str, str | None]:
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    if value["task_id"] != task_id or (
        require_current_revision
        and value["work_item_revision"] != state["current_revision"]
    ):
        raise RuleFailure("Code Intelligence record targets the wrong task revision")
    _record_name(value)
    target = value["target"]
    base = full_commit(repo, target["base_commit"])
    head = target["head_commit"]
    if head is None:
        if target["diff_hash"] is not None:
            raise RuleFailure("base-only Code Intelligence target cannot have a diff hash")
    else:
        head = full_commit(repo, head)
        if target["diff_hash"] != subject_diff_hash(repo, base, head):
            raise RuleFailure("Code Intelligence target diff hash is stale")
    return directory, base, head


def _matching_fallback(
    fallbacks: list[dict[str, Any]], action: str, path: str | None, digest: str | None
) -> dict[str, Any] | None:
    for fallback in fallbacks:
        if (
            fallback["action"] == action
            and fallback["path"] == path
            and fallback["observed_sha256"] == digest
        ):
            return fallback
    return None


def _validate_source_fallbacks(
    repo: Path,
    value: dict[str, Any],
    base: str,
    head: str | None,
) -> None:
    target = value["target"]
    for fallback in value["source_fallbacks"]:
        action = fallback["action"]
        path = fallback["path"]
        digest = fallback["observed_sha256"]
        result_paths = fallback["result_paths"]
        if not fallback["purpose"]:
            raise RuleFailure("source fallback requires a non-empty purpose")
        if action != "SEARCH_SOURCE" and result_paths:
            raise RuleFailure("non-SEARCH_SOURCE fallback must use empty result_paths")
        if action == "READ_SOURCE":
            if not isinstance(path, str) or digest is None:
                raise RuleFailure("READ_SOURCE fallback requires a current SHA")
            resolved = resolve_repo_reference(repo, path)
            if not resolved.is_file() or file_sha256(resolved) != digest:
                raise RuleFailure(f"READ_SOURCE fallback hash is stale: {path}")
            if any(item is not None for item in (fallback["base_commit"], fallback["head_commit"], fallback["diff_hash"])):
                raise RuleFailure("READ_SOURCE fallback cannot claim a Git diff target")
        elif action == "INSPECT_GIT_DIFF":
            if not isinstance(path, str) or digest is not None:
                raise RuleFailure("INSPECT_GIT_DIFF fallback requires a null SHA")
            if resolve_repo_reference(repo, path).is_file():
                raise RuleFailure("INSPECT_GIT_DIFF fallback cannot describe an existing file")
            if head is None or (
                fallback["base_commit"] != base
                or fallback["head_commit"] != head
                or fallback["diff_hash"] != target["diff_hash"]
            ):
                raise RuleFailure("INSPECT_GIT_DIFF fallback requires the target base/head/diff hash")
        else:
            if path is not None or digest is not None:
                raise RuleFailure("SEARCH_SOURCE fallback cannot name a path or SHA")
            if any(item is not None for item in (fallback["base_commit"], fallback["head_commit"], fallback["diff_hash"])):
                raise RuleFailure("SEARCH_SOURCE fallback cannot claim a Git diff target")
            if len(result_paths) > MAX_SEARCH_SOURCE_RESULTS:
                raise RuleFailure(
                    f"SEARCH_SOURCE fallback may record at most {MAX_SEARCH_SOURCE_RESULTS} result paths"
                )
            seen_paths: set[str] = set()
            for result in result_paths:
                result_path = result["path"]
                if result_path in seen_paths:
                    raise RuleFailure("duplicate SEARCH_SOURCE result path")
                seen_paths.add(result_path)
                resolved = resolve_repo_reference(repo, result_path)
                if not resolved.is_file():
                    raise RuleFailure(
                        f"SEARCH_SOURCE result is not a current regular file: {result_path}"
                    )
                if file_sha256(resolved) != result["observed_sha256"]:
                    raise RuleFailure(
                        f"SEARCH_SOURCE result hash is stale: {result_path}"
                    )


def _validate_v2_freshness(
    repo: Path, value: dict[str, Any], base: str, head: str | None
) -> None:
    freshness = value["freshness"]
    points = freshness["stale_points"]
    fallbacks = value["source_fallbacks"]
    file_points = [point for point in points if point["scope"] == "FILE"]
    index_points = [point for point in points if point["scope"] == "INDEX"]
    for point in file_points:
        if (
            not isinstance(point["path"], str)
            or point["reason"] != "PENDING_SYNC"
            or point["fallback"] not in {"READ_SOURCE", "INSPECT_GIT_DIFF"}
        ):
            raise RuleFailure("file stale point is invalid")
        if point["fallback"] == "READ_SOURCE":
            if point["observed_sha256"] is None:
                raise RuleFailure("READ_SOURCE stale point requires a current SHA")
            resolved = resolve_repo_reference(repo, point["path"])
            if not resolved.is_file() or file_sha256(resolved) != point["observed_sha256"]:
                raise RuleFailure(f"stale file hash is stale: {point['path']}")
        elif point["observed_sha256"] is not None:
            raise RuleFailure("INSPECT_GIT_DIFF stale point requires a null SHA")
        if _matching_fallback(
            fallbacks, point["fallback"], point["path"], point["observed_sha256"]
        ) is None:
            raise RuleFailure("stale point requires a matching source fallback")
    for point in index_points:
        if (
            point["path"] is not None
            or point["fallback"] != "SEARCH_SOURCE"
            or point["observed_sha256"] is not None
            or point["reason"] == "PENDING_SYNC"
        ):
            raise RuleFailure("index stale point is invalid")
        if _matching_fallback(fallbacks, "SEARCH_SOURCE", None, None) is None:
            raise RuleFailure("stale point requires a matching source fallback")
    status = freshness["status"]
    basis = freshness["basis"]
    if status != "UNAVAILABLE" and "NONE" in basis:
        raise RuleFailure("freshness basis NONE is reserved for UNAVAILABLE")
    if status == "CURRENT_AT_CHECK" and points:
        raise RuleFailure("CURRENT_AT_CHECK cannot contain stale points")
    if status == "CURRENT_AT_CHECK" and "STATUS_JSON" not in basis:
        sync_acknowledged = (
            value["sync"] is not None
            and value["sync"]["status"] == "SUCCESS"
            and "SYNC_ACKNOWLEDGED" in basis
        )
        if not sync_acknowledged:
            raise RuleFailure(
                "CURRENT_AT_CHECK requires STATUS_JSON or successful sync acknowledgement"
            )
    if status == "PARTIAL_STALE" and (not file_points or index_points):
        raise RuleFailure("PARTIAL_STALE requires only file stale points")
    if status == "INDEX_STALE" and not index_points:
        raise RuleFailure("INDEX_STALE requires an index stale point")
    if status == "NOT_VERIFIED" and not any(
        point["reason"] == "STATUS_UNREADABLE" for point in index_points
    ):
        raise RuleFailure("NOT_VERIFIED requires STATUS_UNREADABLE")
    if status == "UNAVAILABLE":
        if freshness["basis"] != ["NONE"] or points:
            raise RuleFailure("UNAVAILABLE freshness must use NONE with no stale points")
        if (
            value["sync"] is not None
            and value["sync"]["status"] != "UNAVAILABLE"
        ) or any(
            item["status"] != "UNAVAILABLE" for item in value["queries"]
        ):
            raise RuleFailure("UNAVAILABLE record contains an attempted query or sync")


def _validate_v2_record_value(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    root: Path,
    *,
    require_current_revision: bool = True,
) -> dict[str, Any]:
    errors = validate_schema(
        value, read_json(root / "schemas" / "code-intelligence-record-v2.schema.json")
    )
    if errors:
        raise RuleFailure("Code Intelligence record failed schema validation:\n- " + "\n- ".join(errors))
    _, base, head = _validate_record_identity(
        repo,
        task_id,
        value,
        require_current_revision=require_current_revision,
    )
    provider = value["provider"]
    if value["status"] in {"USED", "FAILED"} and provider is None:
        raise RuleFailure("used or failed Code Intelligence record requires a provider")
    if provider is not None:
        descriptor = load_providers(root).get(provider["id"])
        if (
            descriptor is None
            or provider["descriptor_version"] != descriptor["provider_version"]
            or provider["transport"] != descriptor["transport"]
            or not set(provider["available_operations"]).issubset(OPERATIONS)
        ):
            raise RuleFailure("Code Intelligence record names an invalid provider capability set")
    freshness = value["freshness"]
    if freshness["status"] == "UNAVAILABLE" and freshness["response_sha256"] is not None:
        raise RuleFailure("UNAVAILABLE freshness response hash must be null")
    if value["status"] == "UNAVAILABLE" and (
        freshness["status"] != "UNAVAILABLE"
        or "RESPONSE_BANNER" in freshness["basis"]
    ):
        raise RuleFailure(
            "UNAVAILABLE Code Intelligence record cannot claim observed graph freshness"
        )
    if "RESPONSE_BANNER" in freshness["basis"] and (
        provider is None or "explore" not in provider["available_operations"]
    ):
        raise RuleFailure(
            "RESPONSE_BANNER freshness requires an advertised explore capability"
        )
    query_ids = [item["id"] for item in value["queries"]]
    expected_ids = [f"CIQ-{index:03d}" for index in range(1, len(query_ids) + 1)]
    if query_ids != expected_ids:
        raise RuleFailure("Code Intelligence query IDs must be sequential")
    for query in value["queries"]:
        if provider is not None and query["status"] != "UNAVAILABLE" and "explore" not in provider["available_operations"]:
            raise RuleFailure(f"query used an unavailable provider operation: {query['id']}")
        if query["status"] == "SUCCESS" and query["response_sha256"] is None:
            raise RuleFailure(f"successful query lacks response hash: {query['id']}")
        if query["status"] == "FAILED" and not query["error"]:
            raise RuleFailure(f"failed query lacks error: {query['id']}")
        for symbol in query["symbols"]:
            path = resolve_repo_reference(repo, symbol["path"])
            if not path.is_file():
                raise RuleFailure(f"Code Intelligence symbol path is not a file: {symbol['path']}")
    if "RESPONSE_BANNER" in freshness["basis"]:
        response_sha256 = freshness["response_sha256"]
        successful_explore_hashes = {
            query["response_sha256"]
            for query in value["queries"]
            if query["status"] == "SUCCESS" and query["response_sha256"] is not None
        }
        if not successful_explore_hashes:
            raise RuleFailure(
                "RESPONSE_BANNER freshness requires a successful explore query with a response hash"
            )
        if response_sha256 is None:
            raise RuleFailure("RESPONSE_BANNER freshness response hash is required")
        if response_sha256 not in successful_explore_hashes:
            raise RuleFailure(
                "RESPONSE_BANNER freshness response hash must match a successful explore query"
            )
    elif freshness["response_sha256"] is not None:
        raise RuleFailure("freshness response hash requires RESPONSE_BANNER basis")
    status_check = value["status_check"]
    if status_check is not None:
        status_check_status = status_check["status"]
        if status_check_status == "SUCCESS":
            if status_check["response_sha256"] is None or status_check["error"] is not None:
                raise RuleFailure("successful Code Intelligence status check requires a response hash and no error")
            if provider is None or "status" not in provider["available_operations"]:
                raise RuleFailure("successful Code Intelligence status check requires status capability")
        elif status_check_status == "FAILED":
            if not status_check["error"]:
                raise RuleFailure("failed Code Intelligence status check lacks error")
            if provider is None or "status" not in provider["available_operations"]:
                raise RuleFailure("failed Code Intelligence status check requires status capability")
        elif status_check_status == "UNAVAILABLE":
            if (
                status_check["phase"] != "STAGE_ENTRY"
                or status_check["response_sha256"] is not None
                or status_check["error"] is not None
            ):
                raise RuleFailure("unavailable Code Intelligence status check cannot contain response or error evidence")
        elif status_check["response_sha256"] is not None:
            raise RuleFailure("non-successful Code Intelligence status check cannot have a response hash")
    sync = value["sync"]
    if sync is not None:
        if sync["status"] != "UNAVAILABLE" and (
            provider is None or "sync" not in provider["available_operations"]
        ):
            raise RuleFailure("Code Intelligence sync evidence requires sync capability")
        if sync["status"] == "SUCCESS":
            if sync["response_sha256"] is None or "SYNC_ACKNOWLEDGED" not in value["freshness"]["basis"]:
                raise RuleFailure("successful Code Intelligence sync requires a response hash and SYNC_ACKNOWLEDGED basis")
        if sync["status"] == "FAILED" and not sync["error"]:
            raise RuleFailure("failed Code Intelligence sync lacks error")
        if sync["status"] == "UNAVAILABLE" and (
            sync["response_sha256"] is not None or sync["error"] is not None
        ):
            raise RuleFailure("unavailable Code Intelligence sync cannot contain response or error evidence")
    status_check_success = status_check is not None and status_check["status"] == "SUCCESS"
    status_check_evidence = status_check is not None and status_check["status"] in {
        "SUCCESS", "FAILED"
    }
    if freshness["status"] != "UNAVAILABLE" and "NONE" in freshness["basis"]:
        raise RuleFailure("freshness basis NONE is reserved for UNAVAILABLE")
    if "STATUS_JSON" in freshness["basis"] and not status_check_evidence:
        raise RuleFailure("STATUS_JSON basis requires structured status check evidence")
    if freshness["status"] == "CURRENT_AT_CHECK":
        if not status_check_success:
            raise RuleFailure("CURRENT_AT_CHECK requires a successful status check")
    if sync is not None and sync["status"] == "SUCCESS":
        if (
            freshness["status"] != "CURRENT_AT_CHECK"
            or not status_check_success
            or status_check["phase"] != "POST_SYNC"
        ):
            raise RuleFailure("successful sync requires a successful POST_SYNC status check")
    if sync is not None and sync["status"] == "FAILED":
        if freshness["status"] != "INDEX_STALE" or not any(
            point["reason"] == "SYNC_FAILED" for point in freshness["stale_points"]
        ):
            raise RuleFailure("failed sync requires INDEX_STALE freshness with SYNC_FAILED")
        if "SYNC_ACKNOWLEDGED" in freshness["basis"]:
            raise RuleFailure("failed sync cannot claim SYNC_ACKNOWLEDGED")
    if status_check is not None and status_check["phase"] == "POST_SYNC":
        if sync is None or sync["status"] not in {"SUCCESS", "FAILED"}:
            raise RuleFailure("POST_SYNC status check requires an attempted sync")
        if sync["status"] == "FAILED" and sync["response_sha256"] is None:
            raise RuleFailure("POST_SYNC status check requires a hashed sync attempt")
    if value["status"] == "UNAVAILABLE" and (
        status_check is not None and status_check["status"] != "UNAVAILABLE"
    ):
        raise RuleFailure("unavailable Code Intelligence record cannot claim a status check")
    _validate_source_fallbacks(repo, value, base, head)
    _validate_v2_freshness(repo, value, base, head)
    observed_statuses = {item["status"] for item in value["queries"]}
    sync_status = sync["status"] if sync is not None else None
    if (
        value["status"] == "FAILED"
        and "FAILED" not in observed_statuses
        and sync_status != "FAILED"
        and (status_check is None or status_check["status"] != "FAILED")
    ):
        raise RuleFailure("failed Code Intelligence record lacks a failed operation")
    if value["status"] == "USED" and not observed_statuses.intersection({"SUCCESS", "EMPTY"}) and sync_status != "SUCCESS":
        raise RuleFailure("used Code Intelligence record lacks a successful operation")
    return value


def validate_historical_v2_record_value(
    repo: Path,
    task_id: str,
    path: Path,
    value: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Validate immutable v2 evidence at its canonical historical location."""
    root = protocol_root(repo) if root is None else root
    value = _validate_v2_record_value(
        repo,
        task_id,
        value,
        root,
        require_current_revision=False,
    )
    expected = code_intelligence_record_path(
        task_dir(repo, task_id), value["work_item_revision"], _record_name(value)
    )
    if path != expected:
        raise RuleFailure("Code Intelligence record reference uses a non-canonical path")
    return value


def _require_exact_keys(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RuleFailure(f"{label} has an invalid field set")
    return value


def _zero_pending(value: Any) -> bool:
    return isinstance(value, dict) and value == {
        "added": 0,
        "modified": 0,
        "removed": 0,
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_v3_stale_point(repo: Path, point: Any) -> dict[str, Any]:
    point = _require_exact_keys(
        point,
        {"scope", "path", "reason", "fallback", "observed_sha256"},
        "Code Intelligence stale point",
    )
    if point["scope"] == "FILE":
        if (
            not isinstance(point["path"], str)
            or point["reason"] != "PENDING_SYNC"
            or point["fallback"] not in {"READ_SOURCE", "INSPECT_GIT_DIFF"}
        ):
            raise RuleFailure("v3 file stale point is invalid")
        resolved = resolve_repo_reference(repo, point["path"])
        if point["fallback"] == "READ_SOURCE":
            if (
                not resolved.is_file()
                or point["observed_sha256"] != file_sha256(resolved)
            ):
                raise RuleFailure("v3 READ_SOURCE stale point hash is stale")
        elif point["observed_sha256"] is not None or resolved.is_file():
            raise RuleFailure("v3 INSPECT_GIT_DIFF stale point must name a missing path")
    elif point["scope"] == "INDEX":
        if (
            point["path"] is not None
            or point["fallback"] != "SEARCH_SOURCE"
            or point["observed_sha256"] is not None
            or point["reason"] not in {
                "PENDING_CHANGES",
                "AUTO_SYNC_DISABLED",
                "WORKTREE_MISMATCH",
                "INDEX_PARTIAL",
                "INDEX_INDEXING",
                "INDEX_FAILED",
                "PENDING_REFERENCES",
                "REINDEX_RECOMMENDED",
                "SYNC_FAILED",
                "STATUS_UNREADABLE",
            }
        ):
            raise RuleFailure("v3 index stale point is invalid")
    else:
        raise RuleFailure("v3 stale point scope is invalid")
    return point


def _validate_v3_status_observation(
    repo: Path, observation: Any, label: str
) -> dict[str, Any]:
    observation = _require_exact_keys(
        observation,
        {
            "status",
            "checked_at",
            "basis",
            "stale_points",
            "status_response_sha256",
            "error",
            "needs_sync",
            "pending_changes",
        },
        label,
    )
    if (
        observation["status"]
        not in {"CURRENT_AT_CHECK", "INDEX_STALE", "NOT_VERIFIED", "UNAVAILABLE"}
        or not isinstance(observation["checked_at"], str)
        or not observation["checked_at"]
        or not isinstance(observation["basis"], list)
        or not isinstance(observation["needs_sync"], bool)
        or not isinstance(observation["stale_points"], list)
    ):
        raise RuleFailure(f"{label} has invalid status fields")
    for point in observation["stale_points"]:
        _validate_v3_stale_point(repo, point)
    status = observation["status"]
    if status in {"CURRENT_AT_CHECK", "INDEX_STALE"}:
        if (
            not _is_sha256(observation["status_response_sha256"])
            or not isinstance(observation["pending_changes"], dict)
            or set(observation["pending_changes"])
            != {"added", "modified", "removed"}
            or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in observation["pending_changes"].values()
            )
            or observation["error"] is not None
            or "STATUS_JSON" not in observation["basis"]
            or len(observation["basis"]) != len(set(observation["basis"]))
            or not set(observation["basis"]).issubset(
                {"STATUS_JSON", "SYNC_ACKNOWLEDGED"}
            )
        ):
            raise RuleFailure(f"{label} successful status evidence is incomplete")
        if status == "CURRENT_AT_CHECK" and observation["stale_points"]:
            raise RuleFailure(f"{label} current status cannot contain stale points")
        if status == "INDEX_STALE" and not observation["stale_points"]:
            raise RuleFailure(f"{label} stale status requires stale points")
    elif status == "NOT_VERIFIED":
        if (
            observation["pending_changes"] is not None
            or not observation["error"]
            or observation["basis"] != ["STATUS_JSON"]
            or (
                observation["status_response_sha256"] is not None
                and not _is_sha256(observation["status_response_sha256"])
            )
        ):
            raise RuleFailure(f"{label} NOT_VERIFIED evidence is incomplete")
    elif (
        observation["status_response_sha256"] is not None
        or observation["pending_changes"] is not None
        or not observation["error"]
        or observation["basis"] != ["NONE"]
        or observation["stale_points"]
    ):
        raise RuleFailure(f"{label} UNAVAILABLE evidence is invalid")
    return observation


def _validate_v3_sync(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    value = _require_exact_keys(
        value,
        {"status", "response_sha256", "error"},
        "Code Intelligence v3 sync",
    )
    if value["status"] not in {"SUCCESS", "FAILED"}:
        raise RuleFailure("v3 sync must describe exactly one attempted command")
    if value["status"] == "SUCCESS" and (
        not _is_sha256(value["response_sha256"]) or value["error"] is not None
    ):
        raise RuleFailure("successful v3 sync requires a response hash")
    if value["status"] == "FAILED" and (
        not value["error"]
        or (
            value["response_sha256"] is not None
            and not _is_sha256(value["response_sha256"])
        )
    ):
        raise RuleFailure("failed v3 sync requires an error")
    return value


def _validate_v3_response(repo: Path, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    value = _require_exact_keys(
        value,
        {
            "classification",
            "checked_at",
            "basis",
            "stale_points",
            "response_sha256",
            "error",
        },
        "Code Intelligence v3 response classification",
    )
    if (
        value["classification"]
        not in {"NONE", "PARTIAL_STALE", "INDEX_STALE", "NOT_VERIFIED"}
        or not _is_sha256(value["response_sha256"])
        or value["basis"] != ["RESPONSE_BANNER"]
    ):
        raise RuleFailure("v3 response classification is invalid")
    for point in value["stale_points"]:
        _validate_v3_stale_point(repo, point)
    if value["classification"] == "NONE" and (
        value["stale_points"] or value["error"] is not None
    ):
        raise RuleFailure("neutral v3 response cannot contain stale evidence")
    if value["classification"] in {"PARTIAL_STALE", "INDEX_STALE"} and (
        not value["stale_points"] or value["error"] is not None
    ):
        raise RuleFailure("stale v3 response requires explicit stale points")
    if value["classification"] == "NOT_VERIFIED" and not value["error"]:
        raise RuleFailure("unverified v3 response requires an error")
    return value


def _validate_v3_fallback_matches(value: dict[str, Any]) -> None:
    fallbacks = value["source_fallbacks"]
    points = value["delivery"]["stale_points"]
    for point in points:
        if point["reason"] == "STATUS_UNREADABLE":
            continue
        if _matching_fallback(
            fallbacks,
            point["fallback"],
            point["path"],
            point["observed_sha256"],
        ) is None:
            raise RuleFailure("v3 stale point requires exact source fallback evidence")
    required = value["delivery"]["required_fallback"]
    if required == "NONE" and fallbacks:
        raise RuleFailure("CURRENT v3 evidence cannot contain source fallbacks")
    if required != "NONE" and not fallbacks:
        raise RuleFailure("non-current v3 evidence requires source fallback evidence")
    if required == "SEARCH_SOURCE" and not any(
        fallback["action"] == "SEARCH_SOURCE" for fallback in fallbacks
    ):
        raise RuleFailure("v3 evidence requires a SEARCH_SOURCE fallback")


def _validate_v3_record_value(
    repo: Path, task_id: str, value: dict[str, Any], root: Path
) -> dict[str, Any]:
    errors = validate_schema(
        value, read_json(root / "schemas/code-intelligence-record.schema.json")
    )
    if errors:
        raise RuleFailure(
            "Code Intelligence record failed schema validation:\n- "
            + "\n- ".join(errors)
        )
    _, base, head = _validate_record_identity(repo, task_id, value)
    project = read_json(repo / ".polaris/project.json")
    expected_repository = {
        "project_id": project["project_id"],
        "root_sha256": hashlib.sha256(
            str(repo.resolve()).encode("utf-8")
        ).hexdigest(),
    }
    if value["repository"] != expected_repository:
        raise RuleFailure("Code Intelligence v3 repository identity does not match")
    if value["provider"] != {"id": "codegraph", "descriptor_version": 2}:
        raise RuleFailure("Code Intelligence v3 requires the official CodeGraph provider")
    query = value["query"]
    if query["status"] == "SUCCESS":
        if query["response_sha256"] is None or query["error"] is not None:
            raise RuleFailure("successful v3 query requires a response hash and no error")
    elif not query["error"] or query["response_sha256"] is not None:
        raise RuleFailure("unsuccessful v3 query requires only a finite error")
    for symbol in query["symbols"]:
        if not resolve_repo_reference(repo, symbol["path"]).is_file():
            raise RuleFailure(f"v3 symbol path is not a current file: {symbol['path']}")

    window = value["query_window"]
    pre = _validate_v3_status_observation(repo, window["pre_status"], "pre-query status")
    sync = _validate_v3_sync(window["sync"])
    post_sync = (
        _validate_v3_status_observation(repo, window["post_sync_status"], "post-sync status")
        if window["post_sync_status"] is not None
        else None
    )
    response = _validate_v3_response(repo, window["response_classification"])
    post = (
        _validate_v3_status_observation(repo, window["post_query_status"], "post-query status")
        if window["post_query_status"] is not None
        else None
    )
    if sync is None and post_sync is not None:
        raise RuleFailure("post-sync status requires one sync attempt")
    if sync is not None and sync["status"] == "SUCCESS" and post_sync is None:
        raise RuleFailure("successful sync requires post-sync status evidence")
    if sync is not None and sync["status"] == "SUCCESS" and (
        post_sync["status"] != "CURRENT_AT_CHECK" or post_sync["needs_sync"]
    ):
        raise RuleFailure("successful sync requires a current post-sync status")
    if query["status"] == "SUCCESS" and (
        response is None
        or response["response_sha256"] != query["response_sha256"]
        or post is None
    ):
        raise RuleFailure("successful v3 query requires matching response and post-status evidence")
    if query["status"] != "SUCCESS" and (response is not None or post is not None):
        raise RuleFailure("unsuccessful v3 query cannot claim response or post-status evidence")

    delivery = value["delivery"]
    for point in delivery["stale_points"]:
        _validate_v3_stale_point(repo, point)
    effective = post_sync if post_sync is not None else pre
    observed_points: list[dict[str, Any]] = [
        point
        for point in pre["stale_points"]
        if point["reason"] == "STATUS_UNREADABLE"
    ]
    for observation in (effective, post):
        if observation is None:
            continue
        observed_points.extend(observation["stale_points"])
        if (
            observation is effective
            and sync is not None
            and sync["status"] == "FAILED"
        ):
            observed_points.append({
                "scope": "INDEX",
                "path": None,
                "reason": "SYNC_FAILED",
                "fallback": "SEARCH_SOURCE",
                "observed_sha256": None,
            })
        pending = observation["pending_changes"]
        if isinstance(pending, dict) and any(pending.values()):
            pending_point = {
                "scope": "INDEX",
                "path": None,
                "reason": "PENDING_CHANGES",
                "fallback": "SEARCH_SOURCE",
                "observed_sha256": None,
            }
            if pending_point not in observed_points:
                observed_points.append(pending_point)
    if response is not None:
        observed_points.extend(response["stale_points"])
    unique_points: list[dict[str, Any]] = []
    for point in observed_points:
        if point not in unique_points:
            unique_points.append(point)
    if delivery["stale_points"] != unique_points:
        raise RuleFailure("v3 delivery stale points do not match the observed query window")
    successful_pending = [
        observation["pending_changes"]
        for observation in (effective, post)
        if observation is not None and isinstance(observation["pending_changes"], dict)
    ]
    expected_pending = {
        key: max((pending[key] for pending in successful_pending), default=0)
        for key in ("added", "modified", "removed")
    }
    if delivery["pending_changes"] != expected_pending:
        raise RuleFailure("v3 delivery pending counts do not match the query window")
    state = delivery["state"]
    expected_record_status = {
        "CURRENT": "CURRENT_AT_CHECK",
        "STALE": (
            "INDEX_STALE"
            if any(point["scope"] == "INDEX" for point in delivery["stale_points"])
            else "PARTIAL_STALE"
        ),
        "UNKNOWN": "NOT_VERIFIED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[state]
    if delivery["record_status"] != expected_record_status:
        raise RuleFailure("v3 delivery state contradicts its record freshness status")
    expected_value_status = {
        "CURRENT": "USED",
        "STALE": "USED" if query["status"] == "SUCCESS" else "FAILED",
        "UNKNOWN": "FAILED",
        "UNAVAILABLE": "UNAVAILABLE",
    }[state]
    if value["status"] != expected_value_status:
        raise RuleFailure("v3 record status contradicts proxy delivery")
    if state == "CURRENT":
        if (
            query["status"] != "SUCCESS"
            or response["classification"] != "NONE"
            or effective["status"] != "CURRENT_AT_CHECK"
            or effective["needs_sync"]
            or not _zero_pending(effective["pending_changes"])
            or post["status"] != "CURRENT_AT_CHECK"
            or post["needs_sync"]
            or not _zero_pending(post["pending_changes"])
            or delivery["usage"] != "NON_AUTHORITATIVE_CONTEXT"
            or delivery["required_fallback"] != "NONE"
            or delivery["stale_points"]
            or not _zero_pending(delivery["pending_changes"])
            or delivery["error"] is not None
        ):
            raise RuleFailure("CURRENT v3 evidence lacks a complete zero-pending window")
    elif state == "STALE":
        if (
            query["status"] not in {"SUCCESS", "FAILED"}
            or delivery["usage"] != "NAVIGATION_ONLY"
            or delivery["required_fallback"] == "NONE"
            or not any(
                point["reason"] != "STATUS_UNREADABLE"
                for point in delivery["stale_points"]
            )
            or (query["status"] == "FAILED" and not delivery["error"])
        ):
            raise RuleFailure("STALE v3 evidence lacks an explicit stale reason")
    elif state == "UNKNOWN":
        if (
            delivery["usage"] != "NAVIGATION_ONLY"
            or delivery["required_fallback"] != "SEARCH_SOURCE"
            or not delivery["error"]
        ):
            raise RuleFailure("UNKNOWN v3 evidence lacks verification failure evidence")
    elif (
        query["status"] != "UNAVAILABLE"
        or pre["status"] != "UNAVAILABLE"
        or any(item is not None for item in (sync, post_sync, response, post))
        or delivery["usage"] != "NO_GRAPH"
        or delivery["stale_points"]
    ):
        raise RuleFailure("UNAVAILABLE v3 evidence contains an attempted operation")
    _validate_source_fallbacks(repo, value, base, head)
    if state in {"STALE", "UNKNOWN"}:
        confirmed_paths: set[str] = set()
        for fallback in value["source_fallbacks"]:
            if fallback["action"] == "READ_SOURCE":
                confirmed_paths.add(fallback["path"])
            elif fallback["action"] == "SEARCH_SOURCE":
                confirmed_paths.update(
                    result["path"] for result in fallback["result_paths"]
                )
        for symbol in query["symbols"]:
            if symbol["path"] not in confirmed_paths:
                raise RuleFailure(
                    "non-current v3 symbol requires current source fallback evidence"
                )
    _validate_v3_fallback_matches(value)
    return value


def validate_record_value(
    repo: Path, task_id: str, value: dict[str, Any], root: Path | None = None
) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    version = value.get("record_version")
    if version == 1:
        return validate_legacy_record_value(repo, task_id, value, root)
    if version == 2:
        return _validate_v2_record_value(repo, task_id, value, root)
    if version == 3:
        return _validate_v3_record_value(repo, task_id, value, root)
    raise RuleFailure("unsupported Code Intelligence record version")


def record(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    if value.get("record_version") != 3:
        raise InputFailure("new Code Intelligence records must use record_version 3")
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


def record_proxy_bundle(
    repo: Path,
    task_id: str,
    bundle_path: Path,
    annotations: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    """Project one immutable proxy bundle into the only writable v3 record shape."""
    repo = repo.resolve()
    root = protocol_root(repo) if root is None else root
    directory = task_dir(repo, task_id)
    runtime = code_intelligence_runtime_dir(directory)
    candidate = bundle_path if bundle_path.is_absolute() else repo / bundle_path
    candidate = confined_target(runtime, candidate, "CodeGraph proxy bundle")
    require_regular_file(candidate, "CodeGraph proxy bundle")
    bundle_digest = file_sha256(candidate)
    bundle = read_json(candidate)
    from .code_intelligence_proxy import (
        LEGACY_REFRESH_POLICY_V2,
        REFRESH_POLICY,
        resolve_stage_context,
    )

    version = bundle.get("bundle_version")
    base_keys = {
        "bundle_version", "proxy", "provider", "repository", "task_context",
        "query", "pre_status", "sync", "post_sync_status",
        "response_classification", "post_query_status", "delivery",
        "response_path",
    }
    if version == 1:
        _require_exact_keys(bundle, base_keys, "CodeGraph proxy bundle")
    elif version == 2:
        _require_exact_keys(
            bundle, {*base_keys, "refresh_policy"}, "CodeGraph proxy bundle"
        )
        if bundle["refresh_policy"] != LEGACY_REFRESH_POLICY_V2:
            raise RuleFailure("CodeGraph proxy bundle has an invalid refresh policy")
    elif version == 3:
        _require_exact_keys(
            bundle, {*base_keys, "refresh_policy"}, "CodeGraph proxy bundle"
        )
        if bundle["refresh_policy"] != REFRESH_POLICY:
            raise RuleFailure("CodeGraph proxy bundle has an invalid refresh policy")
        delivery = bundle.get("delivery")
        if (
            isinstance(delivery, dict)
            and delivery.get("state") != "UNAVAILABLE"
            and (
                not isinstance(bundle.get("sync"), dict)
                or bundle["sync"].get("status") not in {"SUCCESS", "FAILED"}
            )
        ):
            raise RuleFailure(
                "CodeGraph v3 proxy bundle lacks its mandatory sync attempt"
            )
    else:
        raise RuleFailure("CodeGraph proxy bundle has an unsupported identity")
    if bundle["proxy"] != {
        "server_id": "polaris-codegraph",
        "tool": "polaris_codegraph_explore",
    }:
        raise RuleFailure("CodeGraph proxy bundle has an unsupported identity")
    if bundle["provider"] != {"id": "codegraph", "descriptor_version": 2}:
        raise RuleFailure("CodeGraph proxy bundle does not use the official provider")
    context = bundle["task_context"]
    _require_exact_keys(
        context,
        {
            "task_id",
            "work_item_revision",
            "stage",
            "artifact_attempt",
            "reviewer_slot",
            "record_name",
            "target",
        },
        "CodeGraph proxy task context",
    )
    if context["task_id"] != task_id:
        raise RuleFailure("CodeGraph proxy bundle targets the wrong task")
    if context != resolve_stage_context(repo, task_id, context["stage"]):
        raise RuleFailure("CodeGraph proxy bundle stage context is no longer current")
    query = _require_exact_keys(
        bundle["query"],
        {"id", "purpose", "text", "status", "response_sha256", "error"},
        "CodeGraph proxy query",
    )
    query_match = re.fullmatch(r"CIQ-([0-9]{3})", str(query["id"]))
    if query_match is None or query_match.group(1) == "000":
        raise RuleFailure("CodeGraph proxy bundle has an invalid query ID")
    expected_path = directory / task_relative_path(
        "code_intelligence_proxy_bundle",
        record_name=context["record_name"],
        query_id=query["id"],
    )
    if candidate != expected_path:
        raise RuleFailure("CodeGraph proxy bundle uses a non-canonical runtime path")
    query_number = int(query_match.group(1))
    for number in range(1, query_number + 1):
        prior = directory / task_relative_path(
            "code_intelligence_proxy_bundle",
            record_name=context["record_name"],
            query_id=f"CIQ-{number:03d}",
        )
        require_regular_file(prior, "sequential CodeGraph proxy bundle")
    project = read_json(repo / ".polaris/project.json")
    expected_repository = {
        "project_id": project["project_id"],
        "root_sha256": hashlib.sha256(
            str(repo.resolve()).encode("utf-8")
        ).hexdigest(),
    }
    if bundle["repository"] != expected_repository:
        raise RuleFailure("CodeGraph proxy bundle repository identity does not match")
    response_path = bundle["response_path"]
    if response_path is None:
        if query["status"] == "SUCCESS" and bundle["delivery"]["state"] != "UNKNOWN":
            raise RuleFailure("successful CodeGraph bundle lost its response evidence")
    else:
        if not isinstance(response_path, str):
            raise RuleFailure("CodeGraph proxy response path is invalid")
        response_file = confined_target(
            directory, directory / response_path, "CodeGraph proxy response"
        )
        require_regular_file(response_file, "CodeGraph proxy response")
        if query["response_sha256"] != file_sha256(response_file):
            raise RuleFailure("CodeGraph proxy response hash does not match")
    annotation_errors = validate_schema(
        annotations,
        read_json(root / "schemas/code-intelligence-record-annotations.schema.json"),
    )
    if annotation_errors:
        raise RuleFailure(
            "Code Intelligence annotations failed schema validation:\n- "
            + "\n- ".join(annotation_errors)
        )
    if response_path is None and annotations["symbols"]:
        raise RuleFailure("discarded CodeGraph output cannot annotate graph symbols")
    delivery = bundle.get("delivery")
    if not isinstance(delivery, dict) or delivery.get("state") not in {
        "CURRENT",
        "STALE",
        "UNKNOWN",
        "UNAVAILABLE",
    }:
        raise RuleFailure("CodeGraph proxy bundle has an invalid delivery state")
    record_value = {
        "record_version": 3,
        "task_id": task_id,
        "work_item_revision": context["work_item_revision"],
        "stage": context["stage"],
        "artifact_attempt": context["artifact_attempt"],
        "reviewer_slot": context["reviewer_slot"],
        "provider": bundle["provider"],
        "repository": bundle["repository"],
        "target": context["target"],
        "status": {
            "CURRENT": "USED",
            "STALE": (
                "USED" if query["status"] == "SUCCESS" else "FAILED"
            ),
            "UNKNOWN": "FAILED",
            "UNAVAILABLE": "UNAVAILABLE",
        }[delivery["state"]],
        "proxy": {
            **bundle["proxy"],
            "evidence_bundle_sha256": bundle_digest,
        },
        "query": {
            **query,
            "summary": annotations["summary"],
            "symbols": annotations["symbols"],
        },
        "query_window": {
            "pre_status": bundle["pre_status"],
            "sync": bundle["sync"],
            "post_sync_status": bundle["post_sync_status"],
            "response_classification": bundle["response_classification"],
            "post_query_status": bundle["post_query_status"],
        },
        "delivery": delivery,
        "source_fallbacks": annotations["source_fallbacks"],
        "recorded_at": utc_now(),
    }
    return record(repo, task_id, record_value, root)


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
