"""Feature checkpoint and handoff value objects for long-running plans."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, cast


class HandoffReason(str, Enum):
    """Why a worker should rehydrate context before continuing a plan node."""

    PLANNED = "planned"
    CONTEXT_LIMIT = "context_limit"
    SESSION_END = "session_end"
    WORKER_RESTART = "worker_restart"
    RETRY = "retry"
    REPLAN = "replan"
    MANUAL = "manual"


@dataclass(frozen=True)
class FeatureCheckpoint:
    """Durable feature-level checklist entry for a leaf plan node."""

    feature_id: str
    sequence: int = 0
    title: str = ""
    init_command: str | None = None
    test_commands: tuple[str, ...] = field(default_factory=tuple)
    expected_artifacts: tuple[str, ...] = field(default_factory=tuple)
    worktree_path: str | None = None
    branch_name: str | None = None
    base_ref: str | None = None
    commit_ref: str | None = None
    handoff_notes: str = ""

    def __post_init__(self) -> None:
        if not self.feature_id.strip():
            raise ValueError("FeatureCheckpoint.feature_id cannot be empty")
        if self.sequence < 0:
            raise ValueError("FeatureCheckpoint.sequence must be >= 0")
        object.__setattr__(self, "test_commands", _clean_tuple(self.test_commands))
        object.__setattr__(self, "expected_artifacts", _clean_tuple(self.expected_artifacts))

    def to_json(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "sequence": self.sequence,
            "title": self.title,
            "init_command": self.init_command,
            "test_commands": list(self.test_commands),
            "expected_artifacts": list(self.expected_artifacts),
            "worktree_path": self.worktree_path,
            "branch_name": self.branch_name,
            "base_ref": self.base_ref,
            "commit_ref": self.commit_ref,
            "handoff_notes": self.handoff_notes,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> FeatureCheckpoint:
        return cls(
            feature_id=str(payload["feature_id"]),
            sequence=int(payload.get("sequence", 0)),
            title=str(payload.get("title", "")),
            init_command=_optional_str(payload.get("init_command")),
            test_commands=_string_tuple(payload.get("test_commands")),
            expected_artifacts=_string_tuple(payload.get("expected_artifacts")),
            worktree_path=_optional_str(payload.get("worktree_path")),
            branch_name=_optional_str(payload.get("branch_name")),
            base_ref=_optional_str(payload.get("base_ref")),
            commit_ref=_optional_str(payload.get("commit_ref")),
            handoff_notes=str(payload.get("handoff_notes", "")),
        )


@dataclass(frozen=True)
class HandoffPackage:
    """Snapshot a worker needs to get up to speed after session rollover."""

    reason: HandoffReason
    summary: str
    next_steps: tuple[str, ...] = field(default_factory=tuple)
    completed_steps: tuple[str, ...] = field(default_factory=tuple)
    changed_files: tuple[str, ...] = field(default_factory=tuple)
    git_head: str | None = None
    git_diff_summary: str = ""
    test_commands: tuple[str, ...] = field(default_factory=tuple)
    verification_notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("HandoffPackage.summary cannot be empty")
        object.__setattr__(self, "next_steps", _clean_tuple(self.next_steps))
        object.__setattr__(self, "completed_steps", _clean_tuple(self.completed_steps))
        object.__setattr__(self, "changed_files", _clean_tuple(self.changed_files))
        object.__setattr__(self, "test_commands", _clean_tuple(self.test_commands))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_json(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "summary": self.summary,
            "next_steps": list(self.next_steps),
            "completed_steps": list(self.completed_steps),
            "changed_files": list(self.changed_files),
            "git_head": self.git_head,
            "git_diff_summary": self.git_diff_summary,
            "test_commands": list(self.test_commands),
            "verification_notes": self.verification_notes,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> HandoffPackage:
        return cls(
            reason=HandoffReason(str(payload.get("reason", HandoffReason.PLANNED.value))),
            summary=str(payload["summary"]),
            next_steps=_string_tuple(payload.get("next_steps")),
            completed_steps=_string_tuple(payload.get("completed_steps")),
            changed_files=_string_tuple(payload.get("changed_files")),
            git_head=_optional_str(payload.get("git_head")),
            git_diff_summary=str(payload.get("git_diff_summary", "")),
            test_commands=_string_tuple(payload.get("test_commands")),
            verification_notes=str(payload.get("verification_notes", "")),
            created_at=_parse_datetime(payload.get("created_at")),
        )


def _clean_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        items: Sequence[object] = cast(list[object], value)
    elif isinstance(value, tuple):
        items = cast(tuple[object, ...], value)
    else:
        return ()
    return _clean_tuple(tuple(str(item) for item in items if item))


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
