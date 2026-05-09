"""Ray adapter package.

Importing this package must stay cheap: service startup and read-only API
requests import Ray-adjacent modules before they actually need a cluster.
Connection attempts are intentionally deferred to ``client.init_ray_if_needed``.
"""

from __future__ import annotations

import socket

# Kept for compatibility with retry code that clears a failed runtime state.
_ray_init_failed = False


def _check_ray_reachable(address: str, timeout: float = 3) -> bool:
    """Quick TCP check to see if Ray head node is reachable."""
    # Parse host:port from "ray://host:port"
    addr = address.replace("ray://", "")
    if ":" in addr:
        host, port_str = addr.rsplit(":", 1)
        port = int(port_str)
    else:
        host, port = addr, 10001

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (TimeoutError, OSError):
        return False


# Disable Ray's auto_init to prevent uncontrolled ray.init() calls.
# All initialization goes through client.init_ray_if_needed().
import ray._private.auto_init_hook as _auto_init_hook

_auto_init_hook.enable_auto_connect = False

# Now safe to import Ray without connecting to a cluster.
import ray as _ray

# Re-export ray for convenience
ray = _ray

__all__ = ["_check_ray_reachable", "ray"]
