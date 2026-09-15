"""Repeatable formal QA using an existing conversation; no credentials are persisted."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import websockets

PROJECT = "738ace12-0d21-48ca-847d-cd0c2802816d"
TENANT = "02f6fccc-0ac9-4729-bac7-38e77d1c61ef"


async def run(args):
    report = {
        "conversation_id": args.conversation_id,
        "scenario": args.scenario,
        "events": [],
        "snapshots": [],
    }
    output = Path(args.output)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=30) as client:
        response = await client.post(
            "/api/v1/auth/token",
            data={"username": "admin@memstack.ai", "password": "adminpassword"},
        )
        response.raise_for_status()
        token = response.json()["access_token"]
        client.headers.update({"Authorization": "Bearer " + token, "X-Tenant-ID": TENANT})
        message_sent = False
        try:
            path = f"/api/v1/agent/trace/runs/{args.conversation_id}"
            initial = await client.get(path)
            initial.raise_for_status()
            old_ids = {run["run_id"] for run in initial.json()["runs"]}
            task = (
                "不调用任何工具，用中文详细解释分布式系统一致性，至少五千字。"
                if args.scenario == "cancel"
                else "不调用任何工具，只回复 QA_OWNER_COMPLETED_20260914_OK。"
            )
            batch = str(uuid4())
            report["acceptance_batch"] = batch
            prompt = f"这是新验收批次 {batch}，前次运行已经失败且已结束。本次必须创建新的子任务，不能复用、引用或echo历史run_id。请不要使用bash。本次是已授权 QA。请严格仅实际调用一次 sessions_spawn，subagent_name=qa_owner_20260914，task={task}，run_timeout_seconds=60。不要调用 agent_spawn 或替代工具，不要创建 todowrite 计划。如果 sessions_spawn 不存在请直接说明不可用并停止。得到run_id后只报告该run_id；外部测试客户端负责取消与查询，不要再次创建。"
            parent_done = False
            last_poll = 0.0
            async with websockets.connect(
                "ws://127.0.0.1:8000/api/v1/agent/ws?token=" + token, max_size=4 * 1024 * 1024
            ) as ws:
                await ws.send(json.dumps({"type": "subscribe_lifecycle_state", "project_id": PROJECT}))
                while True:
                    subscription = json.loads(await asyncio.wait_for(ws.recv(), 10))
                    if subscription.get("type") == "ack" and subscription.get("action") == "subscribe_lifecycle_state":
                        report["lifecycle_subscription_ack"] = True
                        break
                    if subscription.get("type") == "error":
                        raise RuntimeError("Lifecycle subscription rejected")
                await ws.send(
                    json.dumps(
                        {
                            "type": "send_message",
                            "conversation_id": args.conversation_id,
                            "project_id": PROJECT,
                            "client_message_id": str(uuid4()),
                            "permission_mode": "full_access",
                            "message": prompt,
                        }
                    )
                )
                message_sent = True
                deadline = asyncio.get_running_loop().time() + 100
                while asyncio.get_running_loop().time() < deadline:
                    try:
                        message = json.loads(await asyncio.wait_for(ws.recv(), timeout=1))
                    except TimeoutError:
                        message = {}
                    kind = message.get("type")
                    data = message.get("data")
                    if kind and kind not in {
                        "ping",
                        "pong",
                        "text_delta",
                        "thought_delta",
                        "thinking_delta",
                    }:
                        safe = {"type": kind}
                        for source in (message, data if isinstance(data, dict) else {}):
                            for key in ("conversation_id", "run_id", "tool_name", "status", "code"):
                                if key in source:
                                    safe[key] = source[key]
                        if kind == "subagent_lifecycle":
                            safe = dict(message)
                        report["events"].append(safe)
                        print(json.dumps(safe), flush=True)
                    if kind in {"complete", "execution_completed", "cancelled", "error"}:
                        parent_done = True
                    now = asyncio.get_running_loop().time()
                    if now - last_poll >= 1:
                        last_poll = now
                        response = await client.get(path)
                        response.raise_for_status()
                        children = [
                            run for run in response.json()["runs"] if run["run_id"] not in old_ids
                        ]
                        states = [
                            {
                                "run_id": run["run_id"],
                                "status": run["status"],
                                "subagent_name": run["subagent_name"],
                            }
                            for run in children
                        ]
                        if states and (
                            not report["snapshots"] or report["snapshots"][-1] != states
                        ):
                            report["snapshots"].append(states)
                            print(json.dumps({"children": states}), flush=True)
                        if args.scenario == "cancel" and "cancel_response" not in report:
                            active = next(
                                (run for run in children if run["status"] == "running"), None
                            )
                            if active:
                                response = await client.post(
                                    f"/api/v1/agent/subagent/{active['run_id']}/cancel",
                                    json={
                                        "conversation_id": args.conversation_id,
                                        "reason": "QA owner cancellation",
                                    },
                                )
                                report["cancel_http_status"] = response.status_code
                                report["cancel_response"] = response.json()
                                print(
                                    json.dumps(
                                        {
                                            "cancel_status": response.status_code,
                                            "response": response.json(),
                                        }
                                    ),
                                    flush=True,
                                )
                        if (
                            children
                            and all(run["status"] not in {"pending", "running"} for run in children)
                            and parent_done
                        ):
                            report["final_children"] = children
                            break
                        if parent_done and not children:
                            report["no_child_created"] = True
                            break
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    await ws.send(
                        json.dumps(
                            {"type": "stop_session", "conversation_id": args.conversation_id}
                        )
                    )
                    report["deadline_stop_requested"] = True
            # A new authenticated HTTP client reads durable history independently of WS state.
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:8000", headers=client.headers, timeout=30
            ) as fresh:
                response = await fresh.get(path)
                report["fresh_history_status"] = response.status_code
                if response.status_code == 200:
                    report["fresh_children"] = [
                        run for run in response.json()["runs"] if run["run_id"] not in old_ids
                    ]
        except Exception as exc:
            report["failure_type"] = type(exc).__name__
            if message_sent:
                try:
                    async with websockets.connect(
                        "ws://127.0.0.1:8000/api/v1/agent/ws?token=" + token
                    ) as cleanup_ws:
                        await cleanup_ws.send(json.dumps({
                            "type": "stop_session", "conversation_id": args.conversation_id
                        }))
                        report["failure_stop_requested"] = True
                        cleanup_deadline = asyncio.get_running_loop().time() + 5
                        while asyncio.get_running_loop().time() < cleanup_deadline:
                            receipt = json.loads(await asyncio.wait_for(cleanup_ws.recv(), 1))
                            if receipt.get("type") == "ack":
                                report["failure_stop_ack"] = True
                                break
                except Exception as cleanup_error:
                    report["failure_stop_error_type"] = type(cleanup_error).__name__
        finally:
            report["credential_revocation_status"] = (
                await client.post("/api/v1/auth/signout")
            ).status_code
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2))


parser = argparse.ArgumentParser()
parser.add_argument("--conversation-id", required=True)
parser.add_argument("--scenario", choices=["cancel", "complete"], required=True)
parser.add_argument("--output", required=True)
asyncio.run(run(parser.parse_args()))
