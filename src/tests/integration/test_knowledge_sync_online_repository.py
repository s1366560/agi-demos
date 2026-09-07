"""Online CAS reuses journal transactions without creating offline conflicts."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError, KnowledgeSyncResolution
from src.infrastructure.adapters.primary.web.routers.knowledge_sync import error_response
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncConflictModel as Conflict,
    KnowledgeSyncReceiptModel as Receipt,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    User,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)
from src.tests.integration.test_knowledge_sync_repository import mutation, sync_scope as _sync_scope

sync_scope = _sync_scope


@pytest.mark.parametrize("online", [False, True])
@pytest.mark.parametrize("revocation", ["viewer", "share"])
async def test_write_receipt_replay_rechecks_current_write_permission(
    db, sync_scope, another_user, online, revocation
):
    repo = SqlKnowledgeSyncRepository(db)
    method = repo.mutate_online if online else repo.mutate
    await method(sync_scope, str(uuid4()), mutation())
    db.add_all(
        [
            UserTenant(
                id="replay-ut",
                tenant_id=sync_scope.tenant_id,
                user_id=another_user.id,
                role="member",
            ),
            UserProject(
                id="replay-up",
                project_id=sync_scope.project_id,
                user_id=another_user.id,
                role="member",
            ),
            MemoryShare(
                id="replay-share",
                memory_id="sync-memory-1",
                shared_with_user_id=another_user.id,
                permissions={"edit": True},
                shared_by=sync_scope.actor_id,
            ),
        ]
    )
    await db.commit()
    editor = await repo.resolve_scope(another_user.id, sync_scope.project_id)
    key = str(uuid4())
    request = mutation("update", 1, "Shared edit")
    await method(editor, key, request)
    await db.commit()
    if revocation == "viewer":
        await db.execute(
            update(UserProject).where(UserProject.id == "replay-up").values(role="viewer")
        )
    else:
        await db.execute(delete(MemoryShare).where(MemoryShare.id == "replay-share"))
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await method(editor, key, request)
    assert len((await db.scalars(select(Receipt))).all()) == 2
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 2


@pytest.mark.parametrize("online", [False, True])
async def test_author_can_replay_delete_receipt_using_tombstone(db, sync_scope, online):
    repo = SqlKnowledgeSyncRepository(db)
    method = repo.mutate_online if online else repo.mutate
    await method(sync_scope, str(uuid4()), mutation())
    await db.execute(
        update(UserProject).where(UserProject.user_id == sync_scope.actor_id).values(role="member")
    )
    await db.commit()
    key = str(uuid4())
    request = mutation("delete", 1)
    original = await method(sync_scope, key, request)
    await db.commit()
    replay = await method(sync_scope, key, request)
    assert replay.replayed and replay.receipt_json == original.receipt_json
    assert await db.get(Memory, "sync-memory-1") is None


async def test_online_stale_cas_rolls_back_without_blocking_a_fresh_command(db, sync_scope):
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate_online(sync_scope, str(uuid4()), mutation())
    await repo.mutate_online(sync_scope, str(uuid4()), mutation("update", 1, "Current"))
    await db.commit()
    failed_key = str(uuid4())
    with pytest.raises(KnowledgeSyncError, match="knowledge_sync_write_conflict") as failure:
        await repo.mutate_online(sync_scope, failed_key, mutation("update", 1, "Stale"))
    assert error_response(failure.value).status_code == 409
    await db.commit()
    assert (await db.scalars(select(Conflict))).all() == []
    assert len((await db.scalars(select(Receipt))).all()) == 2
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 2
    assert (await db.get(Memory, "sync-memory-1")).title == "Current"
    fresh = await repo.mutate_online(sync_scope, failed_key, mutation("update", 2, "Fresh"))
    await db.commit()
    assert fresh.to_dict()["receipt"]["version"]["revision"] == 3


async def test_online_receipt_replays_original_version_and_cannot_cross_protocols(db, sync_scope):
    repo = SqlKnowledgeSyncRepository(db)
    key = str(uuid4())
    original = await repo.mutate_online(sync_scope, key, mutation())
    await repo.mutate_online(sync_scope, str(uuid4()), mutation("update", 1, "Later"))
    await db.commit()
    replay = await repo.mutate_online(sync_scope, key, mutation())
    assert replay.replayed and replay.receipt_json == original.receipt_json
    for request, online in ((mutation(title="Different"), True), (mutation(), False)):
        with pytest.raises(KnowledgeSyncError, match="idempotency_conflict"):
            method = repo.mutate_online if online else repo.mutate
            await method(sync_scope, key, request)
    offline_key = str(uuid4())
    await repo.mutate(sync_scope, offline_key, mutation("update", 2, "Offline accepted"))
    with pytest.raises(KnowledgeSyncError, match="idempotency_conflict"):
        await repo.mutate_online(sync_scope, offline_key, mutation("update", 2, "Offline accepted"))
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 3


async def test_online_delete_reserves_identity_and_late_updates_do_not_restore(db, sync_scope):
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate_online(sync_scope, str(uuid4()), mutation())
    outcome = await repo.mutate_online(sync_scope, str(uuid4()), mutation("delete", 1))
    await db.commit()
    assert outcome.to_dict()["receipt"]["version"]["revision"] == 2
    for request in (
        mutation(),
        mutation("update", 1),
        mutation("update", 2),
        mutation("delete", 2),
    ):
        with pytest.raises(KnowledgeSyncError, match="write_conflict"):
            await repo.mutate_online(sync_scope, str(uuid4()), request)
    await db.commit()
    assert await db.get(Memory, "sync-memory-1") is None
    assert (await db.get(Tombstone, "sync-memory-1")).revision == 2
    assert (await db.scalars(select(Conflict))).all() == []
    assert (await repo.changes(sync_scope, 0, 100)).next_cursor == 2


async def test_online_edit_keeps_offline_conflict_and_requires_fresh_resolution(db, sync_scope):
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate_online(sync_scope, str(uuid4()), mutation())
    await repo.mutate_online(sync_scope, str(uuid4()), mutation("update", 1, "Current"))
    conflict = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Offline"))
    conflict_id = conflict.to_dict()["receipt"]["conflict_id"]
    await repo.mutate_online(sync_scope, str(uuid4()), mutation("update", 2, "Online"))
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="conflict_pending"):
        await repo.mutate(sync_scope, str(uuid4()), mutation("update", 3))
    with pytest.raises(KnowledgeSyncError, match="resolution_stale"):
        await repo.resolve(
            sync_scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=conflict_id, expected_current_revision=2, decision="use_proposed"
            ),
        )
    assert (await repo.conflict(sync_scope, conflict_id))["proposed"]["content"][
        "title"
    ] == "Offline"
    assert (await db.get(Memory, "sync-memory-1")).title == "Online"


async def test_online_share_editor_is_journal_actor_but_not_author_and_cannot_delete(
    db, sync_scope, another_user
):
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate_online(sync_scope, str(uuid4()), mutation())
    db.add_all(
        [
            UserTenant(
                id="editor-tenant",
                tenant_id=sync_scope.tenant_id,
                user_id=another_user.id,
                role="member",
            ),
            UserProject(
                id="editor-project",
                project_id=sync_scope.project_id,
                user_id=another_user.id,
                role="member",
            ),
            MemoryShare(
                id="editor-share",
                memory_id="sync-memory-1",
                shared_with_user_id=another_user.id,
                permissions={"edit": True},
                shared_by=sync_scope.actor_id,
            ),
        ]
    )
    await db.commit()
    editor = await repo.resolve_scope(another_user.id, sync_scope.project_id)
    key = str(uuid4())
    await repo.mutate_online(editor, key, mutation("update", 1, "Editor"))
    await db.commit()
    change = await db.scalar(select(Change).where(Change.revision == 2))
    assert change.actor_id == another_user.id
    assert change.snapshot["author_id"] == sync_scope.actor_id
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate_online(editor, str(uuid4()), mutation("delete", 2))
    await db.execute(delete(UserTenant).where(UserTenant.id == "editor-tenant"))
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate_online(editor, key, mutation("update", 1, "Editor"))


async def test_online_viewer_cannot_mutate(db, sync_scope):
    repo = SqlKnowledgeSyncRepository(db)
    await db.execute(
        update(UserProject).where(UserProject.user_id == sync_scope.actor_id).values(role="viewer")
    )
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.mutate_online(sync_scope, str(uuid4()), mutation())
    assert (await db.scalars(select(Change))).all() == []


@pytest.mark.parametrize("invalid", ["inactive_actor", "wrong_tenant", "missing_project"])
async def test_online_rejects_invalid_actor_or_scope_before_any_write(db, sync_scope, invalid):
    scope = sync_scope
    if invalid == "inactive_actor":
        await db.execute(update(User).where(User.id == scope.actor_id).values(is_active=False))
        await db.commit()
    elif invalid == "wrong_tenant":
        scope = replace(scope, tenant_id="wrong-tenant")
    else:
        scope = replace(scope, project_id="missing-project")
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await SqlKnowledgeSyncRepository(db).mutate_online(scope, str(uuid4()), mutation())
    assert (await db.scalars(select(Change))).all() == []
    assert (await db.scalars(select(Receipt))).all() == []
    assert await db.get(Memory, "sync-memory-1") is None
