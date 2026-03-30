from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class SmtpConfig(Entity):
    """SMTP mail configuration for a tenant."""

    tenant_id: str
    smtp_host: str
    smtp_port: int = 587
    smtp_username: str
    smtp_password_encrypted: str
    from_email: str
    from_name: str | None = None
    use_tls: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
