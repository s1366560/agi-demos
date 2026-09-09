"""Cloud sync transactions must preserve revisions, receipts and conflict versions."""

from __future__ import annotations

from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncError,
    KnowledgeSyncResolution,
    KnowledgeSyncScope,
    MemorySyncContent,
    MemorySyncMutation,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project, User
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)


def mutation(
    operation: str = "create", revision: int = 0, title: str = "Original"
) -> MemorySyncMutation:
    return MemorySyncMutation(
        operation=operation,
        memory_id="sync-memory-1",
        expected_revision=revision,
        content=None
        if operation == "delete"
        else MemorySyncContent(title=title, content="Source content"),
    )


@pytest.fixture
async def sync_scope(
    db: AsyncSession, test_project_db: Project, test_user: User
) -> KnowledgeSyncScope:
    return await SqlKnowledgeSyncRepository(db).resolve_scope(test_user.id, test_project_db.id)


async def test_create_update_and_replay_original_receipt_after_subsequent_edits(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    key = str(uuid4())
    created = await repo.mutate(sync_scope, key, mutation())
    await db.commit()
    updated = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Edited"))
    await db.commit()
    replay = await repo.mutate(sync_scope, key, mutation())
    assert replay.replayed
    assert replay.receipt_json == created.receipt_json
    assert updated.to_dict()["receipt"]["version"]["revision"] == 2
    memory = await db.get(Memory, "sync-memory-1")
    assert memory is not None and memory.title == "Edited" and memory.version == 2
    with pytest.raises(KnowledgeSyncError, match="idempotency_conflict"):
        await repo.mutate(sync_scope, key, mutation(title="Different request"))
    page = await repo.changes(sync_scope, 0, 1)
    assert page.has_more and page.next_cursor == 1
    next_page = await repo.changes(sync_scope, page.next_cursor, 10)
    assert not next_page.has_more and next_page.next_cursor == 2
    assert len(next_page.to_dict()["changes"]) == 1


async def test_cas_conflict_persists_both_versions_and_requires_explicit_fresh_resolution(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud edit"))
    key = str(uuid4())
    outcome = await repo.mutate(sync_scope, key, mutation("update", 1, "Offline edit"))
    await db.commit()
    receipt = outcome.to_dict()["receipt"]
    assert receipt["status"] == "conflict"
    conflict = await repo.conflict(sync_scope, receipt["conflict_id"])
    assert conflict["current"]["content"]["title"] == "Cloud edit"
    assert conflict["proposed"]["content"]["title"] == "Offline edit"
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 2
    with pytest.raises(KnowledgeSyncError, match="resolution_stale"):
        await repo.resolve(
            sync_scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=receipt["conflict_id"],
                expected_current_revision=1,
                decision="use_proposed",
            ),
        )
    resolved = await repo.resolve(
        sync_scope,
        str(uuid4()),
        KnowledgeSyncResolution(
            conflict_id=receipt["conflict_id"],
            expected_current_revision=2,
            decision="use_proposed",
        ),
    )
    await db.commit()
    assert resolved.to_dict()["receipt"]["version"]["revision"] == 3
    assert (await db.get(Memory, "sync-memory-1")).title == "Offline edit"
    assert (
        await repo.mutate(sync_scope, key, mutation("update", 1, "Offline edit"))
    ).receipt_json == outcome.receipt_json


async def test_tombstone_reserves_global_id_and_restoration_requires_conflict_resolution(
    db: AsyncSession, sync_scope: KnowledgeSyncScope, test_user: User
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    deleted = await repo.mutate(sync_scope, str(uuid4()), mutation("delete", 1))
    await db.commit()
    assert deleted.to_dict()["receipt"]["version"]["deleted"]
    assert await db.get(Memory, "sync-memory-1") is None
    conflict = await repo.mutate(
        sync_scope, str(uuid4()), mutation("update", 1, "Restore explicitly")
    )
    receipt = conflict.to_dict()["receipt"]
    assert receipt["status"] == "conflict"
    resolved = await repo.resolve(
        sync_scope,
        str(uuid4()),
        KnowledgeSyncResolution(
            conflict_id=receipt["conflict_id"],
            expected_current_revision=2,
            decision="use_proposed",
        ),
    )
    assert resolved.to_dict()["receipt"]["version"]["revision"] == 3
    assert not resolved.to_dict()["receipt"]["version"]["deleted"]


async def test_scope_actor_and_cursor_fail_closed(
    db: AsyncSession, sync_scope: KnowledgeSyncScope, another_user: User
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await db.commit()
    for invalid_scope in (
        KnowledgeSyncScope(
            tenant_id="other-tenant", project_id=sync_scope.project_id, actor_id=sync_scope.actor_id
        ),
        KnowledgeSyncScope(
            tenant_id=sync_scope.tenant_id,
            project_id=sync_scope.project_id,
            actor_id=another_user.id,
        ),
    ):
        with pytest.raises(KnowledgeSyncError):
            await repo.changes(invalid_scope, 0, 100)
        with pytest.raises(KnowledgeSyncError):
            await repo.mutate(invalid_scope, str(uuid4()), mutation("update", 1))
    with pytest.raises(KnowledgeSyncError, match="cursor_invalid"):
        await repo.changes(sync_scope, 999, 100)
    assert len((await db.scalars(select(KnowledgeSyncChangeModel))).all()) == 1


async def test_pending_conflict_blocks_new_mutation_and_keep_current_does_not_advance(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud"))
    conflict = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Offline"))
    with pytest.raises(KnowledgeSyncError, match="conflict_pending"):
        await repo.mutate(sync_scope, str(uuid4()), mutation("update", 2, "Bypass"))
    key = str(uuid4())
    resolution = KnowledgeSyncResolution(
        conflict_id=conflict.to_dict()["receipt"]["conflict_id"],
        expected_current_revision=2,
        decision="keep_current",
    )
    resolved = await repo.resolve(sync_scope, key, resolution)
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 2, "Later"))
    assert (await repo.resolve(sync_scope, key, resolution)).receipt_json == resolved.receipt_json
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 3


async def test_viewer_and_revoked_membership_cannot_replay_writes(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    from sqlalchemy import delete, update

    from src.infrastructure.adapters.secondary.persistence.models import UserProject, UserTenant

    repo = SqlKnowledgeSyncRepository(db)
    key = str(uuid4())
    await repo.mutate(sync_scope, key, mutation())
    await db.execute(
        update(UserProject).where(UserProject.user_id == sync_scope.actor_id).values(role="viewer")
    )
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1))
    assert (await repo.changes(sync_scope, 0, 10)).next_cursor == 1
    await db.execute(delete(UserTenant).where(UserTenant.user_id == sync_scope.actor_id))
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate(sync_scope, key, mutation())


async def test_global_memory_id_collision_is_scoped_without_disclosure(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    from src.infrastructure.adapters.secondary.persistence.models import UserProject

    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    db.add(
        Project(
            id="other-project",
            tenant_id=sync_scope.tenant_id,
            owner_id=sync_scope.actor_id,
            name="Other",
        )
    )
    await db.flush()
    db.add(
        UserProject(
            id="other-membership",
            project_id="other-project",
            user_id=sync_scope.actor_id,
            role="owner",
        )
    )
    await db.commit()
    other = await repo.resolve_scope(sync_scope.actor_id, "other-project")
    for deleted in (False, True):
        if deleted:
            await repo.mutate(sync_scope, str(uuid4()), mutation("delete", 1))
        with pytest.raises(KnowledgeSyncError, match="id_collision"):
            await repo.mutate(other, str(uuid4()), mutation())
        assert (await repo.changes(other, 0, 100)).next_cursor == 0


async def test_member_needs_author_or_explicit_nonexpired_edit_share(
    db: AsyncSession, sync_scope: KnowledgeSyncScope, another_user: User
) -> None:
    from datetime import UTC, datetime, timedelta

    from src.infrastructure.adapters.secondary.persistence.models import (
        MemoryShare,
        UserProject,
        UserTenant,
    )

    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    db.add_all(
        [
            UserTenant(
                id="other-ut",
                tenant_id=sync_scope.tenant_id,
                user_id=another_user.id,
                role="member",
            ),
            UserProject(
                id="other-up",
                project_id=sync_scope.project_id,
                user_id=another_user.id,
                role="member",
            ),
        ]
    )
    await db.commit()
    other = await repo.resolve_scope(another_user.id, sync_scope.project_id)
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate(other, str(uuid4()), mutation("update", 1))
    share = MemoryShare(
        id="edit-share",
        memory_id="sync-memory-1",
        shared_with_user_id=another_user.id,
        permissions={"edit": True},
        shared_by=sync_scope.actor_id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    db.add(share)
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate(other, str(uuid4()), mutation("update", 1))
    share.expires_at = None
    await db.commit()
    outcome = await repo.mutate(other, str(uuid4()), mutation("update", 1))
    assert outcome.to_dict()["receipt"]["version"]["author_id"] == sync_scope.actor_id


async def test_edit_share_does_not_grant_delete_permission(
    db: AsyncSession, sync_scope: KnowledgeSyncScope, another_user: User
) -> None:
    from src.infrastructure.adapters.secondary.persistence.models import (
        MemoryShare,
        UserProject,
        UserTenant,
    )

    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    db.add_all(
        [
            UserTenant(
                id="delete-ut",
                tenant_id=sync_scope.tenant_id,
                user_id=another_user.id,
                role="member",
            ),
            UserProject(
                id="delete-up",
                project_id=sync_scope.project_id,
                user_id=another_user.id,
                role="member",
            ),
            MemoryShare(
                id="delete-share",
                memory_id="sync-memory-1",
                shared_with_user_id=another_user.id,
                permissions={"edit": True},
                shared_by=sync_scope.actor_id,
            ),
        ]
    )
    await db.commit()
    other = await repo.resolve_scope(another_user.id, sync_scope.project_id)
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate(other, str(uuid4()), mutation("delete", 1))
    assert await db.get(Memory, "sync-memory-1") is not None


async def test_keep_both_preserves_both_versions_and_replays_exact_receipt(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud edit"))
    conflict = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Offline edit"))
    await db.commit()
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    key = str(uuid4())
    resolution = KnowledgeSyncResolution(
        conflict_id=conflict_id, expected_current_revision=2, decision="keep_both"
    )
    resolved = await repo.resolve(sync_scope, key, resolution)
    await db.commit()
    receipt = resolved.to_dict()["receipt"]
    assert receipt["status"] == "resolved"
    assert receipt["conflict_id"] == conflict_id
    assert receipt["version"]["revision"] == 2
    assert receipt["version"]["content"]["title"] == "Cloud edit"
    copy_id = receipt["copy_memory_id"]
    assert copy_id == str(uuid5(UUID(conflict_id), "keep-both-copy"))
    assert copy_id != "sync-memory-1"
    saved_version = receipt["copy_version"]
    assert saved_version["memory_id"] == copy_id
    assert saved_version["revision"] == 1 and not saved_version["deleted"]
    assert saved_version["author_id"] == sync_scope.actor_id
    assert saved_version["content"]["title"] == "Offline edit"
    original = await db.get(Memory, "sync-memory-1")
    assert original is not None and original.title == "Cloud edit" and original.version == 2
    saved = await db.get(Memory, copy_id)
    assert saved is not None and saved.title == "Offline edit" and saved.version == 1
    assert saved.project_id == sync_scope.project_id
    changes = (await repo.changes(sync_scope, 0, 100)).to_dict()["changes"]
    assert changes[-1]["sequence"] == receipt["sequence"]
    assert changes[-1]["version"]["memory_id"] == copy_id
    assert (await repo.resolve(sync_scope, key, resolution)).receipt_json == resolved.receipt_json
    with pytest.raises(KnowledgeSyncError, match="conflict_resolved"):
        await repo.resolve(sync_scope, str(uuid4()), resolution)
    followup = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 2, "After copy"))
    assert followup.to_dict()["receipt"]["version"]["revision"] == 3


async def test_keep_both_stale_revision_rejects_without_copy_and_keeps_object_paused(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud edit"))
    conflict = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Offline edit"))
    await db.commit()
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    with pytest.raises(KnowledgeSyncError, match="resolution_stale"):
        await repo.resolve(
            sync_scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=conflict_id, expected_current_revision=1, decision="keep_both"
            ),
        )
    document = await repo.conflict(sync_scope, conflict_id)
    assert document["resolved_change_id"] is None
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 2
    with pytest.raises(KnowledgeSyncError, match="conflict_pending"):
        await repo.mutate(sync_scope, str(uuid4()), mutation("update", 2, "Bypass"))
    resolved = await repo.resolve(
        sync_scope,
        str(uuid4()),
        KnowledgeSyncResolution(
            conflict_id=conflict_id, expected_current_revision=2, decision="keep_both"
        ),
    )
    assert resolved.to_dict()["receipt"]["status"] == "resolved"


async def test_keep_both_delete_proposal_fails_closed_without_touching_either_version(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud edit"))
    conflict = await repo.mutate(sync_scope, str(uuid4()), mutation("delete", 1))
    await db.commit()
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    with pytest.raises(KnowledgeSyncError, match="input_invalid"):
        await repo.resolve(
            sync_scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=conflict_id, expected_current_revision=2, decision="keep_both"
            ),
        )
    document = await repo.conflict(sync_scope, conflict_id)
    assert document["resolved_change_id"] is None
    original = await db.get(Memory, "sync-memory-1")
    assert original is not None and original.title == "Cloud edit" and original.version == 2
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 2


async def test_keep_both_revalidates_write_permission_at_resolution_time(
    db: AsyncSession, sync_scope: KnowledgeSyncScope
) -> None:
    from sqlalchemy import update

    from src.infrastructure.adapters.secondary.persistence.models import UserProject

    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud edit"))
    conflict = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Offline edit"))
    await db.commit()
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    await db.execute(
        update(UserProject).where(UserProject.user_id == sync_scope.actor_id).values(role="viewer")
    )
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.resolve(
            sync_scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=conflict_id, expected_current_revision=2, decision="keep_both"
            ),
        )
    document = await repo.conflict(sync_scope, conflict_id)
    assert document["resolved_change_id"] is None
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 2
