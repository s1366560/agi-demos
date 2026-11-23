"""Recognize credential-shaped values before persisting displayable text."""

import re

_SECRET_LIKE_ENV_VAR_PATTERNS = (
    re.compile(r"^(?:AKIA|ASIA)[A-Z0-9]{16}$"),
    re.compile(r"^GHP_[A-Z0-9]{20,}$"),
    re.compile(r"^GH(?:S|U|O|P)_[A-Z0-9]{20,}$"),
    re.compile(r"^GITHUB_PAT_[A-Z0-9_]{20,}$"),
    re.compile(r"^SK-PROJ-[A-Z0-9_-]{16,}$"),
    re.compile(r"^SK(?:_LIVE|_TEST)?_[A-Z0-9_]{16,}$"),
    re.compile(r"^MS_SK_[A-F0-9]{16,}$"),
    re.compile(r"^XOX[COPRSAB]-[A-Z0-9-]{10,}$"),
    re.compile(r"^XOX[BAPRS]_[A-Z0-9_]{10,}$"),
)
_SECRET_LIKE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"(?i)\bGHP_[A-Z0-9]{20,}\b"),
    re.compile(r"(?i)\bGH(?:S|U|O|P)_[A-Z0-9]{20,}\b"),
    re.compile(r"(?i)\bGITHUB_PAT_[A-Z0-9_]{20,}\b"),
    re.compile(r"(?i)\bBEARER\s+[A-Z0-9._-]{16,}\b"),
    re.compile(r"(?i)\bSK-PROJ-[A-Z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bSK-[A-Z0-9]{16,}\b"),
    re.compile(r"(?i)\bSK(?:_LIVE|_TEST)?_[A-Z0-9_]{16,}\b"),
    re.compile(r"(?i)\bMS_SK_[A-F0-9]{16,}\b"),
    re.compile(r"(?i)\bXOX[COPRSAB]-[A-Z0-9-]{10,}\b"),
    re.compile(r"(?i)\bXOX[BAPRS]_[A-Z0-9_]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
)
_SECRET_TEXT_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{8,}")


def is_secret_like_env_var_value(candidate: str) -> bool:
    """Return True when a value fully matches a high-confidence secret shape."""
    normalized = candidate.upper()
    return any(pattern.fullmatch(normalized) for pattern in _SECRET_LIKE_ENV_VAR_PATTERNS)


def contains_secret_like_text(value: str) -> bool:
    """Detect secret-like tokens in freeform text."""
    if any(pattern.search(value) for pattern in _SECRET_LIKE_TEXT_PATTERNS):
        return True
    return any(
        is_secret_like_env_var_value(token) for token in _SECRET_TEXT_TOKEN_RE.findall(value)
    )
