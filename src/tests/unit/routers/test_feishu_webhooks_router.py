from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.routers import webhooks


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(webhooks.router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _json_body(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()


def _signature(timestamp: str, nonce: str, encrypt_key: str, body: bytes) -> str:
    return hashlib.sha256(
        timestamp.encode() + nonce.encode() + encrypt_key.encode() + body
    ).hexdigest()


def _signed_headers(body: bytes, encrypt_key: str) -> dict[str, str]:
    timestamp = "1700000000"
    nonce = "nonce-1"
    return {
        "content-type": "application/json",
        "x-lark-request-timestamp": timestamp,
        "x-lark-request-nonce": nonce,
        "x-lark-signature": _signature(timestamp, nonce, encrypt_key, body),
    }


def _message_payload(token: str = "verify-token") -> dict[str, Any]:
    return {
        "header": {"token": token, "event_type": "im.message.receive_v1"},
        "event": {
            "message": {"chat_id": "chat-1", "content": '{"text":"hello"}'},
            "sender": {"sender_id": {"open_id": "ou_1"}},
        },
    }


@pytest.mark.asyncio
async def test_feishu_webhook_fails_closed_without_verification_config(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)

    response = await client.post(
        "/api/v1/webhooks/feishu/workspace-message",
        content=_json_body(_message_payload()),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_feishu_webhook_rejects_invalid_verification_token(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify-token")
    monkeypatch.delenv("FEISHU_ENCRYPT_KEY", raising=False)

    response = await client.post(
        "/api/v1/webhooks/feishu/workspace-message",
        content=_json_body(_message_payload(token="wrong-token")),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_feishu_webhook_accepts_challenge_with_valid_token(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify-token")
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "encrypt-key")

    response = await client.post(
        "/api/v1/webhooks/feishu/workspace-message",
        json={"type": "url_verification", "token": "verify-token", "challenge": "challenge-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-1"}


@pytest.mark.asyncio
async def test_feishu_webhook_rejects_missing_signature_when_encrypt_key_configured(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "encrypt-key")

    response = await client.post(
        "/api/v1/webhooks/feishu/workspace-message",
        content=_json_body(_message_payload()),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_feishu_webhook_rejects_invalid_signature(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FEISHU_VERIFICATION_TOKEN", raising=False)
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "encrypt-key")
    body = _json_body(_message_payload())

    response = await client.post(
        "/api/v1/webhooks/feishu/workspace-message",
        content=body,
        headers={
            "content-type": "application/json",
            "x-lark-request-timestamp": "1700000000",
            "x-lark-request-nonce": "nonce-1",
            "x-lark-signature": "bad-signature",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_feishu_webhook_accepts_valid_token_and_signature(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", "verify-token")
    monkeypatch.setenv("FEISHU_ENCRYPT_KEY", "encrypt-key")
    body = _json_body(_message_payload())

    response = await client.post(
        "/api/v1/webhooks/feishu/workspace-message",
        content=body,
        headers=_signed_headers(body, "encrypt-key"),
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0, "msg": "ok"}
