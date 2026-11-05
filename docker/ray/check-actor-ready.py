#!/usr/bin/env python3
"""Read the existing HITL router's health RPC; never create an actor or local cluster."""

from __future__ import annotations

import argparse
import json
import math
import os

import ray

_FIELDS = frozenset({"running", "listening", "redis_connected", "ready"})


def check_actor(address: str, namespace: str, actor_name: str, timeout: float) -> dict[str, bool]:
    if not address.strip() or address.strip().lower() == "local":
        raise ValueError("an existing Ray cluster address is required")
    try:
        ray.init(
            address=address,
            namespace=namespace,
            ignore_reinit_error=True,
            log_to_driver=False,
            configure_logging=False,
        )
        actor = ray.get_actor(actor_name, namespace=namespace)
        result = ray.get(actor.health.remote(), timeout=timeout)
        if (
            not isinstance(result, dict)
            or result.keys() != _FIELDS
            or any(type(value) is not bool for value in result.values())
            or result["ready"]
            != (result["running"] and result["listening"] and result["redis_connected"])
        ):
            raise ValueError("invalid Ray router health response")
        return result
    finally:
        ray.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default=os.environ.get("RAY_ADDRESS", "auto"))
    parser.add_argument("--namespace", default=os.environ.get("RAY_NAMESPACE", "memstack"))
    parser.add_argument("--actor-name", default="hitl-router")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be positive")
    try:
        result = check_actor(args.address, args.namespace, args.actor_name, args.timeout)
    except Exception:
        # Transport errors may contain Redis URLs or credentials; never echo them.
        print(json.dumps({"ready": False, "error": "ray_actor_not_ready"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
