from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.infrastructure.i18n import gettext as _

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

_FEISHU_VERIFICATION_TOKEN_ENV = "FEISHU_VERIFICATION_TOKEN"
_FEISHU_ENCRYPT_KEY_ENV = "FEISHU_ENCRYPT_KEY"


def _dict_value(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _string_value(source: dict[str, Any], key: str, default: str = "") -> str:
    value = source.get(key)
    return value if isinstance(value, str) else default


def _extract_verification_token(body: dict[str, Any]) -> str | None:
    header = _dict_value(body, "header")
    token = _string_value(header, "token")
    if token:
        return token

    event_header = _dict_value(_dict_value(body, "event"), "header")
    token = _string_value(event_header, "token")
    if token:
        return token

    token = _string_value(body, "token")
    return token or None


def _verify_feishu_token(body: dict[str, Any], expected_token: str) -> None:
    if not hmac.compare_digest(_extract_verification_token(body) or "", expected_token):
        logger.warning("Rejected Feishu webhook with invalid verification token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_("Invalid Feishu webhook verification token"),
        )


def _verify_feishu_signature(request: Request, raw_body: bytes, encrypt_key: str) -> None:
    timestamp = request.headers.get("X-Lark-Request-Timestamp")
    nonce = request.headers.get("X-Lark-Request-Nonce")
    signature = request.headers.get("X-Lark-Signature")
    if not timestamp or not nonce or not signature:
        logger.warning("Rejected Feishu webhook with missing signature headers")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_("Missing Feishu webhook signature"),
        )

    expected = hashlib.sha256(
        timestamp.encode() + nonce.encode() + encrypt_key.encode() + raw_body
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        logger.warning("Rejected Feishu webhook with invalid signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_("Invalid Feishu webhook signature"),
        )


def _is_url_verification(body: dict[str, Any]) -> bool:
    return "challenge" in body or body.get("type") == "url_verification"


def _verify_feishu_webhook_request(
    request: Request,
    raw_body: bytes,
    body: dict[str, Any],
) -> None:
    verification_token = os.getenv(_FEISHU_VERIFICATION_TOKEN_ENV)
    encrypt_key = os.getenv(_FEISHU_ENCRYPT_KEY_ENV)

    if not verification_token and not encrypt_key:
        logger.error("Feishu webhook received but no verification secret is configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_("Feishu webhook verification is not configured"),
        )

    if verification_token:
        _verify_feishu_token(body, verification_token)
        if _is_url_verification(body):
            return

    if encrypt_key:
        _verify_feishu_signature(request, raw_body, encrypt_key)


@router.post("/api/v1/webhooks/feishu/workspace-message")
async def feishu_workspace_message(request: Request) -> JSONResponse:
    raw_body = await request.body()
    try:
        decoded_body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid Feishu webhook JSON payload"),
        ) from exc
    if not isinstance(decoded_body, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Invalid Feishu webhook JSON payload"),
        )
    body = cast(dict[str, Any], decoded_body)

    _verify_feishu_webhook_request(request, raw_body, body)

    if "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})

    event = _dict_value(body, "event")
    message = _dict_value(event, "message")
    sender = _dict_value(event, "sender")

    chat_id = _string_value(message, "chat_id")
    sender_open_id = _string_value(_dict_value(sender, "sender_id"), "open_id")

    # Feishu encodes message.content as a JSON string with a "text" field
    raw_content = _string_value(message, "content", "{}")
    try:
        decoded_content = json.loads(raw_content)
        content = (
            _string_value(cast(dict[str, Any], decoded_content), "text", raw_content)
            if isinstance(decoded_content, dict)
            else raw_content
        )
    except (json.JSONDecodeError, TypeError):
        content = raw_content

    if not chat_id or not content:
        return JSONResponse({"code": 0, "msg": "ignored: missing chat_id or content"})

    logger.info(
        "Feishu message received: chat_id=%s sender=%s content_length=%d",
        chat_id,
        sender_open_id,
        len(content),
    )

    try:
        raw_handle_message_event: Any
        from memstack_agent.plugins.feishu.plugin import (  # pyright: ignore[reportMissingImports]
            handle_message_event as raw_handle_message_event,  # pyright: ignore[reportUnknownVariableType]
        )

        handle_message_event = cast(
            Callable[[str, str, str], Awaitable[None]],
            raw_handle_message_event,
        )
        await handle_message_event(chat_id, sender_open_id, content)
    except ImportError:
        logger.debug("Feishu plugin not installed, message logged but not processed")

    return JSONResponse({"code": 0, "msg": "ok"})
