"""Tests for AnnounceState enum and AnnounceConfig value object."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.domain.model.agent.announce_config import AnnounceConfig, AnnounceState


@pytest.mark.unit
class TestAnnounceState:
    def test_announce_state_values(self) -> None:
        assert AnnounceState.PENDING.value == "pending"
        assert AnnounceState.ANNOUNCING.value == "announcing"
        assert AnnounceState.ANNOUNCED.value == "announced"
        assert AnnounceState.FAILED.value == "failed"
        assert AnnounceState.EXPIRED.value == "expired"

    def test_announce_state_is_str_enum(self) -> None:
        assert isinstance(AnnounceState.PENDING, str)
        assert isinstance(AnnounceState.ANNOUNCING, str)
        assert isinstance(AnnounceState.ANNOUNCED, str)
        assert isinstance(AnnounceState.FAILED, str)
        assert isinstance(AnnounceState.EXPIRED, str)


@pytest.mark.unit
class TestAnnounceConfig:
    def test_default_values(self) -> None:
        config = AnnounceConfig()
        assert config.max_retries == 2
        assert config.retry_delay_ms == 200
        assert config.backoff_multiplier == 2.0
        assert config.max_retry_delay_ms == 5000
        assert config.expire_after_seconds == 300

    def test_frozen_immutability(self) -> None:
        config = AnnounceConfig()
        with pytest.raises(FrozenInstanceError):
            config.max_retries = 5  # type: ignore[misc]

    def test_delay_for_attempt_zero(self) -> None:
        config = AnnounceConfig(retry_delay_ms=100)
        assert config.delay_for_attempt(0) == 100

    def test_delay_for_attempt_with_backoff(self) -> None:
        config = AnnounceConfig(retry_delay_ms=100, backoff_multiplier=2.0)
        assert config.delay_for_attempt(1) == 200

    def test_delay_for_attempt_capped(self) -> None:
        config = AnnounceConfig(
            retry_delay_ms=100,
            backoff_multiplier=10.0,
            max_retry_delay_ms=500,
        )
        result = config.delay_for_attempt(5)
        assert result == 500

    def test_from_settings_reads_attributes(self) -> None:
        settings = Mock()
        settings.AGENT_SUBAGENT_ANNOUNCE_MAX_RETRIES = 5
        settings.AGENT_SUBAGENT_ANNOUNCE_RETRY_DELAY_MS = 500

        config = AnnounceConfig.from_settings(settings)
        assert config.max_retries == 5
        assert config.retry_delay_ms == 500

    def test_from_settings_uses_defaults(self) -> None:
        settings = SimpleNamespace()

        config = AnnounceConfig.from_settings(settings)
        assert config.max_retries == 2
        assert config.retry_delay_ms == 200

    def test_post_init_rejects_negative_retries(self) -> None:
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            AnnounceConfig(max_retries=-1)

    def test_post_init_rejects_negative_delay(self) -> None:
        with pytest.raises(ValueError, match="retry_delay_ms must be >= 0"):
            AnnounceConfig(retry_delay_ms=-1)

    def test_post_init_rejects_low_backoff(self) -> None:
        with pytest.raises(ValueError, match="backoff_multiplier must be >= 1.0"):
            AnnounceConfig(backoff_multiplier=0.5)

    def test_post_init_rejects_max_less_than_base(self) -> None:
        with pytest.raises(ValueError, match="max_retry_delay_ms.*must be >= retry_delay_ms"):
            AnnounceConfig(retry_delay_ms=1000, max_retry_delay_ms=500)

    def test_post_init_rejects_zero_expiry(self) -> None:
        with pytest.raises(ValueError, match="expire_after_seconds must be > 0"):
            AnnounceConfig(expire_after_seconds=0)
