"""Dependency-neutral primitives shared by GraphX wire protocol v1 DTOs."""

import unicodedata
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, StringConstraints


def _validate_wire_version(value: object) -> object:
    if type(value) is not int or value != 1:
        raise ValueError("wire version must be integer 1")
    return value


WireVersion = Annotated[Literal[1], BeforeValidator(_validate_wire_version)]
RequestIdText = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
]
DigestHexText = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _validate_bounded_text(value: str, *, label: str, maximum_bytes: int) -> str:
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{label} must use NFC normalization")
    byte_length = len(value.encode("utf-8"))
    if byte_length > maximum_bytes:
        raise ValueError(f"{label} must not exceed {maximum_bytes} UTF-8 bytes")
    return value


def _validate_opaque_id(value: str) -> str:
    return _validate_bounded_text(value, label="opaque identity", maximum_bytes=256)


def _validate_idempotency_key(value: str) -> str:
    return _validate_bounded_text(value, label="idempotency key", maximum_bytes=256)


def _validate_safe_diagnostic(value: str) -> str:
    return _validate_bounded_text(value, label="diagnostics", maximum_bytes=65_536)


OpaqueIdText = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_validate_opaque_id),
]
IdempotencyKeyText = Annotated[
    str,
    StringConstraints(min_length=1),
    AfterValidator(_validate_idempotency_key),
]
SafeDiagnosticText = Annotated[str, AfterValidator(_validate_safe_diagnostic)]


class StrictWireModel(BaseModel):
    """Base for closed, strict and immutable v1 wire objects."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
        revalidate_instances="always",
    )
