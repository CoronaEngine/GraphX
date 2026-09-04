# GraphX Phase 1 Semantics and Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Phase 1 of `plan.md`: a Python 3.12 project skeleton with enforced dependency boundaries, strict immutable domain/config models, closed v1 wire schemas, canonicalization golden vectors, and executable rejection tests.

**Architecture:** Build from the dependency center outward. `protocol/` owns dependency-neutral wire DTOs, `core/` owns immutable validated domain/config objects and canonicalization rules, inbound workflow adapters are the only JSON-to-domain mapping path, and the two executable entry points remain independent. Phase 1 defines data shapes and boundary validation only; compilation, scheduling, transition decisions, SQLite, MCP serving, and Host execution begin in later phases.

**Tech Stack:** Python 3.12, Pydantic v2 strict models, Pyright strict, Ruff, pytest, standard-library `json`, `hashlib`, `dataclasses`, `enum`, `typing`, and `unicodedata`.

**Spec:** [`plan.md`](../../../plan.md), especially §§1.2, 1.3, 3.4, 4.2–4.7, 5.1, 6, 8, 10, 11.1, 13 Phase 1, and 14.1/14.7/14.8.

## Global Constraints

- Python version is exactly the product floor from §10.1: Python 3.12.
- Production code has complete parameter and return annotations and passes Pyright strict.
- Production code does not use `Any`, `dict[str, Any]`, `cast()` as validation, unexplained `type: ignore`, `eval`, `exec`, monkey patching, dynamic Runner imports, pickle, or dynamic state mutation with `setattr()`.
- Runtime boundaries reject unknown fields, unsupported versions/enums, duplicate JSON keys, non-NFC strings, NUL, out-of-range integers, excessive depth/count/byte size, and illegal tagged-union field combinations.
- `WorkflowConfig`, frozen `WorkflowIR`, and `RunState` remain distinct types. Phase 1 defines the first and the complete RunState aggregate shape; Phase 2 implements the only construction path for valid IR.
- `protocol/` imports no GraphX layer; `core/` imports neither `application/` nor `adapters/`; `application/` imports no concrete adapter; `adapters/host/` imports only `protocol/` plus external/stdlib packages.
- Only `adapters/store/sqlite/` may import `sqlite3`, open database connections, or execute SQL. Phase 1 contains no SQLite implementation.
- Only `application/state_committer.py` may eventually commit NodeState or RunState changes. Phase 1 defines no mutating state service.
- Canonical profile is `graphx-canonical-json-v1`; digests are lowercase SHA-256 of `domain || 0x00 || canonical_bytes`.
- The only accepted external-node side effects are `none` and `workspaceMutation`; Phase 1 models both but does not dispatch either.
- Tests and names reference the governing requirement ID or section where practical: CTRL-01..03, STATE-01, TASK-01..02, SCHED-01, MUT-01..03, RESULT-01, IDEM-01, OUTCOME-01, COND-01, BOUNDARY-01, EXT-01, OP-01, REV-01, AUTH-01, and CANON-01.
- Every task ends with its focused pytest target and the repository gates relevant at that point.

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, Python floor, console entry points, strict Pyright/Ruff/pytest configuration. |
| `src/graphx/bootstrap.py` | Service composition entry point only; Phase 1 exposes an importable stub with no Host import. |
| `src/graphx/adapters/host/main.py` | Independent Host entry point; Phase 1 exposes an importable stub with no Core/Application import. |
| `src/graphx/protocol/common_v1.py` | Strict wire base class, bounded scalar aliases, opaque wire identifier/digest strings, and safe diagnostics primitives. |
| `src/graphx/protocol/workflow_v1.py` | Closed Workflow Config v1 DTOs: node variants, ValueSchema, ValueExpr, ConditionExpr, ProcessSpec, policies, and revision policy. |
| `src/graphx/protocol/execution_v1.py` | Closed execution DTOs: dispatches, completion, Host observations, results, revisions, evidence, handles, and mutation resolution. |
| `src/graphx/protocol/mcp_v1.py` | Versioned MCP request/response DTOs, NextDecision, inspect summaries, error union, and retry directives. |
| `src/graphx/core/config/models.py` | Frozen validated Config-domain dataclasses and strong workflow/node/name types. |
| `src/graphx/core/ir/models.py` | Frozen IR type declarations only; constructor token remains private to the Phase 2 Compiler. |
| `src/graphx/core/ir/canonicalization.py` | Typed canonical JSON serialization and domain-separated hashing. |
| `src/graphx/core/runtime/models.py` | Enums, strong IDs, frozen records, tagged ownership, and complete immutable RunState aggregate. |
| `src/graphx/adapters/inbound/workflow/loader.py` | UTF-8 JSON parsing, duplicate-key rejection, and Pydantic wire validation. |
| `src/graphx/adapters/inbound/workflow/mapper.py` | Explicit wire DTO to frozen Config-domain mapping; no semantic compilation. |
| `src/graphx/adapters/inbound/mcp/authorization.py` | Pure closed Controller/Host operation allowlist over transport-created principals. |
| `tests/unit/architecture/test_import_boundaries.py` | AST-based dependency and `sqlite3` ownership guards. |
| `tests/unit/protocol/test_workflow_v1.py` | Workflow closed-schema accept/reject matrix. |
| `tests/unit/protocol/test_execution_v1.py` | Execution DTO identity, tag, field, and size matrix. |
| `tests/unit/protocol/test_mcp_v1.py` | Envelope, principal-field exclusion, request/response, error, and redaction matrix. |
| `tests/unit/core/test_canonicalization.py` | Canonical bytes, domain separation, bounds, and golden vectors. |
| `tests/unit/core/test_runtime_models.py` | Frozen aggregate, enum, tagged ownership, and RunStatus/WorkflowOutcome composition tests. |
| `tests/unit/adapters/test_workflow_loader.py` | Raw JSON duplicate/Unicode/NUL/version rejection and mapping tests. |
| `tests/unit/adapters/test_mcp_authorization.py` | Closed principal/operation permission matrix. |
| `tests/fixtures/canonicalization_v1.json` | Checked-in canonicalization inputs, bytes, domains, and expected digests. |

---

### Task 1: Bootstrap the Python Package and Enforce Import Boundaries

**Files:**
- Create: `pyproject.toml`
- Create: `src/graphx/__init__.py`
- Create: package `__init__.py` files for every directory listed in §10.4
- Create: `src/graphx/bootstrap.py`
- Create: `src/graphx/adapters/host/main.py`
- Create: `tests/unit/architecture/test_import_boundaries.py`

**Interfaces:**
- Produces: console entry points `graphx-service = graphx.bootstrap:main` and `graphx-host = graphx.adapters.host.main:main`.
- Produces: `main() -> None` in both entry modules.
- Produces: `test_layer_imports_follow_plan_10_4()` and `test_only_sqlite_adapter_imports_sqlite3()` as permanent architecture gates.

- [ ] **Step 1: Write the failing architecture tests**

```python
def test_layer_imports_follow_plan_10_4() -> None:
    violations = collect_graphx_import_violations(SRC_ROOT)
    assert violations == []


def test_only_sqlite_adapter_imports_sqlite3() -> None:
    offenders = collect_sqlite3_importers(SRC_ROOT)
    assert offenders <= {Path("graphx/adapters/store/sqlite")}
```

The AST walker must inspect `Import` and `ImportFrom`; it must reject protocol-to-GraphX imports, core-to-outer imports, application-to-adapter imports, Host-to-Core/Application/inbound/store imports, and `sqlite3` outside the SQLite adapter subtree.

- [ ] **Step 2: Run the architecture test and confirm the missing package/config failure**

Run: `python3.12 -m pytest tests/unit/architecture/test_import_boundaries.py -q`

Expected: FAIL because the package skeleton and collector do not exist.

- [ ] **Step 3: Add project configuration and the two independent entry points**

```toml
[build-system]
requires = ["hatchling>=1,<2"]
build-backend = "hatchling.build"

[project]
name = "graphx-task-executor"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["pydantic>=2,<3"]

[project.optional-dependencies]
dev = ["pyright>=1,<2", "pytest>=8,<10", "ruff>=0.9,<1"]

[project.scripts]
graphx-service = "graphx.bootstrap:main"
graphx-host = "graphx.adapters.host.main:main"

[tool.pyright]
pythonVersion = "3.12"
typeCheckingMode = "strict"
include = ["src", "tests"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Both `main()` functions return `None` and perform no composition or external work in Phase 1.

- [ ] **Step 4: Implement the AST import-boundary collector and run it**

Run: `python3.12 -m pytest tests/unit/architecture/test_import_boundaries.py -q`

Expected: PASS, including synthetic forbidden-import fixtures proving each rule can fail.

- [ ] **Step 5: Run initial static gates**

Run: `python3.12 -m ruff check . && python3.12 -m ruff format --check . && python3.12 -m pyright`

Expected: all commands exit 0.

- [ ] **Step 6: Commit the independently reviewable skeleton**

```bash
git add pyproject.toml src tests/unit/architecture
git commit -m "build: establish GraphX package boundaries"
```

---

### Task 2: Add Strong Primitive Types and Canonical JSON v1

**Files:**
- Create: `src/graphx/protocol/common_v1.py`
- Create: `src/graphx/core/ir/canonicalization.py`
- Create: `tests/unit/core/test_canonicalization.py`
- Create: `tests/fixtures/canonicalization_v1.json`

**Interfaces:**
- Produces from `protocol/common_v1.py`: `StrictWireModel`, `WireVersion`, `DigestHexText`, `SafeDiagnosticText`, and validated opaque wire identifier strings.
- Produces: recursive `CanonicalValue` containing only `None | bool | signed-64-bit int | NFC str | tuple[CanonicalValue, ...] | Mapping[str, CanonicalValue]`.
- Produces from `core/ir/canonicalization.py`: domain `DigestHex`, `CanonicalizationProfileId`, and `DigestDomain`; Core does not import wire DTOs.
- Produces: `canonical_json_bytes(value: CanonicalValue) -> bytes`.
- Produces: `domain_digest(domain: DigestDomain, value: CanonicalValue) -> DigestHex`.
- Produces: closed `DigestDomain` enum with `graphx-ir-v1`, `graphx-contract-v1`, `graphx-request-v1`, `graphx-response-v1`, `graphx-revision-v1`, and `graphx-workspace-identity-v1`.

- [ ] **Step 1: Write failing golden-vector tests**

```python
def test_canon_01_utf8_key_order_and_domain_digest() -> None:
    value = {"b": 2, "a": "é"}
    assert canonical_json_bytes(value) == b'{"a":"\xc3\xa9","b":2}'
    assert domain_digest(DigestDomain.IR, value) == (
        "a16dc324de0bdf7e014d5b557cdd679a7b329d40e625be2291e76a4116c2213f"
    )


def test_canon_01_domain_separation() -> None:
    value = {"b": 2, "a": "é"}
    assert domain_digest(DigestDomain.REQUEST, value) == (
        "b68d6467b04e99ec85ecd9c9b465fb6cfac9e4b96616900c9e935ac7b89c63dc"
    )
```

Add rejection cases for float, integer outside signed 64-bit range, non-NFC string, NUL, duplicate mapping keys at decode time, and an unsupported digest domain.

- [ ] **Step 2: Run the focused tests and confirm missing-symbol failures**

Run: `python3.12 -m pytest tests/unit/core/test_canonicalization.py -q`

Expected: FAIL on missing `canonical_json_bytes` and `domain_digest`.

- [ ] **Step 3: Implement canonicalization without untyped containers**

```python
def domain_digest(domain: DigestDomain, value: CanonicalValue) -> DigestHex:
    payload = domain.value.encode("ascii") + b"\x00" + canonical_json_bytes(value)
    return DigestHex(hashlib.sha256(payload).hexdigest())
```

The serializer emits UTF-8 without BOM or extra whitespace, sorts object keys by UTF-8 bytes, preserves array order, emits JSON booleans/null exactly, validates NFC/NUL recursively, and never accepts float.

- [ ] **Step 4: Check in the independent fixture**

`tests/fixtures/canonicalization_v1.json` must contain the literal input, canonical UTF-8 bytes represented as hex, digest domain, and expected lowercase digest. Tests read the fixture as `object`, validate it into a strict fixture model, then compare runtime output.

- [ ] **Step 5: Run focused and static gates**

Run: `python3.12 -m pytest tests/unit/core/test_canonicalization.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

Expected: all commands exit 0.

- [ ] **Step 6: Commit canonicalization**

```bash
git add src/graphx/protocol/common_v1.py src/graphx/core/ir/canonicalization.py tests
git commit -m "feat: freeze canonical JSON v1"
```

---

### Task 3: Define the Closed Workflow Config v1 Wire Schema

**Files:**
- Create: `src/graphx/protocol/workflow_v1.py`
- Create: `tests/unit/protocol/test_workflow_v1.py`

**Interfaces:**
- Produces node union: `AgentNodeV1 | CommandNodeV1 | VerifierNodeV1 | GateNodeV1 | TerminalNodeV1`, discriminated by `type`.
- Produces ValueSchema union: boolean, integer, bounded string, bounded array, closed object, process result, verification evidence.
- Produces ValueExpr union: `FromExprV1 | LiteralExprV1` with exactly one tag.
- Produces ConditionExpr union: `Eq | Ne | Lt | Le | Gt | Ge | Not | All | Any` with exactly one operator.
- Produces `ProcessSpecV1`, `RetryPolicyV1`, `TimeoutPolicyV1`, `SettlementRecoveryPolicyV1`, `CanonicalTreeRevisionPolicyV1`, `WorkflowV1`, and `WorkflowConfigV1`.
- All objects inherit `StrictWireModel` configured with `extra="forbid"`, strict values, frozen instances, and aliases matching the JSON contract.

- [ ] **Step 1: Write the node field-matrix tests**

```python
@pytest.mark.parametrize(
    ("node", "forbidden_field"),
    [
        (valid_agent_node(), "condition"),
        (valid_command_node(), "task"),
        (valid_verifier_node(), "outcome"),
        (valid_gate_node(), "sideEffect"),
        (valid_terminal_node(), "when"),
    ],
)
def test_plan_4_4_rejects_node_specific_unknown_fields(
    node: JsonObject, forbidden_field: str
) -> None:
    candidate = node.with_item(forbidden_field, True)
    with pytest.raises(ValidationError):
        NodeV1Adapter.validate_python(candidate.value)
```

Add exact boundary cases for node count 1024/1025, ID regex and 64-byte limit, task byte length, 32 acceptance criteria, argv count/total bytes, exit codes, retry 1..10, recovery 1..5, timeout 1..86400, and paired `settlesMutation`/`settlementRecovery`.

- [ ] **Step 2: Write ValueSchema and ConditionExpr depth/tag tests**

Cover depth 16/17, 128/129 object properties, `maxItems` 10000/10001, string maximum 1 MiB, forbidden float/null/bytes, duplicate collections, mixed comparison operand kinds, zero/65 `all` operands, and more than one operator in a condition object.

- [ ] **Step 3: Run the tests and confirm schema symbols are absent**

Run: `python3.12 -m pytest tests/unit/protocol/test_workflow_v1.py -q`

Expected: FAIL during import of `WorkflowConfigV1`.

- [ ] **Step 4: Implement the strict discriminated models and local validators**

```python
class StrictWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, populate_by_name=False)


class WorkflowConfigV1(StrictWireModel):
    version: Literal[1]
    workflow: WorkflowV1
```

Validators count UTF-8 bytes rather than Python characters, require NFC, reject NUL and duplicates, and enforce node-type required/forbidden combinations. They do not check graph cycles, references, reachability, inferred dependencies, or condition operand types that depend on upstream outputs; those belong to the Phase 2 Compiler.

- [ ] **Step 5: Run schema and static gates**

Run: `python3.12 -m pytest tests/unit/protocol/test_workflow_v1.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

Expected: all commands exit 0.

- [ ] **Step 6: Commit the Config wire schema**

```bash
git add src/graphx/protocol/workflow_v1.py tests/unit/protocol/test_workflow_v1.py
git commit -m "feat: add closed workflow config v1 schema"
```

---

### Task 4: Add Raw Workflow Loading and Explicit Config-Domain Mapping

**Files:**
- Create: `src/graphx/core/config/models.py`
- Create: `src/graphx/adapters/inbound/workflow/loader.py`
- Create: `src/graphx/adapters/inbound/workflow/mapper.py`
- Create: `tests/unit/adapters/test_workflow_loader.py`

**Interfaces:**
- Produces: `load_workflow_json(payload: bytes) -> WorkflowConfigV1`.
- Produces: `map_workflow_config(dto: WorkflowConfigV1) -> WorkflowConfig`.
- Produces: frozen Config-domain node/value/condition dataclasses, `WorkflowId`, `NodeId`, `InputName`, and `OutputName`.
- Does not produce `WorkflowIR`; only the Phase 2 Compiler may do so.

- [ ] **Step 1: Write failing raw-boundary tests**

```python
def test_ctrl_02_loader_rejects_duplicate_json_keys() -> None:
    raw = b'{"version":1,"version":1,"workflow":{"id":"w","nodes":[]}}'
    with pytest.raises(WorkflowDecodeError) as exc_info:
        load_workflow_json(raw)
    assert exc_info.value.code is WorkflowDecodeErrorCode.DUPLICATE_KEY


def test_plan_4_4_loader_rejects_non_nfc_text() -> None:
    raw = '{"version":1,"workflow":{"id":"e\u0301","nodes":[]}}'.encode()
    with pytest.raises(WorkflowDecodeError):
        load_workflow_json(raw)
```

Also reject invalid UTF-8, BOM, NUL, trailing JSON, unknown version, and unknown fields before mapping.

- [ ] **Step 2: Run focused tests and confirm missing loader/mapping failures**

Run: `python3.12 -m pytest tests/unit/adapters/test_workflow_loader.py -q`

Expected: FAIL on missing `load_workflow_json`.

- [ ] **Step 3: Implement typed parsing and explicit mapping**

```python
def load_workflow_json(payload: bytes) -> WorkflowConfigV1:
    text = decode_utf8_without_bom(payload)
    decoded: object = DuplicateRejectingJsonDecoder().decode(text)
    return WorkflowConfigV1.model_validate(decoded)


def map_workflow_config(dto: WorkflowConfigV1) -> WorkflowConfig:
    return WorkflowConfig(version=1, workflow=map_workflow(dto.workflow))
```

Mapping uses explicit exhaustive `match` statements over every closed union and `assert_never()` for unreachable variants. Config-domain collections become tuples and immutable mappings. No Pydantic DTO or caller-owned mutable list/dict is retained.

- [ ] **Step 4: Prove DTO mutation cannot affect the domain object**

Tests construct from mutable raw inputs, map them, mutate the original inputs, and assert the frozen domain object and its canonical form remain unchanged. Tests also assert attempts to assign fields raise `FrozenInstanceError` or Pydantic frozen-instance errors.

- [ ] **Step 5: Run focused and static gates**

Run: `python3.12 -m pytest tests/unit/adapters/test_workflow_loader.py tests/unit/protocol/test_workflow_v1.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

Expected: all commands exit 0.

- [ ] **Step 6: Commit the trusted Config boundary**

```bash
git add src/graphx/core/config src/graphx/adapters/inbound/workflow tests/unit/adapters
git commit -m "feat: validate and map workflow config"
```

---

### Task 5: Define Immutable IR Declarations and the Complete RunState Aggregate

**Files:**
- Create: `src/graphx/core/ir/models.py`
- Create: `src/graphx/core/runtime/models.py`
- Create: `tests/unit/core/test_runtime_models.py`

**Interfaces:**
- Produces strong ID/value objects for Run, reservation, attempt, mechanical attempt/execution, activation, external operation, settlement check, lease, binding, observation, request, contract, revision, evidence, transaction, principal, host, workspace, and thread identities.
- Produces enums exactly matching §§6 and 8: `NodeState`, `RunStatus`, `WorkflowOutcome`, `HostKind`, `SideEffectClass`, `ResultOutcome`, `VerificationStatus`, `OperationKind`, `OperationState`, `OperationTerminalDisposition`, `ExecutionDisposition`, `RetryDirective`, `MutationResolutionDecision`, and `ConditionDecisionKind`.
- Produces frozen tagged ownership records for reservation, agent attempt, mechanical attempt, settled mutation, and settlement-check owners.
- Produces frozen records: `RunControllerBinding`, `RunHostBinding`, `CancellationIntent`, `DispatchReservation`, `AgentAttempt`, `ExecutionHandle`, `TaskActivation`, `MechanicalAttempt`, `MechanicalExecutionHandle`, `SettlementCheckExecution`, `ExternalOperation`, `ExternalOperationObservation`, `WorkspaceRevision`, `VerificationEvidence`, `ActiveExecutionSlot`, `MutationLease`, `AcceptedWorkspaceBaseline`, `NodeRuntimeState`, `NodeOutput`, and `RunState`.
- Produces IR declaration types with no public valid-IR constructor. `WorkflowIR` is frozen and can only be created by passing a module-private `_CompilerToken`; Task 8 verifies external construction is rejected. Phase 2's `core/ir/compiler.py` will be the only production importer of that token.

- [ ] **Step 1: Write the enum and frozen-record tests**

```python
def test_state_01_runtime_records_are_frozen() -> None:
    reservation = make_reservation()
    with pytest.raises(FrozenInstanceError):
        reservation.node_id = NodeId("other")  # type: ignore[misc]


def test_outcome_01_rejects_success_without_success_outcome() -> None:
    with pytest.raises(InvalidRunAggregate):
        build_run_state(status=RunStatus.SUCCEEDED, outcome=None)
```

The single explained test-only ignore is permitted because the line intentionally attempts an illegal assignment; production remains ignore-free.

- [ ] **Step 2: Add the aggregate composition matrix**

Accept exactly: `succeeded + success`; failure-terminal `failed + failure`; operational `failed + None`; and `validated/running/blocked/ambiguous/cancelled + None`. Reject terminal status with active slot, unresolved operation, or mutation lease; reject a stable aggregate containing `NodeState.VERIFYING`; reject attempt without its required immutable handle; reject more than one activation per AgentAttempt.

- [ ] **Step 3: Run focused tests and confirm missing model failures**

Run: `python3.12 -m pytest tests/unit/core/test_runtime_models.py -q`

Expected: FAIL importing `RunState` and the runtime enums.

- [ ] **Step 4: Implement frozen records and one validated aggregate constructor**

```python
@dataclass(frozen=True, slots=True)
class RunState:
    run_id: RunId
    aggregate_version: int
    ir_digest: IrDigest
    status: RunStatus
    outcome: WorkflowOutcome | None
    controller_binding: RunControllerBinding
    host_binding: RunHostBinding
    nodes: Mapping[NodeId, NodeRuntimeState]
    reservations: tuple[DispatchReservation, ...]
    agent_attempts: tuple[AgentAttempt, ...]
    mechanical_attempts: tuple[MechanicalAttempt, ...]
    execution_handles: tuple[ExecutionHandle, ...]
    mechanical_execution_handles: tuple[MechanicalExecutionHandle, ...]
    task_activations: tuple[TaskActivation, ...]
    external_operations: tuple[ExternalOperation, ...]
    external_operation_observations: tuple[ExternalOperationObservation, ...]
    settlement_checks: tuple[SettlementCheckExecution, ...]
    settled_mutations: tuple[SettledMutationRecord, ...]
    node_outputs: tuple[NodeOutput, ...]
    evidence_records: tuple[VerificationEvidence, ...]
    accepted_workspace_baseline: AcceptedWorkspaceBaseline | None
    effective_workspace_baseline: WorkspaceRevision
    idempotency_receipts: tuple[IdempotencyReceipt, ...]
    active_slot: ActiveExecutionSlot | None
    mutation_leases: tuple[MutationLease, ...]
    cancellation_intent: CancellationIntent | None
```

Construction copies mappings into immutable proxies/tuples and calls `validate_run_state_composition(state)`. That validator checks structural composition only; legal transitions remain Phase 2.

- [ ] **Step 5: Verify strict typing and import direction**

Run: `python3.12 -m pytest tests/unit/core/test_runtime_models.py tests/unit/architecture/test_import_boundaries.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

Expected: all commands exit 0.

- [ ] **Step 6: Commit the domain model layer**

```bash
git add src/graphx/core/ir/models.py src/graphx/core/runtime/models.py tests/unit/core
git commit -m "feat: define immutable GraphX runtime aggregate"
```

---

### Task 6: Define Execution, Result, Revision, and Evidence Wire Schemas

**Files:**
- Create: `src/graphx/protocol/execution_v1.py`
- Create: `tests/unit/protocol/test_execution_v1.py`

**Interfaces:**
- Produces `AgentNodeDispatchV1`, `MechanicalNodeDispatchV1`, `TaskContractV1`, `AgentCompletionPayloadV1`, `HostObservationEnvelopeV1`, `AgentNodeResultV1`, `MechanicalNodeResultV1`, `WorkspaceRevisionV1`, `VerificationEvidenceV1`, `ProcessResultV1`, `DispatchReservationV1`, handle DTOs, operation observation DTOs, and `MutationResolutionV1`.
- Produces discriminated `NodeResultV1 = AgentNodeResultV1 | MechanicalNodeResultV1`.
- Produces closed `ResultOutcome` field matrices from §8.6.
- Public DTOs contain no caller-supplied authenticated Host ID; Host ID exists only in the internal transport context/domain observation.

- [ ] **Step 1: Write result-outcome field-matrix tests**

```python
@pytest.mark.parametrize("outcome", ["execution_failed", "precondition_blocked", "cancelled"])
def test_result_01_noncompleted_result_rejects_outputs(outcome: str) -> None:
    payload = valid_mechanical_result(outcome=outcome).with_item("outputs", {"x": 1})
    with pytest.raises(ValidationError):
        NodeResultV1Adapter.validate_python(payload.value)


def test_auth_01_public_host_observation_rejects_host_id() -> None:
    payload = valid_host_observation().with_item("hostId", "caller-forged")
    with pytest.raises(ValidationError):
        HostObservationEnvelopeV1.model_validate(payload.value)
```

Cover all four outcomes, agent/mechanical tags, forbidden gate/terminal results, 1 MiB result payload, 64 KiB diagnostics, 1 MiB stdout/stderr evidence, matching identity fields, and `running/unknown` exclusion from NodeResult.

- [ ] **Step 2: Write evidence and observation separation tests**

AgentCompletionPayload must reject provider identity, execution disposition, terminal/quiescence evidence, settled revision, Host observation identity/digest, and authenticated Host ID. VerificationEvidence must require run/node/attempt/execution/operation identities, check ID/hash, evidence subject revision, status, tagged check result, and evidence digest.

- [ ] **Step 3: Run focused tests and confirm missing DTO failures**

Run: `python3.12 -m pytest tests/unit/protocol/test_execution_v1.py -q`

Expected: FAIL importing `NodeResultV1Adapter`.

- [ ] **Step 4: Implement the closed execution unions**

```python
class AgentNodeResultV1(StrictWireModel):
    wire_version: Literal[1] = Field(alias="wireVersion")
    kind: Literal["agent"]
    outcome: ResultOutcomeV1
    agent_completion: AgentCompletionPayloadV1 = Field(alias="agentCompletion")
    host_observation: HostObservationEnvelopeV1 = Field(alias="hostObservation")
    thread_id: ThreadIdText = Field(alias="threadId")
    task_binding_token: TaskBindingTokenText = Field(alias="taskBindingToken")
```

Use model validators to enforce each outcome's required/forbidden fields and canonical byte-size limits. Identity/revision equality against RunState is not performed here; Phase 2's pure result validation owns semantic matching.

- [ ] **Step 5: Run focused and static gates**

Run: `python3.12 -m pytest tests/unit/protocol/test_execution_v1.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

Expected: all commands exit 0.

- [ ] **Step 6: Commit execution DTOs**

```bash
git add src/graphx/protocol/execution_v1.py tests/unit/protocol/test_execution_v1.py
git commit -m "feat: add execution protocol v1"
```

---

### Task 7: Define MCP Envelopes, Operation DTOs, Principals, and Closed Errors

**Files:**
- Create: `src/graphx/protocol/mcp_v1.py`
- Create: `src/graphx/adapters/inbound/mcp/authorization.py`
- Create: `tests/unit/protocol/test_mcp_v1.py`
- Create: `tests/unit/adapters/test_mcp_authorization.py`

**Interfaces:**
- Consumes immutable domain principals `ControllerPrincipal` and `HostPrincipal` from `core/runtime/models.py`; they are transport-created values and are never fields in public request JSON.
- Produces request DTOs for all fourteen §11 operations: validate workflow, record Host observation, start run, next, bind task, activate task, activate mechanical, submit result, fail attempt, reconcile external operation, resolve mutation, inspect run, resume run, and cancel run.
- Every mutating request carries `wireVersion=1`, UUID `requestId`, non-empty `idempotencyKey`, and—when a Run exists—`runId` plus `expectedRunVersion`.
- Produces `ResponseEnvelopeV1`, `NextDecisionV1`, inspect summaries/cursors, `ErrorBodyV1`, `ErrorCodeV1`, and `RetryDirectiveV1`.

- [ ] **Step 1: Write failing envelope and principal-exclusion tests**

```python
def test_auth_01_request_rejects_principal_and_host_id_fields() -> None:
    request = valid_bind_request().with_items(principalId="p", hostId="h")
    with pytest.raises(ValidationError):
        BindTaskRequestV1.model_validate(request.value)


def test_idem_01_mutating_request_requires_idempotency_fields() -> None:
    request = valid_next_request().without("idempotencyKey")
    with pytest.raises(ValidationError):
        NextRequestV1.model_validate(request.value)
```

Add a table covering all fourteen operations and the Controller/Host allowlist from §11.1. The schema test verifies field shapes; a pure `authorize(principal, operation) -> AuthorizationDecision` test verifies the closed permissions matrix without transport I/O.

- [ ] **Step 2: Write the closed error and redaction tests**

Assert exactly these codes: `invalid_request`, `unsupported_version`, `unauthenticated`, `forbidden`, `not_found`, `conflict`, `stale`, `not_ready`, `run_not_runnable`, `reconciliation_required`, `capability_unavailable`, `integrity_failure`, `internal_failure`. Assert exactly these retry directives: `do_not_retry`, `retry_same_request`, `reconcile`, `user_action`. Reject raw Contract, token, credential, database path, absolute workspace path, and traceback-shaped details.

- [ ] **Step 3: Run focused tests and confirm missing DTO failures**

Run: `python3.12 -m pytest tests/unit/protocol/test_mcp_v1.py -q`

Expected: FAIL importing `ResponseEnvelopeV1`.

- [ ] **Step 4: Implement all operation DTOs and exhaustive inbound authorization**

```python
def authorize(principal: McpPrincipal, operation: McpOperation) -> AuthorizationDecision:
    match principal:
        case ControllerPrincipal():
            return authorize_controller(operation)
        case HostPrincipal():
            return authorize_host(operation)
        case unreachable:
            assert_never(unreachable)
```

The function lives in `adapters/inbound/mcp/authorization.py`, not in `protocol/`; protocol remains data-only. Response envelopes exclude `requestId` and `replayed` from the stable receipt-body digest. Inspect DTOs expose only run version, IR digest, status/outcome, node/operation/lease summaries, and opaque cursors; they do not expose binding tokens, raw Contract bytes, Host credentials, database information, or raw provider evidence.

- [ ] **Step 5: Run focused and static gates**

Run: `python3.12 -m pytest tests/unit/protocol/test_mcp_v1.py tests/unit/adapters/test_mcp_authorization.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

Expected: all commands exit 0.

- [ ] **Step 6: Commit MCP DTOs and permission types**

```bash
git add src/graphx/protocol/mcp_v1.py src/graphx/adapters/inbound/mcp/authorization.py tests/unit/protocol/test_mcp_v1.py tests/unit/adapters/test_mcp_authorization.py
git commit -m "feat: define MCP protocol v1"
```

---

### Task 8: Lock IR Construction, Model Ownership, and Phase Boundaries

**Files:**
- Modify: `src/graphx/core/ir/models.py`
- Modify: `src/graphx/core/runtime/models.py`
- Modify: `tests/unit/core/test_runtime_models.py`
- Modify: `tests/unit/architecture/test_import_boundaries.py`
- Create: `tests/unit/core/test_ir_construction.py`

**Interfaces:**
- Produces: `WorkflowIR` declarations that cannot be instantiated through a public constructor.
- Produces: exhaustive owner union `StateOwner = ReservationOwner | AgentAttemptOwner | MechanicalAttemptOwner | SettledMutationOwner | SettlementCheckOwner`.
- Produces: explicit model-to-authority inventory exercised by tests: Config input, IR snapshot, RunState aggregate, Host observation, and external provider identity remain distinct.

- [ ] **Step 1: Write failing construction and ownership tests**

```python
def test_ctrl_03_only_compiler_token_can_construct_ir() -> None:
    with pytest.raises(TypeError):
        WorkflowIR(workflow_id=WorkflowId("w"), nodes=(), digest=IrDigest("0" * 64))


def test_mut_01_owner_union_is_exhaustive() -> None:
    owners = make_each_owner_variant()
    assert {owner.kind for owner in owners} == {
        OwnerKind.RESERVATION,
        OwnerKind.AGENT_ATTEMPT,
        OwnerKind.MECHANICAL_ATTEMPT,
        OwnerKind.SETTLED_MUTATION,
        OwnerKind.SETTLEMENT_CHECK,
    }
```

- [ ] **Step 2: Add negative imports for all authority boundaries**

Synthetic source trees must demonstrate that the guard rejects: protocol importing Core, Core importing Application, Application importing SQLite adapter, Host importing Core, inbound MCP importing SQLite directly, and `bootstrap.py` importing Host.

- [ ] **Step 3: Implement private IR creation and exhaustive ownership helpers**

```python
class _CompilerToken:
    __slots__ = ()


_COMPILER_TOKEN = _CompilerToken()


@dataclass(frozen=True, slots=True)
class WorkflowIR:
    _compiler_token: InitVar[_CompilerToken]
    workflow_id: WorkflowId
    nodes: tuple[IRNode, ...]
    digest: IrDigest

    def __post_init__(self, _compiler_token: _CompilerToken) -> None:
        if _compiler_token is not _COMPILER_TOKEN:
            raise TypeError("WorkflowIR may only be constructed by the Compiler")
```

`_COMPILER_TOKEN` is not exported from `core.ir.models`; Phase 2's `core/ir/compiler.py` is the only production module allowed by the architecture test to import it and pass it to the constructor.

- [ ] **Step 4: Run the model and architecture suites**

Run: `python3.12 -m pytest tests/unit/core/test_ir_construction.py tests/unit/core/test_runtime_models.py tests/unit/architecture/test_import_boundaries.py -q`

Expected: all commands exit 0.

- [ ] **Step 5: Commit Phase 1 authority guards**

```bash
git add src/graphx/core tests/unit/core tests/unit/architecture
git commit -m "test: enforce GraphX authority boundaries"
```

---

### Task 9: Run the Phase 1 Acceptance Matrix and Freeze the Baseline

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Create: `tests/unit/test_phase1_acceptance.py`

**Interfaces:**
- Produces: one Phase 1 smoke suite importing every public model/adapter entry point and exercising one accepted and one rejected payload per closed union.
- Produces: README status links to `plan.md` Phase 1 without restating semantic rules.

- [ ] **Step 1: Write the Phase 1 acceptance smoke test**

```python
def test_phase_1_public_surface_is_closed_and_importable() -> None:
    assert WorkflowConfigV1.model_json_schema()["additionalProperties"] is False
    assert set(NodeState) == EXPECTED_NODE_STATES
    assert set(RunStatus) == EXPECTED_RUN_STATUSES
    assert CANONICALIZATION_PROFILE_ID == "graphx-canonical-json-v1"
```

The suite also checks all public Pydantic models are frozen/extra-forbid, every enum is closed, all aggregate dataclasses are frozen+slotted, every wire version is 1, public requests contain no `hostId`/principal field, and both console targets import independently.

- [ ] **Step 2: Run all tests and capture the first failure**

Run: `python3.12 -m pytest -q`

Expected: PASS if Tasks 1–8 are complete; any failure is fixed in the owning task's module and focused test before rerunning the suite.

- [ ] **Step 3: Run the complete release gate**

Run: `python3.12 -m pyright && python3.12 -m ruff check . && python3.12 -m ruff format --check . && python3.12 -m pytest`

Expected: all four commands exit 0.

- [ ] **Step 4: Verify Phase 1 scope exclusions**

Run: `rg -n "sqlite3|class .*Scheduler|def compile_|mcp\.server|subprocess|create_thread" src/graphx -g '*.py'`

Expected: no `sqlite3`, Scheduler, Compiler implementation, MCP server startup, subprocess execution, or Codex task creation appears in Phase 1 production modules. The only accepted hits are names/types in comments or protocol declarations, and those are reviewed manually.

- [ ] **Step 5: Update status documentation without duplicating authority**

README changes state that Phase 1 is implemented and link to `plan.md` §13 and the Phase 1 acceptance test. They do not copy state-transition tables, Schema bounds, or authority rules.

- [ ] **Step 6: Commit the Phase 1 baseline**

```bash
git add README.md README.zh-CN.md tests/unit/test_phase1_acceptance.py
git commit -m "docs: mark GraphX phase 1 baseline"
```

---

## Review Checkpoints

1. **After Task 1:** approve packaging and dependency direction before any model work.
2. **After Task 4:** approve the complete Config boundary before Runtime/IR types depend on it.
3. **After Task 7:** compare every public wire DTO against §§8 and 11.1; reject leaked Host identity or open unions.
4. **After Task 8:** confirm the code expresses authority separation without implementing Phase 2 transitions.
5. **After Task 9:** accept Phase 1 only when all four release gates pass from a clean environment.

## Requirement Coverage Audit

| Phase 1 obligation | Owning tasks |
|---|---|
| §10 package skeleton, two entry points, dependency guards | Tasks 1 and 8 |
| Strict separate Config, immutable IR, and complete RunState models | Tasks 4, 5, and 8 |
| §4.4–4.6 closed Config/Value/Condition/policy bounds | Tasks 3 and 4 |
| §4.7 canonical profile, domain digest, and golden vectors | Task 2 |
| NodeState/RunStatus/outcome and stable aggregate composition | Task 5 |
| Dispatch, attempt, handle, activation, operation, settlement, ownership, and resolution types | Tasks 5, 6, and 8 |
| NodeDispatch, Agent/Host payload separation, NodeResult, revision, and evidence wire types | Task 6 |
| MCP request/response, inspect, errors, principals, and permission matrix | Task 7 |
| Unknown field/version/enum and missing isolation/authority prerequisite rejection | Tasks 1, 3, 6, 7, and 9 |
| Phase 1 release gates and Phase 2+ exclusion | Task 9 |

## Phase 1 Definition of Done

- All §10.4 package directories and both entry points exist and import independently.
- Architecture tests mechanically reject every forbidden dependency and any `sqlite3` import outside its adapter boundary.
- Workflow Config v1, ValueSchema, ValueExpr, ConditionExpr, ProcessSpec, retry/timeout/recovery policies, and RevisionPolicy are closed and enforce all §4.4–4.7 local bounds.
- Canonicalization golden vectors pin bytes, profile, domain separation, and lowercase SHA-256 digests.
- WorkflowConfig, WorkflowIR, and RunState are distinct; RunState contains every aggregate member named in §4.2 and rejects illegal stable compositions.
- All Phase 1 runtime records are immutable and all state/identity/result/operation variants are enums or tagged unions rather than bare strings.
- NodeDispatch, Task Contract, AgentCompletionPayload, HostObservationEnvelope, NodeResult, WorkspaceRevision, VerificationEvidence, MCP envelopes, inspect summaries, and errors are versioned closed DTOs.
- Public DTOs cannot inject HostId/principal authority, Agent payloads cannot carry Host-only observations, and diagnostics cannot expose secrets or private paths.
- No Phase 2+ behavior exists: no compiler logic, scheduler, transition evaluator, StateCommitter, SQLite schema, MCP server, Host execution, or mutation lease acquisition.
- `pyright`, `ruff check`, `ruff format --check`, and `pytest` all pass.

## Deferred Explicitly to Later Phases

- Phase 2: graph semantic validation, WorkflowIR construction, canonical IR digest, condition evaluation, transitions, ready calculation, and deterministic scheduling.
- Phase 3: Store ports, SQLite adapter/constraints/migrations, StateCommitter, Query Service, MCP server, and the mechanical vertical slice.
- Phase 4: GraphX Skill, Codex Host Adapter behavior, bootstrap/bind/activate calls, and read-only Agent execution.
- Phase 5: canonical workspace observation implementation, mutation leases, settlement recovery, and mutation resolution behavior.
- Phase 6: fault-injection matrix, recovery handbook, reference workflows, and release packaging.
