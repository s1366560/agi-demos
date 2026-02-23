"""Event Schema Registry - Version management for event schemas.

The Schema Registry provides:
1. Registration of event schemas by type and version
2. Version migration for backward/forward compatibility
3. Schema validation
4. Default version management

Usage:
    # Register a schema
    @EventSchemaRegistry.register("thought", "1.0")
    class AgentThoughtEventV1(AgentDomainEvent):
        content: str
        thought_level: str = "task"

    # Get a schema
    schema = EventSchemaRegistry.get_schema("thought", "1.0")

    # Migrate an event
    v2_event = EventSchemaRegistry.migrate(v1_event, "1.0", "2.0")
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)


# Type variable for event classes
T = TypeVar("T")


@dataclass
class SchemaInfo:
    """Information about a registered schema."""

    event_type: str
    version: str
    schema_class: Type[Any]
    deprecated: bool = False
    deprecation_message: Optional[str] = None


@dataclass
class MigrationInfo:
    """Information about a schema migration."""

    from_version: str
    to_version: str
    migrator: Callable[[Dict[str, Any]], Dict[str, Any]]


class EventSchemaRegistry:
    """Registry for event schemas and migrations.

    This class provides centralized schema management for all domain events,
    enabling version tracking and migration.
    """

    # Schemas indexed by (event_type, version)
    _schemas: Dict[Tuple[str, str], SchemaInfo] = {}

    # Migrations indexed by (event_type, from_version, to_version)
    _migrations: Dict[Tuple[str, str, str], MigrationInfo] = {}

    # Default versions for each event type
    _default_versions: Dict[str, str] = {}

    # Latest versions for each event type
    _latest_versions: Dict[str, str] = {}

    @classmethod
    def register(
        cls,
        event_type: str,
        version: str,
        *,
        deprecated: bool = False,
        deprecation_message: Optional[str] = None,
    ) -> Callable[[Type[T]], Type[T]]:
        """Decorator to register an event schema.

        Args:
            event_type: The event type (e.g., "thought", "act")
            version: Schema version (e.g., "1.0", "2.0")
            deprecated: Whether this version is deprecated
            deprecation_message: Optional message for deprecated versions

        Returns:
            Decorator function

        Example:
            @EventSchemaRegistry.register("thought", "1.0")
            class AgentThoughtEventV1(AgentDomainEvent):
                content: str
        """

        def decorator(schema_class: Type[T]) -> Type[T]:
            key = (event_type, version)
            cls._schemas[key] = SchemaInfo(
                event_type=event_type,
                version=version,
                schema_class=schema_class,
                deprecated=deprecated,
                deprecation_message=deprecation_message,
            )

            # Update latest version
            current_latest = cls._latest_versions.get(event_type, "0.0")
            if cls._compare_versions(version, current_latest) > 0:
                cls._latest_versions[event_type] = version

            # Set default version if not set
            if event_type not in cls._default_versions:
                cls._default_versions[event_type] = version

            logger.debug(f"Registered schema: {event_type} v{version}")
            return schema_class

        return decorator

    @classmethod
    def register_migration(
        cls,
        event_type: str,
        from_version: str,
        to_version: str,
    ) -> Callable[[Callable[[Dict[str, Any]], Dict[str, Any]]], Callable[[Dict[str, Any]], Dict[str, Any]]]:
        """Decorator to register a schema migration.

        Args:
            event_type: The event type
            from_version: Source version
            to_version: Target version

        Returns:
            Decorator function

        Example:
            @EventSchemaRegistry.register_migration("thought", "1.0", "2.0")
            def migrate_thought_v1_to_v2(data: Dict) -> Dict:
                return {**data, "thinking_time_ms": None}
        """

        def decorator(
            migrator: Callable[[Dict[str, Any]], Dict[str, Any]]
        ) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
            key = (event_type, from_version, to_version)
            cls._migrations[key] = MigrationInfo(
                from_version=from_version,
                to_version=to_version,
                migrator=migrator,
            )
            logger.debug(f"Registered migration: {event_type} v{from_version} -> v{to_version}")
            return migrator

        return decorator

    @classmethod
    def get_schema(
        cls,
        event_type: str,
        version: str = "latest",
    ) -> Optional[Type[Any]]:
        """Get a schema class by type and version.

        Args:
            event_type: The event type
            version: Schema version or "latest" for the latest version

        Returns:
            Schema class or None if not found
        """
        if version == "latest":
            version = cls._latest_versions.get(event_type)
            if not version:
                return None

        key = (event_type, version)
        info = cls._schemas.get(key)

        if info and info.deprecated:
            logger.warning(
                f"Using deprecated schema: {event_type} v{version}. "
                f"{info.deprecation_message or 'Consider upgrading.'}"
            )

        return info.schema_class if info else None

    @classmethod
    def get_schema_info(
        cls,
        event_type: str,
        version: str,
    ) -> Optional[SchemaInfo]:
        """Get full schema information.

        Args:
            event_type: The event type
            version: Schema version

        Returns:
            SchemaInfo or None if not found
        """
        key = (event_type, version)
        return cls._schemas.get(key)

    @classmethod
    def migrate(
        cls,
        event_data: Dict[str, Any],
        event_type: str,
        from_version: str,
        to_version: str,
    ) -> Dict[str, Any]:
        """Migrate event data from one version to another.

        Args:
            event_data: The event payload data
            event_type: The event type
            from_version: Source version
            to_version: Target version

        Returns:
            Migrated event data

        Raises:
            ValueError: If no migration path exists
        """
        if from_version == to_version:
            return event_data

        # Try direct migration
        direct_key = (event_type, from_version, to_version)
        if direct_key in cls._migrations:
            return cls._migrations[direct_key].migrator(event_data)

        # Try to find migration path
        path = cls._find_migration_path(event_type, from_version, to_version)
        if not path:
            raise ValueError(
                f"No migration path from {event_type} v{from_version} to v{to_version}"
            )

        # Apply migrations in sequence
        current_data = event_data
        for step_from, step_to in path:
            key = (event_type, step_from, step_to)
            current_data = cls._migrations[key].migrator(current_data)

        return current_data

    @classmethod
    def set_default_version(cls, event_type: str, version: str) -> None:
        """Set the default version for an event type.

        Args:
            event_type: The event type
            version: Version to use as default
        """
        cls._default_versions[event_type] = version

    @classmethod
    def get_default_version(cls, event_type: str) -> Optional[str]:
        """Get the default version for an event type.

        Args:
            event_type: The event type

        Returns:
            Default version or None
        """
        return cls._default_versions.get(event_type)

    @classmethod
    def get_latest_version(cls, event_type: str) -> Optional[str]:
        """Get the latest version for an event type.

        Args:
            event_type: The event type

        Returns:
            Latest version or None
        """
        return cls._latest_versions.get(event_type)

    @classmethod
    def list_schemas(cls, event_type: Optional[str] = None) -> List[SchemaInfo]:
        """List all registered schemas.

        Args:
            event_type: Optional filter by event type

        Returns:
            List of SchemaInfo objects
        """
        schemas = list(cls._schemas.values())
        if event_type:
            schemas = [s for s in schemas if s.event_type == event_type]
        return sorted(schemas, key=lambda s: (s.event_type, s.version))

    @classmethod
    def list_event_types(cls) -> List[str]:
        """List all registered event types.

        Returns:
            List of event type strings
        """
        return sorted(set(key[0] for key in cls._schemas.keys()))

    @classmethod
    def is_registered(cls, event_type: str, version: str) -> bool:
        """Check if a schema is registered.

        Args:
            event_type: The event type
            version: Schema version

        Returns:
            True if registered
        """
        return (event_type, version) in cls._schemas

    @classmethod
    def clear(cls) -> None:
        """Clear all registered schemas and migrations.

        WARNING: This is mainly for testing purposes.
        """
        cls._schemas.clear()
        cls._migrations.clear()
        cls._default_versions.clear()
        cls._latest_versions.clear()

    @classmethod
    def _compare_versions(cls, v1: str, v2: str) -> int:
        """Compare two version strings.

        Args:
            v1: First version
            v2: Second version

        Returns:
            -1 if v1 < v2, 0 if equal, 1 if v1 > v2
        """
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]

        for p1, p2 in zip(parts1, parts2):
            if p1 < p2:
                return -1
            if p1 > p2:
                return 1

        if len(parts1) < len(parts2):
            return -1
        if len(parts1) > len(parts2):
            return 1

        return 0

    @classmethod
    def _find_migration_path(
        cls,
        event_type: str,
        from_version: str,
        to_version: str,
    ) -> Optional[List[Tuple[str, str]]]:
        """Find a migration path between versions.

        Uses BFS to find the shortest path.

        Args:
            event_type: The event type
            from_version: Source version
            to_version: Target version

        Returns:
            List of (from, to) version tuples or None if no path exists
        """
        # Build adjacency list
        graph: Dict[str, List[str]] = {}
        for key in cls._migrations:
            if key[0] == event_type:
                src, dst = key[1], key[2]
                if src not in graph:
                    graph[src] = []
                graph[src].append(dst)

        # BFS
        from collections import deque

        queue = deque([(from_version, [])])
        visited = {from_version}

        while queue:
            current, path = queue.popleft()

            if current == to_version:
                return path

            for next_version in graph.get(current, []):
                if next_version not in visited:
                    visited.add(next_version)
                    queue.append((next_version, path + [(current, next_version)]))

        return None


# Convenience functions
def get_schema(event_type: str, version: str = "latest") -> Optional[Type[Any]]:
    """Get a schema class by type and version."""
    return EventSchemaRegistry.get_schema(event_type, version)


def migrate_event(
    event_data: Dict[str, Any],
    event_type: str,
    from_version: str,
    to_version: str,
) -> Dict[str, Any]:
    """Migrate event data from one version to another."""
    return EventSchemaRegistry.migrate(event_data, event_type, from_version, to_version)
