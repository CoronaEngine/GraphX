# Polaris 工作流精简设计

## 状态

已批准方向：实施仓库审核中识别出的工作流精简项。

目标协议版本：`0.1.20`
目标工作流版本：`0.1.3`

## 问题

当前 `0.1.2` 工作流保留了严格的治理边界，但部分持久状态和门禁并没有引入新的 Authority、证据或人工决策。最突出的问题是：`runtime/progress.json` 中的本地瞬时遥测被设为耐久 `FINISH_IMPLEMENTATION` 转换的硬前提，而协议同时又声明 runtime 状态不参与阶段门禁或 Fresh Clone 恢复。

Happy path 还包含多组可以合并的相邻机械转换：

- `START_IMPLEMENTATION` 后紧接 `DISPATCH_IMPLEMENTATION` 自转换；
- `FINISH_IMPLEMENTATION` 后续接同一个 Implementer 执行 `SYNC_DOCS`；
- `ACCEPT_REVIEW` 后紧接 `START_VALIDATION`，且两次检查相同 Review；
- R0/R1 的 `PASS_VALIDATION` 后紧接 `CLOSE`，中间不存在最终人工批准。

Code Intelligence 是可选、非阻断能力，但当前每个阶段即使 Provider 未使用，也会写入 unavailable 或 skipped 记录。这会产生耐久噪声，却不会增强任何门禁。

此外，产品 Authority 规定关闭任务前必须完整通过任务校验，但当前实现的关闭门禁只检查 Result 和可选的 R2 最终批准。

## 目标

1. 删除没有独立治理边界的持久状态和转换。
2. 将 ignored 的实时进度降为可选遥测，而不是耐久 Authority。
3. 保留 Work Item、Plan 决策、Implementation handoff、Implementation、Knowledge Delta、Review handoff、Review、Validation、Result、事件账本和状态投影等耐久产物。
4. 保持独立 Review 与基于验收标准的 Validation 为两个不同阶段。
5. 仅为等待 R2 最终人工批准保留显式 `VERIFIED` 状态。
6. 在提交关闭转换前，完整校验候选任务投影。
7. 提供从工作流 `0.1.2` 到 `0.1.3` 的显式、可恢复迁移。
8. 运行时继续只依赖 Python 标准库。

## 非目标

- 删除独立 Implementer 或 Reviewer 的隔离要求。
- 删除 Work Item 确认、Plan 决策、Knowledge Delta、Review 或 Validation。
- 引入 daemon、scheduler、Task DAG、数据库或自定义 Agent Runtime。
- 自动 push、merge、发布或编排远程 CI。
- 改写或删除历史 artifact 或事件。

## 备选方案

### 方案 A：只修改 Skills 和文档

这可以减少对话层面的仪式，但持久工作流和门禁仍保持不变。已有冻结工作流的项目仍然必须执行旧转换，而且 ignored progress 的硬门禁仍然存在。

不采用，因为它没有解决机械层面的冗余。

### 方案 B：保留所有状态，但自动串联转换

Controller 可以在前一个转换后立即执行 `DISPATCH_IMPLEMENTATION`、`START_VALIDATION` 和 `CLOSE`。这能减少用户可见的暂停，但仍然保留重复事件、重复校验、中间 checkpoint commit，以及没有独立含义的恢复状态。

不采用，因为它只是隐藏复杂度，没有消除复杂度。

### 方案 C：升级版本并精简工作流

引入工作流 `0.1.3`，删除冗余状态和事件，解除遥测依赖，并显式迁移已有任务。

采用该方案，因为它让持久控制流与真实治理边界保持一致，同时保留可审计性。

## 目标工作流

普通持久主路径调整为：

```text
DRAFT → QUALIFIED → PLANNED → IMPLEMENTING
      → REVIEWING → VALIDATING → CLOSED
```

R2 增加最终批准状态：

```text
VALIDATING → VERIFIED → CLOSED
```

工作流 `0.1.3` 删除 `IMPLEMENTED`、`DOCS_SYNCED` 和 `REVIEWED` 状态。

以下治理回路保持不变：

```text
REVIEWING  -- REJECT_REVIEW --> IMPLEMENTING
VALIDATING -- FAIL_IMPLEMENTATION --> IMPLEMENTING
VALIDATING -- FAIL_PLAN --> PLANNED
任意非终态 -- NEW_REVISION --> QUALIFIED
任意非终态 -- BLOCK --> BLOCKED
BLOCKED -- RESOLVE_BLOCK --> blocked_from
任意非终态 -- CANCEL --> CANCELLED
```

`review_dispute` 是 `RESOLVE_BLOCK` 的例外：同一 revision 的 Review 达到最大 attempt 后，任务保持 Human-owned `BLOCKED`，只能通过 `NEW_REVISION` 或 `CANCEL` 离开，不能开启第 4 次 attempt。

## 转换设计

### 开始 Implementation

`START_IMPLEMENTATION` 首次执行 `PLANNED → IMPLEMENTING`；Review 或 Validation 返工时执行 `IMPLEMENTING → IMPLEMENTING` 自转换。两种情况都要求在同一次转换中提交当前 attempt 的 Implementation handoff。门禁合并检查：

- R2 实施前批准；
- handoff 的身份、revision、attempt、Plan、Working Set 和 package。

删除 `DISPATCH_IMPLEMENTATION`。handoff 注册后由宿主执行 Worker 派发；Worker 派发是宿主动作，不是持久工作流状态。

### 完成 Implementation 并开始 Review

Implementer 返回前完成代码、测试、必要项目文档、最终检查、Implementation artifact 和 Knowledge Delta。两个 artifact 绑定相同的最终 subject commit 和 diff hash。

主 Controller 随后构建不可变 Review handoff，并直接从 `IMPLEMENTING` 执行 `START_REVIEW`。该转换注册：

- `implementation`；
- `knowledge_delta`；
- `review_handoff`；
- 最终 subject base/head commits。

合并后的门禁检查 Implementation handoff 绑定、Implementation artifact、Knowledge Delta、文档影响、最终 subject 和 Review handoff，然后执行 `IMPLEMENTING → REVIEWING`。

Documentation 前不再创建单独的 Implementation checkpoint commit。最终 subject checkpoint 已同时包含代码、测试、构建配置和项目文档。

### 接受 Review 并开始 Validation

`ACCEPT_REVIEW` 只校验一次全部必需 Review artifact，并执行 `REVIEWING → VALIDATING`。删除 `START_VALIDATION`。Validation 仍是独立阶段，并生成新的不可变 Validation artifact。

### Validation 通过并关闭

使用两个显式通过事件，避免在代码中隐藏条件目标状态：

- `PASS_AND_CLOSE`：只允许 R0/R1 使用；注册 Validation 和 Result，完整校验候选 CLOSED 投影，然后执行 `VALIDATING → CLOSED`。
- `PASS_VALIDATION`：只允许 R2 使用；注册 Validation，校验全部验收标准，然后执行 `VALIDATING → VERIFIED`。

R2 随后记录最终人工批准和 Result，再通过 `CLOSE` 执行 `VERIFIED → CLOSED`。两个关闭路径都必须在追加事件前调用相同的完整候选任务校验器。

## 候选投影校验

重构任务校验，使相同规则既可以校验：

- 当前保存在 `state.json` 中的投影；或
- `transition_task.py` 在追加事件前准备的候选投影。

公开的 `validate_task.py` 命令继续校验已保存状态和事件重建结果。关闭门禁使用拟议的 CLOSED 状态及已注册 artifact 调用共享候选校验器。不得先追加 CLOSED 事件再进行事后校验。

这会消除 `plan.md` 与当前 `closure_ready` 实现之间的偏差，同时避免复制第二套关闭规则。

## Implementation 实时进度

`runtime/progress.json` 继续供能够展示实时进度的宿主使用，但明确降为 best-effort、可选遥测：

- 继续保持 Git ignored；
- 文件缺失不得阻断 `START_REVIEW`、恢复或关闭；
- R0 不要求初始化或写入步骤事件；
- R1/R2 可以使用有序步骤展示状态，但最终 Implementation artifact 才是 Authority；
- 如果存在有效 progress 快照，Controller 可以将其与 Implementation summary 对比，并把不一致报告为警告，而不是转换失败；
- Implementation `step_results` 继续作为必填耐久摘要，由 Implementer 直接写入 Implementation artifact。

使用 progress updater 时，它仍然拒绝损坏或冲突的更新。其本地状态机不属于项目工作流图。

## Code Intelligence 记录

Code Intelligence 继续保持可选、在 artifact 边界上 Provider-neutral，并且非阻断。

- 阶段没有执行 query 或与 freshness 有关的操作时，artifact 可以省略 Code Intelligence 引用。
- marker 缺失、策略禁用，或当前会话已经确认 Provider 不可用时，不要求生成新的耐久阶段记录。
- 只有阶段实际执行 Provider status、sync 或 explore，且结果具有审计价值时，才写入耐久记录。
- Provider 证据过期或不足时，仍必须执行源码和 Git 回退。
- Validation 继续禁止把 Code Intelligence 当作验收证据。

历史 v1 和 v2 记录保持不可变、可读取。

## 从工作流 0.1.2 迁移

协议 `0.1.20` 增加能够替换冻结工作流并映射任务投影的显式迁移策略。迁移继续保持相邻、append-only、可恢复且受锁保护。

状态映射如下：

| 旧状态 | 新状态 |
|---|---|
| `DRAFT` | `DRAFT` |
| `QUALIFIED` | `QUALIFIED` |
| `PLANNED` | `PLANNED` |
| 已注册 handoff 的 `IMPLEMENTING` | `IMPLEMENTING` |
| 未注册 handoff 的 `IMPLEMENTING` | `PLANNED` |
| `IMPLEMENTED` | `IMPLEMENTING` |
| `DOCS_SYNCED` | `IMPLEMENTING` |
| `REVIEWING` | `REVIEWING` |
| `REVIEWED` | `VALIDATING` |
| `VALIDATING` | `VALIDATING` |
| R0/R1 `VERIFIED` | `VALIDATING`，允许通过 `PASS_AND_CLOSE` 重新提交现有 Validation 与 Result |
| R2 `VERIFIED` | `VERIFIED` |
| `BLOCKED` | `BLOCKED`，并按相同规则映射 `blocked_from` |
| `CLOSED` | `CLOSED` |
| `CANCELLED` | `CANCELLED` |

保留全部 artifact。`DOCS_SYNCED → IMPLEMENTING` 使新 `START_REVIEW` 门禁能够复用已有 Implementation 和 Knowledge Delta，只生成缺失的 Review handoff。`IMPLEMENTED → IMPLEMENTING` 允许同一个 Implementer 完成文档工作，而不依赖 ignored progress 文件。

每个迁移任务追加一个 `MIGRATE_POLARIS` 事件，其中包含新旧协议版本、新旧工作流版本和新旧状态。迁移记录保存转换前后的 event sequence 和映射状态。重跑时复用已追加且匹配的事件，并拒绝不一致的部分状态。

## Authority 与 artifact 兼容性

- 历史 `events.jsonl` 可以包含已删除的状态；这些仍是合法历史事件。
- 重建出的当前投影使用最终迁移事件和工作流 `0.1.3`。
- 不得仅为了采用新工作流而改写已有不可变 artifact。
- 新 Implementation 和 Knowledge Delta 绑定同一个最终 subject。
- `state.json` 继续只保存当前 artifact 指针。
- Result 继续作为耐久关闭摘要；R0/R1 Controller 在 `PASS_AND_CLOSE` 前生成 Result，不再经过单独的 VERIFIED checkpoint。

## Skills 与用户对话契约

稳定的九字段 Polaris 状态块保持不变。新工作流任务不再输出已删除的阶段标记：

- `IMPLEMENTATION_FINISHED` 和 `DOCS_SYNCED` 合并为最终 subject 就绪后的 `REVIEW_HANDOFF_READY`；
- `REVIEW_ACCEPTED` 报告状态 `VALIDATING`，并立即把 Validation 标记为下一动作；
- R0/R1 的 Validation PASS 与成功关闭属于同一次转换结果，因此 Controller 只输出 `TASK_CLOSED`；
- R2 仍在 `VERIFIED` 输出 `VALIDATION_PASS`，并请求最终批准。

恢复建议和用户文档同步更新为新的状态及合法下一动作。

## 测试策略

必须先编写测试，再修改实现，并覆盖：

1. `START_IMPLEMENTATION` 原子注册并校验 handoff。
2. `DISPATCH_IMPLEMENTATION` 不再存在且会被拒绝。
3. 缺少 `runtime/progress.json` 不阻断最终 Implementation-to-Review 转换。
4. `START_REVIEW` 必须检查匹配的 Implementation、Knowledge Delta、文档检查、最终 subject 和 Review handoff。
5. Implementation 与 Knowledge Delta 绑定相同最终 subject。
6. `ACCEPT_REVIEW` 直接进入 `VALIDATING`；`START_VALIDATION` 不再存在。
7. R0/R1 `PASS_AND_CLOSE` 要求 Validation、Result 和完整候选任务校验通过。
8. R2 禁止使用 `PASS_AND_CLOSE`，通过 `PASS_VALIDATION` 进入 `VERIFIED`，关闭前仍要求最终批准。
9. 未使用 Code Intelligence 时允许省略引用；存在记录时仍执行完整校验。
10. 所有旧工作流状态都能确定性迁移，包括 `BLOCKED.blocked_from` 和未注册 handoff 的旧 `IMPLEMENTING` 边界情况。
11. 中断迁移可恢复，且不会重复追加事件。
12. 文档、模板、Schema、宿主渲染 Skills 以及完整 R1/R2 流程都与工作流 `0.1.3` 一致。

完成前必须运行完整仓库测试、compile 检查、模板物化检查和 clean-worktree 检查。

## 成功标准

- 新 R1 happy path 在 Planning 后只需要一次开始 Implementation 转换、一次开始 Review 转换、一次 Review 接受转换和一次通过并关闭转换。
- ignored runtime 文件不再是任何耐久门禁的前提。
- Review 和 Validation 继续保留独立证据。
- R2 保留两个人工批准门禁。
- 已有 `0.1.2` 项目拥有显式相邻迁移路径。
- `validate_task.py` 与关闭转换共享同一套合法性实现。
- 全部测试通过，运行时代码只使用 Python 标准库。
