"""Interactive cloud login sessions.

Access tokens stay short-lived ``ms_sk_`` API keys. Refresh tokens are random
``ms_rt_`` secrets; only their HMAC-SHA256 digest is persisted. Reuse of a
rotated or revoked refresh token revokes the whole ``family_id``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.auth_service_v2 import AuthService
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import APIKey, UserSession

ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
_REFRESH_PREFIX = "ms_rt_"


@dataclass(frozen=True, slots=True)
class IssuedCloudLogin:
    """Plaintext credentials returned once to the caller. Never log this object."""

    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: str
    family_id: str
    auth_method: str


class RefreshRejectedError(Exception):
    """Refresh token is unknown, expired, or was already rotated."""

    def __init__(self, *, reused: bool) -> None:
        super().__init__("cloud login refresh rejected")
        self.reused = reused


def hash_refresh_token(token: str, *, secret: str) -> str:
    """Return the HMAC-SHA256 hex digest of a refresh token."""
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_refresh_token() -> str:
    return f"{_REFRESH_PREFIX}{secrets.token_hex(32)}"


def _aware(value: datetime) -> datetime:
    """SQLite tests drop timezone info; comparisons stay in UTC either way."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class CloudLoginSessionService:
    """Issue, rotate, and revoke cloud login sessions for one database transaction."""

    def __init__(self, db: AsyncSession, *, secret: str) -> None:
        if not secret:
            raise ValueError("cloud login session secret is required")
        self._db = db
        self._secret = secret

    async def bind_access_key(
        self,
        *,
        user_id: str,
        access_api_key_id: str,
        auth_method: str,
        device_label: str | None = None,
        family_id: str | None = None,
    ) -> IssuedCloudLogin:
        """Attach a new refresh token to an access key created in this transaction."""
        del auth_method
        now = datetime.now(UTC)
        access_key = await self._db.get(APIKey, access_api_key_id)
        if access_key is None or access_key.user_id != user_id:
            raise ValueError("cloud login access key is missing")
        if access_key.expires_at is None:
            access_key.expires_at = now + ACCESS_TOKEN_TTL
        access_expires_at = _aware(access_key.expires_at)
        refresh_token = _generate_refresh_token()
        session_id = str(uuid4())
        resolved_family = family_id or str(uuid4())
        self._db.add(
            UserSession(
                id=session_id,
                user_id=user_id,
                family_id=resolved_family,
                refresh_token_hash=hash_refresh_token(refresh_token, secret=self._secret),
                access_api_key_id=access_api_key_id,
                expires_at=now + REFRESH_TOKEN_TTL,
                device_label=device_label,
                created_at=now,
            )
        )
        await self._db.flush()
        return IssuedCloudLogin(
            access_token="",
            access_expires_at=access_expires_at,
            refresh_token=refresh_token,
            refresh_expires_at=now + REFRESH_TOKEN_TTL,
            session_id=session_id,
            family_id=resolved_family,
            auth_method="",
        )

    async def rotate(self, refresh_token: str) -> IssuedCloudLogin:
        """Rotate a live refresh token. Reuse of a retired token revokes its family."""
        if not refresh_token.startswith(_REFRESH_PREFIX):
            raise RefreshRejectedError(reused=False)
        digest = hash_refresh_token(refresh_token, secret=self._secret)
        statement = select(UserSession).where(UserSession.refresh_token_hash == digest)
        if self._db.bind is not None and self._db.bind.dialect.name != "sqlite":
            statement = statement.with_for_update()
        row = (await self._db.execute(refresh_select_statement(statement))).scalar_one_or_none()
        if row is None:
            raise RefreshRejectedError(reused=False)
        now = datetime.now(UTC)
        if row.revoked_at is not None or row.replaced_by is not None:
            await self.revoke_family(row.family_id, observed_at=now)
            raise RefreshRejectedError(reused=True)
        if _aware(row.expires_at) <= now:
            raise RefreshRejectedError(reused=False)

        access_key = (
            await self._db.get(APIKey, row.access_api_key_id) if row.access_api_key_id else None
        )
        if access_key is None or not access_key.is_active:
            await self.revoke_family(row.family_id, observed_at=now)
            raise RefreshRejectedError(reused=True)
        permissions = list(access_key.permissions)
        plain_key = AuthService.generate_api_key()
        new_key = APIKey(
            id=str(uuid4()),
            user_id=row.user_id,
            key_hash=AuthService.hash_api_key(plain_key),
            name="Cloud login session",
            permissions=permissions,
            expires_at=now + ACCESS_TOKEN_TTL,
            is_active=True,
            created_at=now,
        )
        self._db.add(new_key)
        if access_key is not None:
            access_key.is_active = False
        successor = await self.bind_access_key(
            user_id=row.user_id,
            access_api_key_id=new_key.id,
            auth_method="refresh",
            device_label=row.device_label,
            family_id=row.family_id,
        )
        row.revoked_at = now
        row.replaced_by = successor.session_id
        row.rotated_at = now
        await self._db.flush()
        return IssuedCloudLogin(
            access_token=plain_key,
            access_expires_at=successor.access_expires_at,
            refresh_token=successor.refresh_token,
            refresh_expires_at=successor.refresh_expires_at,
            session_id=successor.session_id,
            family_id=successor.family_id,
            auth_method="refresh",
        )

    async def revoke_family(self, family_id: str, *, observed_at: datetime | None = None) -> None:
        """Revoke every refresh in a family and deactivate its access keys."""
        now = observed_at or datetime.now(UTC)
        rows = (
            await self._db.execute(
                refresh_select_statement(
                    select(UserSession).where(UserSession.family_id == family_id)
                )
            )
        ).scalars()
        for row in rows:
            if row.revoked_at is None:
                row.revoked_at = now
            if row.access_api_key_id is None:
                continue
            access_key = await self._db.get(APIKey, row.access_api_key_id)
            if access_key is not None:
                access_key.is_active = False
        await self._db.flush()

    async def revoke_access_key(self, access_api_key_id: str) -> None:
        """Revoke every refresh family still bound to an explicitly revoked access key."""
        rows = (
            (
                await self._db.execute(
                    refresh_select_statement(
                        select(UserSession).where(
                            UserSession.access_api_key_id == access_api_key_id
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        seen: set[str] = set()
        for row in rows:
            if row.family_id in seen:
                continue
            seen.add(row.family_id)
            await self.revoke_family(row.family_id)

    async def revoke_access_token(self, access_token: str) -> None:
        """Revoke the refresh family that issued this access token, when one exists."""
        if not access_token.startswith("ms_sk_"):
            return
        digest = AuthService.hash_api_key(access_token)
        access_key = (
            await self._db.execute(
                refresh_select_statement(select(APIKey).where(APIKey.key_hash == digest))
            )
        ).scalar_one_or_none()
        if access_key is None:
            return
        session = (
            (
                await self._db.execute(
                    refresh_select_statement(
                        select(UserSession)
                        .where(UserSession.access_api_key_id == access_key.id)
                        .order_by(UserSession.created_at.desc())
                    )
                )
            )
            .scalars()
            .first()
        )
        if session is None:
            return
        await self.revoke_family(session.family_id)
