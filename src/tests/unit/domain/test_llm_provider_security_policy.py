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

    def test_remote_http_is_rejected(self):
        with pytest.raises(ValueError, match="HTTPS is required"):
            validate_provider_base_url("http://api.x.ai/v1", ProviderType.XAI)

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

    def test_remote_http_is_rejected(self):
        with pytest.raises(ValueError, match="HTTPS is required"):
            validate_provider_base_url("http://api.kimi.com/coding/v1", ProviderType.KIMI_CODING)

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


class TestArbitraryBasePathsAccepted:
    """The API base path is user-controlled configuration; only transport is validated."""

    @pytest.mark.parametrize(
        ("base_url", "expected"),
        [
            # Z.AI coding-plan gateway path from a real provider edit screen.
            (
                "https://open.bigmodel.cn/api/coding/paas/v4",
                "https://open.bigmodel.cn/api/coding/paas/v4",
            ),
            # Unknown paths on a coding origin are no longer special-cased.
            ("https://api.kimi.com/v1", "https://api.kimi.com/v1"),
            ("https://api.kimi.com/coding/v1/secret", "https://api.kimi.com/coding/v1/secret"),
            ("https://api.moonshot.cn/coding/v1", "https://api.moonshot.cn/coding/v1"),
            # Coding paths extend to other families without restriction.
            (
                "https://api.kimi.com/coding/v1",
                "https://api.kimi.com/coding/v1",
            ),
            # Gateway bearer-like path segments and custom proxies are accepted.
            ("https://proxy.example/tenant-token", "https://proxy.example/tenant-token"),
            ("https://api.x.ai/v1/secret", "https://api.x.ai/v1/secret"),
            # Empty paths remain valid.
            ("https://api.x.ai", "https://api.x.ai"),
        ],
    )
    def test_base_path_is_accepted_and_normalized(self, base_url, expected):
        assert validate_provider_base_url(base_url, ProviderType.OPENAI) == expected

    def test_zai_coding_gateway_path_is_accepted_for_its_family(self):
        assert (
            validate_provider_base_url(
                "https://open.bigmodel.cn/api/coding/paas/v4", ProviderType.ZAI_CODING
            )
            == "https://open.bigmodel.cn/api/coding/paas/v4"
        )

    def test_structural_invalidity_stays_rejected(self):
        with pytest.raises(ValueError, match="Invalid provider base URL"):
            validate_provider_base_url("https://api.x.ai/v1?token=x", ProviderType.XAI)
        with pytest.raises(ValueError, match="Invalid provider base URL"):
            validate_provider_base_url("https://user:pass@api.x.ai/v1", ProviderType.XAI)
