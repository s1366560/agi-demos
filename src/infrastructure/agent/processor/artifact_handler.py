"""Artifact handling for session processor.

Extracted from processor.py -- handles artifact extraction from tool
outputs, sanitization of binary data, S3 uploads, and canvas-displayable
content detection.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, cast

from src.domain.events.agent_events import (
    AgentArtifactCreatedEvent,
    AgentArtifactErrorEvent,
    AgentArtifactOpenEvent,
    AgentArtifactReadyEvent,
    AgentDomainEvent,
)
from src.infrastructure.adapters.secondary.sandbox.artifact_integration import (
    extract_artifacts_from_mcp_result,
)

if TYPE_CHECKING:
    from src.application.services.artifact_service import ArtifactService

logger = logging.getLogger(__name__)

# Module-level set to prevent background upload tasks from being GC'd.
_artifact_bg_tasks: set[asyncio.Task[Any]] = set()

# -----------------------------------------------------------------------
# Module-level helpers (previously in processor.py top-level scope)
# -----------------------------------------------------------------------


def strip_artifact_binary_data(result: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of an artifact result with binary/base64 data removed.

    The artifact binary content is handled separately by ``process_tool_artifacts``
    and must not leak into the ``AgentObserveEvent.result`` field.  Keeping it
    there causes the JSON payload persisted to Redis and PostgreSQL to be
    extremely large, which can fail the entire event-persistence transaction
    and lose all conversation history.
    """
    cleaned = {**result}
    if "artifact" in cleaned and isinstance(cleaned["artifact"], dict):
        artifact = {**cleaned["artifact"]}
        artifact.pop("data", None)
        cleaned["artifact"] = artifact
    # Also strip base64 from embedded MCP content items
    if "content" in cleaned and isinstance(cleaned["content"], list):
        stripped_content = []
        for item in cleaned["content"]:
            if isinstance(item, dict) and item.get("type") in ("image", "resource"):
                item = {**item}
                item.pop("data", None)
            stripped_content.append(item)
        cleaned["content"] = stripped_content
    return cleaned


# Canvas-displayable MIME type mapping
_CANVAS_MIME_MAP: dict[str, str] = {
    "text/html": "preview",
    "text/markdown": "markdown",
    "text/csv": "data",
    "application/json": "data",
    "application/xml": "data",
    "text/xml": "data",
}


def get_canvas_content_type(mime_type: str, filename: str) -> str | None:
    """Determine canvas content type for a given MIME type and filename."""
    if mime_type in _CANVAS_MIME_MAP:
        return _CANVAS_MIME_MAP[mime_type]
    if mime_type.startswith("text/"):
        return "code"
    # Check common code extensions
    code_exts = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".sh",
        ".bash",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".sql",
        ".css",
        ".scss",
        ".less",
        ".vue",
        ".svelte",
    }
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in code_exts:
        return "code"
    return None


_LANG_EXT_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".md": "markdown",
    ".xml": "xml",
    ".toml": "toml",
}


def get_language_from_filename(filename: str) -> str | None:
    """Get language identifier from filename extension."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _LANG_EXT_MAP.get(ext)


# -----------------------------------------------------------------------
# ArtifactHandler class
# -----------------------------------------------------------------------

_MAX_TOOL_OUTPUT_BYTES = 30_000

# Regex matching long base64-like sequences (256+ chars of [A-Za-z0-9+/=])
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/=]{256,}")


class ArtifactHandler:
    """Handles artifact extraction, sanitization, and upload from tool outputs.

    Parameters
    ----------
    artifact_service:
        The artifact service used for create_artifact calls.
    langfuse_context:
        Observability context dict providing project_id, tenant_id, etc.
    """

    def __init__(
        self,
        artifact_service: ArtifactService | None,
        langfuse_context: dict[str, Any] | None,
    ) -> None:
        self._artifact_service = artifact_service
        self._langfuse_context = langfuse_context

    def set_langfuse_context(self, ctx: dict[str, Any] | None) -> None:
        """Update langfuse context (set per-process call)."""
        self._langfuse_context = ctx

    # ------------------------------------------------------------------
    # Sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def sanitize_tool_output(output: str) -> str:
        """Sanitize tool output to prevent binary/base64 data from entering LLM context.

        Applies two defensive filters:
        1. Replace long base64-like sequences with a placeholder.
        2. Truncate output exceeding _MAX_TOOL_OUTPUT_BYTES.
        """
        if not output:
            return output

        # Strip embedded base64 blobs
        sanitized = _BASE64_PATTERN.sub("[binary data omitted]", output)

        # Hard size cap
        encoded = sanitized.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_TOOL_OUTPUT_BYTES:
            sanitized = encoded[:_MAX_TOOL_OUTPUT_BYTES].decode("utf-8", errors="ignore")
            sanitized += "\n... [output truncated]"

        return sanitized

    # ------------------------------------------------------------------
    # Artifact processing
    # ------------------------------------------------------------------

    async def process_tool_artifacts(  # noqa: C901, PLR0911, PLR0912, PLR0915
        self,
        tool_name: str,
        result: Any,  # noqa: ANN401
        tool_execution_id: str | None = None,
    ) -> AsyncIterator[AgentDomainEvent]:
        """Process tool result and extract any artifacts (images, files, etc.).

        This method:
        1. Extracts image/resource content from MCP-style results
        2. Uploads artifacts to storage via ArtifactService
        3. Emits artifact_created events for frontend display

        Args:
            tool_name: Name of the tool that produced the result
            result: Tool execution result (may contain images/resources)
            tool_execution_id: ID of the tool execution

        Yields:
            AgentArtifactCreatedEvent for each artifact created
        """
        logger.warning(
            f"[ArtifactUpload] Processing tool={tool_name}, "
            f"has_service={self._artifact_service is not None}, "
            f"result_type={type(result).__name__}"
        )

        if not self._artifact_service:
            logger.warning("[ArtifactUpload] No artifact_service configured, skipping")
            return

        # Get context from langfuse context
        ctx = self._langfuse_context or {}
        project_id = ctx.get("project_id")
        tenant_id = ctx.get("tenant_id")
        conversation_id = ctx.get("conversation_id")
        message_id = ctx.get("message_id")

        if not project_id or not tenant_id:
            logger.warning(
                f"[ArtifactUpload] Missing context: project_id={project_id}, tenant_id={tenant_id}"
            )
            return

        # Check if result contains MCP-style content
        if not isinstance(result, dict):
            return

        has_artifact = result.get("artifact") is not None
        if has_artifact:
            has_data = result["artifact"].get("data") is not None
            logger.warning(
                f"[ArtifactUpload] tool={tool_name}, has_data={has_data}, "
                f"encoding={result['artifact'].get('encoding')}"
            )

        # Check for export_artifact tool result which has special 'artifact' field
        if result.get("artifact"):
            artifact_info = result["artifact"]
            try:
                import base64

                # Get file content
                encoding = artifact_info.get("encoding", "utf-8")
                if encoding == "base64":
                    # Binary file - get data from artifact info or image content
                    data = artifact_info.get("data")
                    if not data:
                        # Check for image content
                        for item in result.get("content", []):
                            if item.get("type") == "image":
                                data = item.get("data")
                                break
                    if data:
                        file_content = base64.b64decode(data)
                        logger.warning(
                            f"[ArtifactUpload] Decoded {len(file_content)} bytes from base64"
                        )
                    else:
                        logger.warning("[ArtifactUpload] base64 encoding but no data found")
                        return
                else:
                    # Text file - get from content
                    content = result.get("content", [])
                    if content:
                        first_item = content[0] if content else {}
                        text = (
                            first_item.get("text", "")
                            if isinstance(first_item, dict)
                            else str(first_item)
                        )
                        if not text:
                            logger.warning("export_artifact returned empty text content")
                            return
                        file_content = text.encode("utf-8")
                    else:
                        logger.warning("export_artifact returned no content")
                        return

                # Detect MIME type for the artifact_created event
                from src.application.services.artifact_service import (
                    detect_mime_type,
                    get_category_from_mime,
                )

                filename = artifact_info.get("filename", "exported_file")
                mime_type = detect_mime_type(filename)
                category = get_category_from_mime(mime_type)
                artifact_id = str(uuid.uuid4())

                # Yield artifact_created event IMMEDIATELY so the frontend
                # knows about the artifact even if the upload is slow.
                yield AgentArtifactCreatedEvent(
                    artifact_id=artifact_id,
                    filename=filename,
                    mime_type=mime_type,
                    category=category.value,
                    size_bytes=len(file_content),
                    url=None,
                    preview_url=None,
                    tool_execution_id=tool_execution_id,
                    source_tool=tool_name,
                    source_path=artifact_info.get("path"),
                )

                # Emit artifact_open for canvas-displayable content
                canvas_type = get_canvas_content_type(mime_type, filename)
                if canvas_type and len(file_content) < 500_000:
                    try:
                        text_content = file_content.decode("utf-8")
                        yield AgentArtifactOpenEvent(
                            artifact_id=artifact_id,
                            title=filename,
                            content=text_content,
                            content_type=canvas_type,
                            language=get_language_from_filename(filename),
                        )
                    except (UnicodeDecodeError, ValueError):
                        pass  # Binary content, skip canvas open

                # Upload artifact in a background thread to avoid event loop
                # contention. aioboto3 upload hangs when the event loop is busy
                # with LLM streaming, so we use synchronous boto3 in a thread.
                logger.warning(
                    f"[ArtifactUpload] Scheduling threaded upload: filename={filename}, "
                    f"size={len(file_content)}, project_id={project_id}"
                )

                _schedule_threaded_upload(
                    file_content=file_content,
                    filename=filename,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    tool_execution_id=tool_execution_id or "",
                    conversation_id=conversation_id or "",
                    message_id=message_id or "",
                    tool_name=tool_name,
                    artifact_id=artifact_id,
                    mime_type=mime_type,
                    category_value=category.value,
                )
                return

            except Exception as e:
                import traceback

                logger.error(
                    f"Failed to process export_artifact result: {e}\n"
                    f"Artifact info: {artifact_info}\n"
                    f"Traceback: {traceback.format_exc()}"
                )

        # Check for MCP content array with images/resources
        content = result.get("content", [])
        if not content:
            return

        # Check if there are any image or resource types
        has_rich_content = any(
            item.get("type") in ("image", "resource") for item in content if isinstance(item, dict)
        )
        if not has_rich_content:
            return

        try:
            # Extract artifacts from MCP result
            artifact_data_list = extract_artifacts_from_mcp_result(result, tool_name)

            for artifact_data in artifact_data_list:
                try:
                    # Upload artifact
                    artifact = await self._artifact_service.create_artifact(
                        file_content=artifact_data["content"],
                        filename=artifact_data["filename"],
                        project_id=project_id,
                        tenant_id=tenant_id,
                        sandbox_id=None,  # TODO: Get sandbox_id if available
                        tool_execution_id=tool_execution_id,
                        conversation_id=conversation_id,
                        source_tool=tool_name,
                        source_path=artifact_data.get("source_path"),
                        metadata={
                            "extracted_from": "mcp_result",
                            "original_mime": artifact_data["mime_type"],
                        },
                    )

                    logger.info(
                        f"Created artifact {artifact.id} from tool {tool_name}: "
                        f"{artifact.filename} ({artifact.category.value}, "
                        f"{artifact.size_bytes} bytes)"
                    )

                    # Emit artifact created event
                    yield AgentArtifactCreatedEvent(
                        artifact_id=artifact.id,
                        filename=artifact.filename,
                        mime_type=artifact.mime_type,
                        category=artifact.category.value,
                        size_bytes=artifact.size_bytes,
                        url=artifact.url,
                        preview_url=artifact.preview_url,
                        tool_execution_id=tool_execution_id,
                        source_tool=tool_name,
                    )
                    # Emit artifact_open for canvas-displayable content
                    canvas_type = get_canvas_content_type(artifact.mime_type, artifact.filename)
                    if canvas_type and artifact.size_bytes < 500_000:
                        try:
                            text_content = artifact_data["content"].decode("utf-8")
                            yield AgentArtifactOpenEvent(
                                artifact_id=artifact.id,
                                title=artifact.filename,
                                content=text_content,
                                content_type=canvas_type,
                                language=get_language_from_filename(artifact.filename),
                            )
                        except (UnicodeDecodeError, ValueError):
                            pass  # Binary content, skip canvas open

                except Exception as e:
                    logger.error(f"Failed to create artifact from {tool_name}: {e}")

        except Exception as e:
            logger.error(f"Error processing artifacts from tool {tool_name}: {e}")


# -----------------------------------------------------------------------
# Background upload helpers (module-level to avoid closure issues)
# -----------------------------------------------------------------------


def _sync_upload(  # noqa: PLR0913
    content: bytes,
    fname: str,
    pid: str,
    tid: str,
    texec_id: str,
    tname: str,
    art_id: str,
    bucket: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    region: str,
    mime: str,
    no_proxy: bool = False,
) -> dict[str, Any]:
    """Synchronous S3 upload in a thread pool."""
    from datetime import date
    from urllib.parse import quote

    import boto3  # pyright: ignore[reportMissingTypeStubs]
    from botocore.config import Config as BotoConfig  # pyright: ignore[reportMissingTypeStubs]

    config_kwargs: dict[str, Any] = {
        "connect_timeout": 10,
        "read_timeout": 30,
        "retries": {"max_attempts": 5, "mode": "standard"},
    }
    if no_proxy:
        config_kwargs["proxies"] = {"http": None, "https": None}

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=BotoConfig(**config_kwargs),
    )

    date_part = date.today().strftime("%Y/%m/%d")
    unique_id = art_id[:8]
    safe_fname = fname.replace("/", "_")
    object_key = (
        f"artifacts/{tid}/{pid}/{date_part}/{texec_id or 'direct'}/{unique_id}_{safe_fname}"
    )

    metadata = {
        "artifact_id": art_id,
        "project_id": pid,
        "tenant_id": tid,
        "filename": quote(fname, safe=""),
        "source_tool": tname or "",
    }

    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=content,
        ContentType=mime,
        Metadata=metadata,
    )

    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": object_key},
        ExpiresIn=7 * 24 * 3600,
    )

    return {
        "url": url,
        "object_key": object_key,
        "size_bytes": len(content),
    }


async def _threaded_upload(
    content: bytes,
    fname: str,
    pid: str,
    tid: str,
    texec_id: str,
    conv_id: str,
    msg_id: str,
    tname: str,
    art_id: str,
    mime: str,
    cat: str,
) -> None:
    """Run sync upload in thread, then publish result to Redis and DB."""
    import time as _time

    from src.configuration.config import get_settings
    from src.infrastructure.agent.actor.execution import (
        _persist_events,  # pyright: ignore[reportPrivateUsage]
        _publish_event_to_stream,  # pyright: ignore[reportPrivateUsage]
    )

    settings = get_settings()

    try:
        result = await asyncio.to_thread(
            _sync_upload,
            content=content,
            fname=fname,
            pid=pid,
            tid=tid,
            texec_id=texec_id,
            tname=tname,
            art_id=art_id,
            bucket=settings.s3_bucket_name,
            endpoint=settings.s3_endpoint_url or "",
            access_key=settings.aws_access_key_id or "",
            secret_key=settings.aws_secret_access_key or "",
            region=settings.aws_region,
            mime=mime,
            no_proxy=settings.s3_no_proxy,
        )
        logger.warning(
            f"[ArtifactUpload] Threaded upload SUCCESS: filename={fname}, url={result['url'][:80]}"
        )

        ready_event = AgentArtifactReadyEvent(
            artifact_id=art_id,
            filename=fname,
            mime_type=mime,
            category=cat,
            size_bytes=result["size_bytes"],
            url=result["url"],
            tool_execution_id=texec_id,
            source_tool=tname,
        )
        ready_event_dict = ready_event.to_event_dict()
        ready_time_us = int(_time.time() * 1_000_000)
        await _publish_event_to_stream(
            conversation_id=conv_id,
            event=cast(dict[str, Any], ready_event_dict),
            message_id=msg_id,
            event_time_us=ready_time_us,
            event_counter=0,
        )
        # Persist to DB so history loading can merge URL into artifact_created
        await _persist_events(
            conversation_id=conv_id,
            message_id=msg_id,
            events=[
                {
                    **ready_event_dict,
                    "event_time_us": ready_time_us,
                    "event_counter": 0,
                }
            ],
        )
    except Exception as upload_err:
        logger.error(f"[ArtifactUpload] Threaded upload failed: {fname}: {upload_err}")
        error_event = AgentArtifactErrorEvent(
            artifact_id=art_id,
            filename=fname,
            tool_execution_id=texec_id,
            error=f"Upload failed: {upload_err}",
        )
        error_event_dict = error_event.to_event_dict()
        error_time_us = int(_time.time() * 1_000_000)
        try:
            await _publish_event_to_stream(
                conversation_id=conv_id,
                event=cast(dict[str, Any], error_event_dict),
                message_id=msg_id,
                event_time_us=error_time_us,
                event_counter=0,
            )
        except Exception:
            logger.error("[ArtifactUpload] Failed to publish error event")
        # Persist to DB so history loading shows error instead of uploading
        try:
            await _persist_events(
                conversation_id=conv_id,
                message_id=msg_id,
                events=[
                    {
                        **error_event_dict,
                        "event_time_us": error_time_us,
                        "event_counter": 0,
                    }
                ],
            )
        except Exception:
            logger.error("[ArtifactUpload] Failed to persist error event")


def _schedule_threaded_upload(
    *,
    file_content: bytes,
    filename: str,
    project_id: str,
    tenant_id: str,
    tool_execution_id: str,
    conversation_id: str,
    message_id: str,
    tool_name: str,
    artifact_id: str,
    mime_type: str,
    category_value: str,
) -> None:
    """Schedule a background upload task, preventing GC."""
    _upload_task = asyncio.create_task(
        _threaded_upload(
            content=file_content,
            fname=filename,
            pid=project_id,
            tid=tenant_id,
            texec_id=tool_execution_id,
            conv_id=conversation_id,
            msg_id=message_id,
            tname=tool_name,
            art_id=artifact_id,
            mime=mime_type,
            cat=category_value,
        )
    )
    _artifact_bg_tasks.add(_upload_task)
    _upload_task.add_done_callback(_artifact_bg_tasks.discard)
