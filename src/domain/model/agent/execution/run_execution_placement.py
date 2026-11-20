"""Run-level execution location. Distinct from cloud worktree environment snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.domain.shared_kernel import ValueObject

EXECUTION_TARGET_MAX_LENGTH = 16
EXECUTION_MACHINE_ID_MAX_LENGTH = 128
EXECUTION_ENVIRONMENT_ID_MAX_LENGTH = 64
LOCAL_ROOT_LABEL_MAX_LENGTH = 255


class ExecutionTarget(StrEnum):
    """Where a single run's tools and filesystem actually execute."""

    LOCAL = "local"
    CLOUD = "cloud"


class InvalidExecutionTarget(ValueError):
    """Raised when a caller submits an execution target outside the closed set."""


def parse_execution_target(value: object | None) -> ExecutionTarget:
    """Accept omitted values as cloud. Reject every other token."""

    if value is None:
        return ExecutionTarget.CLOUD
    if isinstance(value, ExecutionTarget):
        return value
    if isinstance(value, str) and value in {
        ExecutionTarget.LOCAL.value,
        ExecutionTarget.CLOUD.value,
    }:
        return ExecutionTarget(value)
    raise InvalidExecutionTarget("execution_target must be local or cloud")


def _optional_text(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit:
        return None
    return text


@dataclass(frozen=True, kw_only=True)
class RunExecutionPlacement(ValueObject):
    """Persisted execution location for one agent run authority row."""

    execution_target: ExecutionTarget
    execution_machine_id: str | None = None
    execution_environment_id: str | None = None
    local_root_label: str | None = None

    def __post_init__(self) -> None:
        machine_id = _optional_text(
            self.execution_machine_id,
            limit=EXECUTION_MACHINE_ID_MAX_LENGTH,
        )
        environment_id = _optional_text(
            self.execution_environment_id,
            limit=EXECUTION_ENVIRONMENT_ID_MAX_LENGTH,
        )
        local_root_label = _optional_text(
            self.local_root_label,
            limit=LOCAL_ROOT_LABEL_MAX_LENGTH,
        )
        object.__setattr__(self, "execution_machine_id", machine_id)
        object.__setattr__(self, "execution_environment_id", environment_id)
        object.__setattr__(self, "local_root_label", local_root_label)

    def public_dict(self) -> dict[str, str | None]:
        """API and WebSocket fields. These never live inside environment.kind."""

        return {
            "execution_target": self.execution_target.value,
            "execution_machine_id": self.execution_machine_id,
            "execution_environment_id": self.execution_environment_id,
            "local_root_label": self.local_root_label,
        }


CLOUD_RUN_EXECUTION_PLACEMENT = RunExecutionPlacement(execution_target=ExecutionTarget.CLOUD)


def placement_from_mapping(value: object | None) -> RunExecutionPlacement:
    """Read the four public fields from a mapping, defaulting a missing target to cloud."""

    if not isinstance(value, dict):
        return CLOUD_RUN_EXECUTION_PLACEMENT
    record: dict[str, Any] = value
    return RunExecutionPlacement(
        execution_target=parse_execution_target(record.get("execution_target")),
        execution_machine_id=_optional_text(
            record.get("execution_machine_id"),
            limit=EXECUTION_MACHINE_ID_MAX_LENGTH,
        ),
        execution_environment_id=_optional_text(
            record.get("execution_environment_id"),
            limit=EXECUTION_ENVIRONMENT_ID_MAX_LENGTH,
        ),
        local_root_label=_optional_text(
            record.get("local_root_label"),
            limit=LOCAL_ROOT_LABEL_MAX_LENGTH,
        ),
    )
