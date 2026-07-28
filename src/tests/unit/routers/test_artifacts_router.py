"""Unit tests for artifact API authorization."""

import hashlib
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.services.artifact_content_contract import (
    ArtifactContentContract,
    ArtifactContentRevisionConflictError,
    ArtifactContentSaveReceipt,
)
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


@pytest.mark.unit
class TestArtifactContentContractV2Router:
    async def _grant_project_access(self, test_db) -> None:
        test_db.add(
            UserProject(
                id="user-project-artifact-content-v2",
                user_id=USER_ID,
                project_id=OTHER_PROJECT_ID,
                role="member",
            )
        )
        await test_db.commit()

    @staticmethod
    def _hash(content: str) -> str:
        return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"

    @pytest.mark.asyncio
    async def test_content_get_returns_v2_json_and_bytes_without_presigned_redirect(
        self,
        test_db,
        artifacts_client,
        artifact_service_mock,
    ) -> None:
        await self._grant_project_access(test_db)
        content_hash = self._hash("hello")
        artifact_service_mock.get_artifact_content.return_value = ArtifactContentContract(
            contract_version=2,
            artifact_id="artifact-1",
            revision=3,
            content_hash=content_hash,
            mime_type="text/plain",
            content="hello",
        )
        artifact_service_mock.get_artifact_bytes.return_value = b"hello"

        content = artifacts_client.get("/api/v1/artifacts/artifact-1/content")
        raw = artifacts_client.get("/api/v1/artifacts/artifact-1/content/bytes")
        download = artifacts_client.get("/api/v1/artifacts/artifact-1/download")

        assert content.status_code == 200
        assert content.json() == {
            "contract_version": 2,
            "artifact_id": "artifact-1",
            "revision": 3,
            "content_hash": content_hash,
            "mime_type": "text/plain",
            "content": "hello",
        }
        assert raw.status_code == 200
        assert raw.content == b"hello"
        assert raw.headers["content-type"] == "text/plain; charset=utf-8"
        assert raw.headers["cache-control"] == "private, no-store"
        assert raw.headers["x-content-type-options"] == "nosniff"
        assert download.status_code == 200
        assert download.content == b"hello"
        assert download.headers["cache-control"] == "private, no-store"
        assert download.headers["content-disposition"] == "attachment"
        assert download.headers["x-content-type-options"] == "nosniff"
        assert "presigned" not in str(download.headers).lower()
        artifact_service_mock.refresh_artifact_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_content_put_returns_receipt_and_structured_revision_conflict(
        self,
        test_db,
        artifacts_client,
        artifact_service_mock,
    ) -> None:
        await self._grant_project_access(test_db)
        content_hash = self._hash("updated")
        artifact_service_mock.save_artifact_content.return_value = ArtifactContentSaveReceipt(
            artifact_id="artifact-1",
            revision=4,
            content_hash=content_hash,
            duplicate=False,
        )
        request = {
            "contract_version": 2,
            "expected_revision": 3,
            "content_hash": content_hash,
            "idempotency_key": "artifact-1:save:0001",
            "content": "updated",
        }

        saved = artifacts_client.put("/api/v1/artifacts/artifact-1/content", json=request)

        assert saved.status_code == 200
        assert saved.json() == {
            "artifact_id": "artifact-1",
            "revision": 4,
            "content_hash": content_hash,
            "duplicate": False,
        }

        artifact_service_mock.save_artifact_content.side_effect = (
            ArtifactContentRevisionConflictError(
                server_revision=5,
                server_content_hash=self._hash("server"),
            )
        )
        conflict = artifacts_client.put("/api/v1/artifacts/artifact-1/content", json=request)

        assert conflict.status_code == 409
        assert conflict.json() == {
            "detail": "Artifact content revision conflict",
            "reason_code": "artifact_content_revision_conflict",
            "server_revision": 5,
            "server_content_hash": self._hash("server"),
        }
