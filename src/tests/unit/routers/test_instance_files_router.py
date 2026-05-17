"""Tests for instance file route authorization."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.infrastructure.adapters.primary.web.routers import instance_files


class InstanceServiceStub:
    def __init__(self, instance: object | None) -> None:
        self.get_instance = AsyncMock(return_value=instance)


class ContainerStub:
    def __init__(self, instance: object | None) -> None:
        self._instance_service = InstanceServiceStub(instance)

    def instance_service(self) -> InstanceServiceStub:
        return self._instance_service


class FileServiceStub:
    def __init__(self) -> None:
        self.list_tree = AsyncMock(return_value=[])
        self.read_content = AsyncMock(return_value="content")
        self.read_bytes = AsyncMock(return_value=(b"content", "file.txt", "text/plain"))
        self.create = AsyncMock()
        self.upload = AsyncMock()
        self.delete = AsyncMock()


def _patch_container(
    monkeypatch: pytest.MonkeyPatch,
    instance: object | None,
) -> None:
    monkeypatch.setattr(
        instance_files,
        "get_container_with_db",
        lambda _request, _db: ContainerStub(instance),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route_name",
    ["list", "preview", "download", "create", "upload", "delete"],
)
async def test_instance_file_routes_hide_missing_or_foreign_instances(
    monkeypatch: pytest.MonkeyPatch,
    route_name: str,
) -> None:
    _patch_container(monkeypatch, SimpleNamespace(tenant_id="other-tenant"))
    file_service = FileServiceStub()
    monkeypatch.setattr(instance_files, "_get_file_service", lambda: file_service)
    request = SimpleNamespace()
    db = SimpleNamespace()

    route_calls: dict[str, Any] = {
        "list": lambda: instance_files.list_files(
            instance_id="instance-1",
            request=request,
            tenant_id="tenant-1",
            db=db,
        ),
        "preview": lambda: instance_files.preview_file(
            instance_id="instance-1",
            file_path="file.txt",
            request=request,
            tenant_id="tenant-1",
            db=db,
        ),
        "download": lambda: instance_files.download_file(
            instance_id="instance-1",
            file_path="file.txt",
            request=request,
            tenant_id="tenant-1",
            db=db,
        ),
        "create": lambda: instance_files.create_file(
            instance_id="instance-1",
            body=instance_files.CreateFileRequest(path="file.txt", type="file"),
            request=request,
            tenant_id="tenant-1",
            db=db,
        ),
        "upload": lambda: instance_files.upload_file(
            instance_id="instance-1",
            request=request,
            file=SimpleNamespace(read=AsyncMock(return_value=b"content"), filename="file.txt"),
            directory="",
            tenant_id="tenant-1",
            db=db,
        ),
        "delete": lambda: instance_files.delete_file(
            instance_id="instance-1",
            file_path="file.txt",
            request=request,
            tenant_id="tenant-1",
            db=db,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Instance not found"
    file_service.list_tree.assert_not_awaited()
    file_service.read_content.assert_not_awaited()
    file_service.read_bytes.assert_not_awaited()
    file_service.create.assert_not_awaited()
    file_service.upload.assert_not_awaited()
    file_service.delete.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_files_allows_owned_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(monkeypatch, SimpleNamespace(tenant_id="tenant-1"))
    file_service = FileServiceStub()
    monkeypatch.setattr(instance_files, "_get_file_service", lambda: file_service)

    result = await instance_files.list_files(
        instance_id="instance-1",
        request=SimpleNamespace(),
        tenant_id="tenant-1",
        db=SimpleNamespace(),
    )

    assert result == {"tree": []}
    file_service.list_tree.assert_awaited_once_with("instance-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_preview_file_sanitizes_missing_file_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(monkeypatch, SimpleNamespace(tenant_id="tenant-1"))
    file_service = FileServiceStub()
    file_service.read_content.side_effect = FileNotFoundError("secret/path.txt missing")
    monkeypatch.setattr(instance_files, "_get_file_service", lambda: file_service)

    with pytest.raises(HTTPException) as exc_info:
        await instance_files.preview_file(
            instance_id="instance-1",
            file_path="secret/path.txt",
            request=SimpleNamespace(),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "File not found"
    assert "secret/path.txt" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_file_sanitizes_conflict_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(monkeypatch, SimpleNamespace(tenant_id="tenant-1"))
    file_service = FileServiceStub()
    file_service.create.side_effect = FileExistsError("secret/path.txt already exists")
    monkeypatch.setattr(instance_files, "_get_file_service", lambda: file_service)

    with pytest.raises(HTTPException) as exc_info:
        await instance_files.create_file(
            instance_id="instance-1",
            body=instance_files.CreateFileRequest(path="secret/path.txt", type="file"),
            request=SimpleNamespace(),
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "File already exists"
    assert "secret/path.txt" not in exc_info.value.detail


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upload_file_sanitizes_validation_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_container(monkeypatch, SimpleNamespace(tenant_id="tenant-1"))
    file_service = FileServiceStub()
    file_service.upload.side_effect = ValueError("secret directory is invalid")
    monkeypatch.setattr(instance_files, "_get_file_service", lambda: file_service)

    with pytest.raises(HTTPException) as exc_info:
        await instance_files.upload_file(
            instance_id="instance-1",
            request=SimpleNamespace(),
            file=SimpleNamespace(read=AsyncMock(return_value=b"content"), filename="file.txt"),
            directory="secret",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid file request"
    assert "secret" not in exc_info.value.detail
