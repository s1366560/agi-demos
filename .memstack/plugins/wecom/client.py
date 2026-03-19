"""WeCom utility functions for direct API calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from src.domain.model.channels.message import SenderInfo

_PLUGIN_DIR = Path(__file__).resolve().parent


class WeComClient:
    """Enhanced WeCom API client with full feature support.

    Features:
    - Messaging (text, images, files, cards)
    - User management
    - Department management
    - Media operations
    - Menu operations
    """

    def __init__(
        self,
        corp_id: str,
        agent_id: str,
        secret: str,
    ) -> None:
        self.corp_id = corp_id
        self.agent_id = agent_id
        self.secret = secret
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0

    async def _get_access_token(self) -> str:
        """Get or refresh access token."""
        import time

        import aiohttp

        now = time.time()
        if self._access_token and now < self._access_token_expires_at - 300:
            return self._access_token

        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?"
            f"corpid={self.corp_id}&corpsecret={self.secret}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(
                        f"WeCom gettoken failed: {data.get('errmsg', 'unknown error')}"
                    )
                self._access_token = data["access_token"]
                self._access_token_expires_at = now + 7200
                return self._access_token

    # === User operations ===

    async def get_user(self, user_id: str) -> dict[str, Any]:
        """Get user by user_id."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/user/get?access_token={token}&userid={user_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom get user failed: {data.get('errmsg')}")
                return data

    async def get_user_info(self, code: str) -> dict[str, Any]:
        """Get user info by OAuth2 code."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/user/getuserinfo?access_token={token}&code={code}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom get user info failed: {data.get('errmsg')}")
                return data

    async def get_department_users(
        self, department_id: int, fetch_child: bool = False
    ) -> list[dict[str, Any]]:
        """Get users in a department."""
        import aiohttp

        token = await self._get_access_token()
        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/user/list?"
            f"access_token={token}&department_id={department_id}&fetch_child={1 if fetch_child else 0}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(
                        f"WeCom get department users failed: {data.get('errmsg')}"
                    )
                return data.get("userlist", [])

    # === Department operations ===

    async def get_department_list(self, department_id: int = 1) -> list[dict[str, Any]]:
        """Get department list."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/department/list?access_token={token}&id={department_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(
                        f"WeCom get department list failed: {data.get('errmsg')}"
                    )
                return data.get("department", [])

    # === Message operations ===

    async def send_text(self, to: str, content: str) -> str:
        """Send text message."""
        return await self._send_message(
            {"touser": to, "msgtype": "text", "text": {"content": content}}
        )

    async def send_image(self, to: str, media_id: str) -> str:
        """Send image message."""
        return await self._send_message(
            {"touser": to, "msgtype": "image", "image": {"media_id": media_id}}
        )

    async def send_file(self, to: str, media_id: str) -> str:
        """Send file message."""
        return await self._send_message(
            {"touser": to, "msgtype": "file", "file": {"media_id": media_id}}
        )

    async def send_textcard(
        self,
        to: str,
        title: str,
        description: str,
        url: str,
        btn_txt: str = "详情",
    ) -> str:
        """Send text card message."""
        return await self._send_message(
            {
                "touser": to,
                "msgtype": "textcard",
                "textcard": {
                    "title": title,
                    "description": description,
                    "url": url,
                    "btntxt": btn_txt,
                },
            }
        )

    async def send_markdown(self, to: str, content: str) -> str:
        """Send markdown message (WeCom 4.0+)."""
        return await self._send_message(
            {"touser": to, "msgtype": "markdown", "markdown": {"content": content}}
        )

    async def send_news(self, to: str, articles: list[dict[str, Any]]) -> str:
        """Send news (article) message."""
        return await self._send_message(
            {"touser": to, "msgtype": "news", "news": {"articles": articles}}
        )

    async def _send_message(self, msg_data: dict[str, Any]) -> str:
        """Send message via API."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"

        # Add agent_id
        msg_data["agentid"] = self.agent_id

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=msg_data) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom send failed: {data.get('errmsg')}")
                return str(data.get("msgid", ""))

    # === Media operations ===

    async def upload_media(self, file_path: str, media_type: str = "image") -> str:
        """Upload media file."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token={token}&type={media_type}"

        form = aiohttp.FormData()
        form.add_field(
            "media",
            open(file_path, "rb"),
            filename=file_path.split("/")[-1],
            content_type="application/octet-stream",
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom upload failed: {data.get('errmsg')}")
                return data["media_id"]

    async def get_media(self, media_id: str) -> bytes:
        """Download media file."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={media_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.content_type == "application/json":
                    data = await resp.json()
                    raise RuntimeError(f"WeCom get media failed: {data.get('errmsg')}")
                return await resp.read()

    # === Menu operations ===

    async def create_menu(
        self, button: list[dict[str, Any]], agent_id: str | None = None
    ) -> dict[str, Any]:
        """Create application menu."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/menu/create?access_token={token}&agentid={agent_id or self.agent_id}"

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={"button": button}) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom create menu failed: {data.get('errmsg')}")
                return data

    async def get_menu(self, agent_id: str | None = None) -> dict[str, Any]:
        """Get application menu."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/menu/get?access_token={token}&agentid={agent_id or self.agent_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom get menu failed: {data.get('errmsg')}")
                return data

    async def delete_menu(self, agent_id: str | None = None) -> dict[str, Any]:
        """Delete application menu."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/menu/delete?access_token={token}&agentid={agent_id or self.agent_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom delete menu failed: {data.get('errmsg')}")
                return data

    # === Tag operations ===

    async def create_tag(
        self, tag_name: str, tag_id: int | None = None
    ) -> dict[str, Any]:
        """Create a tag."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/tag/create?access_token={token}"

        payload: dict[str, Any] = {"tagname": tag_name}
        if tag_id:
            payload["tagid"] = tag_id

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom create tag failed: {data.get('errmsg')}")
                return data

    async def add_tag_users(
        self, tag_id: int, user_ids: list[str]
    ) -> dict[str, Any]:
        """Add users to a tag."""
        import aiohttp

        token = await self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/tag/addtagusers?access_token={token}"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"tagid": tag_id, "userlist": user_ids}
            ) as resp:
                data = await resp.json()
                if data.get("errcode") != 0:
                    raise RuntimeError(f"WeCom add tag users failed: {data.get('errmsg')}")
                return data


# === Convenience functions ===

# async def send_wecom_text(
#     corp_id: str, agent_id: str, secret: str, to: str, text: str
# ) -> str:
#     """Send a text message via WeCom."""
#     client = WeComClient(corp_id, agent_id, secret)
#     return await client.send_text(to, text)


# async def send_wecom_card(
#     corp_id: str,
#     agent_id: str,
#     secret: str,
#     to: str,
#     title: str,
#     description: str,
#     url: str,
# ) -> str:
#     """Send a text card message via WeCom."""
#     client = WeComClient(corp_id, agent_id, secret)
#     return await client.send_textcard(to, title, description, url)
