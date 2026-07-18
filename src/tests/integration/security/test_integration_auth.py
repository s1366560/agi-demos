from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.configuration.config import get_settings
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import create_user
from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import User

app = create_app()


@pytest.fixture
async def integration_db_override():
    settings = get_settings()
    # Create a fresh engine for this test function to ensure clean loop binding
    engine = create_async_engine(settings.postgres_url)
    TestingSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db():
        async with TestingSessionLocal() as session:
            yield session

    yield _get_db

    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_flow(integration_db_override):
    app.dependency_overrides[get_db] = integration_db_override
    try:
        # Ensure test user is fresh
        test_email = f"integration_test_admin_{uuid4().hex}@memstack.ai"
        async for session in integration_db_override():
            # Ensure test user is fresh
            result = await session.execute(select(User).where(User.email == test_email))
            user = result.scalar_one_or_none()
            if user:
                await session.delete(user)
                await session.commit()

            user = await create_user(
                session,
                email=test_email,
                name="Integration Test User",
                password="admin123",
            )
            await session.commit()
            break  # Only need one session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Test Login (POST /auth/token)
            print("\n1. Testing Login (POST /auth/token)...")
            login_data = {"username": test_email, "password": "admin123"}

            response = await client.post("/api/v1/auth/token", data=login_data)

            if response.status_code != 200:
                pytest.fail(f"❌ Login failed: {response.status_code} - {response.text}")

            token_data = response.json()
            access_token = token_data.get("access_token")
            token_type = token_data.get("token_type")

            assert access_token is not None

            print(f"✅ Login successful! Token type: {token_type}")

            # 2. Test Get Current User (GET /auth/me)
            print("\n2. Testing Get User (GET /auth/me)...")
            headers = {"Authorization": f"Bearer {access_token}"}

            response = await client.get("/api/v1/users/me", headers=headers)

            if response.status_code != 200:
                pytest.fail(f"❌ Get User failed: {response.status_code} - {response.text}")

            user_data = response.json()
            print("✅ Get User successful!")

            assert user_data.get("email") == test_email
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_key_routes_persist_created_key(integration_db_override):
    app.dependency_overrides[get_db] = integration_db_override
    try:
        test_email = f"integration_test_keys_{uuid4().hex}@memstack.ai"
        async for session in integration_db_override():
            result = await session.execute(select(User).where(User.email == test_email))
            user = result.scalar_one_or_none()
            if user:
                await session.delete(user)
                await session.commit()

            user = await create_user(
                session,
                email=test_email,
                name="Integration Key Test User",
                password="admin123",
            )
            await session.commit()
            break

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login_response = await client.post(
                "/api/v1/auth/token",
                data={"username": test_email, "password": "admin123"},
            )
            assert login_response.status_code == 200
            access_token = login_response.json()["access_token"]
            headers = {"Authorization": f"Bearer {access_token}"}

            create_response = await client.post(
                "/api/v1/auth/keys",
                headers=headers,
                json={"name": "Route Key", "permissions": ["read", "write"]},
            )
            assert create_response.status_code == 200
            created_key = create_response.json()
            assert created_key["key"].startswith("ms_sk_")

            api_key_headers = {"Authorization": f"Bearer {created_key['key']}"}
            auth_me_response = await client.get("/api/v1/auth/me", headers=api_key_headers)
            assert auth_me_response.status_code == 200
            assert auth_me_response.json()["email"] == test_email

            list_response = await client.get("/api/v1/auth/keys", headers=headers)
            assert list_response.status_code == 200
            assert any(
                api_key["key_id"] == created_key["key_id"] for api_key in list_response.json()
            )

            delete_response = await client.delete(
                f"/api/v1/auth/keys/{created_key['key_id']}",
                headers=headers,
            )
            assert delete_response.status_code == 204

            list_after_delete_response = await client.get("/api/v1/auth/keys", headers=headers)
            assert list_after_delete_response.status_code == 200
            assert not any(
                api_key["key_id"] == created_key["key_id"]
                for api_key in list_after_delete_response.json()
            )
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_signout_revokes_only_authorization_bearer_and_is_idempotent(
    integration_db_override,
):
    app.dependency_overrides[get_db] = integration_db_override
    try:
        test_email = f"integration_test_signout_{uuid4().hex}@memstack.ai"
        async for session in integration_db_override():
            await create_user(
                session,
                email=test_email,
                name="Integration Signout Test User",
                password="admin123",
            )
            await session.commit()
            break

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:

            async def login() -> str:
                response = await client.post(
                    "/api/v1/auth/token",
                    data={"username": test_email, "password": "admin123"},
                )
                assert response.status_code == 200
                return str(response.json()["access_token"])

            current_token = await login()
            other_token = await login()
            current_headers = {"Authorization": f"Bearer {current_token}"}
            other_headers = {"Authorization": f"Bearer {other_token}"}

            signout_response = await client.post(
                "/api/v1/auth/signout",
                headers=current_headers,
                json={"token": other_token},
            )

            assert signout_response.status_code == 200
            assert signout_response.json() == {"success": True}
            assert (await client.get("/api/v1/auth/me", headers=current_headers)).status_code == 401
            assert (await client.get("/api/v1/auth/me", headers=other_headers)).status_code == 200

            repeated_response = await client.post(
                "/api/v1/auth/signout",
                headers=current_headers,
                json={"token": other_token},
            )
            assert repeated_response.status_code == 200
            assert repeated_response.json() == {"success": True}
            assert (await client.get("/api/v1/auth/me", headers=other_headers)).status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_device_cancel_revokes_bound_token_and_rejects_caller_token(
    integration_db_override,
):
    app.dependency_overrides[get_db] = integration_db_override
    try:
        test_email = f"integration_test_device_cancel_{uuid4().hex}@memstack.ai"
        async for session in integration_db_override():
            await create_user(
                session,
                email=test_email,
                name="Integration Device Cancel Test User",
                password="admin123",
            )
            await session.commit()
            break

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            login_response = await client.post(
                "/api/v1/auth/token",
                data={"username": test_email, "password": "admin123"},
            )
            assert login_response.status_code == 200
            login_token = str(login_response.json()["access_token"])
            login_headers = {"Authorization": f"Bearer {login_token}"}

            code_response = await client.post("/api/v1/auth/device/code", json={})
            assert code_response.status_code == 200
            grant = code_response.json()
            approve_response = await client.post(
                "/api/v1/auth/device/approve",
                headers=login_headers,
                json={"user_code": grant["user_code"]},
            )
            assert approve_response.status_code == 200

            token_response = await client.post(
                "/api/v1/auth/device/token",
                json={"device_code": grant["device_code"]},
            )
            assert token_response.status_code == 200
            device_token = str(token_response.json()["access_token"])
            device_headers = {"Authorization": f"Bearer {device_token}"}
            assert (await client.get("/api/v1/auth/me", headers=device_headers)).status_code == 200

            rejected_cancel = await client.post(
                "/api/v1/auth/device/cancel",
                json={
                    "device_code": grant["device_code"],
                    "access_token": login_token,
                },
            )
            assert rejected_cancel.status_code == 422
            assert (await client.get("/api/v1/auth/me", headers=device_headers)).status_code == 200
            assert (await client.get("/api/v1/auth/me", headers=login_headers)).status_code == 200

            cancel_response = await client.post(
                "/api/v1/auth/device/cancel",
                json={"device_code": grant["device_code"]},
            )
            assert cancel_response.status_code == 200
            assert cancel_response.json() == {"success": True}
            assert (await client.get("/api/v1/auth/me", headers=device_headers)).status_code == 401
            assert (await client.get("/api/v1/auth/me", headers=login_headers)).status_code == 200

            repeated_cancel = await client.post(
                "/api/v1/auth/device/cancel",
                json={"device_code": grant["device_code"]},
            )
            assert repeated_cancel.status_code == 200
            assert repeated_cancel.json() == {"success": True}

            pending_response = await client.post("/api/v1/auth/device/code", json={})
            assert pending_response.status_code == 200
            pending_grant = pending_response.json()
            assert (
                await client.post(
                    "/api/v1/auth/device/cancel",
                    json={"device_code": pending_grant["device_code"]},
                )
            ).status_code == 200
            expired_response = await client.post(
                "/api/v1/auth/device/token",
                json={"device_code": pending_grant["device_code"]},
            )
            assert expired_response.status_code == 410
    finally:
        app.dependency_overrides.pop(get_db, None)
