"""Shared evaluation data models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class EvaluationCase(BaseModel):
    """A software-engineering task evaluated against an agent runner."""

    id: str = Field(min_length=1)
    category: Literal[
        "bug_fix",
        "failing_test_repair",
        "small_refactor",
        "config_runtime_issue",
        "docs_backed_change",
    ]
    prompt: str = Field(min_length=1)
    verification_command: str = Field(min_length=1)
    target_repo: Path
    repo_ref: str | None = None
    expected_files: list[str] = Field(default_factory=list)
    deterministic_commands: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("target_repo")
    @classmethod
    def expand_target_repo(cls, value: Path) -> Path:
        return value.expanduser()


class RunnerCommand(BaseModel):
    """Command planned or executed by a runner."""

    cwd: Path
    argv: list[str]
    env: dict[str, str] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """Normalized result emitted by every runner."""

    case_id: str
    runner: Literal["mini", "memstack"]
    resolved: bool
    patch_applied: bool
    verification_command: str
    duration_sec: float
    steps: int | None = None
    trajectory_path: Path | None = None
    failure_reason: str | None = None
    diff_summary: str = ""
    workspace_path: Path | None = None
    dry_run: bool = False
    planned_command: RunnerCommand | None = None
