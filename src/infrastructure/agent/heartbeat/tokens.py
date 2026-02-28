"""Heartbeat token constants and stripping utilities.

Ported from OpenClaw's auto-reply/tokens.ts and auto-reply/heartbeat.ts.

Provides:
- HEARTBEAT_TOKEN constant
- strip_heartbeat_token() — removes HEARTBEAT_OK from agent replies
- is_heartbeat_content_effectively_empty() — checks if HEARTBEAT.md has
  no actionable content (only comments/headers/empty lines)
"""

from __future__ import annotations

import re

# The token the agent emits when heartbeat check finds nothing actionable.
HEARTBEAT_TOKEN: str = "HEARTBEAT_OK"

# Regex for HTML tags
_HTML_TAG_RE = re.compile(r"<[^>]*>")
# Regex for &nbsp;
_NBSP_RE = re.compile(r"&nbsp;", re.IGNORECASE)
# Regex for leading markdown wrappers
_MD_LEADING_RE = re.compile(r"^[*`~_]+")
# Regex for trailing markdown wrappers
_MD_TRAILING_RE = re.compile(r"[*`~_]+$")


def is_heartbeat_content_effectively_empty(content: str | None) -> bool:
    """Check if HEARTBEAT.md content has no actionable tasks.

    A file is considered effectively empty if it contains only:
    - Whitespace
    - Comment lines (lines starting with # — valid ATX headers)
    - Empty markdown list items (``- [ ]``, ``* [ ]``, ``- ``)
    - Empty lines

    A missing file (None) returns False so the LLM can still decide
    what to do. This function is only for when the file exists but
    has no real content.

    Args:
        content: The raw HEARTBEAT.md content, or None if the file is missing.

    Returns:
        True if the file exists but contains no actionable instructions.
    """
    if content is None:
        return False

    # ATX header regex: # followed by space-or-EOL (not #TODO or #hashtag)
    header_re = re.compile(r"^#+(\s|$)")
    # Empty list items: "- [ ]", "* [ ]", "- ", etc.
    empty_list_re = re.compile(r"^[-*+]\s*(\[[\sXx]?\]\s*)?$")
    # HTML comment blocks
    html_comment_re = re.compile(r"^<!--.*?-->$", re.DOTALL)

    for line in content.split("\n"):
        trimmed = line.strip()
        if not trimmed:
            continue
        if header_re.match(trimmed):
            continue
        if empty_list_re.match(trimmed):
            continue
        if html_comment_re.match(trimmed):
            continue
        # Found a non-empty, non-comment line — actionable content exists
        return False

    return True


def _strip_markup(text: str) -> str:
    """Normalize lightweight markup so wrapped HEARTBEAT_OK tokens still strip.

    Handles: HTML tags, &nbsp;, and leading/trailing markdown wrappers.
    """
    result = _HTML_TAG_RE.sub(" ", text)
    result = _NBSP_RE.sub(" ", result)
    result = _MD_LEADING_RE.sub("", result)
    result = _MD_TRAILING_RE.sub("", result)
    return result


def _strip_token_at_edges(raw: str) -> tuple[str, bool]:
    """Strip HEARTBEAT_OK from the leading and trailing edges of text.

    Returns:
        Tuple of (cleaned_text, did_strip).
    """
    text = raw.strip()
    if not text:
        return ("", False)

    token = HEARTBEAT_TOKEN
    if token not in text:
        return (text, False)

    # Regex to match token at end with up to 4 trailing non-word chars
    token_at_end_re = re.compile(re.escape(token) + r"[^\w]{0,4}$")

    did_strip = False
    changed = True
    while changed:
        changed = False
        text = text.strip()

        # Strip token at start
        if text.startswith(token):
            after = text[len(token) :].lstrip()
            text = after
            did_strip = True
            changed = True
            continue

        # Strip token at end (with up to 4 trailing non-word chars)
        match = token_at_end_re.search(text)
        if match:
            idx = text.rfind(token)
            before = text[:idx].rstrip()
            if not before:
                text = ""
            else:
                after = text[idx + len(token) :].lstrip()
                text = f"{before}{after}".rstrip()
            did_strip = True
            changed = True

    # Collapse whitespace
    collapsed = re.sub(r"\s+", " ", text).strip()
    return (collapsed, did_strip)


def strip_heartbeat_token(
    raw: str | None,
    *,
    mode: str = "message",
    max_ack_chars: int = 300,
) -> tuple[bool, str, bool]:
    """Strip HEARTBEAT_OK from an agent reply.

    Ported from OpenClaw's stripHeartbeatToken().

    Args:
        raw: The raw reply text from the agent.
        mode: Either "heartbeat" or "message". In heartbeat mode, replies
            whose remaining text (after token stripping) is at or below
            max_ack_chars are treated as empty acknowledgements.
        max_ack_chars: Maximum character count for an ack-only reply.

    Returns:
        Tuple of (should_skip, text, did_strip):
        - should_skip: True if the reply should be suppressed entirely.
        - text: The cleaned reply text (empty string if should_skip).
        - did_strip: Whether the HEARTBEAT_OK token was found and removed.
    """
    if not raw or not raw.strip():
        return (True, "", False)

    trimmed = raw.strip()

    # Check both original and markup-normalized versions
    trimmed_normalized = _strip_markup(trimmed)
    has_token = HEARTBEAT_TOKEN in trimmed or HEARTBEAT_TOKEN in trimmed_normalized

    if not has_token:
        return (False, trimmed, False)

    # Try stripping from original first, then from normalized
    stripped_original_text, stripped_original_did = _strip_token_at_edges(trimmed)
    stripped_normalized_text, stripped_normalized_did = _strip_token_at_edges(trimmed_normalized)

    # Pick whichever actually stripped and has content
    if stripped_original_did and stripped_original_text:
        picked_text, picked_did = stripped_original_text, stripped_original_did
    else:
        picked_text, picked_did = stripped_normalized_text, stripped_normalized_did

    if not picked_did:
        return (False, trimmed, False)

    if not picked_text:
        return (True, "", True)

    rest = picked_text.strip()
    if mode == "heartbeat" and len(rest) <= max_ack_chars:
        return (True, "", True)

    return (False, rest, True)
