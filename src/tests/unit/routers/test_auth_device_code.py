import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.adapters.primary.web.routers import auth as auth_router
from src.infrastructure.adapters.primary.web.routers.auth import DeviceCodeCancelRequest


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def exists(self, key: str) -> int:
        return int(key in self.values)

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.values[key] = value
        self.ttls[key] = ttl
        return True

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            deleted += int(self.values.pop(key, None) is not None)
            self.ttls.pop(key, None)
        return deleted

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def eval(self, script: str, numkeys: int, *args: object) -> int:
        if numkeys == 1:
            key, owner = str(args[0]), str(args[1])
            if self.values.get(key) != owner:
                return 0
            await self.delete(key)
            return 1

        keys = [str(arg) for arg in args[:numkeys]]
        values = [str(arg) for arg in args[numkeys:]]
        lock_key, device_key = keys[:2]
        owner, expected = values[:2]
        if "return -1" in script and self.values.get(lock_key) != owner:
            return -1
        if self.values.get(lock_key) != owner or self.values.get(device_key) != expected:
            return 0

        if "KEEPTTL" in script:
            replacement, device_code = values[2:4]
            self.values[device_key] = replacement
            if numkeys == 3 and self.values.get(keys[2]) == device_code:
                await self.delete(keys[2])
            return 1

        device_code = values[2]
        await self.delete(device_key)
        if self.values.get(keys[2]) == device_code:
            await self.delete(keys[2])
        return 1


def _grant(*, status: str, access_token: str | None = None) -> dict[str, object]:
    return {
        "user_code": "ABCD2345",
        "status": status,
        "approved_user_id": "user-1" if access_token else None,
        "access_token": access_token,
    }


@pytest.fixture
def device_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    redis = _FakeRedis()

    async def get_redis_client() -> _FakeRedis:
        return redis

    monkeypatch.setattr(
        "src.infrastructure.agent.state.agent_worker_state.get_redis_client",
        get_redis_client,
    )
    return redis


@pytest.mark.unit
async def test_device_token_retains_consumed_grant_until_client_cleanup(
    device_redis: _FakeRedis,
) -> None:
    device_code = "device-secret"
    device_key = auth_router._device_key(device_code)
    user_key = auth_router._user_code_key("ABCD2345")
    device_redis.values[device_key] = json.dumps(
        _grant(status="approved", access_token="ms_sk_server_bound")
    )
    device_redis.values[user_key] = device_code
    device_redis.ttls[device_key] = 300

    response = await auth_router.device_code_token({"device_code": device_code})

    assert response == {"access_token": "ms_sk_server_bound", "token_type": "bearer"}
    retained = json.loads(device_redis.values[device_key])
    assert retained["status"] == "consumed"
    assert retained["access_token"] == "ms_sk_server_bound"
    assert user_key not in device_redis.values


@pytest.mark.unit
async def test_device_token_does_not_return_grant_lost_to_cross_backend_cancel(
    monkeypatch: pytest.MonkeyPatch,
    device_redis: _FakeRedis,
) -> None:
    device_code = "device-secret"
    device_key = auth_router._device_key(device_code)
    user_key = auth_router._user_code_key("ABCD2345")
    device_redis.values[device_key] = json.dumps(
        _grant(status="approved", access_token="ms_sk_server_bound")
    )
    device_redis.values[user_key] = device_code

    async def lose_to_cancel(*_args: object, **_kwargs: object) -> bool:
        await device_redis.delete(device_key, user_key)
        return False

    monkeypatch.setattr(auth_router, "_compare_and_set_device_grant", lose_to_cancel)

    with pytest.raises(auth_router.HTTPException) as raised:
        await auth_router.device_code_token({"device_code": device_code})

    assert raised.value.status_code == 410
    assert device_key not in device_redis.values


@pytest.mark.unit
async def test_device_cancel_revokes_only_server_bound_token_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    device_redis: _FakeRedis,
) -> None:
    device_code = "device-secret"
    device_key = auth_router._device_key(device_code)
    user_key = auth_router._user_code_key("ABCD2345")
    device_redis.values[device_key] = json.dumps(
        _grant(status="consumed", access_token="ms_sk_server_bound")
    )
    device_redis.values[user_key] = device_code
    revoked_hashes: list[str] = []

    class Repository:
        def __init__(self, _db: object) -> None:
            pass

        async def delete_by_hash(self, key_hash: str) -> None:
            revoked_hashes.append(key_hash)

    monkeypatch.setattr(auth_router, "SqlAPIKeyRepository", Repository)
    db = SimpleNamespace(commit=AsyncMock())
    request = DeviceCodeCancelRequest(device_code=device_code)

    assert await auth_router.device_code_cancel(request, db) == {"success": True}
    assert revoked_hashes == [auth_router.hash_api_key("ms_sk_server_bound")]
    assert device_key not in device_redis.values
    assert user_key not in device_redis.values
    db.commit.assert_awaited_once()

    assert await auth_router.device_code_cancel(request, db) == {"success": True}
    assert revoked_hashes == [auth_router.hash_api_key("ms_sk_server_bound")]


@pytest.mark.unit
async def test_pending_cancel_reloads_grant_when_cross_backend_approval_wins(
    monkeypatch: pytest.MonkeyPatch,
    device_redis: _FakeRedis,
) -> None:
    device_code = "device-secret"
    device_key = auth_router._device_key(device_code)
    user_key = auth_router._user_code_key("ABCD2345")
    device_redis.values[device_key] = json.dumps(_grant(status="pending"))
    device_redis.values[user_key] = device_code
    revoked_hashes: list[str] = []

    class Repository:
        def __init__(self, _db: object) -> None:
            pass

        async def delete_by_hash(self, key_hash: str) -> None:
            revoked_hashes.append(key_hash)

    original_delete = auth_router._compare_and_delete_device_grant
    first_delete = True

    async def approval_wins_first_delete(*args: object, **kwargs: object) -> int:
        nonlocal first_delete
        if first_delete:
            first_delete = False
            device_redis.values[device_key] = json.dumps(
                _grant(status="approved", access_token="ms_sk_racing_approval")
            )
            return 0
        return await original_delete(*args, **kwargs)

    monkeypatch.setattr(auth_router, "SqlAPIKeyRepository", Repository)
    monkeypatch.setattr(
        auth_router,
        "_compare_and_delete_device_grant",
        approval_wins_first_delete,
    )
    db = SimpleNamespace(commit=AsyncMock())

    assert await auth_router.device_code_cancel(
        DeviceCodeCancelRequest(device_code=device_code),
        db,
    ) == {"success": True}
    assert revoked_hashes == [auth_router.hash_api_key("ms_sk_racing_approval")]
    assert device_key not in device_redis.values
    assert user_key not in device_redis.values


@pytest.mark.unit
async def test_device_cancel_serializes_with_approval_and_revokes_racing_key(
    monkeypatch: pytest.MonkeyPatch,
    device_redis: _FakeRedis,
) -> None:
    device_code = "device-secret"
    device_key = auth_router._device_key(device_code)
    user_key = auth_router._user_code_key("ABCD2345")
    device_redis.values[device_key] = json.dumps(_grant(status="pending"))
    device_redis.values[user_key] = device_code
    device_redis.ttls[device_key] = 300
    create_started = asyncio.Event()
    allow_create = asyncio.Event()
    revoked_hashes: list[str] = []

    async def create_api_key(*_args: object, **_kwargs: object) -> tuple[str, None]:
        create_started.set()
        await allow_create.wait()
        return "ms_sk_racing_approval", None

    class Repository:
        def __init__(self, _db: object) -> None:
            pass

        async def delete_by_hash(self, key_hash: str) -> None:
            revoked_hashes.append(key_hash)

    monkeypatch.setattr(auth_router, "create_api_key", create_api_key)
    monkeypatch.setattr(auth_router, "SqlAPIKeyRepository", Repository)
    role_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=list))
    db = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
        execute=AsyncMock(return_value=role_result),
    )
    current_user = SimpleNamespace(id="user-1")

    approve_task = asyncio.create_task(
        auth_router.device_code_approve(
            {"user_code": "ABCD2345"},
            current_user=current_user,
            db=db,
        )
    )
    await create_started.wait()
    cancel_task = asyncio.create_task(
        auth_router.device_code_cancel(DeviceCodeCancelRequest(device_code=device_code), db)
    )
    await asyncio.sleep(0)
    assert not cancel_task.done()

    allow_create.set()

    assert await approve_task == {"status": "approved"}
    assert await cancel_task == {"success": True}
    assert revoked_hashes == [auth_router.hash_api_key("ms_sk_racing_approval")]
    assert device_key not in device_redis.values
    assert user_key not in device_redis.values


@pytest.mark.unit
async def test_device_approval_cannot_republish_after_lock_expiry_and_cancel(
    monkeypatch: pytest.MonkeyPatch,
    device_redis: _FakeRedis,
) -> None:
    device_code = "device-secret"
    device_key = auth_router._device_key(device_code)
    user_key = auth_router._user_code_key("ABCD2345")
    device_redis.values[device_key] = json.dumps(_grant(status="pending"))
    device_redis.values[user_key] = device_code
    device_redis.ttls[device_key] = 300
    create_started = asyncio.Event()
    allow_create = asyncio.Event()

    async def create_api_key(*_args: object, **_kwargs: object) -> tuple[str, None]:
        create_started.set()
        await allow_create.wait()
        return "ms_sk_expired_lock_approval", None

    revoked_hashes: list[str] = []

    class Repository:
        def __init__(self, _db: object) -> None:
            pass

        async def delete_by_hash(self, key_hash: str) -> None:
            revoked_hashes.append(key_hash)

    monkeypatch.setattr(auth_router, "create_api_key", create_api_key)
    monkeypatch.setattr(auth_router, "SqlAPIKeyRepository", Repository)
    role_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=list))
    db = SimpleNamespace(
        commit=AsyncMock(),
        rollback=AsyncMock(),
        execute=AsyncMock(return_value=role_result),
    )
    current_user = SimpleNamespace(id="user-1")
    approve_task = asyncio.create_task(
        auth_router.device_code_approve(
            {"user_code": "ABCD2345"},
            current_user=current_user,
            db=db,
        )
    )
    await create_started.wait()

    lock_key = f"memstack:device-lock:{auth_router.hash_api_key(device_code)}"
    await device_redis.delete(lock_key)
    assert await auth_router.device_code_cancel(
        DeviceCodeCancelRequest(device_code=device_code),
        db,
    ) == {"success": True}
    allow_create.set()

    with pytest.raises(auth_router.HTTPException) as raised:
        await approve_task
    assert raised.value.status_code == 409
    assert device_key not in device_redis.values
    assert user_key not in device_redis.values
    assert revoked_hashes == [auth_router.hash_api_key("ms_sk_expired_lock_approval")]
