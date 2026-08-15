"""Discover, validate, and render declarative Polaris host adapters."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .polaris_core import InputFailure, RuleFailure, validate_json_file


SKILL_REFERENCE = re.compile(r"\{\{skill:([a-z][a-z0-9-]*)\}\}")


def _relative_path(value: str, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuleFailure(f"host adapter {field} must be a safe relative path: {value}")
    return path


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _render_references(
    text: str,
    skill_name: str,
    invocation_prefix: str,
    available_skills: set[str] | None,
) -> str:
    references = set(SKILL_REFERENCE.findall(text))
    if available_skills is not None:
        unknown = references - available_skills
        if unknown:
            raise InputFailure(
                f"Skill references unknown host-rendered Skills: {skill_name}: "
                f"{', '.join(sorted(unknown))}"
            )
    rendered = SKILL_REFERENCE.sub(
        lambda match: f"{invocation_prefix}{match.group(1)}", text
    )
    if "{{skill:" in rendered:
        raise InputFailure(f"Skill contains an invalid host placeholder: {skill_name}")
    return rendered


def load_host_adapters(root: Path) -> list[dict[str, Any]]:
    hosts_root = root / "hosts"
    schema = root / "schemas" / "host-adapter.schema.json"
    adapters: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    claimed_targets: list[tuple[Path, str]] = []
    for path in sorted(hosts_root.glob("*/adapter.json")):
        adapter = validate_json_file(path, schema)
        host_id = adapter["host_id"]
        if path.parent.name != host_id:
            raise RuleFailure(f"host adapter directory does not match host_id: {path}")
        if host_id in seen_ids:
            raise RuleFailure(f"duplicate host adapter: {host_id}")
        seen_ids.add(host_id)
        if not adapter["display_name"].strip():
            raise RuleFailure(f"host adapter display_name must not be blank: {path}")
        prefix = adapter["invocation_prefix"]
        if not prefix or any(character.isspace() for character in prefix):
            raise RuleFailure(
                f"host adapter invocation_prefix must be nonblank: {path}"
            )
        for line in adapter["entry_frontmatter"]:
            if not line.strip() or "\n" in line or line.strip() == "---":
                raise RuleFailure(f"invalid host entry frontmatter line: {path}")
        skill_target = _relative_path(
            adapter["skill_target"], "skill_target"
        )
        current_targets = [(skill_target, f"{host_id} skill_target")]
        overlay = adapter["skill_overlay_root"]
        if overlay is not None:
            overlay_path = path.parent / _relative_path(overlay, "skill_overlay_root")
            if not overlay_path.is_dir():
                raise RuleFailure(f"host skill overlay root is missing: {overlay_path}")
        appendix = adapter["skill_appendix_root"]
        if appendix is not None:
            appendix_path = path.parent / _relative_path(
                appendix, "skill_appendix_root"
            )
            if not appendix_path.is_dir():
                raise RuleFailure(f"host Skill appendix root is missing: {appendix_path}")
        for item in adapter["files"]:
            source = path.parent / _relative_path(item["source"], "files.source")
            target = _relative_path(item["target"], "files.target")
            current_targets.append((target, f"{host_id} file {target.as_posix()}"))
            if not source.is_file():
                raise RuleFailure(f"host adapter source file is missing: {source}")
        for target, label in current_targets:
            for claimed, claimed_label in claimed_targets:
                if _paths_overlap(target, claimed):
                    raise RuleFailure(
                        "host adapter target conflicts: "
                        f"{label} overlaps {claimed_label}"
                    )
            claimed_targets.append((target, label))
        adapter["adapter_root"] = path.parent
        adapters.append(adapter)
    if not adapters:
        raise RuleFailure(f"no host adapters found under {hosts_root}")
    return adapters


def render_skill(
    text: str,
    skill_name: str,
    adapter: dict[str, Any],
    available_skills: set[str] | None = None,
) -> str:
    known_references = set(SKILL_REFERENCE.findall(text))
    if skill_name not in known_references and skill_name == adapter["entry_skill"]:
        raise InputFailure(f"entry Skill does not reference itself: {skill_name}")
    text = _render_references(
        text, skill_name, adapter["invocation_prefix"], available_skills
    )
    if skill_name == adapter["entry_skill"] and adapter["entry_frontmatter"]:
        closing = text.find("\n---\n", len("---\n"))
        if closing == -1:
            raise InputFailure(f"Skill has invalid frontmatter: {skill_name}")
        lines = "\n".join(adapter["entry_frontmatter"])
        text = text[:closing] + f"\n{lines}" + text[closing:]
    appendix_root = adapter["skill_appendix_root"]
    if appendix_root is not None:
        appendix_path = (
            adapter["adapter_root"]
            / _relative_path(appendix_root, "skill_appendix_root")
            / f"{skill_name}.md"
        )
        if appendix_path.is_file():
            appendix = _render_references(
                appendix_path.read_text(encoding="utf-8"),
                skill_name,
                adapter["invocation_prefix"],
                available_skills,
            )
            text = text.rstrip() + "\n\n" + appendix.rstrip() + "\n"
    return text


def adapter_skill_target(repo: Path, adapter: dict[str, Any]) -> Path:
    return repo / _relative_path(adapter["skill_target"], "skill_target")


def adapter_file_target(repo: Path, item: dict[str, Any]) -> Path:
    return repo / _relative_path(item["target"], "files.target")
