# Working Set

Generated for `TASK-0001@r001`. Entries are `path — reason — discovered_from`.

## Documents

- `.polaris/project-index.md` — bounded project recovery map — recovery bootstrap
- `.polaris/tasks/TASK-0001/PLAN.md` — delta plan and acceptance mapping — task state
- `.polaris/tasks/TASK-0001/revisions/work-item-r001.json` — frozen execution contract — task state
- `AGENTS.md` — project rules — recovery bootstrap
- `README.md` — current user-facing overview and command reference — work-item AC-07

## Code

- `README.md` — affected module entry point — work-item.affected_modules
- `docs/USAGE.md` — affected module entry point — work-item.affected_modules
- `scripts/build_review_handoff.py` — authoritative reviewer handoff command — work-item AC-05
- `scripts/init_project.py` — authoritative project initialization behavior — work-item AC-01
- `scripts/init_task.py` — authoritative task initialization behavior — work-item AC-04
- `scripts/record_exploration.py` — authoritative failed exploration interface — work-item operational reference
- `scripts/recover_task.py` — authoritative fresh-session recovery command — work-item AC-06
- `scripts/transition_task.py` — authoritative workflow transition interface — work-item AC-04
- `scripts/vendor_project.py` — authoritative vendoring behavior and flags — work-item AC-01

## Tests

- `<AC-01-evidence>` — 检查 docs/USAGE.md 的首次接入和 Git 提交章节 — work-item.acceptance.AC-01
- `<AC-02-evidence>` — 检查 docs/USAGE.md 的提出需求前检查清单 — work-item.acceptance.AC-02
- `<AC-03-evidence>` — 检查 docs/USAGE.md 的需求模板和示例 — work-item.acceptance.AC-03
- `<AC-04-evidence>` — 检查 docs/USAGE.md 的任务执行章节 — work-item.acceptance.AC-04
- `<AC-05-evidence>` — 检查 docs/USAGE.md 的独立审查章节 — work-item.acceptance.AC-05
- `<AC-06-evidence>` — 检查 docs/USAGE.md 的恢复与跨电脑章节 — work-item.acceptance.AC-06
- `<AC-07-evidence>` — 检查 README 链接并运行文档命令/路径静态校验 — work-item.acceptance.AC-07

## Decisions

- None

## Explorations

- None

## Unknowns

- None
