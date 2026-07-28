"""Tests for the structured workspace file-browser MCP contract."""

import asyncio
import base64

from src.tools.registry import get_tool_registry
from src.tools.workspace_file_browser_tools import (
    download_workspace_file,
    list_workspace_files,
    read_workspace_file,
)


def test_structured_file_browser_lists_reads_and_downloads_workspace_files(
    tmp_path,
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (tmp_path / "payload.bin").write_bytes(b"\x00\x01\x02")

    listing_result = asyncio.run(
        list_workspace_files(
            path="/",
            limit=20,
            _workspace_dir=str(tmp_path),
        )
    )

    assert listing_result["isError"] is False
    listing = listing_result["listing"]
    assert listing["authority"] == "sandbox"
    assert listing["isolation"] == "isolated"
    assert listing["path"] == "/"
    assert [item["name"] for item in listing["entries"]] == ["docs", "payload.bin"]
    assert listing["entries"][0]["kind"] == "directory"
    assert listing["entries"][1]["kind"] == "file"

    read_result = asyncio.run(
        read_workspace_file(
            path="/docs/guide.md",
            max_bytes=1024,
            _workspace_dir=str(tmp_path),
        )
    )

    assert read_result["isError"] is False
    assert read_result["file"]["content"] == "# Guide\n"
    assert read_result["file"]["mime_type"] == "text/markdown"
    assert read_result["file"]["truncated"] is False

    download_result = asyncio.run(
        download_workspace_file(
            path="/payload.bin",
            max_bytes=1024,
            _workspace_dir=str(tmp_path),
        )
    )

    assert download_result["isError"] is False
    assert base64.b64decode(download_result["download"]["base64"]) == b"\x00\x01\x02"
    assert download_result["download"]["size_bytes"] == 3


def test_file_browser_cursor_is_revision_bound_and_rejects_stale_pages(tmp_path) -> None:
    for name in ["a.txt", "b.txt", "c.txt"]:
        (tmp_path / name).write_text(name, encoding="utf-8")

    first = asyncio.run(
        list_workspace_files(
            path="/",
            limit=2,
            _workspace_dir=str(tmp_path),
        )
    )
    cursor = first["listing"]["cursor"]
    assert isinstance(cursor, str)

    second = asyncio.run(
        list_workspace_files(
            path="/",
            limit=2,
            cursor=cursor,
            _workspace_dir=str(tmp_path),
        )
    )
    assert [item["name"] for item in second["listing"]["entries"]] == ["c.txt"]

    (tmp_path / "d.txt").write_text("changed", encoding="utf-8")
    stale = asyncio.run(
        list_workspace_files(
            path="/",
            limit=2,
            cursor=cursor,
            _workspace_dir=str(tmp_path),
        )
    )
    assert stale["isError"] is True
    assert stale["reason_code"] == "sandbox_file_cursor_stale"


def test_file_browser_fails_closed_on_traversal_symlinks_binary_reads_and_limits(
    tmp_path,
) -> None:
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "escape").symlink_to(outside)
    (tmp_path / "binary.dat").write_bytes(b"\xff\xfe")
    (tmp_path / "large.txt").write_text("abcdef", encoding="utf-8")

    traversal = asyncio.run(
        list_workspace_files(
            path="/../",
            _workspace_dir=str(tmp_path),
        )
    )
    assert traversal["isError"] is True
    assert traversal["reason_code"] == "sandbox_file_path_invalid"

    symlink = asyncio.run(
        read_workspace_file(
            path="/escape",
            _workspace_dir=str(tmp_path),
        )
    )
    assert symlink["isError"] is True
    assert symlink["reason_code"] == "sandbox_file_symlink_rejected"

    binary = asyncio.run(
        read_workspace_file(
            path="/binary.dat",
            _workspace_dir=str(tmp_path),
        )
    )
    assert binary["isError"] is True
    assert binary["reason_code"] == "sandbox_file_mime_not_text"

    oversized = asyncio.run(
        download_workspace_file(
            path="/large.txt",
            max_bytes=3,
            _workspace_dir=str(tmp_path),
        )
    )
    assert oversized["isError"] is True
    assert oversized["reason_code"] == "sandbox_file_too_large"


def test_structured_file_browser_tools_are_registered_for_platform_use() -> None:
    names = set(get_tool_registry().list_names())

    assert {
        "platform_list_workspace_files",
        "platform_read_workspace_file",
        "platform_download_workspace_file",
    } <= names
