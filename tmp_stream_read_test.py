import asyncio

import redis.asyncio as redis

from src.infrastructure.adapters.secondary.event.redis_event_bus import RedisEventBusAdapter

conversation_id = "acaa2153-b78b-4f70-92da-c8d96ea6db7b"


async def main():
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    bus = RedisEventBusAdapter(r)
    stream_key = f"agent:events:{conversation_id}"
    count = 0
    async for msg in bus.stream_read(stream_key, last_id="0", count=5, block_ms=1000):
        print("msg", msg)
        count += 1
        if count >= 5:
            break
    await r.aclose()


asyncio.run(main())
asyncio.run(main())
