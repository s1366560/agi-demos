"""Project declared REPL output using accepted, durably stored media bindings."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, TypeGuard

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.result import ToolAttachment

DISPLAY_ANNOTATION = "x-agistack-display-kind"
MEDIA_TYPES = {
    "image": frozenset({"image/png", "image/jpeg", "image/webp"}),
    "audio": frozenset({"audio/wav", "audio/x-wav", "audio/mpeg", "audio/ogg"}),
}
MAX_MEDIA_BYTES = 10 * 1024 * 1024
MAX_CELL_MEDIA_BYTES = 32 * 1024 * 1024
_MEDIA_FIELDS = frozenset({"kind", "artifact_id", "mime_type", "size_bytes"})


def declared_repl(schema: dict[str, Any]) -> bool:
    return schema.get(DISPLAY_ANNOTATION) == "repl_output"


def _identifier(value: object) -> TypeGuard[str]:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 256
        and all(c.isascii() and (c.isalnum() or c in "_-") for c in value)
    )


def _text_entries(texts: list[object]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in texts:
        if not isinstance(entry, dict) or entry.get("type") != "text":
            raise ValueError("Invalid text entry")
        text = entry.get("text")
        if not isinstance(text, str):
            raise ValueError("Invalid text content")
        result.append({"kind": "text", "text": text})
    return result


def _bindings(references: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for reference in references:
        if not isinstance(reference, dict):
            raise ValueError("Invalid media binding")
        native_id = reference.get("native_attachment_id")
        if not _identifier(native_id) or native_id in bindings:
            raise ValueError("Invalid media identity")
        bindings[native_id] = reference
    return bindings


def _media_entries(media: list[object], references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bindings = _bindings(references)
    result: list[dict[str, Any]] = []
    accepted: set[str] = set()
    for entry in media:
        if (
            not isinstance(entry, dict)
            or not _MEDIA_FIELDS.issubset(entry)
            or not set(entry).issubset(_MEDIA_FIELDS | {"url", "store"})
        ):
            raise ValueError("Invalid media descriptor")
        kind, native_id = entry["kind"], entry["artifact_id"]
        mime, size = entry["mime_type"], entry["size_bytes"]
        if (
            not isinstance(kind, str)
            or kind not in MEDIA_TYPES
            or not _identifier(native_id)
            or native_id in accepted
            or not isinstance(mime, str)
            or mime not in MEDIA_TYPES[kind]
            or type(size) is not int
            or not 0 < size <= 9_007_199_254_740_991
        ):
            raise ValueError("Invalid media format")
        accepted.add(native_id)
        binding = bindings.get(native_id)
        if (
            binding is None
            or binding.get("native_mime_type", binding.get("mime_type")) != mime
            or binding.get("size_bytes") != size
        ):
            raise ValueError("Media binding mismatch")
        stored_mime = binding.get("mime_type")
        if stored_mime != mime and (mime, stored_mime) != ("audio/x-wav", "audio/wav"):
            raise ValueError("Stored media MIME mismatch")
        result.append(
            {"kind": kind, "mimeType": stored_mime, "sizeBytes": size, "_binding": binding}
        )
    if accepted != set(bindings):
        raise ValueError("Media binding coverage mismatch")
    return result


def _ordered_entries(
    order: object, entries: dict[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    count = sum(len(values) for values in entries.values())
    if order is None:
        if entries["text"] and entries["media"]:
            raise ValueError("Mixed output requires explicit order")
        source = "text" if entries["text"] else "media"
        order = [{"source": source, "index": index} for index in range(count)]
    if not isinstance(order, list) or len(order) != count:
        raise ValueError("Invalid output order")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in order:
        if not isinstance(item, dict) or set(item) != {"source", "index"}:
            raise ValueError("Invalid output order entry")
        source, index = item["source"], item["index"]
        if (
            not isinstance(source, str)
            or source not in entries
            or type(index) is not int
            or not 0 <= index < len(entries[source])
            or (source, index) in seen
        ):
            raise ValueError("Output order coverage mismatch")
        seen.add((source, index))
        result.append(entries[source][index])
    return result


def _entries(output: object, references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(output, str):
        output = json.loads(output)
    if not isinstance(output, dict):
        raise ValueError("Invalid output")
    texts, media = output.get("outputs", []), output.get("artifacts", [])
    if not isinstance(texts, list) or not isinstance(media, list):
        raise ValueError("Invalid output entries")
    if not 0 < len(texts) + len(media) <= 256:
        raise ValueError("Invalid output entry count")
    entries = {"text": _text_entries(texts), "media": _media_entries(media, references)}
    return _ordered_entries(output.get("output_order"), entries)


def _within_limit(entry: dict[str, Any], admitted_bytes: int) -> bool:
    size = entry["sizeBytes"]
    if isinstance(size, bool) or not isinstance(size, int):
        return False
    return bool(size <= MAX_MEDIA_BYTES and admitted_bytes + size <= MAX_CELL_MEDIA_BYTES)


def select_repl_attachments(
    output: object, attachments: list[ToolAttachment]
) -> tuple[list[ToolAttachment], list[dict[str, Any]]]:
    """Select actual accepted bytes in display order; omitted refs never acquire fake cloud IDs."""
    references = [
        {
            "native_attachment_id": item.name,
            "mime_type": item.mime_type,
            "size_bytes": len(item.content),
        }
        for item in attachments
        if isinstance(item.content, bytes)
    ]
    try:
        entries = _entries(output, references)
    except (ValueError, TypeError):
        return [], []
    actual = {item.name: item for item in attachments}
    selected: list[ToolAttachment] = []
    omitted: list[dict[str, Any]] = []
    admitted_bytes = 0
    for entry in entries:
        if entry["kind"] == "text":
            continue
        binding = entry["_binding"]
        if _within_limit(entry, admitted_bytes):
            selected.append(actual[binding["native_attachment_id"]])
            admitted_bytes += entry["sizeBytes"]
        else:
            omitted.append(binding)
    return selected, omitted


def repl_output_display(
    schema: dict[str, Any], output: object, references: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Publish only exact bindings; legal oversized entries preserve the surrounding text."""
    if not declared_repl(schema):
        return None
    try:
        entries = _entries(output, references)
        result: list[dict[str, Any]] = []
        admitted_bytes, remaining_text = 0, 32768
        for entry in entries:
            if entry["kind"] == "text":
                encoded = entry["text"].encode("utf-16-le", errors="surrogatepass")[
                    : remaining_text * 2
                ]
                text = encoded.decode("utf-16-le", errors="ignore")
                remaining_text -= len(text.encode("utf-16-le")) // 2
                result.append({"kind": "text", "text": text})
            elif not _within_limit(entry, admitted_bytes):
                result.append({"kind": "unavailable", "reason": "media_size_limit"})
            else:
                artifact_id = entry["_binding"].get("artifact_id")
                if not _identifier(artifact_id):
                    return None
                admitted_bytes += entry["sizeBytes"]
                result.append(
                    {
                        "kind": entry["kind"],
                        "artifactId": artifact_id,
                        "mimeType": entry["mimeType"],
                        "sizeBytes": entry["sizeBytes"],
                        "store": "conversation_tool_media",
                    }
                )
        return {"kind": "repl_output", "entries": result}
    except (ValueError, TypeError):
        return None
