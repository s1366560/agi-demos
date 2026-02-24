"""
Dynamic schema generation for projects.

This module provides functionality to dynamically create Pydantic models
based on project-specific entity and edge type definitions stored in the database.
"""

import logging
from datetime import datetime
from typing import Any, TypedDict

from pydantic import BaseModel, Field, create_model
from sqlalchemy import select

from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import (
    EdgeType,
    EdgeTypeMap,
    EntityType,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Type Definitions for Schema Context (Graphiti-compatible)
# =============================================================================


class EntityTypeContext(TypedDict):
    """Entity type context item for LLM prompts (Graphiti-compatible format)."""

    entity_type_id: int
    entity_type_name: str
    entity_type_description: str


class SchemaContext(TypedDict):
    """Complete schema context for entity/relationship extraction."""

    entity_types_context: list[EntityTypeContext]
    edge_type_map: dict[tuple[str, str], list[str]]
    entity_type_id_to_name: dict[int, str]
    entity_type_name_to_id: dict[str, int]


# =============================================================================
# Default Entity Types (matching Graphiti defaults)
# =============================================================================

DEFAULT_ENTITY_TYPES_CONTEXT: list[EntityTypeContext] = [
    {
        "entity_type_id": 0,
        "entity_type_name": "Entity",
        "entity_type_description": "Default entity classification. Use this if the entity does not fit into any other specific category.",
    },
    {
        "entity_type_id": 1,
        "entity_type_name": "Person",
        "entity_type_description": "A human being, real or fictional.",
    },
    {
        "entity_type_id": 2,
        "entity_type_name": "Organization",
        "entity_type_description": "A company, institution, association, or other group of people.",
    },
    {
        "entity_type_id": 3,
        "entity_type_name": "Location",
        "entity_type_description": "A place, city, country, landmark, or physical location.",
    },
    {
        "entity_type_id": 4,
        "entity_type_name": "Concept",
        "entity_type_description": "An abstract idea, theory, or general notion.",
    },
    {
        "entity_type_id": 5,
        "entity_type_name": "Event",
        "entity_type_description": "A happening, occurrence, or incident, typically at a specific time and place.",
    },
    {
        "entity_type_id": 6,
        "entity_type_name": "Artifact",
        "entity_type_description": "An object made by a human being, typically an item of cultural or historical interest.",
    },
]


_TYPE_MAP: dict[str, type] = {
    "Integer": int,
    "Float": float,
    "Boolean": bool,
    "DateTime": datetime,
    "List": list,
    "Dict": dict,
}


def _resolve_python_type(type_str: str) -> type:
    """Resolve a schema type string to a Python type."""
    return _TYPE_MAP.get(type_str, str)


def _build_typed_fields(schema: dict[str, Any]) -> dict[str, Any]:
    """Build pydantic model fields from a schema definition dict."""
    fields = {}
    for field_name, field_def in schema.items():
        desc = ""
        if isinstance(field_def, dict):
            type_str = field_def.get("type", "String")
            desc = field_def.get("description", "")
        else:
            type_str = str(field_def)
        py_type = _resolve_python_type(type_str)
        fields[field_name] = (py_type | None, Field(None, description=desc))
    return fields


async def _fetch_entity_types(session: Any, project_id: str) -> dict[str, Any]:
    """Fetch and build entity type models from the database."""
    entity_types: dict[str, Any] = {}
    result = await session.execute(select(EntityType).where(EntityType.project_id == project_id))
    for et in result.scalars().all():
        fields = _build_typed_fields(et.schema)
        model = create_model(et.name, **fields, __base__=BaseModel)
        if et.description:
            model.__doc__ = et.description
        entity_types[et.name] = model
    return entity_types


async def _fetch_edge_types(session: Any, project_id: str) -> dict[str, Any]:
    """Fetch and build edge type models from the database."""
    edge_types: dict[str, Any] = {}
    result = await session.execute(select(EdgeType).where(EdgeType.project_id == project_id))
    for et in result.scalars().all():
        fields = _build_typed_fields(et.schema)
        edge_types[et.name] = create_model(et.name, **fields, __base__=BaseModel)
    return edge_types


async def _fetch_edge_maps(session: Any, project_id: str) -> dict[tuple[str, str], list[str]]:
    """Fetch edge type maps from the database."""
    edge_type_map: dict[tuple[str, str], list[str]] = {}
    result = await session.execute(select(EdgeTypeMap).where(EdgeTypeMap.project_id == project_id))
    for em in result.scalars().all():
        key = (em.source_type, em.target_type)
        if key not in edge_type_map:
            edge_type_map[key] = []
        edge_type_map[key].append(em.edge_type)
    return edge_type_map


async def get_project_schema(project_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[tuple[str, str], list[str]]]:
    """
    Get dynamic schema for a project.
    Returns: (entity_types, edge_types, edge_type_map)
    """
    # Default types
    default_types = {
        "Entity": "A generic entity. Use this if the entity does not fit into any other specific category.",
        "Person": "A human being, real or fictional.",
        "Organization": "A company, institution, association, or other group of people.",
        "Location": "A place, city, country, landmark, or physical location.",
        "Concept": "An abstract idea, theory, or general notion.",
        "Event": "A happening, occurrence, or incident, typically at a specific time and place.",
        "Artifact": "An object made by a human being, typically an item of cultural or historical interest.",
    }
    entity_types = {}
    for name, desc in default_types.items():
        model = create_model(name, __base__=BaseModel)
        model.__doc__ = desc
        entity_types[name] = model

    if not project_id:
        return entity_types, {}, {}

    async with async_session_factory() as session:
        entity_types.update(await _fetch_entity_types(session, project_id))
        edge_types = await _fetch_edge_types(session, project_id)
        edge_type_map = await _fetch_edge_maps(session, project_id)

    return entity_types, edge_types, edge_type_map


# =============================================================================
# Schema Context for LLM Prompts (Graphiti-compatible)
# =============================================================================

# Simple in-memory cache for schema context
_schema_context_cache: dict[str, tuple[SchemaContext, float]] = {}
_CACHE_TTL_SECONDS = 60.0  # Cache TTL in seconds


def _get_cached_schema_context(project_id: str) -> SchemaContext | None:
    """Get cached schema context if not expired."""
    import time

    if project_id in _schema_context_cache:
        context, cached_time = _schema_context_cache[project_id]
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            return context
    return None


def _set_cached_schema_context(project_id: str, context: SchemaContext) -> None:
    """Set schema context in cache."""
    import time

    _schema_context_cache[project_id] = (context, time.time())


def clear_schema_context_cache(project_id: str | None = None) -> None:
    """
    Clear the schema context cache.

    Args:
        project_id: If provided, only clear cache for this project.
                   If None, clear entire cache.
    """
    if project_id is None:
        _schema_context_cache.clear()
        logger.debug("Cleared all schema context cache")
    elif project_id in _schema_context_cache:
        del _schema_context_cache[project_id]
        logger.debug(f"Cleared schema context cache for project {project_id}")


def get_default_schema_context() -> SchemaContext:
    """
    Get default schema context without project-specific customizations.

    Returns:
        SchemaContext with default entity types and empty edge_type_map
    """
    entity_type_id_to_name = {
        ctx["entity_type_id"]: ctx["entity_type_name"] for ctx in DEFAULT_ENTITY_TYPES_CONTEXT
    }
    entity_type_name_to_id = {
        ctx["entity_type_name"]: ctx["entity_type_id"] for ctx in DEFAULT_ENTITY_TYPES_CONTEXT
    }

    return SchemaContext(
        entity_types_context=list(DEFAULT_ENTITY_TYPES_CONTEXT),
        edge_type_map={},
        entity_type_id_to_name=entity_type_id_to_name,
        entity_type_name_to_id=entity_type_name_to_id,
    )


# Track which projects have been initialized (in-memory flag)
_initialized_projects: set[str] = set()


async def _ensure_default_types_initialized(project_id: str) -> None:
    """
    Ensure default entity types are initialized in the database for a project.

    This is called automatically on first schema context access for a project.
    Uses an in-memory flag to avoid repeated database checks.

    Args:
        project_id: Project ID to initialize defaults for
    """
    import uuid as uuid_module

    # Skip if already initialized in this process
    if project_id in _initialized_projects:
        return

    async with async_session_factory() as session:
        # Check if any default types exist for this project
        result = await session.execute(
            select(EntityType.name).where(
                EntityType.project_id == project_id, EntityType.source == "system"
            )
        )
        existing_system_types = {row[0] for row in result.fetchall()}

        # If all default types exist, mark as initialized and return
        default_type_names = {t["entity_type_name"] for t in DEFAULT_ENTITY_TYPES_CONTEXT}
        if default_type_names.issubset(existing_system_types):
            _initialized_projects.add(project_id)
            return

        # Insert missing default types
        created_count = 0
        for type_ctx in DEFAULT_ENTITY_TYPES_CONTEXT:
            type_name = type_ctx["entity_type_name"]

            if type_name in existing_system_types:
                continue

            entity_type = EntityType(
                id=str(uuid_module.uuid4()),
                project_id=project_id,
                name=type_name,
                description=type_ctx["entity_type_description"],
                schema={},
                status="ENABLED",
                source="system",
            )
            session.add(entity_type)
            created_count += 1

        if created_count > 0:
            await session.commit()
            logger.info(
                f"Auto-initialized {created_count} default entity types for project {project_id}"
            )

    _initialized_projects.add(project_id)


async def get_project_schema_context(project_id: str | None = None) -> SchemaContext:
    """
    Get schema context for a project in Graphiti-compatible format.

    This function returns entity types with integer IDs for LLM prompts,
    edge type mappings for relationship validation, and ID/name mappings.

    The default Entity type always has ID 0. Custom types start from ID 7
    (after default types: Entity=0, Person=1, Organization=2, Location=3,
    Concept=4, Event=5, Artifact=6).

    Note: Default types are automatically initialized in the database on first access.

    Args:
        project_id: Project ID to load custom types for.
                   If None, returns only default types.

    Returns:
        SchemaContext containing:
        - entity_types_context: List of entity types with IDs for LLM
        - edge_type_map: Dict mapping (source_type, target_type) to allowed edge types
        - entity_type_id_to_name: Dict mapping type ID to type name
        - entity_type_name_to_id: Dict mapping type name to type ID

    Example:
        >>> context = await get_project_schema_context("project-123")
        >>> context["entity_types_context"]
        [
            {"entity_type_id": 0, "entity_type_name": "Entity", ...},
            {"entity_type_id": 1, "entity_type_name": "Person", ...},
            {"entity_type_id": 7, "entity_type_name": "CustomType", ...},  # Custom
        ]
        >>> context["edge_type_map"]
        {("Person", "Organization"): ["WORKS_AT", "FOUNDED"]}
    """
    # Return default context if no project
    if not project_id:
        return get_default_schema_context()

    # Check cache first
    cached = _get_cached_schema_context(project_id)
    if cached is not None:
        logger.debug(f"Using cached schema context for project {project_id}")
        return cached

    # Initialize default types in database (first time only)
    await _ensure_default_types_initialized(project_id)

    # Start with empty context - will load all from database
    entity_types_context: list[EntityTypeContext] = []
    edge_type_map: dict[tuple[str, str], list[str]] = {}

    # Track existing type names to maintain ID assignment order
    type_id_counter = 0

    async with async_session_factory() as session:
        # Fetch ALL Entity Types from database (including defaults)
        result = await session.execute(
            select(EntityType)
            .where(EntityType.project_id == project_id)
            .order_by(EntityType.created_at)
        )
        db_entity_types = list(result.scalars().all())

        # Assign IDs based on order (defaults first, then custom)
        # Sort: system types first, then by name for consistency
        db_entity_types.sort(key=lambda et: (0 if et.source == "system" else 1, et.name))

        for et in db_entity_types:
            entity_types_context.append(
                EntityTypeContext(
                    entity_type_id=type_id_counter,
                    entity_type_name=et.name,
                    entity_type_description=et.description or f"A {et.name} entity.",
                )
            )
            type_id_counter += 1

        # Fetch Edge Type Maps
        result = await session.execute(
            select(EdgeTypeMap).where(EdgeTypeMap.project_id == project_id)
        )
        for em in result.scalars().all():
            key = (em.source_type, em.target_type)  # type: ignore[attr-defined]
            if key not in edge_type_map:
                edge_type_map[key] = []
            if em.edge_type not in edge_type_map[key]:  # type: ignore[attr-defined]
                edge_type_map[key].append(em.edge_type)  # type: ignore[attr-defined]

    # Build ID/name mappings
    entity_type_id_to_name = {
        ctx["entity_type_id"]: ctx["entity_type_name"] for ctx in entity_types_context
    }
    entity_type_name_to_id = {
        ctx["entity_type_name"]: ctx["entity_type_id"] for ctx in entity_types_context
    }

    context = SchemaContext(
        entity_types_context=entity_types_context,
        edge_type_map=edge_type_map,
        entity_type_id_to_name=entity_type_id_to_name,
        entity_type_name_to_id=entity_type_name_to_id,
    )

    # Cache the result
    _set_cached_schema_context(project_id, context)
    logger.debug(
        f"Loaded schema context for project {project_id}: "
        f"{len(entity_types_context)} entity types, "
        f"{len(edge_type_map)} edge type mappings"
    )

    return context


def format_entity_types_for_prompt(entity_types_context: list[EntityTypeContext]) -> str:
    """
    Format entity types context as a string for LLM prompts.

    Args:
        entity_types_context: List of entity type context items

    Returns:
        Formatted string listing entity types with IDs

    Example:
        >>> types_str = format_entity_types_for_prompt(context["entity_types_context"])
        >>> print(types_str)
        0. Entity - Default entity classification...
        1. Person - A human being...
    """
    lines = []
    for ctx in entity_types_context:
        lines.append(
            f"{ctx['entity_type_id']}. {ctx['entity_type_name']} - {ctx['entity_type_description']}"
        )
    return "\n".join(lines)


# =============================================================================
# Schema Persistence Functions
# =============================================================================


async def initialize_default_types_for_project(project_id: str) -> dict[str, int]:
    """
    Initialize default entity types for a project in the database.

    This function ensures all default types (Entity, Person, Organization, etc.)
    are saved to PostgreSQL for the given project. Existing types are skipped.

    Args:
        project_id: Project ID to initialize types for

    Returns:
        Dict with counts: {"created": N, "existing": M}

    Example:
        >>> result = await initialize_default_types_for_project("project-123")
        >>> print(result)
        {"created": 7, "existing": 0}
    """
    import uuid

    created_count = 0
    existing_count = 0

    async with async_session_factory() as session:
        # Check existing types for this project
        result = await session.execute(
            select(EntityType.name).where(EntityType.project_id == project_id)
        )
        existing_names = {row[0] for row in result.fetchall()}

        # Insert default types that don't exist
        for type_ctx in DEFAULT_ENTITY_TYPES_CONTEXT:
            type_name = type_ctx["entity_type_name"]

            if type_name in existing_names:
                existing_count += 1
                continue

            entity_type = EntityType(
                id=str(uuid.uuid4()),
                project_id=project_id,
                name=type_name,
                description=type_ctx["entity_type_description"],
                schema={},
                status="ENABLED",
                source="system",  # Mark as system-provided default
            )
            session.add(entity_type)
            created_count += 1
            logger.debug(f"Created default entity type: {type_name} for project {project_id}")

        await session.commit()

    if created_count > 0:
        # Clear cache to reflect new types
        clear_schema_context_cache(project_id)
        logger.info(
            f"Initialized {created_count} default entity types for project {project_id} "
            f"({existing_count} already existed)"
        )

    return {"created": created_count, "existing": existing_count}


async def save_discovered_entity_type(
    project_id: str,
    name: str,
    description: str | None = None,
) -> str | None:
    """
    Save a newly discovered entity type to the database.

    If the type already exists (by name), returns None.
    Otherwise creates the type with source="llm_discovered".

    Args:
        project_id: Project ID
        name: Entity type name
        description: Optional description

    Returns:
        UUID of created type, or None if already exists
    """
    import uuid

    async with async_session_factory() as session:
        # Check if type already exists
        result = await session.execute(
            select(EntityType.id).where(
                EntityType.project_id == project_id, EntityType.name == name
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            return None

        type_id = str(uuid.uuid4())
        entity_type = EntityType(
            id=type_id,
            project_id=project_id,
            name=name,
            description=description or f"Auto-discovered {name} entity type.",
            schema={},
            status="ENABLED",
            source="llm_discovered",
        )
        session.add(entity_type)
        await session.commit()

        # Clear cache
        clear_schema_context_cache(project_id)
        logger.info(f"Saved discovered entity type: {name} for project {project_id}")

        return type_id


async def save_discovered_edge_type(
    project_id: str,
    name: str,
    description: str | None = None,
) -> str | None:
    """
    Save a newly discovered edge/relationship type to the database.

    If the type already exists (by name), returns None.
    Otherwise creates the type with source="llm_discovered".

    Args:
        project_id: Project ID
        name: Edge type name (e.g., "WORKS_AT", "MANAGES")
        description: Optional description

    Returns:
        UUID of created type, or None if already exists
    """
    import uuid

    async with async_session_factory() as session:
        # Check if type already exists
        result = await session.execute(
            select(EdgeType.id).where(EdgeType.project_id == project_id, EdgeType.name == name)
        )
        existing = result.scalar_one_or_none()

        if existing:
            return None

        type_id = str(uuid.uuid4())
        edge_type = EdgeType(
            id=type_id,
            project_id=project_id,
            name=name,
            description=description or f"Auto-discovered {name} relationship type.",
            schema={},
            status="ENABLED",
            source="llm_discovered",
        )
        session.add(edge_type)
        await session.commit()

        # Clear cache
        clear_schema_context_cache(project_id)
        logger.info(f"Saved discovered edge type: {name} for project {project_id}")

        return type_id


async def save_discovered_edge_type_map(
    project_id: str,
    source_type: str,
    target_type: str,
    edge_type: str,
) -> str | None:
    """
    Save a newly discovered edge type mapping to the database.

    The mapping defines which edge types are allowed between entity type pairs.
    If the mapping already exists, returns None.

    Args:
        project_id: Project ID
        source_type: Source entity type name
        target_type: Target entity type name
        edge_type: Edge type name

    Returns:
        UUID of created mapping, or None if already exists
    """
    import uuid

    async with async_session_factory() as session:
        # Check if mapping already exists
        result = await session.execute(
            select(EdgeTypeMap.id).where(
                EdgeTypeMap.project_id == project_id,
                EdgeTypeMap.source_type == source_type,
                EdgeTypeMap.target_type == target_type,
                EdgeTypeMap.edge_type == edge_type,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            return None

        map_id = str(uuid.uuid4())
        edge_map = EdgeTypeMap(
            id=map_id,
            project_id=project_id,
            source_type=source_type,
            target_type=target_type,
            edge_type=edge_type,
            status="ENABLED",
            source="llm_discovered",
        )
        session.add(edge_map)
        await session.commit()

        # Clear cache
        clear_schema_context_cache(project_id)
        logger.debug(
            f"Saved discovered edge type map: {source_type}-[{edge_type}]->{target_type} "
            f"for project {project_id}"
        )

        return map_id


async def save_discovered_types_batch(
    project_id: str,
    entity_types: list[dict[str, str]],
    edge_types: list[str],
    edge_type_maps: list[dict[str, str]],
) -> dict[str, int]:
    """
    Batch save discovered types to the database.

    This is more efficient than calling individual save functions.

    Args:
        project_id: Project ID
        entity_types: List of {"name": str, "description": str}
        edge_types: List of edge type names
        edge_type_maps: List of {"source_type": str, "target_type": str, "edge_type": str}

    Returns:
        Dict with counts: {
            "entity_types_created": N,
            "edge_types_created": M,
            "edge_type_maps_created": K,
        }
    """
    import uuid

    entity_types_created = 0
    edge_types_created = 0
    edge_type_maps_created = 0

    async with async_session_factory() as session:
        # Get existing entity types
        result = await session.execute(
            select(EntityType.name).where(EntityType.project_id == project_id)
        )
        existing_entity_types = {row[0] for row in result.fetchall()}

        # Get existing edge types
        result = await session.execute(
            select(EdgeType.name).where(EdgeType.project_id == project_id)
        )
        existing_edge_types = {row[0] for row in result.fetchall()}

        # Get existing edge type maps
        result = await session.execute(
            select(EdgeTypeMap.source_type, EdgeTypeMap.target_type, EdgeTypeMap.edge_type).where(
                EdgeTypeMap.project_id == project_id
            )
        )
        existing_maps = {(r[0], r[1], r[2]) for r in result.fetchall()}

        # Save new entity types
        for et in entity_types:
            name = et.get("name", "")
            if not name or name in existing_entity_types:
                continue

            session.add(
                EntityType(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    name=name,
                    description=et.get("description", f"Auto-discovered {name} entity type."),
                    schema={},
                    status="ENABLED",
                    source="llm_discovered",
                )
            )
            existing_entity_types.add(name)
            entity_types_created += 1

        # Save new edge types
        for edge_name in edge_types:
            if not edge_name or edge_name in existing_edge_types:
                continue

            session.add(
                EdgeType(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    name=edge_name,
                    description=f"Auto-discovered {edge_name} relationship type.",
                    schema={},
                    status="ENABLED",
                    source="llm_discovered",
                )
            )
            existing_edge_types.add(edge_name)
            edge_types_created += 1

        # Save new edge type maps
        for em in edge_type_maps:
            source = em.get("source_type", "")
            target = em.get("target_type", "")
            edge = em.get("edge_type", "")

            if not all([source, target, edge]):
                continue

            map_key = (source, target, edge)
            if map_key in existing_maps:
                continue

            session.add(
                EdgeTypeMap(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    source_type=source,
                    target_type=target,
                    edge_type=edge,
                    status="ENABLED",
                    source="llm_discovered",
                )
            )
            existing_maps.add(map_key)
            edge_type_maps_created += 1

        await session.commit()

    # Clear cache if anything was created
    if entity_types_created or edge_types_created or edge_type_maps_created:
        clear_schema_context_cache(project_id)
        logger.info(
            f"Batch saved discovered types for project {project_id}: "
            f"{entity_types_created} entity types, "
            f"{edge_types_created} edge types, "
            f"{edge_type_maps_created} edge type maps"
        )

    return {
        "entity_types_created": entity_types_created,
        "edge_types_created": edge_types_created,
        "edge_type_maps_created": edge_type_maps_created,
    }
