"""Explicit mapping from validated wire DTOs to frozen Config-domain models."""

from typing import assert_never

from graphx.core.config.models import (
    AgentNodeConfig,
    AllCondition,
    AnyCondition,
    ArrayValueSchema,
    BinaryCondition,
    BooleanValueSchema,
    CanonicalTreeRevisionPolicy,
    CommandNodeConfig,
    ConditionExpr,
    FieldName,
    FromValueExpr,
    GateNodeConfig,
    InputName,
    IntegerValueSchema,
    LiteralValueExpr,
    NodeConfig,
    NodeId,
    NotCondition,
    ObjectValueSchema,
    OutputName,
    ProcessResultValueSchema,
    ProcessSpec,
    RetryPolicy,
    SettlementRecoveryPolicy,
    SideEffectClass,
    StringValueSchema,
    TerminalNodeConfig,
    TimeoutPolicy,
    ValueExpr,
    ValueSchema,
    VerificationEvidenceValueSchema,
    VerifierNodeConfig,
    WorkflowConfig,
    WorkflowDefinition,
    WorkflowId,
    WorkflowOutcome,
    immutable_mapping,
)
from graphx.protocol.workflow_v1 import (
    AgentNodeV1,
    AllConditionV1,
    AnyConditionV1,
    ArrayValueSchemaV1,
    BooleanValueSchemaV1,
    CommandNodeV1,
    ConditionExprV1,
    EqConditionV1,
    FromValueExprV1,
    GateNodeV1,
    GeConditionV1,
    GtConditionV1,
    IntegerValueSchemaV1,
    LeConditionV1,
    LiteralValueExprV1,
    LtConditionV1,
    NeConditionV1,
    NodeV1,
    NotConditionV1,
    ObjectValueSchemaV1,
    ProcessResultValueSchemaV1,
    ProcessSpecV1,
    StringValueSchemaV1,
    TerminalNodeV1,
    ValueExprV1,
    ValueSchemaV1,
    VerificationEvidenceValueSchemaV1,
    VerifierNodeV1,
    WorkflowConfigV1,
)


def _map_value_schema(value: ValueSchemaV1) -> ValueSchema:
    match value:
        case BooleanValueSchemaV1():
            return BooleanValueSchema()
        case IntegerValueSchemaV1():
            return IntegerValueSchema()
        case StringValueSchemaV1(max_length=maximum):
            return StringValueSchema(maximum)
        case ArrayValueSchemaV1(items=items, max_items=maximum):
            return ArrayValueSchema(_map_value_schema(items), maximum)
        case ObjectValueSchemaV1(properties=properties, required=required):
            mapped = {FieldName(key): _map_value_schema(item) for key, item in properties.items()}
            return ObjectValueSchema(
                immutable_mapping(mapped), tuple(FieldName(name) for name in required)
            )
        case ProcessResultValueSchemaV1():
            return ProcessResultValueSchema()
        case VerificationEvidenceValueSchemaV1():
            return VerificationEvidenceValueSchema()
    assert_never(value)


def _map_value_expr(value: ValueExprV1) -> ValueExpr:
    match value:
        case FromValueExprV1(from_path=path):
            return FromValueExpr(path)
        case LiteralValueExprV1(literal=literal):
            return LiteralValueExpr(literal)
    assert_never(value)


def _map_condition(value: ConditionExprV1) -> ConditionExpr:
    match value:
        case EqConditionV1(operands=(left, right)):
            return BinaryCondition("eq", _map_value_expr(left), _map_value_expr(right))
        case NeConditionV1(operands=(left, right)):
            return BinaryCondition("ne", _map_value_expr(left), _map_value_expr(right))
        case LtConditionV1(operands=(left, right)):
            return BinaryCondition("lt", _map_value_expr(left), _map_value_expr(right))
        case LeConditionV1(operands=(left, right)):
            return BinaryCondition("le", _map_value_expr(left), _map_value_expr(right))
        case GtConditionV1(operands=(left, right)):
            return BinaryCondition("gt", _map_value_expr(left), _map_value_expr(right))
        case GeConditionV1(operands=(left, right)):
            return BinaryCondition("ge", _map_value_expr(left), _map_value_expr(right))
        case NotConditionV1(operand=operand):
            return NotCondition(_map_condition(operand))
        case AllConditionV1(operands=operands):
            return AllCondition(tuple(_map_condition(item) for item in operands))
        case AnyConditionV1(operands=operands):
            return AnyCondition(tuple(_map_condition(item) for item in operands))
    assert_never(value)


def _map_process(value: ProcessSpecV1) -> ProcessSpec:
    return ProcessSpec(value.argv, value.cwd, value.success_exit_codes)


def _map_inputs(values: dict[str, ValueExprV1]) -> dict[InputName, ValueExpr]:
    return {InputName(name): _map_value_expr(value) for name, value in values.items()}


def _map_outputs(values: dict[str, ValueSchemaV1]) -> dict[OutputName, ValueSchema]:
    return {OutputName(name): _map_value_schema(value) for name, value in values.items()}


def _map_node(value: NodeV1) -> NodeConfig:
    node_id = NodeId(value.id)
    depends_on = tuple(NodeId(item) for item in value.depends_on)
    match value:
        case AgentNodeV1():
            return AgentNodeConfig(
                id=node_id,
                depends_on=depends_on,
                when=None if value.when is None else _map_condition(value.when),
                side_effect=SideEffectClass(value.side_effect),
                task=value.task,
                inputs=immutable_mapping(_map_inputs(value.inputs)),
                outputs=immutable_mapping(_map_outputs(value.outputs)),
                acceptance_criteria=value.acceptance_criteria,
                retry=RetryPolicy(value.retry.max_attempts),
                timeout=TimeoutPolicy(value.timeout.seconds),
            )
        case CommandNodeV1():
            return CommandNodeConfig(
                id=node_id,
                depends_on=depends_on,
                when=None if value.when is None else _map_condition(value.when),
                side_effect=SideEffectClass(value.side_effect),
                command=_map_process(value.command),
                inputs=immutable_mapping(_map_inputs(value.inputs)),
                outputs=immutable_mapping(_map_outputs(value.outputs)),
                retry=RetryPolicy(value.retry.max_attempts),
                timeout=TimeoutPolicy(value.timeout.seconds),
            )
        case VerifierNodeV1():
            recovery = value.settlement_recovery
            return VerifierNodeConfig(
                id=node_id,
                depends_on=depends_on,
                when=None if value.when is None else _map_condition(value.when),
                side_effect=SideEffectClass(value.side_effect),
                check=_map_process(value.check),
                inputs=immutable_mapping(_map_inputs(value.inputs)),
                outputs=immutable_mapping(_map_outputs(value.outputs)),
                retry=RetryPolicy(value.retry.max_attempts),
                timeout=TimeoutPolicy(value.timeout.seconds),
                settles_mutation=(
                    None if value.settles_mutation is None else NodeId(value.settles_mutation)
                ),
                settlement_recovery=(
                    None if recovery is None else SettlementRecoveryPolicy(recovery.max_attempts)
                ),
            )
        case GateNodeV1():
            return GateNodeConfig(
                id=node_id,
                depends_on=depends_on,
                when=None if value.when is None else _map_condition(value.when),
                condition=_map_condition(value.condition),
            )
        case TerminalNodeV1():
            return TerminalNodeConfig(
                id=node_id,
                depends_on=depends_on,
                condition=_map_condition(value.condition),
                outcome=WorkflowOutcome(value.outcome),
            )
    assert_never(value)


def map_workflow_config(dto: WorkflowConfigV1) -> WorkflowConfig:
    """Copy a validated wire Config into immutable domain objects."""
    policy = dto.workflow.revision_policy
    mapped_policy = (
        None
        if policy is None
        else CanonicalTreeRevisionPolicy(
            policy.authoritative_roots,
            policy.excluded_roots,
            policy.include_untracked,
        )
    )
    return WorkflowConfig(
        version=1,
        workflow=WorkflowDefinition(
            id=WorkflowId(dto.workflow.id),
            revision_policy=mapped_policy,
            nodes=tuple(_map_node(node) for node in dto.workflow.nodes),
        ),
    )
