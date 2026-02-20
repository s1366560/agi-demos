"""Feishu document (Docx) operations."""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FeishuDocClient:
    """Client for Feishu document operations."""
    
    def __init__(self, client):
        self._client = client
    
    async def create_document(
        self,
        title: str,
        folder_token: Optional[str] = None
    ) -> Dict[str, str]:
        """Create a new document.
        
        Args:
            title: Document title
            folder_token: Optional folder to create document in
            
        Returns:
            Dict with document_token and url
        """
        data = {
            "title": title,
        }
        
        if folder_token:
            data["folder_token"] = folder_token
        
        response = self._client.docx.document.create(data=data)
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create document: {response.get('msg')}")
        
        return {
            "document_token": response["data"]["document"]["document_token"],
            "url": response["data"]["document"].get("url", ""),
        }
    
    async def get_document(self, document_token: str) -> Dict[str, Any]:
        """Get document metadata.
        
        Args:
            document_token: Document token
            
        Returns:
            Document metadata
        """
        response = self._client.docx.document.get(path={"document_token": document_token})
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get document: {response.get('msg')}")
        
        return response["data"]
    
    async def get_document_content(
        self,
        document_token: str,
        lang: str = "0"  # 0=zh, 1=en
    ) -> str:
        """Get document raw content.
        
        Args:
            document_token: Document token
            lang: Language (0=Chinese, 1=English)
            
        Returns:
            Document content as string
        """
        response = self._client.docx.document.raw_content.get(
            path={"document_token": document_token},
            params={"lang": lang}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get document content: {response.get('msg')}")
        
        return response["data"].get("content", "")
    
    async def list_document_blocks(
        self,
        document_token: str,
        page_size: int = 500
    ) -> List[Dict[str, Any]]:
        """List all blocks in a document.
        
        Args:
            document_token: Document token
            page_size: Number of blocks per page
            
        Returns:
            List of document blocks
        """
        blocks = []
        page_token = None
        
        while True:
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            
            response = self._client.docx.document.blocks.list(
                path={"document_token": document_token},
                params=params
            )
            
            if response.get("code") != 0:
                raise RuntimeError(f"Failed to list blocks: {response.get('msg')}")
            
            items = response["data"].get("items", [])
            blocks.extend(items)
            
            page_token = response["data"].get("page_token")
            if not page_token:
                break
        
        return blocks
    
    async def get_block(self, document_token: str, block_id: str) -> Dict[str, Any]:
        """Get a specific block.
        
        Args:
            document_token: Document token
            block_id: Block ID
            
        Returns:
            Block data
        """
        response = self._client.docx.document.blocks.get(
            path={"document_token": document_token, "block_id": block_id}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get block: {response.get('msg')}")
        
        return response["data"]
    
    async def create_block(
        self,
        document_token: str,
        parent_block_id: str,
        block_type: int,
        content: Dict[str, Any],
        index: int = 0
    ) -> Dict[str, str]:
        """Create a new block in the document.
        
        Args:
            document_token: Document token
            parent_block_id: Parent block ID (use document_token for root)
            block_type: Block type number
            content: Block content
            index: Insert position
            
        Returns:
            Created block info
        """
        data = {
            "children": [
                {
                    "block_type": block_type,
                    **content,
                }
            ]
        }
        
        if index > 0:
            data["index"] = index
        
        response = self._client.docx.document.blocks.children.create(
            path={"document_token": document_token, "block_id": parent_block_id},
            data=data
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create block: {response.get('msg')}")
        
        children = response["data"].get("children", [])
        return {
            "block_id": children[0]["block_id"] if children else "",
        }
    
    async def update_block(
        self,
        document_token: str,
        block_id: str,
        content: Dict[str, Any]
    ) -> None:
        """Update a block.
        
        Args:
            document_token: Document token
            block_id: Block ID
            content: New block content
        """
        response = self._client.docx.document.blocks.patch(
            path={"document_token": document_token, "block_id": block_id},
            data=content
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to update block: {response.get('msg')}")
    
    async def delete_block(self, document_token: str, block_id: str) -> None:
        """Delete a block.
        
        Args:
            document_token: Document token
            block_id: Block ID
        """
        response = self._client.docx.document.blocks.delete(
            path={"document_token": document_token, "block_id": block_id}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to delete block: {response.get('msg')}")


# Block types for docx
BLOCK_TYPE_PAGE = 1
BLOCK_TYPE_TEXT = 2
BLOCK_TYPE_HEADING1 = 3
BLOCK_TYPE_HEADING2 = 4
BLOCK_TYPE_HEADING3 = 5
BLOCK_TYPE_HEADING4 = 6
BLOCK_TYPE_HEADING5 = 7
BLOCK_TYPE_HEADING6 = 8
BLOCK_TYPE_HEADING7 = 9
BLOCK_TYPE_HEADING8 = 10
BLOCK_TYPE_HEADING9 = 11
BLOCK_TYPE_BULLET = 12
BLOCK_TYPE_ORDERED = 13
BLOCK_TYPE_CODE = 14
BLOCK_TYPE_QUOTE = 15
BLOCK_TYPE_TODO = 17
BLOCK_TYPE_DIVIDER = 18
BLOCK_TYPE_IMAGE = 27
BLOCK_TYPE_TABLE = 31
BLOCK_TYPE_QUOTE_CONTAINER = 34
