"""Regression tests for the shared provider base-URL security policy."""

from __future__ import annotations

import pytest

from src.domain.llm_providers.models import ProviderType
from src.domain.llm_providers.security_policy import (
    environment_credential_endpoint_is_official,
    validate_provider_base_url,
)

pytestmark = pytest.mark.unit


class TestXaiOfficialEndpoints:
    def test_global_v1_endpoint_is_accepted(self):
        assert (
            validate_provider_base_url("https://api.x.ai/v1", ProviderType.XAI)
            == "https://api.x.ai/v1"
        )

    def test_us_regional_endpoint_is_official(self):
        assert (
            validate_provider_base_url("https://us.api.x.ai/v1", ProviderType.XAI)
            == "https://us.api.x.ai/v1"
        )
        assert environment_credential_endpoint_is_official(
            ProviderType.XAI, "https://us.api.x.ai/v1"
        )
        assert environment_credential_endpoint_is_official(ProviderType.XAI, "https://api.x.ai/v1")

    @pytest.mark.parametrize(
        "base_url",
        [
            "https://api.x.ai/v1/secret",
            "https://api.x.ai",
            "http://api.x.ai/v1",
        ],
    )
    def test_xai_fail_closed_rejections(self, base_url):
        with pytest.raises(ValueError, match="allowed API base path|HTTPS is required"):
            validate_provider_base_url(base_url, ProviderType.XAI)

    def test_lookalike_host_is_not_an_official_credential_endpoint(self):
        assert not environment_credential_endpoint_is_official(
            ProviderType.XAI, "https://api.x.ai.evil.com/v1"
        )


class TestKimiOfficialEndpoints:
    def test_kimi_coding_subscription_endpoint_is_accepted(self):
        assert (
            validate_provider_base_url("https://api.kimi.com/coding/v1", ProviderType.KIMI_CODING)
            == "https://api.kimi.com/coding/v1"
        )

    def test_kimi_coding_endpoint_normalizes_trailing_slash(self):
        assert (
            validate_provider_base_url("https://api.kimi.com/coding/v1/", ProviderType.KIMI)
            == "https://api.kimi.com/coding/v1"
        )

    def test_kimi_moonshot_origin_keeps_v1(self):
        assert (
            validate_provider_base_url("https://api.moonshot.cn/v1", ProviderType.KIMI)
            == "https://api.moonshot.cn/v1"
        )

    def test_kimi_coding_endpoint_counts_as_official_for_env_credentials(self):
        assert environment_credential_endpoint_is_official(
            ProviderType.KIMI_CODING, "https://api.kimi.com/coding/v1"
        )

    @pytest.mark.parametrize(
        "base_url",
        [
            # Unknown paths on the coding origin stay closed.
            "https://api.kimi.com/v1",
            "https://api.kimi.com/coding/v1/secret",
            # The coding path is not minted onto the moonshot origin.
            "https://api.moonshot.cn/coding/v1",
            # Transport must stay HTTPS on the default port.
            "http://api.kimi.com/coding/v1",
            "https://api.kimi.com:8443/coding/v1",
            # Lookalike hosts are not official origins.
            "https://api.kimi.com.evil.com/coding/v1",
        ],
    )
    def test_kimi_fail_closed_rejections(self, base_url):
        with pytest.raises(ValueError, match="allowed API base path|HTTPS is required"):
            validate_provider_base_url(base_url, ProviderType.KIMI_CODING)

    def test_loopback_http_is_allowed_for_a_local_fake_endpoint(self):
        assert (
            validate_provider_base_url("http://127.0.0.1:8010/v1", ProviderType.OPENAI)
            == "http://127.0.0.1:8010/v1"
        )
        assert (
            validate_provider_base_url("http://localhost:8010/v1", ProviderType.OPENAI)
            == "http://localhost:8010/v1"
        )

    def test_remote_http_stays_rejected(self):
        with pytest.raises(ValueError, match="HTTPS is required"):
            validate_provider_base_url("http://example.com/v1", ProviderType.OPENAI)

    def test_coding_endpoint_not_extended_to_other_families(self):
        with pytest.raises(ValueError, match="allowed API base path"):
            validate_provider_base_url("https://api.kimi.com/coding/v1", ProviderType.OPENAI)
