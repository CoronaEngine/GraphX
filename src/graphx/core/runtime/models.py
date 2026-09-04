"""Immutable records composing the authoritative GraphX RunState aggregate."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, NewType

from graphx.core.config.models import NodeId, WorkflowOutcome
from graphx.core.ir.canonicalization import DigestHex

RunId = NewType("RunId", str)
DispatchReservationId = NewType("DispatchReservationId", str)
AgentAttemptId = NewType("AgentAttemptId", str)
MechanicalAttemptId = NewType("MechanicalAttemptId", str)
MechanicalExecutionId = NewType("MechanicalExecutionId", str)
TaskActivationId = NewType("TaskActivationId", str)
SettlementCheckExecutionId = NewType("SettlementCheckExecutionId", str)
ExternalOperationId = NewType("ExternalOperationId", str)
MutationLeaseId = NewType("MutationLeaseId", str)
SettledMutationRecordId = NewType("SettledMutationRecordId", str)
HostId = NewType("HostId", str)
WorkspaceId = NewType("WorkspaceId", str)
ThreadId = NewType("ThreadId", str)
TaskBindingToken = NewType("TaskBindingToken", str)
RequestDigest = NewType("RequestDigest", str)
ContractHash = NewType("ContractHash", str)
ExecutionInputRevision = NewType("ExecutionInputRevision", str)
EvidenceSubjectRevision = NewType("EvidenceSubjectRevision", str)
ObservationId = NewType("ObservationId", str)
EvidenceId = NewType("EvidenceId", str)
IdempotencyReceiptId = NewType("IdempotencyReceiptId", str)
PrincipalId = NewType("PrincipalId", str)


class NodeState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"


class RunStatus(StrEnum):
    VALIDATED = "validated"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"


class HostKind(StrEnum):
    CODEX = "codex"


class ResultOutcome(StrEnum):
    COMPLETED = "completed"
    EXECUTION_FAILED = "execution_failed"
    PRECONDITION_BLOCKED = "precondition_blocked"
    CANCELLED = "cancelled"


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class OperationKind(StrEnum):
    TASK_CREATE = "taskCreate"
    CONTRACT_DELIVERY = "contractDelivery"
    MECHANICAL_START = "mechanicalStart"
    SETTLEMENT_CHECK = "settlementCheck"


class OperationState(StrEnum):
    PREPARED = "prepared"
    UNKNOWN = "unknown"
    ACTIVE = "active"
    TERMINAL = "terminal"
    CONFLICTED = "conflicted"


class OperationTerminalDisposition(StrEnum):
    SUCCEEDED = "succeeded"
    NOT_CREATED = "not_created"
    NOT_STARTED = "not_started"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionDisposition(StrEnum):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class RetryDirective(StrEnum):
    DO_NOT_RETRY = "do_not_retry"
    RETRY_SAME_REQUEST = "retry_same_request"
    RECONCILE = "reconcile"
    USER_ACTION = "user_action"


class MutationResolutionDecision(StrEnum):
    ACCEPTED_CURRENT_WORKSPACE = "accepted_current_workspace"
    REQUEST_SETTLEMENT_CHECK = "request_settlement_check"
    ATTACH_SETTLEMENT_EVIDENCE = "attach_settlement_evidence"


class ConditionDecisionKind(StrEnum):
    SATISFIED = "satisfied"
    NOT_SATISFIED = "not_satisfied"


class OwnerKind(StrEnum):
    RESERVATION = "reservation"
    AGENT_ATTEMPT = "agent_attempt"
    MECHANICAL_ATTEMPT = "mechanical_attempt"
    SETTLED_MUTATION = "settled_mutation"
    SETTLEMENT_CHECK = "settlement_check"


@dataclass(frozen=True, slots=True)
class ReservationOwner:
    identity: DispatchReservationId
    kind: ClassVar[OwnerKind] = OwnerKind.RESERVATION


@dataclass(frozen=True, slots=True)
class AgentAttemptOwner:
    identity: AgentAttemptId
    kind: ClassVar[OwnerKind] = OwnerKind.AGENT_ATTEMPT


@dataclass(frozen=True, slots=True)
class MechanicalAttemptOwner:
    identity: MechanicalAttemptId
    kind: ClassVar[OwnerKind] = OwnerKind.MECHANICAL_ATTEMPT


@dataclass(frozen=True, slots=True)
class SettledMutationOwner:
    identity: SettledMutationRecordId
    kind: ClassVar[OwnerKind] = OwnerKind.SETTLED_MUTATION


@dataclass(frozen=True, slots=True)
class SettlementCheckOwner:
    identity: SettlementCheckExecutionId
    kind: ClassVar[OwnerKind] = OwnerKind.SETTLEMENT_CHECK


type StateOwner = (
    ReservationOwner
    | AgentAttemptOwner
    | MechanicalAttemptOwner
    | SettledMutationOwner
    | SettlementCheckOwner
)


@dataclass(frozen=True, slots=True)
class ControllerPrincipal:
    principal_id: PrincipalId
    authentication_method: str


@dataclass(frozen=True, slots=True)
class HostPrincipal:
    principal_id: PrincipalId
    host_id: HostId
    authentication_method: str


type McpPrincipal = ControllerPrincipal | HostPrincipal


@dataclass(frozen=True, slots=True)
class RunControllerBinding:
    controller_principal_id: str
    validation_id: str
    authorization_version: int


@dataclass(frozen=True, slots=True)
class HostCapabilities:
    idempotent_create_or_start: bool = False
    query_by_operation_id: bool = False
    query_by_binding_token: bool = False
    terminal_observation: bool = False
    descendant_quiescence: bool = False
    immutable_snapshot: bool = False


@dataclass(frozen=True, slots=True)
class RunHostBinding:
    binding_id: str
    host_id: HostId
    host_kind: HostKind
    workspace_id: WorkspaceId
    canonical_workspace_identity: DigestHex
    revision_policy_digest: DigestHex
    isolation_profile_digest: DigestHex
    dispatch_policy_id: str
    provider_version: str = "unknown"
    capabilities: HostCapabilities = HostCapabilities()


@dataclass(frozen=True, slots=True)
class CancellationIntent:
    intent_id: str
    run_id: RunId
    controller_principal_id: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class DispatchReservation:
    reservation_id: DispatchReservationId
    run_id: RunId
    node_id: NodeId
    reserved_attempt_number: int
    task_binding_token: TaskBindingToken
    request_digest: RequestDigest


@dataclass(frozen=True, slots=True)
class AgentAttempt:
    attempt_id: AgentAttemptId
    reservation_id: DispatchReservationId
    run_id: RunId
    node_id: NodeId
    attempt_number: int


@dataclass(frozen=True, slots=True)
class ExecutionHandle:
    reservation_id: DispatchReservationId
    run_id: RunId
    node_id: NodeId
    attempt_id: AgentAttemptId
    task_binding_token: TaskBindingToken
    host_kind: HostKind
    thread_id: ThreadId
    host_id: HostId
    workspace_id: WorkspaceId
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TaskActivation:
    activation_id: TaskActivationId
    attempt_id: AgentAttemptId
    input_revision: ExecutionInputRevision
    contract_hash: ContractHash
    delivery_operation_id: ExternalOperationId
    activated_at: datetime


@dataclass(frozen=True, slots=True)
class MechanicalAttempt:
    attempt_id: MechanicalAttemptId
    reservation_id: DispatchReservationId
    run_id: RunId
    node_id: NodeId
    attempt_number: int


@dataclass(frozen=True, slots=True)
class MechanicalExecutionHandle:
    reservation_id: DispatchReservationId
    attempt_id: MechanicalAttemptId
    execution_id: MechanicalExecutionId
    operation_id: ExternalOperationId
    host_id: HostId
    input_revision: ExecutionInputRevision
    activated_at: datetime


@dataclass(frozen=True, slots=True)
class SettlementCheckExecution:
    recovery_execution_id: SettlementCheckExecutionId
    lease_id: MutationLeaseId
    recovery_sequence: int
    operation_id: ExternalOperationId
    host_id: HostId
    input_revision: ExecutionInputRevision
    evidence_subject_revision: EvidenceSubjectRevision
    check_hash: DigestHex
    contract_hash: ContractHash
    activated_at: datetime


@dataclass(frozen=True, slots=True)
class ExternalOperation:
    operation_id: ExternalOperationId
    run_id: RunId
    kind: OperationKind
    parent: StateOwner
    state: OperationState
    request_digest: RequestDigest
    provider_handle: str | None = None
    terminal_disposition: OperationTerminalDisposition | None = None


@dataclass(frozen=True, slots=True)
class ExternalOperationObservation:
    observation_id: ObservationId
    operation_id: ExternalOperationId
    sequence: int
    state: OperationState
    evidence_digest: DigestHex


@dataclass(frozen=True, slots=True)
class WorkspaceRevision:
    policy_digest: DigestHex
    provider_version: str
    canonical_tree_digest: DigestHex


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    evidence_id: EvidenceId
    run_id: RunId
    node_id: NodeId
    execution_id: str
    check_id: str
    check_hash: DigestHex
    subject_revision: EvidenceSubjectRevision
    status: VerificationStatus
    evidence_digest: DigestHex


@dataclass(frozen=True, slots=True)
class ActiveExecutionSlot:
    run_id: RunId
    owner: StateOwner


@dataclass(frozen=True, slots=True)
class MutationLease:
    lease_id: MutationLeaseId
    run_id: RunId
    canonical_workspace_identity: DigestHex
    owner: StateOwner


@dataclass(frozen=True, slots=True)
class AcceptedWorkspaceBaseline:
    revision: WorkspaceRevision
    resolution_id: str


@dataclass(frozen=True, slots=True)
class SettledMutationRecord:
    record_id: SettledMutationRecordId
    node_id: NodeId
    settled_output_revision: WorkspaceRevision


@dataclass(frozen=True, slots=True)
class NodeRuntimeState:
    node_id: NodeId
    state: NodeState
    reservation_sequence: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class NodeOutput:
    node_id: NodeId
    output_name: str
    canonical_value_digest: DigestHex


@dataclass(frozen=True, slots=True)
class IdempotencyReceipt:
    receipt_id: IdempotencyReceiptId
    principal_id: PrincipalId
    operation: str
    idempotency_key: str
    request_digest: RequestDigest
    response_digest: DigestHex


@dataclass(frozen=True, slots=True)
class MutationResolution:
    resolution_id: str
    lease_id: MutationLeaseId
    decision: MutationResolutionDecision
    observed_revision: WorkspaceRevision
    rationale: str


@dataclass(frozen=True, slots=True)
class ConditionDecision:
    kind: ConditionDecisionKind
    condition_hash: DigestHex
    referenced_values_hash: DigestHex


class InvalidRunAggregate(ValueError):
    """The records do not form a legal stable RunState snapshot."""


@dataclass(frozen=True, slots=True)
class RunState:
    run_id: RunId
    aggregate_version: int
    ir_digest: DigestHex
    status: RunStatus
    outcome: WorkflowOutcome | None
    controller_binding: RunControllerBinding
    host_binding: RunHostBinding
    nodes: tuple[NodeRuntimeState, ...]
    reservations: tuple[DispatchReservation, ...] = ()
    agent_attempts: tuple[AgentAttempt, ...] = ()
    mechanical_attempts: tuple[MechanicalAttempt, ...] = ()
    execution_handles: tuple[ExecutionHandle, ...] = ()
    mechanical_execution_handles: tuple[MechanicalExecutionHandle, ...] = ()
    task_activations: tuple[TaskActivation, ...] = ()
    external_operations: tuple[ExternalOperation, ...] = ()
    external_operation_observations: tuple[ExternalOperationObservation, ...] = ()
    settlement_checks: tuple[SettlementCheckExecution, ...] = ()
    settled_mutations: tuple[SettledMutationRecord, ...] = ()
    node_outputs: tuple[NodeOutput, ...] = ()
    evidence_records: tuple[VerificationEvidence, ...] = ()
    accepted_workspace_baseline: AcceptedWorkspaceBaseline | None = None
    effective_workspace_baseline: WorkspaceRevision | None = None
    idempotency_receipts: tuple[IdempotencyReceipt, ...] = ()
    active_slot: ActiveExecutionSlot | None = None
    mutation_leases: tuple[MutationLease, ...] = ()
    cancellation_intent: CancellationIntent | None = None

    def __post_init__(self) -> None:
        validate_run_state_composition(self)


def validate_run_state_composition(state: RunState) -> None:
    """Reject impossible stable aggregate combinations without deciding transitions."""
    if state.aggregate_version < 0:
        raise InvalidRunAggregate("aggregate version must not be negative")
    if any(node.state is NodeState.VERIFYING for node in state.nodes):
        raise InvalidRunAggregate("verifying cannot be a stable node state")

    if state.status is RunStatus.SUCCEEDED:
        if state.outcome is not WorkflowOutcome.SUCCESS:
            raise InvalidRunAggregate("succeeded Run requires success outcome")
    elif state.status is RunStatus.FAILED:
        if state.outcome not in {None, WorkflowOutcome.FAILURE}:
            raise InvalidRunAggregate("failed Run has an illegal outcome")
    elif state.outcome is not None:
        raise InvalidRunAggregate("non-outcome Run status must not carry outcome")

    terminal = state.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
    if terminal and state.active_slot is not None:
        raise InvalidRunAggregate("terminal Run must not retain an active slot")
    if terminal and any(
        operation.state is not OperationState.TERMINAL for operation in state.external_operations
    ):
        raise InvalidRunAggregate("terminal Run must not retain an unresolved operation")
    if terminal and state.mutation_leases:
        raise InvalidRunAggregate("terminal Run must not retain a mutation lease")

    for attempt in state.agent_attempts:
        handles = tuple(
            handle for handle in state.execution_handles if handle.attempt_id == attempt.attempt_id
        )
        if len(handles) != 1:
            raise InvalidRunAggregate("each AgentAttempt requires exactly one ExecutionHandle")
        activations = tuple(
            activation
            for activation in state.task_activations
            if activation.attempt_id == attempt.attempt_id
        )
        if len(activations) > 1:
            raise InvalidRunAggregate("each AgentAttempt permits at most one TaskActivation")

    for attempt in state.mechanical_attempts:
        handles = tuple(
            handle
            for handle in state.mechanical_execution_handles
            if handle.attempt_id == attempt.attempt_id
        )
        if len(handles) != 1:
            raise InvalidRunAggregate(
                "each MechanicalAttempt requires exactly one MechanicalExecutionHandle"
            )
