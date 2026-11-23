"""Start the Rust gateway in front of listening test upstreams."""

import asyncio
import json
import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from src.tests.integration.package_http_server import serve_project_api


@pytest.fixture(scope="module")
def gateway_binary() -> str:
    if not shutil.which("cargo"):
        pytest.skip("building the Rust gateway requires Cargo")
    stack = Path(__file__).resolve().parents[3] / "agi-stack"
    build = subprocess.run(
        ["cargo", "build", "--locked", "-p", "agistack-gateway", "--message-format=json"],
        cwd=stack,
        capture_output=True,
        check=True,
        text=True,
    )
    return next(
        event["executable"]
        for line in build.stdout.splitlines()
        if (event := json.loads(line)).get("executable")
        and event["target"]["name"] == "agistack-gateway"
    )


@asynccontextmanager
async def gateway_client(
    binary: str, backend: FastAPI, *, rust_app: FastAPI | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    rust = FastAPI()

    @rust.get("/api/v1/memories/")
    async def rust_owned() -> dict[str, str]:
        return {"upstream": "rust"}

    async with (
        serve_project_api(backend) as python,
        serve_project_api(rust_app or rust) as rust_origin,
    ):
        process = await asyncio.create_subprocess_exec(
            binary,
            env={
                **os.environ,
                "AGISTACK_GATEWAY_ADDR": "127.0.0.1:0",
                "AGISTACK_RUST_UPSTREAM": rust_origin,
                "AGISTACK_PYTHON_UPSTREAM": python,
            },
            stdout=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None
        try:
            async with asyncio.timeout(10):
                ready = (await process.stdout.readline()).decode().rstrip()
            prefix = "agistack-gateway listening on "
            assert ready.startswith(prefix)
            async with httpx.AsyncClient(base_url=ready.removeprefix(prefix), timeout=15) as proxy:
                yield proxy
        finally:
            if process.returncode is None:
                process.terminate()
            await process.communicate()
