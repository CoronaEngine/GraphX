"""Closed execution, observation, and result wire schema v1."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from graphx.protocol.common_v1 import (
    DigestHexText,
    OpaqueIdText,
    SafeDiagnosticText,
    StrictWireModel,
    WireVersion,
)

type WireValue = bool | int | str | tuple["WireValue", ...] | dict[str, "WireValue"]
type ResultOutcomeV1 = Literal["completed", "execution_failed", "precondition_blocked", "cancelled"]
type TerminalExecutionDispositionV1 = Literal["not_started", "succeeded", "failed", "cancelled"]


class WorkspaceRevisionV1(StrictWireModel):
    policy_digest: DigestHexText = Field(alias="policyDigest")
    provider_version: OpaqueIdText = Field(alias="providerVersion")
    canonical_tree_digest: DigestHexText = Field(alias="canonicalTreeDigest")


class EvidenceReferenceV1(StrictWireModel):
    identity: OpaqueIdText
    digest: DigestHexText


class HostObservationEnvelopeV1(StrictWireModel):
    provider: OpaqueIdText
    provider_version: OpaqueIdText = Field(alias="providerVersion")
    execution_disposition: Literal[
        "not_started", "running", "succeeded", "failed", "cancelled", "unknown"
    ] = Field(alias="executionDisposition")
    terminal_evidence: EvidenceReferenceV1 = Field(alias="terminalEvidence")
    quiescence_evidence: EvidenceReferenceV1 = Field(alias="quiescenceEvidence")
    settled_output_revision: WorkspaceRevisionV1 = Field(alias="settledOutputRevision")
    observation_id: OpaqueIdText = Field(alias="observationId")
    observation_digest: DigestHexText = Field(alias="observationDigest")


class AgentCompletionPayloadV1(StrictWireModel):
    run_id: OpaqueIdText = Field(alias="runId")
    node_id: OpaqueIdText = Field(alias="nodeId")
    reservation_id: OpaqueIdText = Field(alias="reservationId")
    attempt_id: OpaqueIdText = Field(alias="attemptId")
    activation_id: OpaqueIdText = Field(alias="activationId")
    contract_hash: DigestHexText = Field(alias="contractHash")
    outputs: dict[str, WireValue] | None = None
    task_local_evidence: tuple[EvidenceReferenceV1, ...] = Field(
        default=(), alias="taskLocalEvidence"
    )
    diagnostics: SafeDiagnosticText | None = None


class CommandCheckResultV1(StrictWireModel):
    kind: Literal["command"]
    exit_code: int = Field(alias="exitCode", strict=True, ge=0, le=255)
    stdout_digest: DigestHexText = Field(alias="stdoutDigest")
    stderr_digest: DigestHexText = Field(alias="stderrDigest")
    stdout: str | None = Field(default=None, max_length=1_048_576)
    stderr: str | None = Field(default=None, max_length=1_048_576)


class VerificationEvidenceV1(StrictWireModel):
    run_id: OpaqueIdText = Field(alias="runId")
    node_id: OpaqueIdText = Field(alias="nodeId")
    attempt_id: OpaqueIdText = Field(alias="attemptId")
    execution_id: OpaqueIdText = Field(alias="executionId")
    operation_id: OpaqueIdText = Field(alias="operationId")
    check_id: OpaqueIdText = Field(alias="checkId")
    check_hash: DigestHexText = Field(alias="checkHash")
    evidence_subject_revision: WorkspaceRevisionV1 = Field(alias="evidenceSubjectRevision")
    status: Literal["passed", "failed"]
    check_result: CommandCheckResultV1 = Field(alias="checkResult")
    evidence_digest: DigestHexText = Field(alias="evidenceDigest")


class ProcessResultV1(StrictWireModel):
    exit_code: int = Field(alias="exitCode", strict=True, ge=0, le=255)
    stdout_digest: DigestHexText = Field(alias="stdoutDigest")
    stderr_digest: DigestHexText = Field(alias="stderrDigest")
    stdout: str | None = Field(default=None, max_length=1_048_576)
    stderr: str | None = Field(default=None, max_length=1_048_576)


class AgentNodeResultV1(StrictWireModel):
    wire_version: WireVersion = Field(alias="wireVersion")
    kind: Literal["agent"]
    outcome: ResultOutcomeV1
    agent_completion: AgentCompletionPayloadV1 = Field(alias="agentCompletion")
    host_observation: HostObservationEnvelopeV1 = Field(alias="hostObservation")
    thread_id: OpaqueIdText = Field(alias="threadId")
    task_binding_token: OpaqueIdText = Field(alias="taskBindingToken")
    failure_code: OpaqueIdText | None = Field(default=None, alias="failureCode")
    prerequisite_code: OpaqueIdText | None = Field(default=None, alias="prerequisiteCode")

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "AgentNodeResultV1":
        _validate_terminal_result(self.host_observation.execution_disposition)
        if self.outcome == "completed":
            if self.host_observation.execution_disposition != "succeeded":
                raise ValueError("completed result requires succeeded disposition")
            if self.agent_completion.outputs is None:
                raise ValueError("completed result requires outputs")
            if self.failure_code is not None or self.prerequisite_code is not None:
                raise ValueError("completed result forbids failure/prerequisite code")
        else:
            if self.agent_completion.outputs is not None:
                raise ValueError("noncompleted result forbids outputs")
            if self.outcome == "precondition_blocked" and self.prerequisite_code is None:
                raise ValueError("precondition_blocked requires prerequisiteCode")
            if self.outcome == "execution_failed" and self.failure_code is None:
                raise ValueError("execution_failed requires failureCode")
        _validate_result_size(self)
        return self


class MechanicalNodeResultV1(StrictWireModel):
    wire_version: WireVersion = Field(alias="wireVersion")
    kind: Literal["mechanical"]
    outcome: ResultOutcomeV1
    run_id: OpaqueIdText = Field(alias="runId")
    node_id: OpaqueIdText = Field(alias="nodeId")
    reservation_id: OpaqueIdText = Field(alias="reservationId")
    attempt_id: OpaqueIdText = Field(alias="attemptId")
    execution_id: OpaqueIdText = Field(alias="executionId")
    operation_id: OpaqueIdText = Field(alias="operationId")
    outputs: dict[str, WireValue] | None = None
    verification_evidence: VerificationEvidenceV1 | None = Field(
        default=None, alias="verificationEvidence"
    )
    host_observation: HostObservationEnvelopeV1 = Field(alias="hostObservation")
    diagnostics: SafeDiagnosticText | None = None
    failure_code: OpaqueIdText | None = Field(default=None, alias="failureCode")
    prerequisite_code: OpaqueIdText | None = Field(default=None, alias="prerequisiteCode")

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "MechanicalNodeResultV1":
        _validate_terminal_result(self.host_observation.execution_disposition)
        if self.outcome == "completed":
            if self.host_observation.execution_disposition != "succeeded":
                raise ValueError("completed result requires succeeded disposition")
            if self.outputs is None:
                raise ValueError("completed result requires outputs")
        elif self.outputs is not None or self.verification_evidence is not None:
            raise ValueError("noncompleted result forbids outputs and verificationEvidence")
        _validate_result_size(self)
        return self


def _validate_terminal_result(disposition: str) -> None:
    if disposition in {"running", "unknown"}:
        raise ValueError("NodeResult requires terminal execution disposition")


def _validate_result_size(result: AgentNodeResultV1 | MechanicalNodeResultV1) -> None:
    if len(result.model_dump_json(by_alias=True).encode("utf-8")) > 1_048_576:
        raise ValueError("NodeResult canonical payload must not exceed 1 MiB")


type NodeResultV1 = Annotated[
    AgentNodeResultV1 | MechanicalNodeResultV1, Field(discriminator="kind")
]
NodeResultV1Adapter: TypeAdapter[NodeResultV1] = TypeAdapter(NodeResultV1)


class DispatchReservationV1(StrictWireModel):
    reservation_id: OpaqueIdText = Field(alias="reservationId")
    run_id: OpaqueIdText = Field(alias="runId")
    node_id: OpaqueIdText = Field(alias="nodeId")
    reserved_attempt_number: int = Field(alias="reservedAttemptNumber", strict=True, ge=1)
    task_binding_token: OpaqueIdText = Field(alias="taskBindingToken")
    request_digest: DigestHexText = Field(alias="requestDigest")


class AgentNodeDispatchV1(StrictWireModel):
    kind: Literal["agent"]
    reservation: DispatchReservationV1
    task_create_operation_id: OpaqueIdText = Field(alias="taskCreateOperationId")
    bootstrap_spec_ref: DigestHexText = Field(alias="bootstrapSpecRef")


class MechanicalNodeDispatchV1(StrictWireModel):
    kind: Literal["mechanical"]
    reservation: DispatchReservationV1
    activation_spec_ref: DigestHexText = Field(alias="activationSpecRef")


class TaskContractV1(StrictWireModel):
    wire_version: WireVersion = Field(alias="wireVersion")
    run_id: OpaqueIdText = Field(alias="runId")
    node_id: OpaqueIdText = Field(alias="nodeId")
    attempt_id: OpaqueIdText = Field(alias="attemptId")
    activation_id: OpaqueIdText = Field(alias="activationId")
    task: str
    inputs: dict[str, WireValue]
    workspace_id: OpaqueIdText = Field(alias="workspaceId")
    input_revision: WorkspaceRevisionV1 = Field(alias="inputRevision")
    side_effect: Literal["none", "workspaceMutation"] = Field(alias="sideEffect")
    output_schema_digest: DigestHexText = Field(alias="outputSchemaDigest")
    acceptance_criteria: tuple[str, ...] = Field(alias="acceptanceCriteria", max_length=32)
    max_attempts: int = Field(alias="maxAttempts", strict=True, ge=1, le=10)
    timeout_seconds: int = Field(alias="timeoutSeconds", strict=True, ge=1, le=86_400)
    host_binding_digest: DigestHexText = Field(alias="hostBindingDigest")
    isolation_profile_digest: DigestHexText = Field(alias="isolationProfileDigest")


class MutationResolutionV1(StrictWireModel):
    resolution_id: OpaqueIdText = Field(alias="resolutionId")
    lease_id: OpaqueIdText = Field(alias="leaseId")
    decision: Literal[
        "accepted_current_workspace", "request_settlement_check", "attach_settlement_evidence"
    ]
    observed_revision: WorkspaceRevisionV1 = Field(alias="observedRevision")
    rationale: SafeDiagnosticText
