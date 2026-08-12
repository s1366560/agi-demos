"""Session, plan, outbox, pipeline, and deployment migration mappings."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .mapping_actors import (
    _ENVIRONMENT,
    _copy,
    _epoch_millis,
    _json,
    _scope,
    _updated_at,
)
from .model import DatabaseRow, canonical_hash, canonical_json, decode_json
from .source_columns import (
    AUTHORITY_SOURCE_COLUMNS,
    DEPLOYMENT_SOURCE_COLUMNS,
    MESSAGE_SOURCE_COLUMNS,
    PIPELINE_CONTRACT_JSON_COLUMNS,
    PIPELINE_CONTRACT_SOURCE_COLUMNS,
    PIPELINE_RUN_SOURCE_COLUMNS,
    PIPELINE_STAGE_SOURCE_COLUMNS,
)


def _session(row: DatabaseRow) -> dict[str, object]:
    return {
        "session_id": row["id"],
        "group_id": row["id"],
        "env": _ENVIRONMENT,
        "status": "running",
        "session_kind": "chat",
        "session_title": row["name"],
        "group_version": 1,
        "caller_id": row["created_by"],
        "caller_principal": row["created_by"],
        "created_by": row["created_by"],
        "participants": canonical_json([]),
        "activation_count": 1,
        "current_msg_seq": row["message_count"],
        "gmt_create": row["created_at"],
        "gmt_modified": _updated_at(row),
    }


def _session_participant(row: DatabaseRow, *, actor_column: str) -> dict[str, object]:
    return {
        "session_id": row["workspace_id"],
        "group_id": row["workspace_id"],
        "bot_uuid": row[actor_column],
        "role": row.get("role") or "worker",
        "env": _ENVIRONMENT,
        "collected": False,
        "collected_at": None,
        "gmt_create": row["created_at"],
        "gmt_modified": _updated_at(row),
    }


def _human_session_participant(row: DatabaseRow) -> dict[str, object]:
    return _session_participant(row, actor_column="user_id")


def _bot_session_participant(row: DatabaseRow) -> dict[str, object]:
    return _session_participant(row, actor_column="id")


def _message(row: DatabaseRow) -> dict[str, object]:
    mentions = _json(row, "mentions_json", [])
    metadata = _json(row, "metadata_json", {})
    source = {key: row[key] for key in MESSAGE_SOURCE_COLUMNS}
    source.update({"mentions_json": mentions, "metadata_json": metadata})
    sender_type = str(row["sender_type"])
    return {
        "message_id": row["id"],
        "group_id": row["workspace_id"],
        "session_id": row["workspace_id"],
        "session_seq": row["_sequence"],
        "env": _ENVIRONMENT,
        "sender_id": row["sender_id"],
        "sender_type": sender_type,
        "message_type": "text",
        "content": row["content"],
        "client_msg_id": row["id"],
        "status": "normal",
        "created_at": _epoch_millis(row["created_at"]),
        "gmt_create": row["created_at"],
        "gmt_modified": row["created_at"],
        "run_id": "",
        "owner_bot_id": row["sender_id"] if sender_type == "agent" else None,
        "workspace_id": row["workspace_id"],
        "mentions_json": mentions,
        "parent_message_id": row.get("parent_message_id"),
        "metadata_json": metadata,
        "source_hash": canonical_hash(source),
    }


def _message_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "message_id",
            "workspace_id": "workspace_id",
            "sender_id": "sender_id",
            "sender_type": "sender_type",
            "content": "content",
            "mentions_json": "mentions_json",
            "parent_message_id": "parent_message_id",
            "metadata_json": "metadata_json",
            "created_at": "gmt_create",
        },
    )


def _authority(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "workspace_id": row["workspace_id"],
        "revision": row["revision"],
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _authority_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(row, {column: column for column in AUTHORITY_SOURCE_COLUMNS})


def _mutation_receipt(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "receipt_id": row["id"],
        "actor_id": row["actor_user_id"],
        "contract_version": row["contract_version"],
        "surface": row["surface"],
        "action": row["action"],
        "idempotency_key": row["idempotency_key"],
        "request_hash": row["request_hash"],
        "expected_revision": row["expected_revision"],
        "committed_revision": row.get("committed_revision"),
        "response_json": None,
        "created_at": row["created_at"],
        "committed_at": row.get("committed_at"),
    }


def _mutation_receipt_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "receipt_id",
            "tenant_id": "tenant_id",
            "project_id": "project_id",
            "workspace_id": "workspace_id",
            "actor_user_id": "actor_id",
            "contract_version": "contract_version",
            "surface": "surface",
            "action": "action",
            "idempotency_key": "idempotency_key",
            "request_hash": "request_hash",
            "expected_revision": "expected_revision",
            "committed_revision": "committed_revision",
            "created_at": "created_at",
            "committed_at": "committed_at",
        },
    )


def _collaboration_definition(row: DatabaseRow) -> dict[str, object]:
    normalized = {
        "plan_id": row["id"],
        "workspace_id": row["workspace_id"],
        "goal_id": row["goal_id"],
        "status": row["status"],
        "nodes": _json(row, "_nodes_json", []),
    }
    return {
        "env": _ENVIRONMENT,
        "definition_id": row["id"],
        "version": 1,
        "name": f"Workspace plan {row['id']}",
        "description": row.get("goal_title") or str(row["goal_id"]),
        "source_format": "json",
        "content_hash": canonical_hash(normalized),
        "blob_id": None,
        "yaml_text": None,
        "normalized_json": normalized,
        "metadata_json": {"legacy_goal_id": row["goal_id"]},
        "record_status": "active",
        "created_by": row.get("goal_created_by") or row["workspace_created_by"],
        "gmt_create": row["created_at"],
        "gmt_modified": _updated_at(row),
    }


def _plan(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "plan_id": row["id"],
        "source_task_id": row.get("existing_goal_task_id"),
        "collaboration_definition_id": row["id"],
        "collaboration_definition_version": 1,
        "state_machine_run_id": None,
        "goal": row.get("goal_title") or str(row["goal_id"]),
        "goal_json": {"goal_id": row["goal_id"]},
        "status": row["status"],
        "revision": 0,
        "created_by_actor_id": row.get("goal_created_by") or row["workspace_created_by"],
        "metadata_json": {},
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
        "completed_at": _updated_at(row) if row["status"] == "completed" else None,
    }


def _plan_reverse(row: DatabaseRow) -> dict[str, object]:
    goal_json = decode_json(row.get("goal_json"), default={})
    goal_id = (
        cast(Mapping[object, object], goal_json).get("goal_id")
        if isinstance(goal_json, Mapping)
        else None
    )
    return {
        "id": row["plan_id"],
        "workspace_id": row["workspace_id"],
        "goal_id": goal_id or row.get("source_task_id"),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _plan_node(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "node_id": row["id"],
        "plan_id": row["plan_id"],
        "workspace_task_id": row.get("workspace_task_id"),
        "parent_id": row.get("parent_id"),
        "kind": row["kind"],
        "title": row["title"],
        "description": row["description"],
        "intent": row["intent"],
        "status": row["execution"],
        "sequence_number": row["_sequence"],
        "dependencies_json": _json(row, "depends_on", []),
        "inputs_schema_json": _json(row, "inputs_schema", {}),
        "outputs_schema_json": _json(row, "outputs_schema", {}),
        "acceptance_criteria_json": _json(row, "acceptance_criteria", []),
        "feature_checkpoint_json": _json(row, "feature_checkpoint", None),
        "handoff_package_json": _json(row, "handoff_package", None),
        "recommended_capabilities_json": _json(row, "recommended_capabilities", []),
        "preferred_agent_id": row.get("preferred_agent_id"),
        "estimated_effort_json": _json(row, "estimated_effort", {}),
        "priority": row["priority"],
        "progress_json": _json(row, "progress", {}),
        "assignee_agent_id": row.get("assignee_agent_id"),
        "current_attempt_id": row.get("current_attempt_id"),
        "max_attempts": 1,
        "timeout_deadline_at": None,
        "metadata_json": _json(row, "metadata_json", {}),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
        "completed_at": row.get("completed_at"),
    }


def _plan_node_reverse(row: DatabaseRow) -> dict[str, object]:
    return {
        "id": row["node_id"],
        "plan_id": row["plan_id"],
        "parent_id": row.get("parent_id"),
        "kind": row["kind"],
        "title": row["title"],
        "description": row["description"],
        "depends_on": row["dependencies_json"],
        "inputs_schema": row["inputs_schema_json"],
        "outputs_schema": row["outputs_schema_json"],
        "acceptance_criteria": row["acceptance_criteria_json"],
        "feature_checkpoint": row.get("feature_checkpoint_json"),
        "handoff_package": row.get("handoff_package_json"),
        "recommended_capabilities": row["recommended_capabilities_json"],
        "preferred_agent_id": row.get("preferred_agent_id"),
        "estimated_effort": row["estimated_effort_json"],
        "priority": row["priority"],
        "intent": row["intent"],
        "execution": row["status"],
        "progress": row["progress_json"],
        "assignee_agent_id": row.get("assignee_agent_id"),
        "current_attempt_id": row.get("current_attempt_id"),
        "workspace_task_id": row.get("workspace_task_id"),
        "metadata_json": row["metadata_json"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row.get("completed_at"),
    }


def _plan_blackboard(row: DatabaseRow) -> dict[str, object]:
    value = _json(row, "value_json", None)
    return {
        **_scope(row),
        "entry_id": row["id"],
        "plan_id": row["plan_id"],
        "key": row["key"],
        "version": row["version"],
        "value_json": value,
        "content_hash": canonical_hash(value),
        "created_by_actor_id": row["published_by"],
        "schema_ref": row.get("schema_ref"),
        "metadata_json": _json(row, "metadata_json", {}),
        "created_at": row["created_at"],
    }


def _plan_blackboard_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "entry_id",
            "plan_id": "plan_id",
            "key": "key",
            "value_json": "value_json",
            "published_by": "created_by_actor_id",
            "version": "version",
            "schema_ref": "schema_ref",
            "metadata_json": "metadata_json",
            "created_at": "created_at",
        },
    )


def _plan_event(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "event_id": row["id"],
        "plan_id": row["plan_id"],
        "event_sequence": row["_sequence"],
        "node_id": row.get("node_id"),
        "attempt_id": row.get("attempt_id"),
        "event_type": row["event_type"],
        "source": row["source"],
        "actor_id": row.get("actor_id"),
        "payload_json": _json(row, "payload_json", {}),
        "created_at": row["created_at"],
    }


def _plan_event_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "event_id",
            "plan_id": "plan_id",
            "workspace_id": "workspace_id",
            "node_id": "node_id",
            "attempt_id": "attempt_id",
            "event_type": "event_type",
            "source": "source",
            "actor_id": "actor_id",
            "payload_json": "payload_json",
            "created_at": "created_at",
        },
    )


def _outbox(row: DatabaseRow) -> dict[str, object]:
    is_plan = row["_source_kind"] == "plan"
    aggregate_id = row.get("plan_id") or row["workspace_id"]
    legacy_status = str(row["status"])
    attempt_count = row["attempt_count"]
    max_attempts = row["max_attempts"]
    if not isinstance(attempt_count, int) or not isinstance(max_attempts, int):
        raise TypeError("outbox attempt counters must be integers")
    if legacy_status == "processed":
        status = "dispatched"
    elif legacy_status == "processing":
        status = "retry"
    elif legacy_status == "failed":
        status = "dead_letter" if attempt_count >= max_attempts else "retry"
    else:
        status = legacy_status
    return {
        **_scope(row),
        "outbox_id": row["id"],
        "aggregate_type": "plan" if is_plan else "blackboard",
        "aggregate_id": aggregate_id,
        "event_type": row["event_type"],
        "stream_name": f"workspace:{row['workspace_id']}",
        "event_sequence": row["_sequence"],
        "payload_json": _json(row, "payload_json", {}),
        "metadata_json": _json(row, "metadata_json", {}),
        "correlation_id": row.get("correlation_id"),
        "idempotency_key": f"legacy:{row['_source_kind']}:{row['id']}",
        "status": status,
        "legacy_status": legacy_status,
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
        "lease_owner": row.get("lease_owner"),
        "lease_expires_at": row.get("lease_expires_at"),
        "last_error": row.get("last_error"),
        "next_attempt_at": row.get("next_attempt_at"),
        "dispatched_at": row.get("dispatched_at") or row.get("processed_at"),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _outbox_reverse(row: DatabaseRow) -> dict[str, object]:
    is_plan = row["aggregate_type"] == "plan"
    result = {
        "_source_table": "workspace_plan_outbox" if is_plan else "workspace_blackboard_outbox",
        "id": row["outbox_id"],
        "workspace_id": row["workspace_id"],
        "event_type": row["event_type"],
        "payload_json": row["payload_json"],
        "status": row.get("legacy_status") or row["status"],
        "attempt_count": row["attempt_count"],
        "max_attempts": row["max_attempts"],
        "lease_owner": row.get("lease_owner"),
        "lease_expires_at": row.get("lease_expires_at"),
        "last_error": row.get("last_error"),
        "next_attempt_at": row.get("next_attempt_at"),
        "metadata_json": row["metadata_json"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if is_plan:
        result.update({"plan_id": row["aggregate_id"], "processed_at": row.get("dispatched_at")})
    else:
        result.update(
            {
                "tenant_id": row["tenant_id"],
                "project_id": row["project_id"],
                "correlation_id": row.get("correlation_id"),
                "dispatched_at": row.get("dispatched_at"),
            }
        )
    return result


def _pipeline_contract(row: DatabaseRow) -> dict[str, object]:
    values = {**_scope(row), "contract_id": row["id"]}
    for column in PIPELINE_CONTRACT_SOURCE_COLUMNS:
        if column not in {"id", "workspace_id"}:
            values[column] = (
                _json(row, column, [] if column == "commands_json" else {})
                if column in PIPELINE_CONTRACT_JSON_COLUMNS
                else row.get(column)
            )
    values["updated_at"] = _updated_at(row)
    return values


def _pipeline_contract_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in PIPELINE_CONTRACT_SOURCE_COLUMNS if column != "id"}
    mapping["id"] = "contract_id"
    return _copy(row, mapping)


def _pipeline_run(row: DatabaseRow) -> dict[str, object]:
    values = {**_scope(row), "run_id": row["id"]}
    for column in PIPELINE_RUN_SOURCE_COLUMNS:
        if column not in {"id", "workspace_id"}:
            values[column] = (
                _json(row, column, {}) if column == "metadata_json" else row.get(column)
            )
    values["updated_at"] = _updated_at(row)
    return values


def _pipeline_run_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in PIPELINE_RUN_SOURCE_COLUMNS if column != "id"}
    mapping["id"] = "run_id"
    return _copy(row, mapping)


def _pipeline_stage(row: DatabaseRow) -> dict[str, object]:
    values = {**_scope(row), "stage_run_id": row["id"]}
    for column in PIPELINE_STAGE_SOURCE_COLUMNS:
        if column not in {"id", "workspace_id"}:
            default: object = [] if column == "artifact_refs_json" else {}
            values[column] = (
                _json(row, column, default)
                if column in {"artifact_refs_json", "metadata_json"}
                else row.get(column)
            )
    values["updated_at"] = _updated_at(row)
    return values


def _pipeline_stage_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in PIPELINE_STAGE_SOURCE_COLUMNS if column != "id"}
    mapping["id"] = "stage_run_id"
    return _copy(row, mapping)


def _deployment(row: DatabaseRow) -> dict[str, object]:
    values = {**_scope(row), "deployment_id": row["id"]}
    for column in DEPLOYMENT_SOURCE_COLUMNS:
        if column in {"id", "workspace_id", "pid", "ws_preview_url"}:
            continue
        values[column] = _json(row, column, {}) if column == "metadata_json" else row.get(column)
    values["process_id"] = row.get("pid")
    values["websocket_preview_url"] = row.get("ws_preview_url")
    values["updated_at"] = _updated_at(row)
    return values


def _deployment_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in DEPLOYMENT_SOURCE_COLUMNS if column != "id"}
    mapping.update(
        {"id": "deployment_id", "pid": "process_id", "ws_preview_url": "websocket_preview_url"}
    )
    return _copy(row, mapping)
