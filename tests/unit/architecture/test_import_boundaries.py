from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[3]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
GRAPHX_ROOT = SOURCE_ROOT / "graphx"


@dataclass(frozen=True, slots=True)
class ImportRecord:
    importer: Path
    imported_module: str


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SOURCE_ROOT).with_suffix("").parts)


def _imports(path: Path) -> tuple[ImportRecord, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    records: list[ImportRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            records.extend(ImportRecord(path, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            records.append(ImportRecord(path, node.module))
    return tuple(records)


def _graphx_imports(root: Path) -> tuple[ImportRecord, ...]:
    return tuple(record for path in root.rglob("*.py") for record in _imports(path))


def _is_within(path: Path, relative_directory: str) -> bool:
    return path.is_relative_to(SOURCE_ROOT / relative_directory)


def _boundary_violation(record: ImportRecord) -> str | None:
    module = record.imported_module
    importer = record.importer

    if _is_within(importer, "graphx/protocol") and module.startswith(
        ("graphx.core", "graphx.application", "graphx.adapters")
    ):
        return "protocol cannot import another GraphX layer"
    if _is_within(importer, "graphx/core") and module.startswith(
        ("graphx.application", "graphx.adapters")
    ):
        return "core cannot import application or adapters"
    if _is_within(importer, "graphx/application") and module.startswith("graphx.adapters"):
        return "application cannot import adapters"
    if _is_within(importer, "graphx/adapters/host") and module.startswith(
        ("graphx.core", "graphx.application", "graphx.adapters.inbound", "graphx.adapters.store")
    ):
        return "host can depend only on protocol within GraphX"
    if importer == GRAPHX_ROOT / "bootstrap.py" and module.startswith("graphx.adapters.host"):
        return "service bootstrap cannot import the host adapter"
    return None


def test_plan_10_4_package_skeleton_exists() -> None:
    """工程骨架包含 Service 与 Host 的独立入口。"""
    required_files = {
        REPOSITORY_ROOT / "pyproject.toml",
        GRAPHX_ROOT / "__init__.py",
        GRAPHX_ROOT / "bootstrap.py",
        GRAPHX_ROOT / "adapters" / "host" / "main.py",
    }
    assert {path for path in required_files if not path.is_file()} == set()


def test_plan_10_4_layer_imports_follow_dependency_direction() -> None:
    """源码导入遵守从外层指向内层的依赖边界。"""
    violations = tuple(
        f"{_module_name(record.importer)} imports {record.imported_module}: {reason}"
        for record in _graphx_imports(GRAPHX_ROOT)
        if (reason := _boundary_violation(record)) is not None
    )
    assert violations == ()


def test_plan_10_4_protocol_may_import_a_protocol_sibling() -> None:
    """Protocol 允许引用同层协议模块。"""
    record = ImportRecord(GRAPHX_ROOT / "protocol" / "workflow_v1.py", "graphx.protocol.common_v1")

    assert _boundary_violation(record) is None


@pytest.mark.parametrize(
    ("relative_importer", "imported_module"),
    [
        ("graphx/protocol/workflow_v1.py", "graphx.core.config.models"),
        ("graphx/core/runtime/models.py", "graphx.adapters.store.sqlite.store"),
        ("graphx/application/service.py", "graphx.adapters.store.sqlite.store"),
        ("graphx/adapters/host/main.py", "graphx.core.runtime.models"),
        ("graphx/bootstrap.py", "graphx.adapters.host.main"),
    ],
)
def test_plan_10_4_guard_detects_each_forbidden_dependency(
    relative_importer: str, imported_module: str
) -> None:
    """架构守卫识别各类禁止的跨层依赖。"""
    record = ImportRecord(SOURCE_ROOT / relative_importer, imported_module)

    assert _boundary_violation(record) is not None


def test_plan_10_4_only_sqlite_adapter_imports_sqlite3() -> None:
    """只有 SQLite Adapter 可以导入 sqlite3。"""
    offenders = tuple(
        _module_name(record.importer)
        for record in _graphx_imports(GRAPHX_ROOT)
        if record.imported_module == "sqlite3"
        and not _is_within(record.importer, "graphx/adapters/store/sqlite")
    )
    assert offenders == ()
