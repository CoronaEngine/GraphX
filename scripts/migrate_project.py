#!/usr/bin/env python3
"""Apply or resume the one explicit migration into the vendored Polaris version."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from internal.install_manifest import validate_install_manifest
from internal.migration_protocol import migrate_project as apply_migration
from internal.polaris_core import InputFailure, protocol_root, run_main
from validate_project import validate as validate_project


def migrate(repo: Path) -> dict[str, object]:
    root = protocol_root(repo)
    if root != repo / "tools" / "polaris":
        raise InputFailure("vendor the target Polaris version before migrating the project")
    validate_install_manifest(repo, root)
    result = apply_migration(repo, root)
    validate_project(repo)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run_main(lambda: migrate(args.repo.resolve()), args.json)


if __name__ == "__main__":
    sys.exit(main())
