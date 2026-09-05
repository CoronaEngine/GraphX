from __future__ import annotations

from graphx.adapters.host.main import main as host_main
from graphx.bootstrap import main as service_main
from graphx.core.ir.canonicalization import CANONICALIZATION_PROFILE_ID
from graphx.core.runtime.models import NodeState, RunStatus
from graphx.protocol.common_v1 import StrictWireModel
from graphx.protocol.execution_v1 import AgentNodeResultV1, HostObservationEnvelopeV1
from graphx.protocol.mcp_v1 import NextRequestV1, ResponseEnvelopeV1
from graphx.protocol.workflow_v1 import WorkflowConfigV1


def test_phase_1_public_surface_is_closed_and_importable() -> None:
    """Phase 1 公开入口可导入，状态集合符合约定。"""
    assert callable(service_main)
    assert callable(host_main)
    assert CANONICALIZATION_PROFILE_ID == "graphx-canonical-json-v1"
    assert {state.value for state in NodeState} == {
        "pending",
        "ready",
        "dispatching",
        "running",
        "verifying",
        "succeeded",
        "failed",
        "skipped",
        "blocked",
        "ambiguous",
        "cancelled",
    }
    assert {status.value for status in RunStatus} == {
        "validated",
        "running",
        "succeeded",
        "failed",
        "blocked",
        "ambiguous",
        "cancelled",
    }


def test_phase_1_public_wire_models_are_frozen_and_closed() -> None:
    """Phase 1 公开协议模型启用严格、冻结和未知字段拒绝。"""
    models: tuple[type[StrictWireModel], ...] = (
        WorkflowConfigV1,
        AgentNodeResultV1,
        HostObservationEnvelopeV1,
        NextRequestV1,
        ResponseEnvelopeV1,
    )

    for model in models:
        assert model.model_config.get("frozen") is True
        assert model.model_config.get("extra") == "forbid"
        assert model.model_config.get("strict") is True


def test_auth_01_public_request_schemas_do_not_expose_authority_fields() -> None:
    """公开请求 Schema 不暴露由服务决定的权限身份字段。"""
    schemas = (NextRequestV1.model_json_schema(), HostObservationEnvelopeV1.model_json_schema())

    for schema in schemas:
        properties = schema.get("properties")
        assert isinstance(properties, dict)
        assert "hostId" not in properties
        assert "principal" not in properties
        assert "principalId" not in properties
