from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from src.infrastructure.security.oauth_login import (
    OAuthLoginService,
    OAuthProviderConfiguration,
    OAuthProviderUnavailableError,
    OAuthStateInvalidError,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


def google_configuration() -> OAuthProviderConfiguration:
    return OAuthProviderConfiguration(
        provider_id="google",
        display_name="Google",
        client_id="client-id",
        client_secret="client-secret",
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scopes=("openid", "email", "profile"),
        requires_verified_email=True,
    )


def github_configuration() -> OAuthProviderConfiguration:
    return OAuthProviderConfiguration(
        provider_id="github",
        display_name="GitHub",
        client_id="client-id",
        client_secret="client-secret",
        authorization_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        email_url="https://api.github.com/user/emails",
        scopes=("read:user", "user:email"),
        requires_verified_email=True,
    )


@pytest.mark.unit
class TestOAuthLoginService:
    async def test_begin_authorization_persists_opaque_one_time_state_with_pkce(self) -> None:
        redis = FakeRedis()
        service = OAuthLoginService(
            public_base_url="https://app.memstack.example",
            providers={"google": google_configuration()},
        )

        authorization = await service.begin_authorization(
            redis,
            provider_id="google",
            redirect_to="/tenant/t-1/overview",
        )

        query = parse_qs(urlparse(authorization.authorization_url).query)
        assert query["client_id"] == ["client-id"]
        assert query["redirect_uri"] == ["https://app.memstack.example/login/callback/google"]
        assert query["code_challenge_method"] == ["S256"]
        assert len(query["code_challenge"][0]) >= 43
        assert "redirect_to" not in query["state"][0]
        assert len(redis.values) == 1
        stored_payload = json.loads(next(iter(redis.values.values())))
        assert stored_payload["redirect_to"] == "/tenant/t-1/overview"
        assert stored_payload["provider_id"] == "google"
        assert stored_payload["callback_surface"] == "web"
        assert stored_payload["code_verifier"]

    async def test_begin_authorization_uses_the_dedicated_desktop_callback_surface(
        self,
    ) -> None:
        redis = FakeRedis()
        service = OAuthLoginService(
            public_base_url="https://app.memstack.example",
            providers={"github": github_configuration()},
        )

        authorization = await service.begin_authorization(
            redis,
            provider_id="github",
            redirect_to="/tenant/t-1/project/p-1/overview",
            callback_surface="desktop",
        )

        query = parse_qs(urlparse(authorization.authorization_url).query)
        assert query["redirect_uri"] == ["agistack-auth://oauth/callback/github"]
        stored_payload = json.loads(next(iter(redis.values.values())))
        assert stored_payload == {
            "callback_surface": "desktop",
            "code_verifier": stored_payload["code_verifier"],
            "provider_id": "github",
            "redirect_to": "/tenant/t-1/project/p-1/overview",
            "redirect_uri": "agistack-auth://oauth/callback/github",
        }

    async def test_exchange_callback_consumes_state_and_returns_verified_identity(self) -> None:
        redis = FakeRedis()
        service = OAuthLoginService(
            public_base_url="https://app.memstack.example",
            providers={"google": google_configuration()},
        )
        authorization = await service.begin_authorization(
            redis,
            provider_id="google",
            redirect_to="/tenant/t-1/overview",
        )
        state = parse_qs(urlparse(authorization.authorization_url).query)["state"][0]

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL("https://oauth2.googleapis.com/token"):
                body = (await request.aread()).decode()
                assert "client_secret=client-secret" in body
                assert "code_verifier=" in body
                return httpx.Response(200, json={"access_token": "provider-token"})
            assert request.url == httpx.URL("https://openidconnect.googleapis.com/v1/userinfo")
            assert request.headers["authorization"] == "Bearer provider-token"
            return httpx.Response(
                200,
                json={
                    "sub": "subject-1",
                    "email": "USER@example.com",
                    "email_verified": True,
                    "name": "OAuth User",
                    "picture": "https://images.example/avatar.png",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await service.exchange_callback(
                redis,
                provider_id="google",
                code="authorization-code",
                state=state,
                http_client=client,
            )

        assert result.redirect_to == "/tenant/t-1/overview"
        assert result.identity.provider_id == "google"
        assert result.identity.subject == "subject-1"
        assert result.identity.email == "user@example.com"
        assert result.identity.email_verified is True

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(OAuthStateInvalidError):
                await service.exchange_callback(
                    redis,
                    provider_id="google",
                    code="authorization-code",
                    state=state,
                    http_client=client,
                )

    async def test_rejects_unknown_provider_without_creating_state(self) -> None:
        redis = FakeRedis()
        service = OAuthLoginService(
            public_base_url="https://app.memstack.example",
            providers={"google": google_configuration()},
        )

        with pytest.raises(OAuthProviderUnavailableError):
            await service.begin_authorization(
                redis,
                provider_id="unknown",
                redirect_to="/",
            )

        assert redis.values == {}

    async def test_rejects_browser_normalized_cross_origin_redirect_before_state_write(
        self,
    ) -> None:
        redis = FakeRedis()
        service = OAuthLoginService(
            public_base_url="https://app.memstack.example",
            providers={"google": google_configuration()},
        )

        with pytest.raises(ValueError, match="same-origin"):
            await service.begin_authorization(
                redis,
                provider_id="google",
                redirect_to="/\\attacker.example/path",
            )

        assert redis.values == {}

    async def test_exchange_callback_accepts_github_numeric_subject(self) -> None:
        redis = FakeRedis()
        service = OAuthLoginService(
            public_base_url="https://app.memstack.example",
            providers={"github": github_configuration()},
        )
        authorization = await service.begin_authorization(
            redis,
            provider_id="github",
            redirect_to="/",
        )
        state = parse_qs(urlparse(authorization.authorization_url).query)["state"][0]

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url == httpx.URL("https://github.com/login/oauth/access_token"):
                return httpx.Response(200, json={"access_token": "provider-token"})
            if request.url == httpx.URL("https://api.github.com/user"):
                return httpx.Response(
                    200,
                    json={"id": 123456, "login": "octocat", "name": "Octo Cat"},
                )
            assert request.url == httpx.URL("https://api.github.com/user/emails")
            return httpx.Response(
                200,
                json=[{"email": "octo@example.com", "verified": True, "primary": True}],
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await service.exchange_callback(
                redis,
                provider_id="github",
                code="authorization-code",
                state=state,
                http_client=client,
            )

        assert result.identity.subject == "123456"
        assert result.identity.email == "octo@example.com"
        assert result.identity.email_verified is True

    async def test_rejects_provider_mismatch_and_consumes_the_state(self) -> None:
        redis = FakeRedis()
        service = OAuthLoginService(
            public_base_url="https://app.memstack.example",
            providers={"google": google_configuration()},
        )
        authorization = await service.begin_authorization(
            redis,
            provider_id="google",
            redirect_to="/",
        )
        state = parse_qs(urlparse(authorization.authorization_url).query)["state"][0]

        with pytest.raises(OAuthStateInvalidError):
            await service.exchange_callback(
                redis,
                provider_id="github",
                code="authorization-code",
                state=state,
            )

        assert redis.values == {}
