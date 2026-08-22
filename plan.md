# Polaris Clean-Slate 实施计划

> 状态：Architecture approved; implementation not started
>
> 产品形态：单任务、前台运行的受控 Agent Harness
>
> 核心目标：让 Agent 能够稳定、正确、可恢复地执行长时间软件工程任务
>
> 兼容策略：不兼容旧 Polaris，不提供旧任务、旧协议或旧版本迁移

## 1. 产品定义

Polaris 是围绕一个长任务运行的确定性监督器。它控制：

- 每次模型调用前构造什么 Context View；
- 模型提出的动作是否允许执行；
- 工具结果如何登记、持久化和恢复；
- 何时建立 durability checkpoint；
- 崩溃、上下文压缩或会话中断后如何继续；
- 任务何时有资格进入独立验证；
- 谁可以宣布任务完成。

模型负责语义工作：理解需求和代码、形成假设、选择方案、编写修改、分析失败并提出下一动作。

Polaris 负责事实、资源和生命周期：任务合同、运行状态、上下文路由、工具边界、provenance、checkpoint、恢复和完成门禁。

一句话定义：

> **Polaris 是一个为单个长任务维护可行动状态、受控上下文和可验证完成条件的 Agent Harness。**

## 2. 唯一目标与成功含义

Polaris 的唯一产品目标是提高长任务的正确完成率。

“稳定、正确执行”至少包含：

1. **合同不漂移**：目标、范围和硬约束不会被对话摘要或模型自行修改。
2. **状态不丢失**：任一已完成外部动作和下一动作在进入下一轮前已经持久化。
3. **上下文不污染**：模型只看到当前动作需要的高密度 Working Set。
4. **恢复不陈旧**：源码和工具观察绑定版本身份；恢复时能够区分历史内容与当前内容。
5. **失败有边界**：相同前置条件下的同一失败动作不会无界重复。
6. **Mutation 可解释**：每个工作区修改都有动作、输入、输出和前后版本。
7. **完成不自证**：执行模型只能提出完成候选，不能直接写入终态。
8. **中断可恢复**：进程退出后无需依赖旧聊天即可继续。

任何不能直接改善上述性质，或无法通过 benchmark 证明价值的机制，不进入第一版。

## 3. 第一版边界

### 3.1 必须实现

- 一个本地仓库中的一个活动任务；
- 一个前台运行、由 Polaris 控制的模型调用循环；
- OpenAI 这一个模型提供方，以及一个最小的内部 Model Client 边界；
- 冻结且可修订的 Task Contract；
- 原子 Runtime State 和 append-only Action Events；
- 每轮重新生成的 Context View；
- recoverability-aware Storage Policy；
- attention-aware Context Routing；
- 最小 Tool Gateway；
- mutation 前门禁和 mutation 后 Action Boundary；
- provenance、版本身份和 stale recovery 检测；
- event、state 和 durability checkpoint 三层持久化；
- 崩溃恢复和 ambiguous mutation 处理；
- 干净上下文中的独立 Verifier；
- microbenchmark、trace replay 和端到端长任务 benchmark。

### 3.2 明确不做

- 兼容旧 Polaris 文件、任务、命令、版本或迁移；
- Codex、Claude Code 等多宿主 Skill 适配；
- 通用 Agent Runtime、插件市场或任意工具平台；
- 多任务调度、Task DAG、队列、scheduler 或 daemon；
- 多项目管理、远程执行、自动 push、merge 或发布；
- Dashboard、TUI、IDE 或复杂交互界面；
- 数据库、向量库或知识图谱服务；
- R0/R1/R2 治理等级；
- 多阶段 Workflow Skills；
- Implementation/Review handoff 文件体系；
- Documentation Sync、Knowledge Delta 或 Failed Exploration 提升流程；
- 安装清单、vendoring、Doctor 或协议迁移；
- Windows、macOS、Linux 同时产品化。

第一版只支持 macOS 上的可信本地仓库。可移植性只有在核心机制通过真实 benchmark 后再处理。

## 4. 核心不变量

以下规则必须由代码和测试保证，不能只依赖 prompt：

1. 模型不能直接写 Task Contract、Runtime State 或终态。
2. 所有有副作用动作由 Polaris 串行执行。
3. 每次 mutation 后，下一次模型调用前必须形成耐久 Action Boundary。
4. 多个只读动作只有在目的相同且无副作用时才允许并行。
5. 所有工具结果必须记录来源、参数、结果和恢复路径。
6. 引用可变仓库内容时必须记录 source identity 和 version identity。
7. Dirty semantic state 在 eviction、compaction、暂停或退出前必须落盘。
8. 相同 action fingerprint 在前置条件不变时，第三次执行前必须触发重复失败门禁。
9. 进程恢复时不得盲目重放状态未知的 mutation。
10. 只有 Controller 在 Verifier 通过后可以写入 DONE。

## 5. 总体架构

~~~text
Human
  ↓
Task Contract
  ↓
Polaris Controller
  ├── Runtime State / Event Store
  ├── Context Manager
  ├── Model Client
  ├── Action Gate
  ├── Tool Gateway
  ├── Checkpoint / Recovery
  └── Independent Verifier
        ↓
Local Repository + Tests + Git
~~~

### 5.1 Task Contract

保存人类意图的唯一权威版本：

- goal；
- motivation；
- scope in/out；
- hard constraints；
- acceptance criteria；
- human-owned decisions；
- revision。

合同冻结后不得静默覆盖。目标、范围、硬约束或验收标准变化时创建新 revision，并使旧完成候选失效。

### 5.2 Controller

拥有执行循环和状态转换。它接收模型动作，执行门禁，调用工具，持久化事实，并决定继续、等待、验证或终止。

Controller 不承担代码语义判断，也不实现通用任务规划器。

### 5.3 Context Manager

内部严格分成两层：

- **Storage Policy**：决定信息是否持久、能否恢复、恢复成本和版本身份。
- **Attention Policy**：决定当前模型调用应该看到什么、放在哪里以及占用多少预算。

Stored State 不等于 Model-visible State。模型看到的是权威状态生成的临时 projection。

### 5.4 Model Client

只负责：

- 接收构造完成的 Context View；
- 调用一个具体模型提供方；
- 返回标准化的模型消息和工具调用；
- 记录模型、用量、延迟和请求身份。

第一版只有 OpenAI Model Client 这一个实现。该边界用于隔离外部 API，不建设多模型适配平台。

### 5.5 Tool Gateway

第一版仅提供：

- 文件局部读取；
- 代码或文本搜索；
- Patch 应用；
- Shell 命令；
- Git 状态和 diff 查询。

测试、构建和静态检查通过 Shell 调用现有项目工具。模型不能绕过 Tool Gateway 直接接触文件系统或进程。

### 5.6 State Store

使用普通文件而不是数据库：

~~~text
.polaris/
├── task.json
├── state.json
├── events.jsonl
├── memory/
├── outputs/
└── checkpoints/
~~~

- task.json：当前冻结 Task Contract。
- state.json：当前可行动状态的原子 snapshot。
- events.jsonl：append-only 动作和状态事实。
- memory/：不可可靠重建或恢复昂贵的语义。
- outputs/：大型工具输出及其 hash。
- checkpoints/：阶段性 durability metadata。

目录和文件只在实际实现需要时创建；不要预先建设模板系统。

### 5.7 Independent Verifier

Verifier 使用冻结合同、最终工作区事实和证据，在干净上下文中运行。它只读审查，不能修改 subject。

Verifier 负责：

- 逐项检查 acceptance criteria；
- 运行或核对确定性证据；
- 检查越界修改；
- 检查未解释的工作区变化；
- 构造关键反例；
- 输出 PASS 或结构化返工要求。

Controller 验证 Verifier 输出后才能写入 DONE。

## 6. 受控执行循环

每轮执行：

~~~text
Load authoritative state
→ Build minimal Context View
→ Call model
→ Normalize proposed action
→ Check action gate
→ Execute tool or control action
→ Capture provenance and workspace effects
→ Append event
→ Atomically update state
→ Continue / Wait / Verify
~~~

模型输出被归一为四类：

- TOOL：请求文件、搜索、Patch、Shell 或 Git 操作；
- CHECKPOINT：提交 root cause、约束、不变量、假设或决策理由；
- ASK_USER：请求必须由人提供的信息或授权；
- PROPOSE_DONE：提交完成候选。

### 6.1 Action Boundary

一次 Action Boundary 至少绑定：

- run ID；
- action ID；
- action type 和 fingerprint；
- state version；
- workspace version before/after；
- tool input；
- result、exit code 和 output reference；
- changed paths；
- recovery status；
- next action。

有副作用动作一次只执行一个。只读批次可以并行，但必须共享一个明确目的，并分别登记结果。

### 6.2 Action Gate

执行前机械检查：

- 路径是否位于允许仓库；
- 动作是否超出 Task Contract；
- 是否触碰高风险或不可逆边界；
- 模型看到的 workspace version 是否仍然有效；
- 前一 mutation 是否已经完成持久化；
- 是否存在 unresolved ambiguous action；
- 是否在无新条件下重复相同失败动作；
- 当前动作是否需要 foreground 特定约束。

Action Gate 判断合法性，不判断方案质量。

## 7. Context Management

### 7.1 Context Item

内部 Context Item 至少包含：

- stable ID；
- kind；
- content 或 backing reference；
- provenance；
- source version；
- recoverability；
- recovery cost；
- freshness；
- salience；
- phase/action tags；
- pin level；
- dirty flag。

### 7.2 Recoverability

第一版使用三档：

- EXACT：有明确来源和版本，可精确恢复；
- EXPENSIVE：理论可重建，但需要显著调试或计算；
- POOR：无法可靠从仓库重新推导。

策略：

~~~text
EXACT + cheap
→ aggressive eviction

EXPENSIVE
→ persist high-density semantic result

POOR + high impact
→ persistent pin
~~~

### 7.3 Attention Tiers

- **Tier 0 — Authoritative Core**：goal、当前相关硬约束、acceptance、active blocker。
- **Tier 1 — Foreground Set**：当前 action 直接需要的信息。
- **Tier 2 — Hot Working Set**：近期源码、观察和调试结果。
- **Tier 3 — Recoverable Cache**：只在需要时 fault-in。
- **Tier 4 — Archive**：日志、旧证据和历史事件。

Tier 0 的内容长期存在，但只把与当前 action 相关的 projection 放进模型请求。

### 7.4 Routing

机械 routing 优先：

- phase/action tag；
- changed path；
- tool type；
- risk kind；
- constraint scope；
- freshness；
- provenance match。

第一版不增加额外 LLM 调用来选择上下文。语义判断只用于模型在正常执行过程中主动提交的 CHECKPOINT。

### 7.5 Context Pressure

发生上下文压力时：

1. 扫描 Dirty items；
2. 持久化没有 backing store 的关键语义；
3. 淘汰 EXACT 且恢复便宜的内容；
4. 将大型输出替换为引用；
5. 检查引用是否 stale；
6. 重新生成最小 Context View。

PreCompact 是最后安全屏障，不是整个 Context Manager。

## 8. 状态、事件与恢复

### 8.1 最小状态

业务状态只保留：

- READY
- RUNNING
- WAITING
- VERIFYING
- DONE
- CANCELLED

调查、实现、测试等属于 active action kind，不扩展成治理状态机。

state.json 必须直接回答：

- 当前目标是什么；
- 当前状态是什么；
- 当前动作是什么；
- 已完成的关键 checkpoint 是什么；
- blocker 是什么；
- next action 是什么；
- 当前 workspace version 是什么。

### 8.2 Event Store

每个事件包含连续 sequence、时间、run/action identity、类型和 payload。至少记录：

- run start/resume；
- model request/result metadata；
- tool prepared/started/succeeded/failed；
- workspace changed；
- semantic checkpoint；
- user correction；
- state transition；
- verification verdict；
- cancellation。

state snapshot 与事件不一致时，从有效事件重建 state；不得猜测或跳过损坏事件。

### 8.3 Action 生命周期

Mutation 使用：

- PREPARED
- RUNNING
- SUCCEEDED
- FAILED
- AMBIGUOUS

如果进程在 RUNNING 后中断，恢复时先检查工作区事实：

- 能证明未执行：允许重新执行；
- 能证明已完成：补写结果；
- 无法证明：进入 AMBIGUOUS，停止自动 mutation 并请求检查。

不得盲目重放。

### 8.4 Durability

三层持久化：

1. **Action Event**：每次工具调用追加；
2. **Runtime State**：每个可观测动作后原子替换；
3. **Durability Checkpoint**：重要语义、阶段变化、高风险修改、上下文压力、暂停或退出时写入。

Git commit 只在项目本身需要阶段 checkpoint 时创建，不是每个 Action Boundary 的默认成本。

## 9. 失败处理

工具或测试失败时：

1. 失败先成为权威事实；
2. 保存命令、环境、退出码、输出引用和 workspace version；
3. 判断是否产生新 observation；
4. 更新假设、next action 或 blocker；
5. 在条件未变化时阻止第三次相同 action fingerprint。

失败只有三种出口：

- 改变假设后继续；
- 请求用户或外部条件；
- 进入 WAITING 并记录 blocker。

不设置通用 FAILED 终态；人工放弃使用 CANCELLED。

## 10. 完成与验证

模型不能直接完成任务：

~~~text
PROPOSE_DONE
→ Freeze completion candidate
→ Build clean verification context
→ Run deterministic evidence
→ Run independent verifier
→ PASS / return structured corrective action
~~~

验证结果必须绑定：

- Task Contract revision；
- workspace version；
- final diff；
- acceptance criterion；
- evidence command/check；
- result 和 output reference。

任一验收项失败、越界修改、工作区事实变化或证据失效都会返回 RUNNING，并生成明确 next action。

## 11. 安全边界

第一版运行在可信本地仓库，但仍必须：

- 拒绝工作区路径逃逸；
- 默认拒绝明显不可逆或超范围命令；
- 对删除、覆盖、权限、凭据和网络副作用设置显式门禁；
- 不把秘密写入 events、outputs 或模型上下文；
- 限制单次工具输出大小和运行时间；
- 记录所有 mutation；
- 在用户已有无关改动存在时避免混入任务修改。

不建设完整沙箱；安全范围只覆盖实现核心目标所需的本地执行边界。

## 12. 代码边界

计划中的最小结构：

~~~text
src/polaris/
├── contract/
├── runtime/
├── state/
├── context/
├── tools/
└── verification/

tests/
├── unit/
├── traces/
└── end_to_end/

benchmarks/
├── tasks/
├── traces/
└── runner/
~~~

只有在对应模块进入当前 milestone 时才创建目录。

实现语言为 Python。运行时依赖不再要求标准库-only，但任何依赖必须直接服务模型调用、可靠性或测试，并锁定版本。第一版不引入 Web 框架、ORM、任务队列或向量数据库。

## 13. 测试策略

### 13.1 Unit

- Task Contract freeze/revision；
- state 原子写入和 event replay；
- action lifecycle；
- action fingerprint 和重复失败门禁；
- provenance/version identity；
- Context Item 分类；
- routing、pin、budget 和 eviction；
- stale recovery；
- completion authority；
- path 和 mutation gate。

### 13.2 Trace Replay

用确定性模型和工具替身重放：

- 正常多轮任务；
- 每个 Action Boundary 注入崩溃；
- mutation 中断；
- event 写入中断；
- state snapshot 损坏；
- 文件在 eviction 后变化；
- 上下文压力；
- 用户中途修改合同；
- 重复失败；
- verifier reject 后返工。

### 13.3 End-to-End

使用同一模型、工具权限和任务预算比较：

- baseline Agent；
- Polaris 受控 Agent；
- 关闭 Context Routing 的 Polaris；
- 关闭 Recovery Policy 的 Polaris。

至少覆盖：

- 多文件实现任务；
- 长调试任务；
- 早期硬约束在后期才相关的任务；
- 中途进程退出并恢复的任务；
- 存在误导性旧日志或旧源码的任务；
- 模型过早宣布完成的任务。

## 14. 第一版指标

机械指标：

- Action Boundary 崩溃恢复正确率：100%；
- Hard Constraint 持久化存活率：100%；
- stale recovery 检出率：100%；
- 未经 Verifier 写入 DONE：0；
- 工作区外 mutation：0；
- 无新前置条件下同一失败动作执行超过两次：0；
- Context Routing 额外 LLM 调用：0。

端到端 release gate：

- 长任务正确完成率相对 baseline 提升至少 10 个百分点；
- 关键约束违反率相对 baseline 至少降低 50%；
- 中断恢复任务正确完成率至少 95%；
- 每个成功任务的输入 token 不超过 baseline 的 110%；
- Context Manager 自身 wall-time overhead 低于 5%，不含模型、工具和独立验证时间。

长期优化目标是在不降低正确完成率的前提下，将每个成功任务的输入 token 相对 baseline 降低至少 20%。

## 15. 实施里程碑

### M0 — 权威重置与 Benchmark 定义

- 重写 plan.md、AGENTS.md、README、package metadata 和 CI；
- 定义 Task Contract、Runtime State、Action Event 和 Context Item；
- 建立 baseline 任务、trace 和指标计算；
- 写出核心不变量的失败用例。

完成标准：旧架构引用为零；benchmark 可以在无 Polaris 机制时运行并产生 baseline。

### M1 — Durable Runtime Kernel

- 实现 State Store、Event Store 和 replay；
- 实现单模型 Model Client；
- 实现 Controller 和标准化动作；
- 实现最小只读工具；
- 用模拟模型完成多轮无 mutation trace。

完成标准：进程可在任一只读 Action Boundary 后恢复，并产生一致状态。

### M2 — Mutation Boundary

- 增加 Patch、Shell 和 Git 工具；
- 实现 Action Gate；
- 实现 mutation lifecycle 和 workspace version；
- 处理 ambiguous mutation；
- 增加路径、超时、输出和破坏性动作限制。

完成标准：所有 mutation 可追溯；故障注入不会盲目重放未知动作。

### M3 — Context Manager

- 实现 provenance tracking；
- 实现 recoverability 和 dirty/clean classification；
- 实现 Attention Tier、budget 和机械 routing；
- 实现 eviction、fault-in 和 stale detection；
- 实现 checkpoint 与恢复头。

完成标准：microbenchmark 和 trace replay 达到第 14 节机械指标。

### M4 — Verification Gate

- 实现 PROPOSE_DONE；
- 冻结 completion candidate；
- 构造干净验证上下文；
- 运行 acceptance evidence；
- 实现只读 Verifier 和返工动作。

完成标准：任何测试 trace 都无法绕过 Verifier 写入 DONE。

### M5 — Long-Task Evaluation

- 运行 baseline、完整 Polaris 和 ablation；
- 统计成功率、约束违反、恢复、token、latency；
- 分析失败样本；
- 删除无收益机制；
- 只在达到 release gate 后开始产品化。

完成标准：第 14 节端到端 release gate 全部满足，或明确记录未满足项并停止扩展范围。

## 16. 开工顺序

严格按以下顺序：

1. 冻结最小数据模型和 failure traces；
2. 先写 Event/State replay 测试；
3. 实现只读 Controller loop；
4. 加入 mutation lifecycle；
5. 加入 Context Manager；
6. 加入 Verifier；
7. 最后接真实模型跑端到端任务。

不要先实现 CLI 体验、多宿主、安装、迁移、UI 或并行 Agent。

## 17. 当前仓库状态

refactor 分支已经删除旧 Polaris 的 Skills、Schemas、Scripts、Templates、Workflow、Tests、Hosts 和使用文档。旧实现仅存在于 Git 历史中，不建立 legacy/ 副本。

当前保留文件将按 M0 重写。删除不代表新系统已经可运行；在 M1 之前仓库处于预期的 clean-slate 状态。

## 18. 产品决策规则

新增机制前必须回答：

1. 它针对哪一种已观察到的长任务失败？
2. 它由 Harness 机械完成还是要求模型记住？
3. 如何单独 benchmark？
4. 它增加多少 token、latency 和复杂度？
5. 如果没有显著收益，能否完整删除？

无法回答的问题不进入第一版。

## 19. 一句话目标

> **让 Agent 在长任务中始终知道目标、状态和下一动作；在失败后能够恢复；在真正满足验收前无法宣布完成。**
