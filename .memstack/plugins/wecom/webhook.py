"""WeCom webhook handler for processing incoming events and messages."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import xml.etree.ElementTree as ET
from base64 import b64decode, b64encode
from typing import Any, Callable

logger = logging.getLogger(__name__)

HandlerCallback = Callable[[dict[str, Any]], None]


class WeComCrypto:
    """WeCom message encryption/decryption utility."""

    # WeCom encoding AES key is 43 characters
    AES_KEY_LENGTH = 43

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str) -> None:
        self.token = token
        self.corp_id = corp_id
        if encoding_aes_key:
            try:
                self.aes_key = b64decode(encoding_aes_key + "=")
            except Exception as e:
                raise ValueError(f"Invalid encoding_aes_key: {e}")
            if len(self.aes_key) != 32:
                raise ValueError(f"Invalid AES key length: {len(self.aes_key)}")
        else:
            self.aes_key = None

    def verify_url(
        self, msg_signature: str, timestamp: str, nonce: str, echo_str: str
    ) -> str:
        """Verify URL for callback verification."""
        if not self.aes_key:
            # No encryption, just return echo_str
            return echo_str

        signature = self._sign(timestamp, nonce, echo_str)
        if signature != msg_signature:
            logger.warning(
                f"[WeComCrypto] Signature mismatch: {signature} != {msg_signature}"
            )
            return ""

        # Decrypt echo_str
        try:
            encrypted = b64decode(echo_str + "=")
            decrypted = self._decrypt(encrypted)
            # Parse XML to extract encrypt and msg_signature
            root = ET.fromstring(decrypted)
            encrypt = root.find("Encrypt").text
            return self._decrypt_msg(encrypt, timestamp, nonce)
        except Exception as e:
            logger.error(f"[WeComCrypto] Verify URL failed: {e}")
            return ""

    def decrypt_msg(
        self, msg_signature: str, timestamp: str, nonce: str, encrypted_xml: str
    ) -> dict[str, Any]:
        """Decrypt encrypted message from WeCom."""
        if not self.aes_key:
            # No encryption, parse XML directly
            return self._parse_plain_xml(encrypted_xml)

        signature = self._sign(timestamp, nonce, encrypted_xml)
        if signature != msg_signature:
            logger.warning(
                f"[WeComCrypto] Message signature mismatch: {signature} != {msg_signature}"
            )
            return {}

        try:
            root = ET.fromstring(encrypted_xml)
            encrypt = root.find("Encrypt").text
            return self._decrypt_msg(encrypt, timestamp, nonce)
        except Exception as e:
            logger.error(f"[WeComCrypto] Decrypt message failed: {e}")
            return {}

    def encrypt_msg(self, reply_msg: str, nonce: str, timestamp: str | None = None) -> str:
        """Encrypt message to send back to WeCom."""
        if not self.aes_key:
            # No encryption
            return reply_msg

        if timestamp is None:
            import time
            timestamp = str(int(time.time()))

        # Encrypt the message
        encrypt = self._encrypt(reply_msg)
        signature = self._sign(timestamp, nonce, encrypt)

        # Build XML response
        xml = f"""<xml>
<Encrypt><![CDATA[{encrypt}]]></Encrypt>
<MsgSignature><![CDATA[{signature}]]></MsgSignature>
<TimeStamp>{timestamp}</TimeStamp>
<Nonce><![CDATA[{nonce}]]></Nonce>
</xml>"""
        return xml

    def _sign(self, timestamp: str, nonce: str, data: str = "") -> str:
        """Generate signature."""
        params = sorted([self.token, timestamp, nonce, data])
        joined = "".join(params)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()

    def _encrypt(self, text: str) -> str:
        """Encrypt text using AES."""
        import random
        import struct
        import os

        # Random 16 bytes
        random_str = os.urandom(16)
        # Length of text as 4 bytes
        length = struct.pack("I", len(text))
        # Corp_id
        corp_id_bytes = self.corp_id.encode("utf-8")
        # Pad to multiple of 32 bytes
        text_bytes = (random_str + length + text.encode("utf-8") + corp_id_bytes)
        pad_len = 32 - (len(text_bytes) % 32)
        text_bytes += bytes([pad_len] * pad_len)

        # Encrypt using AES-256-CBC
        from Cryptodome.Cipher import AES

        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        encrypted = cipher.encrypt(text_bytes)
        return b64encode(encrypted).decode("utf-8")

    def _decrypt(self, encrypted: bytes) -> str:
        """Decrypt encrypted data."""
        from Cryptodome.Cipher import AES

        cipher = AES.new(self.aes_key, AES.MODE_CBC, self.aes_key[:16])
        decrypted = cipher.decrypt(encrypted)
        # Remove padding
        pad = decrypted[-1]
        content = decrypted[16:-pad]
        # Extract length and text
        length = int.from_bytes(content[:4], "big")
        text = content[4 : 4 + length].decode("utf-8")
        return text

    def _decrypt_msg(
        self, encrypt: str, timestamp: str, nonce: str
    ) -> dict[str, Any]:
        """Decrypt and parse encrypted message."""
        encrypted = b64decode(encrypt + "=")
        xml = self._decrypt(encrypted)
        root = ET.fromstring(xml)

        # Extract fields
        result: dict[str, Any] = {}
        for child in root:
            result[child.tag.lower()] = child.text

        # Verify corp_id
        if result.get("touser") != self.corp_id:
            logger.warning(
                f"[WeComCrypto] CorpID mismatch: {result.get('touser')} != {self.corp_id}"
            )

        return result

    def _parse_plain_xml(self, xml: str) -> dict[str, Any]:
        """Parse plain (non-encrypted) XML message."""
        try:
            root = ET.fromstring(xml)
            result: dict[str, Any] = {}
            for child in root:
                tag = child.tag.lower()
                if tag == "createtime":
                    result[tag] = int(child.text or "0")
                elif tag == "msgid":
                    result[tag] = child.text
                else:
                    result[tag] = child.text
            return result
        except ET.ParseError as e:
            logger.error(f"[WeComCrypto] Parse XML failed: {e}")
            return {}


class WeComWebhookHandler:
    """Handler for WeCom webhook callbacks."""

    def __init__(
        self,
        token: str | None = None,
        encoding_aes_key: str | None = None,
        corp_id: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        self.token = token
        self.agent_id = agent_id
        self.crypto = (
            WeComCrypto(token, encoding_aes_key, corp_id or "")
            if token or encoding_aes_key
            else None
        )
        self._event_handlers: dict[str, list[HandlerCallback]] = {}
        self._default_handlers: list[HandlerCallback] = []

    def register_handler(self, msg_type: str, handler: HandlerCallback) -> None:
        """Register handler for specific message type or 'event'."""
        if msg_type not in self._event_handlers:
            self._event_handlers[msg_type] = []
        self._event_handlers[msg_type].append(handler)

    def verify_request(self, request: Any) -> str:
        """Verify callback URL and return echo string."""
        from fastapi import Request

        if not isinstance(request, Request):
            return ""

        query = request.query_params
        msg_signature = query.get("msg_signature", "")
        timestamp = query.get("timestamp", "")
        nonce = query.get("nonce", "")
        echostr = query.get("echostr", "")

        if not echostr:
            return ""

        if self.crypto:
            return self.crypto.verify_url(msg_signature, timestamp, nonce, echostr)
        else:
            # No encryption, just return echostr
            return echostr

    async def handle_request(self, request: Any) -> str:
        """Handle incoming webhook request."""
        from fastapi import Request

        if not isinstance(request, Request):
            return "success"

        query = request.query_params
        msg_signature = query.get("msg_signature", "")
        timestamp = query.get("timestamp", "")
        nonce = query.get("nonce", "")

        # Read body
        body = await request.body()
        xml_content = body.decode("utf-8") if body else ""

        # Parse and decrypt
        if self.crypto:
            msg_data = self.crypto.decrypt_msg(msg_signature, timestamp, nonce, xml_content)
        else:
            msg_data = self._parse_xml(xml_content)

        if not msg_data:
            return "success"

        # Get message type
        msg_type = msg_data.get("msg_type", "").lower()
        event_type = msg_data.get("event", "").lower()

        # Dispatch to handlers
        handled = False

        # Try event type first
        if event_type and event_type in self._event_handlers:
            for handler in self._event_handlers[event_type]:
                handler(msg_data)
                handled = True

        # Then try message type
        if msg_type in self._event_handlers:
            for handler in self._event_handlers[msg_type]:
                handler(msg_data)
                handled = True

        # Finally try "event" and "message" generic handlers
        if event_type and "event" in self._event_handlers:
            for handler in self._event_handlers["event"]:
                handler(msg_data)
                handled = True

        if msg_type and "message" in self._event_handlers:
            for handler in self._event_handlers["message"]:
                handler(msg_data)
                handled = True

        # Default handlers
        for handler in self._default_handlers:
            handler(msg_data)
            handled = True

        return "success"

    def _parse_xml(self, xml: str) -> dict[str, Any]:
        """Parse plain XML message."""
        try:
            root = ET.fromstring(xml)
            result: dict[str, Any] = {}
            for child in root:
                tag = child.tag.lower()
                if tag == "createtime":
                    result[tag] = int(child.text or "0")
                elif tag == "msgid":
                    result[tag] = child.text
                elif tag == "agentid":
                    result[tag] = child.text
                else:
                    result[tag] = child.text
            return result
        except ET.ParseError as e:
            logger.error(f"[WeComWebhook] Parse XML failed: {e}")
            return {}
