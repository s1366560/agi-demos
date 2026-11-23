"""Real filesystem checks for the advertised workspace write contract."""

import asyncio
import os

import pytest

from src.tools.file_tools import create_write_tool, write_file


@pytest.mark.asyncio
async def test_write_contract_is_explicit_and_writes_utf8_under_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    result = await write_file("nested/marker.txt", "真实写入", _workspace_dir=str(root))
    assert not result.get("isError")
    assert (root / "nested/marker.txt").read_text() == "真实写入"
    assert create_write_tool().workspace_write_contract == "directory-fd-write-v1"


@pytest.mark.asyncio
@pytest.mark.parametrize("path_kind", ["parent", "absolute", "symlink", "hardlink"])
async def test_workspace_write_refuses_external_target(tmp_path, path_kind):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("unchanged")
    if path_kind == "parent":
        requested = "../outside.txt"
    elif path_kind == "absolute":
        requested = str(outside)
    elif path_kind == "symlink":
        (root / "link").symlink_to(tmp_path, target_is_directory=True)
        requested = "link/outside.txt"
    else:
        os.link(outside, root / "alias.txt")
        requested = "alias.txt"
    result = await write_file(requested, "changed", mode="append", _workspace_dir=str(root))
    assert result.get("isError")
    assert outside.read_text() == "unchanged"


@pytest.mark.asyncio
async def test_directory_swapped_to_symlink_before_worker_write_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    parent = root / "nested"
    parent.mkdir()
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "marker.txt").write_text("unchanged")
    original = asyncio.to_thread
    swapped = False

    async def swap_then_write(function, *args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            parent.rename(root / "old-nested")
            parent.symlink_to(outside, target_is_directory=True)
        return await original(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", swap_then_write)
    result = await write_file("nested/marker.txt", "changed", _workspace_dir=str(root))
    assert result.get("isError")
    assert (outside / "marker.txt").read_text() == "unchanged"


@pytest.mark.asyncio
async def test_concurrent_append_preserves_every_accepted_write(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    results = await asyncio.gather(
        *(
            write_file("events.txt", f"{index}\n", mode="append", _workspace_dir=str(root))
            for index in range(20)
        )
    )
    assert all(not result.get("isError") for result in results)
    assert sorted((root / "events.txt").read_text().splitlines(), key=int) == [
        str(i) for i in range(20)
    ]


@pytest.mark.asyncio
async def test_plain_directory_never_advertises_mount_confinement(tmp_path):
    from src.server.websocket_server import MCPWebSocketServer
    from src.tools.confined_workspace_write import workspace_mount_id

    root = tmp_path / "ordinary"
    root.mkdir()
    assert workspace_mount_id(str(root)) is None
    server = MCPWebSocketServer(workspace_dir=str(root))
    server.register_tool(create_write_tool())
    tools = await server._handle_list_tools()
    assert "_meta" not in tools["tools"][0]
    result = await write_file(
        "marker.txt",
        "must not write",
        _workspace_dir=str(root),
        _workspace_write_contract="directory-fd-write-v1",
    )
    assert result.get("isError")
    assert not (root / "marker.txt").exists()
