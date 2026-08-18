# Polaris 专用 CodeGraph MCP 新鲜度代理设计

## 状态

- 日期：2026-08-18
- 状态：提议实施
- 范围：Polaris Code Intelligence 协议与阶段行为
- Provider：`colbymchenry/codegraph`

## 问题

目前，Polaris 允许 Planning、Implementation 和 Review 在独立的
CodeGraph `status` 检查与 `sync-if-needed` 之间任选一种，然后直接查询
`codegraph_explore`。当 status 的结构健康但 `pendingChanges` 非零时，
内部结果会表示为 `CURRENT_AT_CHECK` 加 `needs_sync: true`。精简的 v2
record 不保留 `needs_sync` 或 pending 计数，因此，只执行 status 的路径可能
丢弃已知的陈旧信号，同时仍以 `CURRENT_AT_CHECK` 通过校验。

新鲜度检查和查询还使用不同的传输方式：status 和 sync 通过 CLI 在仓库工作
目录中运行，而 explore 优先使用宿主 MCP 连接。Polaris 没有将这些操作绑定到
同一个项目，也没有把强制的新鲜度警告与 graph 响应一起交付。

所需行为刻意采用 fail-safe 原则：

- Polaris 可以向 Agent 提供陈旧的 graph 输出。
- 当输出已经陈旧或无法验证时，Polaris 必须告知 Agent。
- 已知陈旧或无法验证的输出绝不能被呈现为最新输出。
- 陈旧输出只能继续作为导航线索；当前源码和 Git 仍是权威来源。

## 保证边界

代理保证：Polaris 阶段通过代理交付的每一份 graph 响应，都带有紧邻的 Polaris
新鲜度 envelope；Polaris 观察到的每个新鲜度信号都会被保守分类。代理不证明
CodeGraph 的解析器或关系推断在语义上正确，也不声称交付后的结果永久新鲜或与
commit 精确一致。

原始 `codegraph_explore` MCP 工具和不受限制的 shell 访问继续保留。因此，
Polaris 无法阻止 Agent 绕过代理。Polaris 可以在 canonical 阶段指令中要求使用
代理，并机械拒绝缺少代理来源的 Code Intelligence 证据，但不能证明 Agent 从未
看到过通过其他通道取得的原始响应。

核心不变量是：

> 缺少新鲜度证明不等于新鲜。任何已知的陈旧信号都归类为 `STALE`；任何不可用
> 或不可读的证明都归类为 `UNKNOWN`；只有完全健康且有界的查询窗口才能归类为
> `CURRENT`。

`UNKNOWN` 与 `STALE` 具有相同的 Agent 使用限制。

## 选定方案

新增一个项目级 Polaris MCP server，并暴露唯一工具
`polaris_codegraph_explore`。Polaris 阶段 Skill 使用这个代理执行具备新鲜度感知
能力的 graph 查询。现有 `codegraph_explore` MCP 工具继续保持安装状态，并可供
非 Polaris 工作调用；Polaris 不移除、不包装、不拒绝也不限制 shell 命令。

代理内部使用 CodeGraph CLI 执行 status、可选的一次性 sync 和 explore，且这些
命令都使用同一个显式仓库工作目录。这样既避免 MCP 调用 MCP 的依赖，又能保持
与 `codegraph_explore` 等价的输出。代理只把原始响应写入已忽略的任务 runtime，
并把结构化新鲜度 envelope 与 graph 内容一起返回。

如果代理无法运行，Polaris 阶段会回退到源码和 Git。它不得静默改用原始
Provider 工具来生成 Polaris 证据。Agent 仍可在该证据路径之外自由使用原始工具
或 shell，但此类输出属于未验证的导航上下文，不能产生 `CURRENT` Polaris
record。

相比只修改指令，本方案更合适，因为新鲜度必须与 graph 响应机械地相邻。本方案
也按照要求保留原始 Provider 和 shell 接口，同时为 Polaris record 提供一条可
审计、fail-safe 的路径。

## MCP 接口

创建 `scripts/code_intelligence_mcp.py`，它是一个仅依赖标准库的 stdio MCP
server，由 vendored Polaris 项目 runtime 启动。它暴露一个有界工具：

```text
polaris_codegraph_explore({
  "task_id": "TASK-0001",
  "stage": "PLANNING",
  "query_id": "CIQ-001",
  "purpose": "discover frozen-task relationships",
  "query": "symbols and paths relevant to the frozen task",
  "sync_if_needed": true
})
```

必需输入：

- task ID，用于约束 runtime 证据范围；
- Polaris 阶段和有限的查询目的；
- 当前阶段 record 中下一个连续的 `CIQ-*` ID；
- 一个非空查询字符串。

仓库由项目级 server 启动配置固定，刻意不作为工具参数传入。

`sync_if_needed: true` 允许现有的一次性 sync 行为。`false` 表示只读，并且不
等待 CodeGraph 自动同步。两种模式都不会 sleep、轮询、重试、初始化 CodeGraph，
也不会管理其 daemon 或 watcher。

只要 graph 输出可用，即使交付状态是 `STALE` 或 `UNKNOWN`，MCP 结果仍视为成功。
Provider 执行失败时，返回一个不含 graph 响应、但要求源码回退的 `UNKNOWN`
结果。非法 Polaris 输入返回 MCP 工具错误。

## 查询流程

1. 校验协议兼容性、项目配置、`.codegraph/`、任务身份、阶段、目的和 runtime
   confinement。
2. 在 `cwd=repo` 中通过 CLI 执行查询前 status 检查。
3. 如果 `sync_if_needed` 为 true 且查询前 status 存在 pending changes，最多执行
   一次有界 sync，并且最多执行一次 sync 后 status 检查。
4. 如果有效的查询前状态允许查询，则在同一个 `cwd=repo` 中执行一次有界的
   `codegraph explore`。已知 pending changes 和 index-stale 状态允许执行仅用于
   导航的查询；status 不可用、项目不匹配或查询前 status 不可读时不允许查询。
5. 把精确的 UTF-8 响应保存到 `runtime/code-intelligence/` 下；绝不把原始输出
   写入 Git artifact。
6. 对响应 banner 进行分类。
7. 通过 CLI 执行一次查询后 status 检查。
8. 使用最保守的状态合并查询前、sync、响应和查询后观察结果。
9. 先发出 envelope；只有 graph 输出可用时，才在其后发出原始 graph 输出。
10. 在 envelope 中包含供不可变阶段 record 使用的精简证据 bundle 路径。显式
    query ID 决定其唯一 runtime 文件名；如果目标已经存在，代理必须拒绝，而不
    是覆盖。

查询不会重试。陈旧响应只交付一次，并附带限制；未知响应可以作为仅用于导航的
证据交付，也可以在无法确认其项目或响应完整性时被丢弃。

## 交付状态

### `CURRENT`

只有同时满足以下全部条件时才允许使用：

- 查询前 status 或成功 sync 后的 status 在结构上健康；
- 其 `projectPath` 解析后等于请求的仓库；
- pending added、modified 和 removed 计数全部为零；
- 不存在 worktree mismatch、partial/indexing/failed index、pending reference 或
  reindex recommendation；
- explore 响应不包含 stale banner 或 auto-sync-disabled banner；
- 查询后 status 同样在结构上健康，并且 pending 计数为零。

envelope 使用 `usage: NON_AUTHORITATIVE_CONTEXT`。源码、Git、构建、测试、Review
和 Validation 仍是权威来源。

### `STALE`

当 Polaris 观察到任何已知陈旧信号时使用，包括：

- 查询前或查询后的 pending source changes 非零；
- 逐文件 stale response banner；
- auto-sync 被禁用；
- worktree mismatch；
- partial、indexing 或 failed index 状态；
- pending references 或 reindex recommendation；
- sync 失败，或 sync 后 status 不健康。

envelope 使用 `usage: NAVIGATION_ONLY`，并给出确切的必要回退动作。如果只有
pending 计数而没有安全的文件名，则整个查询都归类为 `INDEX_STALE`；Polaris
不得推断未列出的关系仍是最新的。

### `UNKNOWN`

当无法确定新鲜度时使用，包括能力缺失、超时、畸形 status JSON、畸形的已识别
banner、不安全路径、项目不匹配或无法分类的 Provider 响应。envelope 使用
`usage: NAVIGATION_ONLY`，并要求通过仓库源码搜索和 Git 证据回退。无 banner 的
响应绝不能把它提升为 `CURRENT`。

响应分类采用 fail-safe 原则。精确匹配且受支持的 banner 产生其规定的 stale
状态。其他任何包含警告标记、stale 字样或 pending-sync 字样的疑似警告响应都产生
`UNKNOWN`；其中包括被说明文字、引用、前导空格或 BOM 包装的受支持 banner。
只有完全不含受支持或可疑新鲜度信号的响应才是中性的。

当 Code Intelligence 被禁用、缺少 `.codegraph/` 或缺少 CLI 能力时，
`UNAVAILABLE` 仍表示“不查询”状态。

## 代理激活

代理是项目级且归 Polaris 所有。宿主 adapter 会渲染一份本地 MCP 注册配置，
以一个固定仓库根目录启动 vendored server。它们不会添加全局 server，不会修改
用户原有的 CodeGraph MCP 注册，不会移除任何 CodeGraph 工具，也不会改变 shell
权限。

server 进程在启动时接收仓库根目录，工具调用本身不接受任意项目路径。仓库根目录
缺失、已移动或为 symlink 时，server 必须拒绝。移除或禁用项目本地的 Polaris
MCP 注册，只会禁用代理，不影响 CodeGraph 本身。

adapter 契约必须为每个受支持宿主表示项目级 MCP 注册，而不能把宿主专属配置写入
Code Intelligence adapter。Vendoring 和项目校验会验证该注册只启动仓库中的
vendored Polaris runtime。

## Envelope

每次成功的代理工具结果都以一个有限的文本 content block 开头：

```text
[POLARIS_CODEGRAPH_FRESHNESS]
state: STALE
record_status: INDEX_STALE
reason: PENDING_CHANGES
checked_at: 2026-08-18T12:00:00Z
pending_added: 0
pending_modified: 1
pending_removed: 0
usage: NAVIGATION_ONLY
required_fallback: SEARCH_SOURCE
evidence_bundle: runtime/code-intelligence/CIQ-001.json
[/POLARIS_CODEGRAPH_FRESHNESS]
```

如果保留原始 CodeGraph 响应，它会作为同一 MCP 工具结果中位置更后的 content
block。代理绝不能在 envelope 之前返回 graph 内容。人类可读诊断信息会被写入有限
的 envelope error 字段；子进程 stdout 和 stderr 绝不能在 envelope 之前转发。

## 证据与 Record 协议

引入新的 Code Intelligence record 版本，而不是削弱或改写不可变的 v2 证据。
保留 v1 和 v2 record 作为可读取的历史 artifact；新的阶段 record 使用 v3。

v3 查询证据包含：

- Provider ID 和 descriptor 版本；
- 仓库身份和阶段目标；
- 查询目的和响应 SHA-256；
- 查询前 status 观察结果；
- 可选的 sync 观察结果与 sync 后 status；
- 查询后 status 观察结果；
- 每次成功 status 的 pending added、modified 和 removed 计数；
- response-banner 分类和 stale points；
- 交付状态和使用限制；
- 精确的源码/Git 回退证据。

`CURRENT` 要求查询前或有效 status 和查询后 status 都成功，并且 pending changes
为零。`STALE` 至少需要一个明确的 stale reason。`UNKNOWN` 需要明确的验证失败。
validator 会拒绝观察结果缺失、状态自相矛盾、项目不匹配、响应 hash 不匹配，或在
任何 pending 计数非零时声明 `CURRENT`。

迁移过程会盘点不可变 v2 record，但不改写它们。Polaris 协议版本递增；workflow
graph 版本不变，因为 workflow 状态和 transition 都没有变化。

## 阶段行为

- Planning、Implementation 和 Review 使用代理生成具备新鲜度感知的 Polaris
  graph 证据。原始 `codegraph_explore` 仍可调用，但它的输出属于其他通道，对
  Polaris 而言始终是未验证的，不能支撑 `CURRENT` 阶段 record。
- Implementation 在编辑后若要为 Polaris 生成证据，只能发起一次新的代理调用；
  不能复用阶段入口的 envelope。
- Documentation Sync 在受支持源码发生变化时，使用相同的代理/status 机制生成
  最终有界 sync 证据。
- Validation 仍然不使用 graph。
- 当状态为 `STALE` 或 `UNKNOWN` 时，任何涉及返回文件或关系的阶段结论，都必须先
  完成 envelope 要求的源码/Git 回退。

Vendored `AGENTS.md`、宿主 overlay 和 canonical Skill 必须共享此契约。由于这些
改动会塑造 Skill 行为，因此必须遵循仓库的 `writing-skills` 工作流，并进行对抗性
前后评估。

## 失败处理

- 缺少 `.codegraph/` 或策略被禁用：发出 `UNAVAILABLE`，不执行查询。
- 缺少 CLI：发出 `UNAVAILABLE`，不通过 MCP 绕过。
- 查询前 status 失败：发出 `UNKNOWN`；回退源码；默认不查询。
- Explore 失败：发出 `UNKNOWN`；记录有限错误；不返回 graph 输出。
- 查询后 status 失败：graph 只能以 `UNKNOWN` 且仅供导航的形式交付。
- Explore 成功后出现 pending changes：以 `STALE` 交付，绝不能为 `CURRENT`。
- 不安全或跨项目响应路径：丢弃 graph 响应并使用源码搜索。
- Sync 失败：不重试；继续使用 stale 或 unknown envelope。

## 测试与评估

确定性单元测试和集成测试必须覆盖：

1. 查询前 status 存在 pending 时不能产生 `CURRENT`；
2. 查询后 status 存在 pending 时，会降级原本干净的响应；
3. 查询前后 status 都是零 pending，且响应干净时，产生 `CURRENT`；
4. status 失败或格式错误时产生 `UNKNOWN`，并且代理内部不执行 Provider explore；
5. stale banner 和 disabled-auto-sync banner 产生 `STALE`；
6. 有前缀、格式错误或发生变化的 banner 采用保守失败；
7. CLI status 和 explore 始终使用请求的同一个 `cwd`；
8. 项目不匹配时丢弃 graph 输出；
9. envelope 始终位于 graph bytes 之前；
10. v3 validator 拒绝 pending 计数非零或缺少查询后证据的 `CURRENT`；
11. 历史 v1/v2 record 保持字节不变且仍可读取；
12. Planning、Implementation、Documentation Sync、Review、vendored agent 和
    宿主渲染要求 Polaris 证据具有代理来源，同时保留原始 CodeGraph MCP 工具和
    不受限制的 shell 访问；
13. Validation 仍然不使用 graph；
14. 完整 Polaris 测试套件不依赖 CodeGraph 即可通过；
15. 可选的真实 CLI smoke test 只使用一次性临时仓库。

Skill 评估必须包含以下压力场景：要求 Agent 跳过代理；在存在 pending changes 时
仍信任看似干净的 graph；复用旧 Implementation envelope；或者把 `UNKNOWN` 当成
current。变更后的 Agent 必须拒绝每种捷径并执行要求的回退。

## 非目标

- 证明 CodeGraph 的解析器或推断关系在语义上正确。
- 把 graph freshness 变成 workflow 或 acceptance gate。
- 等待自动同步完成。
- 安装、初始化、配置或管理 CodeGraph。
- 构建第二套 watcher、daemon 或 index。
- 移除、禁用或限制原始 CodeGraph MCP 工具。
- 限制 shell 访问，或拒绝 Polaris Code Intelligence 证据之外的普通 shell 使用。
- 保证响应在交付后继续保持最新。

## 验收条件

1. 任何 CodeGraph 输出若缺少代理 evidence bundle，或其 MCP 结果没有把 freshness
   envelope 放在 graph 内容之前，都不能被接受为 Polaris Code Intelligence
   证据。
2. 任何已观察到的 pending change、stale banner、不健康索引、项目不匹配或验证
   失败，都会阻止 `CURRENT` 交付。
3. `UNKNOWN` 在机制上受到与 `STALE` 完全相同的限制。
4. Pending 计数和查询前后证据在不可变 v3 record 中保持可审计。
5. 陈旧 graph 输出仍可以作为仅供导航的证据使用，但必须完成当前源码或 Git
   回退。
6. 现有历史 record 和 workflow transition 继续有效。
7. 原始 `codegraph_explore` 工具和不受限制的 shell 访问保持可用且不变。
