"""Tests for local chat worker process setup."""

import sys
from types import SimpleNamespace

import pytest

from src.infrastructure.agent.actor import local_chat_worker
from src.infrastructure.telemetry import config


@pytest.mark.unit
def test_initialize_local_worker_telemetry_configures_langfuse_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detached workspace workers must configure LiteLLM callbacks in-process."""
    fake_litellm = SimpleNamespace(callbacks=[])
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            enable_telemetry=False,
            langfuse_enabled=True,
            langfuse_public_key="lf_pk_memstack_dev",
            langfuse_secret_key="lf_sk_memstack_dev",
            langfuse_host="http://localhost:3004",
            langfuse_sample_rate=1.0,
        ),
    )

    initialized = local_chat_worker._initialize_local_worker_telemetry()

    assert initialized is True
    assert fake_litellm.callbacks == ["langfuse_otel"]
