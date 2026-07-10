"""Tests for fail-closed MCP server authentication configuration."""

from src.server.main import _auth_config_from_env


def test_auth_environment_defaults_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("MCP_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("MCP_ALLOW_LOCALHOST", raising=False)
    monkeypatch.delenv("MCP_STATIC_TOKEN", raising=False)

    config = _auth_config_from_env()

    assert config.enabled is True
    assert config.allow_localhost is False
    assert config.static_token is None


def test_auth_environment_allows_explicit_development_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("MCP_AUTH_ENABLED", "false")
    monkeypatch.setenv("MCP_ALLOW_LOCALHOST", "true")

    config = _auth_config_from_env()

    assert config.enabled is False
    assert config.allow_localhost is True
