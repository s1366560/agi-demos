"""Feishu Wiki (Knowledge Base) operations."""

import logging
from typing import Any

from src.infrastructure.adapters.secondary.channels.feishu.client import FeishuClient

logger = logging.getLogger(__name__)


class FeishuWikiClient:
    """Client for Feishu Wiki/Knowledge Base operations."""

    def __init__(self, client: FeishuClient) -> None:
        self._client = client

    async def list_spaces(self, page_size: int = 100) -> list[dict[str, Any]]:
        """List all accessible wiki spaces.

        Args:
            page_size: Number of spaces per page

        Returns:
            List of wiki spaces
        """
        spaces = []
        page_token = None

        while True:
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token

            response = self._client.wiki.space.list(params=params)

            if response.get("code") != 0:
                raise RuntimeError(f"Failed to list spaces: {response.get('msg')}")

            items = response["data"].get("items", [])
            spaces.extend(items)

            page_token = response["data"].get("page_token")
            if not page_token:
                break

        return spaces

    async def get_space(self, space_id: str) -> dict[str, Any]:
        """Get wiki space details.

        Args:
            space_id: Wiki space ID

        Returns:
            Space details
        """
        response = self._client.wiki.space.get(path={"space_id": space_id})

        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get space: {response.get('msg')}")

        return response["data"]

    async def list_nodes(
        self, space_id: str, parent_node_token: str | None = None, page_size: int = 100
    ) -> list[dict[str, Any]]:
        """List wiki nodes in a space.

        Args:
            space_id: Wiki space ID
            parent_node_token: Optional parent node to list children
            page_size: Number of nodes per page

        Returns:
            List of wiki nodes
        """
        nodes = []
        page_token = None

        while True:
            params = {
                "space_id": space_id,
                "page_size": page_size,
            }
            if parent_node_token:
                params["parent_node_token"] = parent_node_token
            if page_token:
                params["page_token"] = page_token

            response = self._client.wiki.node.list(params=params)

            if response.get("code") != 0:
                raise RuntimeError(f"Failed to list nodes: {response.get('msg')}")

            items = response["data"].get("items", [])
            nodes.extend(items)

            page_token = response["data"].get("page_token")
            if not page_token:
                break

        return nodes

    async def get_node(self, token: str) -> dict[str, Any]:
        """Get wiki node details.

        Args:
            token: Wiki node token

        Returns:
            Node details
        """
        response = self._client.wiki.node.get_info(query={"token": token})

        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get node: {response.get('msg')}")

        return response["data"]

    async def create_node(
        self,
        space_id: str,
        title: str,
        node_type: str = "docx",  # docx, sheet, mindnote, bitable
        parent_node_token: str | None = None,
        obj_type: str | None = None,
    ) -> dict[str, str]:
        """Create a new wiki node.

        Args:
            space_id: Wiki space ID
            title: Node title
            node_type: Node type (docx, sheet, mindnote, bitable)
            parent_node_token: Optional parent node
            obj_type: Object type for shortcuts

        Returns:
            Created node info
        """
        data = {
            "space_id": space_id,
            "title": title,
            "node_type": node_type,
        }

        if parent_node_token:
            data["parent_node_token"] = parent_node_token
        if obj_type:
            data["obj_type"] = obj_type

        response = self._client.wiki.node.create(data=data)

        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create node: {response.get('msg')}")

        node = response["data"]["node"]
        return {
            "node_token": node["node_token"],
            "obj_token": node.get("obj_token", ""),
            "url": node.get("url", ""),
        }

    async def move_node(
        self,
        token: str,
        parent_node_token: str | None = None,
        target_space_id: str | None = None,
    ) -> None:
        """Move a wiki node.

        Args:
            token: Node token to move
            parent_node_token: New parent node
            target_space_id: Optional target space (for cross-space move)
        """
        data: dict[str, Any] = {}

        if parent_node_token:
            data["parent_node_token"] = parent_node_token
        if target_space_id:
            data["target_space_id"] = target_space_id

        response = self._client.wiki.node.move(query={"token": token}, data=data)

        if response.get("code") != 0:
            raise RuntimeError(f"Failed to move node: {response.get('msg')}")

    async def update_node_title(self, token: str, title: str) -> None:
        """Update wiki node title.

        Args:
            token: Node token
            title: New title
        """
        response = self._client.wiki.node.update_title(
            query={"token": token}, data={"title": title}
        )

        if response.get("code") != 0:
            raise RuntimeError(f"Failed to update node title: {response.get('msg')}")

    async def get_node_permission(self, token: str) -> dict[str, Any]:
        """Get wiki node permissions.

        Args:
            token: Node token

        Returns:
            Permission settings
        """
        response = self._client.wiki.node.get_permission(query={"token": token})

        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get node permission: {response.get('msg')}")

        return response["data"]


class WikiSearchResult:
    """Result of a wiki search."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.total = data.get("total", 0)
        self.has_more = data.get("has_more", False)
        self.items = data.get("items", [])

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
