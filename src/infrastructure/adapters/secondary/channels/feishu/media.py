"""Feishu media handling - images, files, audio, video."""

import logging
from pathlib import Path
from typing import BinaryIO, Optional, Union

import httpx

logger = logging.getLogger(__name__)


class FeishuMediaManager:
    """Manager for Feishu media operations (upload/download)."""
    
    def __init__(self, client):
        self._client = client
    
    async def upload_image(
        self,
        image: Union[bytes, BinaryIO, Path, str],
        image_type: str = "message"
    ) -> str:
        """Upload an image to Feishu.
        
        Args:
            image: Image data (bytes, file object, path, or URL)
            image_type: "message" or "avatar"
            
        Returns:
            Image key for sending
        """
        if isinstance(image, (str, Path)) and str(image).startswith(("http://", "https://")):
            # Download from URL first
            async with httpx.AsyncClient() as client:
                response = await client.get(str(image))
                response.raise_for_status()
                image_data = response.content
        elif isinstance(image, (str, Path)):
            # Read from file path
            with open(image, "rb") as f:
                image_data = f.read()
        elif hasattr(image, "read"):
            # File-like object
            image_data = image.read()
        else:
            image_data = image
        
        response = self._client.im.image.create(
            data={
                "image_type": image_type,
                "image": image_data,
            }
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Image upload failed: {response.get('msg')}")
        
        return response["data"]["image_key"]
    
    async def upload_file(
        self,
        file: Union[bytes, BinaryIO, Path, str],
        file_name: str,
        file_type: Optional[str] = None,
        duration: Optional[int] = None
    ) -> str:
        """Upload a file to Feishu.
        
        Args:
            file: File data (bytes, file object, path, or URL)
            file_name: File name with extension
            file_type: File type (opus, mp4, pdf, doc, xls, ppt, stream)
            duration: Duration in ms (for audio/video)
            
        Returns:
            File key for sending
        """
        # Detect file type from extension if not provided
        if file_type is None:
            file_type = self._detect_file_type(file_name)
        
        # Read file data
        if isinstance(file, (str, Path)) and str(file).startswith(("http://", "https://")):
            async with httpx.AsyncClient() as client:
                response = await client.get(str(file))
                response.raise_for_status()
                file_data = response.content
        elif isinstance(file, (str, Path)):
            with open(file, "rb") as f:
                file_data = f.read()
        elif hasattr(file, "read"):
            file_data = file.read()
        else:
            file_data = file
        
        data = {
            "file_type": file_type,
            "file_name": file_name,
            "file": file_data,
        }
        if duration is not None:
            data["duration"] = duration
        
        response = self._client.im.file.create(data=data)
        
        if response.get("code") != 0:
            raise RuntimeError(f"File upload failed: {response.get('msg')}")
        
        return response["data"]["file_key"]
    
    async def download_image(self, image_key: str) -> bytes:
        """Download an image by key.
        
        Args:
            image_key: Image key
            
        Returns:
            Image bytes
        """
        response = self._client.im.image.get(path={"image_key": image_key})
        
        # Handle different response formats
        if isinstance(response, bytes):
            return response
        elif hasattr(response, "data"):
            return response.data if isinstance(response.data, bytes) else bytes(response.data)
        else:
            raise RuntimeError(f"Unexpected response format: {type(response)}")
    
    async def download_file(
        self,
        message_id: str,
        file_key: str,
        file_type: str = "file"
    ) -> bytes:
        """Download a file from a message.
        
        Args:
            message_id: Message ID containing the file
            file_key: File key
            file_type: "file" or "image"
            
        Returns:
            File bytes
        """
        response = self._client.im.messageResource.get(
            path={"message_id": message_id, "file_key": file_key},
            params={"type": file_type}
        )
        
        # Handle different response formats
        if isinstance(response, bytes):
            return response
        elif hasattr(response, "data"):
            return response.data if isinstance(response.data, bytes) else bytes(response.data)
        else:
            raise RuntimeError(f"Unexpected response format: {type(response)}")
    
    def _detect_file_type(self, file_name: str) -> str:
        """Detect file type from extension."""
        ext = Path(file_name).suffix.lower()
        type_map = {
            ".opus": "opus",
            ".ogg": "opus",
            ".mp4": "mp4",
            ".mov": "mp4",
            ".avi": "mp4",
            ".pdf": "pdf",
            ".doc": "doc",
            ".docx": "doc",
            ".xls": "xls",
            ".xlsx": "xls",
            ".ppt": "ppt",
            ".pptx": "ppt",
        }
        return type_map.get(ext, "stream")


class MediaUploadResult:
    """Result of a media upload operation."""
    
    def __init__(self, key: str, key_type: str):
        self.key = key
        self.key_type = key_type  # "image_key" or "file_key"
