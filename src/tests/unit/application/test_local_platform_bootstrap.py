"""Local bootstrap safety: reject remote targets and never elevate existing users."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.auth_service_v2 import AuthService
from src.application.use_cases.auth.bootstrap_local_platform_administrator import (
    BootstrapLocalPlatformAdministrator,
    LocalPlatformAdministrator,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.sql_local_platform_administrator_repository import (
    SqlLocalPlatformAdministratorRepository,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("environment", "database_host", "api_host"),
    [
        ("production", "localhost", "localhost"),
        ("development", "db.remote", "localhost"),
        ("development", "localhost", "api.remote"),
    ],
)
async def test_bootstrap_rejects_nonlocal_target_without_writes(
    environment: str, database_host: str, api_host: str
) -> None:
    repository = AsyncMock()
    use_case = BootstrapLocalPlatformAdministrator(
        repository=repository,
        hash_password=lambda _: "unused",
        environment=environment,
        database_host=database_host,
        api_host=api_host,
    )
    with pytest.raises(ValueError, match="requires"):
        await use_case.execute(email="bootstrap@localhost.invalid", password="a" * 48)
    repository.create_new.assert_not_awaited()


@pytest.mark.unit
async def test_bootstrap_creates_and_retires_only_its_new_identity(test_db: AsyncSession) -> None:
    use_case = BootstrapLocalPlatformAdministrator(
        repository=SqlLocalPlatformAdministratorRepository(test_db),
        hash_password=AuthService.get_password_hash,
        environment="development",
        database_host="127.0.0.1",
        api_host="localhost",
    )
    identity = await use_case.execute(email="new-admin@localhost.invalid", password="a" * 48)
    row = await test_db.scalar(select(User).where(User.id == identity.user_id))
    assert row is not None and row.is_superuser and row.is_active
    assert AuthService.verify_password("a" * 48, row.hashed_password)
    assert row.profile["local_platform_bootstrap_id"] == identity.bootstrap_id
    await use_case.deactivate(identity)
    assert not row.is_active


@pytest.mark.unit
async def test_bootstrap_never_elevates_existing_tenant_user(
    test_db: AsyncSession, test_user: User
) -> None:
    repository = SqlLocalPlatformAdministratorRepository(test_db)
    with pytest.raises(ValueError, match="existing identity"):
        await repository.create_new(
            identity=LocalPlatformAdministrator(
                user_id="new-id", email=test_user.email.upper(), bootstrap_id="new-bootstrap"
            ),
            password_hash="unused",
        )
    await test_db.refresh(test_user)
    assert not test_user.is_superuser
    assert await test_db.scalar(select(User.id).where(User.id == "new-id")) is None
    with pytest.raises(ValueError, match="not owned"):
        await repository.deactivate_created(
            LocalPlatformAdministrator(
                user_id=test_user.id, email=test_user.email, bootstrap_id="new-bootstrap"
            )
        )
    assert test_user.is_active
