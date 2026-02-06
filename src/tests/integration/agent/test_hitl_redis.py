#!/usr/bin/env python3
"""Test HITL Redis Stream."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.getcwd())

os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")

import redis.asyncio as aioredis


async def test():
    """Test Redis HITL stream."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis = aioredis.from_url(redis_url)

    tenant_id = "d06da862-1bb1-44fe-93a0-153f58578e07"
    project_id = "a0b13a4d-a0dd-418d-81dd-af48c722773e"
    stream_key = f"hitl:response:{tenant_id}:{project_id}"

    print(f"Checking Redis stream: {stream_key}")

    # Check stream info
    try:
        info = await redis.xinfo_stream(stream_key)
        print(f"Stream info: {info}")
    except Exception as e:
        print(f"Stream info error: {e}")

    # Check consumer groups
    try:
        groups = await redis.xinfo_groups(stream_key)
        print(f"Consumer groups: {groups}")
    except Exception as e:
        print(f"Consumer groups error: {e}")

    # Read pending messages
    try:
        pending = await redis.xpending(stream_key, "hitl-response-router")
        print(f"Pending messages: {pending}")
    except Exception as e:
        print(f"Pending error: {e}")

    # Read stream messages
    try:
        messages = await redis.xrange(stream_key, count=10)
        print(f"Messages in stream: {len(messages)}")
        for msg_id, fields in messages:
            print(f"  {msg_id}: {fields}")
    except Exception as e:
        print(f"Read error: {e}")

    await redis.close()


if __name__ == "__main__":
    asyncio.run(test())
