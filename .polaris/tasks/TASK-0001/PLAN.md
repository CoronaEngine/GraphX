# Plan

## Change delta

1. 新增 `docs/USAGE.md`，作为面向项目使用者的完整中文操作手册。
   - 解释 Polaris 的职责、Git 权威边界以及它不会保存的瞬时状态。
   - 覆盖首次接入、自举、日常提需求前检查、需求表达模板、执行与 Human gate、R0/R1/R2、独立 Review、新会话恢复、换电脑恢复、升级和故障排查。
   - 所有命令、目录和状态名以当前仓库的 v0.1.1 脚本实现为准。
2. 更新 `README.md`，增加使用说明书入口；README 保持快速概览角色，不复制整份手册。

## Alternatives considered

- **把全部说明直接写进 README**：不采用。完整流程、恢复边界和 Review 规则会显著拉长 README，不利于新用户快速浏览，也不利于后续单独维护操作手册。
- **新增命令包装器或 CLI 来简化手册**：不采用。本任务是文档交付，且 MVP 明确不做 CLI；新增运行时行为超出冻结范围。

## Acceptance mapping

| Acceptance | Evidence |
|---|---|
| AC-01 | 静态检查手册含首次接入命令、三个生成目录及其 Git 提交要求；人工复核命令顺序。 |
| AC-02 | 静态检查“提出需求前”清单包含同步、工作区、仓库根目录和 Skills 发现。 |
| AC-03 | 静态检查需求模板、完整示例以及 Human-owned 决策说明。 |
| AC-04 | 静态检查 R0/R1/R2、状态路径、用户参与点以及禁止直接编辑状态文件的说明。 |
| AC-05 | 静态检查新会话 Review、handoff 和连续三次拒绝进入 BLOCKED 的说明。 |
| AC-06 | 静态检查同机新会话与新电脑恢复命令，并明确未提交编辑器/对话状态不可恢复。 |
| AC-07 | 检查 README 链接、文档路径和脚本路径存在；运行仓库自动化测试防止文档改动引入回归。 |

## Risks and documentation impact

- **命令漂移**：手册从当前 `scripts/` 与 `tools/polaris/scripts/` 的真实接口取值；验证时检查所引用脚本均存在。
- **源仓库与目标仓库混淆**：明确开发 Polaris 时使用 `scripts/`，目标仓库 vendoring 后使用 `tools/polaris/scripts/`。
- **过度承诺恢复能力**：明确 Git 可恢复已提交的权威状态，但不能恢复未提交文件、编辑器状态或完整聊天上下文。
- **绕过状态机**：手册只引导使用脚本和 Skills，不建议人工修改 `.polaris` 状态字段。
- **文档影响**：新增一份长期维护的用户文档，并在 README 建立稳定入口；不改变协议、Schema、Skills 或运行时代码。
