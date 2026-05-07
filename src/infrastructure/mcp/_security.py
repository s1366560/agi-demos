"""Internal TLS / connection-hardening helpers for MCP transports.

Centralises the TLS verification policy so every MCP client and transport
applies the same default (verification ON) and respects the same
``MCP_TLS_VERIFY`` environment override. When verification is explicitly
disabled, a loud warning is logged exactly once per process so misconfigured
production deployments are obvious in logs.
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

# Default WebSocket frame size limit (16 MiB). MCP messages should be JSON-RPC
# envelopes; large binary payloads belong on dedicated streaming channels.
DEFAULT_WS_MAX_MSG_SIZE: int = 16 * 1024 * 1024

# Default heartbeat interval for WebSocket transports (seconds). aiohttp uses
# ``heartbeat / 2`` as the PONG timeout.
DEFAULT_WS_HEARTBEAT_SECONDS: float = 30.0

_FALSY_VALUES = frozenset({"0", "false", "no", "off", "disabled"})

_warn_lock = threading.Lock()
_warned_disabled = False


def _coerce_bool(value: str) -> bool:
    return value.strip().lower() not in _FALSY_VALUES


def tls_verify_default() -> bool:
    """Return whether outbound MCP TLS connections should verify certificates.

    Defaults to ``True``. Setting ``MCP_TLS_VERIFY`` to a falsy value
    (``0``, ``false``, ``no``, ``off``, ``disabled``) disables verification
    process-wide and logs a loud warning the first time the override is
    consulted.
    """
    raw = os.environ.get("MCP_TLS_VERIFY")
    if raw is None:
        return True
    enabled = _coerce_bool(raw)
    if not enabled:
        global _warned_disabled
        with _warn_lock:
            if not _warned_disabled:
                _warned_disabled = True
                logger.warning(
                    "MCP_TLS_VERIFY is disabled (raw=%r). All MCP HTTP/WS clients "
                    "will skip certificate validation. Do NOT use this setting "
                    "outside of local development.",
                    raw,
                )
    return enabled


def reset_tls_warning_state_for_tests() -> None:
    """Test helper: reset the one-shot warning flag."""
    global _warned_disabled
    with _warn_lock:
        _warned_disabled = False
