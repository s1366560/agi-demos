"""Security policy shared by provider persistence, probing, and runtime execution."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import quote, urlsplit, urlunsplit

_PROVIDER_VARIANT_SUFFIXES: tuple[str, ...] = ("_coding", "_embedding", "_reranker")

_PROVIDER_PROBE_DEFAULT_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "gemini": "https://generativelanguage.googleapis.com",
    "anthropic": "https://api.anthropic.com",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "minimax": "https://api.minimax.io/v1",
    "zai": "https://open.bigmodel.cn/api/paas/v4",
    "kimi": "https://api.moonshot.cn/v1",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "cohere": "https://api.cohere.com/v1",
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234/v1",
}

_OFFICIAL_PROVIDER_BASE_PATHS: dict[str, frozenset[str]] = {
    "openai": frozenset({"/v1"}),
    "openrouter": frozenset({"/api/v1"}),
    "dashscope": frozenset({"/compatible-mode/v1"}),
    "gemini": frozenset({"", "/v1beta"}),
    "anthropic": frozenset({"", "/v1"}),
    "groq": frozenset({"/openai/v1"}),
    "mistral": frozenset({"/v1"}),
    "deepseek": frozenset({"/v1"}),
    "minimax": frozenset({"/v1"}),
    "zai": frozenset({"/api/paas/v4"}),
    "kimi": frozenset({"/v1"}),
    "volcengine": frozenset({"/api/v3"}),
    "cohere": frozenset({"/v1"}),
    "ollama": frozenset({"", "/api"}),
    "lmstudio": frozenset({"/v1"}),
}

# Custom gateways are permitted, but only at well-known API base paths. Arbitrary
# path components are rejected because they are commonly used for bearer-like
# gateway tokens and would otherwise be returned by ordinary Provider responses.
_SAFE_CUSTOM_PROVIDER_BASE_PATHS = frozenset(
    {
        "",
        "/v1",
        "/v1beta",
        "/api",
        "/api/v1",
        "/api/v3",
        "/api/paas/v4",
        "/openai/v1",
        "/compatible-mode/v1",
    }
)

_PERSISTENT_AUTH_UNAVAILABLE_PROVIDER_FAMILIES = frozenset({"bedrock", "vertex"})
_PROBE_UNSUPPORTED_PROVIDER_FAMILIES = frozenset({"azure_openai", "bedrock", "vertex"})


def normalize_provider_family(provider_type: object) -> str:
    """Normalize enum/string provider variants to their base provider family."""
    normalized = str(getattr(provider_type, "value", provider_type)).strip().lower()
    for suffix in _PROVIDER_VARIANT_SUFFIXES:
        if normalized.endswith(suffix):
            return normalized.removesuffix(suffix)
    return normalized


def provider_probe_default_base_url(provider_type: object) -> str | None:
    """Return the canonical probe base URL for a provider family."""
    return _PROVIDER_PROBE_DEFAULT_BASE_URLS.get(normalize_provider_family(provider_type))


def provider_probe_supported(provider_type: object) -> bool:
    """Return whether this backend has a safe, executable connection probe."""
    return normalize_provider_family(provider_type) not in _PROBE_UNSUPPORTED_PROVIDER_FAMILIES


def provider_persistent_auth_supported(provider_type: object) -> bool:
    """Return whether structured persistent credentials exist for this provider."""
    return (
        normalize_provider_family(provider_type)
        not in _PERSISTENT_AUTH_UNAVAILABLE_PROVIDER_FAMILIES
    )


def _normalized_path(path: str) -> str:
    if path in {"", "/"}:
        return ""
    return path.rstrip("/")


def _effective_port(scheme: str, port: int | None) -> int | None:
    if port is not None:
        return port
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None


def _is_official_origin(provider_type: object, value: str) -> bool:
    default_base_url = provider_probe_default_base_url(provider_type)
    if default_base_url is None:
        return False
    candidate = urlsplit(value)
    official = urlsplit(default_base_url)
    try:
        candidate_port = candidate.port
        official_port = official.port
    except ValueError:
        return False
    return bool(
        candidate.hostname
        and official.hostname
        and candidate.scheme == official.scheme
        and candidate.hostname.casefold() == official.hostname.casefold()
        and _effective_port(candidate.scheme, candidate_port)
        == _effective_port(official.scheme, official_port)
    )


def _validate_provider_transport(
    *,
    scheme: str,
    hostname: str,
    provider_family: str,
) -> None:
    """Validate remote HTTPS and loopback-only local HTTP transports."""
    is_local_provider = provider_family in {"ollama", "lmstudio"}
    if not is_local_provider and scheme != "https":
        raise ValueError("HTTPS is required for credentialed providers")
    if not is_local_provider or scheme != "http":
        return
    is_loopback = hostname.casefold() == "localhost"
    if not is_loopback:
        try:
            is_loopback = ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if not is_loopback:
        raise ValueError("HTTP is only allowed for local provider endpoints")


def _allowed_provider_base_paths(provider_type: object, value: str) -> frozenset[str]:
    """Return the exact path set allowed for an official or custom origin."""
    if not _is_official_origin(provider_type, value):
        return _SAFE_CUSTOM_PROVIDER_BASE_PATHS
    provider_family = normalize_provider_family(provider_type)
    return _OFFICIAL_PROVIDER_BASE_PATHS.get(provider_family, frozenset({""}))


def validate_provider_base_url(
    value: str | None,
    provider_type: object,
) -> str | None:
    """Validate transport and an explicit, non-secret provider API base path."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid provider base URL") from exc
    if parsed.scheme not in {"http", "https"} or hostname is None:
        raise ValueError("Invalid provider base URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Invalid provider base URL")
    if parsed.query or parsed.fragment:
        raise ValueError("Invalid provider base URL")

    _validate_provider_transport(
        scheme=parsed.scheme,
        hostname=hostname,
        provider_family=normalize_provider_family(provider_type),
    )

    path = _normalized_path(parsed.path)
    if path not in _allowed_provider_base_paths(provider_type, normalized):
        raise ValueError("Provider base URL path is not an allowed API base path")

    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def environment_credential_endpoint_is_official(
    provider_type: object,
    base_url: str | None,
) -> bool:
    """Return whether an environment credential stays on an official safe endpoint."""
    default_base_url = provider_probe_default_base_url(provider_type)
    if default_base_url is None:
        return False
    try:
        candidate = validate_provider_base_url(base_url or default_base_url, provider_type)
    except ValueError:
        return False
    return candidate is not None and _is_official_origin(provider_type, candidate)


def append_provider_url_segments(base_url: str, segments: tuple[str, ...]) -> str:
    """Append probe path segments without duplicating an existing suffix/prefix."""
    parsed = urlsplit(base_url)
    existing = [segment for segment in parsed.path.split("/") if segment]
    overlap = 0
    for candidate in range(min(len(existing), len(segments)), -1, -1):
        if existing[len(existing) - candidate :] == list(segments[:candidate]):
            overlap = candidate
            break
    path_segments = existing + [quote(segment, safe="") for segment in segments[overlap:]]
    path = f"/{'/'.join(path_segments)}" if path_segments else ""
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
