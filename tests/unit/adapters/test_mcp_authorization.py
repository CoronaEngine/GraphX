from __future__ import annotations

import pytest

from graphx.adapters.inbound.mcp.authorization import AuthorizationDecision, authorize
from graphx.core.runtime.models import (
    ControllerPrincipal,
    HostId,
    HostPrincipal,
    PrincipalId,
)
from graphx.protocol.mcp_v1 import McpOperationV1, ResolveMutationActionV1

CONTROLLER = ControllerPrincipal(PrincipalId("controller-1"), "capability")
HOST = HostPrincipal(PrincipalId("host-principal-1"), HostId("host-1"), "capability")


@pytest.mark.parametrize(
    "operation",
    [
        McpOperationV1.VALIDATE_WORKFLOW,
        McpOperationV1.START_RUN,
        McpOperationV1.NEXT,
        McpOperationV1.INSPECT_RUN,
        McpOperationV1.RESUME_RUN,
        McpOperationV1.CANCEL_RUN,
    ],
)
def test_auth_01_controller_operations_are_closed(operation: McpOperationV1) -> None:
    """Controller 操作允许总控调用，并拒绝 Host 越权。"""
    assert authorize(CONTROLLER, operation) is AuthorizationDecision.ALLOWED
    assert authorize(HOST, operation) is AuthorizationDecision.FORBIDDEN


@pytest.mark.parametrize(
    "operation",
    [
        McpOperationV1.RECORD_HOST_OBSERVATION,
        McpOperationV1.BIND_TASK,
        McpOperationV1.ACTIVATE_TASK,
        McpOperationV1.ACTIVATE_MECHANICAL,
        McpOperationV1.SUBMIT_RESULT,
        McpOperationV1.FAIL_ATTEMPT,
        McpOperationV1.RECONCILE_EXTERNAL_OPERATION,
    ],
)
def test_auth_01_host_operations_are_closed(operation: McpOperationV1) -> None:
    """Host 操作允许宿主调用，并拒绝 Controller 越权。"""
    assert authorize(HOST, operation) is AuthorizationDecision.ALLOWED
    assert authorize(CONTROLLER, operation) is AuthorizationDecision.FORBIDDEN


def test_auth_01_resolve_mutation_authority_depends_on_action() -> None:
    """Mutation 处置按具体动作校验调用者权限。"""
    assert (
        authorize(
            CONTROLLER,
            McpOperationV1.RESOLVE_MUTATION,
            ResolveMutationActionV1.ACCEPT_CURRENT_WORKSPACE,
        )
        is AuthorizationDecision.ALLOWED
    )
    assert (
        authorize(
            HOST,
            McpOperationV1.RESOLVE_MUTATION,
            ResolveMutationActionV1.REQUEST_SETTLEMENT_CHECK,
        )
        is AuthorizationDecision.ALLOWED
    )
    assert (
        authorize(
            CONTROLLER,
            McpOperationV1.RESOLVE_MUTATION,
            ResolveMutationActionV1.ATTACH_SETTLEMENT_EVIDENCE,
        )
        is AuthorizationDecision.FORBIDDEN
    )
