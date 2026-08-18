"""Render and validate project-local Polaris MCP registrations."""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility
    from . import _tomllib_compat as tomllib

from .path_security import confined_target, require_regular_file
from .polaris_core import InputFailure, RuleFailure


SERVER_ID = "polaris-codegraph"
TOOL_NAME = "polaris_codegraph_explore"
LAUNCHER = "tools/polaris/scripts/code_intelligence_mcp.py"
ARGS = [LAUNCHER, "--repo", "."]
CODEX_START = f"# POLARIS_MCP_START {SERVER_ID}"
CODEX_END = f"# POLARIS_MCP_END {SERVER_ID}"


def project_mcp_target(repo: Path, adapter: dict[str, Any]) -> Path:
    value = adapter["project_mcp"]["target"]
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise RuleFailure(f"project MCP target must be a safe relative path: {value}")
    return confined_target(repo, repo / relative, "project MCP target")


def _definition(adapter: dict[str, Any]) -> dict[str, Any]:
    registration = adapter["project_mcp"]
    if registration["server_id"] != SERVER_ID:
        raise RuleFailure("project MCP registration has an invalid server ID")
    if registration["command"] != "python3" or registration["args"] != ARGS:
        raise RuleFailure("project MCP registration has an invalid launcher")
    return registration


def _codex_definition(adapter: dict[str, Any]) -> dict[str, Any]:
    registration = _definition(adapter)
    return {
        "command": registration["command"],
        "args": registration["args"],
        "cwd": ".",
        "enabled": True,
        "required": False,
        "enabled_tools": [TOOL_NAME],
    }


def _codex_block(adapter: dict[str, Any]) -> str:
    definition = _codex_definition(adapter)
    args = json.dumps(definition["args"], ensure_ascii=False)
    tools = json.dumps(definition["enabled_tools"], ensure_ascii=False)
    return (
        f"{CODEX_START}\n"
        f"[mcp_servers.{SERVER_ID}]\n"
        f'command = "{definition["command"]}"\n'
        f"args = {args}\n"
        f'cwd = "{definition["cwd"]}"\n'
        "enabled = true\n"
        "required = false\n"
        f"enabled_tools = {tools}\n"
        f"{CODEX_END}\n"
    )


def _parse_toml(source: str) -> dict[str, Any]:
    try:
        value = tomllib.loads(source)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise RuleFailure(f"project MCP TOML is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise RuleFailure("project MCP TOML root must be a table")
    return value


def _without_managed_server(value: dict[str, Any]) -> dict[str, Any]:
    cleaned = copy.deepcopy(value)
    servers = cleaned.get("mcp_servers")
    if isinstance(servers, dict):
        servers.pop(SERVER_ID, None)
        if not servers:
            cleaned.pop("mcp_servers", None)
    return cleaned


def _toml_values_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, float) and math.isnan(left) and math.isnan(right):
        return True
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _toml_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _toml_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _merge_codex(adapter: dict[str, Any], source: str) -> str:
    parsed = _parse_toml(source)
    starts = source.count(CODEX_START)
    ends = source.count(CODEX_END)
    if starts != ends or starts > 1:
        raise RuleFailure("project MCP TOML has malformed or duplicate managed markers")
    block = _codex_block(adapter)
    if starts == 1:
        pattern = re.compile(
            rf"(?m)^{re.escape(CODEX_START)}\n.*?^{re.escape(CODEX_END)}(?:\n|$)",
            re.DOTALL,
        )
        if not pattern.search(source):
            raise RuleFailure("project MCP TOML has malformed managed markers")
        rendered = pattern.sub(block, source, count=1)
    else:
        servers = parsed.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise RuleFailure("project MCP TOML mcp_servers must be a table")
        if SERVER_ID in servers:
            raise RuleFailure(
                f"project MCP TOML has a conflicting unmanaged {SERVER_ID} entry"
            )
        separator = "" if not source else ("\n" if source.endswith("\n") else "\n\n")
        rendered = source + separator + block
    final = _parse_toml(rendered)
    if not _toml_values_equal(
        _without_managed_server(parsed), _without_managed_server(final)
    ):
        raise RuleFailure("project MCP markers would rewrite unrelated TOML")
    servers = final.get("mcp_servers")
    if not isinstance(servers, dict) or servers.get(SERVER_ID) != _codex_definition(
        adapter
    ):
        raise RuleFailure("project MCP TOML did not render the exact Polaris entry")
    return rendered


def _claude_definition(adapter: dict[str, Any]) -> dict[str, Any]:
    registration = _definition(adapter)
    return {
        "type": "stdio",
        "command": registration["command"],
        "args": registration["args"],
        "env": {},
    }


def _parse_json(source: str) -> dict[str, Any]:
    try:
        value = json.loads(source)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuleFailure(f"project MCP JSON is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise RuleFailure("project MCP JSON root must be an object")
    return value


def _merge_claude(adapter: dict[str, Any], source: str) -> str:
    value = _parse_json(source or "{}")
    servers = value.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise RuleFailure("project MCP JSON mcpServers must be an object")
    expected = _claude_definition(adapter)
    existing = servers.get(SERVER_ID)
    if existing is not None and existing != expected:
        raise RuleFailure(f"project MCP JSON has a conflicting {SERVER_ID} entry")
    servers[SERVER_ID] = expected
    return json.dumps(value, ensure_ascii=False, indent=4) + "\n"


def merge_project_mcp(
    repo: Path,
    adapter: dict[str, Any],
    source_text: str | None = None,
) -> str:
    registration = _definition(adapter)
    target = project_mcp_target(repo, adapter)
    if source_text is None:
        if target.exists():
            require_regular_file(target, "project MCP configuration")
            try:
                source_text = target.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise InputFailure(
                    f"project MCP configuration is not UTF-8: {target}"
                ) from exc
        else:
            source_text = ""
    if registration["format"] == "codex-toml":
        return _merge_codex(adapter, source_text)
    if registration["format"] == "claude-json":
        return _merge_claude(adapter, source_text)
    raise RuleFailure(f"unsupported project MCP format: {registration['format']}")


def validate_project_mcp(repo: Path, adapter: dict[str, Any]) -> None:
    registration = _definition(adapter)
    target = project_mcp_target(repo, adapter)
    require_regular_file(target, "project MCP configuration")
    source = target.read_text(encoding="utf-8")
    if registration["format"] == "codex-toml":
        if source.count(CODEX_START) != 1 or source.count(CODEX_END) != 1:
            raise RuleFailure("project MCP TOML lacks the unique managed block")
        parsed = _parse_toml(source)
        servers = parsed.get("mcp_servers")
        if not isinstance(servers, dict) or servers.get(SERVER_ID) != _codex_definition(
            adapter
        ):
            raise RuleFailure("project MCP TOML Polaris entry is invalid")
    elif registration["format"] == "claude-json":
        parsed = _parse_json(source)
        servers = parsed.get("mcpServers")
        if not isinstance(servers, dict) or servers.get(SERVER_ID) != _claude_definition(
            adapter
        ):
            raise RuleFailure("project MCP JSON Polaris entry is invalid")
    else:
        raise RuleFailure(f"unsupported project MCP format: {registration['format']}")
    launcher = confined_target(repo, repo / LAUNCHER, "project MCP launcher")
    require_regular_file(launcher, "project MCP launcher")
