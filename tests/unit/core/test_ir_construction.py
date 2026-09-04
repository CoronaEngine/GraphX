from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from graphx.core.config.models import NodeId, WorkflowId
from graphx.core.ir.canonicalization import CANONICALIZATION_PROFILE_ID, DigestHex

# This test intentionally exercises the private token that the Phase 2 Compiler alone may use.
from graphx.core.ir.models import (
    _COMPILER_TOKEN,  # pyright: ignore[reportPrivateUsage]
    IRNode,
    IRNodeKind,
    WorkflowIR,
)


def test_ctrl_03_workflow_ir_rejects_construction_without_compiler_token() -> None:
    with pytest.raises(TypeError):
        WorkflowIR(  # type: ignore[call-arg]
            workflow_id=WorkflowId("workflow"),
            nodes=(),
            stable_node_order=(),
            schema_version=1,
            compiler_version="compiler-v1",
            canonicalization_profile=CANONICALIZATION_PROFILE_ID,
            digest=DigestHex("a" * 64),
        )


def test_ctrl_03_compiler_token_constructs_a_frozen_ir_snapshot() -> None:
    node = IRNode(NodeId("done"), IRNodeKind.TERMINAL, (), None)
    ir = WorkflowIR(
        _COMPILER_TOKEN,
        workflow_id=WorkflowId("workflow"),
        nodes=(node,),
        stable_node_order=(NodeId("done"),),
        schema_version=1,
        compiler_version="compiler-v1",
        canonicalization_profile=CANONICALIZATION_PROFILE_ID,
        digest=DigestHex("a" * 64),
    )

    assert ir.nodes == (node,)
    with pytest.raises(FrozenInstanceError):
        ir.digest = DigestHex("b" * 64)  # type: ignore[misc]
