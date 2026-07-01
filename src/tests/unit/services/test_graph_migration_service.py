"""Unit tests for GraphMigrationService (export/import/compare)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.graph_migration_service import GraphMigrationService
from src.domain.model.graph.dtos import GraphExportDTO
from src.domain.model.retrieval_store import RetrievalChunk, RetrievalSearchResult


def _store(counts=None, export=None, add_episode=None):
    s = MagicMock()
    s.data_export = AsyncMock(return_value=export or GraphExportDTO(exported_at="t", tenant_id=None, project_id=None))
    if counts:
        count_values = iter(counts)

        async def _next_count(*_args, **_kwargs):
            return next(count_values)

        s.count_nodes = AsyncMock(side_effect=_next_count)
    else:
        s.count_nodes = AsyncMock(return_value=0)
    s.add_episode = add_episode or AsyncMock()
    return s


def _export_with(episodes=None, entities=None, relationships=None, communities=None):
    return GraphExportDTO(
        exported_at="t",
        tenant_id="tn",
        project_id="p1",
        episodes=episodes or [],
        entities=entities or [],
        relationships=relationships or [],
        communities=communities or [],
    )


@pytest.mark.unit
class TestGraphMigrationService:
    @pytest.mark.asyncio
    async def test_export_delegates_to_source(self) -> None:
        source = _store(export=_export_with(episodes=[{"uuid": "e1", "content": "x"}]))
        svc = GraphMigrationService()
        export = await svc.export_project_graph(source, project_id="p1")
        assert source.data_export.await_args.kwargs["project_id"] == "p1"
        assert len(export.episodes) == 1

    @pytest.mark.asyncio
    async def test_import_writes_episodes_and_counts_carried(self) -> None:
        target = _store(add_episode=AsyncMock())
        export = _export_with(
            episodes=[
                {"uuid": "e1", "content": "hello", "name": "ep1", "memory_id": "m1"},
                {"uuid": "e2", "content": "world"},
            ],
            entities=[{"uuid": "x"}],
            relationships=[{"edge_id": "r1"}],
            communities=[{"uuid": "c1"}],
        )
        svc = GraphMigrationService()
        report = await svc.import_project_graph(
            target, project_id="p1", export=export, tenant_id="tn"
        )
        assert report.episodes_imported == 2
        assert target.add_episode.await_count == 2
        assert report.entities_imported == 1
        assert report.relationships_imported == 1
        assert report.communities_imported == 1
        assert report.errors == []

    @pytest.mark.asyncio
    async def test_import_records_episode_errors(self) -> None:
        target = MagicMock()
        target.add_episode = AsyncMock(side_effect=RuntimeError("boom"))
        export = _export_with(episodes=[{"uuid": "e1", "content": "x"}])
        svc = GraphMigrationService()
        report = await svc.import_project_graph(target, project_id="p1", export=export)
        assert report.episodes_imported == 0
        assert len(report.errors) == 1
        assert "boom" in report.errors[0]

    @pytest.mark.asyncio
    async def test_compare_backends_reports_counts_match(self) -> None:
        source = MagicMock()
        source.count_nodes = AsyncMock(side_effect=[10, 5, 2])  # entity, episode, community
        target = MagicMock()
        target.count_nodes = AsyncMock(side_effect=[10, 5, 2])
        svc = GraphMigrationService()
        result = await svc.compare_backends(source, target, project_id="p1")
        assert result["counts_match"] is True
        assert result["source"]["entities"] == 10

    @pytest.mark.asyncio
    async def test_compare_backends_reports_mismatch(self) -> None:
        source = MagicMock()
        source.count_nodes = AsyncMock(side_effect=[10, 5, 2])
        target = MagicMock()
        target.count_nodes = AsyncMock(side_effect=[9, 5, 2])
        svc = GraphMigrationService()
        result = await svc.compare_backends(source, target, project_id="p1")
        assert result["counts_match"] is False

    @pytest.mark.asyncio
    async def test_import_project_retrieval_indexes_chunks(self) -> None:
        target = MagicMock()
        target.index_chunks = AsyncMock(return_value=2)
        chunks = [
            RetrievalChunk(source_type="memory", source_id="m1", project_id="p1", content="a"),
            RetrievalChunk(source_type="memory", source_id="m2", project_id="other", content="b"),
        ]
        svc = GraphMigrationService()

        report = await svc.import_project_retrieval(target, project_id="p1", chunks=chunks)

        assert report.chunks_imported == 2
        indexed = target.index_chunks.await_args.args[0]
        assert [chunk.project_id for chunk in indexed] == ["p1", "p1"]

    @pytest.mark.asyncio
    async def test_compare_retrieval_backends_reports_top_k_overlap(self) -> None:
        source = MagicMock()
        source.hybrid_search = AsyncMock(
            return_value=[
                RetrievalSearchResult(id="a", content="A", score=1.0),
                RetrievalSearchResult(id="b", content="B", score=0.9),
            ]
        )
        target = MagicMock()
        target.hybrid_search = AsyncMock(
            return_value=[
                RetrievalSearchResult(id="b", content="B", score=1.0),
                RetrievalSearchResult(id="c", content="C", score=0.8),
            ]
        )
        svc = GraphMigrationService()

        result = await svc.compare_retrieval_backends(
            source,
            target,
            project_id="p1",
            queries=["hello"],
            limit=2,
        )

        assert result["queries"][0]["overlap"] == 0.5
        assert result["all_queries_match"] is False

    @pytest.mark.asyncio
    async def test_migrate_project_backends_combines_graph_and_retrieval(self) -> None:
        source_graph = MagicMock()
        source_graph.data_export = AsyncMock(return_value=_export_with(episodes=[]))
        source_graph.count_nodes = AsyncMock(side_effect=[0, 0, 0])
        target_graph = MagicMock()
        target_graph.add_episode = AsyncMock()
        target_graph.count_nodes = AsyncMock(side_effect=[0, 0, 0])
        source_retrieval = MagicMock()
        source_retrieval.hybrid_search = AsyncMock(
            return_value=[RetrievalSearchResult(id="a", content="A", score=1.0)]
        )
        target_retrieval = MagicMock()
        target_retrieval.index_chunks = AsyncMock(return_value=1)
        target_retrieval.hybrid_search = AsyncMock(
            return_value=[RetrievalSearchResult(id="a", content="A", score=1.0)]
        )
        svc = GraphMigrationService()

        report = await svc.migrate_project_backends(
            source_graph=source_graph,
            target_graph=target_graph,
            source_retrieval=source_retrieval,
            target_retrieval=target_retrieval,
            project_id="p1",
            retrieval_chunks=[
                RetrievalChunk(
                    source_type="memory",
                    source_id="m1",
                    project_id="p1",
                    content="chunk",
                )
            ],
            validation_queries=["chunk"],
        )

        assert report.graph.project_id == "p1"
        assert report.retrieval is not None
        assert report.retrieval.chunks_imported == 1
        assert report.retrieval_comparison is not None
        assert report.retrieval_comparison["all_queries_match"] is True

    @pytest.mark.asyncio
    async def test_compare_graph_snapshots_reports_checksum_match(self) -> None:
        source = _store(
            export=_export_with(
                episodes=[{"uuid": "e1", "content": "hello"}],
                entities=[{"uuid": "n1", "name": "Node"}],
            )
        )
        target = _store(
            export=_export_with(
                episodes=[{"content": "hello", "uuid": "e1"}],
                entities=[{"name": "Node", "uuid": "n1"}],
            )
        )
        svc = GraphMigrationService()

        result = await svc.compare_graph_snapshots(source, target, project_id="p1")

        assert result["counts_match"] is True
        assert result["checksums_match"] is True

    @pytest.mark.asyncio
    async def test_dry_run_project_cutover_reports_switch_and_rollback_bindings(self) -> None:
        export = _export_with(
            episodes=[{"uuid": "e1", "content": "hello"}],
            entities=[{"uuid": "n1"}],
        )
        source_graph = _store(counts=[1, 1, 0], export=export)
        target_graph = _store(counts=[1, 1, 0], export=export)
        source_retrieval = MagicMock()
        source_retrieval.hybrid_search = AsyncMock(
            return_value=[RetrievalSearchResult(id="chunk-1", content="A", score=1.0)]
        )
        target_retrieval = MagicMock()
        target_retrieval.hybrid_search = AsyncMock(
            return_value=[RetrievalSearchResult(id="chunk-1", content="A", score=1.0)]
        )
        svc = GraphMigrationService()

        result = await svc.dry_run_project_cutover(
            source_graph=source_graph,
            target_graph=target_graph,
            source_retrieval=source_retrieval,
            target_retrieval=target_retrieval,
            project_id="p1",
            retrieval_chunks=[
                RetrievalChunk(source_type="memory", source_id="m1", project_id="p1", content="A")
            ],
            validation_queries=["A"],
            source_graph_store_id="old-graph",
            source_retrieval_store_id="old-retrieval",
            target_graph_store_id="new-graph",
            target_retrieval_store_id="new-retrieval",
        )

        assert result["can_switch_bindings"] is True
        assert result["retrieval_chunk_count"] == 1
        assert result["target_bindings"] == {
            "graph_store_id": "new-graph",
            "retrieval_store_id": "new-retrieval",
        }
        assert result["rollback_bindings"] == {
            "graph_store_id": "old-graph",
            "retrieval_store_id": "old-retrieval",
        }

    @pytest.mark.asyncio
    async def test_dry_run_project_cutover_blocks_switch_on_checksum_mismatch(self) -> None:
        source_graph = _store(
            counts=[1, 1, 0],
            export=_export_with(episodes=[{"uuid": "e1", "content": "source"}]),
        )
        target_graph = _store(
            counts=[1, 1, 0],
            export=_export_with(episodes=[{"uuid": "e1", "content": "target"}]),
        )
        svc = GraphMigrationService()

        result = await svc.dry_run_project_cutover(
            source_graph=source_graph,
            target_graph=target_graph,
            project_id="p1",
        )

        assert result["can_switch_bindings"] is False
        assert result["graph_snapshot_comparison"]["checksums_match"] is False
