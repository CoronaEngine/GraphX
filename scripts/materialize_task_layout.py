#!/usr/bin/env python3
"""Materialize generated task templates and real task directories from task_layout."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from internal.task_layout import (
    TEMPLATE_SAMPLE_PATHS,
    TEMPLATE_SOURCE_PATHS,
    task_directories,
    template_path,
    template_source_path,
)


def _generated_files(protocol_root: Path) -> set[Path]:
    root = protocol_root / "templates" / "task"
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}


def validate_materialized_template_tree(protocol_root: Path) -> None:
    if set(TEMPLATE_SAMPLE_PATHS) != set(TEMPLATE_SOURCE_PATHS):
        raise ValueError("template sample and source artifact sets differ")
    expected = {
        template_path(protocol_root, artifact) for artifact in TEMPLATE_SAMPLE_PATHS
    }
    actual = _generated_files(protocol_root)
    if actual != expected:
        missing = sorted(str(path) for path in expected - actual)
        extra = sorted(str(path) for path in actual - expected)
        raise ValueError(f"generated task templates differ; missing={missing}, extra={extra}")
    for artifact in TEMPLATE_SAMPLE_PATHS:
        source = template_source_path(protocol_root, artifact)
        generated = template_path(protocol_root, artifact)
        if not source.is_file():
            raise ValueError(f"missing task template source: {source}")
        if generated.read_bytes() != source.read_bytes():
            raise ValueError(f"generated task template is stale: {generated}")


def materialize_template_tree(protocol_root: Path) -> dict[str, object]:
    if set(TEMPLATE_SAMPLE_PATHS) != set(TEMPLATE_SOURCE_PATHS):
        raise ValueError("template sample and source artifact sets differ")
    generated_root = protocol_root / "templates" / "task"
    generated_root.mkdir(parents=True, exist_ok=True)
    expected = {
        template_path(protocol_root, artifact) for artifact in TEMPLATE_SAMPLE_PATHS
    }
    for stale in _generated_files(protocol_root) - expected:
        stale.unlink()
    for artifact in TEMPLATE_SAMPLE_PATHS:
        source = template_source_path(protocol_root, artifact)
        if not source.is_file():
            raise ValueError(f"missing task template source: {source}")
        destination = template_path(protocol_root, artifact)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    for directory in sorted(
        (path for path in generated_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        if not any(directory.iterdir()):
            directory.rmdir()
    validate_materialized_template_tree(protocol_root)
    return {
        "message": "materialized generated task template tree",
        "files": len(expected),
        "path": str(generated_root),
    }


def materialize_task_directories(directory: Path, revision: int) -> tuple[Path, ...]:
    paths = task_directories(directory, revision)
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    args = parser.parse_args()
    result = materialize_template_tree(args.protocol_root.resolve())
    print(f"{result['message']}: {result['files']} files at {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
