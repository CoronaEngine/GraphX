#!/usr/bin/env python3
"""Project-scoped stdio MCP server for bounded Polaris CodeGraph queries."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from internal.code_intelligence_proxy import execute_proxy_query
from internal.path_security import require_regular_file
from internal.polaris_core import (
    InputFailure,
    RuleFailure,
    protocol_root,
)


PROTOCOL_VERSION = "2025-11-25"
TOOL_NAME = "polaris_codegraph_explore"
SERVER_ROOT = Path(__file__).resolve().parent.parent
TOOL = {
    "name": TOOL_NAME,
    "description": "Run one bounded Polaris CodeGraph freshness window.",
    "inputSchema": {
        "type": "object",
        "required": [
            "task_id",
            "stage",
            "query_id",
            "purpose",
            "query",
            "sync_if_needed",
        ],
        "additionalProperties": False,
        "properties": {
            "task_id": {"type": "string", "pattern": r"^TASK-[0-9]{4}$"},
            "stage": {
                "type": "string",
                "enum": [
                    "PLANNING",
                    "IMPLEMENTATION",
                    "DOCUMENTATION_SYNC",
                    "REVIEW",
                ],
            },
            "query_id": {"type": "string", "pattern": r"^CIQ-[0-9]{3}$"},
            "purpose": {"type": "string", "minLength": 1, "maxLength": 240},
            "query": {"type": "string", "minLength": 1, "maxLength": 8000},
            "sync_if_needed": {"type": "boolean"},
        },
    },
}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": " ".join(message.split())[:240]},
    }


def _result(request_id: Any, value: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": " ".join(message.split())[:240]}
        ],
        "isError": True,
    }


def _valid_request_id(value: Any) -> bool:
    return value is None or (
        not isinstance(value, bool) and isinstance(value, (int, str))
    )


def _validate_arguments(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["tool arguments must be an object"]
    expected = {
        "task_id",
        "stage",
        "query_id",
        "purpose",
        "query",
        "sync_if_needed",
    }
    errors: list[str] = []
    missing = expected - set(value)
    extra = set(value) - expected
    if missing:
        errors.append("missing arguments: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unknown arguments: " + ", ".join(sorted(extra)))
    task_id = value.get("task_id")
    if not isinstance(task_id, str) or re.fullmatch(r"TASK-[0-9]{4}", task_id) is None:
        errors.append("task_id must match TASK-0000")
    if value.get("stage") not in {
        "PLANNING",
        "IMPLEMENTATION",
        "DOCUMENTATION_SYNC",
        "REVIEW",
    }:
        errors.append("stage is invalid")
    query_id = value.get("query_id")
    if not isinstance(query_id, str) or re.fullmatch(r"CIQ-[0-9]{3}", query_id) is None:
        errors.append("query_id must match CIQ-000")
    for key, maximum in (("purpose", 240), ("query", 8000)):
        item = value.get(key)
        if not isinstance(item, str) or not item.strip() or len(item) > maximum:
            errors.append(f"{key} must contain 1 to {maximum} characters")
    if not isinstance(value.get("sync_if_needed"), bool):
        errors.append("sync_if_needed must be a boolean")
    return errors


class McpServer:
    """Small stateful MCP dispatcher with no dependencies beyond the stdlib."""

    def __init__(self, repo: Path) -> None:
        raw_repo = repo.absolute()
        if raw_repo.is_symlink() or not raw_repo.is_dir():
            raise InputFailure("MCP repository root must be a fixed real directory")
        self.repo = raw_repo.resolve()
        if protocol_root(self.repo).resolve() != SERVER_ROOT:
            raise RuleFailure(
                "MCP repository does not match the executing vendored protocol root"
            )
        require_regular_file(
            self.repo / ".polaris/project.json", "Polaris project configuration"
        )
        self.initialized = False
        self.ready = False

    def _initialize(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if self.initialized:
            return _error(request_id, -32600, "MCP server is already initialized")
        if (
            params.get("protocolVersion") != PROTOCOL_VERSION
            or not isinstance(params.get("capabilities"), dict)
            or not isinstance(params.get("clientInfo"), dict)
        ):
            return _error(request_id, -32602, "unsupported or incomplete initialize params")
        self.initialized = True
        version = (protocol_root(self.repo) / "VERSION").read_text(
            encoding="utf-8"
        ).strip()
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "polaris-codegraph", "version": version},
            },
        )

    def _call_tool(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("name") != TOOL_NAME:
            return _error(request_id, -32602, "unknown MCP tool name")
        arguments = params.get("arguments")
        errors = _validate_arguments(arguments)
        if errors:
            return _result(request_id, _tool_error("; ".join(errors)))
        assert isinstance(arguments, dict)
        try:
            proxy = execute_proxy_query(
                self.repo,
                arguments["task_id"],
                arguments["stage"],
                arguments["query_id"],
                arguments["purpose"],
                arguments["query"],
                arguments["sync_if_needed"],
            )
            content = [{"type": "text", "text": proxy["envelope"]}]
            if proxy["response"] is not None:
                content.append({"type": "text", "text": proxy["response"]})
            return _result(
                request_id,
                {
                    "content": content,
                    "structuredContent": {"bundle": proxy["bundle"]},
                    "isError": False,
                },
            )
        except (InputFailure, RuleFailure, OSError, ValueError) as error:
            return _result(request_id, _tool_error(str(error)))
        except Exception as error:  # keep the long-lived stdio server usable
            return _result(
                request_id,
                _tool_error(f"CodeGraph proxy execution failed: {type(error).__name__}"),
            )

    def handle(self, message: Any) -> dict[str, Any] | None:
        """Handle one decoded JSON-RPC message; notifications return ``None``."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "invalid JSON-RPC request")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(message.get("id"), -32600, "request method must be a string")
        has_id = "id" in message
        request_id = message.get("id")
        if has_id and not _valid_request_id(request_id):
            return _error(None, -32600, "invalid JSON-RPC request id")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return None if not has_id else _error(request_id, -32602, "params must be an object")

        if method == "initialize":
            if not has_id:
                return None
            return self._initialize(request_id, params)
        if method == "notifications/initialized":
            if not has_id and self.initialized:
                self.ready = True
            return None
        known_methods = {"ping", "tools/list", "tools/call"}
        if method not in known_methods:
            return None if not has_id else _error(request_id, -32601, "method not found")
        if not self.ready:
            return None if not has_id else _error(request_id, -32600, "MCP server is not initialized")
        if not has_id:
            return None
        if method == "ping":
            return _result(request_id, {})
        if method == "tools/list":
            return _result(request_id, {"tools": [TOOL]})
        return self._call_tool(request_id, params)


def _write_message(value: dict[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()


def serve(repo: Path) -> int:
    if repo.absolute().resolve() != Path.cwd().resolve():
        raise InputFailure("MCP repository must match the process working directory")
    server = McpServer(repo)
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            _write_message(_error(None, -32700, "parse error"))
            continue
        response = server.handle(message)
        if response is not None:
            _write_message(response)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    try:
        return serve(args.repo)
    except (InputFailure, RuleFailure, OSError) as error:
        print(" ".join(str(error).split())[:240], file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
