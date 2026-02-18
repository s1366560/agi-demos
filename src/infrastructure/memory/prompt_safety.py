"""Prompt injection detection and content sanitization.

Ported from Moltbot's auto-capture safety checks.
Detects adversarial instructions in memory content.
"""

from __future__ import annotations

import re

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"forget\s+(?:all\s+)?(?:previous|above|prior)\s+instructions", re.IGNORECASE),
    re.compile(
        r"override\s+(?:all\s+)?(?:system|safety)\s*(?:prompt|instructions)?", re.IGNORECASE
    ),
    re.compile(r"system\s+prompt\s*(?:is|was|says|reads)", re.IGNORECASE),
    re.compile(r"<\s*(?:system|assistant|developer)\b", re.IGNORECASE),
    re.compile(r"\byou\s+are\s+now\s+a\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+if\s+you\b", re.IGNORECASE),
    re.compile(r"\bpretend\s+(?:to\s+be|you\s+are)\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+follow\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bDAN\s+mode\b", re.IGNORECASE),
]


def looks_like_prompt_injection(text: str) -> bool:
    """Check if text contains patterns resembling prompt injection.

    Args:
        text: Content to check.

    Returns:
        True if any injection pattern is detected.
    """
    if not text:
        return False
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


def sanitize_for_context(text: str) -> str:
    """Sanitize memory content for safe inclusion in LLM context.

    Escapes XML-like tags that could be interpreted as role markers.

    Args:
        text: Raw memory content.

    Returns:
        Sanitized text safe for context injection.
    """
    # Escape XML-like tags that could be interpreted as system/role markers
    text = re.sub(r"<(/?)system\b", r"&lt;\1system", text, flags=re.IGNORECASE)
    text = re.sub(r"<(/?)assistant\b", r"&lt;\1assistant", text, flags=re.IGNORECASE)
    text = re.sub(r"<(/?)developer\b", r"&lt;\1developer", text, flags=re.IGNORECASE)
    text = re.sub(r"<(/?)user\b", r"&lt;\1user", text, flags=re.IGNORECASE)
    return text
