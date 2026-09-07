"""HTTP/SQLAlchemy half of the Rust driver's private-schema HITL recovery test."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.adapters.primary.web.routers.agent import hitl as hitl_router


async def answer_pending_request(schema: str, request_id: str, kind: str) -> None:
    """Use the production V2 handler and real SQL claim; isolate auth and delivery."""
    if not schema.startswith("qa_cron_driver_") or not schema.replace("_", "").isalnum():
        raise ValueError("private cron driver schema required")
    if kind not in {"clarification", "decision"}:
        raise ValueError("ordinary HITL kind required")
    url = make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    async def user_dependency() -> SimpleNamespace:
        return SimpleNamespace(id="actor")

    async def tenant_dependency() -> str:
        return "tenant"

    app = FastAPI()
    app.include_router(hitl_router.router, prefix="/api/v1/agent/hitl")
    app.dependency_overrides[hitl_router.get_db] = session_dependency
    app.dependency_overrides[hitl_router.get_current_user] = user_dependency
    app.dependency_overrides[hitl_router.get_current_user_tenant] = tenant_dependency
    field = "answer" if kind == "clarification" else "decision"
    body = {
        "request_id": request_id,
        "hitl_type": kind,
        "response_data": {field: "  exact 中文 answer  "},
        "contract_version": 2,
        "expected_revision": 1,
        "idempotency_key": f"answer-{request_id}",
    }
    try:
        with patch.object(
            hitl_router, "_publish_hitl_response_to_redis", new=AsyncMock(return_value=False)
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://private-hitl.test"
            ) as client:
                first = await client.post("/api/v1/agent/hitl/respond", json=body)
                replay = await client.post("/api/v1/agent/hitl/respond", json=body)
                conflict = await client.post(
                    "/api/v1/agent/hitl/respond",
                    json={**body, "response_data": {field: "different answer"}},
                )
        assert first.status_code == 200, first.text
        assert replay.status_code == 200, replay.text
        assert conflict.status_code == 409, conflict.text
        print(json.dumps({"answered": True, "replay_checked": True, "conflict_checked": True}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(answer_pending_request(*sys.argv[1:]))
