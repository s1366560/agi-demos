"""
Relationship extractor using LLM for discovering relationships between entities.

This module provides:
- LLM-based relationship discovery
- Support for custom relationship types
- Weight calculation for relationship strength
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.infrastructure.graph.extraction.prompts import (
    RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT,
    build_relationship_extraction_prompt,
)
from src.infrastructure.graph.schemas import EntityEdge, EntityNode

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.graph.neo4j_client import Neo4jClient


class RelationshipExtractor:
    """
    LLM-based relationship extractor.

    Discovers relationships between entities using LLM with structured JSON output.

    Example:
        extractor = RelationshipExtractor(llm_client)
        relationships = await extractor.extract(
            content="John works at Acme Corp.",
            entities=[
                {"name": "John", "entity_type": "Person"},
                {"name": "Acme Corp", "entity_type": "Organization"}
            ]
        )
    """

    def __init__(
        self,
        llm_client: LLMClient,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        """
        Initialize relationship extractor.

        Args:
            llm_client: LLM client for relationship extraction
            model: Optional model name override
            temperature: Temperature for LLM (0.0 for deterministic)
        """
        self._llm_client = llm_client
        self._model = model
        self._temperature = temperature

    async def extract(
        self,
        content: str,
        entities: list[dict[str, Any]],
        relationship_types: str | None = None,
        edge_type_map: dict[tuple[str, str], list[str]] | None = None,
        previous_context: str | None = None,
        custom_instructions: str | None = None,
        episode_uuid: str | None = None,
    ) -> list[EntityEdge]:
        """
        Extract relationships between entities from text content.

        Args:
            content: Text to analyze
            entities: List of entity dicts with 'name' and 'entity_type'
            relationship_types: Custom relationship types description
            edge_type_map: Mapping from (source_type, target_type) to allowed edge types
                          If provided, validates and constrains relationship types
            previous_context: Optional context from previous messages
            custom_instructions: Optional custom extraction instructions
            episode_uuid: UUID of the episode this relationship came from

        Returns:
            List of EntityEdge objects
        """
        if not content or not content.strip():
            logger.warning("Empty content provided for relationship extraction")
            return []

        if len(entities) < 2:
            logger.debug("Less than 2 entities, skipping relationship extraction")
            return []

        # Build prompt
        user_prompt = build_relationship_extraction_prompt(
            content=content,
            entities=entities,
            relationship_types=relationship_types,
            previous_context=previous_context,
            custom_instructions=custom_instructions,
        )

        # Call LLM
        try:
            response = await self._call_llm(
                system_prompt=RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as e:
            logger.error(f"LLM call failed during relationship extraction: {e}")
            return []

        # Parse response
        relationships_data = self._parse_relationships_response(response)

        if not relationships_data:
            logger.debug("No relationships extracted from content")
            return []

        # Convert to EntityEdge objects
        # Build entity name to UUID mapping
        entity_map = {e.get("name", ""): e.get("uuid", "") for e in entities}
        # Build entity name to type mapping
        entity_type_map = {e.get("name", ""): e.get("entity_type", "Entity") for e in entities}

        edges = self._create_entity_edges(
            relationships_data=relationships_data,
            entity_map=entity_map,
            entity_type_map=entity_type_map,
            edge_type_map=edge_type_map,
            episode_uuid=episode_uuid,
        )

        logger.info(f"Extracted {len(edges)} relationships from content")
        return edges

    async def extract_from_entity_nodes(
        self,
        content: str,
        entity_nodes: list[EntityNode],
        relationship_types: str | None = None,
        edge_type_map: dict[tuple[str, str], list[str]] | None = None,
        previous_context: str | None = None,
        custom_instructions: str | None = None,
        episode_uuid: str | None = None,
    ) -> list[EntityEdge]:
        """
        Extract relationships between EntityNode objects.

        Convenience method that converts EntityNodes to the expected format.

        Args:
            content: Text to analyze
            entity_nodes: List of EntityNode objects
            relationship_types: Custom relationship types
            edge_type_map: Mapping from (source_type, target_type) to allowed edge types
            previous_context: Optional context
            custom_instructions: Optional custom instructions
            episode_uuid: UUID of the episode

        Returns:
            List of EntityEdge objects
        """
        entities = [
            {
                "name": node.name,
                "entity_type": node.entity_type,
                "uuid": node.uuid,
                "summary": node.summary,
            }
            for node in entity_nodes
        ]

        return await self.extract(
            content=content,
            entities=entities,
            relationship_types=relationship_types,
            edge_type_map=edge_type_map,
            previous_context=previous_context,
            custom_instructions=custom_instructions,
            episode_uuid=episode_uuid,
        )

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """
        Call LLM with structured output support.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            LLM response text
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Try to use LiteLLM-style API
        if hasattr(self._llm_client, "chat"):
            response = await self._llm_client.chat.completions.create(
                model=self._model or getattr(self._llm_client, "model", "gpt-4"),
                messages=messages,
                temperature=self._temperature,
                response_format={"type": "json_object"},
            )
            return response.choices[0].message.content

        elif hasattr(self._llm_client, "ainvoke"):
            # LLMClient / UnifiedLLMClient style - uses domain Message
            from src.domain.llm_providers.llm_types import Message

            domain_messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]
            response = await self._llm_client.ainvoke(domain_messages)
            return response.content if hasattr(response, "content") else str(response)

        elif hasattr(self._llm_client, "generate"):
            response = await self._llm_client.generate(
                messages=messages,
                temperature=self._temperature,
                response_format="json",
            )
            return response.content if hasattr(response, "content") else str(response)

        elif hasattr(self._llm_client, "_generate_response"):
            from src.domain.llm_providers.llm_types import Message

            graphiti_messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]
            response = await self._llm_client._generate_response(
                messages=graphiti_messages,
                response_model=None,
            )
            return response.get("content", "") if isinstance(response, dict) else str(response)

        else:
            raise NotImplementedError(f"Unsupported LLM client type: {type(self._llm_client)}")

    def _parse_relationships_response(
        self,
        response: str,
    ) -> list[dict[str, Any]]:
        """
        Parse LLM response to extract relationships.
        Args:
            response: LLM response text (should be JSON)
            List of relationship dictionaries
        """
        try:
            data = json.loads(response)
            return self._extract_relationships_from_parsed(data)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse relationship response as JSON: {e}")
            return self._extract_json_from_text(response)
    @staticmethod
    def _extract_relationships_from_parsed(data: Any) -> list[dict[str, Any]]:
        """Extract relationship list from parsed JSON data."""
        if isinstance(data, dict):
            for key in ("relationships", "edges", "facts"):
                if key in data:
                    return data[key]
            if "from_entity" in data:
                return [data]
            return []
        if isinstance(data, list):
            return data
        return []

    def _extract_json_from_text(self, text: str) -> list[dict[str, Any]]:
        """
        Try to extract JSON from text that may contain non-JSON content.

        Args:
            text: Text that may contain JSON

        Returns:
            List of relationship dictionaries
        """
        import re

        json_patterns = [
            r'\{[^{}]*"relationships"[^{}]*\[[^\]]*\][^{}]*\}',
            r'\[[^\[\]]*\{[^{}]*"from_entity"[^{}]*\}[^\[\]]*\]',
            r'\{[^{}]*"from_entity"[^{}]*\}',
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, dict) and "relationships" in data:
                        return data["relationships"]
                    elif isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "from_entity" in data:
                        return [data]
                except json.JSONDecodeError:
                    continue

        return []

    def _create_entity_edges(
        self,
        relationships_data: list[dict[str, Any]],
        entity_map: dict[str, str],
        entity_type_map: dict[str, str] | None = None,
        edge_type_map: dict[tuple[str, str], list[str]] | None = None,
        episode_uuid: str | None = None,
    ) -> list[EntityEdge]:
        """
        Create EntityEdge objects from relationship data.

        Args:
            relationships_data: List of relationship dictionaries
            entity_map: Mapping from entity name to UUID
            entity_type_map: Mapping from entity name to entity type
            edge_type_map: Mapping from (source_type, target_type) to allowed edge types
            episode_uuid: UUID of the source episode

        Returns:
            List of EntityEdge objects
        """

        edges = []

        for rel_data in relationships_data:
            from_entity = rel_data.get("from_entity", rel_data.get("source", ""))
            to_entity = rel_data.get("to_entity", rel_data.get("target", ""))
            rel_type = rel_data.get(
                "relationship_type", rel_data.get("relation_type", "RELATED_TO")
            )

            if not from_entity or not to_entity:
                logger.warning(f"Skipping relationship with missing entity: {rel_data}")
                continue

            # Look up UUIDs
            source_uuid = entity_map.get(from_entity)
            target_uuid = entity_map.get(to_entity)

            # If exact match not found, try case-insensitive match
            if not source_uuid:
                source_uuid = self._find_entity_uuid(from_entity, entity_map)
            if not target_uuid:
                target_uuid = self._find_entity_uuid(to_entity, entity_map)

            if not source_uuid or not target_uuid:
                logger.warning(
                    f"Skipping relationship: could not find UUID for "
                    f"'{from_entity}' -> '{to_entity}'"
                )
                continue

            # Normalize relationship type to SCREAMING_SNAKE_CASE
            rel_type = self._normalize_relationship_type(rel_type)

            # Validate edge type against schema constraints (Graphiti-compatible)
            if edge_type_map and entity_type_map:
                source_type = entity_type_map.get(from_entity, "Entity")
                target_type = entity_type_map.get(to_entity, "Entity")
                rel_type = self._validate_edge_type(
                    rel_type, source_type, target_type, edge_type_map
                )

            # Get weight
            weight = rel_data.get("weight", rel_data.get("confidence", 0.5))
            if isinstance(weight, str):
                try:
                    weight = float(weight)
                except ValueError:
                    weight = 0.5
            weight = max(0.0, min(1.0, weight))  # Clamp to [0, 1]

            # Get fact (natural language description)
            fact = rel_data.get("fact", rel_data.get("summary", ""))

            # Parse temporal fields
            valid_at = self._parse_datetime(rel_data.get("valid_at"))
            invalid_at = self._parse_datetime(rel_data.get("invalid_at"))

            # Get additional attributes
            attributes = rel_data.get("attributes", {})

            # Create edge
            edge = EntityEdge(
                uuid=str(uuid4()),
                source_uuid=source_uuid,
                target_uuid=target_uuid,
                relationship_type=rel_type,
                fact=fact,
                summary=fact,  # Keep for backwards compatibility
                weight=weight,
                episodes=[episode_uuid] if episode_uuid else [],
                valid_at=valid_at,
                invalid_at=invalid_at,
                attributes=attributes,
            )
            edges.append(edge)

        return edges

    def _parse_datetime(self, dt_str: str | None) -> datetime | None:
        """
        Parse ISO 8601 datetime string.

        Args:
            dt_str: Datetime string or None

        Returns:
            Parsed datetime or None
        """
        if not dt_str:
            return None

        try:
            # Handle various ISO 8601 formats
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError) as e:
            logger.debug(f"Failed to parse datetime '{dt_str}': {e}")
            return None

    def _find_entity_uuid(
        self,
        entity_name: str,
        entity_map: dict[str, str],
    ) -> str | None:
        """
        Find entity UUID with fuzzy matching.

        Args:
            entity_name: Entity name to find
            entity_map: Mapping from name to UUID

        Returns:
            UUID if found, None otherwise
        """
        name_lower = entity_name.lower().strip()

        for name, uuid in entity_map.items():
            if name.lower().strip() == name_lower:
                return uuid

        # Try partial match (entity name contains search term)
        for name, uuid in entity_map.items():
            if name_lower in name.lower() or name.lower() in name_lower:
                return uuid

        return None

    def _normalize_relationship_type(self, rel_type: str) -> str:
        """
        Normalize relationship type to SCREAMING_SNAKE_CASE.

        Args:
            rel_type: Relationship type string

        Returns:
            Normalized relationship type
        """
        import re

        # Remove special characters except underscores
        cleaned = re.sub(r"[^\w\s]", "", rel_type)

        # Split on whitespace and underscores
        words = re.split(r"[\s_]+", cleaned)

        # Join with underscores and uppercase
        result = "_".join(word.upper() for word in words if word)

        return result if result else "RELATED_TO"

    def _validate_edge_type(
        self,
        relationship_type: str,
        source_entity_type: str,
        target_entity_type: str,
        edge_type_map: dict[tuple[str, str], list[str]],
    ) -> str:
        """
        Validate edge type against schema constraints (Graphiti-compatible).

        This follows Graphiti's edge_type_map validation logic:
        - If no constraints exist for the entity type pair, keep the LLM-generated type
        - If constraints exist but the type is not allowed, fall back to RELATES_TO
        - Also checks (source, Entity), (Entity, target), and (Entity, Entity) as fallbacks

        Args:
            relationship_type: LLM-generated relationship type (already normalized)
            source_entity_type: Type of the source entity
            target_entity_type: Type of the target entity
            edge_type_map: Mapping from (source_type, target_type) to allowed edge types

        Returns:
            Validated relationship type (original or RELATES_TO fallback)
        """
        DEFAULT_EDGE_NAME = "RELATES_TO"

        # Build list of signatures to check (specific to general)
        signatures_to_check = [
            (source_entity_type, target_entity_type),  # Exact match
            (source_entity_type, "Entity"),  # Source specific, target general
            ("Entity", target_entity_type),  # Source general, target specific
            ("Entity", "Entity"),  # Most general
        ]

        # Collect all allowed types from matching signatures
        allowed_types: set = set()
        has_constraints = False

        for signature in signatures_to_check:
            if signature in edge_type_map:
                has_constraints = True
                allowed_types.update(edge_type_map[signature])

        # If no constraints defined, keep the LLM-generated type
        if not has_constraints:
            return relationship_type

        # If type is in allowed list, keep it
        if relationship_type in allowed_types:
            return relationship_type

        # Type not allowed - fall back to default
        logger.debug(
            f"Edge type '{relationship_type}' not allowed for "
            f"{source_entity_type} -> {target_entity_type}, "
            f"allowed types: {sorted(allowed_types)}, "
            f"falling back to {DEFAULT_EDGE_NAME}"
        )
        return DEFAULT_EDGE_NAME


class RelationshipDeduplicator:
    """
    Deduplicator for relationships to avoid duplicate edges in the graph.
    """

    def __init__(self, neo4j_client: Neo4jClient) -> None:
        """
        Initialize deduplicator.

        Args:
            neo4j_client: Neo4j client for querying existing relationships
        """
        self._neo4j_client = neo4j_client

    async def deduplicate(
        self,
        new_edges: list[EntityEdge],
        project_id: str,
    ) -> tuple[list[EntityEdge], list[EntityEdge]]:
        """
        Deduplicate new edges against existing relationships in the graph.

        Args:
            new_edges: New edges to check
            project_id: Project ID to scope the search

        Returns:
            Tuple of (unique_edges, duplicate_edges_to_update)
        """
        if not new_edges:
            return [], []

        unique_edges = []
        edges_to_update = []

        # Query existing relationships
        existing_edges = await self._get_existing_edges(project_id)

        # Build lookup key for existing edges
        existing_keys = {}
        for edge in existing_edges:
            key = (
                edge.get("source_uuid"),
                edge.get("target_uuid"),
                edge.get("relationship_type"),
            )
            existing_keys[key] = edge

        for new_edge in new_edges:
            key = (
                new_edge.source_uuid,
                new_edge.target_uuid,
                new_edge.relationship_type,
            )

            if key in existing_keys:
                # Duplicate found - mark for weight update
                existing = existing_keys[key]
                new_edge.uuid = existing.get("uuid", new_edge.uuid)
                # Increment weight (but cap at 1.0)
                new_edge.weight = min(1.0, existing.get("weight", 0.5) + 0.1)
                edges_to_update.append(new_edge)
            else:
                unique_edges.append(new_edge)

        return unique_edges, edges_to_update

    async def _get_existing_edges(
        self,
        project_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get existing RELATES_TO edges for a project.

        Args:
            project_id: Project ID

        Returns:
            List of edge dictionaries
        """
        query = """
            MATCH (e1:Entity {project_id: $project_id})-[r:RELATES_TO]->(e2:Entity)
            RETURN r.uuid AS uuid,
                   e1.uuid AS source_uuid,
                   e2.uuid AS target_uuid,
                   r.relationship_type AS relationship_type,
                   r.weight AS weight
        """

        try:
            result = await self._neo4j_client.execute_query(query, project_id=project_id)
            return [dict(record) for record in result.records]
        except Exception as e:
            logger.error(f"Failed to get existing edges: {e}")
            return []
