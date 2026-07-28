"""Process-local Artifact repository used only by explicitly unconfigured services."""

from collections.abc import Iterable
from typing import override

from src.domain.model.artifact.artifact import Artifact, ArtifactCategory, ArtifactStatus
from src.domain.ports.repositories.artifact_repository import ArtifactRepositoryPort


class InMemoryArtifactRepository(ArtifactRepositoryPort):
    """Small compatibility adapter for isolated unit tests and local construction."""

    def __init__(self) -> None:
        super().__init__()
        self.artifacts: dict[str, Artifact] = {}

    @override
    async def save(self, artifact: Artifact) -> Artifact:
        self.artifacts[artifact.id] = artifact
        return artifact

    @override
    async def get(self, artifact_id: str) -> Artifact | None:
        return self.artifacts.get(artifact_id)

    @override
    async def get_by_project(
        self,
        project_id: str,
        category: ArtifactCategory | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        return self._filtered(
            (artifact for artifact in self.artifacts.values() if artifact.project_id == project_id),
            category=category,
            status=status,
        )

    @override
    async def get_by_conversation(
        self,
        conversation_id: str,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        return self._filtered(
            (
                artifact
                for artifact in self.artifacts.values()
                if artifact.conversation_id == conversation_id
            ),
            status=status,
        )

    @override
    async def get_by_tool_execution(self, tool_execution_id: str) -> list[Artifact]:
        return self._filtered(
            artifact
            for artifact in self.artifacts.values()
            if artifact.tool_execution_id == tool_execution_id
        )

    @override
    async def get_by_workspace(
        self,
        workspace_id: str,
        category: ArtifactCategory | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        del workspace_id
        return self._filtered((), category=category, status=status)

    @override
    async def delete(self, artifact_id: str) -> bool:
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            return False
        artifact.mark_deleted()
        return True

    @override
    async def update_status(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        error_message: str | None = None,
        url: str | None = None,
        preview_url: str | None = None,
    ) -> bool:
        artifact = self.artifacts.get(artifact_id)
        if artifact is None:
            return False
        artifact.status = status
        artifact.error_message = error_message
        artifact.url = url
        artifact.preview_url = preview_url
        return True

    @staticmethod
    def _filtered(
        artifacts: Iterable[Artifact],
        *,
        category: ArtifactCategory | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        result = [
            artifact
            for artifact in artifacts
            if (category is None or artifact.category is category)
            and (status is None or artifact.status is status)
        ]
        result.sort(key=lambda artifact: artifact.created_at, reverse=True)
        return result
