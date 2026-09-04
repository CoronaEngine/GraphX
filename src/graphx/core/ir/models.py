"""Immutable Workflow IR declarations constructed only by the Compiler."""

from dataclasses import InitVar, dataclass
from enum import StrEnum

from graphx.core.config.models import (
    CanonicalTreeRevisionPolicy,
    ConditionExpr,
    NodeId,
    ProcessSpec,
    RetryPolicy,
    SideEffectClass,
    TimeoutPolicy,
    ValueExpr,
    ValueSchema,
    WorkflowId,
    WorkflowOutcome,
)
from graphx.core.ir.canonicalization import DigestHex


class IRNodeKind(StrEnum):
    AGENT = "agent"
    COMMAND = "command"
    VERIFIER = "verifier"
    GATE = "gate"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class IRInputBinding:
    name: str
    expression: ValueExpr


@dataclass(frozen=True, slots=True)
class IROutputDeclaration:
    name: str
    schema: ValueSchema


@dataclass(frozen=True, slots=True)
class IRNode:
    id: NodeId
    kind: IRNodeKind
    dependencies: tuple[NodeId, ...]
    side_effect: SideEffectClass | None
    inputs: tuple[IRInputBinding, ...] = ()
    outputs: tuple[IROutputDeclaration, ...] = ()
    when: ConditionExpr | None = None
    condition: ConditionExpr | None = None
    condition_hash: DigestHex | None = None
    task: str | None = None
    process_spec: ProcessSpec | None = None
    check_id: str | None = None
    check_hash: DigestHex | None = None
    acceptance_criteria: tuple[str, ...] = ()
    retry: RetryPolicy | None = None
    timeout: TimeoutPolicy | None = None
    settles_mutation: NodeId | None = None
    settlement_recovery_attempts: int | None = None
    outcome: WorkflowOutcome | None = None


class _CompilerToken:
    __slots__ = ()


_COMPILER_TOKEN = _CompilerToken()


@dataclass(frozen=True, slots=True)
class WorkflowIR:
    _compiler_token: InitVar[_CompilerToken]
    workflow_id: WorkflowId
    nodes: tuple[IRNode, ...]
    stable_node_order: tuple[NodeId, ...]
    schema_version: int
    compiler_version: str
    canonicalization_profile: str
    digest: DigestHex
    revision_policy: CanonicalTreeRevisionPolicy | None = None

    def __post_init__(self, _compiler_token: _CompilerToken) -> None:
        if _compiler_token is not _COMPILER_TOKEN:
            raise TypeError("WorkflowIR may only be constructed by the Compiler")
