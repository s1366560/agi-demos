"""Field-parity contracts for the Avernet Workspace migration manifest."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.infrastructure.workspace_core.migration.contracts import SOURCE_COLUMN_CONTRACTS
from src.infrastructure.workspace_core.migration.specs import MIGRATION_SPECS

pytestmark = pytest.mark.unit


def test_every_authoritative_source_table_has_a_frozen_column_contract() -> None:
    mapped_sources = {
        source
        for spec in MIGRATION_SPECS
        for source in spec.source_table.split("+")
        if source not in {"workspaces", "workspace_members", "workspace_agents", "workspace_plans"}
    }

    assert mapped_sources <= SOURCE_COLUMN_CONTRACTS.keys()
    assert {
        "workspaces",
        "workspace_members",
        "workspace_agents",
        "workspace_plans",
        "workspace_messages",
        "workspace_plan_outbox",
        "workspace_blackboard_outbox",
        "user_projects",
    } <= SOURCE_COLUMN_CONTRACTS.keys()


def test_target_mapping_shapes_are_unique_and_explicit() -> None:
    entity_types = [spec.entity_type for spec in MIGRATION_SPECS]

    assert len(entity_types) == len(set(entity_types))
    for spec in MIGRATION_SPECS:
        assert spec.target_columns
        assert set(spec.key_columns) <= set(spec.target_columns)
        assert spec.json_columns <= set(spec.target_columns)


def test_profile_and_message_source_hashes_normalize_json_representation() -> None:
    timestamp = datetime(2026, 8, 11, tzinfo=UTC)
    profile = next(item for item in MIGRATION_SPECS if item.entity_type == "workspace_profile")
    profile_row = {
        "id": "workspace-1",
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "name": "Workspace",
        "description": None,
        "created_by": "user-1",
        "is_archived": False,
        "metadata_json": '{"b": 2, "a": 1}',
        "office_status": "active",
        "hex_layout_config_json": '{"radius": 3}',
        "default_blocking_categories_json": '["security"]',
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    profile_object_row = {
        **profile_row,
        "metadata_json": {"a": 1, "b": 2},
        "hex_layout_config_json": {"radius": 3},
        "default_blocking_categories_json": ["security"],
    }

    profile_text = profile.mapper(profile_row)
    profile_object = profile.mapper(profile_object_row)

    assert profile_text == profile_object

    message = next(item for item in MIGRATION_SPECS if item.entity_type == "workspace_message")
    message_row = {
        "id": "message-1",
        "workspace_id": "workspace-1",
        "sender_id": "agent-1",
        "sender_type": "agent",
        "content": "done",
        "mentions_json": '["user-1"]',
        "parent_message_id": None,
        "metadata_json": '{"b": 2, "a": 1}',
        "created_at": timestamp,
        "_sequence": 1,
    }
    message_object_row = {
        **message_row,
        "mentions_json": ["user-1"],
        "metadata_json": {"a": 1, "b": 2},
    }

    assert message.mapper(message_row) == message.mapper(message_object_row)


def test_every_legacy_authority_has_a_reverse_projection() -> None:
    non_authoritative_mirrors = {
        "organization_mirror",
        "workspace_group",
        "human_identity_mirror",
        "workspace_principal_identity",
        "human_group_participant",
        "organization_member",
        "human_session_participant",
        "workspace_bot",
        "bot_group_participant",
        "bot_session_participant",
        "workspace_session",
        "collaboration_definition",
        "project_principal_membership",
    }

    for spec in MIGRATION_SPECS:
        if spec.entity_type not in non_authoritative_mirrors:
            assert spec.reverse_mapper is not None, spec.entity_type


def test_project_membership_projection_is_project_scoped_and_lossless() -> None:
    spec = next(
        item for item in MIGRATION_SPECS if item.entity_type == "project_principal_membership"
    )

    mapped = spec.mapper(
        {
            "id": "membership-1",
            "user_id": "user-1",
            "project_id": "project-1",
            "role": "member",
            "permissions": {"workspace:create": True},
            "created_at": "2026-08-10T00:00:00Z",
            "_tenant_id": "tenant-1",
            "_project_id": "project-1",
            "_workspace_id": None,
        }
    )

    assert spec.target_table == "project_principal_memberships"
    assert spec.project_scoped
    assert spec.reverse_mapper is None
    assert mapped == {
        "tenant_id": "tenant-1",
        "project_id": "project-1",
        "user_id": "user-1",
        "participant_actor_id": "user-1",
        "source_membership_id": "membership-1",
        "role": "member",
        "permissions_json": {"workspace:create": True},
        "is_active": True,
        "identity_authority": "memstack",
        "source_created_at": "2026-08-10T00:00:00Z",
        "source_updated_at": "2026-08-10T00:00:00Z",
    }
