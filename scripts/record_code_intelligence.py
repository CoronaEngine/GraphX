#!/usr/bin/env python3
"""Record compact optional Code Intelligence evidence or plan an index refresh."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from internal.code_intelligence_protocol import (
    plan_refresh,
    record,
    select_provider,
)
from internal.polaris_core import (
    InputFailure,
    read_json,
    require_protocol_compatible,
    run_main,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path)
    parser.add_argument("--available-tool", action="append", default=[])
    parser.add_argument("--select-provider", action="store_true")
    parser.add_argument("--plan-refresh", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--subject-base")
    parser.add_argument("--subject-head")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()

    def execute() -> dict[str, object]:
        require_protocol_compatible(repo)
        if args.select_provider:
            selected = select_provider(repo, args.available_tool)
            return {"selected": selected, "available": selected is not None}
        if args.plan_refresh:
            if not args.provider or not args.subject_base or not args.subject_head:
                raise InputFailure(
                    "--plan-refresh requires --provider, --subject-base, and --subject-head"
                )
            return plan_refresh(
                repo, args.subject_base, args.subject_head, args.provider
            )
        if args.task_id is None or args.input is None:
            raise InputFailure("recording requires task_id and --input")
        input_path = args.input if args.input.is_absolute() else repo / args.input
        return record(repo, args.task_id, read_json(input_path))

    return run_main(execute, args.json)


if __name__ == "__main__":
    sys.exit(main())
