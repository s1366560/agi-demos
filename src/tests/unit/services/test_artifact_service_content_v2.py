"""ArtifactContentContractV2 service tests."""

import hashlib
from typing import Any

import pytest

from src.application.services.artifact_content_contract import (
    ArtifactContentHashMismatchError,
    ArtifactContentIdempotencyConflictError,
    ArtifactContentNotEditableError,
    ArtifactContentRevisionConflictError,
    ArtifactContentSaveCommand,
    artifact_save_request_hash,
)
from src.application.services.artifact_service import ArtifactService
from src.domain.model.artifact.artifact import Artifact, ArtifactCategory, ArtifactStatus
from src.domain.ports.services.storage_service_port import UploadResult


def _content_hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


class RecordingStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.uploads: list[tuple[str, bytes, str]] = []

    async def upload_file(
        self,
        file_content: bytes,
        object_key: str,
        content_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        del metadata
        self.objects[object_key] = file_content
        self.uploads.append((object_key, file_content, content_type))
        return UploadResult(
            object_key=object_key,
            size_bytes=len(file_content),
            content_type=content_type,
            etag=_content_hash(file_content.decode("utf-8")),
        )

    async def get_file(self, object_key: str) -> bytes | None:
        return self.objects.get(object_key)

    async def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        del args, kwargs
        raise AssertionError("ArtifactContentContractV2 must not generate a presigned URL")


def _ready_artifact(*, mime_type: str = "text/plain") -> Artifact:
    return Artifact(
        id="artifact-v2",
        project_id="project-v2",
        tenant_id="tenant-v2",
        filename="report.txt",
        mime_type=mime_type,
        category=ArtifactCategory.DOCUMENT,
        size_bytes=4,
        object_key="artifacts/tenant-v2/project-v2/report.txt",
        status=ArtifactStatus.READY,
        url="https://storage.invalid/presigned-secret",
    )


def test_content_v2_request_fingerprint_matches_cross_runtime_contract() -> None:
    command = ArtifactContentSaveCommand(
        contract_version=2,
        expected_revision=1,
        content_hash=_content_hash("updated"),
        idempotency_key="artifact-v2:save:0001",
        content="updated",
    )

    assert artifact_save_request_hash("artifact-v2", command) == (
        "sha256:99009b05d03d76249c37a09ec4c3e7f9a3096173f094e0421736197525515a21"
    )


@pytest.fixture
def service_and_storage() -> tuple[ArtifactService, RecordingStorage]:
    storage = RecordingStorage()
    artifact = _ready_artifact()
    storage.objects[artifact.object_key] = b"seed"
    service = ArtifactService(storage_service=storage)  # type: ignore[arg-type]
    service._artifacts[artifact.id] = artifact
    return service, storage


@pytest.mark.unit
async def test_get_content_v2_returns_canonical_text_authority_without_presigned_url(
    service_and_storage,
) -> None:
    service, _storage = service_and_storage

    contract = await service.get_artifact_content("artifact-v2")

    assert contract is not None
    assert contract.contract_version == 2
    assert contract.artifact_id == "artifact-v2"
    assert contract.revision == 1
    assert contract.content_hash == _content_hash("seed")
    assert contract.mime_type == "text/plain"
    assert contract.content == "seed"
    assert "url" not in contract.__dict__


@pytest.mark.unit
async def test_get_content_v2_rejects_non_editable_mime_but_bytes_remain_available() -> None:
    storage = RecordingStorage()
    artifact = _ready_artifact(mime_type="application/pdf")
    storage.objects[artifact.object_key] = b"%PDF"
    service = ArtifactService(storage_service=storage)  # type: ignore[arg-type]
    service._artifacts[artifact.id] = artifact

    with pytest.raises(ArtifactContentNotEditableError):
        await service.get_artifact_content(artifact.id)

    assert await service.get_artifact_bytes(artifact.id) == b"%PDF"


@pytest.mark.unit
async def test_save_content_v2_versions_pointer_and_replays_same_idempotency_key(
    service_and_storage,
) -> None:
    service, storage = service_and_storage
    command = ArtifactContentSaveCommand(
        contract_version=2,
        expected_revision=1,
        content_hash=_content_hash("updated"),
        idempotency_key="artifact-v2:save:0001",
        content="updated",
    )

    first = await service.save_artifact_content("artifact-v2", command)
    replay = await service.save_artifact_content("artifact-v2", command)

    assert first is not None
    assert first.artifact_id == "artifact-v2"
    assert first.revision == 2
    assert first.content_hash == command.content_hash
    assert first.duplicate is False
    assert replay == first.with_duplicate()
    assert len(storage.uploads) == 1

    artifact = await service.get_artifact("artifact-v2")
    assert artifact is not None
    assert artifact.object_key == (
        "artifacts/tenant-v2/project-v2/artifact-v2/versions/"
        f"r2-{command.content_hash.removeprefix('sha256:')}"
    )
    assert artifact.url is None
    assert storage.objects[artifact.object_key] == b"updated"
    assert storage.objects["artifacts/tenant-v2/project-v2/report.txt"] == b"seed"


@pytest.mark.unit
async def test_save_content_v2_rejects_hash_revision_and_idempotency_conflicts(
    service_and_storage,
) -> None:
    service, _storage = service_and_storage
    first = ArtifactContentSaveCommand(
        contract_version=2,
        expected_revision=1,
        content_hash=_content_hash("updated"),
        idempotency_key="artifact-v2:save:0001",
        content="updated",
    )
    await service.save_artifact_content("artifact-v2", first)

    with pytest.raises(ArtifactContentIdempotencyConflictError) as key_conflict:
        await service.save_artifact_content(
            "artifact-v2",
            ArtifactContentSaveCommand(
                contract_version=2,
                expected_revision=1,
                content_hash=_content_hash("different"),
                idempotency_key=first.idempotency_key,
                content="different",
            ),
        )
    assert key_conflict.value.server_revision == 2
    assert key_conflict.value.server_content_hash == first.content_hash

    with pytest.raises(ArtifactContentRevisionConflictError) as revision_conflict:
        await service.save_artifact_content(
            "artifact-v2",
            ArtifactContentSaveCommand(
                contract_version=2,
                expected_revision=1,
                content_hash=_content_hash("newer"),
                idempotency_key="artifact-v2:save:0002",
                content="newer",
            ),
        )
    assert revision_conflict.value.server_revision == 2
    assert revision_conflict.value.server_content_hash == first.content_hash

    with pytest.raises(ArtifactContentHashMismatchError):
        await service.save_artifact_content(
            "artifact-v2",
            ArtifactContentSaveCommand(
                contract_version=2,
                expected_revision=2,
                content_hash=_content_hash("not-the-content"),
                idempotency_key="artifact-v2:save:0003",
                content="actual-content",
            ),
        )
