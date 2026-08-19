# Polaris CodeGraph 新鲜度加固实施计划

> **供 Agent Worker 使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施本计划。所有步骤使用 checkbox（`- [ ]`）跟踪。

**目标：** 在不修改 CodeGraph 的前提下，让 Polaris 每次查询都自动争取一次增量同步后的最新图数据，并把已知过期或无法验证的数据明确标记为只能导航使用。

**架构：** 保留项目级 `polaris_codegraph_explore` 代理，把状态检查、至多一次自动增量同步、一次 explore、查询后复查和新鲜度 envelope 收敛在同一个有界窗口。`codegraph_adapter.py` 只负责外部 CLI 与响应框架兼容，`code_intelligence_proxy.py` 负责窗口编排，MCP 层不再暴露同步开关；新的 bundle v2 记录自动刷新策略，但耐久 record 继续使用 v3。

**技术栈：** Python 3.10+ 标准库（`hashlib`、`json`、`re`、`subprocess`、`unittest`）、JSON Schema、JSON-RPC 2.0/MCP stdio 协议 `2025-11-25`、Git。

**规格：** `docs/superpowers/specs/2026-08-19-codegraph-freshness-hardening-design.md`

## 全局约束

- 只修改 Polaris 仓库；`/Users/zero/Documents/work/ai/codegraph` 必须始终保持无修改。
- Polaris 协议/包版本从 `0.1.21` 精确升级到 `0.1.22`。
- Workflow 版本保持 `0.1.3`，不得改变节点、边、状态或 transition gate。
- Runtime 除 Python 标准库外不得增加依赖。
- pending changes 只允许触发一次 `codegraph sync`；任何路径都不得执行 `codegraph index`。
- `polaris_codegraph_explore` 不再接受 `sync_if_needed`，调用方不能跳过自动增量同步。
- 查询前状态无法验证但仓库身份安全时仍执行一次 explore，并返回 `UNKNOWN`。
- 仓库/worktree 身份不匹配或路径不安全时不执行 explore，也不交付图内容。
- 只有完整干净的有界窗口才能产生 `CURRENT_AT_CHECK`。
- `STALE` 和 `UNKNOWN` 都是 `NAVIGATION_ONLY`；`UNKNOWN` 必须明确写出 `TREAT_AS_STALE`。
- 新 runtime evidence 使用 bundle v2；升级中断时仍可读取 bundle v1。
- 新耐久 Code Intelligence record 继续使用 v3；已提交的 v1、v2、v3 record 不得重写。
- Validation 继续完全不调用 CodeGraph；没有安装 CodeGraph 时完整测试套件必须通过。

---

## 文件职责

- `scripts/internal/codegraph_adapter.py`：低层 status/sync/explore 调用、状态标准化、CodeGraph 响应框架分类。
- `scripts/internal/code_intelligence_proxy.py`：Polaris 阶段约束、自动增量同步、查询窗口、bundle v2、状态合并和 envelope。
- `scripts/code_intelligence_mcp.py`：只处理 MCP 生命周期、输入 schema 与 envelope-first 返回顺序。
- `scripts/internal/code_intelligence_protocol.py`：读取 bundle v1/v2、校验自动刷新策略、投影现有 record v3。
- `skills/code-intelligence/SKILL.md`：统一阶段行为；明确 UNKNOWN 继续查询但必须按过期处理。
- `skills/architecture-planning/SKILL.md`、`skills/implementation/SKILL.md`、`skills/documentation-sync/SKILL.md`、`skills/adversarial-review/SKILL.md`：各阶段只声明查询目的，不再声明同步策略。
- `templates/AGENTS.md`：vendored 项目共享行为边界。
- `README.md`、`README.zh-CN.md`、`docs/USAGE.md`、`plan.md`：用户与产品 Authority。
- `VERSION`、`pyproject.toml`、`templates/project.json`、`templates/task-sources/state.json`、`templates/task/state.json`：协议版本单一事实的各生成/模板表面。
- `workflow/migrations.json`、`scripts/internal/migration_protocol.py`：显式相邻 `0.1.21 → 0.1.22` 版本迁移，不改变 Workflow。
- `tests/test_codegraph.py`：适配器、代理、MCP、bundle、record、Skill 和可选真实 CLI 覆盖。
- `tests/test_core.py`：版本、vendoring、迁移和宿主配置覆盖。

---

### Task 1：让响应分类器适配当前 CodeGraph，同时忽略源码正文中的警告词

**Files:**
- Modify: `scripts/internal/codegraph_adapter.py:24-229`
- Test: `tests/test_codegraph.py:3530-3680`

**Interfaces:**
- Consumes: `classify_response(repo: Path, response: str, *, checked_at: str | None = None) -> dict[str, Any]`。
- Produces: 相同签名；返回的 `classification` 仍只允许 `NONE`、`PARTIAL_STALE`、`INDEX_STALE`、`NOT_VERIFIED`，不改变下游类型。

- [ ] **Step 1：为当前 CodeGraph 的 framing 写失败测试**

在 `CodeGraphTests` 中加入：

```python
def test_current_codegraph_freshness_framing_is_classified(self) -> None:
    samples = {
        "pending": (
            "⚠️ Some files referenced below were edited since the last index sync — "
            "their codegraph entries may be stale:\n"
            "  - src/a.py (edited 12ms ago, pending sync)\n"
            "For accurate content of those specific files, Read them directly. "
            "The rest of this response is fresh.\n",
            "PARTIAL_STALE",
        ),
        "indexing": (
            "⚠️ Some files referenced below were edited since the last index sync — "
            "their codegraph entries may be stale:\n"
            "  - src/a.py (edited 12ms ago, indexing in progress)\n"
            "For accurate content of those specific files, Read them directly. "
            "The rest of this response is fresh.\n",
            "PARTIAL_STALE",
        ),
        "disabled": (
            "⚠️ CodeGraph auto-sync is DISABLED — live file watching stopped, so the "
            "index is frozen and any file edited since then is stale here.\n",
            "INDEX_STALE",
        ),
        "drift": (
            "**`src/a.py`** — A(function) · ⚠ changed since last index sync — "
            "source below is current; the symbol list may be outdated\n",
            "PARTIAL_STALE",
        ),
        "worktree": (
            "⚠ CodeGraph results below come from a different git worktree "
            "(/tmp/main), not where you're working (/tmp/wt) — they may reflect "
            "another branch.\n",
            "INDEX_STALE",
        ),
    }
    for name, (response, expected) in samples.items():
        with self.subTest(name=name):
            self.assertEqual(
                self.classify_response(response)["classification"], expected
            )
```

- [ ] **Step 2：运行 framing 测试并确认 RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_current_codegraph_freshness_framing_is_classified -v`

Expected: pending/indexing/disabled/drift/worktree 中至少一个不等于期望状态。

- [ ] **Step 3：为源码正文误判写失败测试**

```python
def test_warning_words_inside_verbatim_source_do_not_change_freshness(self) -> None:
    response = (
        "**`src/a.py`** — A(function)\n\n"
        "```python\n"
        "def A():\n"
        "    warning = 'stale pending sync out-of-date ⚠'\n"
        "    return warning\n"
        "```\n"
    )
    self.assertEqual(
        self.classify_response(response)["classification"], "NONE"
    )
```

- [ ] **Step 4：运行源码正文测试并确认 RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_warning_words_inside_verbatim_source_do_not_change_freshness -v`

Expected: 当前全文 `_SUSPICIOUS_FRESHNESS_SIGNAL` 扫描返回 `NOT_VERIFIED`。

- [ ] **Step 5：实现 framing-aware 分类**

把旧版固定文案常量替换为当前 CodeGraph 兼容规则，并增加只返回代码围栏之外文本的帮助函数：

```python
_PARTIAL_BANNER_HEADER = (
    "⚠️ Some files referenced below were edited since the last index sync — "
    "their codegraph entries may be stale:\n"
)
_PARTIAL_BANNER_ROW = re.compile(
    r"^  - (?P<path>.+) \(edited [^\n()]+, "
    r"(?:pending sync|indexing in progress)\)$"
)
_DISABLED_BANNER_PREFIX = "⚠️ CodeGraph auto-sync is DISABLED —"
_WORKTREE_BANNER_PREFIX = "⚠ CodeGraph results below come from a different git worktree"
_DRIFTED_FILE_HEADER = re.compile(
    r"^\*\*`(?P<path>[^`]+)`\*\* — .*⚠ changed (?:since last index sync|on disk after the last index sync)"
)

def _framing_lines(response: str) -> list[str]:
    lines: list[str] = []
    inside_fence = False
    for line in response.splitlines():
        if line.startswith("```"):
            inside_fence = not inside_fence
            continue
        if not inside_fence:
            lines.append(line)
    return lines
```

处理顺序固定为：worktree/disabled 顶部提示 → partial 顶部列表 → drifted file header → 已识别尾部提示 → framing 位置的未知 warning-like 文本降级 `NOT_VERIFIED` → `NONE`。文件路径继续通过 `_response_file_point` 做仓库边界和 SHA-256 校验；无法安全拆分的项目级尾部提示生成 `INDEX_STALE + SEARCH_SOURCE`，不猜测文件名。

- [ ] **Step 6：运行适配器分类测试**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_current_codegraph_freshness_framing_is_classified tests.test_codegraph.CodeGraphTests.test_warning_words_inside_verbatim_source_do_not_change_freshness tests.test_codegraph.CodeGraphTests.test_response_banner_marks_only_named_files_stale tests.test_codegraph.CodeGraphTests.test_response_banner_rejects_unsafe_and_symlink_paths tests.test_codegraph.CodeGraphTests.test_response_banner_rejects_unsafe_windows_style_paths -v`

Expected: all PASS。

- [ ] **Step 7：提交 Task 1**

```bash
git add scripts/internal/codegraph_adapter.py tests/test_codegraph.py
git commit -m "fix: classify current CodeGraph freshness framing"
```

---

### Task 2：把自动增量同步、UNKNOWN 查询和 bundle v2 固化到代理契约

**Files:**
- Modify: `scripts/internal/code_intelligence_proxy.py:200-622`
- Modify: `scripts/code_intelligence_mcp.py:24-190`
- Modify: `scripts/internal/code_intelligence_protocol.py:1200-1360`
- Test: `tests/test_codegraph.py:320-1565`

**Interfaces:**
- Consumes: Task 1 的 `classify_response`，以及现有 `inspect_status`、`synchronize_observed_status`、`run_explore`。
- Produces: `execute_proxy_query(repo, task_id, stage, query_id, purpose, query, *, runner=subprocess.run) -> dict[str, Any]`，不再接受同步布尔值。
- Produces: bundle v2 顶层 `refresh_policy`，值固定为 `AUTO_INCREMENTAL_ON_PENDING`。
- Produces: MCP `polaris_codegraph_explore` 输入只包含 task/stage/query ID/purpose/query。

- [ ] **Step 1：写自动同步且无法绕过的失败测试**

```python
def test_proxy_automatically_syncs_pending_without_a_caller_switch(self) -> None:
    self.qualify_task()
    (self.repo / ".codegraph").mkdir()
    pending = json.loads(healthy_status(self.repo))
    pending["pendingChanges"]["modified"] = 1
    responses = [
        completed(json.dumps(pending)),
        completed("synced\n"),
        completed(healthy_status(self.repo)),
        completed("graph bytes\n"),
        completed(healthy_status(self.repo)),
    ]
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return responses.pop(0)

    proxy = self.proxy_module()
    with mock.patch(
        "internal.code_intelligence_proxy.shutil.which",
        return_value="/bin/codegraph",
    ):
        result = proxy.execute_proxy_query(
            self.repo, "TASK-0001", "PLANNING", "CIQ-001",
            "locate A", "symbol A", runner=runner,
        )

    self.assertEqual([item[1] for item in calls], [
        "status", "sync", "status", "explore", "status"
    ])
    self.assertEqual(result["bundle"]["bundle_version"], 2)
    self.assertEqual(result["bundle"]["refresh_policy"], {
        "mode": "AUTO_INCREMENTAL_ON_PENDING",
        "max_sync_attempts": 1,
        "full_rebuild": "USER_ONLY",
    })
```

- [ ] **Step 2：写 pre-status 无法验证但仍查询的失败测试**

```python
def test_proxy_queries_unknown_pre_status_and_treats_result_as_stale(self) -> None:
    self.qualify_task()
    (self.repo / ".codegraph").mkdir()
    responses = [
        completed("not-json\n"),
        completed("graph bytes\n"),
        completed(healthy_status(self.repo)),
    ]
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return responses.pop(0)

    with mock.patch(
        "internal.code_intelligence_proxy.shutil.which",
        return_value="/bin/codegraph",
    ):
        result = self.proxy_module().execute_proxy_query(
            self.repo, "TASK-0001", "PLANNING", "CIQ-001",
            "locate A", "symbol A", runner=runner,
        )

    self.assertEqual([item[1] for item in calls], ["status", "explore", "status"])
    self.assertEqual(result["response"], "graph bytes\n")
    self.assertEqual(result["bundle"]["delivery"]["state"], "UNKNOWN")
    self.assertIn("freshness: TREAT_AS_STALE", result["envelope"])
```

- [ ] **Step 3：写身份不匹配时禁止查询的失败测试**

```python
def test_proxy_does_not_query_a_different_project_index(self) -> None:
    self.qualify_task()
    (self.repo / ".codegraph").mkdir()
    wrong = json.loads(healthy_status(self.repo))
    wrong["projectPath"] = str(self.repo / "other-checkout")
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return completed(json.dumps(wrong))

    with mock.patch(
        "internal.code_intelligence_proxy.shutil.which",
        return_value="/bin/codegraph",
    ):
        result = self.proxy_module().execute_proxy_query(
            self.repo, "TASK-0001", "PLANNING", "CIQ-001",
            "locate A", "symbol A", runner=runner,
        )

    self.assertEqual([item[1] for item in calls], ["status"])
    self.assertIsNone(result["response"])
    self.assertEqual(result["bundle"]["delivery"]["state"], "UNKNOWN")
    self.assertEqual(result["bundle"]["delivery"]["reason"], "PROJECT_MISMATCH")
```

- [ ] **Step 4：运行三项代理测试并确认 RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_proxy_automatically_syncs_pending_without_a_caller_switch tests.test_codegraph.CodeGraphTests.test_proxy_queries_unknown_pre_status_and_treats_result_as_stale tests.test_codegraph.CodeGraphTests.test_proxy_does_not_query_a_different_project_index -v`

Expected: 旧签名、旧 early-return 或 bundle v1 至少导致一项失败。

- [ ] **Step 5：实现固定自动刷新策略和新代理签名**

在 `code_intelligence_proxy.py` 增加唯一策略常量：

```python
REFRESH_POLICY = {
    "mode": "AUTO_INCREMENTAL_ON_PENDING",
    "max_sync_attempts": 1,
    "full_rebuild": "USER_ONLY",
}

def execute_proxy_query(
    repo: Path,
    task_id: str,
    stage: str,
    query_id: str,
    purpose: str,
    query: str,
    *,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    """Execute one automatically refreshed, immutable CodeGraph query window."""
```

以上代码块只替换现有函数声明和 docstring；函数主体按本步骤后续规则原位修改，不新建第二个入口。删除对 `sync_if_needed` 的输入校验。`_bundle_base` 写 `bundle_version: 2` 和 `refresh_policy: dict(REFRESH_POLICY)`。只要 `pre_status.get("needs_sync")` 为真，就无条件调用一次 `synchronize_observed_status`。

把旧的 `effective_pre["status"] == "NOT_VERIFIED"` early return 拆成两个分支，并使用一个精确判断函数：

```python
def _pre_status_blocks_query(observation: dict[str, Any]) -> bool:
    if any(
        point.get("reason") == "WORKTREE_MISMATCH"
        for point in observation.get("stale_points", [])
    ):
        return True
    error = str(observation.get("error") or "").lower()
    return any(token in error for token in (
        "different project",
        "unsafe project marker",
        "repository root",
        "symlink",
    ))
```

`_pre_status_blocks_query(effective_pre)` 为真时不查询；普通 timeout/JSON/执行验证失败继续调用 `run_explore`。查询成功后仍执行 post-status，最终 `_delivery` 保留 pre-status 的 UNKNOWN 原因。

- [ ] **Step 6：更新 envelope 的显式处理语义**

在 `render_freshness_envelope` 中加入：

```python
freshness = (
    "VERIFIED_AT_CHECK"
    if delivery["state"] == "CURRENT"
    else "NO_GRAPH"
    if delivery["state"] == "UNAVAILABLE"
    else "TREAT_AS_STALE"
)
lines.insert(3, f"freshness: {freshness}")
```

`STALE` 与 `UNKNOWN` 都必须输出 `TREAT_AS_STALE`；不得只依赖 `usage: NAVIGATION_ONLY` 暗示。

- [ ] **Step 7：为 MCP 公开 schema 写失败测试**

把 MCP schema 测试改为：

```python
tool = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
schema = tool["result"]["tools"][0]["inputSchema"]
self.assertNotIn("sync_if_needed", schema["properties"])
self.assertNotIn("sync_if_needed", schema["required"])
self.assertEqual(set(schema["required"]), {
    "task_id", "stage", "query_id", "purpose", "query",
})
```

- [ ] **Step 8：运行 MCP schema 测试并确认 RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_mcp_server_initializes_and_lists_one_proxy_tool -v`

Expected: 当前 schema 仍包含 `sync_if_needed`，测试失败。

- [ ] **Step 9：删除 MCP 公开同步开关**

从 `TOOL`、`_validate_arguments` 和 `_call_tool` 删除 `sync_if_needed`。调用精确改为：

```python
proxy = execute_proxy_query(
    self.repo,
    arguments["task_id"],
    arguments["stage"],
    arguments["query_id"],
    arguments["purpose"],
    arguments["query"],
)
```

- [ ] **Step 10：为 bundle v1/v2 兼容性写失败测试**

给现有 `record_current_v3_fixture` 增加测试专用参数：

```python
def record_current_v3_fixture(
    self,
    *,
    legacy_bundle: bool = False,
    invalid_refresh_policy: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
```

在该 helper 已生成 `query`、尚未调用 `record_proxy_bundle` 的位置加入：

```python
bundle_path = query["bundle_path"]
bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
if legacy_bundle:
    bundle["bundle_version"] = 1
    bundle.pop("refresh_policy")
elif invalid_refresh_policy:
    bundle["refresh_policy"]["max_sync_attempts"] = 2
if legacy_bundle or invalid_refresh_policy:
    write_json_atomic(bundle_path, bundle)
```

然后添加：

```python
def test_bundle_v1_remains_projectable_but_v2_policy_is_fixed(self) -> None:
    recorded, _query = self.record_current_v3_fixture(legacy_bundle=True)
    self.assertEqual(recorded["record_version"], 3)

    self.tearDown()
    self.setUp()
    with self.assertRaisesRegex(RuleFailure, "refresh policy"):
        self.record_current_v3_fixture(invalid_refresh_policy=True)
```

- [ ] **Step 11：运行 bundle 兼容测试并确认 RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_bundle_v1_remains_projectable_but_v2_policy_is_fixed -v`

Expected: bundle v2 尚未被支持，或错误策略尚未被拒绝。

- [ ] **Step 12：让 bundle v1/v2 都可投影，但新查询只写 v2**

在 `record_proxy_bundle` 中按版本选择精确键集合：

```python
version = bundle.get("bundle_version")
base_keys = {
    "bundle_version", "proxy", "provider", "repository", "task_context",
    "query", "pre_status", "sync", "post_sync_status",
    "response_classification", "post_query_status", "delivery",
    "response_path",
}
if version == 1:
    _require_exact_keys(bundle, base_keys, "CodeGraph proxy bundle")
elif version == 2:
    _require_exact_keys(
        bundle, {*base_keys, "refresh_policy"}, "CodeGraph proxy bundle"
    )
    if bundle["refresh_policy"] != REFRESH_POLICY:
        raise RuleFailure("CodeGraph proxy bundle has an invalid refresh policy")
else:
    raise RuleFailure("CodeGraph proxy bundle has an unsupported identity")
```

在 `record_proxy_bundle` 函数内与现有 `resolve_stage_context` 延迟导入放在同一位置，从 `code_intelligence_proxy` 导入同一个 `REFRESH_POLICY`，不要复制第二份策略常量。record v3 输出结构保持不变；bundle digest 继续绑定输入 bundle 的精确字节。

- [ ] **Step 13：机械更新所有代理调用，并证明公开表面无旧参数**

把测试中的旧调用：

```python
query = proxy.execute_proxy_query(
    self.repo,
    "TASK-0001",
    "PLANNING",
    "CIQ-001",
    "locate A",
    "symbol A",
    False,
    runner=runner,
)
```

统一移除第七个位置布尔参数，改为：

```python
query = proxy.execute_proxy_query(
    self.repo,
    "TASK-0001",
    "PLANNING",
    "CIQ-001",
    "locate A",
    "symbol A",
    runner=runner,
)
```

Run: `rg -n "sync_if_needed" scripts/code_intelligence_mcp.py scripts/internal/code_intelligence_proxy.py`

Expected: no matches。`scripts/internal/codegraph_adapter.py` 与 `scripts/code_intelligence_runtime.py` 的低层显式 sync helper 保留，不属于 MCP 查询绕过开关。

- [ ] **Step 14：运行代理、MCP 与 record 聚焦测试**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_proxy_automatically_syncs_pending_without_a_caller_switch tests.test_codegraph.CodeGraphTests.test_proxy_queries_unknown_pre_status_and_treats_result_as_stale tests.test_codegraph.CodeGraphTests.test_proxy_does_not_query_a_different_project_index tests.test_codegraph.CodeGraphTests.test_proxy_window_requires_clean_pre_and_post_status_for_current tests.test_codegraph.CodeGraphTests.test_proxy_window_never_promotes_failed_or_post_stale_queries tests.test_codegraph.CodeGraphTests.test_mcp_server_initializes_and_lists_one_proxy_tool tests.test_codegraph.CodeGraphTests.test_mcp_server_returns_envelope_before_graph_and_preserves_bundle tests.test_codegraph.CodeGraphTests.test_bundle_v1_remains_projectable_but_v2_policy_is_fixed tests.test_codegraph.CodeGraphTests.test_v3_record_projects_exact_proxy_bundle tests.test_codegraph.CodeGraphTests.test_failed_explore_proxy_bundle_projects_to_unknown_v3 tests.test_codegraph.CodeGraphTests.test_failed_sync_proxy_bundle_preserves_only_observed_post_status -v`

Expected: all PASS；任一测试都不得观察到两次 sync、两次 explore 或 `codegraph index`。

- [ ] **Step 15：提交 Task 2**

```bash
git add scripts/internal/code_intelligence_proxy.py scripts/code_intelligence_mcp.py scripts/internal/code_intelligence_protocol.py tests/test_codegraph.py
git commit -m "feat: enforce automatic CodeGraph freshness windows"
```

---

### Task 3：统一所有阶段 Skill 和用户文档的新鲜度行为

**Files:**
- Modify: `skills/code-intelligence/SKILL.md`
- Modify: `skills/architecture-planning/SKILL.md`
- Modify: `skills/implementation/SKILL.md`
- Modify: `skills/documentation-sync/SKILL.md`
- Modify: `skills/adversarial-review/SKILL.md`
- Modify: `templates/AGENTS.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/USAGE.md`
- Modify: `plan.md`
- Test: `tests/test_codegraph.py:130-240,2970-3070`

**Interfaces:**
- Consumes: Task 2 的无同步参数 MCP schema 和四态 envelope。
- Produces: 所有宿主渲染后相同的阶段行为；Planning、Implementation、Documentation Sync、Review 不再选择同步策略。

- [ ] **Step 1：先加行为锚点失败测试**

```python
def test_all_agent_surfaces_require_automatic_freshness_policy(self) -> None:
    paths = [
        ROOT / "skills/code-intelligence/SKILL.md",
        ROOT / "skills/architecture-planning/SKILL.md",
        ROOT / "skills/implementation/SKILL.md",
        ROOT / "skills/documentation-sync/SKILL.md",
        ROOT / "skills/adversarial-review/SKILL.md",
        ROOT / "templates/AGENTS.md",
    ]
    required = (
        "automatically runs at most one incremental `codegraph sync`",
        "never runs `codegraph index`",
        "UNKNOWN",
        "TREAT_AS_STALE",
        "source/Git fallback",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("sync_if_needed", text, path.as_posix())
        for anchor in required:
            self.assertIn(anchor, text, f"{path}: {anchor}")
```

更新 `test_documentation_sync_uses_one_proxy_query`：删除 `sync_if_needed: true` 锚点，改为断言 `changed source paths`、`documented symbols`、`automatic incremental sync` 和 `no separate status/sync MCP tool`。

- [ ] **Step 2：运行 Skill 行为测试并确认 RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_require_automatic_freshness_policy tests.test_codegraph.CodeGraphTests.test_documentation_sync_uses_one_proxy_query -v`

Expected: 当前 Skill 仍包含 `sync_if_needed`，测试失败。

- [ ] **Step 3：更新 canonical Skills**

`skills/code-intelligence/SKILL.md` 必须明确以下单一流程：

```text
Call only polaris_codegraph_explore with task ID, stage, next CIQ-NNN,
purpose, and query. The proxy automatically runs at most one incremental
`codegraph sync` when pending changes exist and never runs `codegraph index`.
Read the freshness envelope before graph content. CURRENT_AT_CHECK is bounded
non-authoritative context. STALE and UNKNOWN/TREAT_AS_STALE are navigation-only
and require the exact source/Git fallback before any conclusion is used.
```

各阶段 Skill 只保留 task/stage/query 范围和查询次数约束：

- Planning：冻结范围内关系发现；
- Implementation：修改前可查，修改后需要结论时必须重新调用；
- Documentation Sync：仅 supported source 发生变化时，对 changed paths/symbols 调用一次；
- Review：Reviewer 独立调用，不继承 Implementer envelope；
- Validation：继续禁止 Code Intelligence。

- [ ] **Step 4：更新共享模板和用户文档**

在 `templates/AGENTS.md`、README、`docs/USAGE.md`、`plan.md` 中统一写明：

```text
代理在查询前检查状态；存在 pending changes 时自动且至多执行一次增量
`codegraph sync`；状态无法验证但仓库身份安全时仍查询并标记 UNKNOWN /
TREAT_AS_STALE；全量 `codegraph index` 始终由用户主动执行。
```

删除所有“按调用参数决定是否同步”和 `sync_if_needed: true/false` 描述。保留 CodeGraph 的安装、初始化、watcher、daemon、raw MCP 与全量重建归用户所有的边界。

- [ ] **Step 5：运行渲染与行为测试**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_require_proxy_provenance tests.test_codegraph.CodeGraphTests.test_all_agent_surfaces_require_automatic_freshness_policy tests.test_codegraph.CodeGraphTests.test_documentation_sync_uses_one_proxy_query tests.test_codegraph.CodeGraphTests.test_validation_remains_graph_free tests.test_core.PolarisCoreTests.test_host_adapters_render_from_one_host_neutral_skill_source -v`

Expected: all PASS；Validation 渲染中没有代理、status 或 sync 调用。

- [ ] **Step 6：提交 Task 3**

```bash
git add skills templates/AGENTS.md README.md README.zh-CN.md docs/USAGE.md plan.md tests/test_codegraph.py
git commit -m "docs: define automatic CodeGraph freshness behavior"
```

---

### Task 4：升级协议到 0.1.22，并增加不重写证据的相邻迁移

**Files:**
- Modify: `VERSION`
- Modify: `pyproject.toml`
- Modify: `templates/project.json`
- Modify: `templates/task-sources/state.json`
- Modify: `templates/task/state.json`
- Modify: `workflow/migrations.json`
- Modify: `scripts/internal/migration_protocol.py:280-480`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/USAGE.md`
- Modify: `plan.md`
- Test: `tests/test_codegraph.py:160-205,1720-1990`
- Test: `tests/test_core.py:2570-2620`

**Interfaces:**
- Consumes: 现有 migration protocol v2 的 `replace_version` / `append_version_event`。
- Produces: 唯一相邻步骤 `0.1.21-to-0.1.22`，Workflow 前后均为 `0.1.3`。

- [ ] **Step 1：写 0.1.21 → 0.1.22 迁移失败测试**

在 `tests/test_codegraph.py` 中使用现有 v3 fixture：

```python
def test_0122_migration_preserves_v3_code_intelligence_records(self) -> None:
    recorded, _query = self.record_current_v3_fixture()
    actual_path = (
        self.repo
        / ".polaris/tasks/TASK-0001/code-intelligence/r001/planning.json"
    )
    self.assertEqual(
        json.loads(actual_path.read_text(encoding="utf-8")), recorded
    )
    before = actual_path.read_bytes()
    self.set_protocol_version("0.1.21")

    with protocol_source_at("0.1.22") as source:
        vendor(source, self.repo, False)
    result = migrate_project(self.repo)

    self.assertEqual(result["from"], "0.1.21")
    self.assertEqual(result["to"], "0.1.22")
    self.assertEqual(actual_path.read_bytes(), before)
    migration = json.loads(Path(result["record"]).read_text(encoding="utf-8"))
    self.assertEqual(migration["retired_code_intelligence_records"], [])
```

- [ ] **Step 2：写 Workflow 不得变化的失败测试**

```python
def test_0122_version_only_migration_rejects_workflow_change(self) -> None:
    self.set_protocol_version("0.1.21")
    with protocol_source_at("0.1.22") as source:
        migrations_path = source / "workflow/migrations.json"
        migrations = read_json(migrations_path)
        migrations["steps"][-1]["to_workflow_version"] = "0.1.4"
        write_json_atomic(migrations_path, migrations)
        vendor(source, self.repo, False)
    with self.assertRaisesRegex(
        RuleFailure, "workflow migration requires replacement"
    ):
        migrate_project(self.repo)
```

- [ ] **Step 3：运行迁移测试并确认 RED**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_0122_migration_preserves_v3_code_intelligence_records tests.test_core.PolarisCoreTests.test_0122_version_only_migration_rejects_workflow_change -v`

Expected: 缺少相邻迁移步骤，或 v3 record 被旧 retirement inventory 拒绝。

- [ ] **Step 4：追加迁移步骤并限定历史 inventory**

在 `workflow/migrations.json` 末尾追加：

```json
{
    "migration_id": "0.1.21-to-0.1.22",
    "from_polaris_version": "0.1.21",
    "to_polaris_version": "0.1.22",
    "from_workflow_version": "0.1.3",
    "to_workflow_version": "0.1.3",
    "project_strategy": "replace_version",
    "task_strategy": "append_version_event"
}
```

`_retired_code_intelligence_records` 只服务 `0.1.20-to-0.1.21` 的历史 retirement。`_new_record` 和中断恢复重算 inventory 时，仅对该 migration ID 调用它；`0.1.21-to-0.1.22` 的 `retired_code_intelligence_records` 固定为空列表。不得重新清点或重写 v3 record。

- [ ] **Step 5：升级所有当前版本 Authority**

把以下当前版本值精确改为 `0.1.22`：

```text
VERSION
pyproject.toml project.version
templates/project.json polaris_version
templates/task-sources/state.json polaris_version
templates/task/state.json polaris_version
README.md / README.zh-CN.md / docs/USAGE.md / plan.md 当前版本说明
```

历史迁移说明中的 `0.1.20 → 0.1.21` 保留，并新增 `0.1.21 → 0.1.22` 行为说明。现有测试中对当前版本的断言更新为 `0.1.22`，历史 fixture 和旧迁移断言不得机械替换。

- [ ] **Step 6：运行版本与迁移测试**

Run: `python3 -m unittest tests.test_codegraph.CodeGraphTests.test_0122_migration_preserves_v3_code_intelligence_records tests.test_codegraph.CodeGraphTests.test_migration_inventories_frozen_v2_records_without_rewriting_them tests.test_codegraph.CodeGraphTests.test_migration_resume_rejects_mutated_frozen_v2_inventory tests.test_core.PolarisCoreTests.test_0122_version_only_migration_rejects_workflow_change tests.test_core.PolarisCoreTests.test_version_only_migration_rejects_a_workflow_version_change tests.test_core.PolarisCoreTests.test_migration_rejects_an_undeclared_version_jump -v`

Expected: all PASS；旧 `0.1.20 → 0.1.21` inventory 行为保持不变，新迁移不清点 v3。

- [ ] **Step 7：重新生成 task layout 并验证无漂移**

Run: `python3 scripts/materialize_task_layout.py`

Run: `git diff --check`

Expected: 只出现计划内的模板版本变化；生成树与 `task-sources` 保持一致。

- [ ] **Step 8：提交 Task 4**

```bash
git add VERSION pyproject.toml templates workflow/migrations.json scripts/internal/migration_protocol.py README.md README.zh-CN.md docs/USAGE.md plan.md tests/test_codegraph.py tests/test_core.py
git commit -m "chore: advance Polaris protocol to 0.1.22"
```

---

### Task 5：端到端验收、跨平台检查和完成前验证

**Files:**
- Modify if a failing assertion exposes a gap: only files already named in Tasks 1-4
- Test: `tests/test_codegraph.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: Tasks 1-4 的完整实现。
- Produces: 可审查、可迁移、无需修改 CodeGraph 的 Polaris `0.1.22`。

- [ ] **Step 1：加固 fake-CLI 端到端断言**

扩展现有 `test_vendored_mcp_proxy_runs_one_auditable_fake_cli_window`，让 fake CLI 记录 argv/cwd，并断言：

```python
self.assertEqual(
    [entry["argv"][0] for entry in calls],
    ["status", "sync", "status", "explore", "status"],
)
self.assertTrue(all(Path(entry["cwd"]).resolve() == repo.resolve() for entry in calls))
self.assertNotIn("index", [arg for entry in calls for arg in entry["argv"]])
self.assertTrue(first_content.startswith("[POLARIS_CODEGRAPH_FRESHNESS]\n"))
self.assertIn("freshness: VERIFIED_AT_CHECK", first_content)
self.assertEqual(record_value["record_version"], 3)
```

fake status 的第一次响应必须包含一个 pending modified，sync 后与 query 后响应必须干净，从而真实覆盖自动增量同步，而不是手工传入同步开关。

- [ ] **Step 2：运行 CodeGraph 聚焦全套**

Run: `python3 -m unittest tests.test_codegraph -v`

Expected: all PASS；如果本机未安装 CodeGraph，仅真实 CLI smoke test 可以 SKIP。

- [ ] **Step 3：运行 Core 聚焦全套**

Run: `python3 -m unittest tests.test_core -v`

Expected: all PASS。

- [ ] **Step 4：运行仓库完整验证**

Run: `python3 tests/run_tests.py`

Run: `python3 -m compileall -q polaris_cli.py scripts tests`

Run: `python3 scripts/materialize_task_layout.py`

Run: `git diff --check`

Expected: 完整测试 PASS；编译与格式检查退出 0；materialize 不产生未解释漂移。

- [ ] **Step 5：证明不存在查询绕过和全量重建路径**

Run: `rg -n "sync_if_needed" skills templates/AGENTS.md scripts/code_intelligence_mcp.py scripts/internal/code_intelligence_proxy.py README.md README.zh-CN.md docs/USAGE.md plan.md`

Expected: no matches。

Run: `rg -n "codegraph index" scripts skills templates README.md README.zh-CN.md docs/USAGE.md plan.md`

Expected: 只出现“Polaris 不执行、由用户主动执行”的文档语句；`scripts/` 内不得出现可执行 command 组装。

Run: `git -C /Users/zero/Documents/work/ai/codegraph status --short`

Expected: no output。

- [ ] **Step 6：对照规格建立最终覆盖表**

| 规格要求 | 必须通过的测试 |
|---|---|
| 当前 CodeGraph framing | `test_current_codegraph_freshness_framing_is_classified` |
| 源码 warning 不误判 | `test_warning_words_inside_verbatim_source_do_not_change_freshness` |
| pending 自动同步一次 | `test_proxy_automatically_syncs_pending_without_a_caller_switch` |
| pre-status unknown 仍查询 | `test_proxy_queries_unknown_pre_status_and_treats_result_as_stale` |
| 身份不匹配不查询 | `test_proxy_does_not_query_a_different_project_index` |
| clean window 才 CURRENT | `test_proxy_window_requires_clean_pre_and_post_status_for_current` |
| envelope 永远在前 | `test_mcp_server_returns_envelope_before_graph_and_preserves_bundle` |
| bundle v2 / record v3 | `test_v3_record_projects_exact_proxy_bundle` |
| STALE/UNKNOWN 强制 fallback | `test_v3_record_rejects_mutated_window_identity_and_fallbacks` |
| 所有阶段无同步开关 | `test_all_agent_surfaces_require_automatic_freshness_policy` |
| Validation graph-free | `test_validation_remains_graph_free` |
| v3 record 迁移不重写 | `test_0122_migration_preserves_v3_code_intelligence_records` |
| Workflow 保持 0.1.3 | `test_0122_version_only_migration_rejects_workflow_change` |
| vendored fake CLI 全窗口 | `test_vendored_mcp_proxy_runs_one_auditable_fake_cli_window` |
| CodeGraph 仓库不修改 | Step 5 的独立 `git status` 检查 |

- [ ] **Step 7：提交仅由验收暴露的修正**

```bash
git add scripts skills templates workflow tests README.md README.zh-CN.md docs/USAGE.md plan.md VERSION pyproject.toml
git commit -m "test: verify CodeGraph freshness hardening end to end"
```

如果 Steps 2-6 没有产生文件变化，则跳过该提交。

- [ ] **Step 8：请求代码审查并进入分支收尾**

完整验证通过后，依次使用 `superpowers:requesting-code-review` 和 `superpowers:finishing-a-development-branch`。审查必须特别核对：没有 CodeGraph 仓库改动、没有 `codegraph index` 执行路径、没有同步绕过参数、UNKNOWN 图仍可返回但必须按过期处理。
