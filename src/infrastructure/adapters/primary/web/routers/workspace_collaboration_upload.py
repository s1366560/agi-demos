"""Bounded multipart staging for Workspace Collaboration uploads."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, TypedDict, cast

from fastapi import HTTPException, Request, status
from python_multipart.multipart import MultipartParser, parse_options_header

from src.application.services.blackboard_file_service import (
    MAX_FILE_SIZE,
    create_upload_staging_path,
)
from src.infrastructure.i18n import gettext as _

if TYPE_CHECKING:
    from python_multipart.multipart import MultipartCallbacks

MAX_WORKSPACE_UPLOAD_BYTES = MAX_FILE_SIZE
MAX_MULTIPART_REQUEST_BYTES = MAX_WORKSPACE_UPLOAD_BYTES + (1024 * 1024)
_MAX_MULTIPART_FIELD_BYTES = 64 * 1024


class _MultipartCallbacks(TypedDict, total=False):
    on_part_begin: Callable[[], None]
    on_part_data: Callable[[bytes, int, int], None]
    on_part_end: Callable[[], None]
    on_header_field: Callable[[bytes, int, int], None]
    on_header_value: Callable[[bytes, int, int], None]
    on_header_end: Callable[[], None]
    on_headers_finished: Callable[[], None]
    on_end: Callable[[], None]


def _decode_multipart_value(value: bytes, charset: str) -> str:
    try:
        return value.decode(charset)
    except (LookupError, UnicodeDecodeError):
        return value.decode("latin-1")


def _write_file_buffers(destination: BinaryIO, buffers: tuple[memoryview, ...]) -> None:
    for buffer in buffers:
        written = destination.write(buffer)
        if written != len(buffer):
            raise OSError("Workspace upload staging write was incomplete")


async def _complete_file_io(operation: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(operation)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.shield(task)
        raise


@dataclass(frozen=True, kw_only=True)
class StagedWorkspaceUpload:
    """Metadata and private path for one fully bounded upload."""

    path: Path
    parent_path: str
    filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str


class _WorkspaceMultipartStream:
    """Parse one multipart upload while writing file bytes directly to staging."""

    def __init__(self, *, charset: str) -> None:
        self._charset = charset
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._content_disposition = b""
        self._content_type = ""
        self._part_name: str | None = None
        self._part_kind: str | None = None
        self._field_data = bytearray()
        self._parent_path = "/"
        self._parent_seen = False
        self._file_seen = False
        self._file_finished = False
        self._filename = ""
        self._staged_path: Path | None = None
        self._destination: BinaryIO | None = None
        self._pending_file_buffers: list[memoryview] = []
        self._size_bytes = 0
        self._digest = hashlib.sha256()
        self._ended = False

    @property
    def callbacks(self) -> _MultipartCallbacks:
        return {
            "on_part_begin": self.on_part_begin,
            "on_part_data": self.on_part_data,
            "on_part_end": self.on_part_end,
            "on_header_field": self.on_header_field,
            "on_header_value": self.on_header_value,
            "on_header_end": self.on_header_end,
            "on_headers_finished": self.on_headers_finished,
            "on_end": self.on_end,
        }

    def on_part_begin(self) -> None:
        self._header_name.clear()
        self._header_value.clear()
        self._content_disposition = b""
        self._content_type = ""
        self._part_name = None
        self._part_kind = None
        self._field_data.clear()

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        buffer = memoryview(data)[start:end]
        if self._part_kind == "file":
            self._size_bytes += len(buffer)
            if self._size_bytes > MAX_WORKSPACE_UPLOAD_BYTES:
                raise upload_too_large()
            self._digest.update(buffer)
            self._pending_file_buffers.append(buffer)
            return
        if self._part_kind == "parent_path":
            if len(self._field_data) + len(buffer) > _MAX_MULTIPART_FIELD_BYTES:
                raise ValueError("Workspace upload parent path is too large")
            self._field_data.extend(buffer)
            return
        raise ValueError("Workspace upload part data preceded its headers")

    def on_part_end(self) -> None:
        if self._part_kind == "file":
            self._file_finished = True
        elif self._part_kind == "parent_path":
            self._parent_path = _decode_multipart_value(
                bytes(self._field_data),
                self._charset,
            )
        else:
            raise ValueError("Workspace upload part is invalid")
        self._part_kind = None

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._extend_bounded_header(self._header_name, data[start:end])

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._extend_bounded_header(self._header_value, data[start:end])

    def on_header_end(self) -> None:
        header_name = bytes(self._header_name).lower()
        header_value = bytes(self._header_value)
        if header_name == b"content-disposition":
            self._content_disposition = header_value
        elif header_name == b"content-type":
            self._content_type = _decode_multipart_value(header_value, "latin-1")
        self._header_name.clear()
        self._header_value.clear()

    def on_headers_finished(self) -> None:
        disposition, options = parse_options_header(self._content_disposition)
        if disposition != b"form-data" or b"name" not in options:
            raise ValueError("Workspace upload Content-Disposition is invalid")
        self._part_name = _decode_multipart_value(options[b"name"], self._charset)
        if b"filename" in options:
            self._start_file_part(options[b"filename"])
            return
        self._start_field_part()

    def on_end(self) -> None:
        self._ended = True

    async def flush_file_buffers(self) -> None:
        if not self._pending_file_buffers:
            return
        if self._destination is None:
            raise ValueError("Workspace upload staging destination is missing")
        buffers = tuple(self._pending_file_buffers)
        self._pending_file_buffers.clear()
        await _complete_file_io(
            asyncio.to_thread(_write_file_buffers, self._destination, buffers)
        )

    async def finish(self) -> StagedWorkspaceUpload:
        if (
            not self._ended
            or not self._file_seen
            or not self._file_finished
            or self._staged_path is None
            or self._destination is None
        ):
            raise ValueError("Workspace upload multipart body is incomplete")
        await self.flush_file_buffers()
        await _complete_file_io(asyncio.to_thread(self._destination.flush))
        await _complete_file_io(asyncio.to_thread(self._destination.close))
        self._destination = None
        return StagedWorkspaceUpload(
            path=self._staged_path,
            parent_path=self._parent_path,
            filename=self._filename,
            content_type=self._content_type,
            size_bytes=self._size_bytes,
            checksum_sha256=self._digest.hexdigest(),
        )

    async def abort(self) -> None:
        self._pending_file_buffers.clear()
        try:
            if self._destination is not None:
                await _complete_file_io(asyncio.to_thread(self._destination.close))
        finally:
            self._destination = None
            if self._staged_path is not None:
                self._staged_path.unlink(missing_ok=True)

    def _start_file_part(self, raw_filename: bytes) -> None:
        if self._part_name != "file" or self._file_seen:
            raise ValueError("Workspace upload must contain exactly one file")
        self._file_seen = True
        self._part_kind = "file"
        self._filename = _decode_multipart_value(raw_filename, self._charset)
        self._staged_path = create_upload_staging_path()
        self._destination = self._staged_path.open("wb")

    def _start_field_part(self) -> None:
        if self._part_name != "parent_path" or self._parent_seen:
            raise ValueError("Workspace upload contains an unsupported field")
        self._parent_seen = True
        self._part_kind = "parent_path"

    @staticmethod
    def _extend_bounded_header(target: bytearray, content: bytes) -> None:
        if len(target) + len(content) > _MAX_MULTIPART_FIELD_BYTES:
            raise ValueError("Workspace upload header is too large")
        target.extend(content)


def require_bounded_upload_content_length(request: Request) -> None:
    """Reject a declared oversized request before parsing any multipart bytes."""
    raw_content_length = request.headers.get("content-length")
    if raw_content_length is None:
        return
    try:
        content_length = int(raw_content_length)
    except ValueError as exc:
        raise _invalid_upload("workspace_collaboration_upload_length_invalid") from exc
    if content_length < 0:
        raise _invalid_upload("workspace_collaboration_upload_length_invalid")
    if content_length > MAX_MULTIPART_REQUEST_BYTES:
        raise upload_too_large()


async def stage_workspace_upload_request(request: Request) -> StagedWorkspaceUpload:
    """Parse once and stream file bytes directly into bounded private storage."""
    media_type, options = parse_options_header(request.headers.get("content-type", ""))
    if media_type != b"multipart/form-data" or b"boundary" not in options:
        raise _invalid_upload("workspace_collaboration_upload_invalid")
    raw_charset = options.get(b"charset", b"utf-8")
    charset = _decode_multipart_value(raw_charset, "latin-1")
    stream = _WorkspaceMultipartStream(charset=charset)
    parser = MultipartParser(
        options[b"boundary"],
        cast("MultipartCallbacks", stream.callbacks),
    )
    request_bytes = 0
    try:
        async for chunk in request.stream():
            request_bytes += len(chunk)
            if request_bytes > MAX_MULTIPART_REQUEST_BYTES:
                raise upload_too_large()
            _ = parser.write(chunk)
            await stream.flush_file_buffers()
        parser.finalize()
        return await stream.finish()
    except HTTPException:
        await stream.abort()
        raise
    except ValueError as exc:
        await stream.abort()
        raise _invalid_upload("workspace_collaboration_upload_invalid") from exc
    except BaseException:
        await asyncio.shield(stream.abort())
        raise


def upload_too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail={
            "reason_code": "workspace_collaboration_upload_too_large",
            "message": _("Workspace Collaboration upload exceeds the maximum size"),
        },
    )


def _invalid_upload(reason_code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "reason_code": reason_code,
            "message": _("Invalid Workspace Collaboration upload"),
        },
    )
