"""Loopback fixture for the authenticated native microphone socket.

Only the isolated voice connection is synthesized. Login, project membership, package
authorization and revocation are served by the local development API.
"""

import asyncio
import json
import threading
from collections.abc import Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field

import aiohttp
from aiohttp import web

DEV_API = "http://127.0.0.1:8000"
_HOP_HEADERS = {"host", "connection", "content-length", "transfer-encoding", "keep-alive"}


@dataclass
class SpeechFixture:
    project: str
    conversation: str
    received: list[str] = field(default_factory=list)
    closed: list[str] = field(default_factory=list)

    async def _voice(self, request, upstream):
        if (
            request.query.get("project_id") != self.project
            or request.query.get("conversation_id") != self.conversation
            or request.query.get("package_session") != "1"
        ):
            raise web.HTTPForbidden()
        protocols = [
            s.strip() for s in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        ]
        credential = next((p for p in protocols if p.startswith("ms_sk_")), None)
        if not credential or "memstack.auth" not in protocols:
            raise web.HTTPUnauthorized()
        async with upstream.get(
            f"{DEV_API}/api/v1/agent/conversations/{self.conversation}",
            params={"project_id": self.project},
            headers={"Authorization": "Bearer " + credential},
        ) as response:
            if response.status != 200:
                raise web.HTTPForbidden()
        socket = web.WebSocketResponse(protocols=("memstack.auth",))
        await socket.prepare(request)
        mode = ""
        sent = False
        try:
            async for frame in socket:
                if frame.type == aiohttp.WSMsgType.TEXT:
                    config = json.loads(frame.data)
                    if not config.get("package_ticket"):
                        await socket.close(code=4003)
                        break
                    mode = config["mode"]
                elif frame.type == aiohttp.WSMsgType.BINARY and frame.data and not sent:
                    self.received.append(mode)
                    sent = True
                    await socket.send_json({"type": "asr_final", "text": "synthetic fixture"})
                    if mode == "voice":
                        await socket.send_json(
                            {"type": "agent_complete", "content": "native test reply"}
                        )
        finally:
            self.closed.append(mode)
        return socket

    async def serve(self, ready, stop):
        async with aiohttp.ClientSession(auto_decompress=False, trust_env=False) as upstream:

            async def handle(request):
                if request.path == "/api/v1/voice/chat":
                    return await self._voice(request, upstream)
                if not request.path.startswith("/api/"):
                    raise web.HTTPNotFound()
                headers = {
                    k: v for k, v in request.headers.items() if k.lower() not in _HOP_HEADERS
                }
                async with upstream.request(
                    request.method,
                    DEV_API + request.raw_path,
                    headers=headers,
                    data=await request.read(),
                    allow_redirects=False,
                ) as response:
                    return web.Response(
                        status=response.status,
                        body=await response.read(),
                        headers={
                            k: v
                            for k, v in response.headers.items()
                            if k.lower() not in _HOP_HEADERS
                        },
                    )

            app = web.Application(client_max_size=30 * 1024**2)
            app.router.add_route("*", "/{tail:.*}", handle)
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            await web.TCPSite(runner, "127.0.0.1", 0).start()
            try:
                ready.set_result("http://127.0.0.1:" + str(runner.addresses[0][1]))
                await asyncio.to_thread(stop.wait)
            finally:
                await runner.cleanup()

    @contextmanager
    def running(self) -> Iterator[str]:
        stop = threading.Event()
        ready = Future()

        def run():
            try:
                asyncio.run(self.serve(ready, stop))
            except Exception as error:
                if not ready.done():
                    ready.set_exception(error)
                else:
                    raise

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            yield ready.result(timeout=10)
        finally:
            stop.set()
            thread.join(timeout=10)
