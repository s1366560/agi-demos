"""merge legacy workspace auto agent definitions

Revision ID: h5c6d7e8f9a0
Revises: g4b5c6d7e8f9
Create Date: 2026-06-03

"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.engine import Connection, RowMapping

revision: str = "h5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "g4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTO_TEAM_CREATORS = ("workspace_plan_team_setup", "leader_team_setup")
_TRIGGER_DESCRIPTION = "Execute tasks assigned by the durable workspace plan supervisor."

_ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "architect": {
        "display_name": "Workspace Architect",
        "description": "Researches requirements and produces architecture or implementation plans.",
        "capabilities": ["architecture", "research", "planning", "web_search"],
    },
    "builder": {
        "display_name": "Workspace Builder",
        "description": "Implements backend, frontend, tests, and project artifacts.",
        "capabilities": [
            "software_development",
            "backend",
            "frontend",
            "codegen",
            "file_edit",
            "shell",
            "testing",
        ],
    },
    "verifier": {
        "display_name": "Workspace Verifier",
        "description": "Runs verification, browser checks, and evidence synthesis.",
        "capabilities": ["verification", "browser_e2e", "testing", "evidence", "shell"],
    },
}


def upgrade() -> None:
    """Create project-scoped worker definitions and repoint current bindings."""
    bind = op.get_bind()
    bind.exec_driver_sql("SET LOCAL lock_timeout = '10s'")

    legacy_rows = _legacy_auto_team_definitions(bind)
    grouped_rows: dict[tuple[str, str, str], list[RowMapping]] = {}
    for row in legacy_rows:
        role_key = _infer_role_key(row)
        if role_key is None:
            continue
        grouped_rows.setdefault((row["tenant_id"], row["project_id"], role_key), []).append(row)

    merged_at = datetime.now(UTC)
    for (tenant_id, project_id, role_key), rows in grouped_rows.items():
        canonical_id = _ensure_project_scoped_definition(
            bind=bind,
            tenant_id=tenant_id,
            project_id=project_id,
            role_key=role_key,
            rows=rows,
            merged_at=merged_at,
        )
        legacy_ids = [row["id"] for row in rows]
        _repoint_workspace_agent_bindings(bind, old_agent_ids=legacy_ids, canonical_id=canonical_id)
        _repoint_current_task_assignments(bind, old_agent_ids=legacy_ids, canonical_id=canonical_id)
        _repoint_agent_bindings(bind, old_agent_ids=legacy_ids, canonical_id=canonical_id)
        _mark_legacy_definitions_superseded(
            bind,
            old_agent_ids=legacy_ids,
            canonical_id=canonical_id,
            canonical_name=_team_agent_name(project_id, role_key),
            merged_at=merged_at,
        )


def downgrade() -> None:
    """Data merge is intentionally not reversed."""


def _legacy_auto_team_definitions(bind: Connection) -> list[RowMapping]:
    result = bind.execute(
        sa.text(
            """
            SELECT *
            FROM agent_definitions
            WHERE metadata_json->>'created_by' IN :creators
              AND metadata_json->>'workspace_id' IS NOT NULL
              AND project_id IS NOT NULL
            ORDER BY tenant_id, project_id, display_name, created_at, id
            """
        ).bindparams(sa.bindparam("creators", expanding=True)),
        {"creators": _AUTO_TEAM_CREATORS},
    )
    return [row._mapping for row in result]


def _infer_role_key(row: RowMapping) -> str | None:
    display_name = str(row["display_name"] or "").strip()
    name = str(row["name"] or "").strip().lower()
    if display_name == "Workspace Architect" or name.endswith("-architect"):
        return "architect"
    if display_name == "Workspace Builder" or name.endswith("-builder"):
        return "builder"
    if display_name == "Workspace Verifier" or name.endswith("-verifier"):
        return "verifier"
    return None


def _ensure_project_scoped_definition(
    *,
    bind: Connection,
    tenant_id: str,
    project_id: str,
    role_key: str,
    rows: list[RowMapping],
    merged_at: datetime,
) -> str:
    canonical_name = _team_agent_name(project_id, role_key)
    existing = (
        bind.execute(
            sa.text(
                """
            SELECT *
            FROM agent_definitions
            WHERE name = :name
            ORDER BY created_at, id
            LIMIT 1
            """
            ),
            {"name": canonical_name},
        )
        .mappings()
        .first()
    )
    if existing is not None:
        _update_existing_project_definition(
            bind=bind,
            existing=existing,
            project_id=project_id,
            role_key=role_key,
            rows=rows,
            merged_at=merged_at,
        )
        return str(existing["id"])

    template = rows[-1]
    canonical_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL, f"memstack.workspace-plan-agent:{tenant_id}:{project_id}:{role_key}"
        )
    )
    role_definition = _ROLE_DEFINITIONS[role_key]
    legacy_ids = [str(row["id"]) for row in rows]
    legacy_workspace_ids = _sorted_unique(
        str(row["metadata_json"].get("workspace_id"))
        for row in rows
        if isinstance(row["metadata_json"], dict) and row["metadata_json"].get("workspace_id")
    )
    metadata = {
        "created_by": "workspace_plan_team_setup",
        "project_id": project_id,
        "workspace_role": "execution_worker",
        "team_definition_scope": "project",
        "team_composition_id": f"workspace-plan-team:{project_id}:merged",
        "max_iterations_explicit": False,
        "recommended_capabilities": role_definition["capabilities"],
        "merged_legacy_agent_definition_ids": legacy_ids,
        "merged_legacy_workspace_ids": legacy_workspace_ids,
        "merged_at": merged_at.isoformat(),
    }
    max_iterations = max(80, *[int(row["max_iterations"] or 0) for row in rows])
    allowlist = _merged_allowlist(rows)
    bind.execute(
        _insert_agent_definition_statement(),
        {
            "id": canonical_id,
            "tenant_id": tenant_id,
            "project_id": project_id,
            "name": canonical_name,
            "display_name": role_definition["display_name"],
            "system_prompt": _team_agent_prompt(
                role_definition["display_name"],
                role_definition["description"],
            ),
            "trigger_description": _TRIGGER_DESCRIPTION,
            "trigger_examples": template["trigger_examples"],
            "trigger_keywords": template["trigger_keywords"],
            "model": template["model"],
            "persona_files": template["persona_files"],
            "allowed_tools": ["*"],
            "allowed_skills": [],
            "allowed_mcp_servers": [],
            "max_tokens": template["max_tokens"],
            "temperature": template["temperature"],
            "max_iterations": max_iterations,
            "workspace_dir": None,
            "workspace_config": None,
            "can_spawn": template["can_spawn"],
            "max_spawn_depth": template["max_spawn_depth"],
            "agent_to_agent_enabled": True,
            "agent_to_agent_allowlist": allowlist,
            "discoverable": True,
            "source": template["source"] or "database",
            "enabled": True,
            "max_retries": template["max_retries"],
            "fallback_models": template["fallback_models"],
            "total_invocations": 0,
            "avg_execution_time_ms": 0.0,
            "success_rate": 1.0,
            "metadata_json": metadata,
            "session_policy": template["session_policy"],
            "delegate_config": template["delegate_config"],
            "created_at": merged_at,
            "updated_at": merged_at,
        },
    )
    return canonical_id


def _insert_agent_definition_statement() -> sa.TextClause:
    return sa.text(
        """
        INSERT INTO agent_definitions (
            id, tenant_id, project_id, name, display_name, system_prompt, trigger_description,
            trigger_examples, trigger_keywords, model, persona_files, allowed_tools, allowed_skills,
            allowed_mcp_servers, max_tokens, temperature, max_iterations, workspace_dir,
            workspace_config, can_spawn, max_spawn_depth, agent_to_agent_enabled,
            agent_to_agent_allowlist, discoverable, source, enabled, max_retries, fallback_models,
            total_invocations, avg_execution_time_ms, success_rate, metadata_json, session_policy,
            delegate_config, created_at, updated_at
        ) VALUES (
            :id, :tenant_id, :project_id, :name, :display_name, :system_prompt,
            :trigger_description, :trigger_examples, :trigger_keywords, :model, :persona_files,
            :allowed_tools, :allowed_skills, :allowed_mcp_servers, :max_tokens, :temperature,
            :max_iterations, :workspace_dir, :workspace_config, :can_spawn, :max_spawn_depth,
            :agent_to_agent_enabled, :agent_to_agent_allowlist, :discoverable, :source, :enabled,
            :max_retries, :fallback_models, :total_invocations, :avg_execution_time_ms,
            :success_rate, :metadata_json, :session_policy, :delegate_config, :created_at,
            :updated_at
        )
        """
    ).bindparams(
        sa.bindparam("trigger_examples", type_=sa.JSON),
        sa.bindparam("trigger_keywords", type_=sa.JSON),
        sa.bindparam("persona_files", type_=sa.JSON),
        sa.bindparam("allowed_tools", type_=sa.JSON),
        sa.bindparam("allowed_skills", type_=sa.JSON),
        sa.bindparam("allowed_mcp_servers", type_=sa.JSON),
        sa.bindparam("workspace_config", type_=sa.JSON),
        sa.bindparam("agent_to_agent_allowlist", type_=sa.JSON),
        sa.bindparam("fallback_models", type_=sa.JSON),
        sa.bindparam("metadata_json", type_=sa.JSON),
        sa.bindparam("session_policy", type_=sa.JSON),
        sa.bindparam("delegate_config", type_=sa.JSON),
    )


def _update_existing_project_definition(
    *,
    bind: Connection,
    existing: RowMapping,
    project_id: str,
    role_key: str,
    rows: list[RowMapping],
    merged_at: datetime,
) -> None:
    role_definition = _ROLE_DEFINITIONS[role_key]
    metadata = dict(existing["metadata_json"] or {})
    metadata.update(
        {
            "created_by": "workspace_plan_team_setup",
            "project_id": project_id,
            "workspace_role": "execution_worker",
            "team_definition_scope": "project",
            "team_composition_id": f"workspace-plan-team:{project_id}:merged",
            "max_iterations_explicit": False,
            "recommended_capabilities": role_definition["capabilities"],
            "merged_legacy_agent_definition_ids": _sorted_unique(
                [
                    *metadata.get("merged_legacy_agent_definition_ids", []),
                    *[row["id"] for row in rows],
                ]
            ),
            "merged_legacy_workspace_ids": _sorted_unique(
                [
                    *metadata.get("merged_legacy_workspace_ids", []),
                    *[
                        row["metadata_json"].get("workspace_id")
                        for row in rows
                        if isinstance(row["metadata_json"], dict)
                        and row["metadata_json"].get("workspace_id")
                    ],
                ]
            ),
            "merged_at": merged_at.isoformat(),
        }
    )
    max_iterations = max(
        int(existing["max_iterations"] or 0), 80, *[int(row["max_iterations"] or 0) for row in rows]
    )
    allowlist = _merged_allowlist([existing, *rows])
    bind.execute(
        sa.text(
            """
            UPDATE agent_definitions
            SET project_id = :project_id,
                display_name = :display_name,
                system_prompt = :system_prompt,
                trigger_description = :trigger_description,
                allowed_tools = :allowed_tools,
                allowed_skills = :allowed_skills,
                allowed_mcp_servers = :allowed_mcp_servers,
                max_iterations = :max_iterations,
                agent_to_agent_enabled = true,
                agent_to_agent_allowlist = :agent_to_agent_allowlist,
                discoverable = true,
                enabled = true,
                metadata_json = :metadata_json,
                updated_at = :updated_at
            WHERE id = :id
            """
        ).bindparams(
            sa.bindparam("allowed_tools", type_=sa.JSON),
            sa.bindparam("allowed_skills", type_=sa.JSON),
            sa.bindparam("allowed_mcp_servers", type_=sa.JSON),
            sa.bindparam("agent_to_agent_allowlist", type_=sa.JSON),
            sa.bindparam("metadata_json", type_=sa.JSON),
        ),
        {
            "id": existing["id"],
            "project_id": project_id,
            "display_name": role_definition["display_name"],
            "system_prompt": _team_agent_prompt(
                role_definition["display_name"],
                role_definition["description"],
            ),
            "trigger_description": _TRIGGER_DESCRIPTION,
            "allowed_tools": ["*"],
            "allowed_skills": [],
            "allowed_mcp_servers": [],
            "max_iterations": max_iterations,
            "agent_to_agent_allowlist": allowlist,
            "metadata_json": metadata,
            "updated_at": merged_at,
        },
    )


def _repoint_workspace_agent_bindings(
    bind: Connection,
    *,
    old_agent_ids: list[str],
    canonical_id: str,
) -> None:
    for old_agent_id in old_agent_ids:
        bindings = bind.execute(
            sa.text(
                """
                SELECT id, workspace_id
                FROM workspace_agents
                WHERE agent_id = :old_agent_id
                ORDER BY created_at, id
                """
            ),
            {"old_agent_id": old_agent_id},
        ).mappings()
        for binding in bindings:
            existing = bind.execute(
                sa.text(
                    """
                    SELECT id
                    FROM workspace_agents
                    WHERE workspace_id = :workspace_id
                      AND agent_id = :canonical_id
                    LIMIT 1
                    """
                ),
                {"workspace_id": binding["workspace_id"], "canonical_id": canonical_id},
            ).first()
            if existing is not None:
                bind.execute(
                    sa.text(
                        """
                        UPDATE workspace_agents
                        SET is_active = false,
                            status = 'offline',
                            updated_at = :updated_at
                        WHERE id = :id
                        """
                    ),
                    {"id": binding["id"], "updated_at": datetime.now(UTC)},
                )
                continue
            bind.execute(
                sa.text(
                    """
                    UPDATE workspace_agents
                    SET agent_id = :canonical_id,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                {
                    "id": binding["id"],
                    "canonical_id": canonical_id,
                    "updated_at": datetime.now(UTC),
                },
            )


def _repoint_current_task_assignments(
    bind: Connection,
    *,
    old_agent_ids: list[str],
    canonical_id: str,
) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE workspace_tasks
            SET assignee_agent_id = :canonical_id,
                updated_at = :updated_at
            WHERE assignee_agent_id IN :old_agent_ids
            """
        ).bindparams(sa.bindparam("old_agent_ids", expanding=True)),
        {
            "canonical_id": canonical_id,
            "old_agent_ids": old_agent_ids,
            "updated_at": datetime.now(UTC),
        },
    )


def _repoint_agent_bindings(
    bind: Connection,
    *,
    old_agent_ids: list[str],
    canonical_id: str,
) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE agent_bindings
            SET agent_id = :canonical_id
            WHERE agent_id IN :old_agent_ids
            """
        ).bindparams(sa.bindparam("old_agent_ids", expanding=True)),
        {"canonical_id": canonical_id, "old_agent_ids": old_agent_ids},
    )


def _mark_legacy_definitions_superseded(
    bind: Connection,
    *,
    old_agent_ids: list[str],
    canonical_id: str,
    canonical_name: str,
    merged_at: datetime,
) -> None:
    rows = bind.execute(
        sa.text(
            """
            SELECT id, metadata_json
            FROM agent_definitions
            WHERE id IN :old_agent_ids
            """
        ).bindparams(sa.bindparam("old_agent_ids", expanding=True)),
        {"old_agent_ids": old_agent_ids},
    ).mappings()
    for row in rows:
        metadata = dict(row["metadata_json"] or {})
        metadata.update(
            {
                "superseded_by_agent_definition_id": canonical_id,
                "superseded_by": canonical_name,
                "superseded_at": merged_at.isoformat(),
            }
        )
        bind.execute(
            sa.text(
                """
                UPDATE agent_definitions
                SET discoverable = false,
                    metadata_json = :metadata_json,
                    updated_at = :updated_at
                WHERE id = :id
                """
            ).bindparams(sa.bindparam("metadata_json", type_=sa.JSON)),
            {"id": row["id"], "metadata_json": metadata, "updated_at": merged_at},
        )


def _merged_allowlist(rows: list[RowMapping]) -> list[str]:
    values: list[str] = []
    for row in rows:
        allowlist = row["agent_to_agent_allowlist"] or []
        if not isinstance(allowlist, list):
            continue
        values.extend(str(value) for value in allowlist if value)
    return _sorted_unique(values)


def _sorted_unique(values: Sequence[Any]) -> list[str]:
    return sorted({str(value) for value in values if value is not None and str(value)})


def _team_agent_name(project_id: str, role_key: str) -> str:
    compact_project_id = "".join(ch for ch in project_id.lower() if ch.isalnum())[:16]
    return f"workspace-plan-{compact_project_id}-{role_key}"


def _team_agent_prompt(display_name: str, description: str) -> str:
    return (
        f"You are {display_name}, an execution worker in an autonomous workspace team. "
        f"{description} Follow the workspace task binding exactly, report progress through "
        "workspace reporting tools, provide concrete artifacts and verification evidence, "
        "and do not finalize the root goal yourself; the durable plan supervisor owns closeout."
    )
