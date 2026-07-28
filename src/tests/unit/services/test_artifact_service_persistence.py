"""Persistent Artifact lifecycle authority tests."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.artifact_content_authority_service import (
    ArtifactContentAuthorityService,
)
from src.application.services.artifact_content_contract import (
    ArtifactContentSaveCommand,
)
from src.application.services.artifact_service import ArtifactService
from src.domain.model.artifact.artifact import ArtifactStatus
from src.domain.ports.services.storage_service_port import (
    StorageObjectMetadata,
    UploadResult,
)
from src.infrastructure.adapters.secondary.persistence.artifact_model import (
    ArtifactModel,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_artifact_repository import (
    SqlArtifactRepository,
)

TENANT_ID = "tenant-artifact-lifecycle"
PROJECT_ID = "project-artifact-lifecycle"
CONVERSATION_ID = "conversation-artifact-lifecycle"
ARTIFACT_ID = "artifact-lifecycle"


def _hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


class LifecycleStorage:
    """Process-shared object store double with a controllable upload barrier."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.upload_started = asyncio.Event()
        self.upload_release = asyncio.Event()
        self.block_upload = False
        self.presigned_keys: list[str] = []

    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        del metadata
        self.upload_started.set()
        if self.block_upload:
            await self.upload_release.wait()
        self.objects[object_key] = file_content
        return UploadResult(
            object_key=object_key,
            size_bytes=len(file_content),
            content_type=content_type,
            etag=_hash(file_content),
        )

    async def generate_presigned_url(
        self,
        object_key: str,
        expiration_seconds: int,
    ) -> str:
        del expiration_seconds
        self.presigned_keys.append(object_key)
        return f"https://storage.invalid/{object_key}"

    async def get_file(self, object_key: str) -> bytes | None:
        return self.objects.get(object_key)

    async def get_file_metadata(self, object_key: str) -> StorageObjectMetadata | None:
        content = self.objects.get(object_key)
        if content is None:
            return None
        return StorageObjectMetadata(
            size_bytes=len(content),
            content_type="application/octet-stream",
        )

    async def get_file_bounded(self, object_key: str, *, max_bytes: int) -> bytes | None:
        content = self.objects.get(object_key)
        if content is None or len(content) > max_bytes:
            return None
        return content

    async def stream_file(
        self,
        object_key: str,
        *,
        max_bytes: int,
        chunk_size: int = 64 * 1024,
    ) -> AsyncIterator[bytes]:
        content = self.objects.get(object_key)
        if content is None or len(content) > max_bytes:
            return
        for offset in range(0, len(content), chunk_size):
            yield content[offset : offset + chunk_size]

    async def delete_file(self, object_key: str) -> bool:
        return self.objects.pop(object_key, None) is not None


async def _seed_scope(session: AsyncSession) -> None:
    user = User(
        id="artifact-lifecycle-user",
        email="artifact-lifecycle@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=False,
    )
    session.add_all(
        [
            user,
            Tenant(
                id=TENANT_ID,
                name="Artifact Lifecycle",
                slug="artifact-lifecycle",
                owner_id=user.id,
            ),
            Project(
                id=PROJECT_ID,
                tenant_id=TENANT_ID,
                name="Artifact Lifecycle",
                owner_id=user.id,
            ),
            Conversation(
                id=CONVERSATION_ID,
                project_id=PROJECT_ID,
                tenant_id=TENANT_ID,
                user_id=user.id,
                title="Artifact lifecycle",
            ),
        ]
    )
    await session.commit()


def _service(
    sessions: async_sessionmaker[AsyncSession],
    storage: LifecycleStorage,
) -> ArtifactService:
    return ArtifactService(
        storage_service=storage,  # type: ignore[arg-type]
        artifact_repository=SqlArtifactRepository(sessions),
    )


@pytest.mark.unit
async def test_persistent_artifact_authority_survives_service_rebuild_and_content_save(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = LifecycleStorage()
    async with sessions() as session:
        await _seed_scope(session)

    created = await _service(sessions, storage).create_artifact(
        file_content=b"seed",
        filename="report.txt",
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        tool_execution_id="tool-execution-lifecycle",
        conversation_id=CONVERSATION_ID,
        artifact_id=ARTIFACT_ID,
    )
    assert created.status is ArtifactStatus.READY

    rebuilt = _service(sessions, storage)
    recovered = await rebuilt.get_artifact(ARTIFACT_ID)
    assert recovered is not None
    assert recovered.status is ArtifactStatus.READY
    assert [item.id for item in await rebuilt.get_artifacts_by_project(PROJECT_ID)] == [ARTIFACT_ID]
    assert [
        item.id
        for item in await rebuilt.get_artifacts_by_tool_execution("tool-execution-lifecycle")
    ] == [ARTIFACT_ID]

    async with sessions() as session:
        content_service = ArtifactContentAuthorityService(
            repository=SqlArtifactContentAuthorityRepository(session),
            storage_service=storage,  # type: ignore[arg-type]
        )
        scope = await content_service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        command = ArtifactContentSaveCommand(
            contract_version=2,
            expected_revision=1,
            content_hash=_hash(b"updated"),
            idempotency_key="artifact-lifecycle:save:1",
            content="updated",
        )
        outcome = await content_service.save_content(scope, command)
        assert outcome is not None
        await session.commit()
        version_key = outcome.uploaded_object_key
        assert version_key is not None

    rebuilt_after_save = _service(sessions, storage)
    saved = await rebuilt_after_save.get_artifact(ARTIFACT_ID)
    assert saved is not None
    assert saved.object_key == version_key
    assert saved.metadata["content_revision"] == 2
    assert saved.metadata["content_hash"] == _hash(b"updated")

    refreshed_url = await rebuilt_after_save.refresh_artifact_url(ARTIFACT_ID)
    assert refreshed_url == f"https://storage.invalid/{version_key}"
    assert storage.presigned_keys[-1] == version_key
    assert await rebuilt_after_save.delete_artifact(ARTIFACT_ID) is True

    after_delete = await _service(sessions, storage).get_artifact(ARTIFACT_ID)
    assert after_delete is not None
    assert after_delete.status is ArtifactStatus.DELETED
    assert version_key not in storage.objects


@pytest.mark.unit
async def test_cancelled_create_finishes_upload_and_durable_lifecycle_transition(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = LifecycleStorage()
    storage.block_upload = True
    async with sessions() as session:
        await _seed_scope(session)

    create_task = asyncio.create_task(
        _service(sessions, storage).create_artifact(
            file_content=b"seed",
            filename="report.txt",
            project_id=PROJECT_ID,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            artifact_id=ARTIFACT_ID,
        )
    )
    await storage.upload_started.wait()
    during_upload = await _service(sessions, storage).get_artifact(ARTIFACT_ID)
    assert during_upload is not None
    assert during_upload.status is ArtifactStatus.UPLOADING

    create_task.cancel()
    storage.upload_release.set()
    with pytest.raises(asyncio.CancelledError):
        await create_task

    after_restart = await _service(sessions, storage).get_artifact(ARTIFACT_ID)
    assert after_restart is not None
    assert after_restart.status is ArtifactStatus.READY
    assert after_restart.object_key in storage.objects


@pytest.mark.unit
async def test_failed_upload_remains_durably_error_after_service_rebuild(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = LifecycleStorage()
    async with sessions() as session:
        await _seed_scope(session)

    async def fail_upload(*args: Any, **kwargs: Any) -> UploadResult:
        del args, kwargs
        raise RuntimeError("storage unavailable")

    storage.upload_file = fail_upload  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await _service(sessions, storage).create_artifact(
            file_content=b"seed",
            filename="report.txt",
            project_id=PROJECT_ID,
            tenant_id=TENANT_ID,
            conversation_id=CONVERSATION_ID,
            artifact_id=ARTIFACT_ID,
        )

    async with sessions() as session:
        model = await session.get(ArtifactModel, ARTIFACT_ID)
        assert model is not None
        assert model.status == ArtifactStatus.ERROR.value
        assert model.error_message == "storage unavailable"
