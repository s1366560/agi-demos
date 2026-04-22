"""`memstack chat` — one-shot or streaming prompt."""

from __future__ import annotations

import json as _json
import uuid

import click

from ..auth import AuthError, resolve_api_key
from ..client import ApiError, die, emit, request, stream_sse


@click.command("chat", help="Send a single message to an agent.")
@click.argument("project_id")
@click.argument("message")
@click.option("--conversation", help="Reuse an existing conversation_id.")
@click.option("--stream", "stream", is_flag=True, help="Consume SSE events.")
@click.pass_context
def chat(
    ctx: click.Context,
    project_id: str,
    message: str,
    conversation: str | None,
    stream: bool,
) -> None:
    try:
        key = resolve_api_key(ctx.obj.get("api_key"))
    except AuthError as e:
        die(str(e), code=2)
        return

    conversation_id = conversation or str(uuid.uuid4())
    body = {
        "conversation_id": conversation_id,
        "message": message,
        "project_id": project_id,
    }
    as_json = bool(ctx.obj.get("json"))
    if not as_json:
        click.echo(f"[conversation_id={conversation_id}]", err=True)

    if stream:
        try:
            for event_name, data in stream_sse(
                "POST", "/agent/chat", api_key=key, json=body
            ):
                if as_json:
                    print(_json.dumps({"event": event_name, "data": data}))
                    continue
                try:
                    evt = _json.loads(data)
                except _json.JSONDecodeError:
                    print(f"[{event_name}] {data}")
                    continue
                kind = evt.get("type") or event_name
                text = evt.get("content") or evt.get("delta") or ""
                if text:
                    print(f"[{kind}] {text}")
                else:
                    print(f"[{kind}]")
        except ApiError as e:
            die(str(e))
        return

    try:
        data = request("POST", "/agent/chat", api_key=key, json=body)
    except ApiError as e:
        die(str(e))
    emit(data, as_json=as_json)
