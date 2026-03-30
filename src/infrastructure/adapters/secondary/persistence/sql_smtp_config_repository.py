from __future__ import annotations

from datetime import UTC, datetime
from typing import override

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.smtp.smtp_config import SmtpConfig
from src.domain.ports.repositories.smtp_config_repository import (
    SmtpConfigRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    SmtpConfigModel,
)


class SqlSmtpConfigRepository(SmtpConfigRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def find_by_tenant(self, tenant_id: str) -> SmtpConfig | None:
        result = await self._session.execute(
            select(SmtpConfigModel).where(
                SmtpConfigModel.tenant_id == tenant_id,
                SmtpConfigModel.deleted_at.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    @override
    async def save(self, config: SmtpConfig) -> SmtpConfig:
        result = await self._session.execute(
            select(SmtpConfigModel).where(SmtpConfigModel.id == config.id)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.smtp_host = config.smtp_host
            existing.smtp_port = config.smtp_port
            existing.smtp_username = config.smtp_username
            existing.smtp_password_encrypted = config.smtp_password_encrypted
            existing.from_email = config.from_email
            existing.from_name = config.from_name
            existing.use_tls = config.use_tls
            existing.updated_at = datetime.now(UTC)
            await self._session.flush()
            return config

        model = SmtpConfigModel(
            id=config.id,
            tenant_id=config.tenant_id,
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
            smtp_username=config.smtp_username,
            smtp_password_encrypted=config.smtp_password_encrypted,
            from_email=config.from_email,
            from_name=config.from_name,
            use_tls=config.use_tls,
        )
        self._session.add(model)
        await self._session.flush()
        return config

    @override
    async def soft_delete(self, config_id: str) -> None:
        await self._session.execute(
            update(SmtpConfigModel)
            .where(SmtpConfigModel.id == config_id)
            .values(deleted_at=datetime.now(UTC))
        )
        await self._session.flush()

    @staticmethod
    def _to_domain(row: SmtpConfigModel) -> SmtpConfig:
        return SmtpConfig(
            id=row.id,
            tenant_id=row.tenant_id,
            smtp_host=row.smtp_host,
            smtp_port=row.smtp_port,
            smtp_username=row.smtp_username,
            smtp_password_encrypted=row.smtp_password_encrypted,
            from_email=row.from_email,
            from_name=row.from_name,
            use_tls=row.use_tls,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )
