# GraphX 测试

测试由 pytest 执行，`run_tests.py` 仅提供适合手动查看的中文报告。
产品语义与测试门槛以 [plan.md 第 14 节](../plan.md#14-测试门槛) 为准。

## 环境与入口

VS Code 用户可以直接打开仓库根目录的 [run_tests.py](../run_tests.py)，点击右上角“运行 Python 文件”。这个启动入口只使用标准库，并自动调用 `.venv` 中的 Python 执行本目录的中文报告入口；不需要先激活虚拟环境。已有 `.venv` 时无需其他准备。

在仓库根目录首次准备环境（已有 `.venv` 可跳过）：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

运行全部测试：

```bash
.venv/bin/python tests/run_tests.py
```

也可以先 `source .venv/bin/activate`，再运行 `python tests/run_tests.py`。
Windows 使用 `.venv\Scripts\python.exe` 替代 `.venv/bin/python`。
入口以仓库根目录解析相对路径，其余参数交给 pytest：

```bash
# 按目录或文件选择
.venv/bin/python tests/run_tests.py tests/unit/protocol
.venv/bin/python tests/run_tests.py tests/unit/test_phase1_acceptance.py

# 按函数名、requirement ID 或参数 ID 筛选
.venv/bin/python tests/run_tests.py -k auth_01
.venv/bin/python tests/run_tests.py -k task-too-long

# 第一次失败即停止 / 仅列出测试
.venv/bin/python tests/run_tests.py -x
.venv/bin/python -m pytest --collect-only -q
```

报告按文件分组，每行显示场景、参数 ID、状态和该阶段耗时。例如：

```text
[PASS] Agent 策略与文本必须符合重试、超时和长度限制。 [task-too-long] — 0.001s
```

`PASS` 表示通过，`FAIL` 表示断言失败，`ERROR` 表示准备、清理或收集错误。
`SKIP`、`XFAIL`、`XPASS` 分别表示跳过、预期失败、意外通过，单独统计。
如果测试主体通过但清理失败，会同时记录 PASS 和 teardown ERROR；汇总按报告计数，
最终仍返回失败。pytest 的失败详情和短摘要保留原始用例定位信息。

退出码沿用 pytest：0 正常结束，1 测试失败，2 中断或收集错误，3 内部错误，
4 命令用法错误，5 未找到测试。退出码 0 可能包含跳过或预期失败，请同时查看汇总。
当前阶段没有真实 Codex 派发或完整工作流的端到端验证。

## 质量检查

```bash
.venv/bin/python -m pyright
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m pytest -q
```

原生 pytest 始终可用，CI 可直接使用它，无需中文报告入口。

## 新增测试

- 按被测层放入 `unit/core`、`unit/protocol`、`unit/adapters` 或 `unit/architecture`。
- 用测试名称或 metadata 引用 requirement ID / plan 章节。
- 函数首行 docstring 用一句中文说明实际验证的行为；入口会读取它，缺失时回退到用例 ID。
- 参数化测试用短而有意义的 `ids=[...]` 或 `pytest.param(..., id="...")`；
  尤其不要把超长字符串直接作为默认显示名称。
- 名称和说明应反映断言实际提供的保证；提示词存在检查不能证明真实派发或隔离行为。
- 保留边界值、拒绝路径和实际副作用断言，不为改善显示而删减测试数据。
- 报告器的回归测试在 `unit/test_test_runner.py`，通过子进程验证真实入口及退出码。
