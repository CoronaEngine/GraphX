"""Provider-neutral, best-effort Code Intelligence configuration and evidence."""

from __future__ import annotations

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
    validate_json_file,
    validate_schema,
    write_json_atomic,
)
from .task_location_protocol import resolve_repo_reference
from .task_layout import code_intelligence_record_path, state_path


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
    repo: Path, task_id: str, value: dict[str, Any]
) -> tuple[Path, str, str | None]:
    directory = task_dir(repo, task_id)
    state = read_json(state_path(directory))
    if value["task_id"] != task_id or value["work_item_revision"] != state["current_revision"]:
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
    repo: Path, task_id: str, value: dict[str, Any], root: Path
) -> dict[str, Any]:
    errors = validate_schema(
        value, read_json(root / "schemas" / "code-intelligence-record.schema.json")
    )
    if errors:
        raise RuleFailure("Code Intelligence record failed schema validation:\n- " + "\n- ".join(errors))
    _, base, head = _validate_record_identity(repo, task_id, value)
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


def validate_record_value(
    repo: Path, task_id: str, value: dict[str, Any], root: Path | None = None
) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    if value.get("record_version") == 1:
        return validate_legacy_record_value(repo, task_id, value, root)
    return _validate_v2_record_value(repo, task_id, value, root)


def record(
    repo: Path,
    task_id: str,
    value: dict[str, Any],
    root: Path | None = None,
) -> dict[str, Any]:
    root = protocol_root(repo) if root is None else root
    if value.get("record_version") == 1:
        raise InputFailure("new Code Intelligence records must use record_version 2")
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
