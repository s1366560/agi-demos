"""HTTP header helpers shared by FastAPI routers."""

from __future__ import annotations

from urllib.parse import quote


def content_disposition_attachment(filename: str) -> str:
    """Build a safe attachment Content-Disposition value for arbitrary filenames."""
    header_filename = filename.replace("\r", "_").replace("\n", "_")
    fallback = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in {'"', "\\", ";", "/"} else "_"
        for ch in header_filename
    ).strip()
    ascii_filename = fallback or "download"
    encoded_filename = quote(header_filename, safe="")
    return f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
