"""Loopback HTTP endpoint for exercising real package clients against a scoped test app."""

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI


@asynccontextmanager
async def serve_project_api(app: FastAPI) -> AsyncIterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(16)
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(8):
                while not server.started:
                    await asyncio.sleep(0.02)
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, timeout=12)
