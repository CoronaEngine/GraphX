"""Render and validate project-local Polaris MCP registrations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility
    tomllib = None  # type: ignore[assignment]

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


def _strip_toml_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif quote == "'":
            if character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == "#":
            return line[:index]
    return line


def _toml_key_path(source: str) -> tuple[str, ...]:
    parts: list[str] = []
    position = 0
    while position < len(source):
        while position < len(source) and source[position].isspace():
            position += 1
        if position == len(source):
            break
        if source[position] in {'"', "'"}:
            quote = source[position]
            start = position
            position += 1
            escaped = False
            while position < len(source):
                character = source[position]
                if quote == '"' and escaped:
                    escaped = False
                elif quote == '"' and character == "\\":
                    escaped = True
                elif character == quote:
                    position += 1
                    break
                position += 1
            else:
                raise ValueError("unterminated quoted key")
            token = source[start:position]
            try:
                value = json.loads(token) if quote == '"' else token[1:-1]
            except json.JSONDecodeError as exc:
                raise ValueError("invalid quoted key") from exc
            parts.append(value)
        else:
            match = re.match(r"[A-Za-z0-9_-]+", source[position:])
            if match is None:
                raise ValueError("invalid bare key")
            parts.append(match.group(0))
            position += len(match.group(0))
        while position < len(source) and source[position].isspace():
            position += 1
        if position == len(source):
            break
        if source[position] != ".":
            raise ValueError("invalid dotted key")
        position += 1
    if not parts:
        raise ValueError("empty key")
    return tuple(parts)


def _find_toml_assignment(line: str) -> int | None:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif quote == "'":
            if character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif character == "=":
            return index
    return None


def _toml_compat_value(source: str) -> Any:
    value = source.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _parse_toml_compat(source: str) -> dict[str, Any]:
    """Extract MCP tables on Python 3.10 while preserving unrelated TOML bytes."""
    result: dict[str, Any] = {}
    current_table: tuple[str, ...] = ()
    declared_tables: set[tuple[str, ...]] = set()
    assigned_keys: set[tuple[str, ...]] = set()

    def ensure_table(path: tuple[str, ...]) -> dict[str, Any]:
        node = result
        for part in path:
            existing = node.get(part)
            if existing is None:
                existing = {}
                node[part] = existing
            if not isinstance(existing, dict):
                raise ValueError("table conflicts with a scalar value")
            node = existing
        return node

    for raw_line in source.splitlines():
        line = _strip_toml_comment(raw_line).strip()
        if not line:
            continue
        if line.startswith("["):
            array_table = line.startswith("[[")
            closing = "]]" if array_table else "]"
            opening_length = 2 if array_table else 1
            if not line.endswith(closing):
                raise ValueError("malformed table header")
            current_table = _toml_key_path(line[opening_length:-len(closing)])
            if current_table in declared_tables:
                raise ValueError("duplicate table")
            declared_tables.add(current_table)
            if current_table[0] == "mcp_servers":
                ensure_table(current_table)
            continue
        assignment = _find_toml_assignment(line)
        if assignment is None:
            # Unrelated multiline TOML values are preserved byte-for-byte. The
            # managed block emitted below never uses multiline values.
            continue
        key_path = _toml_key_path(line[:assignment])
        full_path = (*current_table, *key_path)
        if full_path in assigned_keys:
            raise ValueError("duplicate key")
        assigned_keys.add(full_path)
        if not full_path or full_path[0] != "mcp_servers":
            continue
        parent = ensure_table(full_path[:-1])
        if full_path[-1] in parent:
            raise ValueError("key conflicts with a table")
        parent[full_path[-1]] = _toml_compat_value(line[assignment + 1 :])
    return result


def _parse_toml(source: str) -> dict[str, Any]:
    if tomllib is None:
        try:
            return _parse_toml_compat(source)
        except (UnicodeDecodeError, ValueError) as exc:
            raise RuleFailure(f"project MCP TOML is invalid: {exc}") from exc
    try:
        value = tomllib.loads(source)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise RuleFailure(f"project MCP TOML is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise RuleFailure("project MCP TOML root must be a table")
    return value


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
