"""Ray adapter package - pre-initializes Ray with allow_multiple=True."""

from __future__ import annotations

import os

# Set environment variables BEFORE any Ray import
os.environ.setdefault("RAY_ADDRESS", "ray://localhost:10001")
os.environ.setdefault("RAY_NAMESPACE", "memstack")

# CRITICAL FIX: Patch Ray's auto_init_ray BEFORE importing ray
# This prevents "allow_multiple" errors
import ray._private.auto_init_hook as _auto_init_hook

# Store original function
_original_auto_init_ray = _auto_init_hook.auto_init_ray

def _patched_auto_init_ray():
    """Patched auto_init that uses allow_multiple=True."""
    if not _auto_init_hook.enable_auto_connect:
        return
        
    import ray as _ray_module
    
    if _ray_module.is_initialized():
        return
    
    with _auto_init_hook.auto_init_lock:
        if _ray_module.is_initialized():
            return
        
        # Get settings from environment
        address = os.environ.get("RAY_ADDRESS", "ray://localhost:10001")
        namespace = os.environ.get("RAY_NAMESPACE", "memstack")
        
        # Init with allow_multiple=True
        _ray_module.init(
            address=address,
            namespace=namespace,
            ignore_reinit_error=True,
            allow_multiple=True,
            log_to_driver=False,
        )

# Apply the patch
_auto_init_hook.auto_init_ray = _patched_auto_init_ray

# Now safe to import ray
import ray as _ray

# Initialize Ray immediately with allow_multiple=True
if not _ray.is_initialized():
    try:
        _ray.init(
            address=os.environ.get("RAY_ADDRESS", "ray://localhost:10001"),
            namespace=os.environ.get("RAY_NAMESPACE", "memstack"),
            ignore_reinit_error=True,
            allow_multiple=True,
            log_to_driver=False,
        )
    except ValueError as e:
        # Already connected is OK
        if "already connected" not in str(e).lower():
            raise

# Re-export ray for convenience
ray = _ray

__all__ = ["ray"]
