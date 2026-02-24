"""Factory functions for creating channel-related services."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.channels.media_import_service import MediaImportService
from src.infrastructure.adapters.secondary.channels.feishu.media_downloader import (
    FeishuMediaDownloader,
)

logger = logging.getLogger(__name__)


def create_media_import_service(
    db_session: AsyncSession,
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
) -> MediaImportService | None:
    """Create a MediaImportService instance with FeishuMediaDownloader.

    This factory function creates the lightweight media import service
    with only the FeishuMediaDownloader dependency. Heavy dependencies
    (mcp_adapter, artifact_service, db_session) are passed at call time.

    Args:
        db_session: Database session (unused, kept for API compatibility)
        app_id: Feishu app ID
        app_secret: Feishu app secret
        domain: Feishu domain ("feishu" or "lark")

    Returns:
        Lightweight MediaImportService instance, or None if failed
    """
    try:
        # Create Feishu media downloader
        feishu_downloader = FeishuMediaDownloader(
            app_id=app_id,
            app_secret=app_secret,
            domain=domain,
        )

        # Create lightweight service (no heavy dependencies)
        media_import_service = MediaImportService(feishu_downloader=feishu_downloader)

        logger.info("Successfully created MediaImportService")
        return media_import_service

    except Exception as e:
        logger.error(f"Failed to create MediaImportService: {e}", exc_info=True)
        return None


async def create_media_import_service_from_config(
    db_session: AsyncSession,
    channel_config_id: str | None = None,
) -> MediaImportService | None:
    """Create MediaImportService from database channel configuration.

    This function loads the channel config from database and creates
    the appropriate media import service with proper credentials.

    Args:
        db_session: Database session for queries
        channel_config_id: Optional channel config ID. If not provided,
            uses the first enabled Feishu config found.

    Returns:
        Configured MediaImportService instance, or None if failed
    """
    try:
        from src.infrastructure.adapters.secondary.persistence.channel_models import (
            ChannelConfigModel,
        )

        logger.info(
            f"[MediaImportFactory] Creating MediaImportService - "
            f"channel_config_id={channel_config_id}"
        )

        # Build query
        query = select(ChannelConfigModel).where(
            ChannelConfigModel.enabled.is_(True),
            ChannelConfigModel.channel_type == "feishu",
        )

        if channel_config_id:
            query = query.where(ChannelConfigModel.id == channel_config_id)

        query = query.limit(1)

        logger.info("[MediaImportFactory] Executing query...")
        result = await db_session.execute(query)
        config = result.scalar_one_or_none()

        if not config:
            logger.warning(
                "[MediaImportFactory] No enabled Feishu channel config found in database"
            )
            return None

        logger.info(
            f"[MediaImportFactory] Found config: id={config.id}, "
            f"app_id={config.app_id}, project_id={config.project_id}"
        )

        # Extract config
        app_id = config.app_id
        app_secret = config.app_secret

        # Decrypt app_secret if needed
        if app_secret:
            try:
                from src.infrastructure.security.encryption_service import get_encryption_service

                encryption_service = get_encryption_service()
                app_secret = encryption_service.decrypt(app_secret)
            except Exception as e:
                logger.warning(f"[MediaImportFactory] Failed to decrypt app_secret: {e}")

        # Use domain field if available, otherwise check extra_settings
        domain = "feishu"
        if hasattr(config, "domain") and config.domain:
            domain = config.domain
        elif hasattr(config, "extra_settings") and config.extra_settings:
            domain = config.extra_settings.get("domain", "feishu")

        if not app_id or not app_secret:
            logger.warning(
                f"[MediaImportFactory] Channel config {config.id} missing credentials - "
                f"app_id={bool(app_id)}, app_secret={bool(app_secret)}"
            )
            return None

        logger.info(f"[MediaImportFactory] Creating MediaImportService with domain={domain}")

        return create_media_import_service(
            db_session=db_session,
            app_id=app_id,
            app_secret=app_secret,
            domain=domain,
        )

    except Exception as e:
        logger.error(
            f"[MediaImportFactory] Failed to create MediaImportService from config: {e}",
            exc_info=True,
        )
        return None
