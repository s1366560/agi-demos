"""Original-owner QA sandbox refresh. Default is read-only; --apply posts once."""

import argparse
import asyncio
import getpass
import json
import os
import subprocess
from pathlib import Path

import httpx

OWNER = "bf922bb7-290d-4252-8891-f82b97aa14b2"
PROJECT = "738ace12-0d21-48ca-847d-cd0c2802816d"
TENANT = "02f6fccc-0ac9-4729-bac7-38e77d1c61ef"
SANDBOX = "mcp-sandbox-653501ed6a06"
IMAGE = "sha256:9777bf69a9681d2767e8fb0e15576c48b86fe7ec5b65bd41e24cacdb0981520b"
WORKSPACE = f"/tmp/memstack_{PROJECT}"
CHROMIUM = "/home/sandbox/.config/chromium"
CHROMIUM_VOLUME = "memstack-sky-cua-chromium-d648e4faf75e178151f7f02e1e32696a"
ENDPOINT = f"/api/v1/projects/{PROJECT}/sandbox"
REPORT = Path(__file__).with_name("qa-sandbox-refresh-result.json")


def docker(*arguments):
    result = subprocess.run(["docker", *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError("Docker read/probe failed")
    return result.stdout.strip()


def inspect_containers():
    ids = docker("ps", "-aq").splitlines()
    template = (
        '{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},'
        '"labels":{{json .Config.Labels}},"mounts":{{json .Mounts}},'
        '"state":{{json .State.Status}}}'
    )
    return [json.loads(docker("inspect", "--format", template, item)) for item in ids]


def validate_containers(containers):
    """Cover every selector used by cleanup_project_containers, plus shared mounts."""
    candidates = []
    for value in containers:
        labels = value["labels"] or {}
        name = value["name"].lstrip("/")
        mounts = value["mounts"]
        path_match = any(f"memstack_{PROJECT}" in m.get("Source", "") for m in mounts)
        cleanup_match = labels.get("memstack.sandbox") == "true" and (
            labels.get("memstack.project_id") == PROJECT
            or path_match
            or PROJECT in name
            or f"memstack_{PROJECT}" in name
        )
        if cleanup_match or path_match or name == SANDBOX:
            candidates.append(value)
    if len(candidates) != 1:
        raise ValueError("QA cleanup scope must contain exactly one unshared container")
    value = candidates[0]
    labels = value["labels"] or {}
    if (
        value["name"].lstrip("/") != SANDBOX
        or labels.get("memstack.project_id") != PROJECT
        or labels.get("memstack.tenant_id") != TENANT
        or labels.get("memstack.sandbox") != "true"
        or value["state"] != "running"
    ):
        raise ValueError("Container identity does not match the original QA sandbox")
    workspace = [m for m in value["mounts"] if m.get("Destination") == "/workspace"]
    chromium = [m for m in value["mounts"] if m.get("Destination") == CHROMIUM]
    if (
        len(workspace) != 1
        or workspace[0].get("Type") != "bind"
        or os.path.realpath(workspace[0]["Source"]) != os.path.realpath(WORKSPACE)
        or not workspace[0].get("RW")
        or len(chromium) != 1
        or chromium[0].get("Type") != "volume"
        or chromium[0].get("Name") != CHROMIUM_VOLUME
    ):
        raise ValueError("Original workspace bind or Chromium volume does not match")
    volume_name = chromium[0]["Name"]
    if any(
        other["id"] != value["id"] and any(m.get("Name") == volume_name for m in other["mounts"])
        for other in containers
    ):
        raise ValueError("Another container shares the QA Chromium volume")
    return {
        "container_id": value["id"],
        "image_id": value["image"],
        "workspace_source": workspace[0]["Source"],
        "chromium_volume": volume_name,
    }


def validate_sandbox(value):
    if any(
        value.get(key) != expected
        for key, expected in {
            "sandbox_id": SANDBOX,
            "project_id": PROJECT,
            "tenant_id": TENANT,
        }.items()
    ):
        raise ValueError("Official sandbox response belongs to another scope")
    return {key: value.get(key) for key in ("sandbox_id", "status", "is_healthy")}


PROBE = r"""
import asyncio, json, os
import aiohttp
from src.server.main import _auth_config_from_env
async def main():
    token = _auth_config_from_env().static_token
    if not token: raise RuntimeError("MCP static credential is unavailable")
    port = int(os.environ.get("MCP_PORT", "8765"))
    async with aiohttp.ClientSession() as client:
        async with client.ws_connect(f"http://127.0.0.1:{port}/", headers={"Authorization":"Bearer "+token}) as ws:
            async def request(identifier, method, params):
                await ws.send_json({"jsonrpc":"2.0","id":identifier,"method":method,"params":params})
                while True:
                    response = await asyncio.wait_for(ws.receive_json(), 15)
                    if response.get("id") == identifier:
                        if "error" in response: raise RuntimeError("MCP request failed")
                        return response["result"]
            await request(1,"initialize",{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"qa-mount-probe","version":"1"}})
            await ws.send_json({"jsonrpc":"2.0","method":"notifications/initialized"})
            result = await request(2,"tools/list",{})
            matches = [v for v in result["tools"] if v["name"] == "write"]
            if len(matches) != 1: raise RuntimeError("Expected one builtin write tool")
            print(json.dumps({"tool":"write","meta":matches[0].get("_meta")}))
asyncio.run(main())
"""


async def run(apply):
    report = {
        "apply_requested": apply,
        "restart_requested": False,
        "applied": False,
        "owner_id": OWNER,
        "project_id": PROJECT,
        "sandbox_id": SANDBOX,
        "reviewed_image_id": IMAGE,
    }
    client = httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=180)
    authenticated = False
    try:
        before = validate_containers(await asyncio.to_thread(inspect_containers))
        if docker("image", "inspect", "sandbox-mcp-server:latest", "--format", "{{.Id}}") != IMAGE:
            raise ValueError("Latest image has drifted from the reviewed build")
        report["before"] = before
        password = os.environ.get("QA_OWNER_PASSWORD") or getpass.getpass(
            "Original QA owner password: "
        )
        login = await client.post(
            "/api/v1/auth/token", data={"username": "admin@memstack.ai", "password": password}
        )
        del password
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        authenticated = True
        me = await client.get("/api/v1/auth/me")
        me.raise_for_status()
        if me.json().get("user_id") != OWNER:
            raise ValueError("Authenticated account is not the original QA owner")
        response = await client.get(ENDPOINT)
        response.raise_for_status()
        report["official_before"] = validate_sandbox(response.json())
        if apply:
            if validate_containers(await asyncio.to_thread(inspect_containers)) != before:
                raise ValueError("Container state changed since preflight")
            if (
                docker("image", "inspect", "sandbox-mcp-server:latest", "--format", "{{.Id}}")
                != IMAGE
            ):
                raise ValueError("Reviewed image changed before restart")
            # Never retry: timeout can mean the server already started recreating.
            report["restart_requested"] = True
            restarted = await client.post(ENDPOINT + "/restart")
            report["restart_http_status"] = restarted.status_code
            restarted.raise_for_status()
            if restarted.json().get("success") is not True:
                raise ValueError("Restart did not report success")
            validate_sandbox(restarted.json()["sandbox"])
            after = validate_containers(await asyncio.to_thread(inspect_containers))
            if after["image_id"] != IMAGE or any(
                after[key] != before[key] for key in ("workspace_source", "chromium_volume")
            ):
                raise ValueError("Recreated image or preserved storage differs")
            response = await client.get(ENDPOINT)
            response.raise_for_status()
            report["official_after"] = validate_sandbox(response.json())
            if (
                report["official_after"]["status"] != "running"
                or not report["official_after"]["is_healthy"]
            ):
                raise ValueError("Recreated sandbox is not healthy")
            probe = json.loads(
                await asyncio.to_thread(docker, "exec", SANDBOX, "python", "-c", PROBE)
            )
            if probe != {
                "tool": "write",
                "meta": {
                    "memstack/workspace-write": {
                        "contract": "directory-fd-write-v1",
                        "workspace_root": "/workspace",
                    }
                },
            }:
                raise ValueError("Live MCP mount confinement contract is absent")
            report.update(after=after, live_tools_list=probe, applied=True)
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        raise
    finally:
        try:
            if authenticated:
                logout = await client.post("/api/v1/auth/signout")
                report["owner_auth_revoked"] = logout.status_code == 200
        except Exception as exc:
            report["signout_error_type"] = type(exc).__name__
        finally:
            await client.aclose()
            REPORT.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    try:
        asyncio.run(run(parser.parse_args().apply))
    except Exception:
        raise SystemExit("QA sandbox preflight/update failed; see sanitized report") from None
