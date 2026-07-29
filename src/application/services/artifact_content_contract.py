"""ArtifactContentContractV2 value objects and structural validation."""

import hashlib
import re
import secrets
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
_SAFE_BINARY_ARTIFACT_MIME_TYPES = frozenset(
    {
        "application/epub+zip",
        "application/gzip",
        "application/msword",
        "application/octet-stream",
        "application/pdf",
        "application/rtf",
        "application/vnd.ms-excel",
        "application/vnd.ms-fontobject",
        "application/vnd.ms-powerpoint",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/x-tar",
        "application/zip",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "audio/webm",
        "font/otf",
        "font/ttf",
        "font/woff",
        "font/woff2",
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/svg+xml",
        "image/tiff",
        "image/webp",
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/x-matroska",
        "video/x-msvideo",
    }
)
KNOWN_ARTIFACT_MIME_TYPES = EDITABLE_ARTIFACT_MIME_TYPES | _SAFE_BINARY_ARTIFACT_MIME_TYPES
_ACTIVE_RAW_ARTIFACT_MIME_TYPES = frozenset(
    {
        "application/javascript",
        "application/xml",
        "image/svg+xml",
        "text/css",
        "text/html",
        "text/javascript",
        "text/xml",
    }
)
_MIME_TOKEN_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


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


def normalize_mime_type(value: object) -> str:
    """Return a known, strictly parsed media type or the safe binary fallback."""
    fallback = "application/octet-stream"
    if not isinstance(value, str) or not value or len(value) > 255:
        return fallback
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return fallback
    parts = [part.strip() for part in value.split(";")]
    if not parts or not parts[0] or any(not part for part in parts[1:]):
        return fallback
    media_parts = parts[0].split("/")
    if (
        len(media_parts) != 2
        or not _MIME_TOKEN_PATTERN.fullmatch(media_parts[0])
        or not _MIME_TOKEN_PATTERN.fullmatch(media_parts[1])
    ):
        return fallback
    for parameter in parts[1:]:
        name, separator, raw_value = parameter.partition("=")
        if (
            not separator
            or not _MIME_TOKEN_PATTERN.fullmatch(name.strip())
            or not _valid_mime_parameter_value(raw_value.strip())
        ):
            return fallback
    normalized = f"{media_parts[0].lower()}/{media_parts[1].lower()}"
    return normalized if normalized in KNOWN_ARTIFACT_MIME_TYPES else fallback


def preview_response_mime_type(value: str) -> str:
    """Prevent raw preview responses from declaring active executable content."""
    normalized = normalize_mime_type(value)
    if normalized in _ACTIVE_RAW_ARTIFACT_MIME_TYPES:
        return "application/octet-stream"
    return normalized


def _valid_mime_parameter_value(value: str) -> bool:
    if _MIME_TOKEN_PATTERN.fullmatch(value):
        return True
    if len(value) < 2 or value[0] != '"' or value[-1] != '"':
        return False
    escaped = False
    for character in value[1:-1]:
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"' or ord(character) < 32 or ord(character) == 127:
            return False
    return not escaped


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
    nonce = secrets.token_hex(16)
    return (
        f"{bucket_prefix}/{artifact.tenant_id}/{artifact.project_id}/{artifact.id}/"
        f"versions/r{revision}-{digest}-{nonce}"
    )
