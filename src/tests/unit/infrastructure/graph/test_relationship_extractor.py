"""Unit tests for RelationshipExtractor (Graphiti-compatible edge type validation)."""

import pytest

from src.infrastructure.graph.extraction.relationship_extractor import (
    RelationshipDeduplicator,
    RelationshipExtractor,
)


class MockLLMClient:
    """Mock LLM client for testing."""

    async def generate_response(self, **_kwargs):
        return '{"relationships": []}'


class GenerateOnlyLLMClient:
    """Mock the default project LLM client response shape."""

    async def generate(self, **_kwargs):
        return {
            "content": (
                '{"relationships": ['
                '{"from_entity": "Ada", "to_entity": "Lab", "relationship_type": "FOUNDED"}'
                "]}"
            )
        }


class FailingLLMClient:
    """Mock LLM client that raises a provider-style error."""

    async def generate_response(self, **_kwargs):
        raise RuntimeError("provider echoed relationship-secret-2468")


class FailingNeo4jClient:
    """Mock Neo4j client that raises a provider-style error."""

    async def execute_query(self, *_args, **_kwargs):
        raise RuntimeError("provider echoed existing-edge-secret-8642")


@pytest.fixture
def extractor():
    """Create RelationshipExtractor with mocked dependencies."""
    return RelationshipExtractor(llm_client=MockLLMClient())


@pytest.mark.unit
class TestRelationshipExtractorLLMResponse:
    """Tests for LLM response normalization."""

    async def test_call_llm_extracts_content_from_generate_dict(self):
        extractor = RelationshipExtractor(llm_client=GenerateOnlyLLMClient())

        response = await extractor._call_llm("Extract relationships", "Ada founded a lab.")

        assert '"relationships"' in response
        assert '"relationship_type": "FOUNDED"' in response

    async def test_extract_redacts_llm_exception_details(self, caplog):
        extractor = RelationshipExtractor(llm_client=FailingLLMClient())
        entities = [
            {"name": "Ada", "entity_type": "Person", "uuid": "ada-1"},
            {"name": "Lab", "entity_type": "Organization", "uuid": "lab-1"},
        ]

        with caplog.at_level(
            "ERROR",
            logger="src.infrastructure.graph.extraction.relationship_extractor",
        ):
            result = await extractor.extract("Ada founded relationship-secret-2468", entities)

        assert result == []
        assert "relationship-secret-2468" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text


@pytest.mark.unit
class TestRelationshipExtractorDatetime:
    """Tests for relationship datetime parsing."""

    def test_parse_datetime_redacts_invalid_input(self, extractor, caplog):
        """Invalid datetime debug logs should not include raw extracted values."""
        secret = "relationship-datetime-secret-1357"

        with caplog.at_level(
            "DEBUG",
            logger="src.infrastructure.graph.extraction.relationship_extractor",
        ):
            result = extractor._parse_datetime(f"invalid-{secret}")

        assert result is None
        assert secret not in caplog.text
        assert "error_type=ValueError" in caplog.text


@pytest.mark.unit
class TestEdgeTypeValidation:
    """Tests for _validate_edge_type method (Graphiti-compatible)."""

    def test_validate_allowed_type_returns_original(self, extractor):
        """Allowed edge type should be returned unchanged."""
        edge_type_map = {
            ("Person", "Organization"): ["WORKS_AT", "FOUNDED", "LEADS"],
        }

        result = extractor._validate_edge_type(
            relationship_type="WORKS_AT",
            source_entity_type="Person",
            target_entity_type="Organization",
            edge_type_map=edge_type_map,
        )

        assert result == "WORKS_AT"

    def test_validate_disallowed_type_falls_back_to_relates_to(self, extractor):
        """Disallowed edge type should fall back to RELATES_TO."""
        edge_type_map = {
            ("Person", "Organization"): ["WORKS_AT", "FOUNDED"],
        }

        result = extractor._validate_edge_type(
            relationship_type="LOVES",  # Not in allowed list
            source_entity_type="Person",
            target_entity_type="Organization",
            edge_type_map=edge_type_map,
        )

        assert result == "RELATES_TO"

    def test_validate_no_constraints_keeps_original(self, extractor):
        """When no constraints exist for type pair, keep original type."""
        edge_type_map = {
            ("Person", "Organization"): ["WORKS_AT"],
            # No constraints for Location -> Event
        }

        result = extractor._validate_edge_type(
            relationship_type="HAPPENED_AT",
            source_entity_type="Location",
            target_entity_type="Event",
            edge_type_map=edge_type_map,
        )

        # No constraints for this pair, keep original
        assert result == "HAPPENED_AT"

    def test_validate_empty_edge_type_map_keeps_original(self, extractor):
        """Empty edge_type_map should keep original type."""
        edge_type_map = {}

        result = extractor._validate_edge_type(
            relationship_type="CUSTOM_RELATION",
            source_entity_type="Person",
            target_entity_type="Concept",
            edge_type_map=edge_type_map,
        )

        assert result == "CUSTOM_RELATION"

    def test_validate_checks_entity_fallback_signatures(self, extractor):
        """Should check (source, Entity), (Entity, target), (Entity, Entity) fallbacks."""
        edge_type_map = {
            # No specific (Person, Organization) constraint
            ("Person", "Entity"): ["KNOWS", "INTERACTS_WITH"],  # Fallback
        }

        result = extractor._validate_edge_type(
            relationship_type="KNOWS",
            source_entity_type="Person",
            target_entity_type="Organization",  # Not exact match
            edge_type_map=edge_type_map,
        )

        # Should match via (Person, Entity) fallback
        assert result == "KNOWS"

    def test_validate_fallback_to_entity_entity(self, extractor):
        """Should fall back to (Entity, Entity) as most general constraint."""
        edge_type_map = {
            ("Entity", "Entity"): ["RELATES_TO", "CONNECTED_TO"],
        }

        result = extractor._validate_edge_type(
            relationship_type="CONNECTED_TO",
            source_entity_type="CustomType1",
            target_entity_type="CustomType2",
            edge_type_map=edge_type_map,
        )

        # Should match via (Entity, Entity) fallback
        assert result == "CONNECTED_TO"

    def test_validate_combines_allowed_types_from_all_signatures(self, extractor):
        """Should combine allowed types from all matching signatures."""
        edge_type_map = {
            ("Person", "Organization"): ["WORKS_AT"],
            ("Person", "Entity"): ["KNOWS"],
            ("Entity", "Organization"): ["TARGETS"],
            ("Entity", "Entity"): ["RELATES_TO"],
        }

        # WORKS_AT is in specific (Person, Organization)
        result1 = extractor._validate_edge_type("WORKS_AT", "Person", "Organization", edge_type_map)
        assert result1 == "WORKS_AT"

        # KNOWS is in (Person, Entity) which applies to Person -> anything
        result2 = extractor._validate_edge_type("KNOWS", "Person", "Organization", edge_type_map)
        assert result2 == "KNOWS"

        # TARGETS is in (Entity, Organization) which applies
        result3 = extractor._validate_edge_type("TARGETS", "Person", "Organization", edge_type_map)
        assert result3 == "TARGETS"

        # RELATES_TO is in (Entity, Entity) which always applies
        result4 = extractor._validate_edge_type(
            "RELATES_TO", "Person", "Organization", edge_type_map
        )
        assert result4 == "RELATES_TO"

        # UNKNOWN is not in any, should fall back to RELATES_TO
        result5 = extractor._validate_edge_type("UNKNOWN", "Person", "Organization", edge_type_map)
        assert result5 == "RELATES_TO"

    def test_validate_case_sensitive_matching(self, extractor):
        """Edge type matching should be case-sensitive."""
        edge_type_map = {
            ("Person", "Organization"): ["WORKS_AT"],
        }

        # Lowercase should not match
        result = extractor._validate_edge_type(
            relationship_type="works_at",  # lowercase
            source_entity_type="Person",
            target_entity_type="Organization",
            edge_type_map=edge_type_map,
        )

        # Not in allowed list (case mismatch), falls back
        assert result == "RELATES_TO"


@pytest.mark.unit
class TestRelationshipTypeNormalization:
    """Tests for _normalize_relationship_type method."""

    def test_normalize_spaces_to_underscores(self, extractor):
        """Spaces should become underscores."""
        result = extractor._normalize_relationship_type("works at")
        assert result == "WORKS_AT"

    def test_normalize_to_uppercase(self, extractor):
        """Result should be uppercase."""
        result = extractor._normalize_relationship_type("works_at")
        assert result == "WORKS_AT"

    def test_normalize_removes_special_characters(self, extractor):
        """Special characters should be removed."""
        result = extractor._normalize_relationship_type("works-at!")
        assert result == "WORKSAT"

    def test_normalize_empty_string_returns_default(self, extractor):
        """Empty string should return RELATED_TO."""
        result = extractor._normalize_relationship_type("")
        assert result == "RELATED_TO"

    def test_normalize_preserves_existing_format(self, extractor):
        """Already normalized type should be unchanged."""
        result = extractor._normalize_relationship_type("WORKS_AT")
        assert result == "WORKS_AT"

    def test_normalize_mixed_case(self, extractor):
        """Mixed case should become uppercase."""
        result = extractor._normalize_relationship_type("WorksAt")
        assert result == "WORKSAT"


@pytest.mark.unit
class TestCreateEntityEdges:
    """Tests for _create_entity_edges with edge_type_map validation."""

    def test_create_edges_with_validation(self, extractor):
        """Should validate edge types during creation."""
        relationships_data = [
            {
                "from_entity": "John",
                "to_entity": "Acme Corp",
                "relationship_type": "WORKS_AT",
                "weight": 0.8,
            }
        ]
        entity_map = {"John": "uuid-1", "Acme Corp": "uuid-2"}
        entity_type_map = {"John": "Person", "Acme Corp": "Organization"}
        edge_type_map = {("Person", "Organization"): ["WORKS_AT", "FOUNDED"]}

        edges = extractor._create_entity_edges(
            relationships_data=relationships_data,
            entity_map=entity_map,
            entity_type_map=entity_type_map,
            edge_type_map=edge_type_map,
            episode_uuid="ep-1",
        )

        assert len(edges) == 1
        assert edges[0].relationship_type == "WORKS_AT"

    def test_create_edges_fallback_to_relates_to(self, extractor):
        """Should fall back to RELATES_TO for disallowed types."""
        relationships_data = [
            {
                "from_entity": "John",
                "to_entity": "Acme Corp",
                "relationship_type": "LOVES",  # Not allowed
            }
        ]
        entity_map = {"John": "uuid-1", "Acme Corp": "uuid-2"}
        entity_type_map = {"John": "Person", "Acme Corp": "Organization"}
        edge_type_map = {("Person", "Organization"): ["WORKS_AT"]}

        edges = extractor._create_entity_edges(
            relationships_data=relationships_data,
            entity_map=entity_map,
            entity_type_map=entity_type_map,
            edge_type_map=edge_type_map,
        )

        assert len(edges) == 1
        assert edges[0].relationship_type == "RELATES_TO"

    def test_create_edges_without_constraints(self, extractor):
        """Should keep original type when no constraints."""
        relationships_data = [
            {
                "from_entity": "John",
                "to_entity": "Acme Corp",
                "relationship_type": "custom_relation",
            }
        ]
        entity_map = {"John": "uuid-1", "Acme Corp": "uuid-2"}
        entity_type_map = {"John": "Person", "Acme Corp": "Organization"}
        edge_type_map = None  # No constraints

        edges = extractor._create_entity_edges(
            relationships_data=relationships_data,
            entity_map=entity_map,
            entity_type_map=entity_type_map,
            edge_type_map=edge_type_map,
        )

        assert len(edges) == 1
        # Should be normalized but kept
        assert edges[0].relationship_type == "CUSTOM_RELATION"

    def test_create_edges_redacts_missing_entity_relationship_data(self, extractor, caplog):
        """Missing-entity relationships should not write raw relationship payloads to logs."""
        secret = "relationship-missing-secret-9753"
        relationships_data = [
            {
                "from_entity": "",
                "to_entity": f"Target {secret}",
                "relationship_type": "KNOWS",
                "fact": f"Sensitive fact {secret}",
            }
        ]

        with caplog.at_level(
            "WARNING",
            logger="src.infrastructure.graph.extraction.relationship_extractor",
        ):
            edges = extractor._create_entity_edges(
                relationships_data=relationships_data,
                entity_map={},
            )

        assert edges == []
        assert secret not in caplog.text
        assert "from_entity_present=False" in caplog.text
        assert "to_entity_present=True" in caplog.text


@pytest.mark.unit
class TestRelationshipDeduplicator:
    """Tests for relationship deduplication fallback behavior."""

    async def test_get_existing_edges_redacts_query_exception_details(self, caplog):
        deduplicator = RelationshipDeduplicator(neo4j_client=FailingNeo4jClient())

        with caplog.at_level(
            "ERROR",
            logger="src.infrastructure.graph.extraction.relationship_extractor",
        ):
            result = await deduplicator._get_existing_edges("project-1")

        assert result == []
        assert "existing-edge-secret-8642" not in caplog.text
        assert "error_type=RuntimeError" in caplog.text
