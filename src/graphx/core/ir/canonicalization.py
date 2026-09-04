"""Canonical JSON v1 serialization and domain-separated hashing."""

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from enum import Enum
from typing import Final, NewType, TypeGuard

CANONICALIZATION_PROFILE_ID: Final = "graphx-canonical-json-v1"
MIN_SIGNED_64: Final = -(2**63)
MAX_SIGNED_64: Final = 2**63 - 1

DigestHex = NewType("DigestHex", str)
type CanonicalScalar = bool | int | str | None
type CanonicalValue = (
    CanonicalScalar | tuple["CanonicalValue", ...] | Mapping[str, "CanonicalValue"]
)


class CanonicalizationError(ValueError):
    """A value cannot be represented by the canonical JSON v1 profile."""


class DigestDomain(Enum):
    """Closed digest domains defined by plan.md section 4.7."""

    IR = "graphx-ir-v1"
    CONTRACT = "graphx-contract-v1"
    REQUEST = "graphx-request-v1"
    RESPONSE = "graphx-response-v1"
    REVISION = "graphx-revision-v1"
    WORKSPACE_IDENTITY = "graphx-workspace-identity-v1"


def _validate_string(value: str) -> None:
    if "\x00" in value:
        raise CanonicalizationError("canonical strings must not contain NUL")
    if unicodedata.normalize("NFC", value) != value:
        raise CanonicalizationError("canonical strings must use NFC normalization")


def _encode_string(value: str) -> str:
    _validate_string(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _encode_mapping(value: Mapping[object, object]) -> str:
    items: list[tuple[str, object]] = []
    for raw_key in value:
        if not isinstance(raw_key, str):
            raise CanonicalizationError("canonical object keys must be strings")
        _validate_string(raw_key)
        item: object = value[raw_key]
        items.append((raw_key, item))

    items.sort(key=lambda item: item[0].encode("utf-8"))
    encoded = (f"{_encode_string(key)}:{_encode(item)}" for key, item in items)
    return "{" + ",".join(encoded) + "}"


def _is_object_tuple(value: object) -> TypeGuard[tuple[object, ...]]:
    return isinstance(value, tuple)


def _is_object_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    return isinstance(value, Mapping)


def _encode(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not MIN_SIGNED_64 <= value <= MAX_SIGNED_64:
            raise CanonicalizationError("canonical integers must fit signed 64-bit range")
        return str(value)
    if isinstance(value, str):
        return _encode_string(value)
    if _is_object_tuple(value):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if _is_object_mapping(value):
        return _encode_mapping(value)
    raise CanonicalizationError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json_bytes(value: object) -> bytes:
    """Validate and return the canonical UTF-8 encoding of a JSON value."""
    return _encode(value).encode("utf-8")


def domain_digest(domain: object, value: object) -> DigestHex:
    """Return the domain-separated SHA-256 digest of a canonical value."""
    if not isinstance(domain, DigestDomain):
        raise CanonicalizationError("unsupported digest domain")
    payload = domain.value.encode("ascii") + b"\x00" + canonical_json_bytes(value)
    return DigestHex(hashlib.sha256(payload).hexdigest())
