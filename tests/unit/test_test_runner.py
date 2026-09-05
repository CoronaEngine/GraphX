"""测试工具的回归检查；执行真实入口，验证报告和退出码。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "run_tests.py"


def run_sample(tmp_path: Path, source: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    sample = tmp_path / "test_sample.py"
    sample.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(RUNNER), str(sample), "--color=no", *arguments],
        cwd=tmp_path,
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""},
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
    )


def test_runner_reports_chinese_scenarios_and_supports_selection(tmp_path: Path) -> None:
    """从其他目录运行入口，也能按名称筛选并显示中文场景。"""
    result = run_sample(
        tmp_path,
        '''
def test_selected():
    """合法输入被接受。"""
    assert 2 + 2 == 4

def test_unselected():
    raise AssertionError("must not run")
''',
        "-k",
        "selected and not unselected",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "合法输入被接受" in result.stdout
    assert "[PASS]" in result.stdout
    assert "通过：1" in result.stdout
    assert "1 deselected" in result.stdout


def test_runner_keeps_parameter_failure_details_and_nonzero_exit(tmp_path: Path) -> None:
    """参数化子场景失败时保留用例名、断言详情和失败退出码。"""
    result = run_sample(
        tmp_path,
        '''
import pytest

@pytest.mark.parametrize("value", [1, 2], ids=["valid", "invalid"])
def test_bound(value):
    """拒绝越界值。"""
    assert value == 1, "boundary violation"
''',
    )
    assert result.returncode == 1
    assert result.stdout.count("[FAIL]") == 1
    assert "test_bound[invalid]" in result.stdout
    assert "boundary violation" in result.stdout
    assert "通过：1" in result.stdout
    assert "失败：1" in result.stdout


@pytest.mark.parametrize("phase", ["setup", "teardown"])
def test_runner_preserves_fixture_error_details(tmp_path: Path, phase: str) -> None:
    """fixture 准备或清理失败时显示错误详情，并返回失败。"""
    fixture_body = (
        'raise RuntimeError("fixture exploded")\n    yield'
        if phase == "setup"
        else 'yield\n    raise RuntimeError("fixture exploded")'
    )
    result = run_sample(
        tmp_path,
        f'''import pytest
@pytest.fixture
def resource():
    {fixture_body}

def test_resource(resource):
    """资源生命周期检查。"""
    pass
''',
    )
    assert result.returncode == 1
    assert "[ERROR]" in result.stdout
    assert phase in result.stdout
    assert "fixture exploded" in result.stdout
    assert "错误：1" in result.stdout


def test_runner_distinguishes_skip_xfail_and_xpass(tmp_path: Path) -> None:
    """跳过、预期失败和意外通过分开统计，不冒充正常通过。"""
    result = run_sample(
        tmp_path,
        """import pytest
@pytest.mark.skip(reason="not available")
def test_skip():
    pass

@pytest.mark.xfail(reason="known issue")
def test_xfail():
    assert False

@pytest.mark.xfail(reason="resolved issue", strict=False)
def test_xpass():
    pass
""",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for label in ("[SKIP]", "[XFAIL]", "[XPASS]"):
        assert label in result.stdout
    assert "通过：0" in result.stdout
    assert "跳过：1" in result.stdout
    assert "预期失败：1" in result.stdout
    assert "意外通过：1" in result.stdout


@pytest.mark.parametrize(
    ("source", "exit_code", "detail"),
    [
        ("# empty test file", 5, "no tests ran"),
        ("raise RuntimeError('collection exploded')", 2, "collection exploded"),
    ],
    ids=["no-tests", "collection-error"],
)
def test_runner_preserves_collection_exit_codes(
    tmp_path: Path, source: str, exit_code: int, detail: str
) -> None:
    """空测试集和收集错误保留 pytest 原始退出码及诊断。"""
    result = run_sample(tmp_path, source)
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert detail in result.stdout


def test_verbose_collection_keeps_parameter_ids_short() -> None:
    """原生 pytest 收集边界测试时不展开超长输入字符串。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/protocol", "--collect-only", "-q"],
        cwd=RUNNER.parents[1],
        env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "x" * 100 not in result.stdout
    assert "task-too-long" in result.stdout
