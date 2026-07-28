"""Durable cloud ArtifactContentContractV2 authority tests."""

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.services.artifact_content_authority_service import (
    MAX_ARTIFACT_DOWNLOAD_BYTES,
    MAX_ARTIFACT_PREVIEW_BYTES,
    MAX_EDITABLE_ARTIFACT_BYTES,
    ArtifactContentAuthorityService,
    ArtifactContentIntegrityError,
    ArtifactContentScope,
    ArtifactContentTooLargeError,
)
from src.application.services.artifact_content_contract import (
    ArtifactContentIdempotencyConflictError,
    ArtifactContentNotEditableError,
    ArtifactContentRevisionConflictError,
    ArtifactContentSaveCommand,
)
from src.domain.ports.repositories.artifact_content_authority_repository import (
    ArtifactContentAuthorityRecord,
    ArtifactContentReceiptRecord,
)
from src.domain.ports.services.storage_service_port import (
    StorageObjectMetadata,
    StorageObjectTooLargeError,
    UploadResult,
)
from src.infrastructure.adapters.secondary.persistence.artifact_content_commit_reconciler import (
    ArtifactContentCommitReconciler,
)
from src.infrastructure.adapters.secondary.persistence.artifact_model import (
    ArtifactContentOrphanGcModel,
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
        self.fail_delete = False
        self.gets: list[str] = []
        self.heads: list[str] = []
        self.bounded_gets: list[tuple[str, int]] = []
        self.streams: list[tuple[str, int]] = []

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
        self.gets.append(object_key)
        return self.objects.get(object_key)

    async def get_file_metadata(self, object_key: str) -> StorageObjectMetadata | None:
        self.heads.append(object_key)
        content = self.objects.get(object_key)
        if content is None:
            return None
        return StorageObjectMetadata(
            size_bytes=len(content),
            content_type="application/octet-stream",
        )

    async def get_file_bounded(self, object_key: str, *, max_bytes: int) -> bytes | None:
        self.bounded_gets.append((object_key, max_bytes))
        content = self.objects.get(object_key)
        if content is not None and len(content) > max_bytes:
            raise StorageObjectTooLargeError(
                actual_bytes=len(content),
                max_bytes=max_bytes,
            )
        return content

    async def stream_file(
        self,
        object_key: str,
        *,
        max_bytes: int,
        chunk_size: int = 64 * 1024,
    ):
        self.streams.append((object_key, max_bytes))
        content = self.objects.get(object_key)
        if content is None:
            return
        if len(content) > max_bytes:
            raise StorageObjectTooLargeError(
                actual_bytes=len(content),
                max_bytes=max_bytes,
            )
        for offset in range(0, len(content), chunk_size):
            yield content[offset : offset + chunk_size]

    async def delete_file(self, object_key: str) -> bool:
        self.deletes.append(object_key)
        if self.fail_delete:
            raise RuntimeError("object delete unavailable")
        self.objects.pop(object_key, None)
        return True


class BarrierAuthorityRepository:
    """Two-writer authority double that exposes the same initial revision."""

    def __init__(self) -> None:
        self.scope = ArtifactContentScope(
            artifact_id=ARTIFACT_ID,
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            conversation_id=CONVERSATION_ID,
        )
        self.authority = ArtifactContentAuthorityRecord(
            scope=self.scope,
            mime_type="text/plain",
            status="ready",
            object_key=INITIAL_OBJECT_KEY,
            size_bytes=4,
            revision=1,
            content_hash=_hash("seed"),
        )
        self.receipts: dict[str, ArtifactContentReceiptRecord] = {}
        self.read_barrier = asyncio.Barrier(2)
        self.advance_lock = asyncio.Lock()

    async def get_authority(
        self,
        scope: ArtifactContentScope,
        *,
        for_update: bool = False,
    ) -> ArtifactContentAuthorityRecord | None:
        assert scope == self.scope
        if for_update:
            snapshot = self.authority
            await self.read_barrier.wait()
            return snapshot
        return self.authority

    async def initialize_content_hash(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("seed authority already has a content hash")

    async def get_receipt(
        self,
        scope: ArtifactContentScope,
        idempotency_key: str,
    ) -> ArtifactContentReceiptRecord | None:
        assert scope == self.scope
        return self.receipts.get(idempotency_key)

    async def advance_pointer(
        self,
        scope: ArtifactContentScope,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_hash: str,
        resulting_revision: int,
        content_hash: str,
        object_key: str,
        size_bytes: int,
    ) -> bool:
        assert scope == self.scope
        async with self.advance_lock:
            if self.authority.revision != expected_revision:
                return False
            self.authority = ArtifactContentAuthorityRecord(
                scope=scope,
                mime_type=self.authority.mime_type,
                status=self.authority.status,
                object_key=object_key,
                size_bytes=size_bytes,
                revision=resulting_revision,
                content_hash=content_hash,
            )
            self.receipts[idempotency_key] = ArtifactContentReceiptRecord(
                request_hash=request_hash,
                resulting_revision=resulting_revision,
                content_hash=content_hash,
                object_key=object_key,
            )
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
    session: AsyncSession,
    storage: DurableRecordingStorage,
    orphan_recorder: Callable[..., Awaitable[None]] | None = None,
) -> ArtifactContentAuthorityService:
    return ArtifactContentAuthorityService(
        repository=SqlArtifactContentAuthorityRepository(session),
        storage_service=storage,  # type: ignore[arg-type]
        orphan_recorder=orphan_recorder,
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
async def test_uploaded_object_is_cleaned_when_upload_await_is_cancelled(
    test_engine,
    monkeypatch,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()
    recorder = AsyncMock()
    original_upload = storage.upload_file

    async def upload_then_cancel(*args: Any, **kwargs: Any) -> UploadResult:
        _ = await original_upload(*args, **kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(storage, "upload_file", upload_then_cancel)

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage, recorder)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None

        with pytest.raises(asyncio.CancelledError):
            await service.save_content(scope, _command("uploaded-then-cancelled"))

    assert len(storage.uploads) == 1
    uploaded_key = storage.uploads[0]
    assert storage.deletes == [uploaded_key]
    assert uploaded_key not in storage.objects
    recorder.assert_not_awaited()


@pytest.mark.unit
async def test_advance_pointer_cancellation_retains_authoritative_object_and_records_candidate(
    test_engine,
    monkeypatch,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()
    recorder = AsyncMock()

    async with sessions() as session:
        await _seed_authority(session)
        repository = SqlArtifactContentAuthorityRepository(session)
        service = ArtifactContentAuthorityService(
            repository=repository,
            storage_service=storage,  # type: ignore[arg-type]
            orphan_recorder=recorder,
        )
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        original_advance = repository.advance_pointer

        async def advance_then_cancel(*args: Any, **kwargs: Any) -> bool:
            advanced = await original_advance(*args, **kwargs)
            assert advanced is True
            raise asyncio.CancelledError

        monkeypatch.setattr(repository, "advance_pointer", advance_then_cancel)

        with pytest.raises(asyncio.CancelledError):
            await service.save_content(scope, _command("authoritative-then-cancelled"))

        authority = await repository.get_authority(scope)
        receipt = await repository.get_receipt(scope, "artifact-v2:save:0001")

    assert authority is not None
    assert receipt is not None
    assert authority.object_key == receipt.object_key == storage.uploads[0]
    assert authority.object_key in storage.objects
    assert authority.object_key not in storage.deletes
    recorder.assert_awaited_once()
    assert recorder.await_args.kwargs == {
        "reason_code": "advance_pointer_cancelled",
        "last_error_code": "operation_cancelled",
    }


@pytest.mark.unit
async def test_cancelled_immediate_delete_still_records_retryable_candidate(
    test_engine,
    monkeypatch,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()
    recorder = AsyncMock()

    async def cancel_delete(object_key: str) -> bool:
        storage.deletes.append(object_key)
        raise asyncio.CancelledError

    monkeypatch.setattr(storage, "delete_file", cancel_delete)

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage, recorder)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        with (
            patch.object(
                SqlArtifactContentAuthorityRepository,
                "advance_pointer",
                new=AsyncMock(return_value=False),
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await service.save_content(scope, _command("delete-cancelled"))

    recorder.assert_awaited_once()
    assert recorder.await_args.kwargs == {
        "reason_code": "immediate_delete_cancelled",
        "last_error_code": "storage_delete_cancelled",
    }


@pytest.mark.unit
async def test_cancellation_during_orphan_recorder_waits_for_durable_audit(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()
    storage.fail_delete = True
    recorder_started = asyncio.Event()
    release_recorder = asyncio.Event()
    recorder_completed = asyncio.Event()
    recorded: list[tuple[str, str]] = []

    async def record_candidate(
        _outcome,
        *,
        reason_code: str,
        last_error_code: str,
    ) -> None:
        recorder_started.set()
        await release_recorder.wait()
        recorded.append((reason_code, last_error_code))
        recorder_completed.set()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage, record_candidate)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        with patch.object(
            SqlArtifactContentAuthorityRepository,
            "advance_pointer",
            new=AsyncMock(return_value=False),
        ):
            save_task = asyncio.create_task(
                service.save_content(scope, _command("audit-cancelled"))
            )
            await asyncio.wait_for(recorder_started.wait(), timeout=1)
            save_task.cancel()
            release_recorder.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(save_task, timeout=1)

    assert recorder_completed.is_set()
    assert recorded == [("immediate_delete_failed", "storage_delete_failed")]


@pytest.mark.unit
async def test_failed_immediate_orphan_delete_is_persisted_through_fresh_recorder(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()
    recorder = AsyncMock()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage, recorder)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        storage.fail_delete = True
        with (
            patch.object(
                SqlArtifactContentAuthorityRepository,
                "advance_pointer",
                new=AsyncMock(return_value=False),
            ),
            pytest.raises(ArtifactContentRevisionConflictError),
        ):
            await service.save_content(scope, _command("uncommitted"))

    recorder.assert_awaited_once()
    outcome = recorder.await_args.args[0]
    assert outcome.uploaded_object_key in storage.objects
    assert recorder.await_args.kwargs == {
        "reason_code": "immediate_delete_failed",
        "last_error_code": "storage_delete_failed",
    }


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
        assert raw.revision == 1
        assert raw.content_hash == _hash("seed")
        assert raw.content == b"seed"


@pytest.mark.unit
async def test_commit_failure_reconciler_uses_fresh_authority_and_audits_gc(
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

    reconciler = ArtifactContentCommitReconciler(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
    )
    await reconciler.reconcile(rolled_back)
    assert rolled_back.uploaded_object_key in storage.deletes

    async with sessions() as cleanup_session:
        service = _service(cleanup_session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        committed = await service.save_content(
            scope,
            _command("committed", idempotency_key="artifact-v2:save:0002"),
        )
        assert committed is not None
        await cleanup_session.commit()

    await reconciler.reconcile(committed)
    async with sessions() as restarted_session:
        gc_rows = (
            (await restarted_session.execute(select(ArtifactContentOrphanGcModel))).scalars().all()
        )
        assert len(gc_rows) == 1
        assert gc_rows[0].object_key == rolled_back.uploaded_object_key
        assert gc_rows[0].status == "deleted"
        assert committed.uploaded_object_key not in storage.deletes
        assert committed.uploaded_object_key in storage.objects


@pytest.mark.unit
async def test_ambiguous_reconciliation_retains_object_and_persists_pending_gc(
    test_engine,
    monkeypatch,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        outcome = await service.save_content(scope, _command("ambiguous"))
        assert outcome is not None
        await session.rollback()

    reconciler = ArtifactContentCommitReconciler(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
    )

    async def fail_authority_check(_outcome, *, lease_token: str) -> bool:
        del lease_token
        raise RuntimeError("primary authority unavailable")

    monkeypatch.setattr(reconciler, "_inspect_and_stage", fail_authority_check)
    await reconciler.reconcile(outcome)

    assert outcome.uploaded_object_key in storage.objects
    assert outcome.uploaded_object_key not in storage.deletes
    async with sessions() as audit_session:
        audit = (
            await audit_session.execute(
                select(ArtifactContentOrphanGcModel).where(
                    ArtifactContentOrphanGcModel.object_key == outcome.uploaded_object_key
                )
            )
        ).scalar_one()
        assert audit.status == "pending"
        assert audit.reason_code == "authority_check_failed"
        assert audit.last_error_code == "authority_check_failed"


@pytest.mark.unit
async def test_same_revision_writers_upload_unique_objects_and_only_gc_loser() -> None:
    repository = BarrierAuthorityRepository()
    storage = DurableRecordingStorage()
    first = ArtifactContentAuthorityService(
        repository=repository,  # type: ignore[arg-type]
        storage_service=storage,  # type: ignore[arg-type]
    )
    second = ArtifactContentAuthorityService(
        repository=repository,  # type: ignore[arg-type]
        storage_service=storage,  # type: ignore[arg-type]
    )

    results = await asyncio.gather(
        first.save_content(
            repository.scope,
            _command("same", idempotency_key="artifact-v2:race:first"),
        ),
        second.save_content(
            repository.scope,
            _command("same", idempotency_key="artifact-v2:race:second"),
        ),
        return_exceptions=True,
    )

    assert len(storage.uploads) == 2
    assert storage.uploads[0] != storage.uploads[1]
    assert all("/versions/r2-" in key for key in storage.uploads)
    assert all(_hash("same").removeprefix("sha256:") in key for key in storage.uploads)
    assert sum(isinstance(result, ArtifactContentRevisionConflictError) for result in results) == 1
    assert repository.authority.object_key in storage.objects
    loser_keys = set(storage.uploads) - {repository.authority.object_key}
    assert loser_keys == set(storage.deletes)


@pytest.mark.unit
def test_postgresql_authority_lock_targets_only_the_artifact_row() -> None:
    scope = ArtifactContentScope(
        artifact_id=ARTIFACT_ID,
        tenant_id=TENANT_ID,
        project_id=PROJECT_ID,
        conversation_id=CONVERSATION_ID,
    )

    statement = SqlArtifactContentAuthorityRepository._authority_statement(
        scope,
        for_update=True,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "LEFT OUTER JOIN conversations" in sql
    assert sql.endswith("FOR UPDATE OF artifacts")


@pytest.mark.unit
async def test_commit_reconciler_waits_for_locked_authority_before_delete(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        outcome = await service.save_content(scope, _command("ambiguous-lock"))
        assert outcome is not None
        await session.rollback()

    lock_entered = asyncio.Event()
    release_lock = asyncio.Event()

    async def locked_authority_read(
        repository,
        scope,
        *,
        for_update: bool = False,
    ):
        del repository, scope
        assert for_update is True
        lock_entered.set()
        await release_lock.wait()
        return None

    reconciler = ArtifactContentCommitReconciler(
        session_factory=sessions,
        storage_service=storage,  # type: ignore[arg-type]
    )
    with patch.object(
        SqlArtifactContentAuthorityRepository,
        "get_authority",
        new=locked_authority_read,
    ):
        reconcile_task = asyncio.create_task(reconciler.reconcile(outcome))
        await asyncio.wait_for(lock_entered.wait(), timeout=1)
        assert outcome.uploaded_object_key not in storage.deletes

        release_lock.set()
        await asyncio.wait_for(reconcile_task, timeout=1)

    assert outcome.uploaded_object_key in storage.deletes


@pytest.mark.unit
async def test_verified_reads_fail_closed_on_tamper_and_oversized_metadata(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None

        storage.objects[INITIAL_OBJECT_KEY] = b"evil"
        with pytest.raises(ArtifactContentIntegrityError):
            await service.get_bytes(scope, max_bytes=MAX_ARTIFACT_DOWNLOAD_BYTES)

        storage.objects[INITIAL_OBJECT_KEY] = b"seed"
        storage.gets.clear()
        _ = await session.execute(
            update(ArtifactModel)
            .where(ArtifactModel.id == ARTIFACT_ID)
            .values(size_bytes=MAX_ARTIFACT_DOWNLOAD_BYTES + 1)
        )
        await session.commit()
        with pytest.raises(ArtifactContentTooLargeError) as too_large:
            await service.get_bytes(scope, max_bytes=MAX_ARTIFACT_DOWNLOAD_BYTES)
        assert too_large.value.max_bytes == MAX_ARTIFACT_DOWNLOAD_BYTES
        assert storage.gets == []

        _ = await session.execute(
            update(ArtifactModel).where(ArtifactModel.id == ARTIFACT_ID).values(size_bytes=4)
        )
        await session.commit()
        storage.objects[INITIAL_OBJECT_KEY] = b"overs"
        with pytest.raises(ArtifactContentTooLargeError):
            await service.get_bytes(scope, max_bytes=4)

        storage.objects.pop(INITIAL_OBJECT_KEY)
        with pytest.raises(ArtifactContentIntegrityError):
            await service.get_bytes(scope, max_bytes=MAX_ARTIFACT_DOWNLOAD_BYTES)


@pytest.mark.unit
async def test_download_is_hash_verified_into_a_disk_backed_bounded_stream(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None

        download = await service.stage_download(
            scope,
            max_bytes=MAX_ARTIFACT_DOWNLOAD_BYTES,
        )
        assert download is not None
        assert download.size_bytes == 4
        assert download.content_hash == _hash("seed")
        assert storage.streams == [(INITIAL_OBJECT_KEY, MAX_ARTIFACT_DOWNLOAD_BYTES)]
        assert storage.gets == []

        content = b"".join([chunk async for chunk in download.iter_chunks(chunk_size=2)])
        assert content == b"seed"
        assert not download.staged_path.exists()


@pytest.mark.unit
async def test_legacy_raw_read_conditionally_initializes_hash_and_returns_authority(
    test_engine,
) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        _ = await session.execute(
            update(ArtifactModel).where(ArtifactModel.id == ARTIFACT_ID).values(content_hash=None)
        )
        await session.commit()
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None

        raw = await service.get_bytes(scope, max_bytes=MAX_ARTIFACT_PREVIEW_BYTES)
        await session.commit()

        assert raw is not None
        assert raw.revision == 1
        assert raw.content_hash == _hash("seed")
        assert raw.content == b"seed"
        persisted_hash = (
            await session.execute(
                select(ArtifactModel.content_hash).where(ArtifactModel.id == ARTIFACT_ID)
            )
        ).scalar_one()
        assert persisted_hash == _hash("seed")


@pytest.mark.unit
async def test_save_enforces_utf8_byte_limit_and_rejects_crlf_mime(test_engine) -> None:
    sessions = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    storage = DurableRecordingStorage()

    async with sessions() as session:
        await _seed_authority(session)
        service = _service(session, storage)
        scope = await service.resolve_scope(ARTIFACT_ID)
        assert scope is not None
        multibyte_content = "界" * ((MAX_EDITABLE_ARTIFACT_BYTES // 3) + 1)

        with pytest.raises(ArtifactContentTooLargeError) as too_large:
            await service.save_content(scope, _command(multibyte_content))
        assert too_large.value.actual_bytes > MAX_EDITABLE_ARTIFACT_BYTES
        assert storage.uploads == []

        _ = await session.execute(
            update(ArtifactModel)
            .where(ArtifactModel.id == ARTIFACT_ID)
            .values(mime_type="text/plain\r\nX-Injected: yes")
        )
        await session.commit()
        raw = await service.get_bytes(scope)
        assert raw is not None
        assert raw.mime_type == "application/octet-stream"
        with pytest.raises(ArtifactContentNotEditableError):
            await service.get_content(scope)

        _ = await session.execute(
            update(ArtifactModel)
            .where(ArtifactModel.id == ARTIFACT_ID)
            .values(mime_type="application/x-memstack-unknown")
        )
        await session.commit()
        raw_unknown = await service.get_bytes(scope)
        assert raw_unknown is not None
        assert raw_unknown.mime_type == "application/octet-stream"


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
