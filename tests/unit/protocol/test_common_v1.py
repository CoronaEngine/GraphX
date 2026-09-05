from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphx.protocol.common_v1 import (
    DigestHexText,
    IdempotencyKeyText,
    OpaqueIdText,
    SafeDiagnosticText,
    StrictWireModel,
    WireVersion,
)


class CommonProbe(StrictWireModel):
    wire_version: WireVersion
    digest: DigestHexText
    opaque_id: OpaqueIdText
    idempotency_key: IdempotencyKeyText
    diagnostics: SafeDiagnosticText


def valid_probe() -> dict[str, object]:
    return {
        "wire_version": 1,
        "digest": "a" * 64,
        "opaque_id": "execution-1",
        "idempotency_key": "request-key",
        "diagnostics": "safe summary",
    }


def test_plan_4_4_strict_wire_model_is_closed_and_frozen() -> None:
    """协议模型拒绝未知字段和创建后的字段修改。"""
    probe = CommonProbe.model_validate(valid_probe())

    with pytest.raises(ValidationError, match="frozen"):
        probe.diagnostics = "changed"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        CommonProbe.model_validate({**valid_probe(), "unknown": True})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wire_version", 2),
        ("wire_version", True),
        ("digest", "A" * 64),
        ("digest", "a" * 63),
        ("opaque_id", ""),
        ("opaque_id", "e\u0301"),
        ("idempotency_key", "contains\x00nul"),
        ("diagnostics", "x" * 65_537),
    ],
    ids=[
        "unknown-version",
        "boolean-version",
        "uppercase-digest",
        "short-digest",
        "empty-id",
        "non-nfc-id",
        "nul-idempotency-key",
        "diagnostics-too-long",
    ],
)
def test_plan_4_4_common_wire_types_reject_invalid_values(field: str, value: object) -> None:
    """公共协议字段拒绝非法版本、标识和超长诊断。"""
    candidate = valid_probe()
    candidate[field] = value

    with pytest.raises(ValidationError):
        CommonProbe.model_validate(candidate)


def test_plan_4_4_diagnostic_limit_counts_utf8_bytes() -> None:
    """诊断文本按 UTF-8 字节数执行长度边界检查。"""
    candidate = valid_probe()
    candidate["diagnostics"] = "é" * 32_768

    assert CommonProbe.model_validate(candidate).diagnostics == "é" * 32_768

    candidate["diagnostics"] = "é" * 32_768 + "a"
    with pytest.raises(ValidationError, match="65536 UTF-8 bytes"):
        CommonProbe.model_validate(candidate)
