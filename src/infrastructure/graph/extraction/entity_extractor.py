"""
Entity extractor using LLM for extracting entities from text.

This module provides:
- LLM-based entity extraction with structured output
- Entity deduplication using hash + vector similarity
- Support for custom entity types
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.infrastructure.graph.dedup import HashDeduplicator
from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
from src.infrastructure.graph.extraction.prompts import (
    ENTITY_EXTRACTION_SYSTEM_PROMPT,
    build_entity_extraction_prompt,
)
from src.infrastructure.graph.schemas import EntityNode

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient

# Similarity threshold for entity deduplication
DEDUPE_SIMILARITY_THRESHOLD = 0.92


class EntityExtractor:
    """
    LLM-based entity extractor.

    Extracts entities from text using LLM with structured JSON output,
    then generates vector embeddings for similarity matching.

    Example:
        extractor = EntityExtractor(llm_client, embedding_service)
        entities = await extractor.extract("John works at Acme Corp in New York.")
    """

    def __init__(
        self,
        llm_client: LLMClient,
        embedding_service: EmbeddingService,
        model: str | None = None,
        temperature: float = 0.0,
        use_hash_dedup: bool = True,
    ) -> None:
        """
        Initialize entity extractor.

        Args:
            llm_client: LLM client for entity extraction
            embedding_service: Service for generating embeddings
            model: Optional model name override
            temperature: Temperature for LLM (0.0 for deterministic)
            use_hash_dedup: Enable SHA256 hash deduplication before vector dedup
        """
        self._llm_client = llm_client
        self._embedding_service = embedding_service
        self._model = model
        self._temperature = temperature
        self._use_hash_dedup = use_hash_dedup
        self._hash_deduplicator = HashDeduplicator() if use_hash_dedup else None

    async def extract(
        self,
        content: str,
        entity_types: str | None = None,
        entity_types_context: list[dict[str, Any]] | None = None,
        entity_type_id_to_name: dict[int, str] | None = None,
        previous_context: str | None = None,
        custom_instructions: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> list[EntityNode]:
        """
        Extract entities from text content.

        Args:
            content: Text to extract entities from
            entity_types: Custom entity types description (legacy)
            entity_types_context: Graphiti-compatible entity types with integer IDs
            entity_type_id_to_name: Mapping from entity_type_id to type name
            previous_context: Optional context from previous messages
            custom_instructions: Optional custom extraction instructions
            project_id: Project ID for the extracted entities
            tenant_id: Tenant ID for the extracted entities
            user_id: User ID for the extracted entities

        Returns:
            List of EntityNode objects with embeddings
        """
        if not content or not content.strip():
            logger.warning("Empty content provided for entity extraction")
            return []

        # Build prompt
        user_prompt = build_entity_extraction_prompt(
            content=content,
            entity_types=entity_types,
            entity_types_context=entity_types_context,
            previous_context=previous_context,
            custom_instructions=custom_instructions,
        )

        # Call LLM
        try:
            extracted = await self._call_llm(
                system_prompt=ENTITY_EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as e:
            logger.error(f"LLM call failed during entity extraction: {e}")
            return []

        # Parse response
        entities_data = self._parse_entities_response(extracted)

        if not entities_data:
            logger.debug("No entities extracted from content")
            return []

        # Convert to EntityNode and generate embeddings
        entity_nodes = await self._create_entity_nodes(
            entities_data=entities_data,
            entity_type_id_to_name=entity_type_id_to_name,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        logger.info(f"Extracted {len(entity_nodes)} entities from content")
        return entity_nodes

    async def extract_with_dedup(
        self,
        content: str,
        existing_entities: list[EntityNode],
        entity_types: str | None = None,
        entity_types_context: list[dict[str, Any]] | None = None,
        entity_type_id_to_name: dict[int, str] | None = None,
        previous_context: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        similarity_threshold: float = DEDUPE_SIMILARITY_THRESHOLD,
    ) -> tuple[list[EntityNode], dict[str, str]]:
        """
        Extract entities and deduplicate against existing entities.

        Deduplication strategy (two-pass):
        1. Hash-based exact deduplication (fast, SHA256)
        2. Vector-based semantic deduplication (slower, similarity threshold)

        Args:
            content: Text to extract entities from
            existing_entities: List of existing entities to check for duplicates
            entity_types: Custom entity types description (legacy)
            entity_types_context: Graphiti-compatible entity types with integer IDs
            entity_type_id_to_name: Mapping from entity_type_id to type name
            previous_context: Optional context from previous messages
            project_id: Project ID for the extracted entities
            tenant_id: Tenant ID for the extracted entities
            user_id: User ID for the extracted entities
            similarity_threshold: Threshold for considering entities as duplicates

        Returns:
            Tuple of (unique_entities, duplicate_map)
            - unique_entities: New entities not in existing
            - duplicate_map: Maps new entity name to existing entity UUID
        """
        # Extract entities
        new_entities = await self.extract(
            content=content,
            entity_types=entity_types,
            entity_types_context=entity_types_context,
            entity_type_id_to_name=entity_type_id_to_name,
            previous_context=previous_context,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if not new_entities:
            return [], {}

        if not existing_entities:
            # Still deduplicate within new entities
            if self._hash_deduplicator:
                new_entities = self._hash_deduplicator.dedupe(new_entities)
            return new_entities, {}

        # Pass 1: Hash-based exact deduplication (fast)
        duplicate_map: dict[str, str] = {}
        entities_after_hash: list[EntityNode] = new_entities

        if self._hash_deduplicator:
            entities_after_hash, hash_duplicate_map = self._hash_deduplicator.dedupe_against(
                new_entities=new_entities,
                existing_entities=existing_entities,
            )
            duplicate_map.update(hash_duplicate_map)

            if not entities_after_hash:
                # All entities were exact duplicates
                logger.info(f"All {len(new_entities)} entities were exact duplicates (hash-based)")
                return [], duplicate_map

        # Pass 2: Vector-based semantic deduplication (slower)
        unique_entities, vector_duplicate_map = await self._deduplicate_entities(
            new_entities=entities_after_hash,
            existing_entities=existing_entities,
            similarity_threshold=similarity_threshold,
        )
        duplicate_map.update(vector_duplicate_map)

        logger.info(
            f"Deduplication result: {len(unique_entities)} unique, "
            f"{len(duplicate_map)} total duplicates "
            f"(hash: {len(duplicate_map) - len(vector_duplicate_map)}, "
            f"vector: {len(vector_duplicate_map)})"
        )

        return unique_entities, duplicate_map

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
            # LiteLLM / OpenAI style
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
            # Returns ChatResponse which has .content attribute
            return response.content if hasattr(response, "content") else str(response)

        elif hasattr(self._llm_client, "generate"):
            # Custom LLM client style
            response = await self._llm_client.generate(
                messages=messages,
                temperature=self._temperature,
                response_format="json",
            )
            return response.content if hasattr(response, "content") else str(response)

        elif hasattr(self._llm_client, "_generate_response"):
            # Graphiti-style LLM client
            from src.domain.llm_providers.llm_types import Message

            graphiti_messages = [
                Message(role="system", content=system_prompt),
                Message(role="user", content=user_prompt),
            ]
            response = await self._llm_client._generate_response(
                messages=graphiti_messages,
                response_model=None,  # We'll parse JSON ourselves
            )
            return response.get("content", "") if isinstance(response, dict) else str(response)

        else:
            client_type = type(self._llm_client)
            client_attrs = [attr for attr in dir(self._llm_client) if not attr.startswith("_")]
            logger.error(
                "Unsupported LLM client type encountered in EntityExtractor._call_llm: %s. "
                "Available public attributes: %s. "
                "Expected an LLM client exposing one of the following interfaces: 'chat', "
                "'ainvoke', 'generate', or '_generate_response'.",
                client_type,
                client_attrs,
            )
            raise NotImplementedError(
                f"Unsupported LLM client type: {client_type}. "
                f"Available public attributes: {client_attrs}. "
                "Expected an LLM client exposing one of: 'chat', 'ainvoke', 'generate', or '_generate_response'."
            )

    def _parse_entities_response(
        self,
        response: str,
    ) -> list[dict[str, Any]]:
        """
        Parse LLM response to extract entities.
        Args:
            response: LLM response text (should be JSON)
        Returns:
            List of entity dictionaries
        """
        try:
            data = json.loads(response)
            return self._extract_entities_from_parsed(data)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse entity extraction response as JSON: {e}")
            return self._extract_json_from_text(response)
    @staticmethod
    def _extract_entities_from_parsed(data: Any) -> list[dict[str, Any]]:
        """Extract entity list from already-parsed JSON data."""
        if isinstance(data, dict):
            if "entities" in data:
                return data["entities"]
            if "extracted_entities" in data:
                return data["extracted_entities"]
            if "name" in data:
                return [data]
            return []
        if isinstance(data, list):
            return data
        return []
    def _extract_json_from_text(self, text: str) -> list[dict[str, Any]]:
        """
        Try to extract JSON from text that may contain non-JSON content.
        Uses stack-based matching to support nested JSON objects.
        """
        result = self._try_code_block_json(text)
        if result is not None:
            return result

        result = self._try_stack_based_json(text)
        if result is not None:
            return result

        result = self._try_regex_json(text)
        if result is not None:
            return result
        logger.warning("Could not extract JSON from LLM response")
        return []

    def _try_code_block_json(self, text: str) -> list[dict[str, Any]] | None:
        """Strategy 1: Try markdown code blocks."""
        import re
        code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if not code_block_match:
            return None
        try:
            data = json.loads(code_block_match.group(1))
            if isinstance(data, dict) and "entities" in data:
                return data["entities"]
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        return None

    def _try_stack_based_json(self, text: str) -> list[dict[str, Any]] | None:
        """Strategy 2: Use stack-based matching for nested JSON."""
        json_objects = self._find_json_objects(text)
        for data in json_objects:
            if isinstance(data, dict) and "entities" in data:
                return data["entities"]
            if isinstance(data, list) and len(data) > 0:
                if isinstance(data[0], dict) and ("name" in data[0] or "entity_type" in data[0]):
                    return data
            if isinstance(data, dict) and "name" in data:
                return [data]

        return None

    @staticmethod
    def _find_json_objects(text: str) -> list[Any]:
        """Find all top-level JSON objects/arrays in text using stack matching."""
        json_objects: list[Any] = []
        stack: list[str] = []
        start_idx: int | None = None
        for i, char in enumerate(text):
            if char == "{":
                if not stack:
                    start_idx = i
                stack.append("{")
            elif char == "[" and not stack:
                start_idx = i
                stack.append("[")
            elif char == "[" and stack:
                stack.append("[")
            elif (char == "}" and stack and stack[-1] == "{") or (
                char == "]" and stack and stack[-1] == "["
            ):
                stack.pop()
                if not stack and start_idx is not None:
                    json_str = text[start_idx : i + 1]
                    try:
                        data = json.loads(json_str)
                        json_objects.append(data)
                    except json.JSONDecodeError:
                        pass
                    start_idx = None

        return json_objects

    @staticmethod
    def _try_regex_json(text: str) -> list[dict[str, Any]] | None:
        """Strategy 3: Fallback to regex patterns."""
        import re
        json_patterns = [
            r'\{[^{}]*"entities"\s*:\s*\[',
        ]
        for pattern in json_patterns:
            match = re.search(pattern, text)
            if match:
                remaining = text[match.start() :]
                try:
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(remaining)
                    if isinstance(data, dict) and "entities" in data:
                        return data["entities"]
                except (json.JSONDecodeError, ValueError):
                    pass

        return None

    async def _create_entity_nodes(
        self,
        entities_data: list[dict[str, Any]],
        entity_type_id_to_name: dict[int, str] | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> list[EntityNode]:
        """
        Create EntityNode objects with embeddings.

        Args:
            entities_data: List of entity dictionaries from LLM
            entity_type_id_to_name: Mapping from entity_type_id to type name
            project_id: Project ID
            tenant_id: Tenant ID
            user_id: User ID

        Returns:
            List of EntityNode objects
        """
        entity_nodes = []

        # Collect names for batch embedding
        names = [e.get("name", "") for e in entities_data if e.get("name")]

        if not names:
            return []

        # Generate embeddings in batch
        try:
            embeddings = await self._embedding_service.embed_batch(names)
        except Exception as e:
            logger.error(f"Failed to generate embeddings for entities: {e}")
            embeddings = [None] * len(names)

        # Create EntityNode objects
        for i, entity_data in enumerate(entities_data):
            name = entity_data.get("name", "")
            if not name:
                continue

            # Resolve entity type from entity_type_id (Graphiti-compatible)
            entity_type = self._resolve_entity_type(entity_data, entity_type_id_to_name)

            entity_node = EntityNode(
                uuid=str(uuid4()),
                name=name,
                entity_type=entity_type,
                summary=entity_data.get("summary", entity_data.get("description", "")),
                name_embedding=embeddings[i] if i < len(embeddings) else None,
                attributes=entity_data.get("attributes", {}),
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
            entity_nodes.append(entity_node)

        return entity_nodes

    def _resolve_entity_type(
        self,
        entity_data: dict[str, Any],
        entity_type_id_to_name: dict[int, str] | None = None,
    ) -> str:
        """
        Resolve entity type from LLM response data.

        Priority:
        1. entity_type_id (if entity_type_id_to_name mapping provided)
        2. entity_type (string)
        3. type (legacy field)
        4. "Entity" (default fallback, matching Graphiti's ID 0)

        Args:
            entity_data: Entity dictionary from LLM
            entity_type_id_to_name: Optional mapping from type ID to name

        Returns:
            Resolved entity type name
        """
        # Try entity_type_id first (Graphiti-compatible)
        if entity_type_id_to_name is not None and "entity_type_id" in entity_data:
            type_id = entity_data["entity_type_id"]
            if isinstance(type_id, int) and type_id in entity_type_id_to_name:
                resolved_type = entity_type_id_to_name[type_id]
                logger.debug(f"Resolved entity_type_id {type_id} to '{resolved_type}'")
                return resolved_type
            else:
                # Unknown ID, fall back to default (Entity = ID 0)
                logger.debug(f"Unknown entity_type_id {type_id}, falling back to 'Entity'")
                return entity_type_id_to_name.get(0, "Entity")

        # Fall back to string entity_type or type field
        entity_type = entity_data.get("entity_type", entity_data.get("type", ""))

        # Return "Entity" as default (matching Graphiti's ID 0 semantics)
        # instead of "Unknown" to maintain consistency
        return entity_type if entity_type else "Entity"

    async def _deduplicate_entities(
        self,
        new_entities: list[EntityNode],
        existing_entities: list[EntityNode],
        similarity_threshold: float,
    ) -> tuple[list[EntityNode], dict[str, str]]:
        """
        Deduplicate new entities against existing ones using embedding similarity.

        Args:
            new_entities: Newly extracted entities
            existing_entities: Existing entities in the graph
            similarity_threshold: Threshold for considering duplicates

        Returns:
            Tuple of (unique_entities, duplicate_map)
        """
        if not existing_entities or not new_entities:
            return new_entities, {}

        unique_entities = []
        duplicate_map = {}  # new_entity_name -> existing_entity_uuid

        # Get existing embeddings
        existing_embeddings = [e.name_embedding for e in existing_entities if e.name_embedding]
        existing_names = [e.name for e in existing_entities if e.name_embedding]
        existing_uuids = [e.uuid for e in existing_entities if e.name_embedding]

        if not existing_embeddings:
            return new_entities, {}

        for new_entity in new_entities:
            if not new_entity.name_embedding:
                unique_entities.append(new_entity)
                continue

            # Find most similar existing entity
            similarities = await self._embedding_service.find_most_similar(
                query_embedding=new_entity.name_embedding,
                candidates=existing_embeddings,
                top_k=1,
            )

            if similarities and similarities[0][1] >= similarity_threshold:
                # Found a duplicate
                idx, score = similarities[0]
                existing_name = existing_names[idx]
                existing_uuid = existing_uuids[idx]

                # Additional check: entity types should be compatible
                existing_type = existing_entities[idx].entity_type
                if self._types_compatible(new_entity.entity_type, existing_type):
                    logger.debug(
                        f"Entity '{new_entity.name}' matches '{existing_name}' "
                        f"(similarity: {score:.3f})"
                    )
                    duplicate_map[new_entity.name] = existing_uuid
                else:
                    # Types don't match, treat as unique
                    unique_entities.append(new_entity)
            else:
                # No match found, it's unique
                unique_entities.append(new_entity)

        return unique_entities, duplicate_map

    def _types_compatible(self, type1: str, type2: str) -> bool:
        """
        Check if two entity types are compatible for deduplication.

        Args:
            type1: First entity type
            type2: Second entity type

        Returns:
            True if types are compatible
        """
        # Normalize types
        t1 = type1.lower().strip() if type1 else ""
        t2 = type2.lower().strip() if type2 else ""

        if t1 == t2:
            return True

        # Define compatible type groups
        compatible_groups = [
            {"person", "individual", "human", "user"},
            {"organization", "company", "corporation", "group", "team"},
            {"location", "place", "address", "region", "country", "city"},
            {"concept", "idea", "theory", "methodology"},
            {"product", "service", "tool", "software"},
        ]

        for group in compatible_groups:
            if t1 in group and t2 in group:
                return True

        return False
