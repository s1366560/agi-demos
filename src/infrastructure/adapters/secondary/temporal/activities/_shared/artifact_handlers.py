"""Artifact handling utilities for Temporal Activities.

This module provides common artifact storage and processing functionality
used across Agent activities.
"""

import base64
import logging
import re
import uuid
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Global cached storage adapter
_ARTIFACT_STORAGE_ADAPTER = None


async def get_artifact_storage_adapter():
    """Initialize and cache storage adapter for artifact uploads.

    Returns:
        S3StorageAdapter instance or None if initialization fails
    """
    global _ARTIFACT_STORAGE_ADAPTER
    if _ARTIFACT_STORAGE_ADAPTER is not None:
        return _ARTIFACT_STORAGE_ADAPTER

    try:
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import (
            S3StorageAdapter,
        )

        settings = get_settings()
        _ARTIFACT_STORAGE_ADAPTER = S3StorageAdapter(
            bucket_name=settings.s3_bucket_name,
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
        )
        return _ARTIFACT_STORAGE_ADAPTER
    except Exception as e:
        logger.warning(f"[SharedActivity] Failed to init artifact storage adapter: {e}")
        return None


def parse_data_uri(value: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse data URI and return (mime_type, base64_payload).

    Args:
        value: Data URI string (e.g., "data:image/png;base64,...")

    Returns:
        Tuple of (mime_type, base64_payload) or (None, None) if invalid
    """
    match = re.match(r"^data:([^;]+);base64,(.*)$", value)
    if not match:
        return None, None
    return match.group(1), match.group(2)


async def store_artifact(
    conversation_id: str,
    message_id: str,
    content_b64: str,
    mime_type: str,
    source: str,
) -> Optional[Dict[str, Any]]:
    """Store artifact content and return reference dict.

    Args:
        conversation_id: Conversation ID for path generation
        message_id: Message ID for path generation
        content_b64: Base64-encoded content
        mime_type: MIME type of the content
        source: Source event type for metadata

    Returns:
        Artifact reference dict with object_key, url, mime_type, size_bytes, source
        or None on failure
    """
    try:
        from src.configuration.config import get_settings

        settings = get_settings()
        storage = await get_artifact_storage_adapter()
        if storage is None:
            return None

        content_bytes = base64.b64decode(content_b64)
        ext = mime_type.split("/")[-1] if "/" in mime_type else "bin"
        object_key = f"agent-artifacts/{conversation_id}/{message_id}/{uuid.uuid4()}.{ext}"

        upload_result = await storage.upload_file(
            file_content=content_bytes,
            object_key=object_key,
            content_type=mime_type,
            metadata={"source": source},
        )

        url = await storage.generate_presigned_url(
            object_key=upload_result.object_key,
            expiration_seconds=settings.agent_artifact_url_ttl_seconds,
        )

        return {
            "object_key": upload_result.object_key,
            "url": url,
            "mime_type": upload_result.content_type,
            "size_bytes": upload_result.size_bytes,
            "source": source,
        }
    except Exception as e:
        logger.warning(f"[SharedActivity] Failed to store artifact: {e}")
        return None


async def extract_artifacts_from_event_data(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
) -> Tuple[Dict[str, Any], list]:
    """Extract large base64 artifacts from event data and store externally.

    This function identifies base64-encoded content in event data (images, etc.),
    uploads them to S3, and replaces the content with artifact references.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        event_type: Type of event (for metadata)
        event_data: Event data dict that may contain base64 content

    Returns:
        Tuple of (sanitized_event_data, list_of_artifacts)
    """
    import json

    artifacts: list = []
    sanitized = dict(event_data)

    # Direct base64 field
    if isinstance(sanitized.get("image_base64"), str):
        mime_type = sanitized.get("mime_type") or sanitized.get("format") or "image/png"
        artifact = await store_artifact(
            conversation_id,
            message_id,
            sanitized["image_base64"],
            mime_type,
            source=event_type,
        )
        if artifact:
            artifacts.append(artifact)
            sanitized.pop("image_base64", None)

    # Data URI in content
    if isinstance(sanitized.get("content"), str):
        mime_type, payload = parse_data_uri(sanitized["content"])
        if payload and mime_type:
            artifact = await store_artifact(
                conversation_id,
                message_id,
                payload,
                mime_type,
                source=event_type,
            )
            if artifact:
                artifacts.append(artifact)
                sanitized["content"] = "[artifact]"

    # Tool result payloads (stringified or dict)
    result = sanitized.get("result")
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except Exception:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("image_base64"), str):
            mime_type = parsed.get("mime_type") or parsed.get("format") or "image/png"
            artifact = await store_artifact(
                conversation_id,
                message_id,
                parsed["image_base64"],
                mime_type,
                source=event_type,
            )
            if artifact:
                artifacts.append(artifact)
                parsed.pop("image_base64", None)
                parsed["artifact_url"] = artifact["url"]
                parsed["artifact"] = {
                    "object_key": artifact["object_key"],
                    "mime_type": artifact["mime_type"],
                    "size_bytes": artifact["size_bytes"],
                }
                sanitized["result"] = json.dumps(parsed)
    elif isinstance(result, dict) and isinstance(result.get("image_base64"), str):
        mime_type = result.get("mime_type") or result.get("format") or "image/png"
        artifact = await store_artifact(
            conversation_id,
            message_id,
            result["image_base64"],
            mime_type,
            source=event_type,
        )
        if artifact:
            artifacts.append(artifact)
            result.pop("image_base64", None)
            result["artifact_url"] = artifact["url"]
            result["artifact"] = {
                "object_key": artifact["object_key"],
                "mime_type": artifact["mime_type"],
                "size_bytes": artifact["size_bytes"],
            }
            sanitized["result"] = result

    if artifacts:
        sanitized["artifacts"] = artifacts

    return sanitized, artifacts
