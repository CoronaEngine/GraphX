from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from graphx.adapters.inbound.workflow.loader import (
    WorkflowDecodeError,
    WorkflowDecodeErrorCode,
    load_workflow_json,
)
from graphx.adapters.inbound.workflow.mapper import map_workflow_config
from graphx.core.config.models import AgentNodeConfig, WorkflowConfig
from graphx.protocol.workflow_v1 import WorkflowConfigV1

VALID_WORKFLOW = b"""{
  "version": 1,
  "workflow": {
    "id": "workflow",
    "revisionPolicy": {
      "kind": "canonicalTreeV1",
      "authoritativeRoots": ["."],
      "excludedRoots": [".git"],
      "includeUntracked": true
    },
    "nodes": [
      {
        "id": "agent",
        "type": "agent",
        "sideEffect": "none",
        "task": "Do work",
        "outputs": {"summary": {"kind": "string", "maxLength": 100}}
      }
    ]
  }
}"""


def test_ctrl_02_loads_json_arrays_into_strict_immutable_wire_types() -> None:
    """JSON 数组加载为严格协议模型中的不可变元组。"""
    dto = load_workflow_json(VALID_WORKFLOW)

    assert isinstance(dto, WorkflowConfigV1)
    assert isinstance(dto.workflow.nodes, tuple)
    assert dto.workflow.revision_policy is not None
    assert dto.workflow.revision_policy.authoritative_roots == (".",)


def test_ctrl_02_loader_rejects_duplicate_json_keys() -> None:
    """Workflow JSON 中重复的键被明确拒绝。"""
    raw = b'{"version":1,"version":1,"workflow":{"id":"workflow","nodes":[]}}'

    with pytest.raises(WorkflowDecodeError) as exc_info:
        load_workflow_json(raw)

    assert exc_info.value.code is WorkflowDecodeErrorCode.DUPLICATE_KEY


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"\xff", WorkflowDecodeErrorCode.INVALID_UTF8),
        (b"\xef\xbb\xbf{}", WorkflowDecodeErrorCode.BOM_FORBIDDEN),
        (b"{} {}", WorkflowDecodeErrorCode.TRAILING_CONTENT),
        (
            '{"version":1,"workflow":{"id":"e\u0301","nodes":[]}}'.encode(),
            WorkflowDecodeErrorCode.INVALID_SCHEMA,
        ),
        (
            b'{"version":2,"workflow":{"id":"workflow","nodes":[]}}',
            WorkflowDecodeErrorCode.INVALID_SCHEMA,
        ),
    ],
)
def test_ctrl_02_loader_rejects_invalid_boundary_payloads(
    payload: bytes, code: WorkflowDecodeErrorCode
) -> None:
    """非法编码、JSON 或 Schema 返回对应加载错误。"""
    with pytest.raises(WorkflowDecodeError) as exc_info:
        load_workflow_json(payload)

    assert exc_info.value.code is code


def test_ctrl_01_mapper_creates_a_distinct_frozen_domain_config() -> None:
    """协议模型映射为独立且冻结的领域配置。"""
    dto = load_workflow_json(VALID_WORKFLOW)

    config = map_workflow_config(dto)

    assert isinstance(config, WorkflowConfig)
    assert not isinstance(config, WorkflowConfigV1)
    assert isinstance(config.workflow.nodes[0], AgentNodeConfig)
    assert config.workflow.nodes[0].id == "agent"
    with pytest.raises(FrozenInstanceError):
        config.version = 2  # type: ignore[misc]


def test_ctrl_03_mapping_does_not_retain_mutable_wire_output_maps() -> None:
    """修改原始协议输出映射不会改变已生成的领域配置。"""
    dto = load_workflow_json(VALID_WORKFLOW)
    config = map_workflow_config(dto)
    agent = dto.workflow.nodes[0]
    assert agent.type == "agent"

    agent.outputs.clear()

    mapped_agent = config.workflow.nodes[0]
    assert isinstance(mapped_agent, AgentNodeConfig)
    assert tuple(mapped_agent.outputs) == ("summary",)
