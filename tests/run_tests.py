#!/usr/bin/env python3
"""运行 GraphX 测试并显示中文场景；其余参数直接传给 pytest。"""

from __future__ import annotations

import inspect
import os
import sys
from collections import Counter
from collections.abc import Generator
from pathlib import Path

import pytest
from _pytest.terminal import TerminalReporter

ROOT = Path(__file__).resolve().parents[1]
type TestStatus = tuple[str, str, str | tuple[str, dict[str, bool]]]

LABELS = {
    "passed": "PASS",
    "failed": "FAIL",
    "error": "ERROR",
    "skipped": "SKIP",
    "xfailed": "XFAIL",
    "xpassed": "XPASS",
}


class ScenarioReporter:
    """仅定制显示；测试执行、错误详情及退出码仍由 pytest 管理。"""

    def __init__(self) -> None:
        self.descriptions: dict[str, str] = {}
        self.counts: Counter[str] = Counter()
        self.terminal: TerminalReporter | None = None
        self.reporting = False
        self.current_file = ""

    def pytest_runtest_logstart(self, nodeid: str) -> None:
        filename = nodeid.split("::", 1)[0]
        if self.terminal is not None and filename != self.current_file:
            self.terminal.write_line(f"\n{filename}")
            self.current_file = filename

    def pytest_sessionstart(self, session: pytest.Session) -> None:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if isinstance(reporter, TerminalReporter):
            self.terminal = reporter
            reporter.write_sep("=", "GraphX 自动化测试")

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            if isinstance(item, pytest.Function):
                description = inspect.getdoc(item.obj)
                if description:
                    scenario = description.splitlines()[0]
                    if hasattr(item, "callspec"):
                        scenario += f" [{item.callspec.id}]"
                    self.descriptions[item.nodeid] = scenario

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_logreport(self) -> Generator[None, object, None]:
        # The status hook is also queried again for final failure summaries.
        # Render and count only while pytest is processing a live test report.
        self.reporting = True
        try:
            yield
        finally:
            self.reporting = False

    @pytest.hookimpl(wrapper=True)
    def pytest_report_teststatus(
        self, report: pytest.TestReport | pytest.CollectReport
    ) -> Generator[None, TestStatus, TestStatus]:
        # Preserve pytest's category, including xfail/xpass, and suppress only
        # its progress characters. Native traceback and summary handling remain.
        status = yield
        category = status[0]
        if self.terminal is None or not self.reporting or not isinstance(report, pytest.TestReport):
            return status
        if category in LABELS:
            self.counts[category] += 1
            description = self.descriptions.get(report.nodeid, report.nodeid)
            phase = f" ({report.when})" if category == "error" else ""
            self.terminal.write_line(
                f"[{LABELS[category]}] {description}{phase} — {report.duration:.3f}s"
            )
        return category, "", ""

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.counts["error"] += 1
        elif report.skipped:
            self.counts["skipped"] += 1

    def pytest_terminal_summary(self, terminalreporter: TerminalReporter, exitstatus: int) -> None:
        terminalreporter.write_sep("=", "测试结果汇总")
        labels = (
            ("passed", "通过"),
            ("failed", "失败"),
            ("error", "错误"),
            ("skipped", "跳过"),
            ("xfailed", "预期失败"),
            ("xpassed", "意外通过"),
        )
        terminalreporter.write_line(
            "，".join(f"{label}：{self.counts[category]}" for category, label in labels)
        )
        terminalreporter.write_line(f"pytest 退出码：{exitstatus}")


def main() -> int:
    # Keep repository-relative selectors stable even when launched elsewhere.
    os.chdir(ROOT)
    return int(
        pytest.main(
            ["-q", "-ra", "-o", "console_output_style=classic", *sys.argv[1:]],
            plugins=[ScenarioReporter()],
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
