"""Conflict refresh and successful resolution replays retain current authorization."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, update

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError, KnowledgeSyncResolution
from src.infrastructure.adapters.secondary.persistence.models import (
    MemoryShare,
    UserProject,
    UserTenant,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)
from src.tests.integration.test_knowledge_sync_repository import mutation


@pytest.fixture
async def sync_scope(db, test_project_db, test_user):
    return await SqlKnowledgeSyncRepository(db).resolve_scope(test_user.id, test_project_db.id)


async def test_conflict_refresh_preserves_original_and_observes_later_online_edit(db, sync_scope):
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "First cloud edit"))
    result = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Offline edit"))
    conflict_id = result.to_dict()["receipt"]["conflict_id"]
    await db.commit()
    await repo.mutate_online(sync_scope, str(uuid4()), mutation("update", 2, "Later cloud edit"))
    await db.commit()
    refreshed = await repo.conflict(sync_scope, conflict_id)
    assert refreshed["current"]["revision"] == 2
    assert refreshed["current"]["content"]["title"] == "First cloud edit"
    assert refreshed["observed_current"]["revision"] == 3
    assert refreshed["observed_current"]["content"]["title"] == "Later cloud edit"
    with pytest.raises(KnowledgeSyncError, match="resolution_stale"):
        await repo.resolve(
            sync_scope,
            str(uuid4()),
            KnowledgeSyncResolution(
                conflict_id=conflict_id, expected_current_revision=2, decision="use_proposed"
            ),
        )
    resolved = await repo.resolve(
        sync_scope,
        str(uuid4()),
        KnowledgeSyncResolution(
            conflict_id=conflict_id, expected_current_revision=3, decision="use_proposed"
        ),
    )
    assert resolved.to_dict()["receipt"]["version"]["revision"] == 4


@pytest.mark.parametrize("decision", ["keep_current", "use_proposed"])
async def test_resolution_receipt_replay_rechecks_viewer_downgrade(db, sync_scope, decision):
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud"))
    result = await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Offline"))
    command = KnowledgeSyncResolution(
        conflict_id=result.to_dict()["receipt"]["conflict_id"],
        expected_current_revision=2,
        decision=decision,
    )
    key = str(uuid4())
    resolved = await repo.resolve(sync_scope, key, command)
    await db.commit()
    replay = await repo.resolve(sync_scope, key, command)
    assert replay.replayed and replay.receipt_json == resolved.receipt_json
    await db.execute(
        update(UserProject)
        .where(
            UserProject.project_id == sync_scope.project_id,
            UserProject.user_id == sync_scope.actor_id,
        )
        .values(role="viewer")
    )
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.resolve(sync_scope, key, command)


async def test_resolution_replay_rejects_revoked_share(db, sync_scope, another_user):
    repo = SqlKnowledgeSyncRepository(db)
    await repo.mutate(sync_scope, str(uuid4()), mutation())
    db.add_all(
        [
            UserTenant(
                id="refresh-tenant",
                tenant_id=sync_scope.tenant_id,
                user_id=another_user.id,
                role="member",
            ),
            UserProject(
                id="refresh-project",
                project_id=sync_scope.project_id,
                user_id=another_user.id,
                role="member",
            ),
            MemoryShare(
                id="refresh-share",
                memory_id="sync-memory-1",
                shared_with_user_id=another_user.id,
                permissions={"edit": True},
                shared_by=sync_scope.actor_id,
            ),
        ]
    )
    await db.commit()
    editor = await repo.resolve_scope(another_user.id, sync_scope.project_id)
    await repo.mutate(sync_scope, str(uuid4()), mutation("update", 1, "Cloud"))
    outcome = await repo.mutate(editor, str(uuid4()), mutation("update", 1, "Editor"))
    command = KnowledgeSyncResolution(
        conflict_id=outcome.to_dict()["receipt"]["conflict_id"],
        expected_current_revision=2,
        decision="use_proposed",
    )
    key = str(uuid4())
    await repo.resolve(editor, key, command)
    await db.commit()
    await db.execute(delete(MemoryShare).where(MemoryShare.id == "refresh-share"))
    await db.commit()
    with pytest.raises(KnowledgeSyncError, match="forbidden"):
        await repo.resolve(editor, key, command)
