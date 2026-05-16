from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import cast

_REDACTED = "<redacted>"
_installed = False

type _LogArgs = tuple[object, ...] | Mapping[str, object] | None
_SENSITIVE_QUERY_PARAMS = (
    "access_key",
    "access_token",
    "api_key",
    "apikey",
    "app_secret",
    "auth",
    "authorization",
    "client_secret",
    "key",
    "password",
    "refresh_token",
    "secret",
    "ticket",
    "token",
)
_SENSITIVE_QUERY_PARAM_RE = re.compile(
    rf"(?i)([?&](?:{'|'.join(_SENSITIVE_QUERY_PARAMS)})=)([^&#\s]+)"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\b(Bearer\s+)([A-Za-z0-9._~+/\-=]+)")
_MEMSTACK_API_KEY_RE = re.compile(r"\bms_sk_[0-9a-fA-F]{16,}\b")


def redact_sensitive_log_text(text: str) -> str:
    """Redact credentials that commonly appear in URLs, headers, and API keys."""
    redacted = _SENSITIVE_QUERY_PARAM_RE.sub(rf"\1{_REDACTED}", text)
    redacted = _BEARER_TOKEN_RE.sub(rf"\1{_REDACTED}", redacted)
    return _MEMSTACK_API_KEY_RE.sub(_REDACTED, redacted)


def _redact_log_value(value: object) -> object:
    if isinstance(value, str):
        return redact_sensitive_log_text(value)
    if isinstance(value, tuple):
        tuple_items = cast(tuple[object, ...], value)
        return tuple(_redact_log_value(item) for item in tuple_items)
    if isinstance(value, list):
        list_items = cast(list[object], value)
        return [_redact_log_value(item) for item in list_items]
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {key: _redact_log_value(item) for key, item in mapping.items()}
    return value


def _redact_log_args(args: _LogArgs) -> _LogArgs:
    if isinstance(args, tuple):
        return tuple(_redact_log_value(item) for item in args)
    if isinstance(args, Mapping):
        return {key: _redact_log_value(item) for key, item in args.items()}
    return None


def redact_sensitive_log_record(record: logging.LogRecord) -> logging.LogRecord:
    record.msg = _redact_log_value(record.msg)
    if record.args:
        record.args = _redact_log_args(record.args)
    return record


def install_sensitive_log_redaction() -> None:
    global _installed
    if _installed:
        return

    current_factory = logging.getLogRecordFactory()
    if getattr(current_factory, "_memstack_redacts_sensitive_values", False):
        _installed = True
        return

    def redacting_factory(*args: object, **kwargs: object) -> logging.LogRecord:
        return redact_sensitive_log_record(current_factory(*args, **kwargs))

    redacting_factory._memstack_redacts_sensitive_values = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(redacting_factory)
    _installed = True
