from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/api/v1/webhooks/feishu/workspace-message")
async def feishu_workspace_message(request: Request) -> JSONResponse:
    body: dict[str, Any] = await request.json()

    if "challenge" in body:
        return JSONResponse({"challenge": body["challenge"]})

    event: dict[str, Any] = body.get("event", {})
    message: dict[str, Any] = event.get("message", {})
    sender: dict[str, Any] = event.get("sender", {})

    chat_id: str = message.get("chat_id", "")
    sender_open_id: str = sender.get("sender_id", {}).get("open_id", "")

    # Feishu encodes message.content as a JSON string with a "text" field
    raw_content: str = message.get("content", "{}")
    try:
        content_data = json.loads(raw_content)
        content: str = content_data.get("text", raw_content)
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
        from memstack_agent.plugins.feishu.plugin import (  # type: ignore[import-not-found]
            handle_message_event,
        )

        await handle_message_event(chat_id, sender_open_id, content)
    except ImportError:
        logger.debug("Feishu plugin not installed, message logged but not processed")

    return JSONResponse({"code": 0, "msg": "ok"})
