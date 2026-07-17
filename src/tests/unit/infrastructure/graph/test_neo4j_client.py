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


@pytest.mark.unit
class TestNeo4jClientBatchWrites:
    def _client_with_recorder(self) -> tuple[Neo4jClient, list[tuple[str, dict[str, Any]]]]:
        client = Neo4jClient(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="password",
        )
        calls: list[tuple[str, dict[str, Any]]] = []

        async def record_execute_query(query: str, **kwargs: Any) -> object:
            calls.append((query, kwargs))
            return object()

        client.execute_query = record_execute_query  # type: ignore[method-assign]
        return client, calls

    async def test_save_nodes_batch_groups_by_labels_and_property_keys(self) -> None:
        client, calls = self._client_with_recorder()

        await client.save_nodes_batch(
            [
                {
                    "labels": ["Entity", "Person"],
                    "uuid": "n1",
                    "properties": {"uuid": "n1", "name": "Ada", "name_embedding": [0.1]},
                },
                {
                    "labels": ["Entity", "Person"],
                    "uuid": "n2",
                    "properties": {"uuid": "n2", "name": "Grace", "name_embedding": [0.2]},
                },
                {
                    "labels": ["Entity", "Organization"],
                    "uuid": "n3",
                    "properties": {"name": "Lab"},
                },
            ]
        )

        assert len(calls) == 2
        person_query, person_params = next(c for c in calls if "Entity:Person" in c[0])
        assert "UNWIND $rows AS row" in person_query
        assert "MERGE (n:Entity:Person {uuid: row.uuid})" in person_query
        assert "SET n += row.properties" in person_query
        person_rows = person_params["rows"]
        assert [row["uuid"] for row in person_rows] == ["n1", "n2"]
        # uuid is stripped from SET properties (used only by MERGE).
        assert person_rows[0]["properties"] == {"name": "Ada", "name_embedding": [0.1]}
        _org_query, org_params = next(c for c in calls if "Entity:Organization" in c[0])
        assert [row["uuid"] for row in org_params["rows"]] == ["n3"]

    async def test_save_edges_batch_groups_by_type_and_omits_set_without_properties(self) -> None:
        client, calls = self._client_with_recorder()

        await client.save_edges_batch(
            [
                {
                    "from_uuid": "e1",
                    "to_uuid": "a",
                    "relationship_type": "MENTIONS",
                    "properties": {"uuid": "edge-1"},
                },
                {
                    "from_uuid": "e1",
                    "to_uuid": "b",
                    "relationship_type": "MENTIONS",
                    "properties": {"uuid": "edge-2"},
                },
                {"from_uuid": "a", "to_uuid": "b", "relationship_type": "RELATES_TO"},
            ]
        )

        assert len(calls) == 2
        mentions_query, mentions_params = next(c for c in calls if "MENTIONS" in c[0])
        assert "SET r += row.properties" in mentions_query
        assert [(r["from_uuid"], r["to_uuid"]) for r in mentions_params["rows"]] == [
            ("e1", "a"),
            ("e1", "b"),
        ]
        relates_query, _relates_params = next(c for c in calls if "RELATES_TO" in c[0])
        assert "SET" not in relates_query

    async def test_save_nodes_batch_rejects_invalid_label(self) -> None:
        client, calls = self._client_with_recorder()

        with pytest.raises(ValueError, match="node label"):
            await client.save_nodes_batch(
                [{"labels": ["Entity; DROP"], "uuid": "n1", "properties": {}}]
            )
        assert calls == []

    async def test_save_nodes_batch_noop_for_empty_list(self) -> None:
        client, calls = self._client_with_recorder()

        await client.save_nodes_batch([])

        assert calls == []
