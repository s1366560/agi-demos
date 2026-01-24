import asyncio

import redis.asyncio as redis

conversation_id = "acaa2153-b78b-4f70-92da-c8d96ea6db7b"


async def main():
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    key = f"agent:events:{conversation_id}"
    streams = await r.xread({key: "0"}, count=5, block=1000)
    print(streams)
    await r.aclose()


asyncio.run(main())
