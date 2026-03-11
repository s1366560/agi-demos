"""Volcengine RTC Voice Chat API client (async, V4-signed).

Calls StartVoiceChat / StopVoiceChat on the RTC OpenAPI.
Reference: https://www.volcengine.com/docs/6348/2123348
Signing:  HMAC-SHA256 V4 (similar to AWS SigV4 but Volcengine-specific).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class VolcengineVoiceChatAPI:
    """Async client for Volcengine RTC Voice-Chat OpenAPI."""

    SERVICE = "rtc"
    REGION = "cn-north-1"
    HOST = "rtc.volcengineapi.com"
    API_VERSION = "2024-12-01"

    def __init__(self, ak: str, sk: str) -> None:
        self.ak = ak
        self.sk = sk

    # ------------------------------------------------------------------
    # V4 Signing
    # ------------------------------------------------------------------

    def _sign_v4(self, method: str, query_str: str, body: str) -> dict[str, str]:
        """Build V4-signed headers for a request.

        Args:
            method: HTTP method (POST).
            query_str: Pre-built, sorted query string.
            body: Raw JSON body string.

        Returns:
            Dict of headers to attach to the request.
        """
        now = datetime.now(tz=UTC)
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        short_date = x_date[:8]

        content_type = "application/json"
        payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()

        # Canonical headers (sorted by key)
        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{self.HOST}\n"
            f"x-content-sha256:{payload_hash}\n"
            f"x-date:{x_date}\n"
        )
        signed_headers = "content-type;host;x-content-sha256;x-date"

        canonical_request = "\n".join(
            [
                method.upper(),
                "/",
                query_str,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )

        # String to sign
        credential_scope = f"{short_date}/{self.REGION}/{self.SERVICE}/request"
        string_to_sign = "\n".join(
            [
                "HMAC-SHA256",
                x_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )

        # HMAC chain: sk -> date -> region -> service -> "request"
        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_date = _hmac(self.sk.encode("utf-8"), short_date)
        k_region = _hmac(k_date, self.REGION)
        k_service = _hmac(k_region, self.SERVICE)
        k_signing = _hmac(k_service, "request")
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization = (
            f"HMAC-SHA256 Credential={self.ak}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        return {
            "Content-Type": content_type,
            "Host": self.HOST,
            "X-Date": x_date,
            "X-Content-Sha256": payload_hash,
            "Authorization": authorization,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start_voice_chat(
        self,
        app_id: str,
        room_id: str,
        bot_user_id: str,
        model_endpoint_id: str,
        *,
        target_user_ids: list[str] | None = None,
        welcome_message: str = "你好，有什么可以帮你的吗？",
        system_messages: list[str] | None = None,
        voice_type: str = "BV001_streaming",
        asr_app_id: str | None = None,
        tts_app_id: str | None = None,
    ) -> dict[str, Any]:
        """Start an AI voice chat session via Volcengine RTC.

        Returns:
            Volcengine API response dict.
        """
        action = "StartVoiceChat"
        query_str = f"Action={action}&Version={self.API_VERSION}"

        payload: dict[str, Any] = {
            "AppId": app_id,
            "RoomId": room_id,
            "TaskId": room_id,
            "AgentConfig": {
                "TargetUserId": target_user_ids or [bot_user_id],
                "WelcomeMessage": welcome_message,
                "UserId": f"ai_bot_{bot_user_id}",
                "EnableConversationStateCallback": True,
            },
            "Config": {
                "ASRConfig": {
                    "Provider": "volcano",
                    "ProviderParams": {
                        "Mode": "smallmodel",
                        "AppId": asr_app_id or app_id,
                        "Cluster": "volcengine_streaming_common",
                    },
                },
                "LLMConfig": {
                    "Mode": "ArkV3",
                    "EndPointId": model_endpoint_id,
                    "SystemMessages": system_messages
                    or ["你是一个AI助手，用简洁友好的方式回答问题。"],
                },
                "TTSConfig": {
                    "Provider": "volcano",
                    "ProviderParams": {
                        "app": {
                            "appid": tts_app_id or app_id,
                            "cluster": "volcano_tts",
                        },
                        "audio": {
                            "voice_type": voice_type,
                            "speed_ratio": 1.0,
                        },
                    },
                },
                "InterruptMode": 0,
            },
        }

        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        headers = self._sign_v4("POST", query_str, body)
        url = f"https://{self.HOST}/?{query_str}"

        logger.info("StartVoiceChat room=%s bot=%s", room_id, bot_user_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, content=body, headers=headers)
            result: dict[str, Any] = resp.json()

        _check_response(result, action)
        return result

    async def stop_voice_chat(
        self,
        app_id: str,
        room_id: str,
        bot_user_id: str,
    ) -> dict[str, Any]:
        """Stop an AI voice chat session."""
        action = "StopVoiceChat"
        query_str = f"Action={action}&Version={self.API_VERSION}"

        payload: dict[str, Any] = {
            "AppId": app_id,
            "RoomId": room_id,
            "TaskId": room_id,
        }

        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        headers = self._sign_v4("POST", query_str, body)
        url = f"https://{self.HOST}/?{query_str}"

        logger.info("StopVoiceChat room=%s bot=%s", room_id, bot_user_id)
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, content=body, headers=headers)
            result: dict[str, Any] = resp.json()

        _check_response(result, action)
        return result


def _check_response(result: dict[str, Any], action: str) -> None:
    """Raise on Volcengine API error response."""
    meta = result.get("ResponseMetadata", {})
    error = meta.get("Error")
    if error:
        code = error.get("Code", "Unknown")
        message = error.get("Message", "")
        logger.error("%s failed: %s - %s", action, code, message)
        raise RuntimeError(f"Volcengine {action}: [{code}] {message}")
