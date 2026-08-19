# Polaris CodeGraph 新鲜度加固设计

## 状态

- 日期：2026-08-19
- 状态：设计已确认，等待书面规格审阅
- 范围：仅修改 Polaris 的 CodeGraph 查询与证据行为
- CodeGraph 仓库：禁止修改

## 背景

Polaris 已经通过项目级 `polaris_codegraph_explore` 代理承载 Workflow 内的 CodeGraph 证据。代理会检查 CodeGraph 状态、按条件执行一次增量同步、执行一次 explore 查询、再次检查状态，并把新鲜度 envelope 放在图输出之前。

当前实现仍未完全满足目标契约：

- 调用方可以传入 `sync_if_needed: false`，导致是否争取最新数据取决于 Agent 行为，而不是代理协议；
- 查询前状态超时、损坏或不可读时，代理直接放弃查询；即使仓库身份明确、旧图仍可用于导航，也拿不到图数据；
- 响应分类器绑定了旧版 CodeGraph 的警告文案，无法精确识别当前的 `indexing in progress`、auto-sync disabled 和 changed-on-disk 等提示；
- 当前对可疑词的宽泛扫描可能把返回源码正文中的 `stale`、`warning` 等普通文本误判为 CodeGraph 新鲜度警告；
- 代理 bundle 没有明确记录本次查询所遵循的自动刷新策略。

CodeGraph 是外部 Provider。本次改动不得修改 CodeGraph 仓库、命令、MCP 工具、watcher、daemon、配置或索引实现。

## 目标

1. 在一次有界增量协调能力内，让 Polaris 尽可能取得最新的图数据。
2. 旧图仍有导航价值时允许返回，但必须让“数据已过期”这一事实无法被忽略。
3. 无法验证新鲜度时仍允许返回图数据，但必须明确标为未知，并要求按过期数据处理。
4. 过期或无法验证的关系在经过当前源码或 Git 核验前，不得成为 Planning、Implementation、Documentation Sync 或 Review 的结论。
5. Code Intelligence 继续保持可选、非门禁能力。
6. 已提交的 Code Intelligence v1、v2、v3 record 保持原样。

## 非目标

- 修改 CodeGraph 仓库，或要求 CodeGraph 新增接口。
- 自动执行 `codegraph index` 或其他全量重建操作。全量重建始终由用户主动触发。
- 安装、初始化、启动、配置或监管 CodeGraph。
- 等待 watcher、轮询、重试，或增加 daemon、scheduler。
- 证明 CodeGraph 的解析或关系推断在语义上正确。
- 声称结果交付之后仍会持续保持最新。
- 把 CodeGraph 的可用性或新鲜度变成 Workflow 门禁。

## 已确认决策

### 有界新鲜度

唯一允许的正向新鲜度声明是 `CURRENT_AT_CHECK`。它表示 Polaris 在查询前、可选增量同步、查询和查询后检查组成的有界窗口内，没有发现过期或不可验证信号。它不是永久保证，也不表示结果与某个 Git commit 严格等价。

### 自动增量协调

刷新决策归代理所有，不再归调用方所有。查询前状态只要报告任意 pending added、modified 或 removed 文件，代理就在所有会查询 CodeGraph 的 Polaris 阶段中执行且仅执行一次有界 `codegraph sync`，随后再检查一次状态。

代理绝不执行 `codegraph index`。需要或建议全量重建的索引状态继续标记为过期，并在原因中明确提示这是用户动作。

### 返回有用的旧数据和未知数据

状态检查失败、超时或格式损坏，本身不再阻止 explore 查询；前提是 Polaris 已独立确认固定仓库身份和路径安全。图结果以 `UNKNOWN` 交付，并带有 `TREAT_AS_STALE` 与 `NAVIGATION_ONLY` 限制。

已知的过期信号产生 `STALE`。`STALE` 和 `UNKNOWN` 都可以指引导航，但从中得到的关系或结论必须先由当前源码或 Git 事实核验，才可用于 Workflow。

仓库或 worktree 身份不匹配、路径不安全时禁止查询。Polaris 不得把另一个 checkout 的图当作当前 checkout 的导航数据。

## 备选方案

### 方案一：加固现有 Polaris 代理——采用

把状态检查、可选增量同步、查询、查询后检查、响应分类、证据和交付继续收敛在一个 Polaris 自有操作内。它能在不修改 CodeGraph 的前提下，机械保证新鲜度警告与图输出相邻交付。

### 方案二：所有结果一律标为过期

这个方案安全但会丢弃本可证明的 `CURRENT_AT_CHECK`，也不符合“尽可能拿到新鲜数据”的目标。

### 方案三：先独立检查状态，再调用原始 CodeGraph 工具

这要求 Agent 自行维护两个工具调用之间的关联。Agent 可能漏掉警告，而且状态检查与图交付之间的竞态窗口更大。

## 架构

`polaris_codegraph_explore` 继续作为唯一能够生成 Polaris Code Intelligence 证据的 CodeGraph 路径。原始 CodeGraph MCP 和 shell 命令仍可在该证据路径之外使用，但它们对 Polaris 而言始终属于未验证数据。

项目级 MCP server 在启动时固定仓库根。工具调用只提供 task、stage、顺序 query ID、purpose 和 query，不提供仓库路径，也不提供刷新策略开关。代理的所有操作都以该固定仓库为工作目录。

各组件继续保持单一职责：

- `codegraph_adapter.py`：调用并标准化 CodeGraph CLI 的 status、sync、explore，以及分类 Provider 响应框架；
- `code_intelligence_proxy.py`：校验 Polaris 阶段上下文，控制有界查询窗口，合并观察结果，持久化不可变 runtime 证据，并渲染新鲜度 envelope；
- `code_intelligence_mcp.py`：暴露唯一的项目级 MCP 工具，并保证 envelope 先于图内容；
- `code_intelligence_protocol.py`：校验代理证据，并投影为现有 Code Intelligence record；
- Code Intelligence Skill：在使用过期或未知图结论之前，完成所需的当前源码或 Git 回退核验。

## 查询流程

1. 校验协议兼容性、策略、固定仓库根、task/stage 上下文、query ID、purpose 和 evidence 路径边界。
2. 验证 `.codegraph/` 与 CodeGraph CLI 是否可用。
3. 在固定仓库内执行 `codegraph status --json`。
4. 如果状态证明仓库或 worktree 身份不匹配，停止且不执行查询，不返回图内容。
5. 如果已知存在 pending changes，执行且仅执行一次增量 `codegraph sync`，然后执行一次同步后状态检查。
6. 不因为索引处于 partial、failed、由旧 extraction version 构建或存在其他索引级过期原因而单独触发 sync；这些情况不能通过假装增量同步等同于全量重建来可靠修复。如果 pending changes 与索引级过期原因同时存在，仍对这些变更执行一次增量同步，但同步后仍存在的索引级原因必须保留。
7. 如果状态因为验证错误而不可读或不可确认，保留失败观察并继续查询。Provider 能力缺失、仓库身份不安全或路径不安全仍属于禁止查询条件。
8. 执行一次有界 `codegraph explore`，不重试。
9. 仅在 task 的 Git ignored runtime evidence 目录下保存精确 UTF-8 响应及其哈希；已存在目标或摘要不一致时拒绝覆盖。
10. 只分类 CodeGraph 响应框架和元数据提示。
11. 只要取得 explore 响应，就执行一次查询后状态检查。
12. 保守合并全部观察，并保存不可变代理 bundle。
13. 把 freshness envelope 作为 MCP 的第一个内容块返回；安全且可用的原始图输出只能出现在后续内容块。
14. 每个 `STALE` 或 `UNKNOWN` 结果都必须完成并记录源码/Git 回退，之后才允许投影或使用其结论。

整个流程不等待、不轮询、不重试查询、不重试同步、不全量重建，也不改用原始 MCP 作为替代路径。

## 交付状态

### `CURRENT_AT_CHECK`

必须同时满足以下条件：

- 有效的查询前状态或同步后状态结构正确，且属于固定仓库；
- 任何允许的同步完成后，pending added、modified、removed 数量均为零；
- 不存在 worktree mismatch、partial/indexing/failed index、pending resolution 或 reindex recommendation；
- explore 成功，响应框架不包含过期或不可验证信号；
- 查询后状态结构正确，属于同一仓库，pending 数量均为零且索引健康。

其用途是 `NON_AUTHORITATIVE_CONTEXT`。源码、Git、构建、测试、Review、Validation 和 Human decision 继续拥有权威性。

### `STALE`

至少存在一个明确的过期信号，例如：

- 查询前或查询后仍有 pending changes；
- 唯一一次允许的增量同步失败；
- CodeGraph 报告 pending sync、indexing in progress、changed on disk 或 auto-sync disabled；
- 索引为 partial、indexing、failed，存在 pending resolution，或建议重建；
- 查询期间或查询后观察证明索引在窗口中发生变化。

安全时仍返回图输出。用途是 `NAVIGATION_ONLY`，envelope 必须包含已知原因和所需 fallback。

### `UNKNOWN`

无法建立新鲜度证明，包括 status 超时、status 格式损坏、无法识别的 Provider freshness framing、查询后验证失败或响应完整性不确定。

只要仓库身份、路径边界和响应完整性足以安全交付，仍返回图输出。envelope 必须包含 `freshness: TREAT_AS_STALE`，用途是 `NAVIGATION_ONLY`，并强制执行当前源码或 Git 回退。

如果已知过期信号与验证失败同时存在，两者都必须保留。顶层状态使用 `STALE`，因为明确的过期事实不能被 `UNKNOWN` 隐藏；验证失败作为附加原因存在，也不得把结果升级。

### `UNAVAILABLE`

策略禁用 Code Intelligence、缺少 `.codegraph/` 或缺少 CLI，导致无法尝试 Provider 查询时，没有 CodeGraph 数据可返回，Polaris 直接使用源码和 Git。

如果 explore 已经尝试但失败，状态改为 `UNKNOWN` 且不返回图内容，因为 Polaris 观察到的是验证失败，而不是 Provider 缺失。

身份不匹配表示“无法验证且禁止交付图”，不是 Provider 缺失，因此必须保留对应的安全诊断原因，不能伪装成普通 `UNAVAILABLE`。

## 响应分类

CodeGraph 返回人类可读文本，而不是带版本的结构化 freshness 对象。因此 Polaris 维护一个保守的兼容适配层，但不修改 CodeGraph。

分类器识别当前 CodeGraph 的以下响应框架：

- 响应引用的文件正在等待同步；
- 响应引用的文件正在建立索引；
- 项目内其他文件正在等待同步；
- auto-sync disabled 或 watcher degraded；
- 文件在上次索引同步后已在磁盘上变化；
- worktree 与 index root 不匹配。

分类器必须理解响应结构。它只检查开头提示、已识别的文件区块元数据和已识别的结尾提示，不得在逐字返回的源码正文中搜索 `stale`、`warning`、`pending` 等通用词，因为它们可能只是合法的程序文本。

精确识别的提示生成文件级或索引级 stale point。响应框架位置出现新的或格式损坏的 warning-like 提示时，结果降级为 `UNKNOWN`。普通源码文本不能触发新鲜度降级。status JSON 是主要的机器可读 freshness 基础；响应解析只承担额外的竞态与降级信号。

## 新鲜度 envelope

每个成功的代理工具结果都必须以一个有限文本块开头，例如：

```text
[POLARIS_CODEGRAPH_FRESHNESS]
state: UNKNOWN
record_status: NOT_VERIFIED
freshness: TREAT_AS_STALE
reason: PRE_STATUS_TIMEOUT
checked_at: 2026-08-19T00:00:00Z
pending_added: 0
pending_modified: 0
pending_removed: 0
usage: NAVIGATION_ONLY
required_fallback: SEARCH_SOURCE
evidence_bundle: runtime/code-intelligence/CIQ-001.json
[/POLARIS_CODEGRAPH_FRESHNESS]
```

envelope 永远是第一个内容块。任何 stdout、stderr、诊断或图数据都不得出现在它之前。保留的原始图输出必须位于独立的后续内容块。

## 源码与 Git 回退

`STALE` 和 `UNKNOWN` 证据在完成所需回退之前，不得支持 Workflow 结论：

- 对安全、具名且当前存在的普通文件，读取文件并记录 `READ_SOURCE` 与当前 SHA-256；
- 对安全但缺失或已删除的文件，检查注册 subject 的 Git diff，并记录 `INSPECT_GIT_DIFF` 以及绑定的 base、head、diff hash；
- 对不安全、索引级或未知失效点，执行有界仓库搜索，并记录 `SEARCH_SOURCE`；结果为 0 到 100 个位于仓库边界内的当前普通文件及其 SHA-256。

旧图关系可以决定“去哪里查”。只有由此得到的当前源码或 Git 事实，才能支持计划、编辑、文档结论或 Review verdict。

## 接口与版本

- Polaris 协议/包版本从 `0.1.21` 升级到 `0.1.22`。
- Workflow 保持 `0.1.3`；不改变 Workflow node、edge、status 或 transition gate。
- `polaris_codegraph_explore` 移除公开的 `sync_if_needed` 参数，增量同步决策始终归代理。
- 新的 runtime proxy evidence 使用 `bundle_version: 2`，并记录自动刷新策略。
- bundle v1 继续可读，以恢复升级时尚未完成投影的任务；新调用不再写入 v1。
- 新的耐久 Code Intelligence record 继续使用 `record_version: 3`；现有格式已经能够表达查询前后状态、sync、query、delivery state、reason 和 source fallback。
- 已存在的 v1、v2、v3 耐久 record 保持不可变且继续有效。
- 相邻迁移更新 vendored 协议文件、宿主 MCP 定义、Skills 和 validators，不重写 Code Intelligence record，也不改变 Workflow 状态。

## 失败处理

| 条件 | 是否查询 | 交付状态 | 必须动作 |
|---|---:|---|---|
| 查询前后状态干净 | 是 | `CURRENT_AT_CHECK` | 继续遵守普通 Authority 规则 |
| 有 pending，同步成功且同步后干净 | 是 | 可成为 `CURRENT_AT_CHECK` | 继续遵守普通 Authority 规则 |
| 有 pending，但同步失败 | 是 | `STALE` | 源码/Git 回退 |
| 同步后仍有 pending | 是 | `STALE` | 源码/Git 回退 |
| 索引 partial/failed/建议重建 | 是 | `STALE` | 源码/Git 回退；用户可主动重建 |
| 查询前 status 超时/损坏 | 是 | `UNKNOWN` | 按过期处理；源码/Git 回退 |
| 查询后 status 超时/损坏 | 是 | `UNKNOWN`；若另有已知过期则为 `STALE` | 按过期处理；源码/Git 回退 |
| 未知响应框架警告 | 查询已完成 | `UNKNOWN` | 按过期处理；源码/Git 回退 |
| 仓库/worktree 身份不匹配 | 否 | `UNKNOWN`，无图 | 源码/Git 回退 |
| 不安全响应路径或摘要不一致 | 不交付图 | `UNKNOWN` | 源码/Git 回退 |
| 策略禁用、缺 marker 或缺 CLI | 否 | `UNAVAILABLE` | 使用源码/Git |
| explore 失败 | 已尝试 | `UNKNOWN`，无图 | 按过期处理；使用源码/Git |

任何失败路径都不得调用 `codegraph index`。

## 实现范围

预计涉及的 Polaris 文件包括：

- `scripts/internal/codegraph_adapter.py`
- `scripts/internal/code_intelligence_proxy.py`
- `scripts/internal/code_intelligence_protocol.py`
- `scripts/code_intelligence_mcp.py`
- 必要的 Code Intelligence schema 与 runtime bundle validation
- `skills/code-intelligence/SKILL.md` 及调用它的阶段 Skills
- 宿主渲染/vendoring 指令与模板
- `plan.md`、README、使用文档
- 协议版本与相邻迁移元数据
- `tests/test_codegraph.py` 及相关 core/vendoring 测试

CodeGraph 仓库不在实现范围内，必须保持无修改。

## 测试

确定性测试必须覆盖：

1. 查询前后观察干净时产生 `CURRENT_AT_CHECK`；
2. 所有查询阶段发现 pending changes 时都恰好执行一次增量同步；
3. 同步成功且状态转为干净后可以产生 `CURRENT_AT_CHECK`；
4. 同步失败或同步后仍 pending 时，仍执行 explore 并产生 `STALE`；
5. 查询前 status 不可读、格式损坏、失败或超时时，仍执行 explore 并产生 `UNKNOWN`；
6. 仓库/worktree 身份不匹配时不执行 explore；
7. explore 后首次出现 pending changes 时降级结果；
8. 当前 CodeGraph 的 pending、indexing、degraded/disabled、changed-on-disk 和 mismatch 提示都能正确分类；
9. 返回源码中的 warning-like 单词不影响分类；
10. 响应框架位置出现未知警告时产生 `UNKNOWN`；
11. envelope 永远是第一个内容块，图输出永远不能出现在它之前；
12. 缺少精确 source/Git fallback 的 stale 或 unknown record 被拒绝；
13. MCP schema 不再提供调用方控制的同步绕过开关；
14. command runner 测试证明任何代理分支都不能调用 `codegraph index`；
15. bundle v2 得到校验，bundle v1 继续支持升级中断恢复；
16. 已提交的 Code Intelligence v1、v2、v3 record 保持字节不变且继续有效；
17. 覆盖 Windows 路径与 CRLF、macOS、Linux 行为，不引入平台特定假设；
18. 未安装 CodeGraph 时，完整 Polaris 测试套件仍通过；
19. 可选真实 CLI smoke test 只使用一次性临时仓库。

## 验收标准

1. Polaris 交付的每个图响应之前，都有机器可读且人类可见的 freshness envelope。
2. pending change 始终触发至多一次自动增量同步，且永远不能触发全量重建。
3. 调用方不能关闭自动增量同步策略。
4. freshness 检查失败时，仍可把安全图数据作为 `UNKNOWN` 交付。
5. 已知过期信号始终明确显示为 `STALE`，即使还同时存在其他验证失败。
6. 只有完整干净的有界窗口才能产生 `CURRENT_AT_CHECK`。
7. `STALE` 和 `UNKNOWN` 图数据在记录当前源码或 Git 回退前，只能用于导航。
8. 仓库/worktree 身份不匹配或路径不安全时，永不交付图内容。
9. 已存在的耐久 Code Intelligence record 保持不变且继续有效。
10. CodeGraph 仓库中的任何文件都不被修改。
