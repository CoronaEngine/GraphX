from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphx.protocol.mcp_v1 import (
    ErrorBodyV1,
    ErrorCodeV1,
    NextRequestV1,
    RetryDirectiveV1,
)


def valid_next_request() -> dict[str, object]:
    return {
        "wireVersion": 1,
        "requestId": "12345678-1234-4234-8234-123456789abc",
        "idempotencyKey": "next-1",
        "runId": "run-1",
        "expectedRunVersion": 3,
    }


def test_idem_01_mutating_request_requires_identity_and_expected_version() -> None:
    assert NextRequestV1.model_validate(valid_next_request()).expected_run_version == 3

    for field in ("requestId", "idempotencyKey", "runId", "expectedRunVersion"):
        payload = valid_next_request()
        payload.pop(field)
        with pytest.raises(ValidationError):
            NextRequestV1.model_validate(payload)


def test_auth_01_public_request_rejects_principal_and_host_identity() -> None:
    for field in ("principalId", "principal", "hostId"):
        with pytest.raises(ValidationError):
            NextRequestV1.model_validate({**valid_next_request(), field: "forged"})


def test_plan_11_1_error_and_retry_enums_are_closed() -> None:
    assert {item.value for item in ErrorCodeV1} == {
        "invalid_request",
        "unsupported_version",
        "unauthenticated",
        "forbidden",
        "not_found",
        "conflict",
        "stale",
        "not_ready",
        "run_not_runnable",
        "reconciliation_required",
        "capability_unavailable",
        "integrity_failure",
        "internal_failure",
    }
    assert {item.value for item in RetryDirectiveV1} == {
        "do_not_retry",
        "retry_same_request",
        "reconcile",
        "user_action",
    }


@pytest.mark.parametrize(
    "unsafe_detail",
    [
        "Traceback (most recent call last):",
        "/Users/zero/private/state.db",
        "token=super-secret",
        "credential: hidden",
        "rawContract: semantic payload",
    ],
)
def test_plan_11_1_error_details_reject_sensitive_text(unsafe_detail: str) -> None:
    with pytest.raises(ValidationError, match="unsafe"):
        ErrorBodyV1.model_validate(
            {
                "code": "internal_failure",
                "retryDirective": "do_not_retry",
                "details": {"summary": unsafe_detail},
                "correlationId": "correlation-1",
            }
        )
