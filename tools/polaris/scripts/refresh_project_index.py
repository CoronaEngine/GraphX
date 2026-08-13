#!/usr/bin/env python3
"""Refresh the bounded human-readable project recovery map."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from polaris_core import run_main
from recovery_protocol import refresh_project_index


def refresh(repo: Path) -> dict[str, object]:
    result = refresh_project_index(repo)
    return {
        "message": f"refreshed project recovery map for {len(result['tasks'])} tasks",
        "path": str(repo / ".polaris" / "project-index.md"),
        "recommended_task": result["recommended_task"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: refresh(args.repo.resolve()), args.json)


if __name__ == "__main__":
    sys.exit(main())
