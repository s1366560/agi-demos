"""Locale negotiation and request-scoped current-locale storage.

`SUPPORTED_LOCALES` lists every locale we ship translations for. `DEFAULT_LOCALE`
is the fallback when negotiation fails (browser sent something we don't speak).

`resolve_locale` parses an `Accept-Language` header (RFC 9110), respects an
explicit `X-Language` override, and matches against supported locales using
language-tag prefixing (e.g. `en` matches `en_US`).

`current_locale` returns the request-scoped locale via a `ContextVar`, which
plays nicely with `asyncio` task-local semantics under FastAPI.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Final

# Canonical codes use underscores (Babel convention). Frontend / Accept-Language
# typically use hyphens (en-US); `normalize_locale` handles both.
SUPPORTED_LOCALES: Final[tuple[str, ...]] = ("en_US", "zh_CN")
DEFAULT_LOCALE: Final[str] = "en_US"

_current_locale: ContextVar[str] = ContextVar("memstack_current_locale", default=DEFAULT_LOCALE)


def normalize_locale(code: str | None) -> str | None:
    """Convert a hyphen-separated locale tag to Babel underscore form.

    Returns ``None`` when the input is falsy. Case is normalized so the language
    part is lowercase and the region part is uppercase (``zh-cn`` → ``zh_CN``).
    """
    if not code:
        return None
    code = code.strip().replace("-", "_")
    if not code:
        return None
    parts = code.split("_")
    parts[0] = parts[0].lower()
    if len(parts) > 1:
        parts[1] = parts[1].upper()
    return "_".join(parts)


def _match_supported(candidate: str) -> str | None:
    """Match an arbitrary candidate against `SUPPORTED_LOCALES`.

    Exact match wins; otherwise match by language prefix (`en` → `en_US`).
    """
    if candidate in SUPPORTED_LOCALES:
        return candidate
    language = candidate.split("_", 1)[0]
    for supported in SUPPORTED_LOCALES:
        if supported.split("_", 1)[0] == language:
            return supported
    return None


def _parse_accept_language(header: str) -> list[tuple[str, float]]:
    """Parse `Accept-Language` into ``(tag, quality)`` pairs, sorted by quality."""
    items: list[tuple[str, float]] = []
    for raw in header.split(","):
        token = raw.strip()
        if not token:
            continue
        if ";" in token:
            tag, _, params = token.partition(";")
            tag = tag.strip()
            quality = 1.0
            for param in params.split(";"):
                key, sep, value = param.strip().partition("=")
                if sep and key.strip() == "q":
                    try:
                        quality = float(value.strip())
                    except ValueError:
                        quality = 0.0
                    break
        else:
            tag = token
            quality = 1.0
        if tag:
            items.append((tag, quality))
    items.sort(key=lambda pair: pair[1], reverse=True)
    return items


def resolve_locale(
    accept_language: str | None = None,
    explicit: str | None = None,
) -> str:
    """Pick the best supported locale for a request.

    Priority: explicit override (e.g. `X-Language` header or query param) →
    Accept-Language preference order → `DEFAULT_LOCALE`.
    """
    explicit_normalized = normalize_locale(explicit)
    if explicit_normalized:
        matched = _match_supported(explicit_normalized)
        if matched:
            return matched

    if accept_language:
        for raw_tag, _quality in _parse_accept_language(accept_language):
            normalized = normalize_locale(raw_tag)
            if not normalized:
                continue
            matched = _match_supported(normalized)
            if matched:
                return matched

    return DEFAULT_LOCALE


def current_locale() -> str:
    """Return the locale active for the current async task / request."""
    return _current_locale.get()


def set_current_locale(code: str) -> object:
    """Set the current locale, returning a token usable with `reset_current_locale`.

    The token mirrors `ContextVar.set` so callers can restore the previous
    value in finally blocks (or use the `using_locale` context manager).
    """
    normalized = normalize_locale(code) or DEFAULT_LOCALE
    matched = _match_supported(normalized) or DEFAULT_LOCALE
    return _current_locale.set(matched)


def reset_current_locale(token: object) -> None:
    """Reset the current locale to the value captured by `set_current_locale`."""
    from contextvars import Token

    if isinstance(token, Token):
        _current_locale.reset(token)
