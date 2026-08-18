#!/usr/bin/env python3
"""Run bounded CodeGraph freshness checks for Polaris stage Skills."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from internal.code_intelligence_protocol import load_config, load_providers
from internal.codegraph_adapter import classify_response, inspect_status, sync_if_needed
from internal.polaris_core import (
    InputFailure,
    protocol_root,
    require_protocol_compatible,
    run_main,
    task_dir,
    utc_now,
)
from internal.task_layout import code_intelligence_runtime_dir


def _runtime_directory(directory: Path) -> Path:
    """Return the lexical runtime directory only after rejecting symlink hops."""
    runtime = code_intelligence_runtime_dir(directory)
    runtime_parent = runtime.parent
    for path in (runtime_parent, runtime):
        if path.is_symlink():
            raise InputFailure("CodeGraph response runtime must not cross a symlink")
    if not runtime.is_dir():
        raise InputFailure("CodeGraph response runtime directory is unavailable")
    return runtime.resolve()


def _runtime_input(repo: Path, task_id: str, value: Path) -> Path:
    directory = task_dir(repo, task_id)
    runtime = _runtime_directory(directory)
    candidate = value if value.is_absolute() else repo / value
    if candidate.is_symlink():
        raise InputFailure("CodeGraph response input must not be a symlink")
    candidate = candidate.resolve()
    try:
        relative = candidate.relative_to(runtime)
    except ValueError as error:
        raise InputFailure("CodeGraph response input must be inside task runtime") from error
    cursor = runtime
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise InputFailure("CodeGraph response input must not cross a symlink")
    if not candidate.is_file():
        raise InputFailure("CodeGraph response input must be a regular runtime file")
    return candidate


def _disabled_freshness() -> dict[str, Any]:
    """Return the provider-neutral result for an explicitly disabled project."""
    return {
        "status": "UNAVAILABLE",
        "checked_at": utc_now(),
        "basis": ["NONE"],
        "stale_points": [],
        "status_response_sha256": None,
        "error": "Code Intelligence is disabled by project configuration",
        "needs_sync": False,
        "pending_changes": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", type=Path, default=Path.cwd())
    common.add_argument("--json", action="store_true")
    commands.add_parser("status", parents=[common])
    commands.add_parser("sync-if-needed", parents=[common])
    classify = commands.add_parser("classify-response", parents=[common])
    classify.add_argument("task_id")
    classify.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()

    def execute() -> dict[str, Any]:
        require_protocol_compatible(repo)
        if args.command == "classify-response":
            input_path = _runtime_input(repo, args.task_id, args.input)
            try:
                response = input_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as error:
                raise InputFailure("CodeGraph response input is not UTF-8") from error
            return classify_response(repo, response)
        root = protocol_root(repo)
        if load_config(repo, root)["mode"] == "disabled":
            freshness = _disabled_freshness()
            if args.command == "status":
                return freshness
            return {
                "freshness": freshness,
                "sync": {
                    "status": "UNAVAILABLE",
                    "response_sha256": None,
                    "error": None,
                },
            }
        descriptor = load_providers(root)["codegraph"]
        if args.command == "status":
            return inspect_status(repo, descriptor)
        return sync_if_needed(repo, descriptor)

    return run_main(execute, args.json)


if __name__ == "__main__":
    sys.exit(main())
