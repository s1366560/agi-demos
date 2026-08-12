"""Task, blackboard, topology, objective, and Gene migration mappings."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false

from __future__ import annotations

from .mapping_actors import _copy, _json, _scope, _updated_at
from .model import DatabaseRow, canonical_hash, decode_json
from .source_columns import (
    ATTEMPT_SOURCE_COLUMNS,
    TASK_SOURCE_COLUMNS,
    TOPOLOGY_EDGE_SOURCE_COLUMNS,
    TOPOLOGY_NODE_SOURCE_COLUMNS,
)


def _task(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "task_id": row["id"],
        "title": row["title"],
        "description": row.get("description"),
        "created_by": row["created_by"],
        "assignee_user_id": row.get("assignee_user_id"),
        "assignee_agent_id": row.get("assignee_agent_id"),
        "status": row["status"],
        "priority": row["priority"],
        "estimated_effort": row.get("estimated_effort"),
        "blocker_reason": row.get("blocker_reason"),
        "metadata_json": _json(row, "metadata_json", {}),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
        "completed_at": row.get("completed_at"),
        "archived_at": row.get("archived_at"),
    }


def _task_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in TASK_SOURCE_COLUMNS if column != "id"}
    mapping["id"] = "task_id"
    return _copy(row, mapping)


def _attempt(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "attempt_id": row["id"],
        "task_id": row["workspace_task_id"],
        "root_goal_task_id": row["root_goal_task_id"],
        "attempt_number": row["attempt_number"],
        "status": row["status"],
        "conversation_id": row.get("conversation_id"),
        "worker_agent_id": row.get("worker_agent_id"),
        "leader_agent_id": row.get("leader_agent_id"),
        "candidate_summary": row.get("candidate_summary"),
        "candidate_artifacts_json": _json(row, "candidate_artifacts_json", []),
        "candidate_verifications_json": _json(row, "candidate_verifications_json", []),
        "leader_feedback": row.get("leader_feedback"),
        "adjudication_reason": row.get("adjudication_reason"),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
        "completed_at": row.get("completed_at"),
    }


def _attempt_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in ATTEMPT_SOURCE_COLUMNS if column != "id"}
    mapping.update({"id": "attempt_id", "workspace_task_id": "task_id"})
    return _copy(row, mapping)


def _post(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "post_id": row["id"],
        "author_actor_id": row["author_id"],
        "title": row["title"],
        "content": row["content"],
        "status": row["status"],
        "is_pinned": row["is_pinned"],
        "metadata_json": _json(row, "metadata_json", {}),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _post_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "post_id",
            "workspace_id": "workspace_id",
            "author_id": "author_actor_id",
            "title": "title",
            "content": "content",
            "status": "status",
            "is_pinned": "is_pinned",
            "metadata_json": "metadata_json",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )


def _reply(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "reply_id": row["id"],
        "post_id": row["post_id"],
        "author_actor_id": row["author_id"],
        "content": row["content"],
        "metadata_json": _json(row, "metadata_json", {}),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _reply_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "reply_id",
            "post_id": "post_id",
            "workspace_id": "workspace_id",
            "author_id": "author_actor_id",
            "content": "content",
            "metadata_json": "metadata_json",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )


def _file(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "file_id": row["id"],
        "parent_path": row["parent_path"],
        "name": row["name"],
        "is_directory": row["is_directory"],
        "file_size": row["file_size"],
        "content_type": row["content_type"],
        "storage_backend": "legacy",
        "object_handle": row["storage_key"],
        "uploader_type": row["uploader_type"],
        "uploader_id": row["uploader_id"],
        "uploader_actor_id": row["uploader_id"],
        "uploader_name": row["uploader_name"],
        "checksum_sha256": row.get("checksum_sha256"),
        "detected_mime_type": row.get("mime_type_detected"),
        "created_at": row["created_at"],
    }


def _file_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "file_id",
            "workspace_id": "workspace_id",
            "parent_path": "parent_path",
            "name": "name",
            "is_directory": "is_directory",
            "file_size": "file_size",
            "content_type": "content_type",
            "storage_key": "object_handle",
            "uploader_type": "uploader_type",
            "uploader_id": "uploader_id",
            "uploader_name": "uploader_name",
            "checksum_sha256": "checksum_sha256",
            "mime_type_detected": "detected_mime_type",
            "created_at": "created_at",
        },
    )


def _topology_node(row: DatabaseRow) -> dict[str, object]:
    values = {**_scope(row), "node_id": row["id"]}
    for column in TOPOLOGY_NODE_SOURCE_COLUMNS:
        if column not in {"id", "workspace_id"}:
            values[column] = (
                _json(row, column, [] if column == "tags_json" else {})
                if column in {"tags_json", "data_json"}
                else row.get(column)
            )
    values["updated_at"] = _updated_at(row)
    return values


def _topology_node_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in TOPOLOGY_NODE_SOURCE_COLUMNS if column != "id"}
    mapping["id"] = "node_id"
    return _copy(row, mapping)


def _topology_edge(row: DatabaseRow) -> dict[str, object]:
    return {
        **_scope(row),
        "edge_id": row["id"],
        "source_node_id": row["source_node_id"],
        "target_node_id": row["target_node_id"],
        "edge_type": "dependency",
        "label": row.get("label"),
        "source_hex_q": row.get("source_hex_q"),
        "source_hex_r": row.get("source_hex_r"),
        "target_hex_q": row.get("target_hex_q"),
        "target_hex_r": row.get("target_hex_r"),
        "direction": row["direction"],
        "auto_created": row["auto_created"],
        "data_json": _json(row, "data_json", {}),
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _topology_edge_reverse(row: DatabaseRow) -> dict[str, object]:
    mapping = {column: column for column in TOPOLOGY_EDGE_SOURCE_COLUMNS if column != "id"}
    mapping["id"] = "edge_id"
    return _copy(row, mapping)


def _objective(row: DatabaseRow) -> dict[str, object]:
    raw_progress = row["progress"]
    if not isinstance(raw_progress, (int, float)):
        raise TypeError("objective progress must be numeric")
    progress = float(raw_progress)
    completed = progress >= 1.0
    return {
        **_scope(row),
        "objective_id": row["id"],
        "title": row["title"],
        "description": row.get("description"),
        "objective_type": row["obj_type"],
        "parent_objective_id": row.get("parent_id"),
        "status": "completed" if completed else "active",
        "priority": 0,
        "owner_actor_id": row["created_by"],
        "created_by_actor_id": row["created_by"],
        "progress": progress,
        "success_criteria_json": [],
        "progress_json": {"value": progress},
        "metadata_json": {},
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
        "completed_at": _updated_at(row) if completed else None,
    }


def _objective_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "objective_id",
            "workspace_id": "workspace_id",
            "title": "title",
            "description": "description",
            "obj_type": "objective_type",
            "parent_id": "parent_objective_id",
            "progress": "progress",
            "created_by": "created_by_actor_id",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )


def _gene(row: DatabaseRow) -> dict[str, object]:
    content = decode_json(row.get("config_json"), default={})
    return {
        **_scope(row),
        "gene_id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "category": row["category"],
        "status": "active" if row["is_active"] else "inactive",
        "version": 1,
        "source_version": row["version"],
        "is_active": row["is_active"],
        "config_text": row.get("config_json"),
        "content_json": content,
        "content_hash": canonical_hash(content),
        "source_objective_id": None,
        "created_by_actor_id": row["created_by"],
        "metadata_json": {},
        "created_at": row["created_at"],
        "updated_at": _updated_at(row),
    }


def _gene_reverse(row: DatabaseRow) -> dict[str, object]:
    return _copy(
        row,
        {
            "id": "gene_id",
            "workspace_id": "workspace_id",
            "name": "name",
            "category": "category",
            "description": "description",
            "config_json": "config_text",
            "version": "source_version",
            "is_active": "is_active",
            "created_by": "created_by_actor_id",
            "created_at": "created_at",
            "updated_at": "updated_at",
        },
    )
