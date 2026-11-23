"""Manage independent releases through the project's signed-package API."""

from __future__ import annotations

import base64
from pathlib import Path
from urllib.parse import quote

import click

from ..auth import AuthError, resolve_api_key
from ..client import ApiError, emit, request

_BASE = "/platform-plugins/v2/optional-business"


@click.group("packages")
@click.option("--tenant", required=True)
@click.option("--project", required=True)
@click.pass_context
def packages(ctx: click.Context, tenant: str, project: str) -> None:
    """Manage the signed packages selected for a project."""
    try:
        ctx.obj = {
            **ctx.obj,
            "key": resolve_api_key(ctx.obj.get("api_key")),
            "scope": {"tenant_id": tenant, "project_id": project},
        }
    except AuthError as error:
        raise click.ClickException(str(error)) from error


def _archive_body(path: Path, scope: dict[str, str]) -> dict[str, str]:
    limit = 12 * 1024 * 1024
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("archive exceeds the project upload limit")
    return {**scope, "archive_base64": base64.b64encode(raw).decode("ascii")}


@packages.command("inspect")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_context
def inspect_package(ctx: click.Context, archive: Path) -> None:
    """Verify the archive and show its signed permissions and service bindings."""
    try:
        body = _archive_body(archive, ctx.obj["scope"])
        verified = request("POST", _BASE + "/inspect", api_key=ctx.obj["key"], json=body)
    except (ApiError, OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    emit(verified, as_json=ctx.obj["json"])


@packages.command("install")
@click.argument(
    "archives",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    nargs=-1,
    required=True,
)
@click.option(
    "--approve",
    multiple=True,
    help="Allow this permission in the selected files. Repeat for additional permissions.",
)
@click.pass_context
def install(ctx: click.Context, archives: tuple[Path, ...], approve: tuple[str, ...]) -> None:
    """Verify and enable ARCHIVES in order. Each release is independent."""
    key, scope = ctx.obj["key"], ctx.obj["scope"]
    installed = []
    for path in archives:
        try:
            body = _archive_body(path, scope)
            verified = request("POST", _BASE + "/inspect", api_key=key, json=body)
            needed = verified["permissions"]
            missing = set(needed) - set(approve)
            if missing:
                raise ValueError("permissions require approval: " + ", ".join(sorted(missing)))
            record = request(
                "POST",
                _BASE + "/install",
                api_key=key,
                json={**body, "approved_permissions": needed},
            )
            url = _BASE + "/" + quote(verified["plugin_id"], safe="")
            staged = request("GET", url, api_key=key, params=scope)
            if (
                record["digest"] != verified["digest"]
                or staged["desired_digest"] != verified["digest"]
            ):
                raise ValueError("project selection changed during installation")
            if staged["actual_digest"] != verified["digest"]:
                request(
                    "POST",
                    url + "/enable",
                    api_key=key,
                    json={**scope, "expected_revision": staged["desired_revision"]},
                )
            installed.append(
                {
                    "plugin_id": verified["plugin_id"],
                    "version": verified["version"],
                    "digest": verified["digest"],
                }
            )
        except (ApiError, OSError, ValueError) as error:
            prior = ", ".join(item["plugin_id"] for item in installed)
            suffix = f" (previously enabled: {prior})" if prior else ""
            raise click.ClickException(f"{path.name}: {error}{suffix}") from error
    emit({"items": installed}, as_json=ctx.obj["json"])


@packages.command("list")
@click.pass_context
def list_packages(ctx: click.Context) -> None:
    """Show installed and running versions for the project."""
    try:
        result = request("GET", _BASE + "/", api_key=ctx.obj["key"], params=ctx.obj["scope"])
    except ApiError as error:
        raise click.ClickException(str(error)) from error
    emit(result, as_json=ctx.obj["json"])


@packages.command("rollback")
@click.argument("plugin_id")
@click.pass_context
def rollback(ctx: click.Context, plugin_id: str) -> None:
    """Restore the previously running signed release of PLUGIN_ID."""
    url = _BASE + "/" + quote(plugin_id, safe="")
    scope, key = ctx.obj["scope"], ctx.obj["key"]
    try:
        view = request("GET", url, api_key=key, params=scope)
        request(
            "POST",
            url + "/rollback",
            api_key=key,
            json={**scope, "expected_revision": view["desired_revision"]},
        )
        result = request("GET", url, api_key=key, params=scope)
    except ApiError as error:
        raise click.ClickException(str(error)) from error
    emit(result, as_json=ctx.obj["json"])
