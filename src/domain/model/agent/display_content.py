"""Explicit presentation text never replaces the model-visible user content."""

MAX_DISPLAY_CONTENT_BYTES = 65_536


def validate_display_content(value: object) -> str:
    """Preserve the original text after validating the bounded protocol field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("display_content requires a nonempty string")
    if len(value.encode("utf-8")) > MAX_DISPLAY_CONTENT_BYTES:
        raise ValueError("display_content exceeds the UTF-8 byte limit")
    return value
