"""SHA256 hash-based deduplication for EntityNode objects.

This module provides exact duplicate detection using cryptographic hashing
based on the entity's core attributes (name, type, summary).
"""

import hashlib
import logging

from src.infrastructure.graph.schemas import EntityNode

logger = logging.getLogger(__name__)


class HashDeduplicator:
    """
    Exact duplicate detection using SHA256 hashing.

    Computes a hash based on entity name, entity_type, and summary
    to identify exact duplicates. This is a fast, deterministic method
    that runs before expensive vector similarity checks.

    Example:
        deduper = HashDeduplicator()
        unique = deduper.dedupe(entities)
    """

    def __init__(self) -> None:
        """Initialize the hash deduplicator."""
        self._hash_cache: dict[str, str] = {}

    def compute_hash(self, entity: EntityNode) -> str:
        """
        Compute SHA256 hash for an entity.

        The hash is based on the entity's core identity attributes:
        - name: The entity's name
        - entity_type: The type classification
        - summary: Brief description (optional)

        Args:
            entity: EntityNode to hash

        Returns:
            Hexadecimal SHA256 hash string
        """
        # Normalize summary - empty string if None
        summary = entity.summary or ""

        # Build content string for hashing
        content = f"{entity.name}|{entity.entity_type}|{summary}"

        # Compute SHA256 hash
        hash_value = hashlib.sha256(content.encode()).hexdigest()

        # Cache for potential reuse
        cache_key = str(entity.uuid)
        self._hash_cache[cache_key] = hash_value

        return hash_value

    def dedupe(self, entities: list[EntityNode]) -> list[EntityNode]:
        """
        Remove exact duplicates from a list of entities.

        Uses SHA256 hashing to identify and remove duplicates.
        Preserves the first occurrence of each unique entity.

        Args:
            entities: List of EntityNode objects (may contain duplicates)

        Returns:
            List of unique EntityNode objects (duplicates removed)
        """
        if not entities:
            return []

        seen_hashes: set[str] = set()
        unique_entities: list[EntityNode] = []

        for entity in entities:
            entity_hash = self.compute_hash(entity)

            if entity_hash not in seen_hashes:
                seen_hashes.add(entity_hash)
                unique_entities.append(entity)
            else:
                logger.debug(
                    f"Duplicate entity detected: {entity.name} "
                    f"(type: {entity.entity_type}, hash: {entity_hash[:16]}...)"
                )

        duplicate_count = len(entities) - len(unique_entities)
        if duplicate_count > 0:
            logger.info(
                f"Hash deduplication removed {duplicate_count} duplicates "
                f"({len(unique_entities)} unique from {len(entities)} total)"
            )

        return unique_entities

    def dedupe_against(
        self,
        new_entities: list[EntityNode],
        existing_entities: list[EntityNode],
    ) -> tuple[list[EntityNode], dict[str, str]]:
        """
        Deduplicate new entities against existing entities.

        Compares hashes of new entities against existing entities
        to identify exact duplicates.

        Args:
            new_entities: Newly extracted entities
            existing_entities: Existing entities to check against

        Returns:
            Tuple of (unique_new_entities, duplicate_map)
            - unique_new_entities: New entities not in existing
            - duplicate_map: Maps new entity name to existing entity UUID
        """
        if not new_entities:
            return [], {}

        if not existing_entities:
            return new_entities, {}

        # Compute hashes for existing entities
        existing_hashes: dict[str, str] = {}
        for entity in existing_entities:
            entity_hash = self.compute_hash(entity)
            existing_hashes[entity_hash] = entity.uuid

        # Find unique new entities
        unique_entities: list[EntityNode] = []
        duplicate_map: dict[str, str] = {}

        for entity in new_entities:
            entity_hash = self.compute_hash(entity)

            if entity_hash in existing_hashes:
                # Found a duplicate
                existing_uuid = existing_hashes[entity_hash]
                duplicate_map[entity.name] = existing_uuid
                logger.debug(
                    f"Duplicate entity found: {entity.name} (matches existing: {existing_uuid})"
                )
            else:
                unique_entities.append(entity)

        if duplicate_map:
            logger.info(
                f"Found {len(duplicate_map)} exact duplicates against existing entities "
                f"({len(unique_entities)} new unique entities)"
            )

        return unique_entities, duplicate_map

    def clear_cache(self) -> None:
        """Clear the internal hash cache."""
        self._hash_cache.clear()
