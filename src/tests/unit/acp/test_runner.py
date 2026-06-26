from __future__ import annotations

import pytest

from src.infrastructure.acp.client import ExternalACPAgentConfig
from src.infrastructure.acp.runner_cli import _labels_from_env, _validate_local_policy
from src.infrastructure.acp.runner_gateway import _labels_match
from src.infrastructure.adapters.secondary.persistence.sql_acp_runner_repository import (
    generate_runner_token,
    hash_runner_token,
)


def test_runner_token_hash_is_stable_and_does_not_store_plaintext() -> None:
    token = generate_runner_token()

    assert token.startswith("ms_acp_runner_")
    assert hash_runner_token(token) == hash_runner_token(token)
    assert hash_runner_token(token) != token


def test_runner_labels_match_required_subset() -> None:
    labels = {"region": "cn-shanghai", "gpu": "false", "tier": "edge"}

    assert _labels_match(labels, {"region": "cn-shanghai"})
    assert _labels_match(labels, {"region": "cn-shanghai", "tier": "edge"})
    assert not _labels_match(labels, {"region": "cn-beijing"})


def test_self_hosted_runner_parses_labels_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACP_RUNNER_LABELS", "region=cn-shanghai, tier=edge, malformed")

    assert _labels_from_env() == {"region": "cn-shanghai", "tier": "edge"}


def test_self_hosted_runner_rejects_disallowed_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ACP_RUNNER_ALLOWED_COMMANDS", "opencode,codex")
    config = ExternalACPAgentConfig(
        id="agent-1",
        name="Agent",
        transport="stdio",
        command="claude",
    )

    with pytest.raises(ValueError, match="command is not allowed"):
        _validate_local_policy(config=config, cwd="/workspace/project")


def test_self_hosted_runner_rejects_cwd_outside_allowed_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACP_RUNNER_ALLOWED_COMMANDS", "opencode")
    monkeypatch.setenv("ACP_RUNNER_CWD_ROOTS", "/workspace/project,/tmp/acp")
    config = ExternalACPAgentConfig(
        id="agent-1",
        name="Agent",
        transport="stdio",
        command="opencode",
    )

    _validate_local_policy(config=config, cwd="/workspace/project/service")
    with pytest.raises(ValueError, match="outside allowed roots"):
        _validate_local_policy(config=config, cwd="/Users/customer/private")
