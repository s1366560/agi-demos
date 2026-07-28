"""Durable cloud ArtifactContentContractV2 authority tests."""

import hashlib
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.artifact_content_authority_service import (
    ArtifactContentAuthorityService,
    ArtifactContentScope,
)
from src.application.services.artifact_content_contract import (
    ArtifactContentIdempotencyConflictError,
    ArtifactContentNotEditableError,
    ArtifactContentRevisionConflictError,
    ArtifactContentSaveCommand,
)
from src.domain.ports.services.storage_service_port import UploadResult
from src.infrastructure.adapters.secondary.persistence.artifact_model import ArtifactModel
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation,
    Project,
    Tenant,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_artifact_content_authority import (
    SqlArtifactContentAuthorityRepository,
)

TENANT_ID = "tenant-artifact-v2"
PROJECT_ID = "project-artifact-v2"
CONVERSATION_ID = "conversation-artifact-v2"
ARTIFACT_ID = "artifact-cloud-v2"
INITIAL_OBJECT_KEY = "artifacts/tenant-artifact-v2/project-artifact-v2/report.txt"


def _hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


class DurableRecordingStorage:
    """Process-shared object store double with deterministic failure injection."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {INITIAL_OBJECT_KEY: b"seed"}
        self.uploads: list[str] = []
        self.deletes: list[str] = []
        self.fail_upload = False

    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        del metadata
        if self.fail_upload:
            raise RuntimeError("object store unavailable")
        self.objects[object_key] = file_content
        self.uploads.append(object_key)
        return UploadResult(
            object_key=object_key,
            size_bytes=len(file_content),
            content_type=content_type,
            etag=_hash(file_content.decode("utf-8")),
        )

    async def get_file(self, object_key: str) -> bytes | None:
        return self.objects.get(object_key)

    async def delete_file(self, object_key: str) -> bool:
        self.deletes.append(object_key)
        self.objects.pop(object_key, None)
        return True


async def _seed_authority(session: AsyncSession) -> None:
    user = User(
        id="artifact-authority-user",
        email="artifact-authority@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=False,
    )
    tenant = Tenant(
        id=TENANT_ID,
        name="Artifact Authority",
        slug="artifact-authority",
        owner_id=user.id,
    )
    project = Project(
        id=PROJECT_ID,
        tenant_id=TENANT_ID,
        name="Artifact Authority",
        owner_id=user.id,
    )
    conversation = Conversation(
        id=CONVERSATION_ID,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        user_id=user.id,
        title="Artifact authority",
    )
    artifact = ArtifactModel(
        id=ARTIFACT_ID,
        project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        filename="report.txt",
        mime_type="text/plain",
        category="document",
        size_bytes=4,
        object_key=INITIAL_OBJECT_KEY,
        content_revision=1,
        content_hash=_hash("seed"),
        status="ready",
        artifact_metadata={},
    )
    session.add_all([user, tenant, project, conversation, artifact])
    await session.commit()


def _service(
    session: AsyncSession, storage: DurableRecordingStorage
) -> ArtifactContentAuthorityService:
    return ArtifactContentAuthorityService(
        repository=SqlArtifactContentAuthorityRepository(session),
        storage_service=storage,  # type: ignore[arg-type]
    )


def _command(
    content: str,
    *,
    expected_revision: int = 1,
    idempotency_key: str = "artifact-v2:save:0001",
) -> ArtifactContentSaveCommand:
    return ArtifactContentSaveCommand(
        contract_version=2,
        expected_revision=expected_revision,
        content_hash=_hash(content),
        idempotency_key=idempotency_key,
        content=content,
    )


@pytest.mark.unit
async def test_two_service_instances_share_revision_and_replay_receipt_after_restart(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as first_session:
        await _seed_authority(first_session)
        first_service = _service(first_session, storage)
        scope = await first_service.resolve_scope(ARTIFACT_ID)
        assert scope == ArtifactContentScope(
            artifact_id=ARTIFACT_ID,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            conversation_id=CONVERSATION_ID,
        )
        first = await first_service.save_content(scope, _command("updated"))
        assert first is not None
        assert first.receipt.revision == 2
        assert first.receipt.duplicate is False
        await first_session.commit()

    async with sessions() as restarted_session:
        restarted_service = _service(restarted_session, storage)
        restarted_scope = await restarted_service.resolve_scope(ARTIFACT_ID)
        assert restarted_scope is not None
        authority = await restarted_service.get_content(restarted_scope)
        replay = await restarted_service.save_content(restarted_scope, _command("updated"))

        assert authority is not None
        assert authority.revision == 2
        assert authority.content == "updated"
        assert replay is not None
        assert replay.receipt == first.receipt.with_duplicate()
        assert replay.uploaded_object_key is None
        assert len(storage.uploads) == 1


@pytest.mark.unit
async def test_legacy_content_hash_initialization_survives_service_restart(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as first_session:
        await _seed_authority(first_session)
        _ = await first_session.execute(
            update(ArtifactModel).where(ArtifactModel.id == ARTIFACT_ID).values(content_hash=None)
        )
        await first_session.commit()
        service = _service(first_session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        initialized = await service.get_content(scope)
        assert initialized is not None
        assert initialized.content_hash == _hash("seed")
        await first_session.commit()

    async with sessions() as restarted_session:
        persisted_hash = (
            await restarted_session.execute(
                select(ArtifactModel.content_hash).where(ArtifactModel.id == ARTIFACT_ID)
            )
        ).scalar_one()
        assert persisted_hash == _hash("seed")


@pytest.mark.unit
async def test_idempotency_and_revision_conflicts_preserve_server_pointer(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as first_session:
        await _seed_authority(first_session)
        service = _service(first_session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        saved = await service.save_content(scope, _command("server"))
        assert saved is not None
        await first_session.commit()
        server_object_key = saved.uploaded_object_key

    async with sessions() as second_session:
        service = _service(second_session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None

        with pytest.raises(ArtifactContentIdempotencyConflictError) as key_conflict:
            await service.save_content(scope, _command("different"))
        assert key_conflict.value.server_revision == 2
        assert key_conflict.value.server_content_hash == _hash("server")

        with pytest.raises(ArtifactContentRevisionConflictError) as revision_conflict:
            await service.save_content(
                scope,
                _command(
                    "stale",
                    idempotency_key="artifact-v2:save:0002",
                ),
            )
        assert revision_conflict.value.server_revision == 2
        assert revision_conflict.value.server_content_hash == _hash("server")

        authority = await service.get_content(scope)
        assert authority is not None
        assert authority.revision == 2
        assert authority.content == "server"
        assert server_object_key is not None
        assert storage.objects[server_object_key] == b"server"
        assert len(storage.uploads) == 1


@pytest.mark.unit
async def test_object_write_failure_does_not_publish_new_metadata_pointer(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        storage.fail_upload = True

        with pytest.raises(RuntimeError, match="object store unavailable"):
            await service.save_content(scope, _command("unpublished"))
        await session.rollback()

    async with sessions() as restarted_session:
        service = _service(restarted_session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        authority = await service.get_content(scope)
        assert authority is not None
        assert authority.revision == 1
        assert authority.content_hash == _hash("seed")
        assert authority.content == "seed"
        assert storage.uploads == []


@pytest.mark.unit
async def test_content_save_rejects_non_editable_mime_while_bytes_remain_readable(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        _ = await session.execute(
            update(ArtifactModel)
            .where(ArtifactModel.id == ARTIFACT_ID)
            .values(mime_type="application/pdf")
        )
        await session.commit()
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None

        with pytest.raises(ArtifactContentNotEditableError):
            await service.get_content(scope)
        with pytest.raises(ArtifactContentNotEditableError):
            await service.save_content(scope, _command("updated"))

        raw = await service.get_bytes(scope)
        assert raw is not None
        assert raw.mime_type == "application/pdf"
        assert raw.content == b"seed"


@pytest.mark.unit
async def test_commit_failure_reconciliation_only_deletes_unreferenced_version(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as first_session:
        await _seed_authority(first_session)
        service = _service(first_session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        rolled_back = await service.save_content(scope, _command("rolled-back"))
        assert rolled_back is not None
        await first_session.rollback()

    async with sessions() as cleanup_session:
        service = _service(cleanup_session, storage)
        await service.discard_uncommitted(rolled_back)
        assert rolled_back.uploaded_object_key in storage.deletes

        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        committed = await service.save_content(
            scope,
            _command("committed", idempotency_key="artifact-v2:save:0002"),
        )
        assert committed is not None
        await cleanup_session.commit()

    async with sessions() as restarted_session:
        restarted = _service(restarted_session, storage)
        await restarted.discard_uncommitted(committed)
        assert committed.uploaded_object_key not in storage.deletes
        assert committed.uploaded_object_key in storage.objects


@pytest.mark.unit
async def test_authority_scope_fails_closed_for_tenant_project_conversation_and_artifact(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage)
        canonical = ArtifactContentScope(
            artifact_id=ARTIFACT_ID,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            conversation_id=CONVERSATION_ID,
        )

        assert (
            await service.get_content(
                ArtifactContentScope(
                    artifact_id=canonical.artifact_id,
                    tenant_id="tenant-wrong",
                    project_id=canonical.project_id,
                    conversation_id=canonical.conversation_id,
                )
            )
            is None
        )
        assert (
            await service.get_content(
                ArtifactContentScope(
                    artifact_id=canonical.artifact_id,
                    tenant_id=canonical.tenant_id,
                    project_id="project-wrong",
                    conversation_id=canonical.conversation_id,
                )
            )
            is None
        )
        assert (
            await service.get_content(
                ArtifactContentScope(
                    artifact_id=canonical.artifact_id,
                    tenant_id=canonical.tenant_id,
                    project_id=canonical.project_id,
                    conversation_id="conversation-wrong",
                )
            )
            is None
        )
        assert (
            await service.get_content(
                ArtifactContentScope(
                    artifact_id="artifact-wrong",
                    tenant_id=canonical.tenant_id,
                    project_id=canonical.project_id,
                    conversation_id=canonical.conversation_id,
                )
            )
            is None
        )
