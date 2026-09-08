"""Seed or remove a declared provenance sample in the explicitly isolated QA graph."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from scripts.qa_cloud_knowledge_sync_database import QaCloudDatabase, qa_engine
from scripts.qa_cloud_knowledge_sync_graph import QA_NEO4J_URI
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
    SqlProjectRepository,
)
from src.infrastructure.graph.neo4j_client import Neo4jClient
from src.infrastructure.graph.schemas import (
    CommunityNode,
    EntityEdge,
    EntityNode,
    EpisodicEdge,
    EpisodicNode,
)

if TYPE_CHECKING:
    from src.domain.model.memory.memory import Memory
    from src.domain.model.project.project import Project

FIXTURE_VERSION = "qa-graph-provenance-v1"
CAPTURED_CONTENT = (
    "QA_GRAPH_CAPTURE_V1: This declared sample was captured before the current memory was read."
)
UNLINKED_CONTENT = "QA_GRAPH_UNLINKED_V1: This declared source has no associated memory."


@dataclass(frozen=True, kw_only=True)
class QaGraphFixture:
    fixture_id: str
    tenant_id: str
    project_id: str
    memory_id: str
    nodes: tuple[EpisodicNode | EntityNode | CommunityNode, ...]
    edges: tuple[EntityEdge | EpisodicEdge, ...]
    missing_source_uuid: str

    def summary(self) -> dict[str, object]:
        return {
            "fixture_id": self.fixture_id,
            "fixture_version": FIXTURE_VERSION,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "memory_id": self.memory_id,
            "nodes": [
                {"uuid": node.uuid, "name": node.name, "labels": node.get_labels()}
                for node in self.nodes
            ],
            "edges": [
                {
                    "source_uuid": edge.source_uuid,
                    "target_uuid": edge.target_uuid,
                    "relationship_type": edge.relationship_type,
                }
                for edge in self.edges
            ],
            "missing_source_uuid": self.missing_source_uuid,
        }


def build_qa_graph_fixture(
    state: QaCloudDatabase, *, tenant_id: str, project_id: str, memory_id: str
) -> QaGraphFixture:
    state.validate()
    for value in (tenant_id, project_id, memory_id):
        if str(UUID(value)) != value:
            raise ValueError("QA fixture scope and memory IDs must be canonical UUIDs")
    namespace = uuid5(
        UUID(state.schema.removeprefix("qa_cloud_sync_")),
        f"{FIXTURE_VERSION}/{tenant_id}/{project_id}/{memory_id}",
    )
    fixture_id = str(namespace)
    created_at = datetime.fromisoformat(state.created_at)

    def identifier(name: str) -> str:
        return str(uuid5(namespace, name))

    linked = EpisodicNode(
        uuid=identifier("linked-source"),
        name="QA Graph Captured Source",
        content=CAPTURED_CONTENT,
        source_description="Declared QA sample",
        valid_at=created_at,
        group_id=project_id,
        memory_id=memory_id,
        tenant_id=tenant_id,
        project_id=project_id,
        created_at=created_at,
    )
    unlinked = EpisodicNode(
        uuid=identifier("unlinked-source"),
        name="QA Graph Unlinked Source",
        content=UNLINKED_CONTENT,
        source_description="Declared QA sample",
        valid_at=created_at,
        group_id=project_id,
        tenant_id=tenant_id,
        project_id=project_id,
        created_at=created_at,
    )
    first = EntityNode(
        uuid=identifier("first-entity"),
        name="QA Graph Duplicate Name",
        entity_type="Concept",
        summary="Declared sample entity A",
        tenant_id=tenant_id,
        project_id=project_id,
        created_at=created_at,
    )
    second = EntityNode(
        uuid=identifier("second-entity"),
        name="QA Graph Duplicate Name",
        entity_type="Concept",
        summary="Declared sample entity B",
        tenant_id=tenant_id,
        project_id=project_id,
        created_at=created_at,
    )
    community = CommunityNode(
        uuid=identifier("community"),
        name="QA Graph Membership",
        summary="Membership is not a source reference",
        member_count=1,
        tenant_id=tenant_id,
        project_id=project_id,
        created_at=created_at,
    )
    missing = identifier("missing-source")
    edges: tuple[EntityEdge | EpisodicEdge, ...] = (
        EpisodicEdge(source_uuid=linked.uuid, target_uuid=first.uuid, created_at=created_at),
        EpisodicEdge(source_uuid=linked.uuid, target_uuid=second.uuid, created_at=created_at),
        EpisodicEdge(source_uuid=unlinked.uuid, target_uuid=second.uuid, created_at=created_at),
        EntityEdge(
            uuid=identifier("forward-edge"),
            source_uuid=first.uuid,
            target_uuid=second.uuid,
            relationship_type="QA_SUPPORTS",
            fact="QA_GRAPH_FORWARD_V1: entity A supports entity B.",
            episodes=[linked.uuid, missing],
            created_at=created_at,
            valid_at=created_at,
        ),
        EntityEdge(
            uuid=identifier("reverse-edge"),
            source_uuid=second.uuid,
            target_uuid=first.uuid,
            relationship_type="QA_REPLIES_TO",
            fact="QA_GRAPH_REVERSE_V1: entity B replies to entity A.",
            episodes=[unlinked.uuid],
            created_at=created_at,
            valid_at=created_at,
        ),
        EntityEdge(
            uuid=identifier("self-edge"),
            source_uuid=first.uuid,
            target_uuid=first.uuid,
            relationship_type="QA_SELF",
            fact="QA_GRAPH_SELF_V1: declared self relationship.",
            episodes=[linked.uuid],
            created_at=created_at,
        ),
        EpisodicEdge(
            source_uuid=first.uuid,
            target_uuid=community.uuid,
            relationship_type="BELONGS_TO",
            created_at=created_at,
        ),
    )
    return QaGraphFixture(
        fixture_id=fixture_id,
        tenant_id=tenant_id,
        project_id=project_id,
        memory_id=memory_id,
        nodes=(linked, unlinked, first, second, community),
        edges=edges,
        missing_source_uuid=missing,
    )


def require_qa_fixture_records(
    fixture: QaGraphFixture, project: Project | None, memory: Memory | None, *, cleanup: bool
) -> None:
    if (
        project is None
        or project.id != fixture.project_id
        or project.tenant_id != fixture.tenant_id
    ):
        raise ValueError("QA fixture project does not belong to the requested tenant")
    if not cleanup and (
        memory is None or memory.id != fixture.memory_id or memory.project_id != fixture.project_id
    ):
        raise ValueError("QA fixture requires an existing memory in the requested project")


async def apply_qa_graph_fixture(
    client: Neo4jClient, fixture: QaGraphFixture, *, cleanup: bool = False
) -> None:
    """Use the same public persistence methods as the production graph producer."""
    if client.uri != QA_NEO4J_URI or client.database != "neo4j":
        raise ValueError("Graph fixture writes require the exact isolated QA Neo4j target")
    # Check every owned UUID before any write; never overwrite another sample or scope.
    for node in fixture.nodes:
        existing = await client.find_node_by_uuid(node.uuid)
        if existing is not None and (
            existing.get("tenant_id") != fixture.tenant_id
            or existing.get("project_id") != fixture.project_id
            or existing.get("qa_fixture_id") != fixture.fixture_id
        ):
            raise ValueError("An existing graph node is not owned by this exact QA fixture")
    if cleanup:
        for node in fixture.nodes:
            _ = await client.delete_node(node.uuid)
        return
    nodes: list[dict[str, Any]] = [
        {
            "uuid": node.uuid,
            "labels": node.get_labels(),
            "properties": {**node.to_neo4j_properties(), "qa_fixture_id": fixture.fixture_id},
        }
        for node in fixture.nodes
    ]
    edges: list[dict[str, Any]] = [
        {
            "from_uuid": edge.source_uuid,
            "to_uuid": edge.target_uuid,
            "relationship_type": edge.relationship_type,
            "properties": edge.to_neo4j_properties(),
        }
        for edge in fixture.edges
    ]
    await client.save_nodes_batch(nodes)
    await client.save_edges_batch(edges)


async def run_qa_graph_fixture(
    metadata: Path, *, tenant_id: str, project_id: str, memory_id: str, cleanup: bool = False
) -> dict[str, object]:
    state = QaCloudDatabase.load(metadata)
    fixture = build_qa_graph_fixture(
        state, tenant_id=tenant_id, project_id=project_id, memory_id=memory_id
    )
    engine = qa_engine(state)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with sessions() as session:
            if await session.scalar(sa.text("SELECT current_schema()")) != state.schema:
                raise ValueError("The exact QA schema is absent; refusing graph writes")
            project = await SqlProjectRepository(session).find_by_id(project_id)
            memory = await SqlMemoryRepository(session).find_by_id(memory_id)
            require_qa_fixture_records(fixture, project, memory, cleanup=cleanup)
    finally:
        await engine.dispose()
    # No global graph settings, LLM factories, embedding factories or background tasks.
    async with Neo4jClient(uri=state.neo4j_uri, user="", password="", database="neo4j") as client:
        await apply_qa_graph_fixture(client, fixture, cleanup=cleanup)
    return {"operation": "cleanup" if cleanup else "seed", **fixture.summary()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("operation", choices=["seed", "cleanup"])
    _ = parser.add_argument("--metadata", type=Path, required=True)
    _ = parser.add_argument("--tenant-id", required=True)
    _ = parser.add_argument("--project-id", required=True)
    _ = parser.add_argument("--memory-id", required=True)
    args = parser.parse_args()
    result = asyncio.run(
        run_qa_graph_fixture(
            args.metadata,
            tenant_id=args.tenant_id,
            project_id=args.project_id,
            memory_id=args.memory_id,
            cleanup=args.operation == "cleanup",
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
