"""Security policy shared by provider persistence, probing, and runtime execution."""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import quote, urlsplit, urlunsplit

from src.domain.llm_providers.provider_catalog import (
    FAMILY_SECURITY,
    extra_official_endpoints,
    family_security,
    official_base_paths,
    probe_default_base_urls,
    provider_family,
)

_PROVIDER_PROBE_DEFAULT_BASE_URLS: dict[str, str] = probe_default_base_urls()
_OFFICIAL_PROVIDER_BASE_PATHS: dict[str, frozenset[str]] = official_base_paths()
_PROVIDER_EXTRA_OFFICIAL_ENDPOINTS: dict[str, dict[str, frozenset[str]]] = (
    extra_official_endpoints()
)

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


def _families_where(
    *,
    probe_supported: bool | None = None,
    persistent_auth: bool | None = None,
) -> frozenset[str]:
    selected: set[str] = set()
    for family, spec in FAMILY_SECURITY.items():
        if probe_supported is not None and spec.probe_supported is probe_supported:
            selected.add(family)
        if persistent_auth is not None and spec.persistent_auth is persistent_auth:
            selected.add(family)
    return frozenset(selected)


_PERSISTENT_AUTH_UNAVAILABLE_PROVIDER_FAMILIES = _families_where(persistent_auth=False)
_PROBE_UNSUPPORTED_PROVIDER_FAMILIES = _families_where(probe_supported=False)


def normalize_provider_family(provider_type: object) -> str:
    """Normalize enum/string provider variants to their base provider family."""
    return provider_family(provider_type)


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
    if _extra_official_base_paths(provider_type, value) is not None:
        return True
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


def _extra_official_base_paths(provider_type: object, value: str) -> frozenset[str] | None:
    """Return allowed base paths when the URL targets an extra official origin."""
    endpoints = _PROVIDER_EXTRA_OFFICIAL_ENDPOINTS.get(normalize_provider_family(provider_type))
    if not endpoints:
        return None
    try:
        candidate = urlsplit(value)
        candidate_port = candidate.port
    except ValueError:
        return None
    if not candidate.hostname or candidate.scheme != "https":
        return None
    if _effective_port(candidate.scheme, candidate_port) != 443:
        return None
    return endpoints.get(candidate.hostname.casefold())


def _validate_provider_transport(
    *,
    scheme: str,
    hostname: str,
    provider_family: str,
) -> None:
    """Validate remote HTTPS and loopback-only local HTTP transports."""
    spec = family_security(provider_family)
    is_local_provider = bool(spec and spec.local_http)
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
    extra_paths = _extra_official_base_paths(provider_type, value)
    if extra_paths is not None:
        return extra_paths
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
