"""ArtifactContentContractV2 value objects and structural validation."""

import hashlib
import re
from dataclasses import dataclass, replace
from typing import cast

from src.domain.model.artifact.artifact import Artifact

ARTIFACT_CONTENT_RECEIPTS_METADATA_KEY = "_artifact_content_v2_receipts"
_CONTENT_HASH_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
EDITABLE_ARTIFACT_MIME_TYPES = frozenset(
    {
        "application/javascript",
        "application/json",
        "application/xml",
        "application/x-yaml",
        "text/css",
        "text/csv",
        "text/html",
        "text/javascript",
        "text/markdown",
        "text/plain",
        "text/x-c",
        "text/x-c++",
        "text/x-go",
        "text/x-java",
        "text/x-php",
        "text/x-python",
        "text/x-ruby",
        "text/x-rust",
        "text/x-shellscript",
        "text/x-typescript",
        "text/xml",
        "text/yaml",
    }
)


@dataclass(frozen=True)
class ArtifactContentContract:
    """Canonical editable Artifact content authority."""

    contract_version: int
    artifact_id: str
    revision: int
    content_hash: str
    mime_type: str
    content: str


@dataclass(frozen=True)
class ArtifactContentSaveCommand:
    """Validated-on-use ArtifactContentContractV2 save command."""

    contract_version: int
    expected_revision: int
    content_hash: str
    idempotency_key: str
    content: str


@dataclass(frozen=True)
class ArtifactContentSaveReceipt:
    """Durable-observable result of a content save."""

    artifact_id: str
    revision: int
    content_hash: str
    duplicate: bool

    def with_duplicate(self) -> "ArtifactContentSaveReceipt":
        """Return the replay form without mutating the stored receipt."""
        return replace(self, duplicate=True)


class ArtifactContentError(Exception):
    """Base error for ArtifactContentContractV2 operations."""

    reason_code = "artifact_content_error"


class ArtifactContentContractError(ArtifactContentError):
    """Raised when a V2 command violates the structural contract."""

    reason_code = "artifact_content_command_invalid"


class ArtifactContentNotEditableError(ArtifactContentError):
    """Raised when a binary or unsupported MIME is used as editable text."""

    reason_code = "artifact_content_mime_not_editable"


class ArtifactContentHashMismatchError(ArtifactContentContractError):
    """Raised when a command hash does not identify its UTF-8 content."""

    reason_code = "artifact_content_hash_mismatch"


class ArtifactContentIntegrityError(ArtifactContentError):
    """Raised when stored bytes do not match persisted content authority."""

    reason_code = "artifact_content_integrity_mismatch"


class ArtifactContentContractVersionError(ArtifactContentContractError):
    """Raised when a caller uses an unsupported content contract version."""

    reason_code = "artifact_content_contract_version_unsupported"


class ArtifactContentConflictError(ArtifactContentError):
    """Base error carrying the current server authority for conflict recovery."""

    def __init__(self, *, server_revision: int, server_content_hash: str) -> None:
        super().__init__(self.reason_code)
        self.server_revision = server_revision
        self.server_content_hash = server_content_hash


class ArtifactContentRevisionConflictError(ArtifactContentConflictError):
    """Raised when expected_revision is not the current server revision."""

    reason_code = "artifact_content_revision_conflict"


class ArtifactContentIdempotencyConflictError(ArtifactContentConflictError):
    """Raised when an idempotency key is reused with a different payload."""

    reason_code = "artifact_content_idempotency_conflict"


def normalize_mime_type(value: str) -> str:
    return value.split(";", maxsplit=1)[0].strip().lower()


def artifact_content_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def artifact_content_revision(artifact: Artifact) -> int:
    value: object = artifact.metadata.get("content_revision", 1)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactContentIntegrityError
    return value


def artifact_content_receipts(artifact: Artifact) -> dict[str, object]:
    value: object = artifact.metadata.get(ARTIFACT_CONTENT_RECEIPTS_METADATA_KEY)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ArtifactContentIntegrityError
    receipts = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in receipts):
        raise ArtifactContentIntegrityError
    return cast(dict[str, object], receipts)


def parse_artifact_content_receipt(value: object) -> tuple[str, int, str]:
    if not isinstance(value, dict):
        raise ArtifactContentIntegrityError
    receipt = cast(dict[object, object], value)
    request_hash = receipt.get("request_hash")
    revision = receipt.get("revision")
    content_hash = receipt.get("content_hash")
    if (
        not isinstance(request_hash, str)
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
        or not isinstance(content_hash, str)
        or not _CONTENT_HASH_PATTERN.fullmatch(content_hash)
    ):
        raise ArtifactContentIntegrityError
    return request_hash, revision, content_hash


def validate_artifact_content_command(command: ArtifactContentSaveCommand) -> None:
    if command.contract_version != 2:
        raise ArtifactContentContractVersionError
    if (
        isinstance(command.expected_revision, bool)
        or not isinstance(command.expected_revision, int)
        or command.expected_revision < 0
    ):
        raise ArtifactContentContractError("invalid expected revision")
    if not _CONTENT_HASH_PATTERN.fullmatch(command.content_hash):
        raise ArtifactContentHashMismatchError
    if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(command.idempotency_key):
        raise ArtifactContentContractError("invalid idempotency key")


def artifact_save_request_hash(
    artifact_id: str,
    command: ArtifactContentSaveCommand,
) -> str:
    digest = hashlib.sha256()
    for value in (
        "artifact-content-v2",
        artifact_id,
        str(command.expected_revision),
        command.content_hash,
        command.content,
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def versioned_artifact_object_key(
    *,
    bucket_prefix: str,
    artifact: Artifact,
    revision: int,
    content_hash: str,
) -> str:
    digest = content_hash.removeprefix("sha256:")
    return (
        f"{bucket_prefix}/{artifact.tenant_id}/{artifact.project_id}/{artifact.id}/"
        f"versions/r{revision}-{digest}"
    )
