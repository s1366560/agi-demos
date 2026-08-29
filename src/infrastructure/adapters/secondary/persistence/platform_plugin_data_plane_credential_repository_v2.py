"""Dedicated credential authority for protocol-v2 data-plane workloads."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from secrets import token_hex

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2DataPlaneCredentialModel,
)

PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2 = "ms_dp_"
_PLUGIN_DATA_PLANE_SECRET_HEX_LENGTH_V2 = 64
_PLUGIN_DATA_PLANE_KEY_PREFIX_LENGTH_V2 = 18
_DATA_PLANE_ID_PATTERN_V2 = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,254}$")
_SECRET_PATTERN_V2 = re.compile(
    rf"^{PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2}"
    + rf"[a-f0-9]{{{_PLUGIN_DATA_PLANE_SECRET_HEX_LENGTH_V2}}}$"
)


class PlatformPluginDataPlaneCredentialV2Error(ValueError):
    """Stable credential lifecycle conflict for V2 control-plane transports."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class PlatformPluginDataPlanePrincipalV2:
    """Authenticated workload identity derived only from a dedicated secret."""

    credential_id: str
    data_plane_id: str


@dataclass(frozen=True, kw_only=True)
class IssuedPlatformPluginDataPlaneCredentialV2:
    """One-time plaintext delivery paired with its durable hashed record."""

    secret: str = field(repr=False)
    credential: PlatformPluginV2DataPlaneCredentialModel


class PlatformPluginDataPlaneCredentialRepositoryV2:
    """Issue, rotate, revoke, list, and authenticate data-plane credentials."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def issue(
        self,
        *,
        data_plane_id: str,
        actor_id: str,
        expires_at: datetime | None = None,
        now: datetime | None = None,
        rotated_from_id: str | None = None,
    ) -> IssuedPlatformPluginDataPlaneCredentialV2:
        """Persist a fresh random secret hash and return plaintext exactly once."""
        plane_id = _validate_data_plane_id_v2(data_plane_id)
        principal_id = _validate_actor_id_v2(actor_id)
        observed_at = _utc_now_v2(now)
        normalized_expiry = _validate_expiry_v2(expires_at, observed_at)
        secret = f"{PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2}{token_hex(32)}"
        model = PlatformPluginV2DataPlaneCredentialModel(
            id=PlatformPluginV2DataPlaneCredentialModel.generate_id(),
            data_plane_id=plane_id,
            key_hash=_hash_secret_v2(secret),
            key_prefix=secret[:_PLUGIN_DATA_PLANE_KEY_PREFIX_LENGTH_V2],
            created_by_user_id=principal_id,
            created_at=observed_at,
            expires_at=normalized_expiry,
            revoked_at=None,
            revoked_by_user_id=None,
            rotated_from_id=rotated_from_id,
        )
        self._session.add(model)
        await self._session.flush()
        return IssuedPlatformPluginDataPlaneCredentialV2(
            secret=secret,
            credential=model,
        )

    async def rotate(
        self,
        credential_id: str,
        *,
        actor_id: str,
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> IssuedPlatformPluginDataPlaneCredentialV2:
        """Atomically revoke one credential and issue its bound successor."""
        observed_at = _utc_now_v2(now)
        principal_id = _validate_actor_id_v2(actor_id)
        current = await self._credential_for_update(credential_id)
        if current.revoked_at is not None:
            raise PlatformPluginDataPlaneCredentialV2Error(
                "credential_revoked",
                "plugin v2 data-plane credential is already revoked",
            )
        current.revoked_at = observed_at
        current.revoked_by_user_id = principal_id
        return await self.issue(
            data_plane_id=current.data_plane_id,
            actor_id=principal_id,
            expires_at=expires_at,
            now=observed_at,
            rotated_from_id=current.id,
        )

    async def revoke(
        self,
        credential_id: str,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> PlatformPluginV2DataPlaneCredentialModel:
        """Idempotently revoke one exact credential without deleting audit history."""
        observed_at = _utc_now_v2(now)
        principal_id = _validate_actor_id_v2(actor_id)
        credential = await self._credential_for_update(credential_id)
        if credential.revoked_at is None:
            credential.revoked_at = observed_at
            credential.revoked_by_user_id = principal_id
            await self._session.flush()
        return credential

    async def list_credentials(
        self,
        *,
        data_plane_id: str | None = None,
        limit: int = 100,
    ) -> tuple[PlatformPluginV2DataPlaneCredentialModel, ...]:
        """Return metadata only; plaintext secrets never enter the model."""
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("plugin v2 data-plane credential limit must be between 1 and 1000")
        statement = select(PlatformPluginV2DataPlaneCredentialModel)
        if data_plane_id is not None:
            statement = statement.where(
                PlatformPluginV2DataPlaneCredentialModel.data_plane_id
                == _validate_data_plane_id_v2(data_plane_id)
            )
        result = await self._session.execute(
            refresh_select_statement(
                statement.order_by(
                    PlatformPluginV2DataPlaneCredentialModel.created_at.desc(),
                    PlatformPluginV2DataPlaneCredentialModel.id.desc(),
                ).limit(limit)
            )
        )
        return tuple(result.scalars())

    async def authenticate(
        self,
        secret: object,
        *,
        now: datetime | None = None,
    ) -> PlatformPluginDataPlanePrincipalV2 | None:
        """Resolve an active credential to its immutable plane binding."""
        if not isinstance(secret, str) or _SECRET_PATTERN_V2.fullmatch(secret) is None:
            return None
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2DataPlaneCredentialModel).where(
                    PlatformPluginV2DataPlaneCredentialModel.key_hash == _hash_secret_v2(secret)
                )
            )
        )
        credential = result.scalar_one_or_none()
        if credential is None or credential.revoked_at is not None:
            return None
        observed_at = _utc_now_v2(now)
        expires_at = _database_datetime_utc_v2(credential.expires_at)
        if expires_at is not None and expires_at <= observed_at:
            return None
        return PlatformPluginDataPlanePrincipalV2(
            credential_id=credential.id,
            data_plane_id=credential.data_plane_id,
        )

    async def _credential_for_update(
        self,
        credential_id: object,
    ) -> PlatformPluginV2DataPlaneCredentialModel:
        if not isinstance(credential_id, str) or not credential_id.strip():
            raise PlatformPluginDataPlaneCredentialV2Error(
                "credential_not_found",
                "plugin v2 data-plane credential is unknown",
            )
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2DataPlaneCredentialModel)
                .where(PlatformPluginV2DataPlaneCredentialModel.id == credential_id)
                .with_for_update()
            )
        )
        credential = result.scalar_one_or_none()
        if credential is None:
            raise PlatformPluginDataPlaneCredentialV2Error(
                "credential_not_found",
                "plugin v2 data-plane credential is unknown",
            )
        return credential


def _hash_secret_v2(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _validate_data_plane_id_v2(data_plane_id: object) -> str:
    if (
        not isinstance(data_plane_id, str)
        or _DATA_PLANE_ID_PATTERN_V2.fullmatch(data_plane_id) is None
    ):
        raise ValueError("invalid plugin v2 data_plane_id")
    return data_plane_id


def _validate_actor_id_v2(actor_id: object) -> str:
    if not isinstance(actor_id, str) or not actor_id.strip() or len(actor_id) > 255:
        raise ValueError("plugin v2 credential actor_id must be a non-empty string")
    return actor_id


def _validate_expiry_v2(expires_at: datetime | None, now: datetime) -> datetime | None:
    normalized = _database_datetime_utc_v2(expires_at)
    if normalized is not None and normalized <= now:
        raise ValueError("plugin v2 credential expires_at must be later than creation time")
    return normalized


def _database_datetime_utc_v2(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _utc_now_v2(now: datetime | None) -> datetime:
    resolved = now or datetime.now(UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("plugin v2 credential time must include a timezone")
    return resolved.astimezone(UTC)


__all__ = [
    "PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2",
    "IssuedPlatformPluginDataPlaneCredentialV2",
    "PlatformPluginDataPlaneCredentialRepositoryV2",
    "PlatformPluginDataPlaneCredentialV2Error",
    "PlatformPluginDataPlanePrincipalV2",
]
