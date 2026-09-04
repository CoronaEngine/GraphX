"""Closed Workflow Config v1 wire schema."""

import unicodedata
from typing import Annotated, ClassVar, Literal

from pydantic import AfterValidator, Field, TypeAdapter, field_validator, model_validator

from graphx.protocol.common_v1 import StrictWireModel, WireVersion

IDENTIFIER_PATTERN = r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"
MAX_STRING_BYTES = 1_048_576
MIN_SIGNED_64 = -(2**63)
MAX_SIGNED_64 = 2**63 - 1


def _validate_nfc_text(value: str, *, label: str, maximum_bytes: int) -> str:
    if not value:
        raise ValueError(f"{label} must not be empty")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError(f"{label} must use NFC normalization")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ValueError(f"{label} must not exceed {maximum_bytes} UTF-8 bytes")
    return value


def _validate_identifier(value: str) -> str:
    return _validate_nfc_text(value, label="identifier", maximum_bytes=64)


def _validate_task(value: str) -> str:
    return _validate_nfc_text(value, label="task", maximum_bytes=32_768)


def _validate_acceptance_criterion(value: str) -> str:
    return _validate_nfc_text(value, label="acceptance criterion", maximum_bytes=4_096)


def _validate_literal_string(value: str) -> str:
    return _validate_nfc_text(value, label="literal string", maximum_bytes=MAX_STRING_BYTES)


IdentifierText = Annotated[
    str,
    Field(pattern=IDENTIFIER_PATTERN, min_length=1, max_length=64),
    AfterValidator(_validate_identifier),
]
WorkflowIdText = IdentifierText
NodeIdText = IdentifierText
InputNameText = IdentifierText
OutputNameText = IdentifierText
FieldNameText = IdentifierText
TaskText = Annotated[str, AfterValidator(_validate_task)]
AcceptanceCriterionText = Annotated[str, AfterValidator(_validate_acceptance_criterion)]
LiteralString = Annotated[str, AfterValidator(_validate_literal_string)]
SignedInt64 = Annotated[int, Field(strict=True, ge=MIN_SIGNED_64, le=MAX_SIGNED_64)]
BoundedCount128 = Annotated[int, Field(strict=True, ge=0, le=128)]
BoundedItems = Annotated[int, Field(strict=True, ge=0, le=10_000)]
BoundedStringLength = Annotated[int, Field(strict=True, ge=0, le=MAX_STRING_BYTES)]
RetryAttempts = Annotated[int, Field(strict=True, ge=1, le=10)]
RecoveryAttempts = Annotated[int, Field(strict=True, ge=1, le=5)]
TimeoutSeconds = Annotated[int, Field(strict=True, ge=1, le=86_400)]
ExitCode = Annotated[int, Field(strict=True, ge=0, le=255)]


class BooleanValueSchemaV1(StrictWireModel):
    kind: Literal["boolean"]


class IntegerValueSchemaV1(StrictWireModel):
    kind: Literal["integer"]


class StringValueSchemaV1(StrictWireModel):
    kind: Literal["string"]
    max_length: BoundedStringLength = Field(alias="maxLength")


class ArrayValueSchemaV1(StrictWireModel):
    kind: Literal["array"]
    items: "ValueSchemaV1"
    max_items: BoundedItems = Field(alias="maxItems")

    @model_validator(mode="after")
    def enforce_depth(self) -> "ArrayValueSchemaV1":
        if _value_schema_depth(self) > 16:
            raise ValueError("ValueSchema recursion depth must not exceed 16")
        return self


class ObjectValueSchemaV1(StrictWireModel):
    kind: Literal["object"]
    properties: dict[FieldNameText, "ValueSchemaV1"] = Field(max_length=128)
    required: tuple[FieldNameText, ...] = Field(max_length=128)
    additional_properties: Literal[False] = Field(alias="additionalProperties")

    @field_validator("required")
    @classmethod
    def required_names_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("required names must be unique")
        return value

    @model_validator(mode="after")
    def enforce_object_invariants(self) -> "ObjectValueSchemaV1":
        if not set(self.required) <= set(self.properties):
            raise ValueError("required names must exist in properties")
        if _value_schema_depth(self) > 16:
            raise ValueError("ValueSchema recursion depth must not exceed 16")
        return self


class ProcessResultValueSchemaV1(StrictWireModel):
    kind: Literal["processResult"]


class VerificationEvidenceValueSchemaV1(StrictWireModel):
    kind: Literal["verificationEvidence"]


type ValueSchemaV1 = Annotated[
    BooleanValueSchemaV1
    | IntegerValueSchemaV1
    | StringValueSchemaV1
    | ArrayValueSchemaV1
    | ObjectValueSchemaV1
    | ProcessResultValueSchemaV1
    | VerificationEvidenceValueSchemaV1,
    Field(discriminator="kind"),
]


def _value_schema_depth(value: ValueSchemaV1) -> int:
    if isinstance(value, ArrayValueSchemaV1):
        return 1 + _value_schema_depth(value.items)
    if isinstance(value, ObjectValueSchemaV1):
        return 1 + max((_value_schema_depth(item) for item in value.properties.values()), default=0)
    return 1


ArrayValueSchemaV1.model_rebuild()
ObjectValueSchemaV1.model_rebuild()
ValueSchemaV1Adapter: TypeAdapter[ValueSchemaV1] = TypeAdapter(ValueSchemaV1)


class FromValueExprV1(StrictWireModel):
    from_path: LiteralString = Field(alias="from")


class LiteralValueExprV1(StrictWireModel):
    literal: bool | SignedInt64 | LiteralString


type ValueExprV1 = FromValueExprV1 | LiteralValueExprV1
ValueExprV1Adapter: TypeAdapter[ValueExprV1] = TypeAdapter(ValueExprV1)


class _ConditionBase(StrictWireModel):
    operator: ClassVar[str]


class EqConditionV1(_ConditionBase):
    operator = "eq"
    operands: tuple[ValueExprV1, ValueExprV1] = Field(alias="eq", min_length=2, max_length=2)


class NeConditionV1(_ConditionBase):
    operator = "ne"
    operands: tuple[ValueExprV1, ValueExprV1] = Field(alias="ne", min_length=2, max_length=2)


class LtConditionV1(_ConditionBase):
    operator = "lt"
    operands: tuple[ValueExprV1, ValueExprV1] = Field(alias="lt", min_length=2, max_length=2)


class LeConditionV1(_ConditionBase):
    operator = "le"
    operands: tuple[ValueExprV1, ValueExprV1] = Field(alias="le", min_length=2, max_length=2)


class GtConditionV1(_ConditionBase):
    operator = "gt"
    operands: tuple[ValueExprV1, ValueExprV1] = Field(alias="gt", min_length=2, max_length=2)


class GeConditionV1(_ConditionBase):
    operator = "ge"
    operands: tuple[ValueExprV1, ValueExprV1] = Field(alias="ge", min_length=2, max_length=2)


class NotConditionV1(_ConditionBase):
    operator = "not"
    operand: "ConditionExprV1" = Field(alias="not")


class AllConditionV1(_ConditionBase):
    operator = "all"
    operands: tuple["ConditionExprV1", ...] = Field(alias="all", min_length=1, max_length=64)


class AnyConditionV1(_ConditionBase):
    operator = "any"
    operands: tuple["ConditionExprV1", ...] = Field(alias="any", min_length=1, max_length=64)


type ConditionExprV1 = (
    EqConditionV1
    | NeConditionV1
    | LtConditionV1
    | LeConditionV1
    | GtConditionV1
    | GeConditionV1
    | NotConditionV1
    | AllConditionV1
    | AnyConditionV1
)

NotConditionV1.model_rebuild()
AllConditionV1.model_rebuild()
AnyConditionV1.model_rebuild()
ConditionExprV1Adapter: TypeAdapter[ConditionExprV1] = TypeAdapter(ConditionExprV1)


def _validate_canonical_relative_path(value: str) -> str:
    _validate_nfc_text(value, label="workspace-relative path", maximum_bytes=4_096)
    if value == ".":
        return value
    if value.startswith("/") or "\\" in value:
        raise ValueError("workspace-relative path must be relative POSIX syntax")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("workspace-relative path contains a noncanonical segment")
    return value


CanonicalRelativePath = Annotated[str, AfterValidator(_validate_canonical_relative_path)]


class ProcessSpecV1(StrictWireModel):
    kind: Literal["command"]
    argv: tuple[LiteralString, ...] = Field(min_length=1, max_length=256)
    cwd: CanonicalRelativePath = "."
    success_exit_codes: tuple[ExitCode, ...] = Field(
        default=(0,), alias="successExitCodes", min_length=1, max_length=256
    )

    @field_validator("argv")
    @classmethod
    def argv_fits_total_byte_limit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if sum(len(item.encode("utf-8")) for item in value) > 65_536:
            raise ValueError("argv must not exceed 65536 UTF-8 bytes")
        return value

    @field_validator("success_exit_codes")
    @classmethod
    def success_codes_are_unique(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(value) != len(set(value)):
            raise ValueError("successExitCodes must be unique")
        return value


class RetryPolicyV1(StrictWireModel):
    max_attempts: RetryAttempts = Field(default=1, alias="maxAttempts")


class TimeoutPolicyV1(StrictWireModel):
    seconds: TimeoutSeconds = 3_600


class SettlementRecoveryPolicyV1(StrictWireModel):
    max_attempts: RecoveryAttempts = Field(alias="maxAttempts")


def _paths_overlap(left: str, right: str) -> bool:
    if left == "." or right == ".":
        return True
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _path_is_within(path: str, root: str) -> bool:
    return root == "." or path == root or path.startswith(f"{root}/")


class CanonicalTreeRevisionPolicyV1(StrictWireModel):
    kind: Literal["canonicalTreeV1"]
    authoritative_roots: tuple[CanonicalRelativePath, ...] = Field(
        alias="authoritativeRoots", min_length=1
    )
    excluded_roots: tuple[CanonicalRelativePath, ...] = Field(alias="excludedRoots")
    include_untracked: bool = Field(alias="includeUntracked")

    @model_validator(mode="after")
    def validate_root_relationships(self) -> "CanonicalTreeRevisionPolicyV1":
        if len(self.authoritative_roots) != len(set(self.authoritative_roots)):
            raise ValueError("authoritativeRoots must be unique")
        if len(self.excluded_roots) != len(set(self.excluded_roots)):
            raise ValueError("excludedRoots must be unique")
        for index, left in enumerate(self.authoritative_roots):
            if any(_paths_overlap(left, right) for right in self.authoritative_roots[index + 1 :]):
                raise ValueError("authoritativeRoots must not overlap")
        if any(
            not any(_path_is_within(excluded, root) for root in self.authoritative_roots)
            for excluded in self.excluded_roots
        ):
            raise ValueError("each excluded root must be within an authoritative root")
        return self


type SideEffectV1 = Literal["none", "workspaceMutation"]
type InputsV1 = dict[InputNameText, ValueExprV1]
type OutputsV1 = dict[OutputNameText, ValueSchemaV1]


def _unique_node_ids(value: tuple[str, ...]) -> tuple[str, ...]:
    if len(value) != len(set(value)):
        raise ValueError("dependsOn values must be unique")
    return value


DependsOn = Annotated[tuple[NodeIdText, ...], AfterValidator(_unique_node_ids)]


class AgentNodeV1(StrictWireModel):
    id: NodeIdText
    type: Literal["agent"]
    depends_on: DependsOn = Field(default=(), alias="dependsOn")
    when: ConditionExprV1 | None = None
    side_effect: SideEffectV1 = Field(alias="sideEffect")
    task: TaskText
    inputs: InputsV1 = Field(default_factory=dict)
    outputs: OutputsV1 = Field(max_length=128)
    acceptance_criteria: tuple[AcceptanceCriterionText, ...] = Field(
        default=(), alias="acceptanceCriteria", max_length=32
    )
    retry: RetryPolicyV1 = Field(default_factory=RetryPolicyV1)
    timeout: TimeoutPolicyV1 = Field(default_factory=TimeoutPolicyV1)

    @field_validator("outputs")
    @classmethod
    def outputs_exclude_host_constructed_kinds(cls, value: OutputsV1) -> OutputsV1:
        if any(
            isinstance(item, ProcessResultValueSchemaV1 | VerificationEvidenceValueSchemaV1)
            for item in value.values()
        ):
            raise ValueError("agent outputs cannot contain processResult or verificationEvidence")
        return value


class CommandNodeV1(StrictWireModel):
    id: NodeIdText
    type: Literal["command"]
    depends_on: DependsOn = Field(default=(), alias="dependsOn")
    when: ConditionExprV1 | None = None
    side_effect: SideEffectV1 = Field(alias="sideEffect")
    command: ProcessSpecV1
    inputs: InputsV1 = Field(default_factory=dict)
    outputs: OutputsV1 = Field(max_length=1)
    retry: RetryPolicyV1 = Field(default_factory=RetryPolicyV1)
    timeout: TimeoutPolicyV1 = Field(default_factory=TimeoutPolicyV1)

    @field_validator("outputs")
    @classmethod
    def outputs_are_empty_or_process_result(cls, value: OutputsV1) -> OutputsV1:
        if value and (
            len(value) != 1
            or not isinstance(next(iter(value.values())), ProcessResultValueSchemaV1)
        ):
            raise ValueError("command outputs must contain only one processResult")
        return value


class VerifierNodeV1(StrictWireModel):
    id: NodeIdText
    type: Literal["verifier"]
    depends_on: DependsOn = Field(default=(), alias="dependsOn")
    when: ConditionExprV1 | None = None
    side_effect: SideEffectV1 = Field(alias="sideEffect")
    check: ProcessSpecV1
    inputs: InputsV1 = Field(default_factory=dict)
    outputs: OutputsV1 = Field(min_length=1, max_length=1)
    retry: RetryPolicyV1 = Field(default_factory=RetryPolicyV1)
    timeout: TimeoutPolicyV1 = Field(default_factory=TimeoutPolicyV1)
    settles_mutation: NodeIdText | None = Field(default=None, alias="settlesMutation")
    settlement_recovery: SettlementRecoveryPolicyV1 | None = Field(
        default=None, alias="settlementRecovery"
    )

    @field_validator("outputs")
    @classmethod
    def output_is_verification_evidence(cls, value: OutputsV1) -> OutputsV1:
        if not isinstance(next(iter(value.values())), VerificationEvidenceValueSchemaV1):
            raise ValueError("verifier output must be verificationEvidence")
        return value

    @model_validator(mode="after")
    def settlement_fields_are_paired(self) -> "VerifierNodeV1":
        if (self.settles_mutation is None) != (self.settlement_recovery is None):
            raise ValueError("settlesMutation and settlementRecovery must appear together")
        return self


class GateNodeV1(StrictWireModel):
    id: NodeIdText
    type: Literal["gate"]
    depends_on: DependsOn = Field(default=(), alias="dependsOn")
    when: ConditionExprV1 | None = None
    condition: ConditionExprV1


class TerminalNodeV1(StrictWireModel):
    id: NodeIdText
    type: Literal["terminal"]
    depends_on: DependsOn = Field(default=(), alias="dependsOn")
    condition: ConditionExprV1
    outcome: Literal["success", "failure"]


type NodeV1 = Annotated[
    AgentNodeV1 | CommandNodeV1 | VerifierNodeV1 | GateNodeV1 | TerminalNodeV1,
    Field(discriminator="type"),
]
NodeV1Adapter: TypeAdapter[NodeV1] = TypeAdapter(NodeV1)


class WorkflowV1(StrictWireModel):
    id: WorkflowIdText
    revision_policy: CanonicalTreeRevisionPolicyV1 | None = Field(
        default=None, alias="revisionPolicy"
    )
    nodes: tuple[NodeV1, ...] = Field(max_length=1_024)

    @model_validator(mode="after")
    def external_nodes_require_revision_policy(self) -> "WorkflowV1":
        has_external_node = any(
            isinstance(node, AgentNodeV1 | CommandNodeV1 | VerifierNodeV1) for node in self.nodes
        )
        if has_external_node and self.revision_policy is None:
            raise ValueError("revisionPolicy is required when an external node exists")
        return self


class WorkflowConfigV1(StrictWireModel):
    version: WireVersion
    workflow: WorkflowV1
