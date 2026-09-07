"""Exercise DLQ authorization with real unloaded ORM role relationships."""

from collections.abc import AsyncIterator

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.adapters.primary.web.admin_dlq_application_authority_v2 import require_admin
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import Role, User, UserRole

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("role_name", "tenant_id", "project_id", "expected_status"),
    [
        ("admin", None, None, 200),
        ("user", None, None, 403),
        ("admin", "tenant-a", None, 403),
        ("admin", None, "project-a", 403),
    ],
)
async def test_dlq_loads_roles_and_enforces_global_admin_scope(
    role_name: str,
    tenant_id: str | None,
    project_id: str | None,
    expected_status: int,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            for table in (User.__table__, Role.__table__, UserRole.__table__):
                await connection.run_sync(table.create)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            db.add(User(id="qa-user", email="qa@example.invalid", hashed_password="unused"))
            db.add(Role(id="qa-role", name=role_name))
            db.add(
                UserRole(
                    id="qa-assignment",
                    user_id="qa-user",
                    role_id="qa-role",
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
            )
            await db.commit()
        async with sessions() as db:
            current_user = (await db.execute(select(User))).scalar_one()
            assert "roles" not in current_user.__dict__

            async def user_dependency() -> User:
                return current_user

            async def db_dependency() -> AsyncIterator[AsyncSession]:
                yield db

            app = FastAPI()
            app.dependency_overrides[get_current_user] = user_dependency
            app.dependency_overrides[get_db] = db_dependency

            @app.get("/dlq-access")
            async def access(user: User = Depends(require_admin)) -> dict[str, str]:
                return {"user_id": user.id}

            async with AsyncClient(
                transport=ASGITransport(app=app, raise_app_exceptions=False),
                base_url="http://test",
            ) as client:
                response = await client.get("/dlq-access")
            assert response.status_code == expected_status, response.text
    finally:
        await engine.dispose()
