"""Shared mechanical rules for Validation artifacts."""

from __future__ import annotations

from typing import Any

from .polaris_core import RuleFailure


def validate_acceptance_ids(work_item: dict[str, Any]) -> None:
    """Require stable unique IDs before a Work Item becomes authority."""
    identifiers = [item["id"] for item in work_item["acceptance"]]
    if len(identifiers) != len(set(identifiers)):
        raise RuleFailure("Work Item contains duplicate acceptance IDs")


def validate_acceptance_coverage(
    work_item: dict[str, Any], validation: dict[str, Any]
) -> None:
    """Require one passing Validation result for every acceptance criterion."""
    validate_acceptance_ids(work_item)
    expected = [item["id"] for item in work_item["acceptance"]]
    results = validation["acceptance_results"]
    actual = [item["acceptance_id"] for item in results]
    if (
        len(actual) != len(expected)
        or len(set(actual)) != len(actual)
        or set(actual) != set(expected)
        or any(item["result"] != "PASS" for item in results)
    ):
        raise RuleFailure(
            "Validation must cover every acceptance criterion exactly once with PASS"
        )
