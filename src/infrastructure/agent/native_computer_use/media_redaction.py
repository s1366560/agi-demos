"""Keep hydrated media bytes out of durable model requests and traces."""

from __future__ import annotations

import hashlib
from contextvars import ContextVar
from typing import Any, cast

_MODEL_MEDIA_REFERENCES: ContextVar[dict[str, dict[str, Any]] | None] = ContextVar(
    "native_model_media_references", default=None
)


def register_model_media_reference(encoded: str, reference: dict[str, Any]) -> None:
    references = dict(_MODEL_MEDIA_REFERENCES.get() or {})
    references[hashlib.sha256(encoded.encode("ascii")).hexdigest()] = dict(reference)
    _ = _MODEL_MEDIA_REFERENCES.set(references)


def redact_model_media(value: object) -> Any:  # noqa: ANN401 - JSON recursive value
    """Remove inline binary media from durable provider request and trace records."""
    if isinstance(value, list):
        return [redact_model_media(item) for item in cast(list[object], value)]
    if not isinstance(value, dict):
        return value
    value = cast(dict[str, Any], value)
    result = {key: redact_model_media(item) for key, item in value.items()}
    for key in ("url", "image_url", "imageUrl", "file_data"):
        item = result.get(key)
        if isinstance(item, str) and item.startswith("data:") and ";base64," in item:
            prefix, data = item.split(";base64,", 1)
            result[key] = f"{prefix};artifact-bytes-omitted"
            result["media_sha256"] = hashlib.sha256(
                data.encode("ascii", errors="replace")
            ).hexdigest()
            result["media_encoded_size"] = len(data)
            reference = (_MODEL_MEDIA_REFERENCES.get() or {}).get(result["media_sha256"])
            if reference is not None:
                result["media_artifact"] = reference
    if (
        value.get("type") == "base64"
        and isinstance(value.get("data"), str)
        and value["data"] != "[artifact bytes omitted]"
    ):
        result["data"] = "[artifact bytes omitted]"
        result["media_sha256"] = hashlib.sha256(value["data"].encode()).hexdigest()
        reference = (_MODEL_MEDIA_REFERENCES.get() or {}).get(result["media_sha256"])
        if reference is not None:
            result["media_artifact"] = reference
    for key in ("inline_data", "inlineData", "input_audio"):
        raw_item = value.get(key)
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, Any], raw_item)
        if isinstance(item.get("data"), str) and item["data"] != "[artifact bytes omitted]":
            result[key] = {**item, "data": "[artifact bytes omitted]"}
            result[key]["media_sha256"] = hashlib.sha256(item["data"].encode()).hexdigest()
            reference = (_MODEL_MEDIA_REFERENCES.get() or {}).get(result[key]["media_sha256"])
            if reference is not None:
                result[key]["media_artifact"] = reference
    return result
