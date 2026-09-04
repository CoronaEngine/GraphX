"""Untrusted JSON loading for Workflow Config v1."""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeGuard

from pydantic import ValidationError

from graphx.protocol.workflow_v1 import WorkflowConfigV1


class WorkflowDecodeErrorCode(StrEnum):
    INVALID_UTF8 = "invalid_utf8"
    BOM_FORBIDDEN = "bom_forbidden"
    DUPLICATE_KEY = "duplicate_key"
    MALFORMED_JSON = "malformed_json"
    TRAILING_CONTENT = "trailing_content"
    INVALID_SCHEMA = "invalid_schema"


class WorkflowDecodeError(ValueError):
    """Safe structured failure produced before a Config enters Core."""

    def __init__(self, code: WorkflowDecodeErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@dataclass(frozen=True, slots=True)
class _ObjectPairs:
    pairs: tuple[tuple[str, object], ...]


def _object_pairs_hook(pairs: list[tuple[str, object]]) -> _ObjectPairs:
    return _ObjectPairs(tuple(pairs))


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _freeze_json(value: object) -> object:
    if isinstance(value, _ObjectPairs):
        result: dict[str, object] = {}
        for key, item in value.pairs:
            if key in result:
                raise WorkflowDecodeError(WorkflowDecodeErrorCode.DUPLICATE_KEY)
            result[key] = _freeze_json(item)
        return result
    if _is_object_list(value):
        return tuple(_freeze_json(item) for item in value)
    return value


def _decode_utf8(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkflowDecodeError(WorkflowDecodeErrorCode.INVALID_UTF8) from error
    if text.startswith("\ufeff"):
        raise WorkflowDecodeError(WorkflowDecodeErrorCode.BOM_FORBIDDEN)
    return text


def load_workflow_json(payload: bytes) -> WorkflowConfigV1:
    """Decode and validate one complete Workflow Config JSON document."""
    text = _decode_utf8(payload)
    decoder = json.JSONDecoder(object_pairs_hook=_object_pairs_hook)
    start = len(text) - len(text.lstrip())
    try:
        decoded: object
        end: int
        decoded, end = decoder.raw_decode(text, start)
    except json.JSONDecodeError as error:
        raise WorkflowDecodeError(WorkflowDecodeErrorCode.MALFORMED_JSON) from error
    if text[end:].strip():
        raise WorkflowDecodeError(WorkflowDecodeErrorCode.TRAILING_CONTENT)
    frozen = _freeze_json(decoded)
    try:
        return WorkflowConfigV1.model_validate(frozen)
    except ValidationError as error:
        raise WorkflowDecodeError(WorkflowDecodeErrorCode.INVALID_SCHEMA) from error
