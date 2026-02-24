"""Feishu Bitable (Multi-dimensional Table) operations."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FeishuBitableClient:
    """Client for Feishu Bitable operations."""
    
    def __init__(self, client) -> None:
        self._client = client
    
    async def create_app(
        self,
        name: str,
        folder_token: str | None = None,
        time_zone: str = "Asia/Shanghai",
    ) -> str:
        """Create a new Bitable app.
        
        Args:
            name: App name
            folder_token: Optional folder to create in
            time_zone: Default timezone
            
        Returns:
            App token
        """
        data: dict[str, Any] = {
            "name": name,
            "time_zone": time_zone,
        }
        if folder_token:
            data["folder_token"] = folder_token
        
        response = self._client.bitable.app.create(data=data)
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create Bitable: {response.get('msg')}")
        
        return response["data"]["app_token"]
    
    async def get_app(self, app_token: str) -> dict[str, Any]:
        """Get Bitable app info.
        
        Args:
            app_token: App token
            
        Returns:
            App info
        """
        response = self._client.bitable.app.get_info(path={"app_token": app_token})
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get Bitable: {response.get('msg')}")
        
        return response["data"]
    
    async def list_tables(self, app_token: str) -> list[dict[str, Any]]:
        """List tables in a Bitable.
        
        Args:
            app_token: App token
            
        Returns:
            List of tables
        """
        response = self._client.bitable.table.list(path={"app_token": app_token})
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to list tables: {response.get('msg')}")
        
        return response["data"].get("items", [])
    
    async def create_table(
        self,
        app_token: str,
        name: str,
        fields: list[dict[str, Any]] | None = None,
    ) -> str:
        """Create a new table.
        
        Args:
            app_token: App token
            name: Table name
            fields: Optional initial fields
            
        Returns:
            Table ID
        """
        data: dict[str, Any] = {"table": {"name": name}}
        if fields:
            data["table"]["fields"] = fields
        
        response = self._client.bitable.table.create(
            path={"app_token": app_token},
            data=data
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create table: {response.get('msg')}")
        
        return response["data"]["table_id"]
    
    async def list_fields(
        self,
        app_token: str,
        table_id: str,
        view_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List fields in a table.
        
        Args:
            app_token: App token
            table_id: Table ID
            view_id: Optional view ID to filter
            
        Returns:
            List of fields
        """
        params = {}
        if view_id:
            params["view_id"] = view_id
        
        response = self._client.bitable.field.list(
            path={"app_token": app_token, "table_id": table_id},
            params=params
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to list fields: {response.get('msg')}")
        
        return response["data"].get("items", [])
    
    async def create_field(
        self,
        app_token: str,
        table_id: str,
        field_name: str,
        field_type: int,
        property: dict[str, Any] | None = None,
    ) -> str:
        """Create a new field.
        
        Args:
            app_token: App token
            table_id: Table ID
            field_name: Field name
            field_type: Field type number
            property: Field-specific properties
            
        Returns:
            Field ID
        """
        data: dict[str, Any] = {
            "field_name": field_name,
            "type": field_type,
        }
        if property:
            data["property"] = property
        
        response = self._client.bitable.field.create(
            path={"app_token": app_token, "table_id": table_id},
            data=data
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create field: {response.get('msg')}")
        
        return response["data"]["field_id"]
    
    async def list_records(
        self,
        app_token: str,
        table_id: str,
        view_id: str | None = None,
        filter_: str | None = None,
        sort: list[str] | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        """List records in a table.
        
        Args:
            app_token: App token
            table_id: Table ID
            view_id: Optional view ID
            filter_: Optional filter formula
            sort: Optional sort rules
            page_size: Records per page
            
        Returns:
            List of records
        """
        records = []
        page_token = None
        
        while True:
            params: dict[str, Any] = {"page_size": min(page_size, 500)}
            if view_id:
                params["view_id"] = view_id
            if filter_:
                params["filter"] = filter_
            if sort:
                params["sort"] = sort
            if page_token:
                params["page_token"] = page_token
            
            response = self._client.bitable.record.list(
                path={"app_token": app_token, "table_id": table_id},
                params=params
            )
            
            if response.get("code") != 0:
                raise RuntimeError(f"Failed to list records: {response.get('msg')}")
            
            items = response["data"].get("items", [])
            records.extend(items)
            
            page_token = response["data"].get("page_token")
            has_more = response["data"].get("has_more", False)
            
            if not has_more or not page_token:
                break
        
        return records
    
    async def get_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
    ) -> dict[str, Any]:
        """Get a specific record.
        
        Args:
            app_token: App token
            table_id: Table ID
            record_id: Record ID
            
        Returns:
            Record data
        """
        response = self._client.bitable.record.get(
            path={
                "app_token": app_token,
                "table_id": table_id,
                "record_id": record_id,
            }
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to get record: {response.get('msg')}")
        
        return response["data"]["record"]
    
    async def create_record(
        self,
        app_token: str,
        table_id: str,
        fields: dict[str, Any],
    ) -> str:
        """Create a new record.
        
        Args:
            app_token: App token
            table_id: Table ID
            fields: Field values
            
        Returns:
            Record ID
        """
        response = self._client.bitable.record.create(
            path={"app_token": app_token, "table_id": table_id},
            data={"fields": fields}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to create record: {response.get('msg')}")
        
        return response["data"]["record"]["record_id"]
    
    async def update_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: dict[str, Any],
    ) -> None:
        """Update a record.
        
        Args:
            app_token: App token
            table_id: Table ID
            record_id: Record ID
            fields: Updated field values
        """
        response = self._client.bitable.record.update(
            path={
                "app_token": app_token,
                "table_id": table_id,
                "record_id": record_id,
            },
            data={"fields": fields}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to update record: {response.get('msg')}")
    
    async def delete_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
    ) -> None:
        """Delete a record.
        
        Args:
            app_token: App token
            table_id: Table ID
            record_id: Record ID
        """
        response = self._client.bitable.record.delete(
            path={
                "app_token": app_token,
                "table_id": table_id,
                "record_id": record_id,
            }
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to delete record: {response.get('msg')}")
    
    async def search_records(
        self,
        app_token: str,
        table_id: str,
        query: str,
    ) -> list[dict[str, Any]]:
        """Search records by text.
        
        Args:
            app_token: App token
            table_id: Table ID
            query: Search query
            
        Returns:
            Matching records
        """
        response = self._client.bitable.record.search(
            path={"app_token": app_token, "table_id": table_id},
            data={"query": query}
        )
        
        if response.get("code") != 0:
            raise RuntimeError(f"Failed to search records: {response.get('msg')}")
        
        return response["data"].get("items", [])


# Field type constants
FIELD_TYPE_TEXT = 1
FIELD_TYPE_NUMBER = 2
FIELD_TYPE_SINGLE_SELECT = 3
FIELD_TYPE_MULTI_SELECT = 4
FIELD_TYPE_DATETIME = 5
FIELD_TYPE_CURRENCY = 7
FIELD_TYPE_USER = 11
FIELD_TYPE_PHONE = 13
FIELD_TYPE_URL = 15
FIELD_TYPE_ATTACHMENT = 17
FIELD_TYPE_SINGLE_LINK = 18
FIELD_TYPE_LOOKUP = 19
FIELD_TYPE_FORMULA = 20
FIELD_TYPE_DUPLEX_LINK = 21
FIELD_TYPE_LOCATION = 22
FIELD_TYPE_GROUP_CHAT = 23
FIELD_TYPE_PROGRESS = 25
FIELD_TYPE_RATING = 27
FIELD_TYPE_CHECKBOX = 28
