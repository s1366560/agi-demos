from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.smtp.smtp_config import SmtpConfig


class SmtpConfigRepository(ABC):
    """Repository interface for SMTP configuration persistence."""

    @abstractmethod
    async def find_by_tenant(self, tenant_id: str) -> SmtpConfig | None: ...

    @abstractmethod
    async def save(self, config: SmtpConfig) -> SmtpConfig: ...

    @abstractmethod
    async def soft_delete(self, config_id: str) -> None: ...
