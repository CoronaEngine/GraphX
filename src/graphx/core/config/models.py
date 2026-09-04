"""Immutable domain models for a validated Workflow Config."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import NewType

WorkflowId = NewType("WorkflowId", str)
NodeId = NewType("NodeId", str)
InputName = NewType("InputName", str)
OutputName = NewType("OutputName", str)
FieldName = NewType("FieldName", str)


class SideEffectClass(StrEnum):
    NONE = "none"
    WORKSPACE_MUTATION = "workspaceMutation"


class WorkflowOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class BooleanValueSchema:
    pass


@dataclass(frozen=True, slots=True)
class IntegerValueSchema:
    pass


@dataclass(frozen=True, slots=True)
class StringValueSchema:
    max_length: int


@dataclass(frozen=True, slots=True)
class ArrayValueSchema:
    items: "ValueSchema"
    max_items: int


@dataclass(frozen=True, slots=True)
class ObjectValueSchema:
    properties: Mapping[FieldName, "ValueSchema"]
    required: tuple[FieldName, ...]


@dataclass(frozen=True, slots=True)
class ProcessResultValueSchema:
    pass


@dataclass(frozen=True, slots=True)
class VerificationEvidenceValueSchema:
    pass


type ValueSchema = (
    BooleanValueSchema
    | IntegerValueSchema
    | StringValueSchema
    | ArrayValueSchema
    | ObjectValueSchema
    | ProcessResultValueSchema
    | VerificationEvidenceValueSchema
)


@dataclass(frozen=True, slots=True)
class FromValueExpr:
    from_path: str


@dataclass(frozen=True, slots=True)
class LiteralValueExpr:
    literal: bool | int | str


type ValueExpr = FromValueExpr | LiteralValueExpr


@dataclass(frozen=True, slots=True)
class BinaryCondition:
    operator: str
    left: ValueExpr
    right: ValueExpr


@dataclass(frozen=True, slots=True)
class NotCondition:
    operand: "ConditionExpr"


@dataclass(frozen=True, slots=True)
class AllCondition:
    operands: tuple["ConditionExpr", ...]


@dataclass(frozen=True, slots=True)
class AnyCondition:
    operands: tuple["ConditionExpr", ...]


type ConditionExpr = BinaryCondition | NotCondition | AllCondition | AnyCondition


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    argv: tuple[str, ...]
    cwd: str
    success_exit_codes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    seconds: int


@dataclass(frozen=True, slots=True)
class SettlementRecoveryPolicy:
    max_attempts: int


@dataclass(frozen=True, slots=True)
class CanonicalTreeRevisionPolicy:
    authoritative_roots: tuple[str, ...]
    excluded_roots: tuple[str, ...]
    include_untracked: bool


@dataclass(frozen=True, slots=True)
class AgentNodeConfig:
    id: NodeId
    depends_on: tuple[NodeId, ...]
    when: ConditionExpr | None
    side_effect: SideEffectClass
    task: str
    inputs: Mapping[InputName, ValueExpr]
    outputs: Mapping[OutputName, ValueSchema]
    acceptance_criteria: tuple[str, ...]
    retry: RetryPolicy
    timeout: TimeoutPolicy


@dataclass(frozen=True, slots=True)
class CommandNodeConfig:
    id: NodeId
    depends_on: tuple[NodeId, ...]
    when: ConditionExpr | None
    side_effect: SideEffectClass
    command: ProcessSpec
    inputs: Mapping[InputName, ValueExpr]
    outputs: Mapping[OutputName, ValueSchema]
    retry: RetryPolicy
    timeout: TimeoutPolicy


@dataclass(frozen=True, slots=True)
class VerifierNodeConfig:
    id: NodeId
    depends_on: tuple[NodeId, ...]
    when: ConditionExpr | None
    side_effect: SideEffectClass
    check: ProcessSpec
    inputs: Mapping[InputName, ValueExpr]
    outputs: Mapping[OutputName, ValueSchema]
    retry: RetryPolicy
    timeout: TimeoutPolicy
    settles_mutation: NodeId | None
    settlement_recovery: SettlementRecoveryPolicy | None


@dataclass(frozen=True, slots=True)
class GateNodeConfig:
    id: NodeId
    depends_on: tuple[NodeId, ...]
    when: ConditionExpr | None
    condition: ConditionExpr


@dataclass(frozen=True, slots=True)
class TerminalNodeConfig:
    id: NodeId
    depends_on: tuple[NodeId, ...]
    condition: ConditionExpr
    outcome: WorkflowOutcome


type NodeConfig = (
    AgentNodeConfig | CommandNodeConfig | VerifierNodeConfig | GateNodeConfig | TerminalNodeConfig
)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    id: WorkflowId
    revision_policy: CanonicalTreeRevisionPolicy | None
    nodes: tuple[NodeConfig, ...]


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    version: int
    workflow: WorkflowDefinition


def immutable_mapping[K, V](items: Mapping[K, V]) -> Mapping[K, V]:
    """Copy a validated mapping into an immutable view."""
    return MappingProxyType(dict(items))
