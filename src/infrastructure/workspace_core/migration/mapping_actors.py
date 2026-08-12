"""Lossless source-to-Avernet field mappings for Workspace migration."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from .model import DatabaseRow, canonical_hash, canonical_json, decode_json
from .source_columns import WORKSPACE_SOURCE_COLUMNS

_ENVIRONMENT = "memstack"


def _json(row: DatabaseRow, name: str, default: object) -> object:
    return decode_json(row.get(name), default=default)


def _scope(row: DatabaseRow) -> dict[str, object]:
    return {
        "tenant_id": row["_tenant_id"],
        "project_id": row["_project_id"],
        "workspace_id": row.get("_workspace_id"),
    }


def _updated_at(row: DatabaseRow) -> object:
    return row.get("updated_at") or row["created_at"]


def _epoch_millis(value: object) -> int:
    if not isinstance(value, datetime):
        raise TypeError("timestamp source value must be a datetime")
    timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return int(timestamp.timestamp() * 1000)


def _copy(values: Mapping[str, object], mapping: Mapping[str, str]) -> dict[str, object]:
    return {source: values[target] for source, target in mapping.items()}


def _workspace_profile(row: DatabaseRow) -> dict[str, object]:
    metadata = _json(row, "metadata_json", {})
    hex_layout = _json(row, "hex_layout_config_json", {})
    blocking_categories = _json(row, "default_blocking_categories_json", [])
    source = {key: row[key] for key in WORKSPACE_SOURCE_COLUMNS}
    source.update(
        {
            "metadata_json": metadata,
            "hex_layout_config_json": hex_layout,
            "default_blocking_categories_json": blocking_categories,
        }
    )
    return {
        "workspace_id": row["id"],
        "tenant_id": row["tenant_id"],
        "project_id": row["project_id"],
        "group_id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "created_by": row["created_by"],
        "is_archived": row["is_archived"],
        "office_status": row["office_status"],
        "hex_layout_config_json": hex_layout,
        "default_blocking_categories_json": blocking_categories,
        "metadata_json": metadata,
        "source_hash": canonical_hash(source),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _workspace_profile_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "workspace_id",
            "tenant_id": "tenant_id",
            "project_id": "project_id",
            "name": "name",
            "description": "description",
            "created_by": "created_by",
            "is_archived": "is_archived",
            "metadata_json": "metadata_json",
            "office_status": "office_status",
            "hex_layout_config_json": "hex_layout_config_json",
            "default_blocking_categories_json": "default_blocking_categories_json",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )


def _project_principal_membership(row: DatabaseRow) -> dict[str, object]:
    return {
        "tenant_id": row["_tenant_id"],
        "project_id": row["_project_id"],
        "user_id": row["user_id"],
        "participant_actor_id": row["user_id"],
        "source_membership_id": row["id"],
        "role": row["role"],
        "permissions_json": _json(row, "permissions", {}),
        "is_active": True,
        "identity_authority": "memstack",
        "source_created_at": row["created_at"],
        "source_updated_at": _updated_at(row),
    }


def _organization(row: DatabaseRow) -> dict[str, object]:
    return {
        "env": _ENVIRONMENT,
        "code": row["tenant_id"],
        "name": row["tenant_name"],
        "description": row.get("tenant_description"),
        "managing_provider_id": "memstack-agent-runtime",
        "disabled": False,
        "gmt_create": row["created_at"],
        "gmt_modified": _updated_at(row),
    }


def _group(row: DatabaseRow) -> dict[str, object]:
    archived = bool(row["is_archived"])
    return {
        "group_id": row["id"],
        "label": row["name"],
        "status": "inactive" if archived else "active",
        "driver_bot": row["created_by"],
        "originator": row["created_by"],
        "env": _ENVIRONMENT,
        "routing_policy_json": canonical_json({}),
        "context": row.get("description"),
        "group_kind": "normal",
        "version": 1,
        "record_status": "active",
        "lifecycle_status": "archived" if archived else "active",
        "group_strategy": "chat",
        "participants": canonical_json([]),
        "created_by": row["created_by"],
        "visibility": "private",
        "gmt_create": row["created_at"],
        "gmt_modified": _updated_at(row),
    }


def _member(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "member_id": row["id"],
        "user_id": row["user_id"],
        "participant_actor_id": row["user_id"],
        "role": row["role"],
        "invited_by": row.get("invited_by"),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _member_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "member_id",
            "workspace_id": "workspace_id",
            "user_id": "user_id",
            "role": "role",
            "invited_by": "invited_by",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )


def _human_identity(row: DatabaseRow) -> dict[str, object]:
    return {
        "user_id": row["user_id"],
        "auth_source": "memstack",
        "external_user_id": row["user_id"],
        "user_name": row.get("full_name") or row["email"],
        "external_user_name": row["email"],
        "avatar": None,
        "token": None,
        "token_expire_at": None,
        "env": _ENVIRONMENT,
        "gmt_create": row["user_created_at"],
        "gmt_modified": row.get("user_updated_at") or row["user_created_at"],
    }


def _workspace_principal_identity(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "user_id": row["user_id"],
        "participant_actor_id": row["user_id"],
        "email": row["email"],
        "display_name": row.get("full_name"),
        "is_active": row["is_active"],
        "identity_authority": "memstack",
        "source_created_at": row["user_created_at"],
        "source_updated_at": row.get("user_updated_at") or row["user_created_at"],
    }


def _group_participant(
    row: DatabaseRow, *, actor_kind: str, actor_column: str
) -> dict[str, object]:
    return {
        "group_id": row["workspace_id"],
        "bot_uuid": row[actor_column],
        "role": row.get("role") or "worker",
        "env": _ENVIRONMENT,
        "actor_kind": actor_kind,
        "mode": "auto",
        "gmt_create": row["created_at"],
        "gmt_modified": _updated_at(row),
    }


def _human_group_participant(row: DatabaseRow) -> dict[str, object]:
    return _group_participant(row, actor_kind="human", actor_column="user_id")


def _organization_member(row: DatabaseRow) -> dict[str, object]:
    return {
        "env": _ENVIRONMENT,
        "organization_code": row["_tenant_id"],
        "bot_uuid": row["user_id"],
        "role": "member",
        "disabled": False,
        "gmt_create": row["actor_created_at"],
        "gmt_modified": row.get("actor_updated_at") or row["actor_created_at"],
    }


def _agent_policy(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "workspace_id": row["workspace_id"],
        "revision": row["revision"],
        "roles_json": _json(row, "roles_json", {}),
        "fallbacks_json": _json(row, "fallbacks_json", []),
        "reasoning_effort": row["reasoning_effort"],
        "permission_mode": row["permission_mode"],
        "updated_by": row.get("updated_by"),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _agent_policy_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "workspace_id": "workspace_id",
            "tenant_id": "tenant_id",
            "project_id": "project_id",
            "revision": "revision",
            "roles_json": "roles_json",
            "fallbacks_json": "fallbacks_json",
            "reasoning_effort": "reasoning_effort",
            "permission_mode": "permission_mode",
            "updated_by": "updated_by",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )


def _agent_binding(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "binding_id": row["id"],
        "agent_id": row["agent_id"],
        "bot_uuid": row["id"],
        "participant_actor_id": row["id"],
        "display_name": row.get("display_name"),
        "description": row.get("description"),
        "config_json": _json(row, "config_json", {}),
        "is_active": row["is_active"],
        "hex_q": row.get("hex_q"),
        "hex_r": row.get("hex_r"),
        "theme_color": row.get("theme_color"),
        "label": row.get("label"),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _agent_binding_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "binding_id",
            "workspace_id": "workspace_id",
            "agent_id": "agent_id",
            "display_name": "display_name",
            "description": "description",
            "config_json": "config_json",
            "is_active": "is_active",
            "hex_q": "hex_q",
            "hex_r": "hex_r",
            "theme_color": "theme_color",
            "label": "label",
            "status": "status",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )


def _bot(row: DatabaseRow) -> dict[str, object]:
    return {
        "bot_uuid": row["id"],
        "name": row.get("display_name") or row.get("agent_name") or row["agent_id"],
        "bot_info": canonical_json(
            {
                "workspace_id": row["workspace_id"],
                "agent_id": row["agent_id"],
                "description": row.get("description"),
                "config": _json(row, "config_json", {}),
            }
        ),
        "session_token": None,
        "registered_at": row["created_at"],
        "updated_at": _updated_at(row),
        "env": _ENVIRONMENT,
        "visibility": "private",
        "created_by": row.get("workspace_created_by"),
        "actor_kind": "bot",
        "status": "online" if row["is_active"] else "offline",
        "is_deleted": False,
        "agent_code": row["agent_id"],
        "gmt_create": row["created_at"],
        "gmt_modified": _updated_at(row),
    }


def _bot_group_participant(row: DatabaseRow) -> dict[str, object]:
    return _group_participant(row, actor_kind="bot", actor_column="id")
