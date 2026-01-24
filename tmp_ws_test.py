import asyncio
import json

import aiohttp

BASE_URL = "http://localhost:8000"
PROJECT_ID = "5a93be6c-f391-4e88-a13e-ee2b8e41c5fd"


async def main():
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            f"{BASE_URL}/api/v1/auth/token",
            data={"username": "admin@memstack.ai", "password": "adminpassword"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = await resp.json()
        token = data["access_token"]
        resp = await session.post(
            f"{BASE_URL}/api/v1/agent/conversations",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"project_id": PROJECT_ID, "title": "WS text_delta test"},
        )
        conv = await resp.json()
        conversation_id = conv["id"]
        print("conversation_id", conversation_id)

        ws_url = f"{BASE_URL.replace('http', 'ws')}/api/v1/agent/ws?token={token}"
        async with session.ws_connect(ws_url) as ws:
            connected = await ws.receive_json()
            print("connected", connected.get("type"))
            await ws.send_json(
                {
                    "type": "send_message",
                    "conversation_id": conversation_id,
                    "message": "Please answer: What is 2+2?",
                    "project_id": PROJECT_ID,
                }
            )
            text_delta = 0
            other = 0
            start = asyncio.get_event_loop().time()
            received = 0
            while True:
                if asyncio.get_event_loop().time() - start > 10:
                    print("timeout waiting for events")
                    break
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    t = data.get("type")
                    received += 1
                    if received <= 10:
                        print("event_type", t)
                    if t in ("message", "user_message", "start"):
                        mid = (data.get("data") or {}).get("message_id")
                        if mid:
                            print("event", t, "message_id", mid)
                    if t == "text_delta":
                        text_delta += 1
                        if text_delta <= 5:
                            print("text_delta", data.get("data", {}).get("delta", ""))
                    else:
                        other += 1
                    if t in ("complete", "error"):
                        break
                else:
                    break
            print("text_delta_count", text_delta, "other", other)


asyncio.run(main())
