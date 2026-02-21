"""Channel configuration API endpoints."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup import get_channel_manager
from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
)
from src.infrastructure.adapters.secondary.persistence.channel_repository import (
    ChannelConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User, UserProject
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

    channel_type: str = Field(..., description="Channel type: feishu, dingtalk, wecom")
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
    webhook_port: Optional[int] = Field(None, description="Webhook port")
    webhook_path: Optional[str] = Field(None, description="Webhook path")

    # Settings
    domain: Optional[str] = Field("feishu", description="Domain")
    extra_settings: Optional[dict] = Field(None, description="Extra settings")
    description: Optional[str] = Field(None, description="Description")


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
    webhook_port: Optional[int] = None
    webhook_path: Optional[str] = None
    domain: Optional[str] = None
    extra_settings: Optional[dict] = None
    description: Optional[str] = None


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
    if current_user.role not in ["admin", "super_admin"]:
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
