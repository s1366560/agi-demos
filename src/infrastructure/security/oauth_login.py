"""Server-owned OAuth login authority with one-time state and PKCE."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlencode, urlparse

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPOSITORY_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
_STATE_TTL_SECONDS = 600
_HTTP_TIMEOUT_SECONDS = 15.0


class OAuthStateStore(Protocol):
    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool,
    ) -> object: ...

    async def getdel(self, key: str) -> str | bytes | None: ...


@dataclass(frozen=True, slots=True)
class OAuthProviderConfiguration:
    provider_id: str
    display_name: str
    client_id: str
    client_secret: str = field(repr=False)
    authorization_url: str
    token_url: str
    userinfo_url: str
    scopes: tuple[str, ...]
    requires_verified_email: bool
    email_url: str | None = None


@dataclass(frozen=True, slots=True)
class OAuthProviderDescriptor:
    id: str
    display_name: str


@dataclass(frozen=True, slots=True)
class OAuthAuthorization:
    provider_id: str
    authorization_url: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class OAuthIdentity:
    provider_id: str
    subject: str
    email: str
    email_verified: bool
    display_name: str
    avatar_url: str | None


@dataclass(frozen=True, slots=True)
class OAuthCallbackResult:
    identity: OAuthIdentity
    redirect_to: str


class OAuthLoginError(Exception):
    """Base class for stable OAuth authority failures."""


class OAuthProviderUnavailableError(OAuthLoginError):
    """The requested provider has no complete server configuration."""


class OAuthStateStoreUnavailableError(OAuthLoginError):
    """The one-time OAuth state store is unavailable."""


class OAuthStateInvalidError(OAuthLoginError):
    """OAuth state is missing, expired, consumed, or belongs to another provider."""


class OAuthProviderExchangeError(OAuthLoginError):
    """The provider rejected the code exchange or identity request."""


class OAuthProviderIdentityError(OAuthLoginError):
    """The provider identity is incomplete or its email is unverified."""


class OAuthLoginSettings(BaseSettings):
    """Dedicated auth-provider settings, isolated from the shared application Settings hub."""

    public_base_url: str | None = Field(default=None, alias="OAUTH_PUBLIC_BASE_URL")
    google_client_id: str | None = Field(default=None, alias="OAUTH_GOOGLE_CLIENT_ID")
    google_client_secret: SecretStr | None = Field(
        default=None,
        alias="OAUTH_GOOGLE_CLIENT_SECRET",
    )
    github_client_id: str | None = Field(default=None, alias="OAUTH_GITHUB_CLIENT_ID")
    github_client_secret: SecretStr | None = Field(
        default=None,
        alias="OAUTH_GITHUB_CLIENT_SECRET",
    )

    model_config = SettingsConfigDict(
        env_file=_REPOSITORY_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def _same_origin_redirect(value: str | None) -> str:
    candidate = (value or "/").strip()
    has_unsafe_character = "\\" in candidate or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in candidate
    )
    if not candidate.startswith("/") or candidate.startswith("//") or has_unsafe_character:
        raise ValueError("OAuth redirect target must be a same-origin path")
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        raise ValueError("OAuth redirect target must be a same-origin path")
    return candidate


def _normalized_public_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    is_loopback_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        (parsed.scheme != "https" and not is_loopback_http)
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("OAUTH_PUBLIC_BASE_URL must be an HTTPS origin or loopback HTTP origin")
    return candidate


def _state_key(state: str) -> str:
    digest = hashlib.sha256(state.encode("utf-8")).hexdigest()
    return f"memstack:oauth_login:state:{digest}"


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _string_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _subject_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return None


class OAuthLoginService:
    """Confidential-client OAuth flow; browser receives no provider credentials."""

    def __init__(
        self,
        *,
        public_base_url: str,
        providers: dict[str, OAuthProviderConfiguration],
    ) -> None:
        self._public_base_url = _normalized_public_base_url(public_base_url)
        self._providers = dict(providers)

    def list_providers(self) -> tuple[OAuthProviderDescriptor, ...]:
        return tuple(
            OAuthProviderDescriptor(id=config.provider_id, display_name=config.display_name)
            for config in sorted(self._providers.values(), key=lambda item: item.provider_id)
        )

    def _provider(self, provider_id: str) -> OAuthProviderConfiguration:
        normalized_id = provider_id.strip().casefold()
        provider = self._providers.get(normalized_id)
        if provider is None:
            raise OAuthProviderUnavailableError
        return provider

    def _redirect_uri(
        self,
        provider_id: str,
        callback_surface: Literal["web", "desktop"],
    ) -> str:
        if callback_surface == "desktop":
            return f"agistack-auth://oauth/callback/{provider_id}"
        return f"{self._public_base_url}/login/callback/{provider_id}"

    async def begin_authorization(
        self,
        state_store: OAuthStateStore,
        *,
        provider_id: str,
        redirect_to: str,
        callback_surface: Literal["web", "desktop"] = "web",
    ) -> OAuthAuthorization:
        provider = self._provider(provider_id)
        safe_redirect = _same_origin_redirect(redirect_to)
        state = secrets.token_urlsafe(32)
        code_verifier, code_challenge = _pkce_pair()
        redirect_uri = self._redirect_uri(provider.provider_id, callback_surface)
        state_payload = json.dumps(
            {
                "callback_surface": callback_surface,
                "provider_id": provider.provider_id,
                "redirect_to": safe_redirect,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        try:
            stored = await state_store.set(
                _state_key(state),
                state_payload,
                ex=_STATE_TTL_SECONDS,
                nx=True,
            )
        except Exception as exc:
            raise OAuthStateStoreUnavailableError from exc
        if stored is False or stored is None:
            raise OAuthStateStoreUnavailableError

        query = urlencode(
            {
                "client_id": provider.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(provider.scopes),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return OAuthAuthorization(
            provider_id=provider.provider_id,
            authorization_url=f"{provider.authorization_url}?{query}",
            expires_in=_STATE_TTL_SECONDS,
        )

    async def exchange_callback(
        self,
        state_store: OAuthStateStore,
        *,
        provider_id: str,
        code: str,
        state: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> OAuthCallbackResult:
        if not code.strip() or not state.strip():
            raise OAuthStateInvalidError
        try:
            raw_state = await state_store.getdel(_state_key(state))
        except Exception as exc:
            raise OAuthStateStoreUnavailableError from exc
        if raw_state is None:
            raise OAuthStateInvalidError

        try:
            decoded_state = raw_state.decode("utf-8") if isinstance(raw_state, bytes) else raw_state
            state_payload = json.loads(decoded_state)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
            raise OAuthStateInvalidError from exc
        normalized_provider_id = provider_id.strip().casefold()
        if (
            not isinstance(state_payload, dict)
            or state_payload.get("provider_id") != normalized_provider_id
        ):
            raise OAuthStateInvalidError

        provider = self._provider(normalized_provider_id)

        redirect_to = state_payload.get("redirect_to")
        redirect_uri = state_payload.get("redirect_uri")
        callback_surface = state_payload.get("callback_surface", "web")
        code_verifier = state_payload.get("code_verifier")
        if (
            not isinstance(redirect_to, str)
            or not isinstance(redirect_uri, str)
            or callback_surface not in {"web", "desktop"}
            or redirect_uri
            != self._redirect_uri(
                provider.provider_id,
                callback_surface,
            )
            or not isinstance(code_verifier, str)
            or not code_verifier
        ):
            raise OAuthStateInvalidError
        try:
            safe_redirect = _same_origin_redirect(redirect_to)
        except ValueError as exc:
            raise OAuthStateInvalidError from exc

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)
        try:
            access_token = await self._exchange_code(
                client,
                provider,
                code=code.strip(),
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
            )
            identity = await self._load_identity(client, provider, access_token)
        finally:
            if owns_client:
                await client.aclose()
        return OAuthCallbackResult(identity=identity, redirect_to=safe_redirect)

    async def _exchange_code(
        self,
        client: httpx.AsyncClient,
        provider: OAuthProviderConfiguration,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str,
    ) -> str:
        try:
            response = await client.post(
                provider.token_url,
                data={
                    "client_id": provider.client_id,
                    "client_secret": provider.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthProviderExchangeError from exc
        access_token = _string_field(payload, "access_token") if isinstance(payload, dict) else None
        if access_token is None:
            raise OAuthProviderExchangeError
        return access_token

    async def _load_identity(
        self,
        client: httpx.AsyncClient,
        provider: OAuthProviderConfiguration,
        access_token: str,
    ) -> OAuthIdentity:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        try:
            response = await client.get(provider.userinfo_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthProviderExchangeError from exc
        if not isinstance(payload, dict):
            raise OAuthProviderIdentityError

        subject = _subject_field(payload, "sub") or _subject_field(payload, "id")
        email = _string_field(payload, "email")
        email_verified = payload.get("email_verified") is True
        if provider.email_url and (email is None or not email_verified):
            email, email_verified = await self._load_verified_email(client, provider, headers)

        if (
            subject is None
            or email is None
            or "@" not in email
            or (provider.requires_verified_email and not email_verified)
        ):
            raise OAuthProviderIdentityError
        display_name = _string_field(payload, "name") or email
        avatar_url = _string_field(payload, "picture") or _string_field(payload, "avatar_url")
        return OAuthIdentity(
            provider_id=provider.provider_id,
            subject=subject,
            email=email.casefold(),
            email_verified=email_verified,
            display_name=display_name,
            avatar_url=avatar_url,
        )

    async def _load_verified_email(
        self,
        client: httpx.AsyncClient,
        provider: OAuthProviderConfiguration,
        headers: dict[str, str],
    ) -> tuple[str | None, bool]:
        if provider.email_url is None:
            return None, False
        try:
            response = await client.get(provider.email_url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OAuthProviderExchangeError from exc
        if not isinstance(payload, list):
            raise OAuthProviderIdentityError
        verified = [
            item for item in payload if isinstance(item, dict) and item.get("verified") is True
        ]
        primary = next((item for item in verified if item.get("primary") is True), None)
        selected = primary or (verified[0] if verified else None)
        email = _string_field(selected, "email") if isinstance(selected, dict) else None
        return email, email is not None


def build_oauth_login_service(settings: OAuthLoginSettings | None = None) -> OAuthLoginService:
    resolved = settings or OAuthLoginSettings()
    public_base_url = resolved.public_base_url or "https://oauth.invalid"
    providers: dict[str, OAuthProviderConfiguration] = {}
    if resolved.public_base_url and resolved.google_client_id and resolved.google_client_secret:
        providers["google"] = OAuthProviderConfiguration(
            provider_id="google",
            display_name="Google",
            client_id=resolved.google_client_id,
            client_secret=resolved.google_client_secret.get_secret_value(),
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            scopes=("openid", "email", "profile"),
            requires_verified_email=True,
        )
    if resolved.public_base_url and resolved.github_client_id and resolved.github_client_secret:
        providers["github"] = OAuthProviderConfiguration(
            provider_id="github",
            display_name="GitHub",
            client_id=resolved.github_client_id,
            client_secret=resolved.github_client_secret.get_secret_value(),
            authorization_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            userinfo_url="https://api.github.com/user",
            email_url="https://api.github.com/user/emails",
            scopes=("read:user", "user:email"),
            requires_verified_email=True,
        )
    return OAuthLoginService(public_base_url=public_base_url, providers=providers)


@lru_cache
def get_oauth_login_service() -> OAuthLoginService:
    return build_oauth_login_service()


__all__ = [
    "OAuthAuthorization",
    "OAuthCallbackResult",
    "OAuthIdentity",
    "OAuthLoginService",
    "OAuthLoginSettings",
    "OAuthProviderConfiguration",
    "OAuthProviderDescriptor",
    "OAuthProviderExchangeError",
    "OAuthProviderIdentityError",
    "OAuthProviderUnavailableError",
    "OAuthStateInvalidError",
    "OAuthStateStoreUnavailableError",
    "build_oauth_login_service",
    "get_oauth_login_service",
]
