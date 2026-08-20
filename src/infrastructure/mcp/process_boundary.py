"""Process boundary hardening for stdio MCP servers (R2).

Ports the control mechanisms from the I5 plugin subprocess host
(``src.infrastructure.plugins.subprocess_host``) to long-lived MCP server
processes without changing the MCP JSON-RPC wire protocol:

- environment scrubbing: child processes receive an allowlisted subset of
  the host environment plus the operator-provided per-server variables, so
  host secrets never leak into third-party MCP servers;
- trust tiers: servers classify as ``builtin`` / ``tenant_approved`` /
  ``untrusted``; untrusted servers get the strictest environment and a
  kill-on-timeout policy;
- output budgets: the stdout stream buffer is bounded per policy;
- audit: spawn / exit / timeout / kill events flow to the ``plugin_audit``
  logger, same as plugin runtime boundaries.

Compatibility: set ``MCP_STDIO_INHERIT_ENV=1`` to restore the legacy
inherit-everything environment behavior (mirrors the ``MCP_TLS_VERIFY``
override pattern in ``_security.py``). The wire protocol, timeouts chosen by
callers, and lifecycle ladders are unchanged for healthy servers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("plugin_audit")

__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "MCP_STDIO_INHERIT_ENV",
    "MCPProcessBoundaryPolicy",
    "MCPServerTrustTier",
    "classify_trust_tier",
    "emit_process_audit",
    "sanitize_subprocess_env",
    "spawn_mcp_server_process",
]

MCP_STDIO_INHERIT_ENV = "MCP_STDIO_INHERIT_ENV"

# Matches the historical stdout buffer used for large MCP payloads
# (e.g. base64 screenshots) in the subprocess client.
DEFAULT_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
UNTRUSTED_MAX_OUTPUT_BYTES = 1 * 1024 * 1024

_FALSY_VALUES = frozenset({"0", "false", "no", "off", "disabled"})


class MCPServerTrustTier(str, Enum):
    """Trust classification for an MCP server process."""

    BUILTIN = "builtin"
    TENANT_APPROVED = "tenant_approved"
    UNTRUSTED = "untrusted"


# Host variables that are safe to forward: no credentials, only process
# plumbing (paths, locales, temp dirs, proxies, shell identity).
_BASE_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
        "PROGRAMFILES",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
        "NPM_CONFIG_REGISTRY",
        "UV_INDEX_URL",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    }
)

# Untrusted servers get the smallest viable environment.
_UNTRUSTED_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
    }
)

_ALLOWLIST_BY_TIER: Mapping[MCPServerTrustTier, frozenset[str]] = {
    MCPServerTrustTier.TENANT_APPROVED: _BASE_ENV_ALLOWLIST,
    MCPServerTrustTier.UNTRUSTED: _UNTRUSTED_ENV_ALLOWLIST,
}


def _env_inherit_override() -> bool:
    raw = os.environ.get(MCP_STDIO_INHERIT_ENV)
    return raw is not None and raw.strip().lower() not in _FALSY_VALUES


def sanitize_subprocess_env(
    explicit: Mapping[str, str] | None,
    *,
    tier: MCPServerTrustTier,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the child-process environment.

    Operator-provided per-server variables (``explicit``) always pass
    through — they are the supported way to hand credentials to a server.
    Host variables are filtered by the tier allowlist; ``builtin`` servers
    and the ``MCP_STDIO_INHERIT_ENV`` escape hatch keep the legacy
    inherit-everything behavior.
    """
    host = dict(os.environ if environ is None else environ)
    if tier is MCPServerTrustTier.BUILTIN or _env_inherit_override():
        merged = host
    else:
        allowlist = _ALLOWLIST_BY_TIER[tier]
        merged = {key: value for key, value in host.items() if key in allowlist}
    if explicit:
        merged.update(explicit)
    return merged


def classify_trust_tier(
    command: Sequence[str],
    *,
    builtin_commands: frozenset[str] = frozenset(),
) -> MCPServerTrustTier:
    """Classify a server by its launch command.

    Commands in ``builtin_commands`` (matched by executable basename) are
    platform-shipped and trusted; every other registered server is
    tenant-approved by default. Operators mark a server untrusted by passing
    an explicit policy to the spawn helper.
    """
    if command:
        executable = os.path.basename(command[0])
        if executable in builtin_commands:
            return MCPServerTrustTier.BUILTIN
    return MCPServerTrustTier.TENANT_APPROVED


@dataclass(frozen=True)
class MCPProcessBoundaryPolicy:
    """Boundary controls applied to one MCP server process."""

    tier: MCPServerTrustTier = MCPServerTrustTier.TENANT_APPROVED
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES
    kill_on_timeout: bool = False

    @classmethod
    def for_tier(cls, tier: MCPServerTrustTier) -> MCPProcessBoundaryPolicy:
        """Resolve the default policy for a trust tier."""
        if tier is MCPServerTrustTier.UNTRUSTED:
            return cls(
                tier=tier,
                max_output_bytes=UNTRUSTED_MAX_OUTPUT_BYTES,
                kill_on_timeout=True,
            )
        return cls(tier=tier)


AuditSink = Callable[[Mapping[str, object]], None]


def emit_process_audit(event: Mapping[str, object], *, sink: AuditSink | None = None) -> None:
    """Emit one structured audit event to the ``plugin_audit`` stream."""
    if sink is not None:
        sink(event)
        return
    audit_logger.info("%s", json.dumps(dict(event), sort_keys=True))


async def spawn_mcp_server_process(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None,
    server_name: str,
    policy: MCPProcessBoundaryPolicy | None = None,
    audit: AuditSink | None = None,
) -> asyncio.subprocess.Process:
    """Spawn an MCP server process behind the hardened boundary.

    Applies the output budget (stream limit) and records a spawn audit
    event. The command itself is logged by basename only — arguments may
    carry credentials.
    """
    resolved = policy or MCPProcessBoundaryPolicy.for_tier(
        classify_trust_tier(command),
    )
    emit_process_audit(
        {
            "event": "mcp_server_spawn",
            "server_name": server_name,
            "executable": os.path.basename(command[0]) if command else "",
            "args_count": max(len(command) - 1, 0),
            "trust_tier": resolved.tier.value,
            "max_output_bytes": resolved.max_output_bytes,
        },
        sink=audit,
    )
    return await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env) if env is not None else None,
        limit=resolved.max_output_bytes,
    )
