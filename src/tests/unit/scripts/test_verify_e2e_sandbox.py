"""Tests for the authenticated Sandbox E2E verifier."""

import pytest

from scripts.verify_e2e_sandbox import verify_sandbox_container, verify_tool_result


def _container_attrs() -> dict[str, object]:
    return {
        "Config": {
            "Image": "sandbox-mcp-server:lite",
            "User": "sandbox",
            "Env": [
                "MCP_AUTH_ENABLED=true",
                "MCP_ALLOW_LOCALHOST=false",
                "MCP_STATIC_TOKEN=private-capability",
                "DESKTOP_ENABLED=false",
                "TERMINAL_ENABLED=false",
            ],
        },
        "HostConfig": {
            "Privileged": False,
            "Binds": ["/tmp/memstack-project:/workspace:rw"],
            "PortBindings": {
                "8765/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18765"}],
            },
        },
    }


def test_verify_sandbox_container_accepts_least_privilege_contract() -> None:
    verify_sandbox_container(_container_attrs(), expected_image="sandbox-mcp-server:lite")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("Config", "User", "root"), "non-root"),
        (("HostConfig", "Privileged", True), "privileged"),
        (("HostConfig", "Binds", ["/var/run/docker.sock:/var/run/docker.sock:rw"]), "socket"),
        (
            (
                "HostConfig",
                "PortBindings",
                {"8765/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18765"}]},
            ),
            "loopback",
        ),
    ],
)
def test_verify_sandbox_container_rejects_unsafe_runtime(
    mutation: tuple[str, str, object],
    message: str,
) -> None:
    attrs = _container_attrs()
    section, key, value = mutation
    nested = attrs[section]
    assert isinstance(nested, dict)
    nested[key] = value

    with pytest.raises(RuntimeError, match=message):
        verify_sandbox_container(attrs, expected_image="sandbox-mcp-server:lite")


def test_verify_sandbox_container_rejects_lite_terminal_drift() -> None:
    attrs = _container_attrs()
    config = attrs["Config"]
    assert isinstance(config, dict)
    environment = config["Env"]
    assert isinstance(environment, list)
    environment.append("TERMINAL_ENABLED=true")

    with pytest.raises(RuntimeError, match="terminal"):
        verify_sandbox_container(attrs, expected_image="sandbox-mcp-server:lite")


def test_verify_tool_result_accepts_success_and_expected_text() -> None:
    verify_tool_result(
        {
            "success": True,
            "is_error": False,
            "content": [{"type": "text", "text": "E2E_SANDBOX_OK"}],
        },
        expected_text="E2E_SANDBOX_OK",
    )


def test_verify_tool_result_accepts_expected_rejection() -> None:
    verify_tool_result(
        {
            "success": False,
            "is_error": True,
            "content": [{"type": "text", "text": "outside workspace"}],
        },
        expect_error=True,
    )
