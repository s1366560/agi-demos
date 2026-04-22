"""`memstack artifacts list|pull` — artifact browsing + download."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import httpx

from ..auth import AuthError, resolve_api_key
from ..client import ApiError, base_url, die, emit, request


def _key_or_die(flag: str | None) -> str:
    try:
        return resolve_api_key(flag)
    except AuthError as e:
        die(str(e), code=2)
        raise


@click.group("artifacts", help="Manage tool output artifacts.")
def artifacts_group() -> None:
    pass


@artifacts_group.command("list", help="List artifacts for a project.")
@click.option("--project", "project_id", required=True, help="Project ID.")
@click.option("--category", help="Filter by category (image/video/audio/...).")
@click.option("--tool-execution", help="Filter by tool execution id.")
@click.option("--limit", default=100, show_default=True)
@click.pass_context
def list_artifacts(
    ctx: click.Context,
    project_id: str,
    category: str | None,
    tool_execution: str | None,
    limit: int,
) -> None:
    key = _key_or_die(ctx.obj.get("api_key"))
    params: dict[str, Any] = {"project_id": project_id, "limit": limit}
    if category:
        params["category"] = category
    if tool_execution:
        params["tool_execution_id"] = tool_execution
    try:
        data = request("GET", "/artifacts", api_key=key, params=params)
    except ApiError as e:
        die(str(e))

    items = data.get("artifacts") if isinstance(data, dict) else data
    items = items or []
    if ctx.obj.get("json"):
        emit(items, as_json=True)
        return
    if not items:
        print("(no artifacts)")
        return
    for a in items:
        aid = a.get("id", "")
        name = a.get("filename", "")
        cat = a.get("category", "")
        size = a.get("size_bytes", 0)
        print(f"{aid:<40}{cat:<12}{size:>10}  {name}")


@artifacts_group.command("pull", help="Download an artifact to a local file.")
@click.argument("artifact_id")
@click.option("--output", "output", type=click.Path(dir_okay=False, path_type=Path), help="Output path (default: filename from server).")
@click.pass_context
def pull_artifact(ctx: click.Context, artifact_id: str, output: Path | None) -> None:
    key = _key_or_die(ctx.obj.get("api_key"))

    # Need filename for default output.
    try:
        meta = request("GET", f"/artifacts/{artifact_id}", api_key=key)
    except ApiError as e:
        die(str(e))
    dest = output or Path(meta.get("filename") or artifact_id)

    url = f"{base_url()}/api/v1/artifacts/{artifact_id}/download"
    try:
        with httpx.stream(
            "GET", url, headers={"Authorization": f"Bearer {key}"}, timeout=120.0
        ) as resp:
            if resp.status_code >= 400:
                die(f"download failed: HTTP {resp.status_code}: {resp.read().decode('utf-8', 'replace')}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
    except httpx.HTTPError as e:  # pragma: no cover
        die(f"transport error: {e}")

    if ctx.obj.get("json"):
        emit({"artifact_id": artifact_id, "path": str(dest)}, as_json=True)
    else:
        print(f"Saved {dest}")
