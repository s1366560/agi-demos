"""Graph sync transactions preserve revisions, receipts and conflict versions."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    GraphSyncContent,
    GraphSyncEntity,
    GraphSyncMutation,
    GraphSyncRelationship,
    GraphSyncResolution,
    KnowledgeSyncError,
    KnowledgeSyncScope,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeGraphSyncObjectModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Project, User
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_graph_sync_repository import (
    SqlKnowledgeGraphSyncRepository,
)


def content(title: str = "Alice") -> GraphSyncContent:
    return GraphSyncContent(
        source_revision=1,
        change_sequence=7,
        audit_attempt=1,
        entities=(
            GraphSyncEntity(name=title, kind="person"),
            GraphSyncEntity(name="Acme", kind="organization"),
        ),
        relationships=(
            GraphSyncRelationship(
                source_index=0,
                target_index=1,
                relation_type="works_at",
                fact=f"{title} works at Acme",
                score=0.9,
            ),
        ),
    )


def mutation(
    operation: str = "create", revision: int = 0, name: str = "Alice"
) -> GraphSyncMutation:
    return GraphSyncMutation(
        operation=operation,
        object_id="sync-memory-1",
        expected_revision=revision,
        content=None if operation == "delete" else content(name),
    )


@pytest.fixture
async def sync_scope(
    db: AsyncSession, test_project_db: Project, test_user: User
) -> KnowledgeSyncScope:
    return await SqlKnowledgeGraphSyncRepository(db).resolve_scope(test_user.id, test_project_db.id)


def object_key(scope: KnowledgeSyncScope, object_id: str) -> tuple[str, str, str]:
    return (scope.tenant_id, scope.project_id, object_id)


async def test_create_update_and_replay_original_receipt_after_subsequent_edits(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeGraphSyncRepository(db)
    key = str(uuid4())
    created = await repo.mutate_graph(sync_scope, key, mutation())
    await db.commit()
    updated = await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Bob"))
    await db.commit()
    replay = await repo.mutate_graph(sync_scope, key, mutation())
    assert replay.replayed
    assert replay.receipt_json == created.receipt_json
    assert updated.to_dict()["receipt"]["version"]["revision"] == 2
    stored = await db.get(KnowledgeGraphSyncObjectModel, object_key(sync_scope, "sync-memory-1"))
    assert stored is not None and stored.revision == 2


async def test_cas_conflict_persists_both_versions_and_requires_fresh_resolution(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeGraphSyncRepository(db)
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Bob"))
    conflict = await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Carol"))
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    stored = await repo.graph_conflict(sync_scope, conflict_id)
    assert stored["current"]["revision"] == 2
    assert stored["proposed"]["content"]["entities"][0]["name"] == "Carol"
    stale = GraphSyncResolution(
        conflict_id=conflict_id, expected_current_revision=1, decision="keep_current"
    )
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_resolution_stale"):
        await repo.resolve_graph(sync_scope, str(uuid4()), stale)
    resolved = await repo.resolve_graph(
        sync_scope,
        str(uuid4()),
        GraphSyncResolution(
            conflict_id=conflict_id, expected_current_revision=2, decision="keep_current"
        ),
    )
    assert resolved.to_dict()["receipt"]["status"] == "resolved"
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_conflict_resolved"):
        await repo.resolve_graph(
            sync_scope,
            str(uuid4()),
            GraphSyncResolution(
                conflict_id=conflict_id, expected_current_revision=2, decision="keep_current"
            ),
        )


async def test_delete_vs_modify_conflicts_and_use_proposed_delete_tombstones(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeGraphSyncRepository(db)
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Bob"))
    conflict = await repo.mutate_graph(sync_scope, str(uuid4()), mutation("delete", 1))
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    resolved = await repo.resolve_graph(
        sync_scope,
        str(uuid4()),
        GraphSyncResolution(
            conflict_id=conflict_id, expected_current_revision=2, decision="use_proposed"
        ),
    )
    version = resolved.to_dict()["receipt"]["version"]
    assert version["deleted"] and version["revision"] == 3
    assert (
        await db.get(KnowledgeGraphSyncObjectModel, object_key(sync_scope, "sync-memory-1"))
    ) is None
    # keep_both on a delete proposal fails closed without touching either version.
    await repo.mutate_graph(
        sync_scope,
        str(uuid4()),
        GraphSyncMutation(
            operation="create", object_id="sync-memory-4", expected_revision=0, content=content()
        ),
    )
    await repo.mutate_graph(
        sync_scope,
        str(uuid4()),
        GraphSyncMutation(
            operation="update", object_id="sync-memory-4", expected_revision=1, content=content()
        ),
    )
    delete_conflict = await repo.mutate_graph(
        sync_scope,
        str(uuid4()),
        GraphSyncMutation(operation="delete", object_id="sync-memory-4", expected_revision=1),
    )
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
        await repo.resolve_graph(
            sync_scope,
            str(uuid4()),
            GraphSyncResolution(
                conflict_id=delete_conflict.to_dict()["receipt"]["conflict_id"],
                expected_current_revision=2,
                decision="keep_both",
            ),
        )


async def test_pending_conflict_blocks_new_mutation_and_others_continue(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeGraphSyncRepository(db)
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1))
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Offline"))
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_conflict_pending"):
        await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 2))
    other = GraphSyncMutation(
        operation="create",
        object_id="sync-memory-2",
        expected_revision=0,
        content=content(),
    )
    applied = await repo.mutate_graph(sync_scope, str(uuid4()), other)
    assert applied.to_dict()["receipt"]["status"] == "applied"
    page = await repo.graph_changes(sync_scope, 0, 100)
    assert page.next_cursor == 3


async def test_keep_both_preserves_both_versions_with_deterministic_copy(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeGraphSyncRepository(db)
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Bob"))
    conflict = await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Carol"))
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    resolved = await repo.resolve_graph(
        sync_scope,
        str(uuid4()),
        GraphSyncResolution(
            conflict_id=conflict_id, expected_current_revision=2, decision="keep_both"
        ),
    )
    receipt = resolved.to_dict()["receipt"]
    assert receipt["status"] == "resolved"
    copy_id = receipt["copy_object_id"]
    assert copy_id != "sync-memory-1"
    original = await repo.graph_changes(sync_scope, 0, 100)
    versions = [change["version"] for change in original.to_dict()["changes"]]
    assert versions[-1]["object_id"] == copy_id
    assert versions[-1]["content"]["entities"][0]["name"] == "Carol"
    current = await db.get(KnowledgeGraphSyncObjectModel, object_key(sync_scope, "sync-memory-1"))
    assert current is not None and current.revision == 2
    # The copy id is reserved deterministically by the conflict.
    from uuid import UUID, uuid5

    assert copy_id == str(uuid5(UUID(conflict_id), "keep-both-copy"))


async def test_merged_resolution_rechecks_revision_and_applies_content(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeGraphSyncRepository(db)
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Bob"))
    conflict = await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1, "Carol"))
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    merged = content("Dave")
    resolved = await repo.resolve_graph(
        sync_scope,
        str(uuid4()),
        GraphSyncResolution(
            conflict_id=conflict_id,
            expected_current_revision=2,
            decision="merged",
            content=merged,
        ),
    )
    version = resolved.to_dict()["receipt"]["version"]
    assert version["revision"] == 3
    assert version["content"]["entities"][0]["name"] == "Dave"


async def test_viewer_cannot_write_but_can_observe(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    from src.infrastructure.adapters.secondary.persistence.models import UserProject

    repo = SqlKnowledgeGraphSyncRepository(db)
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await db.commit()
    _ = await db.execute(
        update(UserProject).where(UserProject.user_id == sync_scope.actor_id).values(role="viewer")
    )
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_forbidden"):
        await repo.mutate_graph(sync_scope, str(uuid4()), mutation("update", 1))
    page = await repo.graph_changes(sync_scope, 0, 100)
    assert page.next_cursor == 1


async def test_member_cannot_replace_another_actors_projection(
    db: AsyncSession, test_project_db: Project, test_user: User
) -> None:
    from src.infrastructure.adapters.secondary.persistence.models import (
        User as UserModel,
        UserProject,
        UserTenant,
    )

    repo = SqlKnowledgeGraphSyncRepository(db)
    owner_scope = await repo.resolve_scope(test_user.id, test_project_db.id)
    await repo.mutate_graph(owner_scope, str(uuid4()), mutation())
    await db.commit()
    db.add(UserModel(id="member-2", email="member2@example.test", hashed_password="unused"))
    await db.flush()
    db.add(
        UserTenant(
            id="ut-2", tenant_id=test_project_db.tenant_id, user_id="member-2", role="member"
        )
    )
    db.add(UserProject(id="up-2", project_id=test_project_db.id, user_id="member-2", role="member"))
    await db.flush()
    member_scope = await repo.resolve_scope("member-2", test_project_db.id)
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_forbidden"):
        await repo.mutate_graph(member_scope, str(uuid4()), mutation("update", 1, "Mallory"))
    # A member still originates their own projection records.
    own = GraphSyncMutation(
        operation="create",
        object_id="sync-memory-9",
        expected_revision=0,
        content=content(),
    )
    applied = await repo.mutate_graph(member_scope, str(uuid4()), own)
    assert applied.to_dict()["receipt"]["status"] == "applied"


async def test_scope_and_cursor_fail_closed(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeGraphSyncRepository(db)
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_cursor_invalid"):
        await repo.graph_changes(sync_scope, 2, 100)
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_forbidden"):
        await repo.graph_changes(
            KnowledgeSyncScope(
                tenant_id="other", project_id=sync_scope.project_id, actor_id=sync_scope.actor_id
            ),
            0,
            100,
        )
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_conflict_not_found"):
        await repo.graph_conflict(sync_scope, str(uuid4()))


async def test_dangling_record_reports_source_availability_until_memory_lifecycle(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
        SqlKnowledgeSyncRepository,
    )

    repo = SqlKnowledgeGraphSyncRepository(db)
    # The derived record arrives before its source memory: durable, unavailable.
    await repo.mutate_graph(sync_scope, str(uuid4()), mutation())
    await db.commit()
    read = await repo.graph_object(sync_scope, "sync-memory-1")
    assert read["source_available"] is False
    assert read["source_current"] is False
    # Memory sync delivers the source at the provenance revision.
    memory_repo = SqlKnowledgeSyncRepository(db)
    from src.domain.model.knowledge_sync.contracts import MemorySyncContent, MemorySyncMutation

    await memory_repo.mutate(
        sync_scope,
        str(uuid4()),
        MemorySyncMutation(
            operation="create",
            memory_id="sync-memory-1",
            expected_revision=0,
            content=MemorySyncContent(title="Source", content="Body"),
        ),
    )
    await db.commit()
    read = await repo.graph_object(sync_scope, "sync-memory-1")
    assert read["source_available"] is True
    assert read["source_current"] is True
    # A later source edit makes the provenance revision stale, deterministically.
    await memory_repo.mutate(
        sync_scope,
        str(uuid4()),
        MemorySyncMutation(
            operation="update",
            memory_id="sync-memory-1",
            expected_revision=1,
            content=MemorySyncContent(title="Edited", content="Body"),
        ),
    )
    await db.commit()
    read = await repo.graph_object(sync_scope, "sync-memory-1")
    assert read["source_available"] is True
    assert read["source_current"] is False
    # Source deletion keeps the record durable but unavailable.
    await memory_repo.mutate(
        sync_scope,
        str(uuid4()),
        MemorySyncMutation(operation="delete", memory_id="sync-memory-1", expected_revision=2),
    )
    await db.commit()
    read = await repo.graph_object(sync_scope, "sync-memory-1")
    assert read["source_available"] is False
    assert read["source_current"] is False
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_object_not_found"):
        await repo.graph_object(sync_scope, "never-arrived")
