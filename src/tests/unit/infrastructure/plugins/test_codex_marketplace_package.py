"""Executable package/source boundary tests independent of external registries."""

from __future__ import annotations

import io
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from src.infrastructure.plugins import marketplace_sources
from src.infrastructure.plugins.codex_package import (
    CodexPackageError,
    inspect_codex_package,
    package_digest,
)
from src.infrastructure.plugins.marketplace_sources import (
    _extract_zip,
    _public_address,
    list_source_packages,
    snapshot_source,
)

EXAMPLE = (
    Path(__file__).resolve().parents[5] / "plugins/marketplace-examples/plugins/marketplace-demo"
)
pytestmark = pytest.mark.unit


@pytest.fixture
def package(tmp_path: Path) -> Path:
    target = tmp_path / "package"
    shutil.copytree(EXAMPLE, target)
    return target


def test_real_example_declares_four_capabilities(package: Path) -> None:
    result = inspect_codex_package(package, source_id="examples")
    assert result["descriptor"]["capabilities"] == ["skills", "mcp", "hooks", "apps"]
    assert result["descriptor"]["compatible"] is True
    assert result["descriptor"]["source_id"] == "examples"
    assert len(result["resources"]["hooks"]) == 3
    assert result["resources"]["skills"][0]["name"] == "plugin-demo"


def test_resource_changes_change_package_identity(package: Path) -> None:
    original = package_digest(package)
    (package / "scripts/demo_hook.py").write_text("print('changed')")
    assert package_digest(package) != original


@pytest.mark.parametrize(
    "relative", ["../outside", "/etc/passwd", "skills/../../outside", "..\\outside"]
)
def test_declared_paths_cannot_escape(package: Path, relative: str) -> None:
    manifest_path = package / ".codex-plugin/plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["skills"] = relative
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CodexPackageError, match="inside"):
        inspect_codex_package(package)


def test_symlink_is_rejected_even_when_not_declared(package: Path) -> None:
    (package / "leak").symlink_to("/etc/passwd")
    with pytest.raises(CodexPackageError, match="symlink"):
        inspect_codex_package(package)


def test_unknown_hook_marks_whole_package_incompatible(package: Path) -> None:
    (package / "hooks/hooks.json").write_text(
        json.dumps({"hooks": [{"event": "unknown", "command": "true"}]})
    )
    descriptor = inspect_codex_package(package)["descriptor"]
    assert descriptor["compatible"] is False
    assert "unsupported_hook_event:unknown" in descriptor["reasons"]


def test_proprietary_app_does_not_silently_install(package: Path) -> None:
    (package / ".app.json").write_text(
        json.dumps({"apps": {"private": {"connector_id": "codex-only"}}})
    )
    descriptor = inspect_codex_package(package)["descriptor"]
    assert descriptor["compatible"] is False
    assert descriptor["reasons"] == ["app_requires_accessible_mcp_server:private"]


def test_timeout_is_bounded(package: Path) -> None:
    (package / "hooks/hooks.json").write_text(
        json.dumps(
            {"hooks": [{"event": "session_start", "command": "true", "timeout_seconds": 31}]}
        )
    )
    with pytest.raises(CodexPackageError, match="timeout"):
        inspect_codex_package(package)


@pytest.mark.parametrize("server", [[], {}, 1, None])
def test_invalid_app_server_is_incompatible(package: Path, server: object) -> None:
    (package / ".app.json").write_text(json.dumps({"apps": {"invalid": {"mcp_server": server}}}))
    descriptor = inspect_codex_package(package)["descriptor"]
    assert descriptor["compatible"] is False
    assert "app_requires_accessible_mcp_server:invalid" in descriptor["reasons"]


@pytest.mark.parametrize("extra", [{"args": "--version"}, {"env": {"TOKEN": 42}}, {"headers": []}])
def test_malformed_mcp_configuration_rejected(package: Path, extra: dict) -> None:
    (package / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"demo": {"command": "python3", **extra}}})
    )
    with pytest.raises(CodexPackageError, match="MCP"):
        inspect_codex_package(package)


def test_oauth_declaration_requires_dedicated_client_integration(package: Path) -> None:
    (package / ".mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"demo": {"url": "https://example.com/mcp", "auth": {"type": "oauth"}}}}
        )
    )
    descriptor = inspect_codex_package(package)["descriptor"]
    assert descriptor["compatible"]
    assert not any(reason.startswith("oauth_") for reason in descriptor["reasons"])


@pytest.mark.parametrize("targets", [[], ["unknown"], [1], "local"])
def test_invalid_runtime_targets_rejected(package: Path, targets: object) -> None:
    path = package / ".codex-plugin/plugin.json"
    manifest = json.loads(path.read_text())
    path.write_text(json.dumps({**manifest, "targets": targets}))
    with pytest.raises(CodexPackageError, match="targets"):
        inspect_codex_package(package)


async def test_git_output_limit_kills_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawn = marketplace_sources.asyncio.create_subprocess_exec
    processes = []

    async def oversized_git(*args: str, **kwargs: object) -> object:
        process = await spawn(
            sys.executable,
            "-c",
            "import sys,time; sys.stdout.write('x'*4096); sys.stdout.flush(); time.sleep(60)",
            **kwargs,
        )
        processes.append(process)
        return process

    monkeypatch.setattr(marketplace_sources, "MAX_PACKAGE_BYTES", 1024)
    monkeypatch.setattr(
        marketplace_sources, "_public_address", lambda _: ("example.com", 443, "1.1.1.1", "/")
    )
    monkeypatch.setattr(marketplace_sources.asyncio, "create_subprocess_exec", oversized_git)
    with pytest.raises(CodexPackageError, match="output exceeds"):
        await marketplace_sources._git_snapshot("https://example.com/repo", tmp_path, None)
    assert len(processes) == 1
    assert processes[0].returncode is not None


async def test_snapshot_survives_source_change(package: Path, tmp_path: Path) -> None:
    destination = await snapshot_source("local", str(package), tmp_path / "snapshot")
    digest = package_digest(destination)
    (package / "README.md").write_text("changed")
    assert package_digest(destination) == digest
    assert list_source_packages(destination) == [destination]
    with pytest.raises(CodexPackageError, match="exists"):
        await snapshot_source("local", str(package), destination)


async def test_failed_snapshot_does_not_publish(package: Path, tmp_path: Path) -> None:
    (package / "link").symlink_to("/etc/passwd")
    destination = tmp_path / "snapshot"
    with pytest.raises(CodexPackageError):
        await snapshot_source("local", str(package), destination)
    assert not destination.exists()
    assert not list(tmp_path.glob("marketplace-*"))


@pytest.mark.parametrize("name", ["../escape", "/escape", "a/../../escape", "a\\..\\escape"])
def test_zip_slip_rejected(tmp_path: Path, name: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, "bad")
    with pytest.raises(CodexPackageError):
        _extract_zip(buffer.getvalue(), tmp_path)


def test_zip_symlink_rejected(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "../../outside")
    with pytest.raises(CodexPackageError, match="link"):
        _extract_zip(buffer.getvalue(), tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://127.0.0.1",
        "https://[::1]",
        "https://user:password@example.com",
        "file:///etc/passwd",
    ],
)
def test_remote_url_boundary(url: str) -> None:
    with pytest.raises(CodexPackageError):
        _public_address(url)


def test_catalog_paths_are_confined(tmp_path: Path) -> None:
    (tmp_path / "catalog.json").write_text(json.dumps({"plugins": [{"path": "../other"}]}))
    with pytest.raises(CodexPackageError):
        list_source_packages(tmp_path)


@pytest.mark.parametrize("transport", ["sse", "websocket", "stdio", "streamable-http", "http"])
def test_oauth_unsupported_transport_is_incompatible(package: Path, transport: str) -> None:
    (package / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "demo": {
                        "type": transport,
                        "url": "https://example.com/mcp",
                        "oauth": {"client_id": "test"},
                        **({"command": "python"} if transport == "http" else {}),
                    }
                }
            }
        )
    )
    descriptor = inspect_codex_package(package, source_id="examples")["descriptor"]
    assert descriptor["compatible"] is False
    assert "oauth_requires_streamable_http:demo" in descriptor["reasons"]
