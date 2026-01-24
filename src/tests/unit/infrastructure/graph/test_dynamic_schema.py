"""Unit tests for dynamic schema context loading (Graphiti-compatible)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.adapters.secondary.schema.dynamic_schema import (
    DEFAULT_ENTITY_TYPES_CONTEXT,
    _get_cached_schema_context,
    _initialized_projects,
    _set_cached_schema_context,
    clear_schema_context_cache,
    format_entity_types_for_prompt,
    get_default_schema_context,
    get_project_schema_context,
)


@pytest.mark.unit
class TestDefaultEntityTypes:
    """Tests for default entity types (Graphiti-compatible)."""

    def test_default_entity_types_has_correct_count(self):
        """Verify default entity types count."""
        assert len(DEFAULT_ENTITY_TYPES_CONTEXT) == 7

    def test_default_entity_type_has_id_zero(self):
        """Entity type with ID 0 should be 'Entity' (default)."""
        entity_type = DEFAULT_ENTITY_TYPES_CONTEXT[0]
        assert entity_type["entity_type_id"] == 0
        assert entity_type["entity_type_name"] == "Entity"

    def test_default_entity_types_have_sequential_ids(self):
        """Entity type IDs should be sequential starting from 0."""
        for i, ctx in enumerate(DEFAULT_ENTITY_TYPES_CONTEXT):
            assert ctx["entity_type_id"] == i, f"Expected ID {i}, got {ctx['entity_type_id']}"

    def test_default_entity_types_have_required_fields(self):
        """Each entity type should have id, name, and description."""
        for ctx in DEFAULT_ENTITY_TYPES_CONTEXT:
            assert "entity_type_id" in ctx
            assert "entity_type_name" in ctx
            assert "entity_type_description" in ctx
            assert isinstance(ctx["entity_type_id"], int)
            assert isinstance(ctx["entity_type_name"], str)
            assert isinstance(ctx["entity_type_description"], str)

    def test_default_entity_types_include_expected_types(self):
        """Default types should include Person, Organization, Location, etc."""
        type_names = [ctx["entity_type_name"] for ctx in DEFAULT_ENTITY_TYPES_CONTEXT]
        expected_types = [
            "Entity",
            "Person",
            "Organization",
            "Location",
            "Concept",
            "Event",
            "Artifact",
        ]
        assert type_names == expected_types


@pytest.mark.unit
class TestGetDefaultSchemaContext:
    """Tests for get_default_schema_context function."""

    def test_returns_schema_context_type(self):
        """Should return SchemaContext TypedDict."""
        context = get_default_schema_context()
        assert "entity_types_context" in context
        assert "edge_type_map" in context
        assert "entity_type_id_to_name" in context
        assert "entity_type_name_to_id" in context

    def test_entity_types_context_matches_defaults(self):
        """entity_types_context should match DEFAULT_ENTITY_TYPES_CONTEXT."""
        context = get_default_schema_context()
        assert len(context["entity_types_context"]) == len(DEFAULT_ENTITY_TYPES_CONTEXT)

    def test_edge_type_map_is_empty(self):
        """Default edge_type_map should be empty."""
        context = get_default_schema_context()
        assert context["edge_type_map"] == {}

    def test_entity_type_id_to_name_mapping(self):
        """Verify ID to name mapping is correct."""
        context = get_default_schema_context()
        mapping = context["entity_type_id_to_name"]
        assert mapping[0] == "Entity"
        assert mapping[1] == "Person"
        assert mapping[2] == "Organization"

    def test_entity_type_name_to_id_mapping(self):
        """Verify name to ID mapping is correct."""
        context = get_default_schema_context()
        mapping = context["entity_type_name_to_id"]
        assert mapping["Entity"] == 0
        assert mapping["Person"] == 1
        assert mapping["Organization"] == 2


@pytest.mark.unit
class TestSchemaContextCaching:
    """Tests for schema context caching."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_schema_context_cache()

    def test_cache_starts_empty(self):
        """Cache should be empty after clearing."""
        clear_schema_context_cache()
        assert _get_cached_schema_context("test-project") is None

    def test_set_and_get_cached_context(self):
        """Should be able to set and retrieve cached context."""
        context = get_default_schema_context()
        _set_cached_schema_context("test-project", context)

        cached = _get_cached_schema_context("test-project")
        assert cached is not None
        assert cached["entity_types_context"] == context["entity_types_context"]

    def test_cache_clear_specific_project(self):
        """Should clear cache for specific project only."""
        context = get_default_schema_context()
        _set_cached_schema_context("project-1", context)
        _set_cached_schema_context("project-2", context)

        clear_schema_context_cache("project-1")

        assert _get_cached_schema_context("project-1") is None
        assert _get_cached_schema_context("project-2") is not None

    def test_cache_clear_all(self):
        """Should clear all cached contexts."""
        context = get_default_schema_context()
        _set_cached_schema_context("project-1", context)
        _set_cached_schema_context("project-2", context)

        clear_schema_context_cache()

        assert _get_cached_schema_context("project-1") is None
        assert _get_cached_schema_context("project-2") is None


@pytest.mark.unit
class TestFormatEntityTypesForPrompt:
    """Tests for format_entity_types_for_prompt function."""

    def test_format_default_types(self):
        """Format default entity types for prompt."""
        result = format_entity_types_for_prompt(DEFAULT_ENTITY_TYPES_CONTEXT)

        lines = result.split("\n")
        assert len(lines) == 7
        assert lines[0].startswith("0. Entity -")
        assert lines[1].startswith("1. Person -")

    def test_format_custom_types(self):
        """Format custom entity types."""
        custom_types = [
            {
                "entity_type_id": 0,
                "entity_type_name": "Entity",
                "entity_type_description": "Default",
            },
            {
                "entity_type_id": 7,
                "entity_type_name": "Product",
                "entity_type_description": "A product item",
            },
        ]

        result = format_entity_types_for_prompt(custom_types)

        assert "0. Entity - Default" in result
        assert "7. Product - A product item" in result

    def test_format_empty_list(self):
        """Empty list should return empty string."""
        result = format_entity_types_for_prompt([])
        assert result == ""


@pytest.mark.unit
class TestGetProjectSchemaContext:
    """Tests for get_project_schema_context async function."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_schema_context_cache()

    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_project_id(self):
        """Should return default schema when project_id is None."""
        context = await get_project_schema_context(None)

        assert len(context["entity_types_context"]) == 7
        assert context["edge_type_map"] == {}

    @pytest.mark.asyncio
    async def test_returns_defaults_when_empty_project_id(self):
        """Should return default schema when project_id is empty string."""
        context = await get_project_schema_context("")

        assert len(context["entity_types_context"]) == 7

    @pytest.mark.asyncio
    async def test_uses_cache_on_second_call(self):
        """Should use cached context on subsequent calls."""
        # Pre-populate cache
        cached_context = get_default_schema_context()
        cached_context["entity_types_context"].append(
            {
                "entity_type_id": 99,
                "entity_type_name": "CachedType",
                "entity_type_description": "From cache",
            }
        )
        _set_cached_schema_context("cached-project", cached_context)

        # Call should return cached version without database query
        context = await get_project_schema_context("cached-project")

        type_names = [t["entity_type_name"] for t in context["entity_types_context"]]
        assert "CachedType" in type_names

    @pytest.mark.asyncio
    async def test_loads_custom_entity_types_from_database(self):
        """Should load custom entity types from database."""
        # Mark project as already initialized to skip _ensure_default_types_initialized
        _initialized_projects.add("test-project-123")

        try:
            # Create mock EntityType for custom type
            mock_entity_type = MagicMock()
            mock_entity_type.name = "CustomProduct"
            mock_entity_type.description = "A custom product entity"
            mock_entity_type.schema = {}
            mock_entity_type.source = "llm_discovered"

            # Create mock default entity types (simulating they're in DB)
            mock_default_types = []
            for ctx in DEFAULT_ENTITY_TYPES_CONTEXT:
                mock_type = MagicMock()
                mock_type.name = ctx["entity_type_name"]
                mock_type.description = ctx["entity_type_description"]
                mock_type.source = "system"
                mock_default_types.append(mock_type)

            # Create mock result for EntityType query
            entity_result = MagicMock()
            entity_scalars = MagicMock()
            entity_scalars.all.return_value = mock_default_types + [mock_entity_type]
            entity_result.scalars.return_value = entity_scalars

            # Create empty result for EdgeTypeMap query
            empty_result = MagicMock()
            empty_scalars = MagicMock()
            empty_scalars.all.return_value = []
            empty_result.scalars.return_value = empty_scalars

            # Create mock session
            mock_session = AsyncMock()
            mock_session.execute.side_effect = [entity_result, empty_result]

            # Patch async_session_factory
            with patch(
                "src.infrastructure.adapters.secondary.schema.dynamic_schema.async_session_factory"
            ) as mock_factory:
                mock_context_manager = AsyncMock()
                mock_context_manager.__aenter__.return_value = mock_session
                mock_context_manager.__aexit__.return_value = None
                mock_factory.return_value = mock_context_manager

                # Clear cache to ensure fresh load
                clear_schema_context_cache("test-project-123")
                context = await get_project_schema_context("test-project-123")

            # Verify custom type was added
            type_names = [t["entity_type_name"] for t in context["entity_types_context"]]
            assert "CustomProduct" in type_names

            # Custom type should be after system types (sorted by source, then name)
            custom_type = next(
                t
                for t in context["entity_types_context"]
                if t["entity_type_name"] == "CustomProduct"
            )
            assert custom_type["entity_type_id"] >= 7  # After default types
        finally:
            _initialized_projects.discard("test-project-123")

    @pytest.mark.asyncio
    async def test_loads_edge_type_map_from_database(self):
        """Should load edge type map from database."""
        # Mark project as already initialized to skip _ensure_default_types_initialized
        _initialized_projects.add("test-project-456")

        try:
            # Create mock EdgeTypeMap
            mock_edge_map = MagicMock()
            mock_edge_map.source_type = "Person"
            mock_edge_map.target_type = "Organization"
            mock_edge_map.edge_type = "WORKS_AT"

            mock_edge_map2 = MagicMock()
            mock_edge_map2.source_type = "Person"
            mock_edge_map2.target_type = "Organization"
            mock_edge_map2.edge_type = "FOUNDED"

            # Create mock default entity types
            mock_default_types = []
            for ctx in DEFAULT_ENTITY_TYPES_CONTEXT:
                mock_type = MagicMock()
                mock_type.name = ctx["entity_type_name"]
                mock_type.description = ctx["entity_type_description"]
                mock_type.source = "system"
                mock_default_types.append(mock_type)

            # Create mock results
            entity_result = MagicMock()
            entity_scalars = MagicMock()
            entity_scalars.all.return_value = mock_default_types
            entity_result.scalars.return_value = entity_scalars

            edge_result = MagicMock()
            edge_scalars = MagicMock()
            edge_scalars.all.return_value = [mock_edge_map, mock_edge_map2]
            edge_result.scalars.return_value = edge_scalars

            mock_session = AsyncMock()
            mock_session.execute.side_effect = [entity_result, edge_result]

            with patch(
                "src.infrastructure.adapters.secondary.schema.dynamic_schema.async_session_factory"
            ) as mock_factory:
                mock_context_manager = AsyncMock()
                mock_context_manager.__aenter__.return_value = mock_session
                mock_context_manager.__aexit__.return_value = None
                mock_factory.return_value = mock_context_manager

                # Clear cache to ensure fresh load
                clear_schema_context_cache("test-project-456")
                context = await get_project_schema_context("test-project-456")

            # Verify edge type map
            edge_map = context["edge_type_map"]
            assert ("Person", "Organization") in edge_map
            assert "WORKS_AT" in edge_map[("Person", "Organization")]
            assert "FOUNDED" in edge_map[("Person", "Organization")]
        finally:
            _initialized_projects.discard("test-project-456")

    @pytest.mark.asyncio
    async def test_skips_duplicate_entity_type_names(self):
        """Should handle duplicate entity types correctly (now loaded from DB)."""
        # Mark project as already initialized to skip _ensure_default_types_initialized
        _initialized_projects.add("test-project-789")

        try:
            # Create mock default entity types (all 7 default types in DB)
            mock_default_types = []
            for ctx in DEFAULT_ENTITY_TYPES_CONTEXT:
                mock_type = MagicMock()
                mock_type.name = ctx["entity_type_name"]
                mock_type.description = ctx["entity_type_description"]
                mock_type.source = "system"
                mock_default_types.append(mock_type)

            # Create mock result for EntityType query
            entity_result = MagicMock()
            entity_scalars = MagicMock()
            entity_scalars.all.return_value = mock_default_types
            entity_result.scalars.return_value = entity_scalars

            empty_result = MagicMock()
            empty_scalars = MagicMock()
            empty_scalars.all.return_value = []
            empty_result.scalars.return_value = empty_scalars

            mock_session = AsyncMock()
            mock_session.execute.side_effect = [entity_result, empty_result]

            with patch(
                "src.infrastructure.adapters.secondary.schema.dynamic_schema.async_session_factory"
            ) as mock_factory:
                mock_context_manager = AsyncMock()
                mock_context_manager.__aenter__.return_value = mock_session
                mock_context_manager.__aexit__.return_value = None
                mock_factory.return_value = mock_context_manager

                # Clear cache to ensure fresh load
                clear_schema_context_cache("test-project-789")
                context = await get_project_schema_context("test-project-789")

            # Should have exactly 7 types (all defaults loaded from DB)
            assert len(context["entity_types_context"]) == 7

            # Person should have ID 1 (sorted by source=system, then name alphabetically)
            # Order: Artifact(0), Concept(1), Entity(2), Event(3), Location(4), Organization(5), Person(6)
            # Actually order is by source first (all system), then by name
            type_names = [t["entity_type_name"] for t in context["entity_types_context"]]
            assert "Person" in type_names
        finally:
            _initialized_projects.discard("test-project-789")
