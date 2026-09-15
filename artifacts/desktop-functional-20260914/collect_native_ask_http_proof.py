"""Read-only exact QA ASK evidence; credentials stay in memory and are revoked."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

CID = "e9c68760-fc1c-55bd-8f87-cd4e1a884fcb"
PROJECT = "738ace12-0d21-48ca-847d-cd0c2802816d"
TENANT = "02f6fccc-0ac9-4729-bac7-38e77d1c61ef"
WORKSPACE = "b30bf32d-36f0-4832-bcca-252a8df18b15"
MARKERS = (
    "perm_93af798b",
    "perm_8be7354e",
    "qa-native-ask-once-20260914.txt",
    "qa-native-ask-deny-20260914.txt",
)
OUT = Path(__file__).with_name("cloud-native-ask-final-http-proof.json")


def matches(value):
    encoded = json.dumps(value, ensure_ascii=False)
    return any(marker in encoded for marker in MARKERS)


async def main():
    row = next(
        line for line in Path("AGENTS.md").read_text().splitlines() if line.startswith("| Admin |")
    )
    columns = [part.strip().strip("`") for part in row.split("|")]
    report = {"captured_at": datetime.now(UTC).isoformat(), "conversation_id": CID, "requests": {}}
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

            async def get(name, path, params=None):
                result = await client.get("/api/v1/agent" + path, params=params)
                report["requests"][name] = {
                    "status": result.status_code,
                    "path": path,
                    "params": params,
                }
                result.raise_for_status()
                return result.json()

            params = {"tenant_id": TENANT, "project_id": PROJECT, "workspace_id": WORKSPACE}
            session = await get("session", f"/conversations/{CID}/session", params)
            messages = await get(
                "messages", f"/conversations/{CID}/messages", {**params, "limit": 500}
            )
            records = await get(
                "tool_executions", f"/conversations/{CID}/tool-executions", {**params, "limit": 500}
            )
            selected = [item for item in messages["timeline"] if matches(item)]
            report["matching_timeline"] = selected
            report["matching_tool_executions"] = [
                item for item in records["tool_executions"] if matches(item)
            ]
            report["history_window"] = {
                key: messages.get(key)
                for key in ("total", "has_more", "first_time_us", "last_time_us")
            }
            execution = session["execution"]
            runs = {item["id"]: item for item in execution["run_history"]}
            if execution.get("current_run"):
                runs[execution["current_run"]["id"]] = execution["current_run"]
            report["runs"] = []
            report["excluded_run_ids"] = ["8c01aa0c-d71e-5d18-90aa-624f50fb7533"]
            for run in runs.values():
                if matches(run) and run["id"] not in report["excluded_run_ids"]:
                    safe = {
                        key: value for key, value in run.items() if key != "authorization_snapshot"
                    }
                    safe["summary"] = await get(
                        "summary:" + run["id"], f"/runs/{run['id']}/summary"
                    )
                    report["runs"].append(safe)
        finally:
            logout = await client.post("/api/v1/auth/signout")
            report["owner_auth_revoked"] = logout.status_code == 200
            OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(OUT),
                "events": len(report.get("matching_timeline", [])),
                "tools": len(report.get("matching_tool_executions", [])),
                "runs": [(run["id"], run["status"]) for run in report.get("runs", [])],
                "auth_revoked": report["owner_auth_revoked"],
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
