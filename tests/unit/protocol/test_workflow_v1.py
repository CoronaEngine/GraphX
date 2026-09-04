from __future__ import annotations

from collections.abc import Callable
from typing import TypeGuard

import pytest
from pydantic import ValidationError

from graphx.protocol.workflow_v1 import (
    ConditionExprV1Adapter,
    NodeV1Adapter,
    ValueSchemaV1Adapter,
    WorkflowConfigV1,
)

type JsonObject = dict[str, object]


def is_json_object(value: object) -> TypeGuard[JsonObject]:
    return isinstance(value, dict)


def is_object_tuple(value: object) -> TypeGuard[tuple[object, ...]]:
    return isinstance(value, tuple)


def valid_condition() -> JsonObject:
    return {"eq": ({"literal": True}, {"literal": True})}


def valid_revision_policy() -> JsonObject:
    return {
        "kind": "canonicalTreeV1",
        "authoritativeRoots": (".",),
        "excludedRoots": (".git", "build"),
        "includeUntracked": True,
    }


def valid_agent_node(node_id: str = "agent") -> JsonObject:
    return {
        "id": node_id,
        "type": "agent",
        "sideEffect": "none",
        "task": "Perform the declared work",
        "outputs": {},
    }


def valid_command_node(node_id: str = "command") -> JsonObject:
    return {
        "id": node_id,
        "type": "command",
        "sideEffect": "none",
        "command": {"kind": "command", "argv": ("python", "-V")},
        "outputs": {},
    }


def valid_verifier_node(node_id: str = "verify") -> JsonObject:
    return {
        "id": node_id,
        "type": "verifier",
        "sideEffect": "none",
        "check": {"kind": "command", "argv": ("pytest",)},
        "outputs": {"evidence": {"kind": "verificationEvidence"}},
    }


def valid_gate_node(node_id: str = "gate") -> JsonObject:
    return {"id": node_id, "type": "gate", "condition": valid_condition()}


def valid_terminal_node(node_id: str = "done") -> JsonObject:
    return {
        "id": node_id,
        "type": "terminal",
        "condition": valid_condition(),
        "outcome": "success",
    }


def valid_config(*nodes: JsonObject) -> JsonObject:
    selected_nodes = nodes or (valid_agent_node(), valid_terminal_node())
    return {
        "version": 1,
        "workflow": {
            "id": "workflow",
            "revisionPolicy": valid_revision_policy(),
            "nodes": selected_nodes,
        },
    }


def with_item(value: JsonObject, key: str, item: object) -> JsonObject:
    return {**value, key: item}


def replace_workflow(config: JsonObject, **changes: object) -> JsonObject:
    workflow = config["workflow"]
    assert is_json_object(workflow)
    return {**config, "workflow": {**workflow, **changes}}


def replace_node(config: JsonObject, index: int, node: JsonObject) -> JsonObject:
    workflow = config["workflow"]
    assert is_json_object(workflow)
    nodes = workflow["nodes"]
    assert is_object_tuple(nodes)
    changed = (*nodes[:index], node, *nodes[index + 1 :])
    return replace_workflow(config, nodes=changed)


def test_plan_4_4_accepts_all_five_closed_node_variants() -> None:
    config = valid_config(
        valid_agent_node(),
        valid_command_node(),
        valid_verifier_node(),
        valid_gate_node(),
        valid_terminal_node(),
    )

    parsed = WorkflowConfigV1.model_validate(config)

    assert tuple(node.type for node in parsed.workflow.nodes) == (
        "agent",
        "command",
        "verifier",
        "gate",
        "terminal",
    )


@pytest.mark.parametrize(
    ("factory", "forbidden_field"),
    [
        (valid_agent_node, "condition"),
        (valid_command_node, "task"),
        (valid_verifier_node, "outcome"),
        (valid_gate_node, "sideEffect"),
        (valid_terminal_node, "when"),
    ],
)
def test_plan_4_4_rejects_node_specific_forbidden_fields(
    factory: Callable[[], JsonObject], forbidden_field: str
) -> None:
    node = with_item(factory(), forbidden_field, True)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        NodeV1Adapter.validate_python(node)


def test_plan_4_4_external_workflow_requires_revision_policy() -> None:
    config = valid_config()
    workflow = config["workflow"]
    assert is_json_object(workflow)
    workflow = {key: value for key, value in workflow.items() if key != "revisionPolicy"}

    with pytest.raises(ValidationError, match="revisionPolicy"):
        WorkflowConfigV1.model_validate({**config, "workflow": workflow})


def test_plan_4_4_internal_workflow_may_omit_revision_policy() -> None:
    config = valid_config(valid_terminal_node())
    workflow = config["workflow"]
    assert is_json_object(workflow)
    workflow = {key: value for key, value in workflow.items() if key != "revisionPolicy"}

    assert WorkflowConfigV1.model_validate({**config, "workflow": workflow}).workflow.id == (
        "workflow"
    )


@pytest.mark.parametrize(
    "node",
    [
        with_item(valid_verifier_node(), "settlesMutation", "mutation"),
        with_item(valid_verifier_node(), "settlementRecovery", {"maxAttempts": 2}),
    ],
)
def test_plan_5_1_settlement_fields_must_appear_together(node: JsonObject) -> None:
    with pytest.raises(ValidationError, match=r"settlesMutation.*settlementRecovery"):
        NodeV1Adapter.validate_python(node)


def test_plan_4_4_accepts_workflow_node_limit_and_rejects_one_more() -> None:
    nodes = tuple(valid_agent_node(f"n{index}") for index in range(1024))
    assert len(WorkflowConfigV1.model_validate(valid_config(*nodes)).workflow.nodes) == 1024

    with pytest.raises(ValidationError):
        WorkflowConfigV1.model_validate(valid_config(*nodes, valid_agent_node("overflow")))


@pytest.mark.parametrize("node_id", ["Upper", "has_underscore", "-leading", "a" * 65])
def test_plan_4_4_rejects_invalid_node_ids(node_id: str) -> None:
    with pytest.raises(ValidationError):
        NodeV1Adapter.validate_python(valid_agent_node(node_id))


@pytest.mark.parametrize("maximum", [0, 1, 1_048_576])
def test_plan_4_5_accepts_bounded_string_schema(maximum: int) -> None:
    schema = ValueSchemaV1Adapter.validate_python({"kind": "string", "maxLength": maximum})
    assert schema.kind == "string"


@pytest.mark.parametrize(
    "schema",
    [
        {"kind": "float"},
        {"kind": "string", "maxLength": 1_048_577},
        {"kind": "array", "items": {"kind": "boolean"}, "maxItems": 10_001},
        {
            "kind": "object",
            "properties": {},
            "required": (),
            "additionalProperties": True,
        },
    ],
)
def test_plan_4_5_rejects_value_schema_outside_closed_bounds(schema: JsonObject) -> None:
    with pytest.raises(ValidationError):
        ValueSchemaV1Adapter.validate_python(schema)


def nested_array_schema(depth: int) -> JsonObject:
    schema: JsonObject = {"kind": "boolean"}
    for _ in range(depth - 1):
        schema = {"kind": "array", "items": schema, "maxItems": 1}
    return schema


def test_plan_4_5_enforces_value_schema_depth_16() -> None:
    assert ValueSchemaV1Adapter.validate_python(nested_array_schema(16)).kind == "array"
    with pytest.raises(ValidationError, match="depth"):
        ValueSchemaV1Adapter.validate_python(nested_array_schema(17))


def test_plan_4_5_enforces_object_property_limit_and_required_subset() -> None:
    properties = {f"p{index}": {"kind": "boolean"} for index in range(128)}
    valid = {
        "kind": "object",
        "properties": properties,
        "required": tuple(properties),
        "additionalProperties": False,
    }
    assert ValueSchemaV1Adapter.validate_python(valid).kind == "object"

    with pytest.raises(ValidationError, match="128"):
        ValueSchemaV1Adapter.validate_python(
            {**valid, "properties": {**properties, "overflow": {"kind": "boolean"}}}
        )
    with pytest.raises(ValidationError, match="required"):
        ValueSchemaV1Adapter.validate_python({**valid, "required": ("missing",)})


def test_plan_4_5_command_and_verifier_output_kinds_are_contextual() -> None:
    valid_command = with_item(
        valid_command_node(), "outputs", {"result": {"kind": "processResult"}}
    )
    assert NodeV1Adapter.validate_python(valid_command).type == "command"

    with pytest.raises(ValidationError, match="processResult"):
        NodeV1Adapter.validate_python(
            with_item(valid_agent_node(), "outputs", {"result": {"kind": "processResult"}})
        )
    with pytest.raises(ValidationError):
        NodeV1Adapter.validate_python(with_item(valid_verifier_node(), "outputs", {}))


@pytest.mark.parametrize("operator", ["eq", "ne", "lt", "le", "gt", "ge"])
def test_plan_4_5_accepts_all_binary_condition_operators(operator: str) -> None:
    condition = {operator: ({"literal": 1}, {"literal": 2})}
    assert ConditionExprV1Adapter.validate_python(condition).operator == operator


def test_plan_4_5_accepts_not_all_and_any_and_rejects_open_conditions() -> None:
    condition = valid_condition()
    assert ConditionExprV1Adapter.validate_python({"not": condition}).operator == "not"
    assert ConditionExprV1Adapter.validate_python({"all": (condition,)}).operator == "all"
    assert ConditionExprV1Adapter.validate_python({"any": (condition,)}).operator == "any"

    with pytest.raises(ValidationError):
        ConditionExprV1Adapter.validate_python({"all": ()})
    with pytest.raises(ValidationError):
        ConditionExprV1Adapter.validate_python({"all": (condition,) * 65})
    with pytest.raises(ValidationError):
        ConditionExprV1Adapter.validate_python(
            {"eq": ({"literal": 1}, {"literal": 1}), "not": condition}
        )


@pytest.mark.parametrize(
    "process",
    [
        {"kind": "command", "argv": ()},
        {"kind": "command", "argv": ("",)},
        {"kind": "command", "argv": ("x",) * 257},
        {"kind": "command", "argv": ("x" * 65_537,)},
        {"kind": "command", "argv": ("x",), "successExitCodes": ()},
        {"kind": "command", "argv": ("x",), "successExitCodes": (0, 0)},
        {"kind": "command", "argv": ("x",), "successExitCodes": (256,)},
        {"kind": "command", "argv": ("x",), "cwd": "../outside"},
        {"kind": "command", "argv": ("x",), "env": {"TOKEN": "secret"}},
    ],
)
def test_plan_4_4_rejects_invalid_process_specs(process: JsonObject) -> None:
    with pytest.raises(ValidationError):
        NodeV1Adapter.validate_python(with_item(valid_command_node(), "command", process))


@pytest.mark.parametrize(
    "path",
    ["/absolute", "a//b", "a/./b", "a/../b", "a\\b", "contains\x00nul", "e\u0301"],
)
def test_plan_4_7_rejects_noncanonical_revision_paths(path: str) -> None:
    policy = with_item(valid_revision_policy(), "authoritativeRoots", (path,))
    config = replace_workflow(valid_config(), revisionPolicy=policy)

    with pytest.raises(ValidationError):
        WorkflowConfigV1.model_validate(config)


def test_plan_4_7_rejects_overlapping_and_outside_excluded_roots() -> None:
    overlap = with_item(valid_revision_policy(), "authoritativeRoots", ("src", "src/lib"))
    outside = {
        **valid_revision_policy(),
        "authoritativeRoots": ("src",),
        "excludedRoots": ("outside",),
    }

    with pytest.raises(ValidationError, match="overlap"):
        WorkflowConfigV1.model_validate(replace_workflow(valid_config(), revisionPolicy=overlap))
    with pytest.raises(ValidationError, match="excluded"):
        WorkflowConfigV1.model_validate(replace_workflow(valid_config(), revisionPolicy=outside))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retry", {"maxAttempts": 0}),
        ("retry", {"maxAttempts": 11}),
        ("timeout", {"seconds": 0}),
        ("timeout", {"seconds": 86_401}),
        ("acceptanceCriteria", ("x",) * 33),
        ("acceptanceCriteria", ("x" * 4097,)),
        ("task", ""),
        ("task", "x" * 32_769),
    ],
)
def test_plan_4_4_rejects_agent_policy_and_text_bounds(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        NodeV1Adapter.validate_python(with_item(valid_agent_node(), field, value))
