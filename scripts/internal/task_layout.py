"""Single source of truth for Polaris task-relative paths and template samples."""

from __future__ import annotations

from pathlib import Path


TASK_PATH_PATTERNS = {
    "state": "state.json",
    "events": "events.jsonl",
    "plan": "PLAN.md",
    "plan_decisions": "plan-decisions.json",
    "working_set": "working-set.json",
    "progress": "runtime/progress.json",
    "work_item": "revisions/work-item-r{revision:03d}.json",
    "implementation_revision": "implementations/r{revision:03d}",
    "implementation_handoff": (
        "implementations/r{revision:03d}/handoff-{attempt:03d}.json"
    ),
    "implementation": "implementations/r{revision:03d}/attempt-{attempt:03d}.json",
    "knowledge_revision": "knowledge/r{revision:03d}",
    "knowledge_delta": "knowledge/r{revision:03d}/knowledge-delta-{attempt:03d}.json",
    "review_revision": "reviews/r{revision:03d}",
    "review_handoff": "reviews/r{revision:03d}/handoff-{attempt:03d}.json",
    "review": (
        "reviews/r{revision:03d}/review-{attempt:03d}{reviewer_suffix}.json"
    ),
    "review_response": "reviews/r{revision:03d}/response-{attempt:03d}.json",
    "validation_revision": "validations/r{revision:03d}",
    "validation": "validations/r{revision:03d}/validation-{attempt:03d}.json",
    "result_revision": "results/r{revision:03d}",
    "result": "results/r{revision:03d}/result-{attempt:03d}.json",
    "evidence_revision": "evidence/r{revision:03d}",
    "explorations": "explorations",
    "exploration": "explorations/{exploration_id}.json",
}
TASKS_ROOT = Path(".polaris/tasks")


def task_relative_path(
    artifact: str,
    *,
    revision: int = 1,
    attempt: int = 1,
    reviewer: int = 1,
    exploration_id: str = "EXP-0001",
) -> Path:
    pattern = TASK_PATH_PATTERNS[artifact]
    reviewer_suffix = "" if reviewer == 1 else f"-{reviewer}"
    return Path(
        pattern.format(
            revision=revision,
            attempt=attempt,
            reviewer_suffix=reviewer_suffix,
            exploration_id=exploration_id,
        )
    )


def task_root_relative_path(task_id: str) -> Path:
    return TASKS_ROOT / task_id


def task_repo_relative_path(task_id: str, artifact: str, **values: int | str) -> Path:
    return task_root_relative_path(task_id) / task_relative_path(artifact, **values)


TEMPLATE_SAMPLE_PATHS = {
    "state": task_relative_path("state"),
    "plan": task_relative_path("plan"),
    "plan_decisions": task_relative_path("plan_decisions"),
    "working_set": task_relative_path("working_set"),
    "progress": task_relative_path("progress"),
    "work_item": task_relative_path("work_item"),
    "implementation_handoff": task_relative_path("implementation_handoff"),
    "implementation": task_relative_path("implementation"),
    "knowledge_delta": task_relative_path("knowledge_delta"),
    "review_handoff": task_relative_path("review_handoff"),
    "review": task_relative_path("review"),
    "review_response": task_relative_path("review_response", attempt=2),
    "validation": task_relative_path("validation"),
    "result": task_relative_path("result"),
    "exploration": task_relative_path("exploration"),
}
TEMPLATE_SOURCE_PATHS = {
    "state": Path("state.json"),
    "plan": Path("PLAN.md"),
    "plan_decisions": Path("plan-decisions.json"),
    "working_set": Path("working-set.json"),
    "progress": Path("implementation-progress.json"),
    "work_item": Path("work-item.json"),
    "implementation_handoff": Path("implementation-handoff.json"),
    "implementation": Path("implementation.json"),
    "knowledge_delta": Path("knowledge-delta.json"),
    "review_handoff": Path("review-handoff.json"),
    "review": Path("review.json"),
    "review_response": Path("review-response.json"),
    "validation": Path("validation.json"),
    "result": Path("result.json"),
    "exploration": Path("exploration.json"),
}
RUNTIME_IGNORE_PATTERN = (
    task_root_relative_path("*") / task_relative_path("progress").parent
).as_posix() + "/"
ARCHIVED_RUNTIME_IGNORE_PATTERN = ".polaris/archive/tasks/*/runtime/"


def template_path(protocol_root: Path, artifact: str) -> Path:
    return protocol_root / "templates" / "task" / TEMPLATE_SAMPLE_PATHS[artifact]


def template_source_path(protocol_root: Path, artifact: str) -> Path:
    return (
        protocol_root
        / "templates"
        / "task-sources"
        / TEMPLATE_SOURCE_PATHS[artifact]
    )


def state_path(directory: Path) -> Path:
    return directory / task_relative_path("state")


def events_path(directory: Path) -> Path:
    return directory / task_relative_path("events")


def plan_path(directory: Path) -> Path:
    return directory / task_relative_path("plan")


def plan_decisions_path(directory: Path) -> Path:
    return directory / task_relative_path("plan_decisions")


def working_set_path(directory: Path) -> Path:
    return directory / task_relative_path("working_set")


def progress_relative_path() -> Path:
    return task_relative_path("progress")


def progress_path(directory: Path) -> Path:
    return directory / progress_relative_path()


def work_item_relative_path(revision: int) -> Path:
    return task_relative_path("work_item", revision=revision)


def work_item_path(directory: Path, revision: int) -> Path:
    return directory / work_item_relative_path(revision)


def implementation_revision_dir(directory: Path, revision: int) -> Path:
    return directory / task_relative_path("implementation_revision", revision=revision)


def implementation_handoff_relative_path(revision: int, attempt: int) -> Path:
    return task_relative_path(
        "implementation_handoff", revision=revision, attempt=attempt
    )


def implementation_handoff_path(directory: Path, revision: int, attempt: int) -> Path:
    return directory / implementation_handoff_relative_path(revision, attempt)


def implementation_relative_path(revision: int, attempt: int) -> Path:
    return task_relative_path("implementation", revision=revision, attempt=attempt)


def implementation_path(directory: Path, revision: int, attempt: int) -> Path:
    return directory / implementation_relative_path(revision, attempt)


def knowledge_revision_dir(directory: Path, revision: int) -> Path:
    return directory / task_relative_path("knowledge_revision", revision=revision)


def knowledge_delta_path(directory: Path, revision: int, attempt: int) -> Path:
    return directory / task_relative_path(
        "knowledge_delta", revision=revision, attempt=attempt
    )


def review_revision_dir(directory: Path, revision: int) -> Path:
    return directory / task_relative_path("review_revision", revision=revision)


def review_handoff_path(directory: Path, revision: int, attempt: int) -> Path:
    return directory / task_relative_path(
        "review_handoff", revision=revision, attempt=attempt
    )


def review_path(directory: Path, revision: int, attempt: int, reviewer: int = 1) -> Path:
    return directory / task_relative_path(
        "review", revision=revision, attempt=attempt, reviewer=reviewer
    )


def review_response_path(directory: Path, revision: int, attempt: int) -> Path:
    return directory / task_relative_path(
        "review_response", revision=revision, attempt=attempt
    )


def validation_revision_dir(directory: Path, revision: int) -> Path:
    return directory / task_relative_path("validation_revision", revision=revision)


def validation_path(directory: Path, revision: int, attempt: int) -> Path:
    return directory / task_relative_path(
        "validation", revision=revision, attempt=attempt
    )


def result_revision_dir(directory: Path, revision: int) -> Path:
    return directory / task_relative_path("result_revision", revision=revision)


def result_path(directory: Path, revision: int, attempt: int) -> Path:
    return directory / task_relative_path("result", revision=revision, attempt=attempt)


def evidence_dir(directory: Path, revision: int) -> Path:
    return directory / task_relative_path("evidence_revision", revision=revision)


def explorations_dir(directory: Path) -> Path:
    return directory / task_relative_path("explorations")


def exploration_path(directory: Path, exploration_id: str) -> Path:
    return directory / task_relative_path("exploration", exploration_id=exploration_id)


def revision_directories(directory: Path, revision: int) -> tuple[Path, ...]:
    return (
        work_item_path(directory, revision).parent,
        implementation_revision_dir(directory, revision),
        knowledge_revision_dir(directory, revision),
        review_revision_dir(directory, revision),
        validation_revision_dir(directory, revision),
        result_revision_dir(directory, revision),
        evidence_dir(directory, revision),
        explorations_dir(directory),
    )


def task_directories(directory: Path, revision: int) -> tuple[Path, ...]:
    return (progress_path(directory).parent, *revision_directories(directory, revision))
