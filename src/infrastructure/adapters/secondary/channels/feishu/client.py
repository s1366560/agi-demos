"""Feishu API utilities for the stable channel implementation."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from src.domain.model.channels.message import SenderInfo

_PLUGIN_DIR = Path(__file__).resolve().parent


def _load_sibling(module_file: str) -> ModuleType:
    file_path = _PLUGIN_DIR / module_file
    module_name = f"feishu_{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load sibling module: {file_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FeishuClient:
    """Enhanced Feishu API client with full feature support.

    Features:
    - Messaging (text, cards, images, files)
    - Documents (docx)
    - Wiki (knowledge base)
    - Drive (cloud storage)
    - Bitable (multi-dimensional tables)
    - Media operations
    """

    def __init__(self, app_id: str, app_secret: str, domain: str = "feishu") -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.domain = domain
        self._client: Any | None = None

        # Lazy-loaded sub-clients
        self._media: Any | None = None
        self._docs: Any | None = None
        self._wiki: Any | None = None
        self._drive: Any | None = None
        self._bitable: Any | None = None

    def _get_client(self) -> object:
        """Lazy load Feishu client."""
        if self._client is None:
            try:
                from lark_oapi import Client

                self._client = Client(
                    app_id=self.app_id,
                    app_secret=self.app_secret,
                )
            except ImportError:
                raise ImportError("lark_oapi not installed. Run: pip install lark_oapi") from None
        return self._client

    @property
    def media(self) -> object:
        """Get media manager for image/file operations."""
        if self._media is None:
            _media_mod = _load_sibling("media.py")
            self._media = _media_mod.FeishuMediaManager(self._get_client())
        return self._media

    @property
    def docs(self) -> object:
        """Get document client for docx operations."""
        if self._docs is None:
            _docx_mod = _load_sibling("docx.py")
            self._docs = _docx_mod.FeishuDocClient(self._get_client())
        return self._docs

    @property
    def wiki(self) -> object:
        """Get wiki client for knowledge base operations."""
        if self._wiki is None:
            _wiki_mod = _load_sibling("wiki.py")
            self._wiki = _wiki_mod.FeishuWikiClient(self._get_client())
        return self._wiki

    @property
    def drive(self) -> object:
        """Get drive client for cloud storage operations."""
        if self._drive is None:
            _drive_mod = _load_sibling("drive.py")
            self._drive = _drive_mod.FeishuDriveClient(self._get_client())
        return self._drive

    @property
    def bitable(self) -> object:
        """Get bitable client for multi-dimensional table operations."""
        if self._bitable is None:
            _bitable_mod = _load_sibling("bitable.py")
            self._bitable = _bitable_mod.FeishuBitableClient(self._get_client())
        return self._bitable

    async def send_text_message(self, to: str, text: str) -> str:
        """Send text message.

        Args:
            to: Recipient ID (open_id or chat_id)
            text: Message text

        Returns:
            Message ID
        """
        client = self._get_client()
        receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"

        response = client.im.message.create(
            params={"receive_id_type": receive_id_type},
            data={
                "receive_id": to,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
        )

        return cast(str, response.get("data", {}).get("message_id"))

    async def send_card_message(self, to: str, card: dict[str, Any] | str) -> str:
        """Send interactive card message.

        Args:
            to: Recipient ID
            card: Card configuration dict or JSON string

        Returns:
            Message ID
        """
        client = self._get_client()
        receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"

        if isinstance(card, dict):
            card = json.dumps(card)

        response = client.im.message.create(
            params={"receive_id_type": receive_id_type},
            data={
                "receive_id": to,
                "msg_type": "interactive",
                "content": card,
            },
        )

        return cast(str, response.get("data", {}).get("message_id"))

    async def send_markdown_card(self, to: str, content: str, title: str | None = None) -> str:
        """Send a markdown card message.

        Args:
            to: Recipient ID
            content: Markdown content
            title: Optional card title

        Returns:
            Message ID
        """
        _cards_mod = _load_sibling("cards.py")
        card = _cards_mod.CardBuilder.create_markdown_card(content, title)
        return await self.send_card_message(to, card)

    async def send_image_message(self, to: str, image_key: str) -> str:
        """Send an image message.

        Args:
            to: Recipient ID
            image_key: Image key from upload

        Returns:
            Message ID
        """
        client = self._get_client()
        receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"

        response = client.im.message.create(
            params={"receive_id_type": receive_id_type},
            data={
                "receive_id": to,
                "msg_type": "image",
                "content": json.dumps({"image_key": image_key}),
            },
        )

        return cast(str, response.get("data", {}).get("message_id"))

    async def send_file_message(self, to: str, file_key: str, file_name: str = "") -> str:
        """Send a file message.

        Args:
            to: Recipient ID
            file_key: File key from upload
            file_name: Optional file name

        Returns:
            Message ID
        """
        client = self._get_client()
        receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"

        response = client.im.message.create(
            params={"receive_id_type": receive_id_type},
            data={
                "receive_id": to,
                "msg_type": "file",
                "content": json.dumps({"file_key": file_key}),
            },
        )

        return cast(str, response.get("data", {}).get("message_id"))

    async def reply_message(self, message_id: str, text: str, msg_type: str = "text") -> str:
        """Reply to a message.

        Args:
            message_id: Original message ID
            text: Reply text (or card JSON if msg_type='interactive')
            msg_type: Message type (text, interactive, image, file)

        Returns:
            Reply message ID
        """
        client = self._get_client()

        content = text
        if msg_type == "text":
            content = json.dumps({"text": text})

        response = client.im.message.reply(
            path={"message_id": message_id},
            data={
                "content": content,
                "msg_type": msg_type,
            },
        )

        return cast(str, response.get("data", {}).get("message_id"))

    async def edit_message(self, message_id: str, text: str, msg_type: str = "text") -> None:
        """Edit an existing message (within 24 hours).

        Args:
            message_id: Message ID to edit
            text: New text content
            msg_type: Message type
        """
        client = self._get_client()

        content = text
        if msg_type == "text":
            content = json.dumps({"text": text})

        client.im.message.update(
            path={"message_id": message_id},
            data={
                "msg_type": msg_type,
                "content": content,
            },
        )

    async def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Get message by ID.

        Args:
            message_id: Message ID

        Returns:
            Message data or None
        """
        client = self._get_client()

        response = client.im.message.get(path={"message_id": message_id})

        if response.get("code") != 0:
            return None

        items = response.get("data", {}).get("items", [])
        return items[0] if items else None

    async def recall_message(self, message_id: str) -> None:
        """Recall/delete a message.

        Args:
            message_id: Message ID to recall
        """
        client = self._get_client()

        client.im.message.delete(path={"message_id": message_id})

    async def add_reaction(self, message_id: str, emoji_type: str) -> None:
        """Add emoji reaction to a message.

        Args:
            message_id: Message ID
            emoji_type: Emoji type (e.g., "OK", "THUMBSUP", "HEART")
        """
        client = self._get_client()

        client.im.messageReaction.create(
            data={
                "message_id": message_id,
                "reaction_type": {"emoji_type": emoji_type},
            }
        )

    async def remove_reaction(self, message_id: str, emoji_type: str) -> None:
        """Remove emoji reaction from a message.

        Args:
            message_id: Message ID
            emoji_type: Emoji type
        """
        client = self._get_client()

        client.im.messageReaction.delete(
            data={
                "message_id": message_id,
                "reaction_type": {"emoji_type": emoji_type},
            }
        )

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        """Get chat group information.

        Args:
            chat_id: Chat ID

        Returns:
            Chat info dict with name, description, member_count
        """
        client = self._get_client()

        response = client.im.chat.get({"chat_id": chat_id})
        chat = response.get("data", {})

        return {
            "id": chat.get("chat_id"),
            "name": chat.get("name"),
            "description": chat.get("description"),
            "member_count": chat.get("member_count"),
            "owner_id": chat.get("owner_id"),
        }

    async def get_chat_members(self, chat_id: str) -> list[SenderInfo]:
        """Get chat members.

        Args:
            chat_id: Chat ID

        Returns:
            List of SenderInfo
        """
        client = self._get_client()

        response = client.im.chatMembers.get({"chat_id": chat_id}, {"member_id_type": "open_id"})

        members = response.get("data", {}).get("items", [])
        return [SenderInfo(id=m.get("member_id"), name=m.get("name")) for m in members]

    async def get_user_info(self, user_id: str) -> SenderInfo | None:
        """Get user information.

        Args:
            user_id: User open_id

        Returns:
            SenderInfo or None
        """
        client = self._get_client()

        response = client.contact.user.get({"user_id": user_id}, {"user_id_type": "open_id"})

        user = response.get("data", {}).get("user", {})
        if not user:
            return None

        return SenderInfo(
            id=user.get("open_id", user_id),
            name=user.get("name"),
            avatar=user.get("avatar", {}).get("avatar_origin"),
        )

    async def send_image(self, to: str, image_key: str) -> str:
        """Send image message.

        Args:
            to: Recipient ID
            image_key: Image key from upload

        Returns:
            Message ID
        """
        client = self._get_client()
        receive_id_type = "open_id" if to.startswith("ou_") else "chat_id"

        response = client.im.message.create(
            {"receive_id_type": receive_id_type},
            {
                "receive_id": to,
                "msg_type": "image",
                "content": json.dumps({"image_key": image_key}),
            },
        )

        return cast(str, response.get("data", {}).get("message_id"))

    async def upload_image(self, image_data: bytes) -> str:
        """Upload image.

        Args:
            image_data: Raw image bytes

        Returns:
            Image key
        """
        client = self._get_client()

        response = client.im.image.create({"image_type": "message"}, image_data)

        return cast(str, response.get("data", {}).get("image_key"))


# Convenience functions for direct use


async def send_feishu_text(app_id: str, app_secret: str, to: str, text: str) -> str:
    """Send text message to Feishu (convenience function)."""
    client = FeishuClient(app_id, app_secret)
    return await client.send_text_message(to, text)


async def send_feishu_card(app_id: str, app_secret: str, to: str, card: dict[str, Any]) -> str:
    """Send card message to Feishu (convenience function)."""
    client = FeishuClient(app_id, app_secret)
    return await client.send_card_message(to, card)
