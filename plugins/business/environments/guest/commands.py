"""Environments command shaping. Sockets and tickets stay on the host."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from pydantic import ValidationError

from plugins.business.environments.guest.sandbox import project_metrics, project_sandbox
from plugins.business.guest_runtime.binding import current
from plugins.business.guest_runtime.fetch import exchange, object_body
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

_CLUSTER_FIELDS = {
    "id",
    "name",
    "status",
    "health_status",
    "compute_provider",
    "created_at",
    "updated_at",
    "last_health_check",
    "proxy_endpoint",
}


async def _exchange(
    method: str, suffix: str, body: dict[str, Any] | None = None, *, absent_ok: bool = False
) -> dict[str, Any] | None:
    raw = await current().data(
        "environments.sandbox.exchange",
        {"method": method, "suffix": suffix, "body": body, "absent_ok": absent_ok},
    )
    document = raw["document"]
    return document if isinstance(document, dict) or document is None else None


async def _capability(ctx: object) -> object:
    from plugins.business.environments.backend.package_sandbox_operations import _Capabilities

    try:
        return _Capabilities.model_validate(await _exchange("GET", "/capabilities")).terminal_resume
    except ValidationError as exc:
        raise OptionalBusinessError("runtime_unavailable", "Invalid terminal capability") from exc


async def read_sandbox(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.environments.backend.package_sandbox_operations import _Read

    query = _Read.model_validate(payload)
    tenant, project = ctx.scope.tenant_id, ctx.scope.project_id
    if query.metrics_for:
        sandbox = project_sandbox(tenant, project, await _exchange("GET", "", absent_ok=True))
        if not sandbox or sandbox["sandbox_id"] != query.metrics_for:
            raise OptionalBusinessError("conflict", "The selected sandbox has changed")
        metrics = project_metrics(
            project, query.metrics_for, await _exchange("GET", "/stats") or {}
        )
        return {"metrics": metrics}
    capability = await _capability(ctx)
    return {
        "sandbox": project_sandbox(tenant, project, await _exchange("GET", "", absent_ok=True)),
        "terminal": capability.model_dump(),
    }


async def prepare_sandbox(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from plugins.business.environments.backend.package_sandbox_operations import _Prepare

    data = _Prepare.model_validate(payload)
    return {
        "sandbox": project_sandbox(
            ctx.scope.tenant_id,
            ctx.scope.project_id,
            await _exchange("POST", "", data.model_dump()),
        )
    }


async def restart_sandbox(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.backend.package_sandbox_operations import _Input

    _Input.model_validate(payload)
    response = await _exchange("POST", "/restart")
    if not response or response.get("success") is not True:
        raise OptionalBusinessError("runtime_unavailable", "Sandbox restart failed")
    return {"success": True}


async def terminate_sandbox(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.backend.package_sandbox_operations import _Input

    _Input.model_validate(payload)
    response = await _exchange("DELETE", "")
    if not response or response.get("success") is not True:
        raise OptionalBusinessError("runtime_unavailable", "Sandbox termination failed")
    return {"success": True}


async def authorize_terminal(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from plugins.business.environments.backend.package_sandbox_operations import (
        _Grant,
        _PrivateGrant,
        _RunAuthorization,
    )

    run = _RunAuthorization.model_validate(payload)
    capability = await _capability(ctx)
    if capability.availability != "available":
        raise OptionalBusinessError(
            "runtime_unavailable", capability.reason_code or "terminal_authority_unavailable"
        )
    try:
        response = await _exchange(
            "POST", "/terminal/sessions", run.model_dump(exclude={"open_channel"})
        )
        grant = (_PrivateGrant if run.open_channel else _Grant).model_validate(response)
    except ValidationError as exc:
        raise OptionalBusinessError(
            "runtime_unavailable", "Invalid terminal authorization"
        ) from exc
    if (grant.project_id, grant.run_id, grant.run_revision) != (
        ctx.scope.project_id,
        run.run_id,
        run.expected_run_revision,
    ):
        raise OptionalBusinessError("forbidden", "Terminal grant scope mismatch")
    if isinstance(grant, _PrivateGrant):
        opened = await current().data(
            "environments.terminal.open",
            {"session_id": grant.session_id, "resume_token": grant.resume_token},
        )
        return {"channel": opened["channel"]}
    return grant.model_dump()


async def _pool(
    ctx: object,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not ctx.scope.tenant_id:
        raise HTTPException(403, _("Tenant membership is required"))
    query = {**(params or {}), "scope": "tenant", "tenant_id": ctx.scope.tenant_id}
    status, payload = await exchange(
        "GET" if method == "GET" else method, f"/api/v1/admin/pool/{path}", query=query, body=body
    )
    if status == 403:
        return {"forbidden": True}
    return object_body(status, payload, _("Runtime pool operation failed"))


async def read_pool(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.environments.backend.pool_operations import Read

    query = Read.model_validate(payload)
    params = query.model_dump(exclude={"resource"}, exclude_none=True)
    return await _pool(
        ctx, "GET", query.resource, params=params if query.resource == "instances" else None
    )


async def control_pool(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.environments.backend.pool_operations import Control

    command = Control.model_validate(payload)
    key = command.instance_key
    if key in {".", ".."}:
        raise HTTPException(422, _("Invalid instance key"))
    path = f"instances/{quote(key, safe='')}"
    if command.action == "terminate":
        return await _pool(ctx, "DELETE", path, params={"graceful": command.graceful})
    return await _pool(ctx, "POST", f"{path}/{command.action}")


async def set_tier(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.environments.backend.pool_operations import Tier

    command = Tier.model_validate(payload)
    return await _pool(
        ctx, "POST", f"projects/{command.project_id}/tier", body={"tier": command.tier}
    )


def _cluster_item(row: dict[str, Any], tenant: str) -> dict[str, Any]:
    if row.get("tenant_id") != tenant:
        raise OptionalBusinessError("forbidden", "Environment belongs to another tenant")
    item = {key: row[key] for key in _CLUSTER_FIELDS if key in row and row[key] is not None}
    item["provider_config"] = row.get("provider_config")
    return item


async def write_cluster(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from typing import Annotated

    from pydantic import Field, TypeAdapter

    from plugins.business.environments.command_models import (
        ClusterCreateCommand as _Create,
        ClusterEditCommand as _Edit,
        ClusterUpdateCommand as _Update,
    )

    TypeAdapter(
        Annotated[_Create | _Edit | _Update, Field(discriminator="action")]
    ).validate_python(payload)
    raw = await current().data("environments.clusters.write", payload)
    return {"item": _cluster_item(raw["row"], ctx.scope.tenant_id)}


async def delete_cluster(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.environments.command_models import _Key

    key = _Key.model_validate(payload)
    await current().data("environments.clusters.delete", {"id": key.id})
    return {}


async def _channel(ctx: object, payload: dict[str, Any], kind: str) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.backend.interaction_channel import _ACTION

    _ACTION.validate_python(payload)
    raw = await current().data("environments.channel", {"kind": kind, "payload": payload})
    if "data" in raw and "channel" not in raw:
        return {"data": raw["data"]}
    if "channel" in raw and len(raw) == 1:
        return {"channel": raw["channel"]}
    return {key: value for key, value in raw.items() if key != "resume_token"}


async def project_terminal(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    return await _channel(ctx, payload, "terminal")


async def project_desktop(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    return await _channel(ctx, payload, "desktop")


async def list_pools(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.environments.command_models import _Cluster

    _Cluster.model_validate(payload)
    raw = await current().data("environments.runners.list", payload)
    return {"items": raw["items"]}


async def create_pool(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.command_models import _CreatePool

    _CreatePool.model_validate(payload)
    raw = await current().data("environments.runners.create", payload)
    return {"item": raw["item"]}


async def issue_token(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.command_models import _IssueToken

    _IssueToken.model_validate(payload)
    raw = await current().data("environments.runners.token", payload)
    return {key: value for key, value in raw["token"].items() if key != "credentials_encrypted"}


def _deploy_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        **record,
        "completed_at": record.get("finished_at"),
        "description": record.get("message"),
        "error_message": record.get("message") if record.get("status") == "failed" else None,
    }


async def read_deploys(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.command_models import DeployRead as Read

    Read.model_validate(payload)
    raw = await current().data("environments.deploys.read", payload)
    if raw["kind"] == "list":
        page = dict(raw["page"])
        deploys = page.pop("deploys", [])
        return {**page, "deployments": [_deploy_row(row) for row in deploys]}
    return _deploy_row(raw["record"])


async def change_deploy(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.command_models import DeployChange as Change

    Change.model_validate(payload)
    raw = await current().data("environments.deploys.write", payload)
    return _deploy_row(raw["record"])


async def read_templates(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.command_models import TemplateRead

    TemplateRead.model_validate(payload)
    return await current().data("environments.templates.read", payload)


async def change_template(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    del ctx
    from plugins.business.environments.command_models import TemplateChange

    TemplateChange.model_validate(payload)
    raw = await current().data("environments.templates.write", payload)
    if raw.get("deleted"):
        return {}
    return {key: value for key, value in raw["row"].items() if key != "credentials_encrypted"}


async def create_instance(
    ctx: object, payload: dict[str, Any], _progress: object
) -> dict[str, Any]:
    from src.application.schemas.instance_schemas import InstanceCreate

    await current().data("environments.instances.access", {})
    data = InstanceCreate.model_validate(payload)
    if data.tenant_id != ctx.scope.tenant_id or data.workspace_id:
        raise OptionalBusinessError("forbidden", "Instance is outside the tenant wizard scope")
    if data.cluster_id:
        owned = await current().data("environments.instances.cluster", {"id": data.cluster_id})
        if not owned["ok"]:
            raise OptionalBusinessError("page_not_found", "Cluster unavailable")
    created = await current().data("environments.instances.create", data.model_dump(mode="json"))
    return {"id": created["id"]}


_INSTANCE_FIELDS = _CLUSTER_FIELDS - {"last_health_check", "proxy_endpoint"} | {
    "description",
    "cluster_id",
    "runtime",
    "image_version",
    "replicas",
    "available_replicas",
    "cpu_request",
    "cpu_limit",
    "mem_request",
    "mem_limit",
    "current_revision",
}


def _inventory_item(row: dict[str, Any], tenant: str, kind: str) -> dict[str, Any]:
    if row.get("tenant_id") != tenant:
        raise OptionalBusinessError("forbidden", "Environment belongs to another tenant")
    fields = _INSTANCE_FIELDS if kind == "instance" else _CLUSTER_FIELDS
    return {key: row[key] for key in fields if key in row and row[key] is not None}


async def inventory(ctx: object, payload: dict[str, Any], _progress: object) -> dict[str, Any]:
    from plugins.business.environments.command_models import InventoryQuery

    query = InventoryQuery.model_validate(payload)
    if query.health and (not query.id or query.kind != "clusters"):
        raise OptionalBusinessError("invalid_request", "Cluster health requires a cluster ID")
    raw = await current().data("environments.inventory.read", payload)
    if "health" in raw:
        return {"health": raw["health"]}
    kind = str(raw.get("kind") or "cluster")
    if "item" in raw:
        return {"item": _inventory_item(raw["item"], ctx.scope.tenant_id, kind)}
    return {
        "items": [_inventory_item(row, ctx.scope.tenant_id, kind) for row in raw["items"]],
        "total": raw["total"],
    }


OPERATIONS = {
    "app.environments.sandbox.read": read_sandbox,
    "app.environments.sandbox.prepare": prepare_sandbox,
    "app.environments.terminal.authorize": authorize_terminal,
    "app.environments.inventory.read": inventory,
    "app.environments.clusters.write": write_cluster,
    "app.environments.clusters.delete": delete_cluster,
    "app.environments.sandbox.restart": restart_sandbox,
    "app.environments.sandbox.terminate": terminate_sandbox,
    "app.environments.terminal.interact": project_terminal,
    "app.environments.desktop.interact": project_desktop,
    "app.environments.runners.read": list_pools,
    "app.environments.runners.create": create_pool,
    "app.environments.runners.register": issue_token,
    "app.environments.deploys.read": read_deploys,
    "app.environments.deploys.write": change_deploy,
    "app.environments.templates.read": read_templates,
    "app.environments.templates.write": change_template,
    "app.environments.instances.create": create_instance,
    "app.environments.pool.read": read_pool,
    "app.environments.pool.control": control_pool,
    "app.environments.pool.tier": set_tier,
}
