"""Closed principal authorization matrix for GraphX MCP v1."""

from enum import StrEnum

from graphx.core.runtime.models import ControllerPrincipal, McpPrincipal
from graphx.protocol.mcp_v1 import McpOperationV1, ResolveMutationActionV1


class AuthorizationDecision(StrEnum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"


CONTROLLER_OPERATIONS = frozenset(
    {
        McpOperationV1.VALIDATE_WORKFLOW,
        McpOperationV1.START_RUN,
        McpOperationV1.NEXT,
        McpOperationV1.INSPECT_RUN,
        McpOperationV1.RESUME_RUN,
        McpOperationV1.CANCEL_RUN,
    }
)
HOST_OPERATIONS = frozenset(
    {
        McpOperationV1.RECORD_HOST_OBSERVATION,
        McpOperationV1.BIND_TASK,
        McpOperationV1.ACTIVATE_TASK,
        McpOperationV1.ACTIVATE_MECHANICAL,
        McpOperationV1.SUBMIT_RESULT,
        McpOperationV1.FAIL_ATTEMPT,
        McpOperationV1.RECONCILE_EXTERNAL_OPERATION,
    }
)


def authorize(
    principal: McpPrincipal,
    operation: McpOperationV1,
    action: ResolveMutationActionV1 | None = None,
) -> AuthorizationDecision:
    """Return the fixed §11.1 permission for a transport-authenticated principal."""
    if operation is McpOperationV1.RESOLVE_MUTATION:
        if isinstance(principal, ControllerPrincipal):
            allowed = action is ResolveMutationActionV1.ACCEPT_CURRENT_WORKSPACE
        else:
            allowed = action in {
                ResolveMutationActionV1.REQUEST_SETTLEMENT_CHECK,
                ResolveMutationActionV1.ATTACH_SETTLEMENT_EVIDENCE,
            }
        return AuthorizationDecision.ALLOWED if allowed else AuthorizationDecision.FORBIDDEN

    if isinstance(principal, ControllerPrincipal):
        allowed = operation in CONTROLLER_OPERATIONS
    else:
        allowed = operation in HOST_OPERATIONS
    return AuthorizationDecision.ALLOWED if allowed else AuthorizationDecision.FORBIDDEN
