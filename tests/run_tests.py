#!/usr/bin/env python3
"""Run Polaris tests with readable per-scenario logs and a final summary."""

from __future__ import annotations

import argparse
import sys
import time
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class TestRecord:
    name: str
    description: str
    status: str
    duration: float
    detail: str = ""


def describe(test: unittest.TestCase) -> tuple[str, str]:
    method_name = getattr(test, "_testMethodName", str(test))
    method = getattr(test, method_name, None)
    doc = getattr(method, "__doc__", None)
    description = " ".join(doc.strip().split()) if doc else method_name
    return method_name, description


class PolarisTestResult(unittest.TextTestResult):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.started_at: dict[str, float] = {}
        self.records: list[TestRecord] = []

    def startTest(self, test: unittest.TestCase) -> None:
        super().startTest(test)
        name, description = describe(test)
        self.started_at[test.id()] = time.perf_counter()
        self.stream.writeln(f"\n[ RUN      ] {name}")
        self.stream.writeln(f"             场景：{description}")
        self.stream.flush()

    def _finish(
        self, test: unittest.TestCase, status: str, detail: str = ""
    ) -> None:
        name, description = describe(test)
        duration = time.perf_counter() - self.started_at.pop(test.id(), time.perf_counter())
        self.records.append(TestRecord(name, description, status, duration, detail))
        self.stream.writeln(f"[ {status:<8} ] {name} ({duration:.3f}s)")
        if detail:
            for line in detail.rstrip().splitlines():
                self.stream.writeln(f"             {line}")
        self.stream.flush()

    def addSuccess(self, test: unittest.TestCase) -> None:
        unittest.TestResult.addSuccess(self, test)
        self._finish(test, "PASS")

    def addFailure(self, test: unittest.TestCase, err: object) -> None:
        unittest.TestResult.addFailure(self, test, err)
        self._finish(test, "FAIL", self._exc_info_to_string(err, test))

    def addError(self, test: unittest.TestCase, err: object) -> None:
        unittest.TestResult.addError(self, test, err)
        self._finish(test, "ERROR", self._exc_info_to_string(err, test))

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        unittest.TestResult.addSkip(self, test, reason)
        self._finish(test, "SKIP", reason)

    def printErrors(self) -> None:
        # Failure details are emitted immediately beside the failing scenario.
        return


class PolarisTestRunner(unittest.TextTestRunner):
    resultclass = PolarisTestResult

    def run(self, test: unittest.TestSuite) -> PolarisTestResult:
        self.stream.writeln("=" * 78)
        self.stream.writeln("Polaris v0.1 自动化测试")
        self.stream.writeln(f"测试目录：{ROOT / 'tests'}")
        self.stream.writeln("=" * 78)
        result = super().run(test)
        self.stream.writeln("\n" + "=" * 78)
        self.stream.writeln("测试结果汇总")
        self.stream.writeln("=" * 78)
        for record in result.records:
            self.stream.writeln(
                f"{record.status:<8} {record.duration:>7.3f}s  {record.description}"
            )
        self.stream.writeln("-" * 78)
        self.stream.writeln(
            "总计：{total}，通过：{passed}，失败：{failed}，错误：{errors}，跳过：{skipped}".format(
                total=result.testsRun,
                passed=sum(record.status == "PASS" for record in result.records),
                failed=len(result.failures),
                errors=len(result.errors),
                skipped=len(result.skipped),
            )
        )
        self.stream.writeln(
            f"最终结论：{'PASS（全部机械规则验证通过）' if result.wasSuccessful() else 'FAIL（存在未通过场景）'}"
        )
        self.stream.writeln("=" * 78)
        self.stream.flush()
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pattern", default="test*.py", help="unittest discovery pattern"
    )
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests"), pattern=args.pattern
    )
    result = PolarisTestRunner(stream=sys.stdout, verbosity=0).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
