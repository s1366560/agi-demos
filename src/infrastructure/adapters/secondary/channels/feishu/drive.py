"""Feishu Drive (Cloud Storage) operations."""

import logging
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Union

import httpx

logger = logging.getLogger(__name__)


class FeishuDriveClient:
    """Client for Feishu Drive operations."""
    
    def __init__(self, client):
        self._client = client
    
    async def list_files(
        self,
        folder_token: Optional[str] = None,
        page_size: int = 100
    ) -> List[Dict[str, Any]]:
        """List files in a folder.
        
        Args:
            folder_token: Folder token (None for root)
            page_size: Number of files per page
            
        Returns:
            List of file metadata
        """
        files = []
        page_token = None
        
        while True:
            params: Dict[str, Any] = {"page_size": page_size}
            if folder_token:
                params["folder_token"] = folder_token
            if page_token:
                params["page_token"] = page_token
            
            response = self._client.drive.file.list(params=params)
            
            if response.get("code") != 0:
                raise RuntimeError(f"Failed to list files: {response.get('msg')}")
            
            items = response["data"].get("files", [])
            files.extend(items)
            
            page_token = response["data"].get("next_page_token")
            if not page_token:
                break
        
        return files
    
    async def get_file(self, file_token: str) -> Dict[str, Any]:
        """Get file metadata.
        
        Args:
            file_token: File token
            
        Returns:
            File metadata
        """
        response = self._client.drive.file.get_info(query={"file_token": file_token})
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get file: {response.get('msg')}")
        
        return response["data"]
    
    async def create_folder(
        self,
        name: str,
        parent_token: Optional[str] = None
    ) -> str:
        """Create a new folder.
        
        Args:
            name: Folder name
            parent_token: Optional parent folder token
            
        Returns:
            New folder token
        """
        data: Dict[str, Any] = {"name": name}
        if parent_token:
            data["folder_token"] = parent_token
        
        response = self._client.drive.folder.create(data=data)
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create folder: {response.get('msg')}")
        
        return response["data"]["token"]
    
    async def upload_file(
        self,
        file: Union[bytes, BinaryIO, Path, str],
        file_name: str,
        parent_type: str = "explorer",
        parent_token: Optional[str] = None,
    ) -> str:
        """Upload a file to Drive.
        
        Args:
            file: File data (bytes, file object, path, or URL)
            file_name: File name
            parent_type: Parent type (explorer, folder, etc.)
            parent_token: Parent token
            
        Returns:
            Uploaded file token
        """
        # Read file data
        if isinstance(file, (str, Path)) and str(file).startswith(("http://", "https://")):
            async with httpx.AsyncClient() as client:
                resp = await client.get(str(file))
                resp.raise_for_status()
                file_data = resp.content
        elif isinstance(file, (str, Path)):
            with open(file, "rb") as f:
                file_data = f.read()
        elif hasattr(file, "read"):
            file_data = file.read()
        else:
            file_data = file
        
        data: Dict[str, Any] = {
            "file_name": file_name,
            "parent_type": parent_type,
            "file": file_data,
        }
        if parent_token:
            data["parent_token"] = parent_token
        
        response = self._client.drive.file.create(data=data)
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to upload file: {response.get('msg')}")
        
        return response["data"]["file_token"]
    
    async def download_file(
        self,
        file_token: str,
        local_path: Optional[Union[str, Path]] = None
    ) -> Union[bytes, Path]:
        """Download a file from Drive.
        
        Args:
            file_token: File token
            local_path: Optional path to save file (returns bytes if not provided)
            
        Returns:
            File bytes or saved path
        """
        response = self._client.drive.file.download(query={"file_token": file_token})
        
        # Handle different response formats
        if isinstance(response, bytes):
            file_data = response
        elif hasattr(response, "data"):
            file_data = response.data if isinstance(response.data, bytes) else bytes(response.data)
        else:
            raise RuntimeError(f"Unexpected response format: {type(response)}")
        
        if local_path:
            path = Path(local_path)
            path.write_bytes(file_data)
            return path
        
        return file_data
    
    async def move_file(
        self,
        file_token: str,
        target_folder_token: str,
        target_type: str = "folder"
    ) -> None:
        """Move a file to another folder.
        
        Args:
            file_token: File to move
            target_folder_token: Destination folder
            target_type: Target type
        """
        response = self._client.drive.file.move(
            data={
                "file_token": file_token,
                "target_folder_token": target_folder_token,
                "target_type": target_type,
            }
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to move file: {response.get('msg')}")
    
    async def copy_file(
        self,
        file_token: str,
        target_folder_token: str,
        target_type: str = "folder",
        name: Optional[str] = None,
    ) -> str:
        """Copy a file to another folder.
        
        Args:
            file_token: File to copy
            target_folder_token: Destination folder
            target_type: Target type
            name: Optional new name
            
        Returns:
            New file token
        """
        data: Dict[str, Any] = {
            "file_token": file_token,
            "target_folder_token": target_folder_token,
            "target_type": target_type,
        }
        if name:
            data["name"] = name
        
        response = self._client.drive.file.copy(data=data)
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to copy file: {response.get('msg')}")
        
        return response["data"]["file_token"]
    
    async def delete_file(self, file_token: str, type: str = "file") -> None:
        """Delete a file or folder.
        
        Args:
            file_token: File/folder token
            type: "file" or "folder"
        """
        response = self._client.drive.file.delete(
            data={"token": file_token, "type": type}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to delete file: {response.get('msg')}")
    
    async def search_files(
        self,
        query: str,
        search_type: str = "file",  # file, folder, wiki
        page_size: int = 50
    ) -> List[Dict[str, Any]]:
        """Search for files.
        
        Args:
            query: Search query
            search_type: Type to search
            page_size: Results per page
            
        Returns:
            List of matching files
        """
        results = []
        page_token = None
        
        while True:
            params: Dict[str, Any] = {
                "query": query,
                "search_type": search_type,
                "page_size": page_size,
            }
            if page_token:
                params["page_token"] = page_token
            
            response = self._client.drive.file.search(params=params)
            
            if response.get("code") != 0:
                raise RuntimeError(f"Failed to search files: {response.get('msg')}")
            
            items = response["data"].get("files", [])
            results.extend(items)
            
            page_token = response["data"].get("next_page_token")
            has_more = response["data"].get("has_more", False)
            
            if not has_more or not page_token:
                break
        
        return results
    
    async def get_file_permissions(self, file_token: str) -> Dict[str, Any]:
        """Get file permissions.
        
        Args:
            file_token: File token
            
        Returns:
            Permission settings
        """
        response = self._client.drive.file.get_permission(
            query={"file_token": file_token}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get permissions: {response.get('msg')}")
        
        return response["data"]
    
    async def transfer_file_owner(
        self,
        file_token: str,
        new_owner_id: str,
        type: str = "file",
        remove_old_owner: bool = False,
    ) -> None:
        """Transfer file ownership.
        
        Args:
            file_token: File token
            new_owner_id: New owner user ID
            type: "file" or "folder"
            remove_old_owner: Whether to remove old owner
        """
        response = self._client.drive.file.transfer_owner(
            data={
                "token": file_token,
                "type": type,
                "owner": new_owner_id,
                "remove_old_owner": remove_old_owner,
            }
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to transfer ownership: {response.get('msg')}")


class DriveSearchResult:
    """Result of a drive search."""
    
    def __init__(self, data: Dict[str, Any]):
        self.total = data.get("total", 0)
        self.has_more = data.get("has_more", False)
        self.files = data.get("files", [])
    
    def __iter__(self):
        return iter(self.files)
    
    def __len__(self):
        return len(self.files)
