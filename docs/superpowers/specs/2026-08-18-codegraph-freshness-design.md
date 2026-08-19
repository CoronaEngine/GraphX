# CodeGraph 实时新鲜度与源码回退设计

## 状态

- 日期：2026-08-18
- 状态：历史设计，已由 `2026-08-18-codegraph-polaris-mcp-proxy-design.md` 取代；不得作为当前操作指南
- 适用版本：Polaris v0.1 的下一协议版本
- 产品 authority：`plan.md`
- 唯一正式 CodeGraph Provider：[`colbymchenry/codegraph`](https://github.com/colbymchenry/codegraph)

> 当前阶段必须只调用 Polaris 项目代理 `polaris_codegraph_explore`。本文以下对阶段直接编排 `status`、`sync-if-needed` 或 raw `codegraph_explore` 的描述仅用于解释 v2 历史协议，不能支持新的 Polaris `CURRENT` 证据。

## 背景

Polaris 已有可选 Code Intelligence Provider 协议，但当前 `codegraph` descriptor 指向另一个同名且协议不兼容的产品。目标 Provider 实际应为 `colbymchenry/codegraph`。它默认向 MCP 暴露单一高价值入口 `codegraph_explore`，并提供 `codegraph explore`、`codegraph status --json` 和 `codegraph sync` CLI。

目标 CodeGraph 通过三层机制保持索引接近当前工作树：MCP 文件 watcher 增量同步、响应级逐文件 stale banner，以及连接时 reconciliation。Polaris 不复制这些机制，也不建设 daemon；Polaris 只增加阶段边界检查、必要时的一次增量同步、失效点记录和确定性源码回退。

## 目标

1. `codegraph` Provider ID 只代表 `colbymchenry/codegraph`。
2. Agent 在已初始化仓库中优先通过 `codegraph_explore` 获取源码、调用路径和影响范围。
3. 正常编辑依赖 CodeGraph watcher；Polaris 只在阶段入口、已知索引冻结或最终交付前按需执行 `codegraph sync`。
4. CodeGraph 返回局部失效信息时，明确记录具体文件并要求 Agent 直接读取这些文件。
5. 整体索引无法信任时，明确标记索引级失效并让 Agent 回退到仓库搜索、源码读取或 Git diff。
6. 新鲜度表达必须是一次检查时的有限结论，不能宣称索引与 Git commit 永久或严格一致。
7. Provider 不可用、状态不可解析或同步失败时，Polaris 工作流继续运行；Code Intelligence 永远不是门禁或验收证据。
8. 所有运行时代码继续只依赖 Python 标准库，并在 Windows、macOS 和 Linux 上使用相同协议语义。

## 非目标

- Polaris 不安装 CodeGraph。
- Polaris 不执行 `codegraph init`，因为建立 `.codegraph/` 索引是用户决定。
- Polaris 不启动、停止或管理 CodeGraph daemon，不修改宿主 MCP 配置。
- Polaris 不通过 sleep 等待 watcher，不持续轮询状态，不实现第二套文件 watcher。
- Polaris 不把 CodeGraph 结果当作源码、Git、构建、测试、Validation 或独立 Review 的替代品。
- Polaris 不保存完整图或完整 MCP 响应到 Git。
- 本改动不增加第二个正式 Code Intelligence Provider。

## 方案选择

采用“Provider 原生 watcher + Polaris 按需 sync + 精确失效回退”。

没有采用每次查询前强制同步，因为这会增加延迟和索引锁竞争，并重复 CodeGraph watcher 已完成的工作。没有采用完全被动信任 watcher，因为 watcher 被禁用、索引部分损坏、worktree 不匹配或连接失败时，Polaris 将无法给出可审计的新鲜度结论。

## 架构

### Provider descriptor

`providers/code-intelligence/codegraph.json` 是唯一正式 descriptor，并升级 descriptor 版本。它声明：

- 实现标识：`github.com/colbymchenry/codegraph`
- 项目激活标记：`.codegraph/`
- MCP 主入口：`codegraph_explore`
- MCP 可选健康入口：`codegraph_status`
- CLI executable：`codegraph`
- CLI 查询：`explore`
- CLI 健康检查：`status --json`
- CLI 增量同步：`sync --quiet`
- CodeGraph 支持的源码扩展名

Planning 的 context、dependency、call-path 和 impact 目的，Implementation 的 edit context，Review 的 subject impact 都映射为不同 query purpose，但最终调用同一个 `codegraph_explore`。Polaris 不再假设 Provider 有多个窄工具。

descriptor Schema 只描述通用的 marker、MCP operation 和 CLI capability；CodeGraph JSON 输出和 banner 的具体解释封装在 adapter 内，不能散落到核心 workflow 或阶段 Skills。

### 协议层

`scripts/internal/code_intelligence_protocol.py` 保留以下 Provider-neutral 职责：

- 加载 `.polaris/code-intelligence.json`。
- 加载并验证正式 descriptor。
- 根据配置、`.codegraph/` marker 和宿主暴露的工具选择 Provider。
- 验证 v2 Code Intelligence record 与当前任务 revision、subject 和仓库路径一致。
- 写入不可变的精简 record。

旧的 `refresh_files` / `refresh_workspace` 逻辑删除。目标 CodeGraph 的 `sync` 本身是增量 reconciliation，并统一处理新增、修改、删除和重命名。

### CodeGraph adapter

新增聚焦的内部 adapter，负责：

- 使用参数数组和显式工作目录调用 `codegraph status --json` 与 `codegraph sync --quiet`，不得经过 shell。
- 对外部进程设置有限超时，并把超时、非零退出码、编码错误和 malformed JSON 转为通用失败状态。
- 验证 status 的 `initialized`、`projectPath`、`pendingChanges`、`worktreeMismatch`、`index.state`、`index.pendingRefs` 和 `index.reindexRecommended`。
- 将官方逐文件 stale banner 解析为受仓库边界约束的文件失效点。
- 将官方 auto-sync-disabled banner 解析为索引级失效点。
- 在允许同步的调用中最多执行一次 `sync`，随后最多执行一次 status 复查。
- 返回 Provider-neutral 的 freshness、stale points 和命令证据摘要。

adapter 不安装、初始化或启动 Provider。`.codegraph/` 不存在时不得调用 MCP 或 CLI。

### 内部运行脚本

新增一个不暴露到用户 `polaris` CLI 命令面的内部脚本，提供三个动作：

- `status`：读取一次 status 并输出通用 freshness JSON。
- `sync-if-needed`：先检查状态，只在需要时同步一次并复查一次。
- `classify-response`：读取任务 runtime 下的原始 explore 响应，提取 stale banner，并输出通用 freshness JSON。

精确 Provider 响应只保存在任务的 ignored `runtime/code-intelligence/` 下。Git 中只保存响应 SHA-256、有限摘要、失效点和源码回退证据。

## 新鲜度模型

每个 v2 Code Intelligence record 包含一个 `freshness` 对象：

```json
{
    "status": "PARTIAL_STALE",
    "checked_at": "2026-08-18T12:00:00Z",
    "basis": [
        "STATUS_JSON",
        "RESPONSE_BANNER"
    ],
    "stale_points": [
        {
            "scope": "FILE",
            "path": "src/widget.py",
            "reason": "PENDING_SYNC",
            "fallback": "READ_SOURCE",
            "observed_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        }
    ]
}
```

### Freshness status

- `CURRENT_AT_CHECK`：检查时没有已知失效信号。该名称明确限制结论时效，不表示 commit-exact。
- `PARTIAL_STALE`：响应引用的一个或多个具体文件处于 pending sync，其他未列出的响应内容仍可作为 CodeGraph 线索使用。
- `INDEX_STALE`：整个索引不可直接信任。
- `NOT_VERIFIED`：无法取得或解析充分健康状态，不能静默视为 current。
- `UNAVAILABLE`：Provider 被禁用、`.codegraph/` 缺失，或 MCP/CLI 查询通道均不可用。

`basis` 只允许：

- `CONNECT_RECONCILIATION`
- `STATUS_JSON`
- `SYNC_ACKNOWLEDGED`
- `RESPONSE_BANNER`
- `NONE`

连接 reconciliation 只有在 Provider 响应明确确认时才能记录，不能由 Polaris 猜测。

### Stale point

文件级失效点：

- `scope` 为 `FILE`。
- `path` 必须是仓库相对 POSIX 路径。
- `reason` 为 `PENDING_SYNC`。
- 文件存在时 `fallback` 必须为 `READ_SOURCE`，且 `observed_sha256` 必须等于记录时当前普通文件的 SHA-256。
- 文件已删除时 `fallback` 必须为 `INSPECT_GIT_DIFF`，且 `observed_sha256` 必须为 `null`。

索引级失效点：

- `scope` 为 `INDEX`。
- `path` 必须为 `null`。
- `fallback` 必须为 `SEARCH_SOURCE`。
- `observed_sha256` 必须为 `null`。
- `reason` 允许：`AUTO_SYNC_DISABLED`、`WORKTREE_MISMATCH`、`INDEX_PARTIAL`、`INDEX_INDEXING`、`INDEX_FAILED`、`PENDING_REFERENCES`、`REINDEX_RECOMMENDED`、`SYNC_FAILED`、`STATUS_UNREADABLE`。

一致性规则：

- `CURRENT_AT_CHECK` 不得包含 stale point。
- `PARTIAL_STALE` 至少包含一个文件级 stale point，且不得包含索引级 stale point。
- `INDEX_STALE` 至少包含一个索引级 stale point。
- `NOT_VERIFIED` 必须包含 `STATUS_UNREADABLE`，或记录查询通道没有提供可验证状态。
- `UNAVAILABLE` 不得伪造 status、sync 或 response 成功证据。
- 所有非 current 状态都必须给出 Agent 下一步回退动作。

### Source fallback

`source_fallbacks` 记录 Agent 对失效范围实际采用的权威来源：

- `READ_SOURCE`：直接读取当前普通文件并绑定 SHA-256。
- `INSPECT_GIT_DIFF`：用于已删除路径，绑定 subject base/head 和 diff hash。
- `SEARCH_SOURCE`：用于整个索引失效或未知影响范围，记录实际使用的仓库搜索目的与有限路径结果。

Validator 能验证路径 confinement、文件类型、当前 SHA-256 和 subject diff hash。它不能证明模型理解了内容，因此这些字段是可审计的输入证据，不是完成门禁。

## 运行流程

### Provider 激活

1. 加载项目 Code Intelligence 配置。
2. 配置为 `disabled` 时记录 `UNAVAILABLE`，不尝试 Provider。
3. `.codegraph/` 不存在时记录 `UNAVAILABLE`。当前会话对该项目停止调用 CodeGraph，并提示用户可自行运行 `codegraph init`。
4. 优先使用宿主暴露的 `codegraph_explore`。
5. MCP explore 不可用而 `codegraph` executable 可用时，使用 `codegraph explore`。
6. 两者均不可用时立即回退源码。

### 阶段入口

1. 调用 `status`。
2. status healthy 且 pending change 总数为零时记录 `CURRENT_AT_CHECK`。
3. 有 pending change 时执行一次 `sync`，然后复查一次。
4. 复查 healthy 时以 `SYNC_ACKNOWLEDGED` 作为 basis。
5. 复查仍 pending 或出现索引级异常时记录 `INDEX_STALE`，本阶段不循环同步。

Healthy status 必须同时满足：

- `initialized` 为 `true`。
- `projectPath` 解析后等于当前仓库根目录。
- `pendingChanges.added`、`modified`、`removed` 均为零。
- `worktreeMismatch` 为 `null`。
- `index.state` 为 `complete`，或为旧版本缺省值 `null` 且没有其他失效信号。
- `index.pendingRefs` 为零。
- `index.reindexRecommended` 为 `false`。

### Explore 查询

1. 查询必须受冻结 Work Item、Working Set、registered subject 或已确认依赖约束。
2. 保存原始响应到 runtime，并记录 SHA-256。
3. 解析 stale banner。
4. 没有 banner 且入口 status healthy 时，结果可作为 `CURRENT_AT_CHECK` 的非权威线索。
5. 逐文件 banner 产生 `PARTIAL_STALE`：立即直接读取列出的文件；这些文件相关的图关系只能用于导航，不能直接形成编辑或 Review 结论。官方明确未列出的响应部分仍可使用。
6. auto-sync-disabled banner 产生 `INDEX_STALE`：允许同步时执行一次 sync 并重试一次查询；无法恢复时直接读取返回的全部路径，并通过仓库搜索补齐依赖。
7. malformed response 产生 `NOT_VERIFIED` 并回退源码。

### Implementation 中途查询

正常编辑不主动同步，也不等待 debounce。只有后续声明步骤确实依赖刚修改代码的新调用关系时才再次查询。查询返回 stale banner 时直接读取 stale 文件；不能通过 sleep 或重复轮询让 banner 消失。

### Documentation Sync

最终代码 subject 存在受支持源码变化时执行一次 `sync-if-needed`。没有受支持源码变化时记录 `SKIPPED`。同步失败只影响 Code Intelligence freshness record，不阻止 docs check、Validation 或任务状态转换。

### Review

Reviewer 使用 registered subject 独立查询，不能复用 Implementer 的查询结论。任何 stale point 都必须在 Reviewer 自己的 record 中重新处理。CodeGraph 不能决定 Review verdict。

### Validation

Validation 不调用 CodeGraph。验收只依赖源码、Git、构建、测试、静态检查和 Human Check。

## 错误处理

- 外部进程超时、非零退出、无法解码或 JSON malformed：`NOT_VERIFIED` 或 `INDEX_STALE`，附有限错误摘要，立即回退。
- `.codegraph/` 缺失：`UNAVAILABLE`，不自动初始化。
- executable 缺失但 MCP 可用：继续使用 MCP；不得因为 CLI status 缺失声称 `CURRENT_AT_CHECK`，响应 banner 仍可提供局部 freshness。
- MCP 缺失但 CLI 可用：使用 CLI explore/status/sync。
- marker、status project path 或返回路径越过仓库边界：拒绝该证据并按 `INDEX_STALE` 回退。
- 同步成功但复查仍 pending：记录 `SYNC_FAILED` 或保留更具体的 status reason，不再同步第二次。
- CodeGraph lock、watcher 或 daemon 错误：Polaris 不管理进程；记录错误并给出用户可执行的 Provider 修复提示。
- 原始响应可能包含源码，不得写入 Git artifact；只保存 ignored runtime 文件及其哈希。

## Agent 指令

vendored `AGENTS.md` 和宿主 worker 指令必须包含同一组条件规则：

1. 只有仓库根存在 `.codegraph/` 才优先使用 CodeGraph。
2. MCP 可用时先用 `codegraph_explore`；非 MCP worker 使用 `codegraph explore`。
3. 响应列出的 stale 文件必须直接读取；不要放弃整个仍可用的图响应。
4. auto-sync disabled 或整体索引失效时，图只作为提示，必须从源码和 Git 确认。
5. 项目未初始化时停止对本项目调用 CodeGraph；可以提示 `codegraph init`，但不得代用户运行。
6. CodeGraph 结果不能扩展冻结 scope，也不能替代测试和门禁。

这些规则由 Polaris vendoring 负责提供给 Implementer 和 Reviewer。若 CodeGraph 官方 installer 已在仓库 instructions 中写入 marker-fenced 规则，内容可以并存，但 Polaris 规则不得修改或删除 installer 管理的 marker block。

## 版本和迁移

本改动升级 Polaris 协议版本，但 workflow 版本继续保持 `0.1.2`。descriptor、record Schema 和阶段 Skill 行为属于 Polaris 协议资产；节点、边、gate ID 和 rigor 图均未改变，因此不应扩展冻结 workflow 的迁移策略。

迁移规则：

- 新任务只能写 v2 Code Intelligence record，并绑定新版 `colbymchenry/codegraph` descriptor。
- 已提交的 v1 record 不删除、不改写，继续作为 immutable historical evidence 审计。
- v1 record 通过独立的 legacy validation path 读取，不再根据当前 descriptor 宣称 Provider capability 或 freshness。
- 迁移记录将 v1 Code Intelligence evidence 标记为 `retired_provider_evidence`；它不能被新阶段复用，也不能支持任何新鲜度结论。
- 活跃任务在迁移后的下一 Code Intelligence 阶段必须生成新的 v2 record。
- 旧产品的 MCP 工具名、descriptor 映射、刷新规划、测试断言和用户文档全部删除；legacy record Schema 使用逻辑 operation 名，不保存旧产品工具名。

## 安全与跨平台

- 所有 CLI 调用使用 `subprocess` 参数列表、显式 `cwd`、UTF-8 文本模式和有限 timeout。
- 不使用 shell command string，不依赖 Bash、PowerShell 或 PATH 分隔符语义。
- status `projectPath`、banner 路径和 source fallback 路径都必须经过现有 confinement 与 regular-file 检查。
- symlink 解析后越出仓库即拒绝。
- `.codegraph/` 只作为存在性 marker，不读取或修改其内部数据库。
- Windows 路径在进入 artifact 前标准化为仓库相对 POSIX 路径。
- 同步命令的 stdout/stderr 只进入 ignored runtime；Git record 只保存哈希与有限错误摘要。

## 文件改动范围

预计修改：

- `providers/code-intelligence/codegraph.json`
- `schemas/code-intelligence-provider.schema.json`
- `schemas/code-intelligence-record.schema.json`
- `scripts/internal/code_intelligence_protocol.py`
- `scripts/record_code_intelligence.py`
- `skills/code-intelligence/SKILL.md`
- `skills/architecture-planning/SKILL.md`
- `skills/implementation/SKILL.md`
- `skills/adversarial-review/SKILL.md`
- `skills/documentation-sync/SKILL.md`
- `templates/AGENTS.md`
- Code Intelligence record 与相关 artifact 模板
- `README.md`
- `docs/USAGE.md`
- `plan.md`
- `VERSION`
- Polaris version、相邻 migration 声明与对应模板；workflow version 保持 `0.1.2`
- `tests/test_core.py`，或按现有测试组织拆出的聚焦测试文件

预计新增：

- 一个内部 CodeGraph adapter 模块
- 一个内部 Code Intelligence runtime 脚本
- v1 record legacy Schema 或等价的只读 legacy validator

预计删除：

- 旧同名产品的所有 MCP 工具映射
- `refresh_files` / `refresh_workspace` Provider 操作和刷新规划分支
- 对旧映射的测试与文档说明

## 测试策略

所有行为改动使用 TDD，并覆盖：

1. 正式 descriptor 只指向 `github.com/colbymchenry/codegraph`。
2. 仓库受管代码、测试和文档中不存在旧 MCP 工具名。
3. `.codegraph/` 缺失时不调用外部工具并返回 `UNAVAILABLE`。
4. MCP explore 优先；MCP 缺失时使用 CLI explore。
5. healthy status 映射为 `CURRENT_AT_CHECK`。
6. pending changes 只触发一次 sync 和一次复查。
7. sync 后仍 pending 映射为 `INDEX_STALE`，且不循环。
8. worktree mismatch、partial/indexing/failed index、pending refs 和 reindex recommended 分别映射为准确 stale reason。
9. 多文件 stale banner 生成多个受限文件路径和 `PARTIAL_STALE`。
10. auto-sync-disabled banner 生成索引级 stale point。
11. malformed status、malformed response、timeout 和非零退出不会静默标记 current。
12. `READ_SOURCE` fallback 必须绑定当前普通文件 SHA-256。
13. 删除文件只能使用 `INSPECT_GIT_DIFF`；索引级失效使用 `SEARCH_SOURCE`。
14. `../`、绝对路径、错误 SHA 和越界 symlink 被拒绝。
15. v2 record 状态与 stale point 的组合满足所有一致性规则。
16. v1 record 在迁移后可审计但不能成为新阶段活跃 evidence。
17. Codex、Claude Code 和 vendored template 都包含相同回退语义。
18. Windows、macOS 和 Linux subprocess/path 行为通过平台无关模拟覆盖。
19. 真实 CodeGraph smoke test 仅在本机已有 CLI 时运行；CI 缺少 CLI 时明确 `SKIP`，不得误报失败。
20. 全量现有测试通过，vendored target 自包含校验继续通过。

## 验收标准

1. Polaris 代码库只存在一个正式 `codegraph` descriptor，且实现来源为 `colbymchenry/codegraph`。
2. 旧同名产品的具体工具名与刷新模型不再出现在受管实现、测试或用户文档中。
3. 已初始化且健康的仓库能通过 MCP 或 CLI 使用 CodeGraph。
4. 有 pending changes 时最多自动同步一次；没有固定等待或轮询。
5. CodeGraph 响应列出的 stale 文件会出现在 v2 record，并绑定源码或 Git diff 回退证据。
6. 整体索引异常会明确标记为 `INDEX_STALE` 或 `NOT_VERIFIED`，Agent 不会静默使用它作结论。
7. Provider 缺失、失败或未初始化不阻塞任何 Polaris workflow gate。
8. 新实现只使用 Python 标准库，并通过跨平台自动化测试。
9. 旧 v1 evidence 保持不可变和可审计，但不能被新阶段复用。
