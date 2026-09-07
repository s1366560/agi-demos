"""Immutable identity of the memory version handed to a processing job."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class MemoryProcessingSource:
    memory_id: str
    project_id: str
    revision: int
    task_id: str | None = None

    def __post_init__(self) -> None:
        if not self.memory_id or not self.project_id:
            raise ValueError("Processing source requires memory and project IDs")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("Processing source requires a positive integer revision")
        if self.task_id is not None and not self.task_id:
            raise ValueError("Processing task ID must be nonempty when provided")

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "MemoryProcessingSource | None":
        """Old jobs without a captured revision cannot update current Memory state."""
        memory_id = payload.get("memory_id")
        project_id = payload.get("project_id")
        revision = payload.get("source_revision")
        task_id = payload.get("task_id")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or not isinstance(project_id, str)
            or not project_id
            or type(revision) is not int
            or revision < 1
            or (task_id is not None and (not isinstance(task_id, str) or not task_id))
        ):
            return None
        return cls(memory_id=memory_id, project_id=project_id, revision=revision, task_id=task_id)
