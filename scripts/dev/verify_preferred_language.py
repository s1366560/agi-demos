# pyright: basic
"""Live end-to-end check: agent reply language follows `preferred_language`.

Covers two entry points:

1. **Direct chat (WS)** — sends `preferred_language` on the `send_message`
   WebSocket frame and inspects the streamed assistant reply.
2. **Workspace task** — creates a workspace + task with
   `preferred_language` via the REST API, then reads the task back to
   confirm the value is persisted to `task.metadata.preferred_language`
   exactly the way `worker_launch._preferred_language_from_metadata`
   expects it.  Combined with the unit tests for that extractor and for
   `_inject_preferred_language_context`, this proves the workspace-task
   originated conversation path carries the language all the way through.

Run:
    uv run python scripts/dev/verify_preferred_language.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.parse
import urllib.request

import websockets

API = "http://localhost:8000"
WS = "ws://localhost:8000/api/v1/agent/ws"
EMAIL = "user@memstack.ai"
PASSWORD = "userpassword"
PROMPT = "Say one short sentence introducing yourself."


def login() -> str:
    data = urllib.parse.urlencode({"username": EMAIL, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{API}/api/v1/auth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["access_token"]


def get_project(token: str) -> dict:
    """Return the first project for the logged-in user (includes tenant_id)."""
    req = urllib.request.Request(
        f"{API}/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["projects"][0]


def create_conversation(token: str, project_id: str, title: str) -> str:
    body = json.dumps({"project_id": project_id, "title": title}).encode()
    req = urllib.request.Request(
        f"{API}/api/v1/agent/conversations",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as r:
        payload = json.loads(r.read())
    return payload.get("conversation_id") or payload["id"]


def create_workspace(token: str, tenant_id: str, project_id: str, name: str) -> str:
    body = json.dumps({"name": name}).encode()
    req = urllib.request.Request(
        f"{API}/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["id"]


def create_workspace_task(
    token: str,
    workspace_id: str,
    title: str,
    preferred_language: str | None,
) -> dict:
    payload: dict = {"title": title}
    if preferred_language is not None:
        payload["preferred_language"] = preferred_language
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API}/api/v1/workspaces/{workspace_id}/tasks",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def get_workspace_task(token: str, workspace_id: str, task_id: str) -> dict:
    req = urllib.request.Request(
        f"{API}/api/v1/workspaces/{workspace_id}/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def classify(text: str) -> str:
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    ascii_letters = sum(1 for c in text if c.isascii() and c.isalpha())
    if cjk >= 3:
        return f"Chinese (cjk={cjk}, ascii_letters={ascii_letters})"
    if ascii_letters >= 3 and cjk == 0:
        return f"English (cjk=0, ascii_letters={ascii_letters})"
    return f"Mixed/unknown (cjk={cjk}, ascii_letters={ascii_letters})"


async def one_round(token: str, project_id: str, preferred_language: str | None) -> dict:
    label = preferred_language or "<omitted>"
    conv_id = create_conversation(token, project_id, f"lang-test-{label}")
    url = f"{WS}?token={token}&session_id=verify-{label}"

    frame: dict = {
        "type": "send_message",
        "conversation_id": conv_id,
        "message": PROMPT,
        "project_id": project_id,
    }
    if preferred_language is not None:
        frame["preferred_language"] = preferred_language

    chunks: list[str] = []
    error: str | None = None
    async with websockets.connect(url, max_size=None) as ws:
        # Subscribe + send
        await ws.send(json.dumps({"type": "subscribe", "conversation_id": conv_id}))
        await ws.send(json.dumps(frame))

        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
                msg = json.loads(raw)
                mtype = msg.get("type")
                data = msg.get("data") or {}
                if mtype == "text_delta":
                    delta = data.get("delta") or data.get("text") or ""
                    if isinstance(delta, str):
                        chunks.append(delta)
                elif mtype == "complete" or mtype == "assistant_message":
                    # capture final content too if present
                    content = data.get("content") or data.get("text")
                    if isinstance(content, str) and content and not chunks:
                        chunks.append(content)
                    break
                elif mtype == "error":
                    error = json.dumps(data)[:300]
                    break
        except TimeoutError:
            error = "timeout waiting for completion"

    full = "".join(chunks).strip()
    return {
        "preferred_language": label,
        "conversation_id": conv_id,
        "reply": full,
        "classification": classify(full),
        "error": error,
    }


async def workspace_task_round(
    token: str,
    tenant_id: str,
    project_id: str,
    preferred_language: str,
) -> dict:
    """Create a workspace + task with `preferred_language`, then read the task
    back and check the metadata key the worker_launch extractor consumes.

    This validates the persistence contract end-to-end. The downstream stages
    (extractor → stream_chat_v2 → _inject_preferred_language_context → LLM)
    are already covered by direct-chat round + unit tests.
    """
    ws_id = create_workspace(
        token,
        tenant_id,
        project_id,
        name=f"lang-verify-{preferred_language}-{int(asyncio.get_event_loop().time() * 1000)}",
    )
    created = create_workspace_task(
        token,
        ws_id,
        title=f"lang-task-{preferred_language}",
        preferred_language=preferred_language,
    )
    fetched = get_workspace_task(token, ws_id, created["id"])
    persisted = (fetched.get("metadata") or {}).get("preferred_language")
    ok = persisted == preferred_language
    return {
        "preferred_language": preferred_language,
        "workspace_id": ws_id,
        "task_id": created["id"],
        "persisted_metadata_preferred_language": persisted,
        "ok": ok,
    }


async def main() -> int:
    token = login()
    project = get_project(token)
    project_id = project["id"]
    tenant_id = project["tenant_id"]
    print(f"project_id={project_id}  tenant_id={tenant_id}\n", flush=True)

    # --- Part A: direct chat (WS) ---
    print("=" * 60)
    print("A. Direct chat — preferred_language on WS send_message frame")
    print("=" * 60)
    chat_results = []
    for lang in ("en-US", "zh-CN", None):
        print(f"--- round preferred_language={lang} ---", flush=True)
        r = await one_round(token, project_id, lang)
        print(f"reply: {r['reply'][:300]}")
        print(f"=> {r['classification']}")
        if r["error"]:
            print(f"!! error: {r['error']}")
        print()
        chat_results.append(r)

    en = next(x for x in chat_results if x["preferred_language"] == "en-US")
    zh = next(x for x in chat_results if x["preferred_language"] == "zh-CN")
    chat_en_ok = en["classification"].startswith("English")
    chat_zh_ok = zh["classification"].startswith("Chinese")

    # --- Part B: workspace-task originated path ---
    print("=" * 60)
    print("B. Workspace task — preferred_language persisted to task.metadata")
    print("=" * 60)
    ws_results = []
    for lang in ("en-US", "zh-CN"):
        print(f"--- round preferred_language={lang} ---", flush=True)
        r = await workspace_task_round(token, tenant_id, project_id, lang)
        print(
            f"workspace_id={r['workspace_id'][:8]}... task_id={r['task_id'][:8]}... "
            f"metadata.preferred_language={r['persisted_metadata_preferred_language']!r} "
            f"=> {'OK' if r['ok'] else 'MISMATCH'}"
        )
        print()
        ws_results.append(r)

    ws_en_ok = next(r for r in ws_results if r["preferred_language"] == "en-US")["ok"]
    ws_zh_ok = next(r for r in ws_results if r["preferred_language"] == "zh-CN")["ok"]

    # --- Verdict ---
    print("=" * 60)
    print("VERDICT")
    print("=" * 60)
    print(f"  Direct chat   en-US -> English reply : {chat_en_ok}")
    print(f"  Direct chat   zh-CN -> Chinese reply : {chat_zh_ok}")
    print(f"  Workspace task en-US -> metadata persisted : {ws_en_ok}")
    print(f"  Workspace task zh-CN -> metadata persisted : {ws_zh_ok}")
    all_ok = chat_en_ok and chat_zh_ok and ws_en_ok and ws_zh_ok
    print(f"  ALL OK : {all_ok}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
