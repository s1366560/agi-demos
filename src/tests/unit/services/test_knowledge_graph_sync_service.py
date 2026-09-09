"""Graph sync contracts validate structure; the service delegates verbatim."""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.application.services.knowledge_graph_sync_service import (
    KnowledgeGraphSyncService,
)
from src.domain.model.knowledge_sync.contracts import (
    GraphSyncContent,
    GraphSyncEntity,
    GraphSyncMutation,
    GraphSyncRelationship,
    GraphSyncResolution,
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncScope,
)


def entity(name: str = "Alice") -> GraphSyncEntity:
    return GraphSyncEntity(name=name, kind="person")


def content() -> GraphSyncContent:
    return GraphSyncContent(
        source_revision=1,
        change_sequence=3,
        audit_attempt=2,
        entities=(entity(), GraphSyncEntity(name="Acme", kind="organization")),
        relationships=(
            GraphSyncRelationship(
                source_index=0,
                target_index=1,
                relation_type="works_at",
                fact="Alice works at Acme",
                score=0.5,
            ),
        ),
    )


@pytest.mark.unit
class TestGraphSyncContracts:
    def test_content_roundtrip_is_canonical(self) -> None:
        value = content()
        assert GraphSyncContent.from_dict(value.to_dict()) == value

    def test_relationship_index_must_reference_an_entity(self) -> None:
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncContent(
                source_revision=1,
                change_sequence=3,
                audit_attempt=1,
                entities=(entity(),),
                relationships=(
                    GraphSyncRelationship(
                        source_index=0,
                        target_index=1,
                        relation_type="knows",
                        fact="Alice knows nobody",
                        score=1.0,
                    ),
                ),
            )

    def test_score_must_be_finite_probability(self) -> None:
        for bad in (float("nan"), float("inf"), -0.1, 1.1):
            with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
                GraphSyncRelationship(
                    source_index=0,
                    target_index=0,
                    relation_type="knows",
                    fact="fact",
                    score=bad,
                )

    def test_provenance_fields_are_positive(self) -> None:
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncContent(source_revision=0, change_sequence=3, audit_attempt=1)
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncContent(source_revision=1, change_sequence=0, audit_attempt=1)
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncContent(source_revision=1, change_sequence=3, audit_attempt=0)

    def test_mutation_invariants_mirror_memory_sync(self) -> None:
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncMutation(
                operation="create", object_id="m", expected_revision=1, content=content()
            )
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncMutation(
                operation="delete", object_id="m", expected_revision=1, content=content()
            )
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncMutation(
                operation="update", object_id="m ", expected_revision=1, content=content()
            )

    def test_mutation_roundtrip(self) -> None:
        value = GraphSyncMutation(
            operation="update", object_id="m", expected_revision=2, content=content()
        )
        assert GraphSyncMutation.from_dict(value.to_dict()) == value

    def test_resolution_requires_content_exactly_for_merged(self) -> None:
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncResolution(
                conflict_id=str(uuid4()), expected_current_revision=1, decision="merged"
            )
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_input_invalid"):
            GraphSyncResolution(
                conflict_id=str(uuid4()),
                expected_current_revision=1,
                decision="keep_current",
                content=content(),
            )


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def resolve_scope(self, actor_id: str, project_id: str) -> KnowledgeSyncScope:
        return KnowledgeSyncScope(tenant_id="t", project_id=project_id, actor_id=actor_id)

    async def mutate_graph(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: GraphSyncMutation
    ) -> KnowledgeSyncOutcome:
        self.calls.append(("mutate", change_id))
        return KnowledgeSyncOutcome(receipt_json='{"status":"applied"}')

    async def resolve_graph(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: GraphSyncResolution
    ) -> KnowledgeSyncOutcome:
        self.calls.append(("resolve", change_id))
        return KnowledgeSyncOutcome(receipt_json='{"status":"resolved"}')

    async def graph_changes(
        self, scope: KnowledgeSyncScope, after: int, limit: int
    ) -> KnowledgeSyncPage:
        self.calls.append(("changes", after))
        return KnowledgeSyncPage(changes_json="[]", next_cursor=after, has_more=False)

    async def graph_conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict:
        self.calls.append(("conflict", conflict_id))
        return {"id": conflict_id}


@pytest.mark.unit
class TestKnowledgeGraphSyncService:
    async def test_delegates_and_validates_change_ids(self) -> None:
        repository = FakeRepository()
        service = KnowledgeGraphSyncService(repository=repository)
        scope = await service.resolve_scope("actor", "project")
        key = str(uuid4())
        await service.mutate(
            scope,
            key,
            GraphSyncMutation(operation="delete", object_id="m", expected_revision=1),
        )
        await service.resolve(
            scope,
            key,
            GraphSyncResolution(
                conflict_id=str(uuid4()), expected_current_revision=1, decision="keep_current"
            ),
        )
        await service.conflict(scope, str(uuid4()))
        assert [call[0] for call in repository.calls] == ["mutate", "resolve", "conflict"]
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_change_id_invalid"):
            await service.mutate(
                scope,
                "not-a-uuid",
                GraphSyncMutation(operation="delete", object_id="m", expected_revision=1),
            )

    async def test_cursor_bounds_fail_closed(self) -> None:
        service = KnowledgeGraphSyncService(repository=FakeRepository())
        scope = KnowledgeSyncScope(tenant_id="t", project_id="p", actor_id="a")
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_cursor_invalid"):
            await service.changes(scope, -1, 100)
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_cursor_invalid"):
            await service.changes(scope, 0, 0)
        with pytest.raises(KnowledgeSyncError, match="knowledge_sync_cursor_invalid"):
            await service.changes(scope, 0, 501)
