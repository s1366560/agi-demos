"""Discover and invoke the active release's signed project commands."""

from urllib.parse import quote

import click

from ..auth import AuthError, resolve_api_key
from ..client import ApiError, emit, request


@click.command("plugin")
@click.argument("plugin_id")
@click.argument("command_id", required=False)
@click.option("--project", required=True, help="Project that owns the installation.")
@click.option("--tenant", required=True, help="Tenant that owns the project.")
@click.pass_context
def plugin(
    ctx: click.Context, plugin_id: str, command_id: str | None, project: str, tenant: str
) -> None:
    """List commands from PLUGIN_ID, or invoke its COMMAND_ID."""
    base = "/platform-plugins/v2/optional-business/" + quote(plugin_id, safe="")
    scope = {"tenant_id": tenant, "project_id": project}
    try:
        key = resolve_api_key(ctx.obj.get("api_key"))
        view = request("GET", base, api_key=key, params=scope)
        commands = view.get("commands", [])
        if command_id is None:
            result = {
                "plugin_id": plugin_id,
                "version": view["running_version"],
                "commands": commands,
            }
        else:
            if command_id not in commands or not view.get("actual_digest"):
                raise click.ClickException("Command is unavailable in the active release.")
            result = request(
                "POST",
                base + "/commands",
                api_key=key,
                json={**scope, "command_id": command_id, "expected_digest": view["actual_digest"]},
            )
    except (ApiError, AuthError) as error:
        raise click.ClickException(str(error)) from error
    emit(result, as_json=ctx.obj.get("json", False))
