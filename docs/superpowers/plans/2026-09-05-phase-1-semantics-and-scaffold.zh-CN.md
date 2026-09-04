# GraphX Phase 1 语义冻结与工程骨架实施计划

> **供执行本计划的智能体使用：** 必须使用子技能 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项实施本计划。各步骤使用复选框（`- [ ]`）跟踪进度。

**目标：** 交付 `plan.md` 的 Phase 1：建立 Python 3.12 工程骨架并强制执行依赖边界，提供严格且不可变的领域/配置模型、封闭的 v1 wire Schema、canonicalization golden vectors，以及可执行的拒绝路径测试。

**架构：** 按依赖方向由内向外施工。`protocol/` 只拥有与 GraphX 各层无关的 wire DTO；`core/` 拥有不可变、已验证的领域/配置对象和 canonicalization 规则；Inbound Workflow Adapter 是 JSON 映射为领域对象的唯一入口；两个可执行入口保持相互独立。Phase 1 只定义数据形状和边界校验；编译、调度、转换决策、SQLite、MCP 服务和 Host 执行从后续阶段开始。

**技术栈：** Python 3.12、Pydantic v2 strict models、Pyright strict、Ruff、pytest，以及标准库 `json`、`hashlib`、`dataclasses`、`enum`、`typing`、`unicodedata`。

**规格依据：** [`plan.md`](../../../plan.md)，重点包括第 1.2、1.3、3.4、4.2–4.7、5.1、6、8、10、11.1、13 节 Phase 1，以及第 14.1、14.7、14.8 节。

## 全局约束

- Python 版本遵循第 10.1 节规定的产品下限：Python 3.12。
- 生产代码的参数和返回值必须完整标注，并通过 Pyright strict。
- 生产代码不得使用 `Any`、`dict[str, Any]`、把 `cast()` 当作校验、无说明的 `type: ignore`、`eval`、`exec`、monkey patch、动态 Runner 导入、pickle，或通过 `setattr()` 动态修改状态。
- 运行时边界必须拒绝未知字段、不支持的版本/枚举、重复 JSON key、非 NFC 字符串、NUL、越界整数、超过限制的深度/数量/字节大小，以及非法 tagged union 字段组合。
- `WorkflowConfig`、冻结的 `WorkflowIR` 和 `RunState` 必须保持为三种独立类型。Phase 1 定义前者和完整的 RunState aggregate 形状；Phase 2 实现合法 IR 的唯一构造路径。
- `protocol/` 不导入任何 GraphX 层；`core/` 不导入 `application/` 或 `adapters/`；`application/` 不导入具体 Adapter；`adapters/host/` 只能导入 `protocol/`、外部包和标准库。
- 只有 `adapters/store/sqlite/` 可以导入 `sqlite3`、打开数据库连接或执行 SQL。Phase 1 不包含 SQLite 实现。
- 只有 `application/state_committer.py` 最终可以提交 NodeState 或 RunState 变化。Phase 1 不定义修改状态的 Service。
- Canonical profile 固定为 `graphx-canonical-json-v1`；digest 为 `domain || 0x00 || canonical_bytes` 的小写 SHA-256。
- External node 只接受 `none` 和 `workspaceMutation` 两种 side effect；Phase 1 对两者建模，但不派发任何一种。
- 测试和名称应在适用处引用对应 requirement ID 或章节：CTRL-01..03、STATE-01、TASK-01..02、SCHED-01、MUT-01..03、RESULT-01、IDEM-01、OUTCOME-01、COND-01、BOUNDARY-01、EXT-01、OP-01、REV-01、AUTH-01、CANON-01。
- 每个任务都必须以该任务的聚焦 pytest 目标以及当时适用的仓库门禁结束。

---

## 文件职责图

| 文件 | 职责 |
|---|---|
| `pyproject.toml` | 包元数据、Python 版本下限、console 入口，以及严格的 Pyright/Ruff/pytest 配置。 |
| `src/graphx/bootstrap.py` | 仅作为 Service 组合入口；Phase 1 提供可导入的空实现，且不得导入 Host。 |
| `src/graphx/adapters/host/main.py` | 独立 Host 入口；Phase 1 提供可导入的空实现，且不得导入 Core/Application。 |
| `src/graphx/protocol/common_v1.py` | 严格 wire 基类、有界标量别名、不透明 wire identity/digest 字符串和安全 diagnostics 原语。 |
| `src/graphx/protocol/workflow_v1.py` | 封闭 Workflow Config v1 DTO：node variants、ValueSchema、ValueExpr、ConditionExpr、ProcessSpec、policy 和 revision policy。 |
| `src/graphx/protocol/execution_v1.py` | 封闭 execution DTO：dispatch、completion、Host observation、result、revision、evidence、handle 和 mutation resolution。 |
| `src/graphx/protocol/mcp_v1.py` | 版本化 MCP request/response DTO、NextDecision、inspect summary、error union 和 retry directive。 |
| `src/graphx/core/config/models.py` | 冻结且已验证的 Config-domain dataclass，以及强类型 workflow/node/name。 |
| `src/graphx/core/ir/models.py` | 仅定义冻结 IR 类型；构造 token 对 Phase 2 Compiler 保持私有。 |
| `src/graphx/core/ir/canonicalization.py` | 类型化 canonical JSON 序列化和按 domain 隔离的哈希。 |
| `src/graphx/core/runtime/models.py` | 枚举、强 ID、冻结 record、tagged ownership 和完整不可变 RunState aggregate。 |
| `src/graphx/adapters/inbound/workflow/loader.py` | UTF-8 JSON 解析、重复 key 拒绝和 Pydantic wire 校验。 |
| `src/graphx/adapters/inbound/workflow/mapper.py` | 显式把 wire DTO 映射为冻结 Config-domain 对象；不做语义编译。 |
| `src/graphx/adapters/inbound/mcp/authorization.py` | 针对 transport 创建的 principal 执行纯、封闭的 Controller/Host operation allowlist。 |
| `tests/unit/architecture/test_import_boundaries.py` | 基于 AST 的依赖边界和 `sqlite3` 所有权守卫。 |
| `tests/unit/protocol/test_workflow_v1.py` | Workflow closed-schema 接受/拒绝矩阵。 |
| `tests/unit/protocol/test_execution_v1.py` | Execution DTO identity、tag、字段和大小矩阵。 |
| `tests/unit/protocol/test_mcp_v1.py` | Envelope、principal 字段排除、request/response、error 和脱敏矩阵。 |
| `tests/unit/core/test_canonicalization.py` | Canonical bytes、domain separation、边界和 golden vector。 |
| `tests/unit/core/test_runtime_models.py` | 冻结 aggregate、枚举、tagged ownership 和 RunStatus/WorkflowOutcome 组合测试。 |
| `tests/unit/adapters/test_workflow_loader.py` | 原始 JSON 的重复/Unicode/NUL/版本拒绝和 mapping 测试。 |
| `tests/unit/adapters/test_mcp_authorization.py` | 封闭的 principal/operation 权限矩阵。 |
| `tests/fixtures/canonicalization_v1.json` | 已签入的 canonicalization 输入、bytes、domain 和预期 digest。 |

---

### 任务 1：建立 Python 包骨架并强制执行导入边界

**文件：**

- 新建：`pyproject.toml`
- 新建：`src/graphx/__init__.py`
- 新建：第 10.4 节列出的每个目录对应的 `__init__.py`
- 新建：`src/graphx/bootstrap.py`
- 新建：`src/graphx/adapters/host/main.py`
- 新建：`tests/unit/architecture/test_import_boundaries.py`

**接口：**

- 产出 console 入口：`graphx-service = graphx.bootstrap:main` 和 `graphx-host = graphx.adapters.host.main:main`。
- 两个入口模块都产出 `main() -> None`。
- 产出永久架构门禁：`test_layer_imports_follow_plan_10_4()` 和 `test_only_sqlite_adapter_imports_sqlite3()`。

- [ ] **步骤 1：先编写失败的架构测试**

```python
def test_layer_imports_follow_plan_10_4() -> None:
    violations = collect_graphx_import_violations(SRC_ROOT)
    assert violations == []


def test_only_sqlite_adapter_imports_sqlite3() -> None:
    offenders = collect_sqlite3_importers(SRC_ROOT)
    assert offenders <= {Path("graphx/adapters/store/sqlite")}
```

AST walker 必须检查 `Import` 和 `ImportFrom`；必须拒绝 protocol 导入 GraphX 层、core 导入外层、application 导入 adapter、Host 导入 Core/Application/inbound/store，以及 SQLite adapter 子树之外的 `sqlite3` 导入。

- [ ] **步骤 2：运行架构测试，确认因包/配置尚不存在而失败**

运行：`python3.12 -m pytest tests/unit/architecture/test_import_boundaries.py -q`

预期：FAIL，因为包骨架和 collector 尚不存在。

- [ ] **步骤 3：添加项目配置和两个独立入口**

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

两个 `main()` 在 Phase 1 中都只返回 `None`，不做组合或外部工作。

- [ ] **步骤 4：实现 AST import-boundary collector 并运行测试**

运行：`python3.12 -m pytest tests/unit/architecture/test_import_boundaries.py -q`

预期：PASS；其中必须包含能证明每条规则确实会失败的合成 forbidden-import fixture。

- [ ] **步骤 5：运行初始静态门禁**

运行：`python3.12 -m ruff check . && python3.12 -m ruff format --check . && python3.12 -m pyright`

预期：所有命令退出码为 0。

- [ ] **步骤 6：提交可独立评审的工程骨架**

```bash
git add pyproject.toml src tests/unit/architecture
git commit -m "build: establish GraphX package boundaries"
```

---

### 任务 2：添加强类型原语和 Canonical JSON v1

**文件：**

- 新建：`src/graphx/protocol/common_v1.py`
- 新建：`src/graphx/core/ir/canonicalization.py`
- 新建：`tests/unit/core/test_canonicalization.py`
- 新建：`tests/fixtures/canonicalization_v1.json`

**接口：**

- `protocol/common_v1.py` 产出：`StrictWireModel`、`WireVersion`、`DigestHexText`、`SafeDiagnosticText` 和已验证的不透明 wire identity 字符串。
- 产出递归 `CanonicalValue`：只允许 `None | bool | signed-64-bit int | NFC str | tuple[CanonicalValue, ...] | Mapping[str, CanonicalValue]`。
- `core/ir/canonicalization.py` 产出领域类型 `DigestHex`、`CanonicalizationProfileId` 和 `DigestDomain`；Core 不导入 wire DTO。
- 产出 `canonical_json_bytes(value: CanonicalValue) -> bytes`。
- 产出 `domain_digest(domain: DigestDomain, value: CanonicalValue) -> DigestHex`。
- 产出封闭的 `DigestDomain` enum：`graphx-ir-v1`、`graphx-contract-v1`、`graphx-request-v1`、`graphx-response-v1`、`graphx-revision-v1`、`graphx-workspace-identity-v1`。

- [ ] **步骤 1：先编写失败的 golden-vector 测试**

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

增加以下拒绝用例：float、超出 signed 64-bit 范围的 integer、非 NFC 字符串、NUL、decode 时出现重复 mapping key，以及不支持的 digest domain。

- [ ] **步骤 2：运行聚焦测试，确认缺少 symbol 导致失败**

运行：`python3.12 -m pytest tests/unit/core/test_canonicalization.py -q`

预期：因缺少 `canonical_json_bytes` 和 `domain_digest` 而 FAIL。

- [ ] **步骤 3：实现不使用无类型容器的 canonicalization**

```python
def domain_digest(domain: DigestDomain, value: CanonicalValue) -> DigestHex:
    payload = domain.value.encode("ascii") + b"\x00" + canonical_json_bytes(value)
    return DigestHex(hashlib.sha256(payload).hexdigest())
```

Serializer 必须输出无 BOM、无额外空白的 UTF-8；按 UTF-8 bytes 排序 object key；保持 array 顺序；精确输出 JSON boolean/null；递归验证 NFC/NUL；不得接受 float。

- [ ] **步骤 4：签入独立 fixture**

`tests/fixtures/canonicalization_v1.json` 必须包含字面输入、以 hex 表示的 canonical UTF-8 bytes、digest domain 和预期小写 digest。测试先把 fixture 读取为 `object`，校验为严格 fixture model，再比较运行时输出。

- [ ] **步骤 5：运行聚焦测试和静态门禁**

运行：`python3.12 -m pytest tests/unit/core/test_canonicalization.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

预期：所有命令退出码为 0。

- [ ] **步骤 6：提交 canonicalization**

```bash
git add src/graphx/protocol/common_v1.py src/graphx/core/ir/canonicalization.py tests
git commit -m "feat: freeze canonical JSON v1"
```

---

### 任务 3：定义封闭的 Workflow Config v1 Wire Schema

**文件：**

- 新建：`src/graphx/protocol/workflow_v1.py`
- 新建：`tests/unit/protocol/test_workflow_v1.py`

**接口：**

- 产出 node union：`AgentNodeV1 | CommandNodeV1 | VerifierNodeV1 | GateNodeV1 | TerminalNodeV1`，以 `type` 作为 discriminator。
- 产出 ValueSchema union：boolean、integer、有界 string、有界 array、封闭 object、process result、verification evidence。
- 产出 ValueExpr union：`FromExprV1 | LiteralExprV1`，必须恰好包含一个 tag。
- 产出 ConditionExpr union：`Eq | Ne | Lt | Le | Gt | Ge | Not | All | Any`，必须恰好包含一个 operator。
- 产出 `ProcessSpecV1`、`RetryPolicyV1`、`TimeoutPolicyV1`、`SettlementRecoveryPolicyV1`、`CanonicalTreeRevisionPolicyV1`、`WorkflowV1`、`WorkflowConfigV1`。
- 所有 object 继承 `StrictWireModel`，配置为 `extra="forbid"`、strict values、frozen instances，且 alias 与 JSON contract 一致。

- [ ] **步骤 1：编写 node 字段矩阵测试**

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

补充精确边界用例：node 数量 1024/1025、ID regex 和 64-byte 上限、task byte length、32 条 acceptance criteria、argv 数量/总字节数、exit code、retry 1..10、recovery 1..5、timeout 1..86400，以及必须成对出现的 `settlesMutation`/`settlementRecovery`。

- [ ] **步骤 2：编写 ValueSchema 和 ConditionExpr 深度/tag 测试**

覆盖：深度 16/17、object property 128/129、`maxItems` 10000/10001、string 上限 1 MiB、禁止 float/null/bytes、重复集合、不同类型 comparison operand、`all` 的 0/65 个 operand，以及 condition object 包含多个 operator。

- [ ] **步骤 3：运行测试，确认 schema symbol 尚不存在**

运行：`python3.12 -m pytest tests/unit/protocol/test_workflow_v1.py -q`

预期：导入 `WorkflowConfigV1` 时 FAIL。

- [ ] **步骤 4：实现严格的 discriminated models 和局部 validator**

```python
class StrictWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, populate_by_name=False)


class WorkflowConfigV1(StrictWireModel):
    version: Literal[1]
    workflow: WorkflowV1
```

Validator 按 UTF-8 bytes 而不是 Python 字符数计数，要求 NFC，拒绝 NUL 和重复项，并执行各 node type 的 required/forbidden 字段组合。此处不检查 graph cycle、reference、reachability、推导 dependency，或依赖上游 output 才能确定的 condition operand 类型；这些属于 Phase 2 Compiler。

- [ ] **步骤 5：运行 schema 和静态门禁**

运行：`python3.12 -m pytest tests/unit/protocol/test_workflow_v1.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

预期：所有命令退出码为 0。

- [ ] **步骤 6：提交 Config wire Schema**

```bash
git add src/graphx/protocol/workflow_v1.py tests/unit/protocol/test_workflow_v1.py
git commit -m "feat: add closed workflow config v1 schema"
```

---

### 任务 4：添加原始 Workflow 加载和显式 Config-domain 映射

**文件：**

- 新建：`src/graphx/core/config/models.py`
- 新建：`src/graphx/adapters/inbound/workflow/loader.py`
- 新建：`src/graphx/adapters/inbound/workflow/mapper.py`
- 新建：`tests/unit/adapters/test_workflow_loader.py`

**接口：**

- 产出 `load_workflow_json(payload: bytes) -> WorkflowConfigV1`。
- 产出 `map_workflow_config(dto: WorkflowConfigV1) -> WorkflowConfig`。
- 产出冻结的 Config-domain node/value/condition dataclass，以及 `WorkflowId`、`NodeId`、`InputName`、`OutputName`。
- 不产出 `WorkflowIR`；只有 Phase 2 Compiler 可以构造它。

- [ ] **步骤 1：先编写失败的原始边界测试**

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

还必须在 mapping 之前拒绝无效 UTF-8、BOM、NUL、尾随 JSON、未知版本和未知字段。

- [ ] **步骤 2：运行聚焦测试，确认缺少 loader/mapping 而失败**

运行：`python3.12 -m pytest tests/unit/adapters/test_workflow_loader.py -q`

预期：因缺少 `load_workflow_json` 而 FAIL。

- [ ] **步骤 3：实现类型化解析和显式 mapping**

```python
def load_workflow_json(payload: bytes) -> WorkflowConfigV1:
    text = decode_utf8_without_bom(payload)
    decoded: object = DuplicateRejectingJsonDecoder().decode(text)
    return WorkflowConfigV1.model_validate(decoded)


def map_workflow_config(dto: WorkflowConfigV1) -> WorkflowConfig:
    return WorkflowConfig(version=1, workflow=map_workflow(dto.workflow))
```

Mapping 必须对每个封闭 union 使用显式、穷尽的 `match` 和 `assert_never()`。Config-domain collection 转换为 tuple 和不可变 mapping。不得保留 Pydantic DTO 或调用方拥有的可变 list/dict。

- [ ] **步骤 4：证明 DTO 的后续变化不会影响领域对象**

测试从可变原始输入构造并 mapping，然后修改原始输入，断言冻结领域对象及其 canonical form 不变。测试还必须断言字段赋值会触发 `FrozenInstanceError` 或 Pydantic frozen-instance error。

- [ ] **步骤 5：运行聚焦测试和静态门禁**

运行：`python3.12 -m pytest tests/unit/adapters/test_workflow_loader.py tests/unit/protocol/test_workflow_v1.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

预期：所有命令退出码为 0。

- [ ] **步骤 6：提交可信 Config 边界**

```bash
git add src/graphx/core/config src/graphx/adapters/inbound/workflow tests/unit/adapters
git commit -m "feat: validate and map workflow config"
```

---

### 任务 5：定义不可变 IR 声明和完整 RunState Aggregate

**文件：**

- 新建：`src/graphx/core/ir/models.py`
- 新建：`src/graphx/core/runtime/models.py`
- 新建：`tests/unit/core/test_runtime_models.py`

**接口：**

- 为 Run、reservation、attempt、mechanical attempt/execution、activation、external operation、settlement check、lease、binding、observation、request、contract、revision、evidence、transaction、principal、host、workspace、thread identity 产出强 ID/value object。
- 产出与第 6、8 节精确一致的枚举：`NodeState`、`RunStatus`、`WorkflowOutcome`、`HostKind`、`SideEffectClass`、`ResultOutcome`、`VerificationStatus`、`OperationKind`、`OperationState`、`OperationTerminalDisposition`、`ExecutionDisposition`、`RetryDirective`、`MutationResolutionDecision`、`ConditionDecisionKind`。
- 为 reservation、agent attempt、mechanical attempt、settled mutation、settlement-check owner 产出冻结 tagged ownership record。
- 产出冻结 record：`RunControllerBinding`、`RunHostBinding`、`CancellationIntent`、`DispatchReservation`、`AgentAttempt`、`ExecutionHandle`、`TaskActivation`、`MechanicalAttempt`、`MechanicalExecutionHandle`、`SettlementCheckExecution`、`ExternalOperation`、`ExternalOperationObservation`、`WorkspaceRevision`、`VerificationEvidence`、`ActiveExecutionSlot`、`MutationLease`、`AcceptedWorkspaceBaseline`、`NodeRuntimeState`、`NodeOutput`、`RunState`。
- 产出没有公开合法构造器的 IR 声明类型。`WorkflowIR` 是 frozen，只有传入模块私有 `_CompilerToken` 才能构造；任务 8 验证外部构造会被拒绝。Phase 2 的 `core/ir/compiler.py` 将成为该 token 唯一的生产代码 importer。

- [ ] **步骤 1：编写 enum 和 frozen-record 测试**

```python
def test_state_01_runtime_records_are_frozen() -> None:
    reservation = make_reservation()
    with pytest.raises(FrozenInstanceError):
        reservation.node_id = NodeId("other")  # type: ignore[misc]


def test_outcome_01_rejects_success_without_success_outcome() -> None:
    with pytest.raises(InvalidRunAggregate):
        build_run_state(status=RunStatus.SUCCEEDED, outcome=None)
```

这里唯一的 test-only ignore 有明确说明：该行有意执行非法赋值；生产代码仍然不允许 ignore。

- [ ] **步骤 2：添加 aggregate 组合矩阵**

只接受以下组合：`succeeded + success`；failure terminal 的 `failed + failure`；operational `failed + None`；以及 `validated/running/blocked/ambiguous/cancelled + None`。拒绝 terminal status 与 active slot、unresolved operation 或 mutation lease 共存；拒绝稳定 aggregate 含 `NodeState.VERIFYING`；拒绝 attempt 缺少必需的不可变 handle；拒绝单个 AgentAttempt 存在多个 activation。

- [ ] **步骤 3：运行聚焦测试，确认 model 尚不存在**

运行：`python3.12 -m pytest tests/unit/core/test_runtime_models.py -q`

预期：导入 `RunState` 和 runtime enum 时 FAIL。

- [ ] **步骤 4：实现冻结 record 和唯一 validated aggregate constructor**

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

构造时把 mapping 复制为 immutable proxy/tuple，并调用 `validate_run_state_composition(state)`。该 validator 只检查结构组合；合法转换仍属于 Phase 2。

- [ ] **步骤 5：验证 strict typing 和导入方向**

运行：`python3.12 -m pytest tests/unit/core/test_runtime_models.py tests/unit/architecture/test_import_boundaries.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

预期：所有命令退出码为 0。

- [ ] **步骤 6：提交领域模型层**

```bash
git add src/graphx/core/ir/models.py src/graphx/core/runtime/models.py tests/unit/core
git commit -m "feat: define immutable GraphX runtime aggregate"
```

---

### 任务 6：定义 Execution、Result、Revision 和 Evidence Wire Schema

**文件：**

- 新建：`src/graphx/protocol/execution_v1.py`
- 新建：`tests/unit/protocol/test_execution_v1.py`

**接口：**

- 产出 `AgentNodeDispatchV1`、`MechanicalNodeDispatchV1`、`TaskContractV1`、`AgentCompletionPayloadV1`、`HostObservationEnvelopeV1`、`AgentNodeResultV1`、`MechanicalNodeResultV1`、`WorkspaceRevisionV1`、`VerificationEvidenceV1`、`ProcessResultV1`、`DispatchReservationV1`、handle DTO、operation observation DTO、`MutationResolutionV1`。
- 产出 discriminated `NodeResultV1 = AgentNodeResultV1 | MechanicalNodeResultV1`。
- 产出第 8.6 节规定的封闭 `ResultOutcome` 字段矩阵。
- 公开 DTO 不包含调用方可提供的 authenticated Host ID；Host ID 只存在于内部 transport context/domain observation。

- [ ] **步骤 1：编写 result-outcome 字段矩阵测试**

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

覆盖全部四种 outcome、agent/mechanical tag、禁止 gate/terminal result、1 MiB result payload、64 KiB diagnostics、1 MiB stdout/stderr evidence、匹配的 identity field，以及 NodeResult 禁止 `running/unknown`。

- [ ] **步骤 2：编写 evidence 与 observation 分离测试**

AgentCompletionPayload 必须拒绝 provider identity、execution disposition、terminal/quiescence evidence、settled revision、Host observation identity/digest 和 authenticated Host ID。VerificationEvidence 必须要求 run/node/attempt/execution/operation identity、check ID/hash、evidence subject revision、status、tagged check result 和 evidence digest。

- [ ] **步骤 3：运行聚焦测试，确认 DTO 尚不存在**

运行：`python3.12 -m pytest tests/unit/protocol/test_execution_v1.py -q`

预期：导入 `NodeResultV1Adapter` 时 FAIL。

- [ ] **步骤 4：实现封闭 execution union**

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

使用 model validator 强制执行每种 outcome 的 required/forbidden 字段和 canonical byte-size 上限。此处不对 RunState 执行 identity/revision 等值判断；Phase 2 的 pure result validation 负责语义匹配。

- [ ] **步骤 5：运行聚焦测试和静态门禁**

运行：`python3.12 -m pytest tests/unit/protocol/test_execution_v1.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

预期：所有命令退出码为 0。

- [ ] **步骤 6：提交 execution DTO**

```bash
git add src/graphx/protocol/execution_v1.py tests/unit/protocol/test_execution_v1.py
git commit -m "feat: add execution protocol v1"
```

---

### 任务 7：定义 MCP Envelope、Operation DTO、Principal 和封闭 Error

**文件：**

- 新建：`src/graphx/protocol/mcp_v1.py`
- 新建：`src/graphx/adapters/inbound/mcp/authorization.py`
- 新建：`tests/unit/protocol/test_mcp_v1.py`
- 新建：`tests/unit/adapters/test_mcp_authorization.py`

**接口：**

- 使用 `core/runtime/models.py` 中的不可变领域 principal：`ControllerPrincipal` 和 `HostPrincipal`；它们由 transport 创建，绝不作为 public request JSON 字段。
- 为第 11 节全部十四个操作产出 request DTO：validate workflow、record Host observation、start run、next、bind task、activate task、activate mechanical、submit result、fail attempt、reconcile external operation、resolve mutation、inspect run、resume run、cancel run。
- 每个 mutating request 携带 `wireVersion=1`、UUID `requestId`、非空 `idempotencyKey`；存在 Run 时还必须携带 `runId` 和 `expectedRunVersion`。
- 产出 `ResponseEnvelopeV1`、`NextDecisionV1`、inspect summary/cursor、`ErrorBodyV1`、`ErrorCodeV1`、`RetryDirectiveV1`。

- [ ] **步骤 1：先编写失败的 envelope 和 principal-field 排除测试**

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

添加覆盖十四个操作及第 11.1 节 Controller/Host allowlist 的表。Schema 测试验证字段形状；纯函数 `authorize(principal, operation) -> AuthorizationDecision` 测试验证封闭权限矩阵，不执行 transport I/O。

- [ ] **步骤 2：编写封闭 error 和脱敏测试**

断言 error code 恰好为：`invalid_request`、`unsupported_version`、`unauthenticated`、`forbidden`、`not_found`、`conflict`、`stale`、`not_ready`、`run_not_runnable`、`reconciliation_required`、`capability_unavailable`、`integrity_failure`、`internal_failure`。断言 retry directive 恰好为：`do_not_retry`、`retry_same_request`、`reconcile`、`user_action`。拒绝 raw Contract、token、credential、database path、absolute workspace path 和形似 traceback 的 details。

- [ ] **步骤 3：运行聚焦测试，确认 DTO 尚不存在**

运行：`python3.12 -m pytest tests/unit/protocol/test_mcp_v1.py -q`

预期：导入 `ResponseEnvelopeV1` 时 FAIL。

- [ ] **步骤 4：实现全部 operation DTO 和穷尽的 inbound authorization**

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

该函数位于 `adapters/inbound/mcp/authorization.py`，不得放入 `protocol/`；protocol 必须保持为纯数据定义。Response envelope 的 stable receipt-body digest 排除 `requestId` 和 `replayed`。Inspect DTO 只暴露 run version、IR digest、status/outcome、node/operation/lease summary 和 opaque cursor；不得暴露 binding token、raw Contract bytes、Host credential、database 信息或 raw provider evidence。

- [ ] **步骤 5：运行聚焦测试和静态门禁**

运行：`python3.12 -m pytest tests/unit/protocol/test_mcp_v1.py tests/unit/adapters/test_mcp_authorization.py -q && python3.12 -m pyright && python3.12 -m ruff check .`

预期：所有命令退出码为 0。

- [ ] **步骤 6：提交 MCP DTO 和权限类型**

```bash
git add src/graphx/protocol/mcp_v1.py src/graphx/adapters/inbound/mcp/authorization.py tests/unit/protocol/test_mcp_v1.py tests/unit/adapters/test_mcp_authorization.py
git commit -m "feat: define MCP protocol v1"
```

---

### 任务 8：锁定 IR 构造、Model Ownership 和阶段边界

**文件：**

- 修改：`src/graphx/core/ir/models.py`
- 修改：`src/graphx/core/runtime/models.py`
- 修改：`tests/unit/core/test_runtime_models.py`
- 修改：`tests/unit/architecture/test_import_boundaries.py`
- 新建：`tests/unit/core/test_ir_construction.py`

**接口：**

- 产出无法通过 public constructor 实例化的 `WorkflowIR` 声明。
- 产出穷尽 owner union：`StateOwner = ReservationOwner | AgentAttemptOwner | MechanicalAttemptOwner | SettledMutationOwner | SettlementCheckOwner`。
- 产出由测试执行的显式 model-to-authority inventory：Config input、IR snapshot、RunState aggregate、Host observation、external provider identity 必须保持相互独立。

- [ ] **步骤 1：先编写失败的构造和 ownership 测试**

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

- [ ] **步骤 2：为全部 authority boundary 添加负向导入测试**

Synthetic source tree 必须证明 guard 会拒绝：protocol 导入 Core、Core 导入 Application、Application 导入 SQLite adapter、Host 导入 Core、Inbound MCP 直接导入 SQLite，以及 `bootstrap.py` 导入 Host。

- [ ] **步骤 3：实现私有 IR 构造和穷尽 ownership helper**

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

`_COMPILER_TOKEN` 不从 `core.ir.models` 导出；架构测试只允许 Phase 2 的 `core/ir/compiler.py` 在生产代码中导入并传递它。

- [ ] **步骤 4：运行 model 和 architecture suite**

运行：`python3.12 -m pytest tests/unit/core/test_ir_construction.py tests/unit/core/test_runtime_models.py tests/unit/architecture/test_import_boundaries.py -q`

预期：所有命令退出码为 0。

- [ ] **步骤 5：提交 Phase 1 authority guard**

```bash
git add src/graphx/core tests/unit/core tests/unit/architecture
git commit -m "test: enforce GraphX authority boundaries"
```

---

### 任务 9：运行 Phase 1 验收矩阵并冻结基线

**文件：**

- 修改：`README.md`
- 修改：`README.zh-CN.md`
- 新建：`tests/unit/test_phase1_acceptance.py`

**接口：**

- 产出一个 Phase 1 smoke suite：导入所有 public model/adapter entry point，并为每个 closed union 执行一个接受 payload 和一个拒绝 payload。
- 产出 README 状态链接，指向 `plan.md` Phase 1，但不重新定义语义规则。

- [ ] **步骤 1：编写 Phase 1 验收 smoke test**

```python
def test_phase_1_public_surface_is_closed_and_importable() -> None:
    assert WorkflowConfigV1.model_json_schema()["additionalProperties"] is False
    assert set(NodeState) == EXPECTED_NODE_STATES
    assert set(RunStatus) == EXPECTED_RUN_STATUSES
    assert CANONICALIZATION_PROFILE_ID == "graphx-canonical-json-v1"
```

该 suite 还要检查：所有 public Pydantic model 都 frozen 且 extra-forbid；每个 enum 都是封闭集合；所有 aggregate dataclass 都 frozen+slotted；每个 wire version 都是 1；public request 不包含 `hostId`/principal 字段；两个 console target 能够独立导入。

- [ ] **步骤 2：运行全部测试并捕获首个失败**

运行：`python3.12 -m pytest -q`

预期：如果任务 1–8 已完成则 PASS；任何 failure 都必须先在其所属任务的 module 和 focused test 中修复，然后再重跑完整 suite。

- [ ] **步骤 3：运行完整发布门禁**

运行：`python3.12 -m pyright && python3.12 -m ruff check . && python3.12 -m ruff format --check . && python3.12 -m pytest`

预期：四条命令全部退出码为 0。

- [ ] **步骤 4：验证 Phase 1 范围排除项**

运行：`rg -n "sqlite3|class .*Scheduler|def compile_|mcp\.server|subprocess|create_thread" src/graphx -g '*.py'`

预期：Phase 1 生产模块不得出现 `sqlite3`、Scheduler、Compiler 实现、MCP server startup、subprocess execution 或 Codex task creation。只允许在注释或 protocol declaration 中命中相应名称，并由 reviewer 人工确认。

- [ ] **步骤 5：更新状态文档，但不复制权威定义**

README 只说明 Phase 1 已实现，并链接到 `plan.md` 第 13 节和 Phase 1 acceptance test；不得复制 state-transition table、Schema bounds 或 authority rule。

- [ ] **步骤 6：提交 Phase 1 基线**

```bash
git add README.md README.zh-CN.md tests/unit/test_phase1_acceptance.py
git commit -m "docs: mark GraphX phase 1 baseline"
```

---

## 评审检查点

1. **任务 1 后：** 在开始任何 model 工作前，批准 packaging 和依赖方向。
2. **任务 4 后：** 在 Runtime/IR 类型开始依赖 Config 前，批准完整 Config 边界。
3. **任务 7 后：** 对照第 8、11.1 节检查每个 public wire DTO；拒绝泄露 Host identity 或开放 union。
4. **任务 8 后：** 确认代码已经表达 authority separation，但没有实现 Phase 2 transition。
5. **任务 9 后：** 只有四项发布门禁均能在 clean environment 通过，才接受 Phase 1。

## Requirement 覆盖审计

| Phase 1 义务 | 负责的任务 |
|---|---|
| 第 10 节 package skeleton、双入口、依赖守卫 | 任务 1、8 |
| 严格分离 Config、immutable IR、完整 RunState model | 任务 4、5、8 |
| 第 4.4–4.6 节 closed Config/Value/Condition/policy bounds | 任务 3、4 |
| 第 4.7 节 canonical profile、domain digest、golden vector | 任务 2 |
| NodeState/RunStatus/outcome 和稳定 aggregate composition | 任务 5 |
| Dispatch、attempt、handle、activation、operation、settlement、ownership、resolution type | 任务 5、6、8 |
| NodeDispatch、Agent/Host payload 分离、NodeResult、revision、evidence wire type | 任务 6 |
| MCP request/response、inspect、error、principal、permission matrix | 任务 7 |
| 拒绝 unknown field/version/enum 和缺失 isolation/authority prerequisite | 任务 1、3、6、7、9 |
| Phase 1 发布门禁和 Phase 2+ 排除 | 任务 9 |

## Phase 1 完成定义

- 第 10.4 节的所有 package directory 和两个入口都存在，且可以独立导入。
- 架构测试能够机械拒绝每种 forbidden dependency，以及 SQLite adapter 边界之外的任何 `sqlite3` 导入。
- Workflow Config v1、ValueSchema、ValueExpr、ConditionExpr、ProcessSpec、retry/timeout/recovery policy、RevisionPolicy 都是封闭的，并强制执行第 4.4–4.7 节的所有局部边界。
- Canonicalization golden vector 固定 bytes、profile、domain separation 和小写 SHA-256 digest。
- WorkflowConfig、WorkflowIR、RunState 相互独立；RunState 包含第 4.2 节列出的全部 aggregate member，并拒绝非法稳定组合。
- 所有 Phase 1 runtime record 都不可变；所有 state/identity/result/operation variant 都使用 enum 或 tagged union，而不是 bare string。
- NodeDispatch、Task Contract、AgentCompletionPayload、HostObservationEnvelope、NodeResult、WorkspaceRevision、VerificationEvidence、MCP envelope、inspect summary、error 都是版本化封闭 DTO。
- Public DTO 无法注入 HostId/principal authority；Agent payload 无法携带 Host-only observation；diagnostics 无法暴露 secret 或 private path。
- 不存在 Phase 2+ 行为：没有 compiler logic、scheduler、transition evaluator、StateCommitter、SQLite schema、MCP server、Host execution 或 mutation lease acquisition。
- `pyright`、`ruff check`、`ruff format --check`、`pytest` 全部通过。

## 明确推迟到后续阶段

- Phase 2：graph semantic validation、WorkflowIR 构造、canonical IR digest、condition evaluation、transition、ready calculation、deterministic scheduling。
- Phase 3：Store port、SQLite adapter/constraint/migration、StateCommitter、Query Service、MCP server、mechanical vertical slice。
- Phase 4：GraphX Skill、Codex Host Adapter 行为、bootstrap/bind/activate call、read-only Agent execution。
- Phase 5：canonical workspace observation 实现、mutation lease、settlement recovery、mutation resolution 行为。
- Phase 6：fault-injection matrix、recovery handbook、reference workflow、release packaging。
