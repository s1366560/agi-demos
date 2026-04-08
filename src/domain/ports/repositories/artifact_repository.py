"""Artifact Repository Port - Interface for artifact persistence."""

from abc import ABC, abstractmethod

from src.domain.model.artifact.artifact import Artifact, ArtifactCategory, ArtifactStatus


class ArtifactRepositoryPort(ABC):
    """
    Repository interface for Artifact entities.

    Defines operations for persisting and retrieving file artifacts
    produced by sandbox/MCP tool executions.
    """

    @abstractmethod
    async def save(self, artifact: Artifact) -> Artifact:
        """
        Save an artifact to the repository.

        Creates a new record if the artifact doesn't exist,
        or updates an existing record.

        Args:
            artifact: The artifact entity to save
        """

    @abstractmethod
    async def get(self, artifact_id: str) -> Artifact | None:
        """
        Get an artifact by ID.

        Args:
            artifact_id: The unique identifier of the artifact

        Returns:
            The artifact if found, None otherwise
        """

    @abstractmethod
    async def get_by_project(
        self,
        project_id: str,
        category: ArtifactCategory | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        """
        Get all artifacts for a project.

        Args:
            project_id: The project ID to filter by
            category: Optional category filter
            status: Optional status filter

        Returns:
            List of artifacts for the project
        """

    @abstractmethod
    async def get_by_conversation(
        self,
        conversation_id: str,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        """
        Get all artifacts for a conversation.

        Args:
            conversation_id: The conversation ID to filter by
            status: Optional status filter

        Returns:
            List of artifacts for the conversation
        """

    @abstractmethod
    async def get_by_tool_execution(
        self,
        tool_execution_id: str,
    ) -> list[Artifact]:
        """
        Get all artifacts for a specific tool execution.

        Args:
            tool_execution_id: The tool execution ID to filter by

        Returns:
            List of artifacts for the tool execution
        """

    @abstractmethod
    async def get_by_workspace(
        self,
        workspace_id: str,
        category: ArtifactCategory | None = None,
        status: ArtifactStatus | None = None,
    ) -> list[Artifact]:
        """
        Get all artifacts for a workspace (blackboard files).

        Args:
            workspace_id: The workspace ID to filter by
            category: Optional category filter
            status: Optional status filter

        Returns:
            List of artifacts for the workspace
        """

    @abstractmethod
    async def delete(self, artifact_id: str) -> bool:
        """
        Soft-delete an artifact by marking its status as DELETED.

        Args:
            artifact_id: The artifact ID to delete

        Returns:
            True if deleted, False if not found
        """

    @abstractmethod
    async def update_status(
        self,
        artifact_id: str,
        status: ArtifactStatus,
        error_message: str | None = None,
        url: str | None = None,
        preview_url: str | None = None,
    ) -> bool:
        """
        Update the status of an artifact.

        Args:
            artifact_id: The artifact ID to update
            status: The new status
            error_message: Optional error message (for ERROR status)
            url: Optional URL to set (for READY status)
            preview_url: Optional preview URL to set (for READY status)

        Returns:
            True if updated, False if not found
        """
