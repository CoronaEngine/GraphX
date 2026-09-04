from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from graphx.core.config.models import NodeId, WorkflowOutcome
from graphx.core.ir.canonicalization import DigestHex
from graphx.core.runtime.models import (
    ActiveExecutionSlot,
    AgentAttempt,
    AgentAttemptId,
    AgentAttemptOwner,
    CancellationIntent,
    ContractHash,
    DispatchReservation,
    DispatchReservationId,
    ExecutionHandle,
    ExecutionInputRevision,
    ExternalOperation,
    ExternalOperationId,
    HostId,
    HostKind,
    InvalidRunAggregate,
    MutationLease,
    MutationLeaseId,
    NodeRuntimeState,
    NodeState,
    OperationKind,
    OperationState,
    RequestDigest,
    RunControllerBinding,
    RunHostBinding,
    RunId,
    RunState,
    RunStatus,
    TaskActivation,
    TaskActivationId,
    TaskBindingToken,
    ThreadId,
    WorkspaceId,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RUN_ID = RunId("run-1")
NODE_ID = NodeId("agent")
RESERVATION_ID = DispatchReservationId("reservation-1")
ATTEMPT_ID = AgentAttemptId("attempt-1")


def make_reservation() -> DispatchReservation:
    return DispatchReservation(
        reservation_id=RESERVATION_ID,
        run_id=RUN_ID,
        node_id=NODE_ID,
        reserved_attempt_number=1,
        task_binding_token=TaskBindingToken("token-1"),
        request_digest=RequestDigest("a" * 64),
    )


def make_bindings() -> tuple[RunControllerBinding, RunHostBinding]:
    return (
        RunControllerBinding("controller-1", "validation-1", 1),
        RunHostBinding(
            binding_id="host-binding-1",
            host_id=HostId("host-1"),
            host_kind=HostKind.CODEX,
            workspace_id=WorkspaceId("workspace-1"),
            canonical_workspace_identity=DigestHex("b" * 64),
            revision_policy_digest=DigestHex("c" * 64),
            isolation_profile_digest=DigestHex("d" * 64),
            dispatch_policy_id="dispatchPolicyV1",
        ),
    )


def make_run_state(
    *,
    status: RunStatus = RunStatus.RUNNING,
    outcome: WorkflowOutcome | None = None,
    node_state: NodeState = NodeState.PENDING,
    active_slot: ActiveExecutionSlot | None = None,
    operations: tuple[ExternalOperation, ...] = (),
    leases: tuple[MutationLease, ...] = (),
    attempts: tuple[AgentAttempt, ...] = (),
    handles: tuple[ExecutionHandle, ...] = (),
    activations: tuple[TaskActivation, ...] = (),
) -> RunState:
    controller, host = make_bindings()
    return RunState(
        run_id=RUN_ID,
        aggregate_version=1,
        ir_digest=DigestHex("e" * 64),
        status=status,
        outcome=outcome,
        controller_binding=controller,
        host_binding=host,
        nodes=(NodeRuntimeState(NODE_ID, node_state, 0, 0),),
        agent_attempts=attempts,
        execution_handles=handles,
        task_activations=activations,
        external_operations=operations,
        active_slot=active_slot,
        mutation_leases=leases,
    )


def test_state_01_runtime_records_are_frozen() -> None:
    reservation = make_reservation()

    with pytest.raises(FrozenInstanceError):
        reservation.node_id = NodeId("other")  # type: ignore[misc]


def test_state_01_node_and_run_state_enums_are_closed() -> None:
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


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (RunStatus.SUCCEEDED, WorkflowOutcome.SUCCESS),
        (RunStatus.FAILED, WorkflowOutcome.FAILURE),
        (RunStatus.FAILED, None),
        (RunStatus.VALIDATED, None),
        (RunStatus.RUNNING, None),
        (RunStatus.BLOCKED, None),
        (RunStatus.AMBIGUOUS, None),
        (RunStatus.CANCELLED, None),
    ],
)
def test_outcome_01_accepts_only_legal_status_outcome_combinations(
    status: RunStatus, outcome: WorkflowOutcome | None
) -> None:
    assert make_run_state(status=status, outcome=outcome).outcome is outcome


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (RunStatus.SUCCEEDED, None),
        (RunStatus.SUCCEEDED, WorkflowOutcome.FAILURE),
        (RunStatus.RUNNING, WorkflowOutcome.SUCCESS),
        (RunStatus.CANCELLED, WorkflowOutcome.FAILURE),
    ],
)
def test_outcome_01_rejects_illegal_status_outcome_combinations(
    status: RunStatus, outcome: WorkflowOutcome | None
) -> None:
    with pytest.raises(InvalidRunAggregate, match="outcome"):
        make_run_state(status=status, outcome=outcome)


def test_state_01_rejects_verifying_as_a_stable_node_state() -> None:
    with pytest.raises(InvalidRunAggregate, match="verifying"):
        make_run_state(node_state=NodeState.VERIFYING)


def test_outcome_01_terminal_run_rejects_active_slot_operation_or_lease() -> None:
    owner = AgentAttemptOwner(ATTEMPT_ID)
    slot = ActiveExecutionSlot(RUN_ID, owner)
    operation = ExternalOperation(
        operation_id=ExternalOperationId("operation-1"),
        run_id=RUN_ID,
        kind=OperationKind.CONTRACT_DELIVERY,
        parent=owner,
        state=OperationState.ACTIVE,
        request_digest=RequestDigest("f" * 64),
    )
    lease = MutationLease(
        lease_id=MutationLeaseId("lease-1"),
        run_id=RUN_ID,
        canonical_workspace_identity=DigestHex("b" * 64),
        owner=owner,
    )

    with pytest.raises(InvalidRunAggregate, match="active slot"):
        make_run_state(
            status=RunStatus.SUCCEEDED,
            outcome=WorkflowOutcome.SUCCESS,
            active_slot=slot,
        )
    with pytest.raises(InvalidRunAggregate, match="operation"):
        make_run_state(
            status=RunStatus.SUCCEEDED,
            outcome=WorkflowOutcome.SUCCESS,
            operations=(operation,),
        )
    with pytest.raises(InvalidRunAggregate, match="lease"):
        make_run_state(
            status=RunStatus.SUCCEEDED,
            outcome=WorkflowOutcome.SUCCESS,
            leases=(lease,),
        )


def test_task_01_agent_attempt_requires_exactly_one_execution_handle() -> None:
    attempt = AgentAttempt(ATTEMPT_ID, RESERVATION_ID, RUN_ID, NODE_ID, 1)

    with pytest.raises(InvalidRunAggregate, match="ExecutionHandle"):
        make_run_state(attempts=(attempt,))


def test_task_01_agent_attempt_rejects_multiple_activations() -> None:
    attempt = AgentAttempt(ATTEMPT_ID, RESERVATION_ID, RUN_ID, NODE_ID, 1)
    handle = ExecutionHandle(
        reservation_id=RESERVATION_ID,
        run_id=RUN_ID,
        node_id=NODE_ID,
        attempt_id=ATTEMPT_ID,
        task_binding_token=TaskBindingToken("token-1"),
        host_kind=HostKind.CODEX,
        thread_id=ThreadId("thread-1"),
        host_id=HostId("host-1"),
        workspace_id=WorkspaceId("workspace-1"),
        created_at=NOW,
    )
    activations = (
        TaskActivation(
            TaskActivationId("activation-1"),
            ATTEMPT_ID,
            ExecutionInputRevision("rev-1"),
            ContractHash("a" * 64),
            ExternalOperationId("delivery-1"),
            NOW,
        ),
        TaskActivation(
            TaskActivationId("activation-2"),
            ATTEMPT_ID,
            ExecutionInputRevision("rev-1"),
            ContractHash("a" * 64),
            ExternalOperationId("delivery-2"),
            NOW,
        ),
    )

    with pytest.raises(InvalidRunAggregate, match="TaskActivation"):
        make_run_state(attempts=(attempt,), handles=(handle,), activations=activations)


def test_state_01_cancellation_intent_is_an_immutable_record() -> None:
    intent = CancellationIntent("cancel-1", RUN_ID, "controller-1", NOW)

    assert intent.run_id == RUN_ID
