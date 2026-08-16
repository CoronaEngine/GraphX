#!/usr/bin/env python3
"""Configure optional Code Intelligence Providers for a Polaris project."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from internal.code_intelligence_protocol import add_provider
from internal.polaris_core import require_protocol_compatible, run_main


def add(repo: Path, provider_id: str) -> dict[str, object]:
    require_protocol_compatible(repo)
    return add_provider(repo, provider_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    actions = parser.add_subparsers(dest="action", required=True)
    add_parser = actions.add_parser(
        "add", help="Enable and prioritize an installed Code Intelligence Provider"
    )
    add_parser.add_argument("provider")
    add_parser.add_argument("--repo", type=Path, default=Path.cwd())
    add_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.action == "add":
        return run_main(
            lambda: add(args.repo.resolve(), args.provider), args.json
        )
    raise AssertionError(f"unsupported action: {args.action}")


if __name__ == "__main__":
    sys.exit(main())
