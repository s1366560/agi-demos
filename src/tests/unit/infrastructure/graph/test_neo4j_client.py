"""Unit tests for Neo4jClient helper behavior."""

from typing import Any

import pytest

from src.infrastructure.graph.neo4j_client import Neo4jClient


@pytest.mark.unit
class TestNeo4jClientVectorIndex:
    async def test_get_vector_index_dimension_redacts_query_failure_log(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client = Neo4jClient(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="password",
        )
        secret_index_name = "vector_index_secret_1357"
        exception_detail = "driver echoed vector-dimension-secret-2468"

        async def fail_execute_query(_query: str, **_kwargs: Any) -> object:
            raise RuntimeError(exception_detail)

        client.execute_query = fail_execute_query  # type: ignore[method-assign]

        with caplog.at_level(
            "WARNING",
            logger="src.infrastructure.graph.neo4j_client",
        ):
            result = await client.get_vector_index_dimension(secret_index_name)

        assert result is None
        assert secret_index_name not in caplog.text
        assert exception_detail not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
        assert "has_index_name=True" in caplog.text
