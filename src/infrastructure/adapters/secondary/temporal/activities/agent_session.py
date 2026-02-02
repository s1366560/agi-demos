"""
Agent Session Activities for Temporal.

This module provides activity implementations for the AgentSessionWorkflow,
enabling long-lived Agent sessions with cached components.

Activities:
- initialize_agent_session_activity: Initialize session and warm up caches
- execute_chat_activity: Execute a chat request using cached components
- cleanup_agent_session_activity: Clean up session resources
"""

import base64
import json
import logging
import re
import time as time_module
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from temporalio import activity

logger = logging.getLogger(__name__)

_ARTIFACT_STORAGE_ADAPTER = None
_ARTIFACT_SERVICE = None


async def _get_artifact_storage_adapter():
    """Initialize and cache storage adapter for artifact uploads."""
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
        logger.warning(f"[AgentSession] Failed to init artifact storage adapter: {e}")
        return None


async def _get_artifact_service():
    """Initialize and cache ArtifactService for rich output handling."""
    global _ARTIFACT_SERVICE
    if _ARTIFACT_SERVICE is not None:
        return _ARTIFACT_SERVICE

    try:
        from src.application.services.artifact_service import ArtifactService
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import (
            S3StorageAdapter,
        )

        settings = get_settings()
        # S3StorageAdapter implements StorageServicePort directly
        storage_service = S3StorageAdapter(
            bucket_name=settings.s3_bucket_name,
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
        )

        _ARTIFACT_SERVICE = ArtifactService(
            storage_service=storage_service,
            event_publisher=None,  # Event publishing handled via SSE streaming
            bucket_prefix="artifacts",
            url_expiration_seconds=7 * 24 * 3600,  # 7 days
        )
        logger.info("[AgentSession] ArtifactService initialized successfully")
        return _ARTIFACT_SERVICE
    except Exception as e:
        logger.warning(f"[AgentSession] Failed to init ArtifactService: {e}")
        import traceback

        logger.warning(f"[AgentSession] Traceback: {traceback.format_exc()}")
        return None


def _parse_data_uri(value: str) -> tuple[str | None, str | None]:
    """Parse data URI and return (mime_type, base64_payload)."""
    match = re.match(r"^data:([^;]+);base64,(.*)$", value)
    if not match:
        return None, None
    return match.group(1), match.group(2)


async def _store_artifact(
    conversation_id: str,
    message_id: str,
    content_b64: str,
    mime_type: str,
    source: str,
) -> dict[str, Any] | None:
    """Store artifact content and return reference dict."""
    try:
        from src.configuration.config import get_settings

        settings = get_settings()
        storage = await _get_artifact_storage_adapter()
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
        logger.warning(f"[AgentSession] Failed to store artifact: {e}")
        return None


async def _extract_artifacts_from_event_data(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
) -> tuple[Dict[str, Any], list[Dict[str, Any]]]:
    """Extract large base64 artifacts from event data and store externally."""
    artifacts: list[Dict[str, Any]] = []
    sanitized = dict(event_data)

    # Direct base64 field
    if isinstance(sanitized.get("image_base64"), str):
        mime_type = sanitized.get("mime_type") or sanitized.get("format") or "image/png"
        artifact = await _store_artifact(
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
        mime_type, payload = _parse_data_uri(sanitized["content"])
        if payload and mime_type:
            artifact = await _store_artifact(
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
            artifact = await _store_artifact(
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
        artifact = await _store_artifact(
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


@activity.defn
async def initialize_agent_session_activity(
    config: Any,  # AgentSessionConfig dataclass
) -> Dict[str, Any]:
    """
    Initialize an Agent Session and warm up caches.

    This activity:
    1. Loads tools (including MCP tools)
    2. Initializes SubAgentRouter
    3. Creates SystemPromptManager singleton
    4. Pre-converts tool definitions
    5. Stores session data for reuse

    Args:
        config: AgentSessionConfig containing tenant_id, project_id, agent_mode, etc.

    Returns:
        Initialization result with status and session data
    """
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        get_agent_graph_service,
        get_or_create_agent_session,
        get_or_create_llm_client,
        get_or_create_provider_config,
        get_or_create_skills,
        get_or_create_tools,
        get_redis_client,
    )
    from src.infrastructure.agent.core.processor import ProcessorConfig

    start_time = time_module.time()

    try:
        # Extract config values (handle both dataclass and dict)
        if hasattr(config, "tenant_id"):
            tenant_id = config.tenant_id
            project_id = config.project_id
            agent_mode = config.agent_mode
            mcp_tools_ttl = getattr(config, "mcp_tools_ttl_seconds", 300)
            temperature = getattr(config, "temperature", 0.7)
            max_tokens = getattr(config, "max_tokens", 4096)
            max_steps = getattr(config, "max_steps", 20)
        else:
            tenant_id = config.get("tenant_id", "")
            project_id = config.get("project_id", "")
            agent_mode = config.get("agent_mode", "default")
            mcp_tools_ttl = config.get("mcp_tools_ttl_seconds", 300)
            temperature = config.get("temperature", 0.7)
            max_tokens = config.get("max_tokens", 4096)
            max_steps = config.get("max_steps", 20)

        logger.info(
            f"[AgentSession] Initializing session: tenant={tenant_id}, "
            f"project={project_id}, mode={agent_mode}"
        )

        # Get shared resources
        graph_service = get_agent_graph_service()
        redis_client = await get_redis_client()

        # Get LLM provider configuration (cached)
        provider_config = await get_or_create_provider_config()

        # Pre-warm LLM client cache
        llm_client = await get_or_create_llm_client(provider_config)

        # Load and cache tools
        tools = await get_or_create_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            graph_service=graph_service,
            redis_client=redis_client,
            llm=llm_client,
            agent_mode=agent_mode,
            mcp_tools_ttl_seconds=mcp_tools_ttl,
            force_mcp_refresh=(mcp_tools_ttl == 0),
        )

        # Load and cache skills
        skills = await get_or_create_skills(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        # Create processor config for session
        processor_config = ProcessorConfig(
            model="",  # Set at chat time
            api_key="",
            base_url=None,
            temperature=temperature,
            max_tokens=max_tokens,
            max_steps=max_steps,
        )

        # Get or create agent session (warms up all caches)
        session_ctx = await get_or_create_agent_session(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
            tools=tools,
            skills=skills,
            subagents=[],
            processor_config=processor_config,
        )

        init_time_ms = (time_module.time() - start_time) * 1000

        logger.info(
            f"[AgentSession] Session initialized in {init_time_ms:.1f}ms: "
            f"tenant={tenant_id}, project={project_id}, "
            f"tools={len(tools)}, use_count={session_ctx.use_count}"
        )

        # Return session data for Workflow to store
        return {
            "status": "initialized",
            "tool_count": len(tools),
            "skill_count": len(skills),
            "session_data": {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "agent_mode": agent_mode,
                "provider_type": (
                    provider_config.provider_type.value
                    if hasattr(provider_config.provider_type, "value")
                    else str(provider_config.provider_type)
                ),
                "initialized_at": datetime.now(timezone.utc).isoformat(),
                "init_time_ms": init_time_ms,
            },
        }

    except Exception as e:
        logger.error(f"[AgentSession] Initialization failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


async def _prepare_attachments(
    attachment_ids: list[str],
    project_id: str,
    tenant_id: str,
) -> Dict[str, Any]:
    """
    Prepare attachments for LLM multimodal input and sync to sandbox.

    Args:
        attachment_ids: List of attachment IDs to process
        project_id: Project ID for sandbox lookup
        tenant_id: Tenant ID

    Returns:
        Dict containing:
        - llm_content: List of content parts for LLM multimodal messages
        - attachment_metadata: List of attachment metadata for Agent context injection
    """
    empty_result = {"llm_content": [], "attachment_metadata": []}

    if not attachment_ids:
        return empty_result

    try:
        from src.application.services.attachment_service import AttachmentService
        from src.configuration.config import get_settings
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_attachment_repository import (
            SqlAlchemyAttachmentRepository,
        )
        from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import (
            S3StorageAdapter,
        )

        settings = get_settings()

        # Initialize services
        storage_service = S3StorageAdapter(
            bucket_name=settings.s3_bucket_name,
            region=settings.aws_region,
            access_key_id=settings.aws_access_key_id,
            secret_access_key=settings.aws_secret_access_key,
            endpoint_url=settings.s3_endpoint_url,
        )

        async with async_session_factory() as db:
            attachment_repo = SqlAlchemyAttachmentRepository(db)
            attachment_service = AttachmentService(
                storage_service=storage_service,
                attachment_repository=attachment_repo,
            )

            # Get attachments
            attachments = await attachment_service.get_by_ids(attachment_ids)
            if not attachments:
                logger.warning(f"[AgentSession] No attachments found for IDs: {attachment_ids}")
                return empty_result

            logger.info(
                f"[AgentSession] Processing {len(attachments)} attachments for project={project_id}"
            )

            # Prepare for LLM and sandbox
            llm_content = []
            sandbox_files = []
            attachment_metadata = []  # Metadata for Agent context awareness

            for attachment in attachments:
                # Log attachment details for debugging
                logger.info(
                    f"[AgentSession] Processing attachment: id={attachment.id}, "
                    f"filename={attachment.filename}, purpose={attachment.purpose}, "
                    f"status={attachment.status}, mime_type={attachment.mime_type}"
                )

                # Determine sandbox path for this attachment
                # This MUST be set before prepare_for_llm to ensure consistent path reporting
                sandbox_path = f"/workspace/{attachment.filename}"

                # Set sandbox_path on attachment object for prepare_for_llm to use
                # (This is a temporary in-memory update, not persisted yet)
                attachment.sandbox_path = sandbox_path

                # Collect metadata for ALL attachments (for Agent context)
                meta = {
                    "id": attachment.id,
                    "filename": attachment.filename,
                    "mime_type": attachment.mime_type,
                    "size_bytes": attachment.size_bytes,
                    "sandbox_path": sandbox_path,
                    "purpose": attachment.purpose.value if attachment.purpose else "llm",
                }
                attachment_metadata.append(meta)

                # Prepare for LLM if needed
                needs_llm = attachment.needs_llm_processing()
                logger.debug(
                    f"[AgentSession] Attachment {attachment.id} needs_llm_processing={needs_llm}"
                )
                if needs_llm:
                    try:
                        llm_part = await attachment_service.prepare_for_llm(attachment)
                        llm_content.append(llm_part)
                        logger.info(
                            f"[AgentSession] Prepared attachment {attachment.id} for LLM: "
                            f"type={llm_part.get('type')}, filename={attachment.filename}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[AgentSession] Failed to prepare attachment {attachment.id} for LLM: {e}"
                        )

                # Prepare for sandbox if needed
                needs_sandbox = attachment.needs_sandbox_import()
                can_use = attachment.can_be_used()
                logger.info(
                    f"[AgentSession] Attachment {attachment.id}: "
                    f"needs_sandbox_import={needs_sandbox}, can_be_used={can_use}"
                )

                if needs_sandbox:
                    if not can_use:
                        logger.warning(
                            f"[AgentSession] Attachment {attachment.id} needs sandbox but cannot be used: "
                            f"status={attachment.status}"
                        )
                    try:
                        sandbox_data = await attachment_service.prepare_for_sandbox(attachment)
                        sandbox_data["attachment_id"] = attachment.id
                        sandbox_files.append(sandbox_data)

                        # 验证 base64 内容完整性
                        content_base64 = sandbox_data.get("content_base64", "")
                        import hashlib

                        content_hash = hashlib.md5(content_base64.encode()).hexdigest()[:8]
                        estimated_size = len(content_base64) * 3 // 4

                        logger.info(
                            f"[AgentSession] Prepared attachment {attachment.id} for sandbox: "
                            f"filename={attachment.filename}, db_size={attachment.size_bytes}, "
                            f"base64_len={len(content_base64)}, estimated_decoded={estimated_size}, "
                            f"content_hash={content_hash}"
                        )
                    except Exception as e:
                        logger.warning(
                            f"[AgentSession] Failed to prepare attachment {attachment.id} for sandbox: {e}",
                            exc_info=True,
                        )

            # Sync files to sandbox if any need it
            logger.info(
                f"[AgentSession] Prepared {len(sandbox_files)} files for sandbox sync, "
                f"{len(llm_content)} for LLM"
            )
            if sandbox_files:
                await _sync_files_to_sandbox(
                    sandbox_files=sandbox_files,
                    project_id=project_id,
                    tenant_id=tenant_id,
                    attachment_service=attachment_service,
                )
            else:
                logger.warning(
                    "[AgentSession] No files to sync to sandbox! "
                    "Check attachment purpose and status."
                )

            return {
                "llm_content": llm_content,
                "attachment_metadata": attachment_metadata,
            }

    except Exception as e:
        logger.error(f"[AgentSession] Failed to prepare attachments: {e}", exc_info=True)
        return empty_result


async def _sync_files_to_sandbox(
    sandbox_files: list[Dict[str, Any]],
    project_id: str,
    tenant_id: str,
    attachment_service,
) -> None:
    """
    Sync files to the project's sandbox /workspace directory.

    CRITICAL: This function must use the SAME sandbox that API Server created.
    It queries the database first (single source of truth), then syncs with Docker.

    Args:
        sandbox_files: List of file data dicts with content_base64, filename, etc.
        project_id: Project ID
        tenant_id: Tenant ID
        attachment_service: AttachmentService instance
    """
    logger.info(
        f"[AgentSession] _sync_files_to_sandbox called with {len(sandbox_files)} files "
        f"for project={project_id}"
    )
    try:
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            get_mcp_sandbox_adapter,
        )

        # Get MCP sandbox adapter from worker state
        sandbox_adapter = get_mcp_sandbox_adapter()
        if not sandbox_adapter:
            logger.warning("[AgentSession] MCP Sandbox adapter not available, skipping file sync")
            return

        # STEP 1: Query DATABASE first (single source of truth)
        sandbox_id = None
        from src.infrastructure.adapters.secondary.persistence.database import (
            async_session_factory,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
            SqlAlchemyProjectSandboxRepository,
        )

        async with async_session_factory() as db:
            sandbox_repo = SqlAlchemyProjectSandboxRepository(db)
            assoc = await sandbox_repo.find_by_project(project_id)
            if assoc and assoc.sandbox_id:
                sandbox_id = assoc.sandbox_id
                logger.info(f"[AgentSession] Found sandbox_id from DB: {sandbox_id}")
            else:
                logger.warning(
                    f"[AgentSession] No sandbox association for project={project_id}. "
                    f"Files cannot be synced until sandbox is created."
                )
                return

        # STEP 2: Sync adapter cache with Docker to ensure we have the container
        # This handles the case where API Server created the container but
        # Agent Worker hasn't seen it yet
        if sandbox_id not in sandbox_adapter._active_sandboxes:
            logger.info(
                f"[AgentSession] Sandbox {sandbox_id} not in adapter cache, syncing from Docker..."
            )
            await sandbox_adapter.sync_from_docker()

        # STEP 3: Verify container actually exists
        if sandbox_id not in sandbox_adapter._active_sandboxes:
            # Try direct Docker check
            container_exists = await sandbox_adapter.container_exists(sandbox_id)
            if not container_exists:
                logger.error(
                    f"[AgentSession] Sandbox {sandbox_id} in DB but container doesn't exist! "
                    f"This may indicate the container was externally deleted. "
                    f"Files cannot be synced until sandbox is recreated."
                )
                return
            else:
                # Container exists but not in adapter cache - sync again
                await sandbox_adapter.sync_from_docker()

        # STEP 4: Final verification before proceeding
        if sandbox_id not in sandbox_adapter._active_sandboxes:
            logger.error(
                f"[AgentSession] Failed to sync sandbox {sandbox_id} to adapter cache. "
                f"Skipping file sync."
            )
            return

        logger.info(
            f"[AgentSession] Sandbox {sandbox_id} verified, proceeding to sync "
            f"{len(sandbox_files)} files..."
        )

        # Import files to sandbox using import_file tool (supports binary files)
        # NOTE: We use import_file instead of write because:
        # 1. write tool only supports text files (UTF-8 encoding)
        # 2. import_file accepts base64 and writes bytes (preserves binary files like PDF, images)
        for file_data in sandbox_files:
            filename = file_data.get("filename", "unnamed")
            content_base64 = file_data.get("content_base64", "")
            attachment_id = file_data.get("attachment_id", "")
            size_bytes = file_data.get("size_bytes", len(content_base64) * 3 // 4)  # Estimate

            if not content_base64:
                logger.warning(f"[AgentSession] Empty content for file {filename}, skipping")
                continue

            try:
                # Use import_file tool which properly handles binary files
                # Files are imported to /workspace/ (not /workspace/input/ for consistency)
                sandbox_path = f"/workspace/{filename}"

                logger.info(
                    f"[AgentSession] Importing file to sandbox: {filename} "
                    f"(~{size_bytes} bytes, base64_len={len(content_base64)})"
                )

                result = await sandbox_adapter.call_tool(
                    sandbox_id=sandbox_id,
                    tool_name="import_file",
                    arguments={
                        "filename": filename,
                        "content_base64": content_base64,
                        "destination": "/workspace",  # Import directly to /workspace
                        "overwrite": True,
                    },
                    timeout=120.0,  # Longer timeout for large files
                )

                # import_file returns {"success": bool, "path": str, ...}
                result_content = result.get("content", [])
                is_error = result.get("is_error", False)

                # Log raw result for debugging
                logger.debug(
                    f"[AgentSession] import_file result for {filename}: "
                    f"is_error={is_error}, content={result_content[:500] if result_content else 'empty'}..."
                )

                # Check for "Unknown tool" error (sandbox may need update)
                for item in result_content or []:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        if "Unknown tool" in text:
                            logger.error(
                                f"[AgentSession] CRITICAL: import_file tool not available in sandbox! "
                                f"The sandbox-mcp-server Docker image may need to be rebuilt. "
                                f"Error: {text}"
                            )

                # Check for success in the response
                success = False
                if not is_error and result_content:
                    for item in result_content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text", "")
                            # Parse JSON response from import_file
                            try:
                                import json

                                response = json.loads(text)
                                success = response.get("success", False)
                                if success:
                                    sandbox_path = response.get("path", sandbox_path)
                                    actual_size = response.get("size_bytes", 0)
                                    sandbox_md5 = response.get("md5", "unknown")
                                    source_md5 = file_data.get("source_md5", "unknown")

                                    # Verify end-to-end integrity
                                    if source_md5 != "unknown" and sandbox_md5 != "unknown":
                                        if source_md5 == sandbox_md5:
                                            logger.info(
                                                f"[AgentSession] ✅ File integrity verified: {filename} "
                                                f"(source_md5={source_md5} == sandbox_md5={sandbox_md5})"
                                            )
                                        else:
                                            logger.error(
                                                f"[AgentSession] ❌ FILE INTEGRITY MISMATCH: {filename} "
                                                f"source_md5={source_md5} != sandbox_md5={sandbox_md5}"
                                            )

                                    logger.info(
                                        f"[AgentSession] Successfully imported {filename}: "
                                        f"path={sandbox_path}, size={actual_size} bytes, md5={sandbox_md5}"
                                    )
                                else:
                                    error_msg = response.get("error", "Unknown error")
                                    logger.warning(
                                        f"[AgentSession] import_file returned success=False for {filename}: {error_msg}"
                                    )
                            except json.JSONDecodeError:
                                # Response is plain text, check for success message
                                success = "successfully" in text.lower()

                if not success or is_error:
                    logger.warning(
                        f"[AgentSession] Failed to import {filename} to sandbox: "
                        f"is_error={is_error}, result={result_content}"
                    )
                    continue

                # Mark attachment as imported
                if attachment_id:
                    await attachment_service.mark_sandbox_imported(
                        attachment_id=attachment_id,
                        sandbox_path=sandbox_path,
                    )

            except Exception as e:
                logger.error(
                    f"[AgentSession] Exception importing file {filename} to sandbox: {e}",
                    exc_info=True,
                )

    except Exception as e:
        logger.error(f"[AgentSession] Failed to sync files to sandbox: {e}", exc_info=True)


@activity.defn
async def execute_chat_activity(
    input: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a chat request using cached session components.

    This activity uses the Agent Session Pool to get pre-initialized
    components, significantly reducing per-request latency.

    Args:
        input: Chat execution input containing:
            - conversation_id: Conversation ID
            - message_id: Message ID
            - user_message: User's message
            - user_id: User ID
            - conversation_context: Conversation history
            - session_config: Session configuration
            - session_data: Cached session data from Workflow

    Returns:
        Chat result with content and metadata
    """
    import os

    from src.infrastructure.adapters.secondary.event.redis_event_bus import RedisEventBusAdapter
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        get_agent_graph_service,
        get_or_create_agent_session,
        get_or_create_llm_client,
        get_or_create_provider_config,
        get_or_create_skills,
        get_or_create_tools,
        get_redis_client,
    )
    from src.infrastructure.agent.core.processor import ProcessorConfig
    from src.infrastructure.agent.core.react_agent import ReActAgent
    from src.infrastructure.security.encryption_service import get_encryption_service

    start_time = time_module.time()

    try:
        # Extract input parameters
        conversation_id = input.get("conversation_id", "")
        message_id = input.get("message_id", "")
        user_message = input.get("user_message", "")
        user_id = input.get("user_id", "")
        conversation_context = input.get("conversation_context", [])
        attachment_ids = input.get("attachment_ids", [])
        session_config = input.get("session_config", {})
        # session_data from Workflow (reserved for future use)
        _ = input.get("session_data", {})

        tenant_id = session_config.get("tenant_id", "")
        project_id = session_config.get("project_id", "")
        agent_mode = session_config.get("agent_mode", "default")

        # Process attachments if any
        attachment_result = {"llm_content": [], "attachment_metadata": []}
        if attachment_ids:
            attachment_result = await _prepare_attachments(
                attachment_ids=attachment_ids,
                project_id=project_id,
                tenant_id=tenant_id,
            )
            logger.info(
                f"[AgentSession] Prepared {len(attachment_result.get('llm_content', []))} "
                f"LLM content parts, {len(attachment_result.get('attachment_metadata', []))} "
                f"metadata entries for conversation={conversation_id}"
            )

        logger.info(
            f"[AgentSession] Executing chat: conversation={conversation_id}, "
            f"message={message_id}, tenant={tenant_id}, project={project_id}"
        )

        # Get shared resources
        graph_service = get_agent_graph_service()
        redis_client = await get_redis_client()
        event_bus = RedisEventBusAdapter(redis_client)

        # Mark agent as running in Redis for page refresh recovery
        # This allows frontend to detect running state and recover stream
        running_key = f"agent:running:{conversation_id}"
        await redis_client.setex(
            running_key,
            300,  # 5 minute TTL (should be longer than any chat execution)
            message_id,
        )
        logger.info(f"[AgentSession] Set agent running: {running_key} -> {message_id}")

        # Get LLM provider configuration (cached)
        provider_config = await get_or_create_provider_config()

        # Get cached LLM client
        llm_client = await get_or_create_llm_client(provider_config)

        # Get cached tools
        tools = await get_or_create_tools(
            project_id=project_id,
            tenant_id=tenant_id,
            graph_service=graph_service,
            redis_client=redis_client,
            llm=llm_client,
            agent_mode=agent_mode,
            mcp_tools_ttl_seconds=session_config.get("mcp_tools_ttl_seconds", 300),
        )

        # Get cached skills
        skills = await get_or_create_skills(
            tenant_id=tenant_id,
            project_id=project_id,
        )

        # Get cached session context (fast path - should be already cached)
        processor_config = ProcessorConfig(
            model="",
            api_key="",
            base_url=None,
            temperature=session_config.get("temperature", 0.7),
            max_tokens=session_config.get("max_tokens", 4096),
            max_steps=session_config.get("max_steps", 20),
        )

        session_ctx = await get_or_create_agent_session(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
            tools=tools,
            skills=skills,
            subagents=[],
            processor_config=processor_config,
        )

        cache_time_ms = (time_module.time() - start_time) * 1000
        logger.info(
            f"[AgentSession] Cache retrieval took {cache_time_ms:.1f}ms "
            f"(use_count={session_ctx.use_count})"
        )

        # Construct model name for LiteLLM
        base_model = session_config.get("model") or provider_config.llm_model
        provider_type_str = (
            provider_config.provider_type.value
            if hasattr(provider_config.provider_type, "value")
            else str(provider_config.provider_type)
        )

        if "/" not in base_model:
            if provider_type_str == "zai":
                default_model = f"openai/{base_model}"
            elif provider_type_str == "qwen":
                default_model = f"dashscope/{base_model}"
            else:
                default_model = f"{provider_type_str}/{base_model}"
        else:
            default_model = base_model

        # Decrypt API key
        encryption_service = get_encryption_service()
        api_key = session_config.get("api_key") or encryption_service.decrypt(
            provider_config.api_key_encrypted
        )
        base_url = session_config.get("base_url") or provider_config.base_url

        # Set environment variables for LiteLLM
        if provider_type_str == "zai":
            os.environ["OPENAI_API_KEY"] = api_key
            if base_url:
                os.environ["OPENAI_API_BASE"] = base_url
            else:
                os.environ["OPENAI_API_BASE"] = "https://open.bigmodel.cn/api/paas/v4"
        elif provider_type_str == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
            if base_url:
                os.environ["OPENAI_API_BASE"] = base_url
        elif provider_type_str == "qwen":
            os.environ["DASHSCOPE_API_KEY"] = api_key
        elif provider_type_str == "deepseek":
            os.environ["DEEPSEEK_API_KEY"] = api_key
            if base_url:
                os.environ["DEEPSEEK_API_BASE"] = base_url
        elif provider_type_str == "gemini":
            os.environ["GOOGLE_API_KEY"] = api_key
            os.environ["GEMINI_API_KEY"] = api_key
        elif provider_type_str == "anthropic":
            os.environ["ANTHROPIC_API_KEY"] = api_key

        # Get artifact service for rich output handling (images, files, etc.)
        artifact_service = await _get_artifact_service()

        # Create ReActAgent with cached components
        agent = ReActAgent(
            model=default_model,
            tools=tools,
            api_key=api_key,
            base_url=base_url,
            temperature=session_config.get("temperature", 0.7),
            max_tokens=session_config.get("max_tokens", 4096),
            max_steps=session_config.get("max_steps", 20),
            agent_mode=agent_mode,
            skills=skills,
            # Use cached components from session pool
            _cached_tool_definitions=session_ctx.tool_definitions,
            _cached_system_prompt_manager=session_ctx.system_prompt_manager,
            _cached_subagent_router=session_ctx.subagent_router,
            # Artifact service for handling rich tool outputs
            artifact_service=artifact_service,
        )

        agent_init_time_ms = (time_module.time() - start_time) * 1000
        logger.info(f"[AgentSession] Agent initialized in {agent_init_time_ms:.1f}ms total")

        # Get the last sequence number from DB to continue from there
        # This ensures sequence_number is globally consistent across user_message and agent events
        sequence_number = await _get_last_sequence_number(conversation_id)
        logger.info(
            f"[AgentSession] Starting from sequence_number={sequence_number} for conversation={conversation_id}"
        )

        # Track execution
        final_content = ""
        is_error = False
        error_message = None

        from src.configuration.config import get_settings

        settings = get_settings()

        # Pre-generate assistant message ID for consistent references
        assistant_message_id = str(uuid.uuid4())

        # Collect artifacts produced during execution
        collected_artifacts: list[Dict[str, Any]] = []

        # Execute ReActAgent and stream events
        event_count = 0
        # Stream key for persistent storage (Redis Stream)
        stream_key = f"agent:events:{conversation_id}"

        async for event in agent.stream(
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            conversation_context=conversation_context,
            message_id=assistant_message_id,
            attachment_content=attachment_result.get("llm_content"),
            attachment_metadata=attachment_result.get("attachment_metadata"),
        ):
            event_count += 1
            sequence_number += 1
            event_type = event.get("type", "unknown")
            event_data = event.get("data", {})

            # Log important events (reduce noise from text_delta)
            if event_type == "text_delta":
                if event_count <= 3 or event_count % 10 == 0:
                    delta_preview = event_data.get("delta", "")[:20]
                    logger.info(
                        f"[AgentSession] TEXT_DELTA #{event_count}: seq={sequence_number}, "
                        f"delta='{delta_preview}...'"
                    )
            else:
                logger.info(
                    f"[AgentSession] Event #{event_count}: type={event_type}, seq={sequence_number}"
                )

            # Inject message_id for frontend filtering
            event_data_with_message_id = {**event_data, "message_id": message_id}

            # Extract and externalize artifacts (e.g., screenshots) to avoid large payloads
            event_data_with_message_id, artifacts = await _extract_artifacts_from_event_data(
                conversation_id=conversation_id,
                message_id=message_id,
                event_type=event_type,
                event_data=event_data_with_message_id,
            )
            if artifacts:
                collected_artifacts.extend(artifacts)

            # Filter empty thoughts and optionally suppress thought streaming
            should_publish = True
            if event_type == "thought":
                thought_text = (
                    event_data_with_message_id.get("thought")
                    or event_data_with_message_id.get("content")
                    or ""
                )
                if not thought_text.strip():
                    continue
                if not settings.agent_emit_thoughts:
                    should_publish = False

            # Attach artifacts to complete event for downstream rendering
            if event_type == "complete":
                event_data_with_message_id["id"] = assistant_message_id
                event_data_with_message_id["assistant_message_id"] = assistant_message_id
                if collected_artifacts:
                    event_data_with_message_id["artifacts"] = collected_artifacts

            # Track content
            if event_type == "text_delta":
                final_content += event_data_with_message_id.get("delta", "")
            elif event_type == "complete":
                final_content = event_data_with_message_id.get("content", final_content)
            elif event_type == "error":
                is_error = True
                error_message = event_data_with_message_id.get("message", "Unknown error")

            # Construct event payload using EventSerializer (single source of truth)
            # This replaces manual event construction with a unified serialization approach
            event_payload = {
                "type": event_type,
                "data": event_data_with_message_id,
                "seq": sequence_number,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            # ================================================================
            # Simplified event publication (single-write to Redis Stream):
            # - Redis Stream provides both persistence AND real-time delivery via XREAD
            # - Removed: Redis List buffer (redundant - Stream has replay capability)
            # - Removed: Redis Pub/Sub (redundant - Stream XREAD with block=0 provides real-time)
            # ================================================================

            try:
                if should_publish:
                    # Single write to Redis Stream (persistent, replayable, real-time)
                    # Auto-trim to 1000 messages per conversation to prevent unbounded growth
                    await event_bus.stream_add(stream_key, event_payload, maxlen=1000)

            except Exception as publish_err:
                logger.warning(f"[AgentSession] Failed to publish event: {publish_err}")

            # Save to DB (skip delta & noisy events for performance)
            await _save_event_to_db(
                conversation_id,
                message_id,
                event_type,
                event_data_with_message_id,
                sequence_number,
            )

            # Buffer text_delta events to database for debugging/late replay
            if event_type in BUFFER_EVENT_TYPES:
                await _save_text_delta_to_buffer(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type=event_type,
                    event_data=event_data_with_message_id,
                    sequence_number=sequence_number,
                    ttl_seconds=300,  # 5 minutes
                )

        # Save assistant message if completed successfully
        if not is_error and final_content:
            sequence_number += 1
            await _save_assistant_message_event(
                conversation_id=conversation_id,
                message_id=message_id,
                content=final_content,
                assistant_message_id=assistant_message_id,
                artifacts=collected_artifacts or None,
                sequence_number=sequence_number,
            )

            # Auto-generate title for first message in conversation
            # Check if this is the first exchange (user + assistant = 2 messages)
            # Only generate for conversations with default title
            message_count = await _get_conversation_message_count(conversation_id)
            if message_count <= 2:  # First user + assistant pair
                await _maybe_generate_and_publish_title(
                    conversation_id=conversation_id,
                    user_message=user_message,
                    tenant_id=session_config.get("tenant_id", ""),
                    project_id=session_config.get("project_id", ""),
                    sequence_number=sequence_number + 1,
                    stream_key=stream_key,
                    event_bus=event_bus,
                )

        total_time_ms = (time_module.time() - start_time) * 1000
        logger.info(
            f"[AgentSession] Chat completed in {total_time_ms:.1f}ms: "
            f"conversation={conversation_id}, error={is_error}"
        )

        # Clear running state after completion
        try:
            await redis_client.delete(running_key)
            logger.info(f"[AgentSession] Cleared agent running: {running_key}")
        except Exception as clear_err:
            logger.warning(f"[AgentSession] Failed to clear running state: {clear_err}")

        return {
            "content": final_content,
            "sequence_number": sequence_number,
            "is_error": is_error,
            "error_message": error_message,
            "execution_time_ms": total_time_ms,
        }

    except Exception as e:
        logger.error(f"[AgentSession] Chat execution failed: {e}", exc_info=True)
        # Try to clear running state on error
        try:
            redis_client = await get_redis_client()
            running_key = f"agent:running:{input.get('conversation_id', '')}"
            await redis_client.delete(running_key)
            logger.info(f"[AgentSession] Cleared agent running on error: {running_key}")
        except Exception as clear_err:
            logger.warning(f"[AgentSession] Failed to clear running state on error: {clear_err}")
        return {
            "content": "",
            "sequence_number": 0,
            "is_error": True,
            "error_message": str(e),
        }


@activity.defn
async def cleanup_agent_session_activity(
    config: Any,  # AgentSessionConfig dataclass
) -> Dict[str, Any]:
    """
    Clean up Agent Session resources.

    This activity is called when the session workflow is stopping.
    It clears session-specific caches to free memory.

    Args:
        config: AgentSessionConfig

    Returns:
        Cleanup result
    """
    from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
        clear_session_cache,
    )

    try:
        # Extract config values
        if hasattr(config, "tenant_id"):
            tenant_id = config.tenant_id
            project_id = config.project_id
            agent_mode = config.agent_mode
        else:
            tenant_id = config.get("tenant_id", "")
            project_id = config.get("project_id", "")
            agent_mode = config.get("agent_mode", "default")

        logger.info(
            f"[AgentSession] Cleaning up session: tenant={tenant_id}, "
            f"project={project_id}, mode={agent_mode}"
        )

        # Clear session-specific cache
        cleared = await clear_session_cache(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_mode=agent_mode,
        )

        logger.info(
            f"[AgentSession] Cleanup completed: tenant={tenant_id}, "
            f"project={project_id}, cleared={cleared}"
        )

        return {
            "status": "cleaned",
            "cleared": cleared,
        }

    except Exception as e:
        logger.error(f"[AgentSession] Cleanup failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


# ============================================================================
# Helper functions (imported from agent.py to avoid duplication)
# ============================================================================


# Delta event types to skip persisting to main DB table
# These are stored in Redis Stream instead for better performance
SKIP_PERSIST_EVENT_TYPES = {
    "thought_delta",
    "text_delta",
    "text_start",
    "text_end",
}

# Noisy event types to skip when persistence is disabled
NOISY_EVENT_TYPES = {
    "step_start",
    "step_end",
    "act",
    "observe",
    "tool_start",
    "tool_result",
    "cost_update",
    "pattern_match",
}

# Event types to save to text_delta buffer table (for debugging and late replay)
# These events are auto-cleaned after 5 minutes
BUFFER_EVENT_TYPES = {
    "text_delta",
    "text_start",
    "text_end",
}


async def _get_last_sequence_number(conversation_id: str) -> int:
    """Get the last sequence number for a conversation from the database.

    This ensures that agent events continue from the correct sequence number
    after user_message events are saved by the service layer.
    """
    from sqlalchemy import func, select

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(func.max(AgentExecutionEvent.sequence_number)).where(
                    AgentExecutionEvent.conversation_id == conversation_id
                )
            )
            last_seq = result.scalar()
            return last_seq if last_seq is not None else 0
    except Exception as e:
        logger.warning(f"Failed to get last sequence number: {e}, defaulting to 0")
        return 0


async def _save_event_to_db(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    sequence_number: int,
) -> None:
    """Save event to DB with idempotency guarantee."""
    if event_type in SKIP_PERSIST_EVENT_TYPES:
        return

    from src.configuration.config import get_settings

    settings = get_settings()
    if event_type == "thought" and not settings.agent_persist_thoughts:
        return
    if not settings.agent_persist_detail_events and event_type in NOISY_EVENT_TYPES:
        return

    import uuid

    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    insert(AgentExecutionEvent)
                    .values(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        message_id=message_id,
                        event_type=event_type,
                        event_data=event_data,
                        sequence_number=sequence_number,
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
                )
                await session.execute(stmt)
    except IntegrityError as e:
        if "uq_agent_events_conv_seq" in str(e):
            logger.warning(
                f"Event already exists (conv={conversation_id}, seq={sequence_number}). "
                "Skipping duplicate."
            )
            return
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save event to DB: {e}")
        raise


async def _save_text_delta_to_buffer(
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Dict[str, Any],
    sequence_number: int,
    ttl_seconds: int = 300,  # 5 minutes default
) -> None:
    """
    Save text_delta event to short-term buffer table for debugging and late replay.

    Args:
        conversation_id: Conversation ID
        message_id: Message ID
        event_type: Event type (text_delta, text_start, text_end)
        event_data: Full event data
        sequence_number: Sequence number
        ttl_seconds: Time-to-live in seconds (default 5 minutes)
    """
    if event_type not in BUFFER_EVENT_TYPES:
        return

    import uuid
    from datetime import timedelta

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import TextDeltaBuffer

    try:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        delta_content = event_data.get("delta", "") if event_type == "text_delta" else None

        async with async_session_factory() as session:
            async with session.begin():
                buffer_event = TextDeltaBuffer(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type=event_type,
                    delta_content=delta_content,
                    event_data=event_data,
                    sequence_number=sequence_number,
                    expires_at=expires_at,
                )
                session.add(buffer_event)

    except Exception as e:
        # Non-critical, just log and continue
        logger.warning(f"[AgentSession] Failed to buffer text_delta: {e}", exc_info=True)


async def _cleanup_expired_text_delta_buffer() -> int:
    """
    Clean up expired text_delta buffer entries.

    This should be called periodically (e.g., every minute) to remove expired entries.

    Returns:
        Number of entries deleted
    """
    from sqlalchemy import delete

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import TextDeltaBuffer

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    delete(TextDeltaBuffer).where(
                        TextDeltaBuffer.expires_at < datetime.now(timezone.utc)
                    )
                )
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logger.info(f"[TextDeltaBuffer] Cleaned up {deleted_count} expired entries")
                return deleted_count
    except Exception as e:
        logger.warning(f"[TextDeltaBuffer] Failed to cleanup: {e}")
        return 0


async def _save_assistant_message_event(
    conversation_id: str,
    message_id: str,
    content: str,
    sequence_number: int,
    assistant_message_id: Optional[str] = None,
    artifacts: Optional[list[Dict[str, Any]]] = None,
) -> str:
    """Save assistant_message event to unified event timeline."""
    import uuid

    from sqlalchemy.dialects.postgresql import insert
    from sqlalchemy.exc import IntegrityError

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    assistant_msg_id = assistant_message_id or str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            async with session.begin():
                stmt = (
                    insert(AgentExecutionEvent)
                    .values(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        message_id=message_id,
                        event_type="assistant_message",
                        event_data={
                            "content": content,
                            "message_id": assistant_msg_id,
                            "role": "assistant",
                            "artifacts": artifacts or [],
                        },
                        sequence_number=sequence_number,
                        created_at=datetime.now(timezone.utc),
                    )
                    .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
                )
                await session.execute(stmt)
        logger.info(
            f"Saved assistant_message event {assistant_msg_id} to conversation {conversation_id}"
        )
        return assistant_msg_id
    except IntegrityError as e:
        if "uq_agent_events_conv_seq" in str(e):
            logger.warning(
                f"assistant_message event already exists (conv={conversation_id}, "
                f"seq={sequence_number}). Skipping duplicate."
            )
            return assistant_msg_id
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save assistant_message event to DB: {e}")
        return assistant_msg_id
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save assistant_message event to DB: {e}")
        return assistant_msg_id
        logger.error(f"Database integrity error: {e}")
        raise
    except Exception as e:
        logger.error(f"Failed to save assistant_message event to DB: {e}")
        return assistant_msg_id
        raise


@activity.defn
async def generate_conversation_title_activity(
    input: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Generate a title for a conversation after the first message.

    This activity:
    1. Checks if conversation still has default title
    2. Fetches the first user message
    3. Generates a title using LLM or falls back to truncation
    4. Publishes a TITLE_GENERATED event
    5. Updates the conversation in the database

    This is called after execute_chat_activity completes to provide
    a user-friendly title for new conversations.

    Args:
        input: Dict containing:
            - conversation_id: Conversation ID
            - user_id: User ID for authorization
            - project_id: Project ID for authorization

    Returns:
        Dict with status, title, and metadata
    """
    from sqlalchemy import select

    from src.domain.events.agent_events import AgentTitleGeneratedEvent
    from src.domain.model.agent.agent_execution_event import USER_MESSAGE
    from src.infrastructure.adapters.secondary.event.redis_event_bus import (
        RedisEventBusAdapter,
    )
    from src.infrastructure.adapters.secondary.persistence.database import (
        async_session_factory,
    )
    from src.infrastructure.adapters.secondary.persistence.models import (
        AgentExecutionEvent,
        Conversation,
    )

    conversation_id = input.get("conversation_id", "")
    user_id = input.get("user_id", "")
    project_id = input.get("project_id", "")

    try:
        # 1. Fetch conversation
        async with async_session_factory() as session:
            result = await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.project_id == project_id,
                    Conversation.user_id == user_id,
                )
            )
            conversation = result.scalar_one_or_none()

        if not conversation:
            logger.warning(f"[TitleGen] Conversation not found: {conversation_id}")
            return {
                "status": "error",
                "error": "Conversation not found",
            }

        # 2. Check if title generation is needed (only for default title)
        if conversation.title != "New Conversation":
            logger.info(
                f"[TitleGen] Skipping title generation for {conversation_id}: "
                f"custom title '{conversation.title}' already set"
            )
            return {
                "status": "skipped",
                "reason": "custom_title_exists",
                "current_title": conversation.title,
            }

        # 3. Fetch first user message for context
        async with async_session_factory() as session:
            result = await session.execute(
                select(AgentExecutionEvent)
                .where(
                    AgentExecutionEvent.conversation_id == conversation_id,
                    AgentExecutionEvent.event_type == USER_MESSAGE,
                )
                .order_by(AgentExecutionEvent.sequence_number.asc())
                .limit(1)
            )
            first_message_event = result.scalar_one_or_none()

        first_message = ""
        message_id = None
        if first_message_event:
            first_message = first_message_event.event_data.get("content", "")
            message_id = first_message_event.message_id

        # If no message found, use conversation ID as fallback
        if not first_message:
            first_message = conversation.id

        # 4. Generate title using AgentService logic
        from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
            get_or_create_llm_client,
            get_or_create_provider_config,
            get_redis_client,
        )

        provider_config = await get_or_create_provider_config()
        llm_client = await get_or_create_llm_client(provider_config)

        # Reuse the title generation logic from AgentService
        title = await _generate_title_for_message(first_message, llm_client)
        generated_by = "llm" if title else "fallback"

        # Fallback to truncated message
        if not title:
            title = _truncate_for_title(first_message)
            generated_by = "fallback"

        # 5. Update conversation in database
        async with async_session_factory() as session:
            result = await session.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = result.scalar_one_or_none()
            if conv:
                conv.title = title
                await session.commit()

        # 6. Publish TITLE_GENERATED event
        redis_client = await get_redis_client()
        if redis_client:
            event_bus = RedisEventBusAdapter(redis_client)
            title_event = AgentTitleGeneratedEvent(
                conversation_id=conversation_id,
                title=title,
                message_id=message_id,
                generated_by=generated_by,
            )
            event_payload = {
                "type": "title_generated",
                "data": title_event.model_dump(exclude={"timestamp", "event_type"}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            stream_key = f"agent:events:{conversation_id}"
            try:
                await event_bus.stream_add(stream_key, event_payload, maxlen=1000)
            except Exception as e:
                logger.warning(f"[TitleGen] Failed to publish event: {e}")

        logger.info(
            f"[TitleGen] Generated title '{title}' for conversation {conversation_id} "
            f"(method={generated_by})"
        )

        return {
            "status": "success",
            "conversation_id": conversation_id,
            "title": title,
            "generated_by": generated_by,
            "message_id": message_id,
        }

    except Exception as e:
        logger.error(f"[TitleGen] Failed to generate title: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
        }


async def _generate_title_for_message(first_message: str, llm_client) -> str | None:
    """Generate a title using LLM with retry logic.

    Args:
        first_message: The first user message content
        llm_client: LLM client for generation

    Returns:
        Generated title or None if generation fails
    """
    import asyncio

    from src.domain.llm_providers.llm_types import Message as LLMMessage

    prompt = f"""Generate a short, friendly title (max 50 characters) for a conversation that starts with this message:

"{first_message[:200]}"

Guidelines:
- Be concise and descriptive
- Use the user's language (English, Chinese, etc.)
- Focus on the main topic or question
- Maximum 50 characters
- Return ONLY the title, no explanation

Title:"""

    max_retries = 2
    base_delay = 0.5  # seconds

    for attempt in range(max_retries):
        try:
            response = await llm_client.ainvoke(
                [
                    LLMMessage.system(
                        "You are a helpful assistant that generates concise conversation titles."
                    ),
                    LLMMessage.user(prompt),
                ]
            )

            title = response.content.strip().strip('"').strip("'")

            # Limit length
            if len(title) > 50:
                title = title[:47] + "..."

            if title:
                return title

        except Exception as e:
            logger.warning(f"[TitleGen] LLM attempt {attempt + 1}/{max_retries} failed: {e}")

            # If not the last attempt, wait with exponential backoff
            if attempt < max_retries - 1:
                delay = base_delay * (2**attempt)
                await asyncio.sleep(delay)

    return None


def _truncate_for_title(message: str) -> str:
    """Generate a fallback title from the first message.

    Args:
        message: The message content

    Returns:
        Truncated title (max 50 characters)
    """
    content = message.strip()

    # Take first 40 characters + "..." to stay under 50
    if len(content) > 40:
        # Try to break at word boundary
        truncated = content[:40]
        last_space = truncated.rfind(" ")
        if last_space > 20:  # Only if we get a reasonable segment
            truncated = truncated[:last_space]
        content = truncated + "..."

    return content or "New Conversation"


async def _get_conversation_message_count(conversation_id: str) -> int:
    """Get the number of message events in a conversation.

    Args:
        conversation_id: Conversation ID

    Returns:
        Number of message events (user_message + assistant_message)
    """
    from sqlalchemy import func, select

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent

    try:
        async with async_session_factory() as session:
            async with session.begin():
                result = await session.execute(
                    select(func.count())
                    .select_from(AgentExecutionEvent)
                    .where(
                        AgentExecutionEvent.conversation_id == conversation_id,
                        AgentExecutionEvent.event_type.in_(["user_message", "assistant_message"]),
                    )
                )
                return result.scalar() or 0
    except Exception as e:
        logger.error(f"[TitleGen] Failed to get message count: {e}")
        return 0  # Assume not first message if error


async def _maybe_generate_and_publish_title(
    conversation_id: str,
    user_message: str,
    tenant_id: str,
    project_id: str,
    sequence_number: int,
    stream_key: str,
    event_bus: Any,
) -> None:
    """Maybe generate and publish a title for the conversation.

    This function checks if the conversation has a default title,
    generates a new title if needed, and publishes a title_generated event.

    Args:
        conversation_id: Conversation ID
        user_message: First user message content
        tenant_id: Tenant ID
        project_id: Project ID
        sequence_number: Next sequence number for the title event
        stream_key: Redis Stream key
        event_bus: Event bus instance
    """
    from sqlalchemy import select

    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.models import Conversation
    from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
        get_or_create_llm_client,
        get_or_create_provider_config,
    )

    try:
        async with async_session_factory() as session:
            async with session.begin():
                # Check conversation title
                result = await session.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
                conversation = result.scalar_one_or_none()

                if not conversation:
                    logger.warning(f"[TitleGen] Conversation {conversation_id} not found")
                    return

                # Skip if title is already customized (not default)
                if conversation.title and conversation.title != "New Conversation":
                    logger.info(
                        f"[TitleGen] Skipping - conversation already has custom title: '{conversation.title}'"
                    )
                    return

                # Generate title
                provider_config = await get_or_create_provider_config()
                llm_client = await get_or_create_llm_client(provider_config)
                title = await _generate_title_for_message(user_message, llm_client)

                if not title:
                    title = _truncate_for_title(user_message)

                # Update conversation in database
                conversation.title = title
                session.add(conversation)

                logger.info(
                    f"[TitleGen] Generated title '{title}' for conversation {conversation_id}"
                )

                # Publish title_generated event to Redis Stream
                await event_bus.stream_add(
                    stream_key,
                    {
                        "type": "title_generated",
                        "data": {
                            "conversation_id": conversation_id,
                            "title": title,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "generated_by": "llm",
                        },
                        "seq": sequence_number,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                    maxlen=1000,
                )

                logger.info(f"[TitleGen] Published title_generated event for {conversation_id}")

    except Exception as e:
        logger.error(f"[TitleGen] Failed to generate/publish title: {e}", exc_info=True)
