"""Resolve the response language for LLM/agent output.

Single source of truth for "what language should the agent reply in?".
Combines the request-scoped locale (set by `LocaleMiddleware` from
`X-Language` / `Accept-Language` / user `preferred_language`) with optional
runtime overrides supplied by the caller.

The resolver returns a canonical BCP-47 tag (`"zh-CN"` or `"en-US"`); the
companion `directive_for()` builder produces the `[Language Directive]`
system-prompt fragment used by `SystemPromptManager` and the workspace
runtime injector.

Why a dedicated module
----------------------
Several agent entry points (main ReAct loop, workspace actor, future
Sisyphus pathway) need the same logic. Keeping the resolver here prevents
drift between injection sites and makes the precedence explicit.
"""

from __future__ import annotations

from typing import Literal

from src.infrastructure.i18n import current_locale, normalize_locale

Language = Literal["zh-CN", "en-US"]

_DEFAULT_LANGUAGE: Language = "en-US"

# Map canonical Babel locale (`zh_CN`) → BCP-47 (`zh-CN`).
_LOCALE_TO_LANGUAGE: dict[str, Language] = {
    "zh_CN": "zh-CN",
    "en_US": "en-US",
}

_LANGUAGE_LABELS: dict[Language, str] = {
    "zh-CN": "Chinese (Simplified)",
    "en-US": "English",
}


def normalize_language(value: str | None) -> Language | None:
    """Normalize a free-form language hint to a supported BCP-47 tag.

    Returns ``None`` when the input is empty or not a supported language.
    Callers that need a "gate" (act only when an explicit preference
    exists) can use this to distinguish "no preference" from "resolved
    default" without re-implementing the precedence rules.
    """
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    # Accept both BCP-47 (`zh-CN`) and Babel (`zh_CN`) forms.
    bcp = cleaned.replace("_", "-")
    lower = bcp.lower()
    if lower in {"zh-cn", "zh", "zh-hans", "zh-hans-cn"}:
        return "zh-CN"
    if lower in {"en-us", "en", "en-gb"}:
        return "en-US"
    return None


def resolve_response_language(
    *,
    runtime_override: str | None = None,
    preferred_language: str | None = None,
) -> Language:
    """Resolve the response language using documented precedence.

    Precedence (highest first):
        1. ``runtime_override`` — per-turn override from runtime_context.
        2. ``preferred_language`` — typically the persisted
           ``User.preferred_language`` value.
        3. ``current_locale()`` — request-scoped locale set by
           ``LocaleMiddleware`` from ``X-Language`` / ``Accept-Language``.
        4. ``"en-US"`` — final default.
    """
    for candidate in (runtime_override, preferred_language):
        normalized = normalize_language(candidate)
        if normalized is not None:
            return normalized

    locale_value = current_locale()
    if locale_value:
        mapped = _LOCALE_TO_LANGUAGE.get(normalize_locale(locale_value) or "")
        if mapped is not None:
            return mapped

    return _DEFAULT_LANGUAGE


def directive_for(language: Language) -> str:
    """Render the ``[Language Directive]`` system-prompt fragment.

    The directive constrains user-facing natural language only; tool
    arguments, code, identifiers, and persisted workspace data stay in
    their original form so machine-readable surfaces remain stable.
    """
    label = _LANGUAGE_LABELS[language]
    return (
        "[Language Directive]\n"
        f"Respond to the user in {label} ({language}) unless the user "
        "explicitly requests another language. Keep tool arguments, code, "
        "identifiers, file paths, and persisted workspace data in their "
        "original language; only the natural-language portions of your "
        "reply should follow this preference."
    )
