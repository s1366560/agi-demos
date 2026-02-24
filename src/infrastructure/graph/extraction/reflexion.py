"""
Reflexion module for checking missed entities in extraction.

This module provides:
- LLM-based review of entity extraction results
- Identification of missed entities
- Iterative improvement of extraction quality
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
from src.infrastructure.graph.extraction.prompts import (
    REFLEXION_SYSTEM_PROMPT,
    build_reflexion_prompt,
)
from src.infrastructure.graph.schemas import EntityNode

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.graph.extraction.entity_extractor import EntityExtractor


class ReflexionChecker:
    """
    Reflexion checker for entity extraction quality improvement.

    Uses LLM to review extracted entities and identify any missed ones,
    improving overall extraction recall.

    Example:
        checker = ReflexionChecker(llm_client, embedding_service)
        missed = await checker.check_missed_entities(
            content="John and Mary work at Acme.",
            extracted_entities=[{"name": "John", "entity_type": "Person"}]
        )
        # Returns: [EntityNode(name="Mary", entity_type="Person", ...)]
    """

    def __init__(
        self,
        llm_client: LLMClient,
        embedding_service: EmbeddingService,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        """
        Initialize reflexion checker.

        Args:
            llm_client: LLM client for reflexion
            embedding_service: Service for generating embeddings
            model: Optional model name override
            temperature: Temperature for LLM
        """
        self._llm_client = llm_client
        self._embedding_service = embedding_service
        self._model = model
        self._temperature = temperature

    async def check_missed_entities(
        self,
        content: str,
        extracted_entities: list[dict[str, Any]],
        entity_types_context: list[dict[str, Any]] | None = None,
        entity_type_id_to_name: dict[int, str] | None = None,
        previous_context: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> list[EntityNode]:
        """
        Check for entities that may have been missed in extraction.

        Args:
            content: Original text content
            extracted_entities: List of entities already extracted
            entity_types_context: Graphiti-compatible entity types with integer IDs
            entity_type_id_to_name: Mapping from entity_type_id to type name
            previous_context: Optional context from previous messages
            project_id: Project ID for missed entities
            tenant_id: Tenant ID for missed entities
            user_id: User ID for missed entities

        Returns:
            List of missed EntityNode objects
        """
        if not content or not content.strip():
            return []

        if not extracted_entities:
            # If nothing was extracted, reflexion might not help much
            # Better to run extraction again with different parameters
            logger.debug("No extracted entities to review, skipping reflexion")
            return []

        # Build prompt
        user_prompt = build_reflexion_prompt(
            content=content,
            extracted_entities=extracted_entities,
            previous_context=previous_context,
        )

        # Call LLM
        try:
            response = await self._call_llm(
                system_prompt=REFLEXION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as e:
            logger.error(f"LLM call failed during reflexion: {e}")
            return []

        # Parse response
        missed_data = self._parse_reflexion_response(response)

        if not missed_data:
            logger.debug("No missed entities found by reflexion")
            return []

        # Filter out entities that are actually already extracted
        # (LLM might incorrectly report some as missed)
        # Handle both EntityNode objects and dictionaries
        def get_name(e):
            if hasattr(e, "name"):
                return e.name.lower() if e.name else ""
            return e.get("name", "").lower()

        extracted_names = {get_name(e) for e in extracted_entities}
        truly_missed = [m for m in missed_data if m.get("name", "").lower() not in extracted_names]

        if not truly_missed:
            logger.debug("Reflexion found entities but they were already extracted")
            return []

        # Create EntityNode objects with embeddings
        missed_nodes = await self._create_entity_nodes(
            entities_data=truly_missed,
            entity_type_id_to_name=entity_type_id_to_name,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        logger.info(f"Reflexion found {len(missed_nodes)} missed entities")
        return missed_nodes

    async def extract_with_reflexion(
        self,
        content: str,
        entity_extractor: EntityExtractor,
        entity_types: str | None = None,
        previous_context: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        max_iterations: int = 1,
    ) -> list[EntityNode]:
        """
        Extract entities with reflexion to improve recall.

        This method:
        1. Extracts entities using the entity extractor
        2. Runs reflexion to find missed entities
        3. Optionally iterates for multiple rounds

        Args:
            content: Text to extract entities from
            entity_extractor: EntityExtractor instance
            entity_types: Custom entity types
            previous_context: Optional context
            project_id: Project ID
            tenant_id: Tenant ID
            user_id: User ID
            max_iterations: Maximum reflexion iterations

        Returns:
            Combined list of all extracted entities
        """
        # Initial extraction
        all_entities = await entity_extractor.extract(
            content=content,
            entity_types=entity_types,
            previous_context=previous_context,
            project_id=project_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        if not all_entities:
            logger.debug("Initial extraction found no entities")
            return []

        # Reflexion iterations
        for iteration in range(max_iterations):
            # Convert to dict format for reflexion
            extracted_dicts = [
                {
                    "name": e.name,
                    "entity_type": e.entity_type,
                    "summary": e.summary,
                }
                for e in all_entities
            ]

            # Check for missed entities
            missed = await self.check_missed_entities(
                content=content,
                extracted_entities=extracted_dicts,
                previous_context=previous_context,
                project_id=project_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )

            if not missed:
                logger.debug(f"Reflexion iteration {iteration + 1}: no missed entities found")
                break

            # Add missed entities
            all_entities.extend(missed)
            logger.info(f"Reflexion iteration {iteration + 1}: added {len(missed)} missed entities")

        return all_entities

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

    def _parse_reflexion_response(
        self,
        response: str,
    ) -> list[dict[str, Any]]:
        """
        Parse LLM response for missed entities.

        Args:
            response: LLM response text

        Returns:
            List of missed entity dictionaries
        """
        try:
            data = json.loads(response)

            if isinstance(data, dict):
                if "missed_entities" in data:
                    return data["missed_entities"]
                elif "entities" in data:
                    return data["entities"]
                elif "name" in data:
                    return [data]
                return []

            elif isinstance(data, list):
                return data

            return []

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse reflexion response as JSON: {e}")
            return self._extract_json_from_text(response)

    def _extract_json_from_text(self, text: str) -> list[dict[str, Any]]:
        """
        Try to extract JSON from text that may contain non-JSON content.

        Args:
            text: Text that may contain JSON

        Returns:
            List of entity dictionaries
        """
        import re

        json_patterns = [
            r'\{[^{}]*"missed_entities"[^{}]*\[[^\]]*\][^{}]*\}',
            r'\[[^\[\]]*\{[^{}]*"name"[^{}]*\}[^\[\]]*\]',
            r'\{[^{}]*"name"[^{}]*\}',
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, dict) and "missed_entities" in data:
                        return data["missed_entities"]
                    elif isinstance(data, list):
                        return data
                    elif isinstance(data, dict) and "name" in data:
                        return [data]
                except json.JSONDecodeError:
                    continue

        return []

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
            entities_data: List of entity dictionaries
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
            logger.error(f"Failed to generate embeddings: {e}")
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
        Resolve entity type from entity data.

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
                return entity_type_id_to_name[type_id]
            else:
                # Unknown ID, fall back to default (Entity = ID 0)
                return entity_type_id_to_name.get(0, "Entity")

        # Fall back to string entity_type or type field
        entity_type = entity_data.get("entity_type", entity_data.get("type", ""))

        # Return "Entity" as default (matching Graphiti's ID 0 semantics)
        return entity_type if entity_type else "Entity"
