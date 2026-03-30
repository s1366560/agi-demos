from __future__ import annotations

import asyncio
import base64
import logging
import smtplib
from email.mime.text import MIMEText

from src.domain.model.smtp.smtp_config import SmtpConfig
from src.domain.ports.repositories.smtp_config_repository import SmtpConfigRepository

logger = logging.getLogger(__name__)


def _encrypt_password(plaintext: str) -> str:
    return base64.b64encode(plaintext.encode()).decode()


def _decrypt_password(encrypted: str) -> str:
    return base64.b64decode(encrypted.encode()).decode()


def mask_password(encrypted: str) -> str:
    try:
        plain = _decrypt_password(encrypted)
        if len(plain) <= 3:
            return "****"
        return "****" + plain[-3:]
    except Exception:
        return "****"


class SmtpConfigService:
    def __init__(self, repo: SmtpConfigRepository) -> None:
        self._repo = repo

    async def get_config(self, tenant_id: str) -> SmtpConfig | None:
        return await self._repo.find_by_tenant(tenant_id)

    async def upsert_config(
        self,
        tenant_id: str,
        *,
        smtp_host: str,
        smtp_port: int,
        smtp_username: str,
        smtp_password: str,
        from_email: str,
        from_name: str | None,
        use_tls: bool,
    ) -> SmtpConfig:
        existing = await self._repo.find_by_tenant(tenant_id)
        encrypted_pw = _encrypt_password(smtp_password)

        if existing:
            existing.smtp_host = smtp_host
            existing.smtp_port = smtp_port
            existing.smtp_username = smtp_username
            existing.smtp_password_encrypted = encrypted_pw
            existing.from_email = from_email
            existing.from_name = from_name
            existing.use_tls = use_tls
            return await self._repo.save(existing)

        config = SmtpConfig(
            tenant_id=tenant_id,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password_encrypted=encrypted_pw,
            from_email=from_email,
            from_name=from_name,
            use_tls=use_tls,
        )
        return await self._repo.save(config)

    async def delete_config(self, config_id: str) -> None:
        await self._repo.soft_delete(config_id)

    async def test_smtp(self, tenant_id: str, recipient_email: str) -> None:
        config = await self._repo.find_by_tenant(tenant_id)
        if config is None:
            raise ValueError("SMTP configuration not found. Save configuration first.")

        password = _decrypt_password(config.smtp_password_encrypted)

        def _send() -> None:
            msg = MIMEText("This is a test email from MemStack SMTP configuration.")
            msg["Subject"] = "MemStack SMTP Test"
            msg["From"] = f"{config.from_name or 'MemStack'} <{config.from_email}>"
            msg["To"] = recipient_email

            if config.use_tls:
                server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15)
                server.starttls()
            else:
                server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15)
            server.login(config.smtp_username, password)
            server.send_message(msg)
            server.quit()

        await asyncio.to_thread(_send)
