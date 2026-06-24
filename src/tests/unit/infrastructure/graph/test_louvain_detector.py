"""Unit tests for LouvainDetector."""

import pytest

from src.infrastructure.graph.community.louvain_detector import LouvainDetector


class FailingNeo4jClient:
    """Neo4j client that raises while fetching graph data."""

    async def execute_query(self, *_args, **_kwargs):
        raise RuntimeError("provider echoed louvain-fetch-secret-2468")


class GraphDataNeo4jClient:
    """Neo4j client that returns enough graph data for Louvain execution."""

    def __init__(self) -> None:
        self._calls = 0

    async def execute_query(self, *_args, **_kwargs):
        class Result:
            def __init__(self, records):
                self.records = records

        self._calls += 1
        if self._calls == 1:
            return Result(
                [
                    {"uuid": "entity-1", "name": "Ada"},
                    {"uuid": "entity-2", "name": "Lab"},
                ]
            )
        return Result([{"source": "entity-1", "target": "entity-2", "weight": 1.0}])


@pytest.mark.unit
class TestLouvainDetector:
    async def test_detect_with_networkx_redacts_fetch_exception(self, caplog):
        detector = LouvainDetector(neo4j_client=FailingNeo4jClient(), use_gds=False)

        with caplog.at_level(
            "ERROR",
            logger="src.infrastructure.graph.community.louvain_detector",
        ):
            result = await detector._detect_with_networkx("project-1", "tenant-1")

        assert result == []
        assert "louvain-fetch-secret-2468" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text

    async def test_detect_with_networkx_redacts_algorithm_exception(self, caplog, monkeypatch):
        detector = LouvainDetector(neo4j_client=GraphDataNeo4jClient(), use_gds=False)

        def fail_louvain(*_args, **_kwargs):
            raise RuntimeError("provider echoed louvain-algorithm-secret-1357")

        monkeypatch.setattr("networkx.algorithms.community.louvain_communities", fail_louvain)

        with caplog.at_level(
            "ERROR",
            logger="src.infrastructure.graph.community.louvain_detector",
        ):
            result = await detector._detect_with_networkx("project-1", "tenant-1")

        assert result == []
        assert "louvain-algorithm-secret-1357" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
