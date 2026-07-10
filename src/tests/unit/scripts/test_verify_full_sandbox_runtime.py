"""Tests for the complete Sandbox image runtime verifier."""

from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from scripts.verify_full_sandbox_runtime import (
    BrowserRenderEvidence,
    _basic_auth_headers,
    _cross_network_probe_commands,
    _runtime_probe_command,
    _validate_browser_render_evidence,
    _verify_http_service_auth,
    _verify_network_metadata,
    _wait_http,
    verify_runtime_metadata,
)


def _browser_evidence() -> BrowserRenderEvidence:
    return BrowserRenderEvidence(
        desktop_title="sandbox:1 - KasmVNC",
        desktop_body="Connected (encrypted) to sandbox:1",
        desktop_canvas_count=3,
        desktop_screenshot_size=20_000,
        terminal_title="ttyd - Terminal",
        terminal_input_count=1,
        terminal_before_digest="before",
        terminal_after_digest="after",
        console_errors=(),
    )


def _attrs() -> dict[str, object]:
    return {
        "Config": {
            "Image": "sandbox-mcp-server:full-ci",
            "User": "sandbox",
            "Env": [
                "MCP_AUTH_ENABLED=true",
                "MCP_ALLOW_LOCALHOST=false",
                "MCP_STATIC_TOKEN=private-capability",
                "DESKTOP_ENABLED=true",
                "TERMINAL_ENABLED=true",
            ],
            "Labels": {
                "memstack.sandbox": "true",
                "memstack.sandbox.network": "true",
            },
        },
        "HostConfig": {
            "Privileged": False,
            "Binds": ["/tmp/workspace:/workspace:rw"],
            "NetworkMode": "memstack-full-runtime-a",
            "PortBindings": {
                "8765/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18765"}],
                "6080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "16080"}],
                "7681/tcp": [{"HostIp": "127.0.0.1", "HostPort": "17681"}],
            },
        },
    }


def test_verify_runtime_metadata_accepts_full_contract() -> None:
    verify_runtime_metadata(
        _attrs(),
        expected_image="sandbox-mcp-server:full-ci",
        expected_network="memstack-full-runtime-a",
    )


@patch("scripts.verify_full_sandbox_runtime.httpx.Client")
def test_wait_http_can_probe_self_signed_desktop_tls(client_class: MagicMock) -> None:
    response = MagicMock(status_code=200, text="desktop-ready")
    client_class.return_value.__enter__.return_value.get.return_value = response

    assert _wait_http("https://127.0.0.1:16080/", verify_tls=False) == "desktop-ready"
    client_class.assert_called_once_with(timeout=5.0, follow_redirects=True, verify=False)


def test_basic_auth_headers_do_not_place_capability_in_url() -> None:
    assert _basic_auth_headers("private-capability") == {
        "Authorization": "Basic c2FuZGJveDpwcml2YXRlLWNhcGFiaWxpdHk="
    }


def test_browser_render_evidence_requires_connected_interactive_surfaces() -> None:
    _validate_browser_render_evidence(_browser_evidence())

    missing_canvas = replace(_browser_evidence(), desktop_canvas_count=0)
    with pytest.raises(RuntimeError, match="canvas"):
        _validate_browser_render_evidence(missing_canvas)

    unchanged_terminal = replace(
        _browser_evidence(),
        terminal_after_digest=_browser_evidence().terminal_before_digest,
    )
    with pytest.raises(RuntimeError, match="visual state"):
        _validate_browser_render_evidence(unchanged_terminal)

    console_error = replace(_browser_evidence(), console_errors=("WebSocket failed",))
    with pytest.raises(RuntimeError, match="console"):
        _validate_browser_render_evidence(console_error)


@patch("scripts.verify_full_sandbox_runtime.httpx.Client")
def test_verify_http_service_auth_rejects_missing_and_wrong_credentials(
    client_class: MagicMock,
) -> None:
    client = client_class.return_value.__enter__.return_value
    client.get.side_effect = [
        MagicMock(status_code=401),
        MagicMock(status_code=401),
        MagicMock(status_code=200),
    ]

    _verify_http_service_auth(
        "https://127.0.0.1:16080/",
        "private-capability",
        verify_tls=False,
    )

    assert client.get.call_args_list[0].kwargs == {}
    assert client.get.call_args_list[1].kwargs == {
        "headers": _basic_auth_headers("wrong-capability")
    }
    assert client.get.call_args_list[2].kwargs == {
        "headers": _basic_auth_headers("private-capability")
    }


def test_cross_network_probes_require_authentication_on_every_private_service() -> None:
    commands = _cross_network_probe_commands(
        victim_ip="172.24.0.2",
        attacker_token="attacker-capability",
    )
    rendered = "\n".join(" ".join(command) for command in commands)

    assert "172.24.0.2" in rendered
    assert "8765" in rendered
    assert "6080" in rendered
    assert "7681" in rendered
    assert "attacker-capability" in rendered
    assert "private-capability" not in rendered
    assert "import websockets" not in rendered


def test_runtime_probe_reports_the_failing_contract_item() -> None:
    command = _runtime_probe_command()

    assert command[:2] == ["bash", "-lc"]
    assert "missing command: $command" in command[2]
    assert "ttyd process is not running" in command[2]
    assert "Xvnc process is not running" in command[2]


def test_verify_network_metadata_requires_inter_container_denial() -> None:
    network = MagicMock()
    network.attrs = {
        "Options": {"com.docker.network.bridge.enable_icc": "false"},
    }

    _verify_network_metadata(network)

    network.attrs = {"Options": {}}
    with pytest.raises(RuntimeError, match="inter-container communication"):
        _verify_network_metadata(network)


@pytest.mark.parametrize(
    ("section", "key", "value", "message"),
    [
        ("Config", "User", "root", "non-root"),
        ("HostConfig", "Privileged", True, "privileged"),
        ("HostConfig", "NetworkMode", "bridge", "dedicated network"),
        (
            "HostConfig",
            "PortBindings",
            {
                "8765/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18765"}],
                "6080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "16080"}],
                "7681/tcp": [{"HostIp": "127.0.0.1", "HostPort": "17681"}],
            },
            "loopback",
        ),
    ],
)
def test_verify_runtime_metadata_rejects_unsafe_contract(
    section: str,
    key: str,
    value: object,
    message: str,
) -> None:
    attrs = _attrs()
    nested = attrs[section]
    assert isinstance(nested, dict)
    nested[key] = value

    with pytest.raises(RuntimeError, match=message):
        verify_runtime_metadata(
            attrs,
            expected_image="sandbox-mcp-server:full-ci",
            expected_network="memstack-full-runtime-a",
        )
