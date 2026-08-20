#!/usr/bin/env python3
"""Diagnose a Polaris project without modifying repository state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from internal.doctor_protocol import DOCTOR_VERSION, diagnose_project


def _emit_report(report: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=4, ensure_ascii=False))
        return
    print(f"{report['status']}: {report['message']}")
    checks = report["checks"]
    if not isinstance(checks, list):
        raise TypeError("Doctor checks must be a list")
    for check in checks:
        if not isinstance(check, dict):
            raise TypeError("Doctor check must be an object")
        print(f"[{check['status']}] {check['label']}: {check['message']}")
        for evidence in check["evidence"]:
            print(f"  Evidence: {evidence}")
        for action in check["actions"]:
            print(f"  Action: {action}")


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = diagnose_project(args.repo.resolve())
    except Exception as exc:
        report = {
            "doctor_version": DOCTOR_VERSION,
            "status": "ERROR",
            "message": str(exc),
            "repository": str(args.repo),
            "mode": "unknown",
            "summary": {"total": 0, "passed": 0, "warnings": 0, "failed": 0},
            "checks": [],
        }
        _emit_report(report, args.json)
        return 2
    _emit_report(report, args.json)
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
