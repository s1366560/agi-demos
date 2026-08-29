"""Dedicated workload credentials for protocol-v2 data planes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2DataPlaneCredentialModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_data_plane_credential_repository_v2 import (
    PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2,
    PlatformPluginDataPlaneCredentialRepositoryV2,
    PlatformPluginDataPlaneCredentialV2Error,
)

pytestmark = pytest.mark.unit


async def test_data_plane_credential_issue_authenticate_rotate_and_revoke(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)
    repository = PlatformPluginDataPlaneCredentialRepositoryV2(db_session)

    issued = await repository.issue(
        data_plane_id="rust-server",
        actor_id="platform-admin",
        expires_at=now + timedelta(days=30),
        now=now,
    )

    assert issued.secret.startswith(PLUGIN_DATA_PLANE_CREDENTIAL_PREFIX_V2)
    assert issued.credential.data_plane_id == "rust-server"
    assert issued.credential.created_by_user_id == "platform-admin"
    assert issued.credential.key_hash != issued.secret
    assert issued.credential.key_prefix == issued.secret[:18]
    principal = await repository.authenticate(issued.secret, now=now)
    assert principal is not None
    assert principal.credential_id == issued.credential.id
    assert principal.data_plane_id == "rust-server"
    assert await repository.authenticate(f"{issued.secret}0", now=now) is None

    rotated = await repository.rotate(
        issued.credential.id,
        actor_id="platform-admin-2",
        expires_at=now + timedelta(days=60),
        now=now + timedelta(minutes=1),
    )

    assert rotated.credential.id != issued.credential.id
    assert rotated.credential.rotated_from_id == issued.credential.id
    assert issued.credential.revoked_at == now + timedelta(minutes=1)
    assert issued.credential.revoked_by_user_id == "platform-admin-2"
    assert await repository.authenticate(issued.secret, now=now + timedelta(minutes=1)) is None
    assert await repository.authenticate(rotated.secret, now=now + timedelta(minutes=1)) is not None

    revoked = await repository.revoke(
        rotated.credential.id,
        actor_id="platform-admin-3",
        now=now + timedelta(minutes=2),
    )
    repeated = await repository.revoke(
        rotated.credential.id,
        actor_id="another-admin",
        now=now + timedelta(minutes=3),
    )

    assert revoked.revoked_at is not None
    revoked_at = revoked.revoked_at.replace(tzinfo=revoked.revoked_at.tzinfo or UTC)
    assert revoked_at == now + timedelta(minutes=2)
    assert revoked.revoked_by_user_id == "platform-admin-3"
    assert repeated.revoked_at == revoked.revoked_at
    assert repeated.revoked_by_user_id == revoked.revoked_by_user_id
    assert await repository.authenticate(rotated.secret, now=now + timedelta(minutes=3)) is None


async def test_data_plane_credential_expiration_and_plane_binding(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 30, 7, 0, tzinfo=UTC)
    repository = PlatformPluginDataPlaneCredentialRepositoryV2(db_session)
    issued = await repository.issue(
        data_plane_id="desktop-sidecar",
        actor_id="platform-admin",
        expires_at=now + timedelta(seconds=1),
        now=now,
    )

    principal = await repository.authenticate(issued.secret, now=now)
    assert principal is not None
    assert principal.data_plane_id == "desktop-sidecar"
    assert await repository.authenticate(issued.secret, now=now + timedelta(seconds=1)) is None


@pytest.mark.parametrize("data_plane_id", ("", " RUST", "rust server", "UPPER"))
async def test_data_plane_credential_rejects_invalid_plane_id(
    db_session: AsyncSession,
    data_plane_id: str,
) -> None:
    repository = PlatformPluginDataPlaneCredentialRepositoryV2(db_session)

    with pytest.raises(ValueError, match="data_plane_id"):
        await repository.issue(
            data_plane_id=data_plane_id,
            actor_id="platform-admin",
        )


async def test_data_plane_credential_rejects_invalid_expiration_and_unknown_rotation(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    repository = PlatformPluginDataPlaneCredentialRepositoryV2(db_session)

    with pytest.raises(ValueError, match="expires_at"):
        await repository.issue(
            data_plane_id="rust-server",
            actor_id="platform-admin",
            expires_at=now,
            now=now,
        )
    with pytest.raises(PlatformPluginDataPlaneCredentialV2Error) as exc_info:
        await repository.rotate(
            "missing-credential",
            actor_id="platform-admin",
            now=now,
        )
    assert exc_info.value.code == "credential_not_found"


def test_data_plane_credential_model_never_exposes_plaintext_field() -> None:
    assert "secret" not in PlatformPluginV2DataPlaneCredentialModel.__table__.columns
    assert "token" not in PlatformPluginV2DataPlaneCredentialModel.__table__.columns
