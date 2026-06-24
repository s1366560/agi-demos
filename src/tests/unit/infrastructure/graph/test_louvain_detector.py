"""Unit tests for LouvainDetector."""

import pytest

from src.infrastructure.graph.community.louvain_detector import LouvainDetector


class FailingNeo4jClient:
    """Neo4j client that raises while fetching graph data."""

    async def execute_query(self, *_args, **_kwargs):
        raise RuntimeError("provider echoed louvain-fetch-secret-2468")


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
