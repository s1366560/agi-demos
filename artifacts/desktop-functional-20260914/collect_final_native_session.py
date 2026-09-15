"""Read exact QA session through owner APIs; never persist credentials."""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("conversation_id")
    parser.add_argument("output_name")
    parser.add_argument("--workspace", default="5e5e6120-f7b1-4fee-918e-521b150b94e8")
    args = parser.parse_args()
    assert Path(args.output_name).name == args.output_name
    output = Path(__file__).with_name(args.output_name)
    columns = [
        part.strip().strip("`")
        for part in next(
            line
            for line in Path("AGENTS.md").read_text().splitlines()
            if line.startswith("| Admin |")
        ).split("|")
    ]
    report = {"captured_at": datetime.now(UTC).isoformat(), "conversation_id": args.conversation_id}
    params = {
        "tenant_id": "02f6fccc-0ac9-4729-bac7-38e77d1c61ef",
        "project_id": "738ace12-0d21-48ca-847d-cd0c2802816d",
        "workspace_id": args.workspace,
    }
    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=45) as client:
        login = await client.post(
            "/api/v1/auth/token", data={"username": columns[2], "password": columns[3]}
        )
        login.raise_for_status()
        client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
        try:
            me = await client.get("/api/v1/auth/me")
            me.raise_for_status()
            assert me.json()["user_id"] == "bf922bb7-290d-4252-8891-f82b97aa14b2"
            report["http_status"] = {}
            for name, suffix in (
                ("session", "session"),
                ("messages", "messages"),
                ("tools", "tool-executions"),
            ):
                response = await client.get(
                    f"/api/v1/agent/conversations/{args.conversation_id}/{suffix}",
                    params={**params, **({"limit": 500} if name != "session" else {})},
                )
                report["http_status"][name] = response.status_code
                response.raise_for_status()
                report[name] = response.json()
        finally:
            report["owner_auth_revoked"] = (
                await client.post("/api/v1/auth/signout")
            ).status_code == 200
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    execution = report.get("session", {}).get("execution", {})
    print(
        json.dumps(
            {
                "output": str(output),
                "http_status": report["http_status"],
                "current_run": {
                    key: execution.get("current_run", {}).get(key)
                    for key in ("id", "status", "revision")
                },
                "tools": [
                    {key: item.get(key) for key in ("id", "tool_name", "status")}
                    for item in report.get("tools", {}).get("tool_executions", [])
                ],
                "auth_revoked": report["owner_auth_revoked"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
