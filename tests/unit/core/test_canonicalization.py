from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from graphx.core.ir.canonicalization import (
    CANONICALIZATION_PROFILE_ID,
    CanonicalizationError,
    DigestDomain,
    canonical_json_bytes,
    domain_digest,
)

FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "canonicalization_v1.json"


class GoldenVector(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: str
    value: dict[str, str | int]
    canonicalHex: str
    domain: DigestDomain
    digest: str


class GoldenVectors(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    profile: str
    vectors: tuple[GoldenVector, ...]


def _golden_vectors() -> GoldenVectors:
    return GoldenVectors.model_validate_json(FIXTURE_PATH.read_bytes())


def test_canon_01_matches_checked_in_golden_vectors() -> None:
    fixture = _golden_vectors()

    assert fixture.profile == "graphx-canonical-json-v1"
    assert fixture.profile == CANONICALIZATION_PROFILE_ID
    for vector in fixture.vectors:
        assert canonical_json_bytes(vector.value).hex() == vector.canonicalHex
        assert domain_digest(vector.domain, vector.value) == vector.digest


def test_canon_01_preserves_array_order_and_json_scalar_spelling() -> None:
    value = (True, False, None, -7, "line\nfeed")

    assert canonical_json_bytes(value) == b'[true,false,null,-7,"line\\nfeed"]'


@pytest.mark.parametrize("value", [-(2**63), 2**63 - 1])
def test_canon_01_accepts_signed_64_bit_boundaries(value: int) -> None:
    assert canonical_json_bytes(value) == str(value).encode("ascii")


@pytest.mark.parametrize("value", [-(2**63) - 1, 2**63])
def test_canon_01_rejects_integer_outside_signed_64_bit(value: int) -> None:
    with pytest.raises(CanonicalizationError, match="signed 64-bit"):
        canonical_json_bytes(value)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (1.5, "unsupported canonical value"),
        ("e\u0301", "NFC"),
        ("contains\x00nul", "NUL"),
        ({1: "not-a-string-key"}, "object keys must be strings"),
        ([1, 2], "unsupported canonical value"),
    ],
)
def test_canon_01_rejects_values_outside_the_closed_profile(value: object, message: str) -> None:
    with pytest.raises(CanonicalizationError, match=message):
        canonical_json_bytes(value)


def test_canon_01_rejects_unknown_digest_domain() -> None:
    with pytest.raises(CanonicalizationError, match="digest domain"):
        domain_digest("graphx-unknown-v1", {})
