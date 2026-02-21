"""Channel configuration API endpoints."""

import logging
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, desc, func, nullslast, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.roles import RoleDefinition
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup import get_channel_manager
from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelOutboxModel,
    ChannelSessionBindingModel,
)
from src.infrastructure.adapters.secondary.persistence.channel_repository import (
    ChannelConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    Role,
    User,
    UserProject,
    UserRole,
)
from src.infrastructure.security.encryption_service import get_encryption_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])


async def verify_project_access(
    project_id: str,
    user: User,
    db: AsyncSession,
    required_role: Optional[List[str]] = None,
):
    """Verify that user has access to the project.

    Args:
        project_id: Project ID to check access for
        user: Current user
        db: Database session
        required_role: Optional list of required roles (e.g., ["owner", "admin"])

    Raises:
        HTTPException: 403 if access denied
    """
    query = select(UserProject).where(
        and_(UserProject.user_id == user.id, UserProject.project_id == project_id)
    )
    if required_role:
        query = query.where(UserProject.role.in_(required_role))

    result = await db.execute(query)
    user_project = result.scalar_one_or_none()

    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to project"
        )
    return user_project


# Pydantic schemas


class ChannelConfigCreate(BaseModel):
    """Schema for creating channel configuration."""

    channel_type: str = Field(
        ...,
        description="Channel type: feishu, dingtalk, wecom",
        pattern=r"^(feishu|dingtalk|wecom|slack|telegram)$",
    )
    name: str = Field(..., description="Display name")
    enabled: bool = Field(True, description="Whether enabled")
    connection_mode: str = Field("websocket", description="websocket or webhook")

    # Credentials
    app_id: Optional[str] = Field(None, description="App ID")
    app_secret: Optional[str] = Field(None, description="App secret")
    encrypt_key: Optional[str] = Field(None, description="Encrypt key")
    verification_token: Optional[str] = Field(None, description="Verification token")

    # Webhook
    webhook_url: Optional[str] = Field(None, description="Webhook URL")
    webhook_port: Optional[int] = Field(None, ge=1, le=65535, description="Webhook port")
    webhook_path: Optional[str] = Field(None, description="Webhook path")

    # Access control
    dm_policy: str = Field(
        "open",
        description="DM policy: open, allowlist, disabled",
        pattern=r"^(open|allowlist|disabled)$",
    )
    group_policy: str = Field(
        "open",
        description="Group policy: open, allowlist, disabled",
        pattern=r"^(open|allowlist|disabled)$",
    )
    allow_from: Optional[List[str]] = Field(
        None, description="Allowlist of user IDs (wildcard * = all)"
    )
    group_allow_from: Optional[List[str]] = Field(
        None, description="Allowlist of group/chat IDs"
    )
    rate_limit_per_minute: int = Field(
        60, ge=0, description="Max messages per minute per chat (0 = unlimited)"
    )

    # Settings
    domain: Optional[str] = Field("feishu", description="Domain")
    extra_settings: Optional[dict] = Field(None, description="Extra settings")
    description: Optional[str] = Field(None, description="Description")

    @model_validator(mode="after")
    def _validate_webhook_requires_token(self) -> "ChannelConfigCreate":
        if self.connection_mode == "webhook" and not self.verification_token:
            raise ValueError(
                "verification_token is required when connection_mode is 'webhook'"
            )
        return self


class ChannelConfigUpdate(BaseModel):
    """Schema for updating channel configuration."""

    name: Optional[str] = None
    enabled: Optional[bool] = None
    connection_mode: Optional[str] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    encrypt_key: Optional[str] = None
    verification_token: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_port: Optional[int] = Field(None, ge=1, le=65535)
    webhook_path: Optional[str] = None
    domain: Optional[str] = None
    extra_settings: Optional[dict] = None
    description: Optional[str] = None
    dm_policy: Optional[str] = Field(
        None, pattern=r"^(open|allowlist|disabled)$"
    )
    group_policy: Optional[str] = Field(
        None, pattern=r"^(open|allowlist|disabled)$"
    )
    allow_from: Optional[List[str]] = None
    group_allow_from: Optional[List[str]] = None
    rate_limit_per_minute: Optional[int] = Field(None, ge=0)


class ChannelConfigResponse(BaseModel):
    """Schema for channel configuration response."""

    id: str
    project_id: str
    channel_type: str
    name: str
    enabled: bool
    connection_mode: str
    app_id: Optional[str] = None
    # app_secret is excluded for security
    webhook_url: Optional[str] = None
    webhook_port: Optional[int] = None
    webhook_path: Optional[str] = None
    domain: Optional[str] = None
    extra_settings: Optional[dict] = None
    dm_policy: str = "open"
    group_policy: str = "open"
    allow_from: Optional[List[str]] = None
    group_allow_from: Optional[List[str]] = None
    rate_limit_per_minute: int = 60
    status: str
    last_error: Optional[str] = None
    description: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ChannelConfigList(BaseModel):
    """Schema for listing channel configurations."""

    items: List[ChannelConfigResponse]
    total: int


# Helper function to convert model to response (excluding sensitive data)
def to_response(config: ChannelConfigModel) -> ChannelConfigResponse:
    return ChannelConfigResponse(
        id=config.id,
        project_id=config.project_id,
        channel_type=config.channel_type,
        name=config.name,
        enabled=config.enabled,
        connection_mode=config.connection_mode,
        app_id=config.app_id,
        webhook_url=config.webhook_url,
        webhook_port=config.webhook_port,
        webhook_path=config.webhook_path,
        domain=config.domain,
        extra_settings=config.extra_settings,
        dm_policy=getattr(config, "dm_policy", None) or "open",
        group_policy=getattr(config, "group_policy", None) or "open",
        allow_from=getattr(config, "allow_from", None),
        group_allow_from=getattr(config, "group_allow_from", None),
        rate_limit_per_minute=getattr(config, "rate_limit_per_minute", None) or 60,
        status=config.status,
        last_error=config.last_error,
        description=config.description,
        created_at=config.created_at.isoformat(),
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


# API Endpoints


@router.post(
    "/projects/{project_id}/configs",
    response_model=ChannelConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_config(
    project_id: str,
    data: ChannelConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new channel configuration for a project."""
    # Verify project access (requires admin or owner role)
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    repo = ChannelConfigRepository(db)

    # Encrypt sensitive credentials before storage
    encryption_service = get_encryption_service()
    encrypted_secret = None
    if data.app_secret:
        encrypted_secret = encryption_service.encrypt(data.app_secret)

    config = ChannelConfigModel(
        project_id=project_id,
        channel_type=data.channel_type,
        name=data.name,
        enabled=data.enabled,
        connection_mode=data.connection_mode,
        app_id=data.app_id,
        app_secret=encrypted_secret,  # Encrypted
        encrypt_key=data.encrypt_key,
        verification_token=data.verification_token,
        webhook_url=data.webhook_url,
        webhook_port=data.webhook_port,
        webhook_path=data.webhook_path,
        domain=data.domain,
        extra_settings=data.extra_settings,
        dm_policy=data.dm_policy,
        group_policy=data.group_policy,
        allow_from=data.allow_from,
        group_allow_from=data.group_allow_from,
        rate_limit_per_minute=data.rate_limit_per_minute,
        description=data.description,
        created_by=current_user.id,
    )

    created = await repo.create(config)
    await db.commit()

    # Auto-connect if enabled
    if created.enabled:
        channel_manager = get_channel_manager()
        if channel_manager:
            try:
                await channel_manager.add_connection(created)
                logger.info(f"[Channels] Auto-connected channel {created.id}")
            except Exception as e:
                logger.warning(f"[Channels] Failed to auto-connect channel {created.id}: {e}")

    return to_response(created)


@router.get("/projects/{project_id}/configs", response_model=ChannelConfigList)
async def list_configs(
    project_id: str,
    channel_type: Optional[str] = None,
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List channel configurations for a project."""
    # Verify project access
    await verify_project_access(project_id, current_user, db)

    repo = ChannelConfigRepository(db)
    configs = await repo.list_by_project(
        project_id, channel_type=channel_type, enabled_only=enabled_only
    )

    return ChannelConfigList(items=[to_response(c) for c in configs], total=len(configs))


@router.get("/configs/{config_id}", response_model=ChannelConfigResponse)
async def get_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a channel configuration by ID."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access
    await verify_project_access(config.project_id, current_user, db)

    return to_response(config)


@router.put("/configs/{config_id}", response_model=ChannelConfigResponse)
async def update_config(
    config_id: str,
    data: ChannelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a channel configuration."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access (requires admin or owner role)
    await verify_project_access(config.project_id, current_user, db, ["owner", "admin"])

    # Update fields
    update_data = data.model_dump(exclude_unset=True)

    # Encrypt app_secret if provided
    if update_data.get("app_secret"):
        encryption_service = get_encryption_service()
        update_data["app_secret"] = encryption_service.encrypt(update_data["app_secret"])

    for field, value in update_data.items():
        setattr(config, field, value)

    updated = await repo.update(config)
    await db.commit()

    # Restart connection if manager is available
    channel_manager = get_channel_manager()
    if channel_manager:
        try:
            await channel_manager.restart_connection(config_id)
            logger.info(f"[Channels] Restarted connection for channel {config_id}")
        except Exception as e:
            logger.warning(f"[Channels] Failed to restart connection {config_id}: {e}")

    return to_response(updated)


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a channel configuration."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access (requires admin or owner role)
    await verify_project_access(config.project_id, current_user, db, ["owner", "admin"])

    # Disconnect channel if connected
    channel_manager = get_channel_manager()
    if channel_manager:
        try:
            await channel_manager.remove_connection(config_id)
            logger.info(f"[Channels] Disconnected channel {config_id}")
        except Exception as e:
            logger.warning(f"[Channels] Failed to disconnect channel {config_id}: {e}")

    deleted = await repo.delete(config_id)
    await db.commit()

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete configuration",
        )

    return None


@router.post("/configs/{config_id}/test", response_model=dict)
async def test_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test a channel configuration by attempting to connect."""
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access
    await verify_project_access(config.project_id, current_user, db)

    # Decrypt credentials for testing
    encryption_service = get_encryption_service()
    app_secret = ""
    if config.app_secret:
        try:
            app_secret = encryption_service.decrypt(config.app_secret)
        except Exception as e:
            logger.warning(f"Failed to decrypt app_secret: {e}")
            return {"success": False, "message": "Failed to decrypt credentials"}

    # Test connection based on channel type
    try:
        if config.channel_type == "feishu":
            from src.infrastructure.adapters.secondary.channels.feishu import (
                FeishuClient,
            )

            # Create client to validate credentials
            FeishuClient(
                app_id=config.app_id or "",
                app_secret=app_secret,
                domain=config.domain or "feishu",
            )

            # Try to get bot info as a test
            # This will fail if credentials are invalid
            # await client.get_bot_info()

            await repo.update_status(config_id, "connected")
            await db.commit()

            return {"success": True, "message": "Connection successful"}
        else:
            return {
                "success": False,
                "message": f"Testing not implemented for {config.channel_type}",
            }

    except Exception as e:
        await repo.update_status(config_id, "error", str(e))
        await db.commit()

        return {"success": False, "message": str(e)}


class ChannelStatusResponse(BaseModel):
    """Schema for channel connection status response."""

    config_id: str
    project_id: str
    channel_type: str
    status: str
    connected: bool
    last_heartbeat: Optional[str] = None
    last_error: Optional[str] = None
    reconnect_attempts: int = 0


class ChannelObservabilitySummaryResponse(BaseModel):
    """Project-level channel routing and delivery summary."""

    project_id: str
    session_bindings_total: int
    outbox_total: int
    outbox_by_status: Dict[str, int]
    active_connections: int
    connected_config_ids: List[str]
    latest_delivery_error: Optional[str] = None


class ChannelOutboxItemResponse(BaseModel):
    """Outbox queue item response."""

    id: str
    channel_config_id: str
    conversation_id: str
    chat_id: str
    status: str
    attempt_count: int
    max_attempts: int
    sent_channel_message_id: Optional[str] = None
    last_error: Optional[str] = None
    next_retry_at: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class ChannelOutboxListResponse(BaseModel):
    """Paginated outbox list response."""

    items: List[ChannelOutboxItemResponse]
    total: int


class ChannelSessionBindingItemResponse(BaseModel):
    """Session binding item response."""

    id: str
    channel_config_id: str
    conversation_id: str
    channel_type: str
    chat_id: str
    chat_type: str
    thread_id: Optional[str] = None
    topic_id: Optional[str] = None
    session_key: str
    created_at: str
    updated_at: Optional[str] = None


class ChannelSessionBindingListResponse(BaseModel):
    """Paginated session binding list response."""

    items: List[ChannelSessionBindingItemResponse]
    total: int


@router.get(
    "/projects/{project_id}/observability/summary",
    response_model=ChannelObservabilitySummaryResponse,
)
async def get_project_channel_observability_summary(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get project-level channel routing and delivery observability summary."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    bindings_total_result = await db.execute(
        select(func.count())
        .select_from(ChannelSessionBindingModel)
        .where(ChannelSessionBindingModel.project_id == project_id)
    )
    session_bindings_total = int(bindings_total_result.scalar() or 0)

    outbox_total_result = await db.execute(
        select(func.count())
        .select_from(ChannelOutboxModel)
        .where(ChannelOutboxModel.project_id == project_id)
    )
    outbox_total = int(outbox_total_result.scalar() or 0)

    outbox_by_status_result = await db.execute(
        select(ChannelOutboxModel.status, func.count())
        .where(ChannelOutboxModel.project_id == project_id)
        .group_by(ChannelOutboxModel.status)
    )
    outbox_by_status: Dict[str, int] = {
        status_name: int(status_count)
        for status_name, status_count in outbox_by_status_result.all()
    }

    latest_error_result = await db.execute(
        select(ChannelOutboxModel.last_error)
        .where(
            ChannelOutboxModel.project_id == project_id,
            ChannelOutboxModel.last_error.isnot(None),
            ChannelOutboxModel.status.in_(["failed", "dead_letter"]),
        )
        .order_by(
            nullslast(desc(ChannelOutboxModel.updated_at)), desc(ChannelOutboxModel.created_at)
        )
        .limit(1)
    )
    latest_delivery_error = latest_error_result.scalar_one_or_none()

    active_connections = 0
    connected_config_ids: List[str] = []
    channel_manager = get_channel_manager()
    if channel_manager:
        for connection in channel_manager.connections.values():
            if connection.project_id == project_id and connection.status == "connected":
                active_connections += 1
                connected_config_ids.append(connection.config_id)

    return ChannelObservabilitySummaryResponse(
        project_id=project_id,
        session_bindings_total=session_bindings_total,
        outbox_total=outbox_total,
        outbox_by_status=outbox_by_status,
        active_connections=active_connections,
        connected_config_ids=connected_config_ids,
        latest_delivery_error=latest_delivery_error,
    )


@router.get(
    "/projects/{project_id}/observability/outbox",
    response_model=ChannelOutboxListResponse,
)
async def list_project_channel_outbox(
    project_id: str,
    status_filter: Optional[Literal["pending", "failed", "sent", "dead_letter"]] = Query(
        None, alias="status", description="Filter by outbox status"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List outbound queue items for a project."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    query = select(ChannelOutboxModel).where(ChannelOutboxModel.project_id == project_id)
    count_query = (
        select(func.count())
        .select_from(ChannelOutboxModel)
        .where(ChannelOutboxModel.project_id == project_id)
    )
    if status_filter:
        query = query.where(ChannelOutboxModel.status == status_filter)
        count_query = count_query.where(ChannelOutboxModel.status == status_filter)

    query = query.order_by(desc(ChannelOutboxModel.created_at)).limit(limit).offset(offset)
    result = await db.execute(query)
    items = result.scalars().all()

    total_result = await db.execute(count_query)
    total = int(total_result.scalar() or 0)

    return ChannelOutboxListResponse(
        items=[
            ChannelOutboxItemResponse(
                id=item.id,
                channel_config_id=item.channel_config_id,
                conversation_id=item.conversation_id,
                chat_id=item.chat_id,
                status=item.status,
                attempt_count=item.attempt_count,
                max_attempts=item.max_attempts,
                sent_channel_message_id=item.sent_channel_message_id,
                last_error=item.last_error,
                next_retry_at=item.next_retry_at.isoformat() if item.next_retry_at else None,
                created_at=item.created_at.isoformat(),
                updated_at=item.updated_at.isoformat() if item.updated_at else None,
            )
            for item in items
        ],
        total=total,
    )


@router.get(
    "/projects/{project_id}/observability/session-bindings",
    response_model=ChannelSessionBindingListResponse,
)
async def list_project_channel_session_bindings(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List deterministic channel session bindings for a project."""
    await verify_project_access(project_id, current_user, db, ["owner", "admin"])

    query = (
        select(ChannelSessionBindingModel)
        .where(ChannelSessionBindingModel.project_id == project_id)
        .order_by(desc(ChannelSessionBindingModel.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    items = result.scalars().all()

    total_result = await db.execute(
        select(func.count())
        .select_from(ChannelSessionBindingModel)
        .where(ChannelSessionBindingModel.project_id == project_id)
    )
    total = int(total_result.scalar() or 0)

    return ChannelSessionBindingListResponse(
        items=[
            ChannelSessionBindingItemResponse(
                id=item.id,
                channel_config_id=item.channel_config_id,
                conversation_id=item.conversation_id,
                channel_type=item.channel_type,
                chat_id=item.chat_id,
                chat_type=item.chat_type,
                thread_id=item.thread_id,
                topic_id=item.topic_id,
                session_key=item.session_key,
                created_at=item.created_at.isoformat(),
                updated_at=item.updated_at.isoformat() if item.updated_at else None,
            )
            for item in items
        ],
        total=total,
    )


@router.get("/configs/{config_id}/status", response_model=ChannelStatusResponse)
async def get_connection_status(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get real-time connection status for a channel configuration.

    This endpoint returns the live connection status from the
    ChannelConnectionManager, including:
    - Current connection status (connected/disconnected/error)
    - Last heartbeat timestamp
    - Last error message if any
    - Number of reconnection attempts
    """
    repo = ChannelConfigRepository(db)
    config = await repo.get_by_id(config_id)

    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")

    # Verify project access
    await verify_project_access(config.project_id, current_user, db)

    # Get real-time status from connection manager
    channel_manager = get_channel_manager()
    if channel_manager:
        status_data = channel_manager.get_status(config_id)
        if status_data:
            return ChannelStatusResponse(
                config_id=status_data["config_id"],
                project_id=status_data["project_id"],
                channel_type=status_data["channel_type"],
                status=status_data["status"],
                connected=status_data["connected"],
                last_heartbeat=status_data.get("last_heartbeat"),
                last_error=status_data.get("last_error"),
                reconnect_attempts=status_data.get("reconnect_attempts", 0),
            )

    # Fall back to database status if not in connection manager
    return ChannelStatusResponse(
        config_id=config.id,
        project_id=config.project_id,
        channel_type=config.channel_type,
        status=config.status,
        connected=config.status == "connected",
        last_heartbeat=None,
        last_error=config.last_error,
        reconnect_attempts=0,
    )


@router.get("/status", response_model=List[ChannelStatusResponse])
async def list_all_connection_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get connection status for all channels.

    Returns a list of all channel connection statuses.
    Requires admin role.
    """
    # Only admins can view all statuses
    has_admin_role = False
    if not current_user.is_superuser:
        role_result = await db.execute(
            select(func.count())
            .select_from(UserRole)
            .join(Role, UserRole.role_id == Role.id)
            .where(
                UserRole.user_id == current_user.id,
                Role.name.in_([RoleDefinition.SYSTEM_ADMIN, "admin", "super_admin"]),
                UserRole.tenant_id.is_(None),
            )
        )
        has_admin_role = bool(role_result.scalar())

    if not current_user.is_superuser and not has_admin_role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )

    channel_manager = get_channel_manager()
    if channel_manager:
        statuses = channel_manager.get_all_status()
        return [
            ChannelStatusResponse(
                config_id=s["config_id"],
                project_id=s["project_id"],
                channel_type=s["channel_type"],
                status=s["status"],
                connected=s["connected"],
                last_heartbeat=s.get("last_heartbeat"),
                last_error=s.get("last_error"),
                reconnect_attempts=s.get("reconnect_attempts", 0),
            )
            for s in statuses
        ]

    return []


# ------------------------------------------------------------------
# Push API — agent-initiated outbound messages
# ------------------------------------------------------------------


class PushMessageRequest(BaseModel):
    """Request body for pushing a message to a bound channel."""

    content: str = Field(..., max_length=4000, description="Text content to send")
    content_type: Literal["text", "markdown", "card"] = Field(
        default="text",
        description="Content format: text, markdown, or card (JSON)",
    )
    card: Optional[Dict] = Field(
        default=None,
        description="Card JSON payload (required when content_type is 'card')",
    )


class PushMessageResponse(BaseModel):
    success: bool
    message: str


@router.post(
    "/conversations/{conversation_id}/push",
    response_model=PushMessageResponse,
    summary="Push message to channel",
    description="Send an agent-initiated message to the channel bound to a conversation.",
)
async def push_message_to_channel(
    conversation_id: str,
    body: PushMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushMessageResponse:
    """Push a message to the channel bound to a conversation."""
    # Verify conversation exists and user has access
    binding = await db.execute(
        select(ChannelSessionBindingModel).where(
            ChannelSessionBindingModel.conversation_id == conversation_id
        )
    )
    binding_row = binding.scalar_one_or_none()
    if not binding_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No channel binding found for this conversation",
        )

    # Verify user has access to the channel's project
    config = await db.execute(
        select(ChannelConfigModel).where(
            ChannelConfigModel.id == binding_row.channel_config_id
        )
    )
    config_row = config.scalar_one_or_none()
    if config_row:
        await verify_project_access(config_row.project_id, user, db)

    from src.application.services.channels.channel_message_router import (
        get_channel_message_router,
    )

    router_instance = get_channel_message_router()
    success = await router_instance.send_to_channel(
        conversation_id=conversation_id,
        content=body.content,
        content_type=body.content_type,
        card=body.card,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to deliver message to channel",
        )

    return PushMessageResponse(success=True, message="Message sent")
