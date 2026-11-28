"""Install and roll back external releases using the installed CLI entry point over HTTP."""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import pytest

from src.tests.integration.package_http_server import serve_project_api
from src.tests.unit.routers import test_optional_business_http_v2 as project_fixtures

http = project_fixtures.http
publisher = project_fixtures.publisher

pytestmark = pytest.mark.integration
_ROOT = Path(__file__).resolve().parents[3]


async def test_install_approve_list_execute_and_rollback(http, publisher, tmp_path):
    client, keys = http
    admin = ["packages", "--tenant", "t", "--project", "p"]
    action = ["plugin", "sample.notes", "ping", "--tenant", "t", "--project", "p"]
    async with serve_project_api(client._transport.app) as origin:

        async def run(*args, success=True):
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "memstack_cli.cli",
                "--json",
                *args,
                cwd=_ROOT / "sdk/memstack_cli",
                env={**os.environ, "MEMSTACK_API_URL": origin, "MEMSTACK_API_KEY": keys["owner"]},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            async with asyncio.timeout(20):
                output, error = await proc.communicate()
            if not success:
                assert proc.returncode == 1
                return error.decode()
            assert proc.returncode == 0, error.decode()[:500]
            return json.loads(output)

        for version, word in (("1.0.0", "ping"), ("1.1.0", "pong")):
            body, digest = publisher[1](version, result=word)
            archive = tmp_path / f"{version}.mspkg"
            archive.write_bytes(base64.b64decode(body["archive_base64"]))
            preview = await run(*admin, "inspect", str(archive))
            assert (
                preview["digest"] == digest
                and preview["permissions"] == body["approved_permissions"]
            )
            if word == "ping":
                assert "permissions require approval" in await run(
                    *admin, "install", str(archive), success=False
                )
                assert (await run(*admin, "list"))["items"] == []
            permissions = [x for p in body["approved_permissions"] for x in ("--approve", p)]
            for _ in range(2):
                receipt = await run(*admin, "install", *permissions, str(archive))
                assert receipt["items"][0]["digest"] == digest
            assert (await run(*admin, "list"))["items"][0]["running_version"] == version
            assert (await run(*action))["op"] == word
        assert (await run(*admin, "rollback", "sample.notes"))["running_version"] == "1.0.0"
        assert (await run(*action))["op"] == "ping"
