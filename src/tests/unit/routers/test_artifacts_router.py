"""Unit tests for artifact API authorization."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.model.artifact.artifact import Artifact, ArtifactCategory, ArtifactStatus
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import artifacts as artifacts_router
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject

USER_ID = "user-artifacts"
PROJECT_ID = "project-artifacts"
OTHER_PROJECT_ID = "project-other"


@pytest.fixture
def artifact_user() -> User:
    return User(
        id=USER_ID,
        email="artifact-user@example.com",
        hashed_password="hashed",
        full_name="Artifact User",
        is_active=True,
        is_superuser=False,
    )


@pytest.fixture
def artifact_service_mock() -> AsyncMock:
    artifact = Artifact(
        id="artifact-1",
        project_id=OTHER_PROJECT_ID,
        tenant_id="tenant-artifacts",
        filename="report.txt",
        mime_type="text/plain",
        category=ArtifactCategory.DOCUMENT,
        size_bytes=5,
        object_key="artifacts/tenant/project/report.txt",
        status=ArtifactStatus.READY,
        url="https://storage.example/report.txt",
    )
    service = AsyncMock()
    service.get_artifact.return_value = artifact
    service.get_artifacts_by_project.return_value = [artifact]
    service.refresh_artifact_url.return_value = "https://storage.example/report.txt"
    service.delete_artifact.return_value = True
    return service


@pytest.fixture
def artifacts_client(test_db, artifact_user, artifact_service_mock, monkeypatch) -> TestClient:
    app = FastAPI()
    app.include_router(artifacts_router.router)

    async def override_get_current_user() -> User:
        return artifact_user

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(artifacts_router, "_artifact_service", artifact_service_mock)
    return TestClient(app)


@pytest.mark.unit
class TestArtifactsRouterAuthorization:
    async def _grant_project_access(self, test_db) -> None:
        test_db.add(
            UserProject(
                id="user-project-artifacts",
                user_id=USER_ID,
                project_id=PROJECT_ID,
                role="member",
            )
        )
        await test_db.commit()

    def test_list_artifacts_rejects_project_without_membership(
        self, artifacts_client, artifact_service_mock
    ):
        response = artifacts_client.get(f"/api/v1/artifacts?project_id={PROJECT_ID}")

        assert response.status_code == 403
        assert response.json()["detail"] == "Access denied to project"
        artifact_service_mock.get_artifacts_by_project.assert_not_called()

    def test_get_artifact_rejects_artifact_project_without_membership(
        self, artifacts_client, artifact_service_mock
    ):
        response = artifacts_client.get("/api/v1/artifacts/artifact-1")

        assert response.status_code == 403
        artifact_service_mock.get_artifact.assert_awaited_once_with("artifact-1")

    def test_download_artifact_rejects_artifact_project_without_membership(
        self, artifacts_client, artifact_service_mock
    ):
        response = artifacts_client.get("/api/v1/artifacts/artifact-1/download")

        assert response.status_code == 403
        artifact_service_mock.refresh_artifact_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_execution_list_filters_artifacts_to_requested_project(
        self, test_db, artifacts_client, artifact_service_mock
    ):
        await self._grant_project_access(test_db)
        allowed_artifact = Artifact(
            id="artifact-allowed",
            project_id=PROJECT_ID,
            tenant_id="tenant-artifacts",
            filename="allowed.txt",
            mime_type="text/plain",
            category=ArtifactCategory.DOCUMENT,
            size_bytes=7,
            object_key="artifacts/tenant/project/allowed.txt",
            status=ArtifactStatus.READY,
            url="https://storage.example/allowed.txt",
        )
        other_project_artifact = artifact_service_mock.get_artifact.return_value
        pending_artifact = Artifact(
            id="artifact-pending",
            project_id=PROJECT_ID,
            tenant_id="tenant-artifacts",
            filename="pending.txt",
            mime_type="text/plain",
            category=ArtifactCategory.DOCUMENT,
            size_bytes=7,
            object_key="artifacts/tenant/project/pending.txt",
            status=ArtifactStatus.PENDING,
        )
        artifact_service_mock.get_artifacts_by_tool_execution.return_value = [
            allowed_artifact,
            other_project_artifact,
            pending_artifact,
        ]

        response = artifacts_client.get(
            f"/api/v1/artifacts?project_id={PROJECT_ID}&tool_execution_id=tool-1"
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["artifacts"][0]["id"] == "artifact-allowed"
