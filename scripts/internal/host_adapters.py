"""Discover, validate, and render declarative Polaris host adapters."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .path_security import (
    confined_target,
    require_regular_file,
    require_regular_tree,
)
from .polaris_core import InputFailure, RuleFailure, validate_json_file


SKILL_REFERENCE = re.compile(r"\{\{skill:([a-z][a-z0-9-]*)\}\}")


def _relative_path(value: str, field: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise RuleFailure(f"host adapter {field} must be a safe relative path: {value}")
    return path


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def discover_skills(root: Path) -> tuple[str, ...]:
    skills_root = root / "skills"
    require_regular_tree(skills_root, "canonical Skills root")
    names: list[str] = []
    for path in sorted(skills_root.iterdir()):
        if not path.is_dir():
            raise RuleFailure(f"canonical Skills root contains a non-directory: {path}")
        if not re.fullmatch(r"[a-z][a-z0-9-]*", path.name):
            raise RuleFailure(f"canonical Skill has an invalid name: {path.name}")
        require_regular_file(path / "SKILL.md", "canonical Skill entry")
        names.append(path.name)
    if not names:
        raise RuleFailure(f"no canonical Skills found under {skills_root}")
    return tuple(names)


def _validate_capabilities(adapter: dict[str, Any], path: Path) -> None:
    capabilities = adapter["capabilities"]
    creates = capabilities["worker_create"]
    if capabilities["worker_status"] and not creates:
        raise RuleFailure(f"worker_status requires worker_create: {path}")
    if capabilities["stable_worker_identity"] and not creates:
        raise RuleFailure(f"stable_worker_identity requires worker_create: {path}")
    if capabilities["worker_resume"] and not (
        creates and capabilities["stable_worker_identity"]
    ):
        raise RuleFailure(
            f"worker_resume requires worker_create and stable_worker_identity: {path}"
        )


def _validate_overlay(
    adapter_root: Path,
    overlay_value: str,
    root: Path,
    available_skills: set[str],
) -> None:
    overlay_root = adapter_root / _relative_path(
        overlay_value, "skill_overlay_root"
    )
    require_regular_tree(overlay_root, "host skill overlay root")
    for skill_overlay in sorted(overlay_root.iterdir()):
        if not skill_overlay.is_dir() or skill_overlay.name not in available_skills:
            raise RuleFailure(
                f"host overlay must target an installed Skill: {skill_overlay}"
            )
        canonical = root / "skills" / skill_overlay.name
        for overlay_file in (
            path for path in skill_overlay.rglob("*") if path.is_file()
        ):
            relative = overlay_file.relative_to(skill_overlay)
            if relative == Path("SKILL.md"):
                raise RuleFailure(
                    f"host overlay must not replace SKILL.md: {overlay_file}"
                )
            if (canonical / relative).exists():
                raise RuleFailure(
                    f"host overlay must not replace canonical Skill content: {overlay_file}"
                )


def _validate_appendices(
    adapter_root: Path,
    appendix_value: str,
    available_skills: set[str],
) -> Path:
    appendix_root = adapter_root / _relative_path(
        appendix_value, "skill_appendix_root"
    )
    require_regular_tree(appendix_root, "host Skill appendix root")
    for appendix in sorted(appendix_root.iterdir()):
        if (
            not appendix.is_file()
            or appendix.suffix != ".md"
            or appendix.stem not in available_skills
        ):
            raise RuleFailure(
                f"host appendix must be <installed-skill>.md: {appendix}"
            )
    return appendix_root


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
    require_regular_tree(hosts_root, "host adapters root")
    adapters: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    claimed_targets: list[tuple[Path, str]] = []
    available_skills = set(discover_skills(root))
    for path in sorted(hosts_root.glob("*/adapter.json")):
        require_regular_file(path, "host adapter manifest")
        if path.parent.is_symlink():
            raise RuleFailure(
                f"host adapter directory must not be a symlink: {path.parent}"
            )
        adapter = validate_json_file(path, schema)
        host_id = adapter["host_id"]
        if path.parent.name != host_id:
            raise RuleFailure(f"host adapter directory does not match host_id: {path}")
        if host_id in seen_ids:
            raise RuleFailure(f"duplicate host adapter: {host_id}")
        seen_ids.add(host_id)
        if adapter["entry_skill"] not in available_skills:
            raise RuleFailure(
                f"host adapter entry_skill is not installed: {adapter['entry_skill']}"
            )
        _validate_capabilities(adapter, path)
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
        project_mcp = adapter["project_mcp"]
        project_mcp_target = _relative_path(
            project_mcp["target"], "project_mcp.target"
        )
        if project_mcp["server_id"] != "polaris-codegraph":
            raise RuleFailure(f"host adapter has an invalid MCP server ID: {path}")
        if project_mcp["format"] not in {"codex-toml", "claude-json"}:
            raise RuleFailure(f"host adapter has an invalid MCP format: {path}")
        if project_mcp["command"] != "python3":
            raise RuleFailure(f"host adapter has an invalid MCP command: {path}")
        if project_mcp["args"] != [
            "tools/polaris/scripts/code_intelligence_mcp.py",
            "--repo",
            ".",
        ]:
            raise RuleFailure(f"host adapter has invalid MCP arguments: {path}")
        current_targets.append((project_mcp_target, f"{host_id} project_mcp"))
        overlay = adapter["skill_overlay_root"]
        if overlay is not None:
            _validate_overlay(path.parent, overlay, root, available_skills)
        appendix = adapter["skill_appendix_root"]
        if appendix is not None:
            appendix_path = _validate_appendices(
                path.parent, appendix, available_skills
            )
            if adapter["capabilities"]["worker_create"] and not (
                appendix_path / f"{adapter['entry_skill']}.md"
            ).is_file():
                raise RuleFailure(
                    f"worker-capable adapter lacks entry Skill appendix: {path}"
                )
        elif adapter["capabilities"]["worker_create"]:
            raise RuleFailure(f"worker-capable adapter lacks Skill appendices: {path}")
        for item in adapter["files"]:
            source = path.parent / _relative_path(item["source"], "files.source")
            target = _relative_path(item["target"], "files.target")
            current_targets.append((target, f"{host_id} file {target.as_posix()}"))
            require_regular_file(source, "host adapter source file")
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
    return confined_target(
        repo,
        repo / _relative_path(adapter["skill_target"], "skill_target"),
        "host Skill target",
    )


def adapter_file_target(repo: Path, item: dict[str, Any]) -> Path:
    return confined_target(
        repo,
        repo / _relative_path(item["target"], "files.target"),
        "host adapter file target",
    )
