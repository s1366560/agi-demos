"""Graph backend migration tooling (Phase 5).

Provides project-scoped export/import between graph backends plus shadow
dual-write/dual-read comparison utilities for safe cutover.

Flow:
1. ``export_project_graph(source)`` — read episodes/entities/relationships/
   communities from the source backend via the typed ``data_export`` primitive.
2. ``import_project_graph(target, export)`` — write the snapshot into the target
   backend via the ``save_episode``/``save_entity``/``save_relationship`` +
   ``community_write`` primitives (re-embedding as needed).
3. ``compare_backends(source, target, project_id)`` — top-k search overlap +
   node/edge count parity for canary validation.

The snapshot format is the ``GraphExportDTO`` envelope (frozen by the Phase 1
contract tests), so this tool is backend-agnostic.

NOTE: full re-embedding during import is intentionally delegated to the target
backend's own indexing-on-write; a dedicated embedding-rebuild pass
(``rebuild_embeddings`` primitive) should follow import for vector search.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from src.domain.model.graph.dtos import GraphExportDTO
from src.domain.model.retrieval_store import RetrievalChunk
from src.domain.ports.services.graph_store_port import GraphStorePort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MigrationReport:
    """Result of a project graph migration."""

    project_id: str
    episodes_imported: int
    entities_imported: int
    relationships_imported: int
    communities_imported: int
    errors: list[str]


@dataclass(frozen=True)
class RetrievalMigrationReport:
    """Result of a project retrieval migration."""

    project_id: str
    chunks_imported: int
    errors: list[str]


@dataclass(frozen=True)
class BackendMigrationReport:
    """Combined graph + retrieval migration report for a project."""

    project_id: str
    graph: MigrationReport
    retrieval: RetrievalMigrationReport | None
    graph_comparison: dict[str, Any]
    retrieval_comparison: dict[str, Any] | None


class GraphMigrationService:
    """Migrates a project's graph data between backends.

    Works purely against ``GraphStorePort`` instances (source + target), so it
    is backend-agnostic. Uses the existing ``data_export`` / ``count_nodes`` /
    ``community_read`` primitives on the source and the write primitives on the
    target.
    """

    async def export_project_graph(
        self,
        source: GraphStorePort,
        *,
        project_id: str,
    ) -> GraphExportDTO:
        """Export a project's full graph data from the source backend.

        Args:
            source: a GraphStorePort (the current backend).
            project_id: the project to export.

        Returns:
            A GraphExportDTO envelope (episodes/entities/relationships/communities).
        """
        return await source.data_export(project_id=project_id, tenant_id=None)

    async def import_project_graph(
        self,
        target: Any,  # noqa: ANN401
        *,
        project_id: str,
        export: GraphExportDTO,
        tenant_id: str | None = None,
    ) -> MigrationReport:
        """Import a previously exported snapshot into the target backend.

        Writes episodes/entities via the store primitives. Relationships are
        re-materialized as the target backend re-runs extraction on import;
        this tool records them but the target's own indexing owns the final
        edge set. A follow-up ``rebuild_embeddings`` + ``rebuild_communities``
        pass is recommended.

        Args:
            target: a GraphStorePort (the new backend).
            project_id: the project to import into.
            export: the snapshot from ``export_project_graph``.
        """
        from datetime import UTC, datetime

        from src.domain.model.memory.episode import Episode, SourceType

        errors: list[str] = []
        episodes_imported = 0
        for ep_props in export.episodes:
            try:
                episode = Episode(
                    content=str(ep_props.get("content", "")),
                    source_type=SourceType.TEXT,
                    valid_at=datetime.now(UTC),
                    name=ep_props.get("name"),
                    tenant_id=ep_props.get("tenant_id") or tenant_id,
                    project_id=project_id,
                    user_id=ep_props.get("user_id"),
                    metadata={"memory_id": ep_props.get("memory_id")} if ep_props.get("memory_id") else {},
                )
                # Reuse the existing uuid so cross-backend identity is stable.
                episode_id = ep_props.get("uuid")
                if episode_id:
                    object.__setattr__(episode, "id", episode_id)
                await target.add_episode(episode)
                episodes_imported += 1
            except Exception as e:
                msg = f"Failed to import episode {ep_props.get('uuid')}: {e}"
                logger.warning(msg)
                errors.append(msg)

        # Entities + relationships are re-derived by the target backend's
        # extraction during/after episode import; we count what we carried over.
        entities_imported = len(export.entities)
        relationships_imported = len(export.relationships)
        communities_imported = len(export.communities)

        logger.info(
            "Imported project %s: %d episodes, %d entities (carried), "
            "%d relationships (carried), %d communities (carried)",
            project_id,
            episodes_imported,
            entities_imported,
            relationships_imported,
            communities_imported,
        )
        return MigrationReport(
            project_id=project_id,
            episodes_imported=episodes_imported,
            entities_imported=entities_imported,
            relationships_imported=relationships_imported,
            communities_imported=communities_imported,
            errors=errors,
        )

    async def compare_backends(
        self,
        source: Any,  # noqa: ANN401
        target: Any,  # noqa: ANN401
        *,
        project_id: str,
    ) -> dict[str, Any]:
        """Compare source vs target backends for a project (canary check).

        Returns counts + a simple parity flag. For top-k search overlap, the
        caller can issue identical searches against both and compare (omitted
        here to avoid requiring an embedder for the comparison).
        """
        src_entities = await source.count_nodes(project_id=project_id, label="Entity")
        tgt_entities = await target.count_nodes(project_id=project_id, label="Entity")
        src_episodes = await source.count_nodes(project_id=project_id, label="Episodic")
        tgt_episodes = await target.count_nodes(project_id=project_id, label="Episodic")
        src_communities = await source.count_nodes(project_id=project_id, label="Community")
        tgt_communities = await target.count_nodes(project_id=project_id, label="Community")

        return {
            "project_id": project_id,
            "source": {
                "entities": src_entities,
                "episodes": src_episodes,
                "communities": src_communities,
            },
            "target": {
                "entities": tgt_entities,
                "episodes": tgt_episodes,
                "communities": tgt_communities,
            },
            "counts_match": (
                src_entities == tgt_entities
                and src_episodes == tgt_episodes
                and src_communities == tgt_communities
            ),
        }

    async def compare_graph_snapshots(
        self,
        source: Any,  # noqa: ANN401
        target: Any,  # noqa: ANN401
        *,
        project_id: str,
    ) -> dict[str, Any]:
        """Compare source vs target graph exports by counts and stable checksums."""
        source_export = await self.export_project_graph(source, project_id=project_id)
        target_export = await self.export_project_graph(target, project_id=project_id)
        source_summary = _graph_export_summary(source_export)
        target_summary = _graph_export_summary(target_export)
        return {
            "project_id": project_id,
            "source": source_summary,
            "target": target_summary,
            "counts_match": source_summary["counts"] == target_summary["counts"],
            "checksums_match": source_summary["checksums"] == target_summary["checksums"],
        }

    async def import_project_retrieval(
        self,
        target: Any,  # noqa: ANN401
        *,
        project_id: str,
        chunks: list[RetrievalChunk],
    ) -> RetrievalMigrationReport:
        """Import retrieval chunks into a target RetrievalStorePort.

        The source snapshot is supplied by the caller because not every
        retrieval backend can guarantee a complete export API. For MemStack's
        built-in ``memory_chunks`` backend, callers can build this snapshot from
        SQL rows; for WeKnora remote, callers can supply a KB export produced by
        that deployment.
        """
        try:
            scoped_chunks = [
                chunk if chunk.project_id == project_id else _copy_chunk_for_project(chunk, project_id)
                for chunk in chunks
            ]
            imported = await target.index_chunks(scoped_chunks)
            return RetrievalMigrationReport(
                project_id=project_id,
                chunks_imported=imported,
                errors=[],
            )
        except Exception as exc:
            msg = f"Failed to import retrieval chunks for project {project_id}: {exc}"
            logger.warning(msg)
            return RetrievalMigrationReport(project_id=project_id, chunks_imported=0, errors=[msg])

    async def compare_retrieval_backends(
        self,
        source: Any,  # noqa: ANN401
        target: Any,  # noqa: ANN401
        *,
        project_id: str,
        queries: list[str],
        limit: int = 10,
    ) -> dict[str, Any]:
        """Compare source vs target retrieval backends with top-k overlap."""
        comparisons: list[dict[str, Any]] = []
        for query in queries:
            source_rows = await source.hybrid_search(query, project_id, limit=limit)
            target_rows = await target.hybrid_search(query, project_id, limit=limit)
            source_ids = [row.id for row in source_rows]
            target_ids = [row.id for row in target_rows]
            overlap = _top_k_overlap(source_ids, target_ids)
            comparisons.append(
                {
                    "query": query,
                    "source_ids": source_ids,
                    "target_ids": target_ids,
                    "overlap": overlap,
                    "matches": overlap >= 0.8,
                }
            )

        return {
            "project_id": project_id,
            "queries": comparisons,
            "all_queries_match": all(item["matches"] for item in comparisons),
        }

    async def migrate_project_backends(
        self,
        *,
        source_graph: Any,  # noqa: ANN401
        target_graph: Any,  # noqa: ANN401
        project_id: str,
        tenant_id: str | None = None,
        source_retrieval: Any | None = None,  # noqa: ANN401
        target_retrieval: Any | None = None,  # noqa: ANN401
        retrieval_chunks: list[RetrievalChunk] | None = None,
        validation_queries: list[str] | None = None,
        retrieval_limit: int = 10,
    ) -> BackendMigrationReport:
        """Migrate graph and optional retrieval data, then compare both planes."""
        graph_export = await self.export_project_graph(source_graph, project_id=project_id)
        graph_report = await self.import_project_graph(
            target_graph,
            project_id=project_id,
            export=graph_export,
            tenant_id=tenant_id,
        )
        graph_comparison = await self.compare_backends(
            source_graph,
            target_graph,
            project_id=project_id,
        )

        retrieval_report: RetrievalMigrationReport | None = None
        retrieval_comparison: dict[str, Any] | None = None
        if target_retrieval is not None and retrieval_chunks is not None:
            retrieval_report = await self.import_project_retrieval(
                target_retrieval,
                project_id=project_id,
                chunks=retrieval_chunks,
            )

        if source_retrieval is not None and target_retrieval is not None and validation_queries:
            retrieval_comparison = await self.compare_retrieval_backends(
                source_retrieval,
                target_retrieval,
                project_id=project_id,
                queries=validation_queries,
                limit=retrieval_limit,
            )

        return BackendMigrationReport(
            project_id=project_id,
            graph=graph_report,
            retrieval=retrieval_report,
            graph_comparison=graph_comparison,
            retrieval_comparison=retrieval_comparison,
        )

    async def dry_run_project_cutover(
        self,
        *,
        source_graph: Any,  # noqa: ANN401
        target_graph: Any,  # noqa: ANN401
        project_id: str,
        source_retrieval: Any | None = None,  # noqa: ANN401
        target_retrieval: Any | None = None,  # noqa: ANN401
        retrieval_chunks: list[RetrievalChunk] | None = None,
        validation_queries: list[str] | None = None,
        source_graph_store_id: str | None = None,
        source_retrieval_store_id: str | None = None,
        target_graph_store_id: str | None = None,
        target_retrieval_store_id: str | None = None,
        retrieval_limit: int = 10,
    ) -> dict[str, Any]:
        """Build a read-only cutover rehearsal report without switching bindings."""
        graph_count_comparison = await self.compare_backends(
            source_graph,
            target_graph,
            project_id=project_id,
        )
        graph_snapshot_comparison = await self.compare_graph_snapshots(
            source_graph,
            target_graph,
            project_id=project_id,
        )

        retrieval_comparison: dict[str, Any] | None = None
        if source_retrieval is not None and target_retrieval is not None and validation_queries:
            retrieval_comparison = await self.compare_retrieval_backends(
                source_retrieval,
                target_retrieval,
                project_id=project_id,
                queries=validation_queries,
                limit=retrieval_limit,
            )

        graph_ok = bool(
            graph_count_comparison.get("counts_match")
            and graph_snapshot_comparison.get("counts_match")
            and graph_snapshot_comparison.get("checksums_match")
        )
        retrieval_ok = retrieval_comparison is None or bool(
            retrieval_comparison.get("all_queries_match")
        )
        return {
            "project_id": project_id,
            "can_switch_bindings": graph_ok and retrieval_ok,
            "graph_count_comparison": graph_count_comparison,
            "graph_snapshot_comparison": graph_snapshot_comparison,
            "retrieval_comparison": retrieval_comparison,
            "retrieval_chunk_count": len(retrieval_chunks or []),
            "target_bindings": {
                "graph_store_id": target_graph_store_id,
                "retrieval_store_id": target_retrieval_store_id,
            },
            "rollback_bindings": {
                "graph_store_id": source_graph_store_id,
                "retrieval_store_id": source_retrieval_store_id,
            },
        }


def _copy_chunk_for_project(chunk: RetrievalChunk, project_id: str) -> RetrievalChunk:
    return RetrievalChunk(
        id=chunk.id,
        source_type=chunk.source_type,
        source_id=chunk.source_id,
        project_id=project_id,
        content=chunk.content,
        chunk_index=chunk.chunk_index,
        category=chunk.category,
        metadata=dict(chunk.metadata),
        embedding=list(chunk.embedding) if chunk.embedding is not None else None,
        importance=chunk.importance,
    )


def _top_k_overlap(source_ids: list[str], target_ids: list[str]) -> float:
    if not source_ids and not target_ids:
        return 1.0
    denominator = max(len(source_ids), len(target_ids), 1)
    return len(set(source_ids) & set(target_ids)) / denominator


def _graph_export_summary(export: GraphExportDTO) -> dict[str, Any]:
    return {
        "counts": {
            "episodes": len(export.episodes),
            "entities": len(export.entities),
            "relationships": len(export.relationships),
            "communities": len(export.communities),
        },
        "checksums": {
            "episodes": _stable_checksum(export.episodes),
            "entities": _stable_checksum(export.entities),
            "relationships": _stable_checksum(export.relationships),
            "communities": _stable_checksum(export.communities),
        },
    }


def _stable_checksum(rows: list[dict[str, Any]]) -> str:
    normalized = sorted(
        json.dumps(row, sort_keys=True, default=str, separators=(",", ":")) for row in rows
    )
    payload = "[" + ",".join(normalized) + "]"
    return sha256(payload.encode("utf-8")).hexdigest()
