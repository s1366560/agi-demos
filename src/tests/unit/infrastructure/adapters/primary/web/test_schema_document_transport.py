"""Malformed command transport is rejected before any runtime/database dependency."""

from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.routers.schema_documents import router

pytestmark = pytest.mark.unit
SCHEMA_ID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("token", ["-0", "0.0", "0e0", "true"])
async def test_history_requires_a_nonnegative_integer_token(token):
    app = FastAPI()
    app.include_router(router)
    raw = '{"schema_id":"' + SCHEMA_ID + '","after_revision":' + token + ',"limit":1}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/document/history", content=raw)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "project_schema_transport_invalid"


@pytest.mark.parametrize(
    "header",
    [
        "X-Expected-Revision",
        "Idempotency-Key",
        "X-Project-Schema-Expected-Revision",
        "X-Project-Schema-Change-Id",
    ],
)
@pytest.mark.parametrize("duplicate", [False, True])
async def test_body_only_transport_rejects_alternate_cas_and_idempotency_headers(header, duplicate):
    app = FastAPI()
    app.include_router(router)
    headers = [(header, "1"), (header, "2")] if duplicate else [(header, "1")]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/document/read", json={}, headers=headers)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "project_schema_transport_invalid"


async def test_oversize_chunk_is_rejected_before_buffer_copy(monkeypatch):
    from fastapi import HTTPException

    from src.infrastructure.adapters.primary.web.routers import schema_documents

    class Buffer(bytearray):
        def extend(self, _chunk):
            pytest.fail("oversize chunk copied into the request buffer")

    class Request:
        headers: ClassVar[dict[str, str]] = {}

        async def stream(self):
            yield b" " * (schema_documents.MAX_TRANSPORT_BYTES + 1)

    monkeypatch.setattr(schema_documents, "bytearray", Buffer, raising=False)
    with pytest.raises(HTTPException) as error:
        await schema_documents._body(Request())
    assert error.value.status_code == 422
