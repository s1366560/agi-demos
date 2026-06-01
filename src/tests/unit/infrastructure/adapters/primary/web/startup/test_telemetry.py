"""Tests for web telemetry startup."""

import os
import sys
from types import SimpleNamespace

import pytest

from src.infrastructure.adapters.primary.web.startup import telemetry


@pytest.mark.unit
async def test_initialize_telemetry_configures_langfuse_otel_when_otel_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Langfuse tracing should not depend on the app-wide OTel switch."""
    fake_litellm = SimpleNamespace(callbacks=["langfuse", "custom"])
    settings = SimpleNamespace(
        enable_telemetry=False,
        langfuse_enabled=True,
        langfuse_public_key="lf_pk_memstack_dev",
        langfuse_secret_key="lf_sk_memstack_dev",
        langfuse_host="http://localhost:3001",
        langfuse_sample_rate=1.0,
    )

    monkeypatch.setattr(telemetry, "settings", settings)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_OTEL_HOST", raising=False)

    initialized = await telemetry.initialize_telemetry()

    assert initialized is True
    assert fake_litellm.callbacks == ["custom", "langfuse_otel"]
    assert os.environ["LANGFUSE_PUBLIC_KEY"] == "lf_pk_memstack_dev"
    assert os.environ["LANGFUSE_SECRET_KEY"] == "lf_sk_memstack_dev"
    assert os.environ["LANGFUSE_OTEL_HOST"] == "http://localhost:3001"
