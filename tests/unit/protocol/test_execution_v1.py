from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphx.protocol.execution_v1 import (
    AgentCompletionPayloadV1,
    HostObservationEnvelopeV1,
    NodeResultV1Adapter,
    VerificationEvidenceV1,
)

type JsonObject = dict[str, object]


def revision() -> JsonObject:
    return {
        "policyDigest": "a" * 64,
        "providerVersion": "tree-v1",
        "canonicalTreeDigest": "b" * 64,
    }


def host_observation(disposition: str = "succeeded") -> JsonObject:
    return {
        "provider": "codex",
        "providerVersion": "1",
        "executionDisposition": disposition,
        "terminalEvidence": {"identity": "terminal-1", "digest": "c" * 64},
        "quiescenceEvidence": {"identity": "quiet-1", "digest": "d" * 64},
        "settledOutputRevision": revision(),
        "observationId": "observation-1",
        "observationDigest": "e" * 64,
    }


def completion(outputs: object = None) -> JsonObject:
    return {
        "runId": "run-1",
        "nodeId": "agent",
        "reservationId": "reservation-1",
        "attemptId": "attempt-1",
        "activationId": "activation-1",
        "contractHash": "f" * 64,
        "outputs": {} if outputs is None else outputs,
    }


def agent_result(outcome: str = "completed") -> JsonObject:
    payload: JsonObject = {
        "wireVersion": 1,
        "kind": "agent",
        "outcome": outcome,
        "agentCompletion": completion(),
        "hostObservation": host_observation("succeeded" if outcome == "completed" else "failed"),
        "threadId": "thread-1",
        "taskBindingToken": "token-1",
    }
    if outcome != "completed":
        completion_payload = completion()
        completion_payload.pop("outputs")
        payload["agentCompletion"] = completion_payload
        payload["failureCode"] = "provider_failed"
    return payload


def test_auth_01_agent_completion_rejects_host_only_fields() -> None:
    for forbidden in (
        "hostId",
        "provider",
        "executionDisposition",
        "terminalEvidence",
        "settledOutputRevision",
    ):
        with pytest.raises(ValidationError):
            AgentCompletionPayloadV1.model_validate({**completion(), forbidden: "forged"})


def test_auth_01_public_host_observation_rejects_host_id() -> None:
    with pytest.raises(ValidationError):
        HostObservationEnvelopeV1.model_validate({**host_observation(), "hostId": "forged"})


def test_result_01_accepts_completed_agent_result() -> None:
    parsed = NodeResultV1Adapter.validate_python(agent_result())

    assert parsed.kind == "agent"
    assert parsed.outcome == "completed"


@pytest.mark.parametrize("outcome", ["execution_failed", "precondition_blocked", "cancelled"])
def test_result_01_noncompleted_agent_result_rejects_outputs(outcome: str) -> None:
    payload = agent_result(outcome)
    agent_completion = payload["agentCompletion"]
    assert isinstance(agent_completion, dict)
    agent_completion["outputs"] = {"summary": "must-be-rejected"}

    with pytest.raises(ValidationError, match="outputs"):
        NodeResultV1Adapter.validate_python(payload)


@pytest.mark.parametrize("disposition", ["running", "unknown"])
def test_result_01_node_result_rejects_nonterminal_disposition(disposition: str) -> None:
    payload = agent_result()
    payload["hostObservation"] = host_observation(disposition)

    with pytest.raises(ValidationError, match="terminal"):
        NodeResultV1Adapter.validate_python(payload)


def test_result_01_completed_result_requires_succeeded_disposition() -> None:
    payload = agent_result()
    payload["hostObservation"] = host_observation("failed")

    with pytest.raises(ValidationError, match="succeeded"):
        NodeResultV1Adapter.validate_python(payload)


def test_rev_01_verification_evidence_requires_complete_identity() -> None:
    evidence = {
        "runId": "run-1",
        "nodeId": "verify",
        "attemptId": "attempt-1",
        "executionId": "execution-1",
        "operationId": "operation-1",
        "checkId": "tests",
        "checkHash": "a" * 64,
        "evidenceSubjectRevision": revision(),
        "status": "passed",
        "checkResult": {
            "kind": "command",
            "exitCode": 0,
            "stdoutDigest": "b" * 64,
            "stderrDigest": "c" * 64,
        },
        "evidenceDigest": "d" * 64,
    }
    assert VerificationEvidenceV1.model_validate(evidence).status == "passed"

    without_execution = {key: value for key, value in evidence.items() if key != "executionId"}
    with pytest.raises(ValidationError):
        VerificationEvidenceV1.model_validate(without_execution)


def test_result_01_rejects_payload_larger_than_one_mib() -> None:
    payload = agent_result()
    payload["agentCompletion"] = completion({"summary": "x" * 1_048_576})

    with pytest.raises(ValidationError, match="1 MiB"):
        NodeResultV1Adapter.validate_python(payload)
