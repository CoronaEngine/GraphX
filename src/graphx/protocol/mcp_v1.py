"""Versioned closed MCP request and response DTOs."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from graphx.protocol.common_v1 import (
    DigestHexText,
    IdempotencyKeyText,
    OpaqueIdText,
    RequestIdText,
    StrictWireModel,
    WireVersion,
)
from graphx.protocol.execution_v1 import (
    HostObservationEnvelopeV1,
    NodeResultV1,
    VerificationEvidenceV1,
    WireValue,
    WorkspaceRevisionV1,
)
from graphx.protocol.workflow_v1 import WorkflowConfigV1


class McpOperationV1(StrEnum):
    VALIDATE_WORKFLOW = "graphx_validate_workflow"
    RECORD_HOST_OBSERVATION = "graphx_record_host_observation"
    START_RUN = "graphx_start_run"
    NEXT = "graphx_next"
    BIND_TASK = "graphx_bind_task"
    ACTIVATE_TASK = "graphx_activate_task"
    ACTIVATE_MECHANICAL = "graphx_activate_mechanical"
    SUBMIT_RESULT = "graphx_submit_result"
    FAIL_ATTEMPT = "graphx_fail_attempt"
    RECONCILE_EXTERNAL_OPERATION = "graphx_reconcile_external_operation"
    RESOLVE_MUTATION = "graphx_resolve_mutation"
    INSPECT_RUN = "graphx_inspect_run"
    RESUME_RUN = "graphx_resume_run"
    CANCEL_RUN = "graphx_cancel_run"


class ResolveMutationActionV1(StrEnum):
    ACCEPT_CURRENT_WORKSPACE = "acceptCurrentWorkspace"
    REQUEST_SETTLEMENT_CHECK = "requestSettlementCheck"
    ATTACH_SETTLEMENT_EVIDENCE = "attachSettlementEvidence"


class ErrorCodeV1(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    STALE = "stale"
    NOT_READY = "not_ready"
    RUN_NOT_RUNNABLE = "run_not_runnable"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    INTEGRITY_FAILURE = "integrity_failure"
    INTERNAL_FAILURE = "internal_failure"


class RetryDirectiveV1(StrEnum):
    DO_NOT_RETRY = "do_not_retry"
    RETRY_SAME_REQUEST = "retry_same_request"
    RECONCILE = "reconcile"
    USER_ACTION = "user_action"


type ErrorCodeText = Literal[
    "invalid_request",
    "unsupported_version",
    "unauthenticated",
    "forbidden",
    "not_found",
    "conflict",
    "stale",
    "not_ready",
    "run_not_runnable",
    "reconciliation_required",
    "capability_unavailable",
    "integrity_failure",
    "internal_failure",
]
type RetryDirectiveText = Literal["do_not_retry", "retry_same_request", "reconcile", "user_action"]


class CorrelatedRequestV1(StrictWireModel):
    wire_version: WireVersion = Field(alias="wireVersion")
    request_id: RequestIdText = Field(alias="requestId")


class MutatingRequestV1(CorrelatedRequestV1):
    idempotency_key: IdempotencyKeyText = Field(alias="idempotencyKey")


class RunMutationRequestV1(MutatingRequestV1):
    run_id: OpaqueIdText = Field(alias="runId")
    expected_run_version: int = Field(alias="expectedRunVersion", strict=True, ge=0)


class ValidateWorkflowRequestV1(MutatingRequestV1):
    workflow: WorkflowConfigV1


class RecordHostObservationRequestV1(MutatingRequestV1):
    observation_kind: Literal["runStartEnvironment", "workspaceRevision"] = Field(
        alias="observationKind"
    )
    observation: HostObservationEnvelopeV1
    validation_id: OpaqueIdText | None = Field(default=None, alias="validationId")
    run_id: OpaqueIdText | None = Field(default=None, alias="runId")
    expected_run_version: int | None = Field(default=None, alias="expectedRunVersion", ge=0)


class StartRunRequestV1(MutatingRequestV1):
    validation_id: OpaqueIdText = Field(alias="validationId")
    ir_digest: DigestHexText = Field(alias="irDigest")
    host_observation_id: OpaqueIdText = Field(alias="hostObservationId")


class NextRequestV1(RunMutationRequestV1):
    pass


class BindTaskRequestV1(RunMutationRequestV1):
    reservation_id: OpaqueIdText = Field(alias="reservationId")
    task_binding_token: OpaqueIdText = Field(alias="taskBindingToken")
    thread_id: OpaqueIdText = Field(alias="threadId")


class ActivateTaskRequestV1(RunMutationRequestV1):
    attempt_id: OpaqueIdText = Field(alias="attemptId")
    thread_id: OpaqueIdText = Field(alias="threadId")
    observed_input_revision: WorkspaceRevisionV1 = Field(alias="observedInputRevision")


class ActivateMechanicalRequestV1(RunMutationRequestV1):
    reservation_id: OpaqueIdText = Field(alias="reservationId")
    observed_input_revision: WorkspaceRevisionV1 = Field(alias="observedInputRevision")
    snapshot_identity: OpaqueIdText | None = Field(default=None, alias="snapshotIdentity")


class SubmitResultRequestV1(RunMutationRequestV1):
    result: NodeResultV1


class FailAttemptRequestV1(RunMutationRequestV1):
    attempt_id: OpaqueIdText = Field(alias="attemptId")
    operation_id: OpaqueIdText = Field(alias="operationId")
    observation: HostObservationEnvelopeV1


class ReconcileExternalOperationRequestV1(RunMutationRequestV1):
    operation_id: OpaqueIdText = Field(alias="operationId")
    reconcile_sequence: int = Field(alias="reconcileSequence", strict=True, ge=1, le=20)
    provider_query_identity: OpaqueIdText = Field(alias="providerQueryIdentity")
    observation: HostObservationEnvelopeV1


class ResolveMutationRequestV1(RunMutationRequestV1):
    action: ResolveMutationActionV1
    lease_id: OpaqueIdText = Field(alias="leaseId")
    workspace_observation_id: OpaqueIdText | None = Field(
        default=None, alias="workspaceObservationId"
    )
    evidence: VerificationEvidenceV1 | None = None


class InspectRunRequestV1(CorrelatedRequestV1):
    run_id: OpaqueIdText = Field(alias="runId")
    cursor: OpaqueIdText | None = None


class ResumeRunRequestV1(RunMutationRequestV1):
    pass


class CancelRunRequestV1(RunMutationRequestV1):
    pass


def _contains_unsafe_text(value: WireValue) -> bool:
    if isinstance(value, str):
        lowered = value.lower()
        return any(
            marker in lowered
            for marker in ("traceback", "/users/", "token=", "credential:", "rawcontract")
        )
    if isinstance(value, tuple):
        return any(_contains_unsafe_text(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_unsafe_text(item) for item in value.values())
    return False


class ErrorBodyV1(StrictWireModel):
    code: ErrorCodeText
    retry_directive: RetryDirectiveText = Field(alias="retryDirective")
    details: dict[str, WireValue]
    correlation_id: OpaqueIdText = Field(alias="correlationId")

    @model_validator(mode="after")
    def details_are_redacted(self) -> "ErrorBodyV1":
        if any(_contains_unsafe_text(value) for value in self.details.values()):
            raise ValueError("unsafe sensitive text in error details")
        return self


class ResponseEnvelopeV1(StrictWireModel):
    wire_version: WireVersion = Field(alias="wireVersion")
    request_id: RequestIdText = Field(alias="requestId")
    receipt_id: OpaqueIdText | None = Field(default=None, alias="receiptId")
    replayed: bool
    body: WireValue | ErrorBodyV1


class AgentNodeDispatchDecisionV1(StrictWireModel):
    kind: Literal["agentNodeDispatch"]
    reservation_id: OpaqueIdText = Field(alias="reservationId")
    binding_token: OpaqueIdText = Field(alias="bindingToken")
    task_create_operation_id: OpaqueIdText = Field(alias="taskCreateOperationId")
    bootstrap_spec_ref: DigestHexText = Field(alias="bootstrapSpecRef")


class MechanicalNodeDispatchDecisionV1(StrictWireModel):
    kind: Literal["mechanicalNodeDispatch"]
    reservation_id: OpaqueIdText = Field(alias="reservationId")
    activation_spec_ref: DigestHexText = Field(alias="activationSpecRef")


class InternalNodeAdvancedV1(StrictWireModel):
    kind: Literal["internalNodeAdvanced"]
    node_id: OpaqueIdText = Field(alias="nodeId")
    transition_digest: DigestHexText = Field(alias="transitionDigest")


class AwaitingActiveExecutionV1(StrictWireModel):
    kind: Literal["awaitingActiveExecution"]
    execution_identity: OpaqueIdText = Field(alias="executionIdentity")


class RunNotRunnableV1(StrictWireModel):
    kind: Literal["runNotRunnable"]
    run_status: Literal[
        "validated", "running", "succeeded", "failed", "blocked", "ambiguous", "cancelled"
    ] = Field(alias="runStatus")
    diagnostics: tuple[str, ...]


type NextDecisionV1 = Annotated[
    AgentNodeDispatchDecisionV1
    | MechanicalNodeDispatchDecisionV1
    | InternalNodeAdvancedV1
    | AwaitingActiveExecutionV1
    | RunNotRunnableV1,
    Field(discriminator="kind"),
]
NextDecisionV1Adapter: TypeAdapter[NextDecisionV1] = TypeAdapter(NextDecisionV1)


class InspectRunBodyV1(StrictWireModel):
    run_version: int = Field(alias="runVersion", strict=True, ge=0)
    ir_digest: DigestHexText = Field(alias="irDigest")
    status: Literal[
        "validated", "running", "succeeded", "failed", "blocked", "ambiguous", "cancelled"
    ]
    outcome: Literal["success", "failure"] | None
    node_summaries: tuple[dict[str, WireValue], ...] = Field(alias="nodeSummaries")
    operation_summaries: tuple[dict[str, WireValue], ...] = Field(alias="operationSummaries")
    lease_summaries: tuple[dict[str, WireValue], ...] = Field(alias="leaseSummaries")
    next_cursor: OpaqueIdText | None = Field(default=None, alias="nextCursor")
