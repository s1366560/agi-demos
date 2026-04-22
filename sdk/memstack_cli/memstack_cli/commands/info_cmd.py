"""`memstack whoami` / `projects` / `conversations`."""

from __future__ import annotations

from typing import Any

import click

from ..auth import AuthError, resolve_api_key
from ..client import ApiError, die, emit, request


def _key_or_die(flag: str | None) -> str:
    try:
        return resolve_api_key(flag)
    except AuthError as e:
        die(str(e), code=2)
        raise  # unreachable


@click.command("whoami", help="Show current user + tenant.")
@click.pass_context
def whoami(ctx: click.Context) -> None:
    key = _key_or_die(ctx.obj.get("api_key"))
    try:
        data = request("GET", "/auth/me", api_key=key)
    except ApiError as e:
        die(str(e))

    if ctx.obj.get("json"):
        emit(data, as_json=True)
        return
    print(f"id:       {data.get('id')}")
    print(f"email:    {data.get('email')}")
    print(f"tenant:   {data.get('tenant_id')}")
    print(f"is_admin: {data.get('is_superuser', False)}")


@click.command("projects", help="List projects in the current tenant.")
@click.option("--tenant", "tenant", help="Override tenant_id.")
@click.pass_context
def projects(ctx: click.Context, tenant: str | None) -> None:
    key = _key_or_die(ctx.obj.get("api_key"))
    tenant_id = tenant
    if not tenant_id:
        try:
            me = request("GET", "/auth/me", api_key=key)
        except ApiError as e:
            die(str(e))
        tenant_id = me.get("tenant_id")
        if not tenant_id:
            die("no tenant_id in /auth/me; pass --tenant", code=2)

    try:
        data: Any = request(
            "GET", "/projects/", api_key=key, params={"tenant_id": tenant_id}
        )
    except ApiError as e:
        die(str(e))

    items = data.get("items") if isinstance(data, dict) else data
    items = items or []
    if ctx.obj.get("json"):
        emit(items, as_json=True)
        return
    if not items:
        print("(no projects)")
        return
    for p in items:
        print(f"{p.get('id'):<40}{p.get('name', '')}")


@click.command("conversations", help="List conversations.")
@click.option("--project", "project", help="Filter by project_id.")
@click.option("--limit", default=20, show_default=True, help="Max rows to return.")
@click.pass_context
def conversations(ctx: click.Context, project: str | None, limit: int) -> None:
    key = _key_or_die(ctx.obj.get("api_key"))
    params: dict[str, Any] = {"limit": limit}
    if project:
        params["project_id"] = project
    try:
        data: Any = request("GET", "/agent/conversations", api_key=key, params=params)
    except ApiError as e:
        die(str(e))

    items = data.get("items") if isinstance(data, dict) else data
    items = items or []
    if ctx.obj.get("json"):
        emit(items, as_json=True)
        return
    if not items:
        print("(no conversations)")
        return
    for c in items:
        title = c.get("title") or "(untitled)"
        print(f"{c.get('id'):<40}{title}")
