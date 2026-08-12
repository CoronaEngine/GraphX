# Polaris

Polaris is a repo-native AI engineering workflow system built on Codex Skills, repository authority state, and deterministic Python validation.

v0.1 intentionally has no CLI, daemon, scheduler, database, Dashboard, or custom Agent Runtime. A target repository vendors:

- `.agents/skills/` for the seven workflow Skills;
- `tools/polaris/` for scripts, schemas, templates, and the default Workflow;
- `.polaris/` for project and task authority state.

## Development checks

```text
python tests/run_tests.py
```

该运行器会为每个场景打印开始、验证目标、PASS/FAIL、耗时，并在末尾输出完整汇总。需要原生 `unittest` 输出时仍可运行 `python -m unittest discover -s tests -v`。

See [plan.md](plan.md) for the complete v0.1 implementation plan and governance model.
