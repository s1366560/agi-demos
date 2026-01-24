"""
Community updater for generating and updating community summaries.

This module provides:
- LLM-based community summarization
- Automatic community updates after entity changes
- Community name generation
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.infrastructure.graph.community.louvain_detector import LouvainDetector
from src.infrastructure.graph.extraction.prompts import (
    COMMUNITY_SUMMARY_SYSTEM_PROMPT,
    build_community_summary_prompt,
)
from src.infrastructure.graph.neo4j_client import Neo4jClient
from src.infrastructure.graph.schemas import CommunityNode, EntityNode

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Schema for LLM Structured Output
# =============================================================================


class CommunitySummary(BaseModel):
    """Schema for community summary LLM output."""

    name: str = Field(description="A concise, descriptive name for the community (2-5 words)")
    summary: str = Field(
        description="A comprehensive summary of the community describing its members, "
        "relationships, and overall theme (50-150 words)"
    )


class CommunityUpdater:
    """
    Community updater for managing community summaries and membership.

    Handles:
    - Generating summaries for communities using LLM
    - Updating community membership after entity changes
    - Refreshing communities periodically

    Example:
        updater = CommunityUpdater(neo4j_client, llm_client, louvain_detector)
        await updater.update_communities_for_entities(entities, project_id)
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        llm_client: Any,
        louvain_detector: LouvainDetector,
        model: Optional[str] = None,
    ):
        """
        Initialize community updater.

        Args:
            neo4j_client: Neo4j client
            llm_client: LLM client for summary generation
            louvain_detector: Louvain community detector
            model: Optional model name override
        """
        self._neo4j_client = neo4j_client
        self._llm_client = llm_client
        self._louvain_detector = louvain_detector
        self._model = model

    async def update_communities_for_entities(
        self,
        entities: List[EntityNode],
        project_id: str,
        tenant_id: Optional[str] = None,
        regenerate_all: bool = False,
    ) -> List[CommunityNode]:
        """
        Update communities after new entities are added.

        This method:
        1. Runs community detection on the updated graph
        2. Updates community membership
        3. Generates summaries for new/changed communities

        Args:
            entities: Newly added entities
            project_id: Project ID
            tenant_id: Tenant ID
            regenerate_all: Whether to regenerate all community summaries

        Returns:
            List of updated CommunityNode objects
        """
        if not entities:
            return []

        # Run community detection
        communities = await self._louvain_detector.detect_communities(
            project_id=project_id,
            tenant_id=tenant_id,
        )

        if not communities:
            logger.debug("No communities detected")
            return []

        # Get current community state
        existing_communities = await self._get_existing_communities(project_id)
        existing_map = {c["uuid"]: c for c in existing_communities}

        # Process each community
        updated_communities = []

        for community in communities:
            # Get community members
            member_entities = await self._get_entities_for_community(
                community,
                project_id,
            )

            if not member_entities:
                continue

            # Check if community needs summary update
            needs_update = regenerate_all
            if community.uuid in existing_map:
                existing = existing_map[community.uuid]
                # Update if member count changed significantly
                old_count = existing.get("member_count", 0)
                if abs(community.member_count - old_count) >= max(1, old_count * 0.2):
                    needs_update = True
            else:
                # New community
                needs_update = True

            # Generate summary if needed
            if needs_update:
                try:
                    summary_result = await self._generate_community_summary(member_entities)
                    community.name = summary_result.get("name", community.name)
                    community.summary = summary_result.get("summary", "")
                except Exception as e:
                    logger.warning(f"Failed to generate community summary: {e}")

            # Save community
            member_uuids = [e.get("uuid") for e in member_entities]
            await self._louvain_detector.save_community(community, member_uuids)

            updated_communities.append(community)

        # Clean up stale communities
        await self._louvain_detector.delete_stale_communities(project_id)

        logger.info(f"Updated {len(updated_communities)} communities for project {project_id}")
        return updated_communities

    async def update_single_community(
        self,
        community_uuid: str,
    ) -> Optional[CommunityNode]:
        """
        Update a single community's summary.

        Args:
            community_uuid: Community UUID

        Returns:
            Updated CommunityNode or None
        """
        # Get community
        query = """
            MATCH (c:Community {uuid: $uuid})
            RETURN c
        """

        result = await self._neo4j_client.execute_query(query, uuid=community_uuid)

        if not result.records:
            return None

        community_data = dict(result.records[0]["c"])

        # Get members
        member_entities = await self._louvain_detector.get_community_members(community_uuid)

        if not member_entities:
            return None

        # Generate summary
        try:
            summary_result = await self._generate_community_summary(member_entities)

            # Update community
            update_query = """
                MATCH (c:Community {uuid: $uuid})
                SET c.name = $name,
                    c.summary = $summary,
                    c.member_count = $member_count
                RETURN c
            """

            await self._neo4j_client.execute_query(
                update_query,
                uuid=community_uuid,
                name=summary_result.get("name", community_data.get("name")),
                summary=summary_result.get("summary", ""),
                member_count=len(member_entities),
            )

            return CommunityNode(
                uuid=community_uuid,
                name=summary_result.get("name", ""),
                summary=summary_result.get("summary", ""),
                member_count=len(member_entities),
                project_id=community_data.get("project_id"),
                tenant_id=community_data.get("tenant_id"),
            )

        except Exception as e:
            logger.error(f"Failed to update community {community_uuid}: {e}")
            return None

    async def _generate_community_summary(
        self,
        member_entities: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        """
        Generate summary for a community using LLM with structured output.

        Args:
            member_entities: List of entity dicts

        Returns:
            Dict with 'name' and 'summary' keys
        """
        # Build prompt
        user_prompt = build_community_summary_prompt(
            entities=member_entities,
            relationships=None,  # Could add relationships for richer context
        )

        # Call LLM with structured output
        try:
            result = await self._call_llm_structured(
                system_prompt=COMMUNITY_SUMMARY_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
            return {
                "name": result.name,
                "summary": result.summary,
            }
        except Exception as e:
            logger.warning("Failed to generate community summary: %s", e)
            return {
                "name": "Unnamed Community",
                "summary": "",
            }

    async def _call_llm_structured(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> CommunitySummary:
        """
        Call LLM with structured output support.

        Uses domain Message types for unified LLM interface.
        Falls back to manual JSON parsing if structured output fails.

        Args:
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            CommunitySummary object with name and summary
        """
        from src.domain.llm_providers.llm_types import Message

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        # Try structured output first (works best with OpenAI and compatible providers)
        if hasattr(self._llm_client, "with_structured_output"):
            try:
                # Note: with_structured_output may need LangChain-compatible messages
                # but we'll try with domain messages first
                structured_llm = self._llm_client.with_structured_output(CommunitySummary)
                result = await structured_llm.ainvoke(messages)
                # Validate we got a proper result
                if isinstance(result, CommunitySummary) and result.name and result.summary:
                    return result
            except Exception as e:
                logger.debug(f"Structured output failed, falling back to manual parsing: {e}")

        # Fallback: Manual JSON extraction from LLM response
        return await self._call_llm_with_json_extraction(messages)

    async def _call_llm_with_json_extraction(
        self,
        messages: list,
    ) -> CommunitySummary:
        """
        Call LLM and extract JSON from response, handling markdown wrapping.

        Args:
            messages: Domain Message list

        Returns:
            CommunitySummary object with name and summary
        """
        import json
        import re

        # Get raw response from LLM using domain Message interface
        if hasattr(self._llm_client, "ainvoke"):
            response = await self._llm_client.ainvoke(messages)
            content = response.content if hasattr(response, "content") else str(response)
        elif hasattr(self._llm_client, "chat"):
            # OpenAI-style client - convert domain messages to dict format
            dict_messages = [
                {"role": m.role if hasattr(m, "role") else "user", "content": m.content}
                for m in messages
            ]
            response = await self._llm_client.chat.completions.create(
                model=self._model or getattr(self._llm_client, "model", "gpt-4"),
                messages=dict_messages,
                temperature=0.3,
            )
            content = response.choices[0].message.content
        else:
            raise NotImplementedError(f"Unsupported LLM client type: {type(self._llm_client)}")

        # Extract JSON from markdown code blocks if present
        json_str = content.strip()
        if json_str.startswith("```"):
            # Try multiple patterns to handle various markdown formats
            # Pattern 1: Standard markdown code block with triple backticks
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", json_str, re.DOTALL)
            if match:
                json_str = match.group(1).strip()
            else:
                # Pattern 2: Handle incomplete markdown (e.g., missing closing backticks)
                match = re.search(r"```(?:json)?\s*(\{.*\})\s*`*", json_str, re.DOTALL)
                if match:
                    json_str = match.group(1).strip()
                else:
                    # Pattern 3: Just extract JSON object directly
                    match = re.search(r"\{.*\}", json_str, re.DOTALL)
                    if match:
                        json_str = match.group(0).strip()

        # Parse JSON
        try:
            data = json.loads(json_str)
            return CommunitySummary(
                name=data.get("name", "Unnamed Community"),
                summary=data.get("summary", ""),
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Raw response: {content[:500]}")
            # Return empty result if parsing fails
            raise ValueError(f"Failed to parse community summary JSON: {e}")

    async def _get_existing_communities(
        self,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get existing communities for a project.

        Args:
            project_id: Project ID

        Returns:
            List of community dicts
        """
        query = """
            MATCH (c:Community {project_id: $project_id})
            RETURN c.uuid AS uuid,
                   c.name AS name,
                   c.summary AS summary,
                   c.member_count AS member_count
        """

        result = await self._neo4j_client.execute_query(query, project_id=project_id)
        return [dict(record) for record in result.records]

    async def _get_entities_for_community(
        self,
        community: CommunityNode,
        project_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get entities that should belong to a community.

        For new communities (from detection), this queries entities
        based on their relationships. For existing communities,
        it returns the current members.

        Args:
            community: Community node
            project_id: Project ID

        Returns:
            List of entity dicts
        """
        # First check if community already exists with members
        existing_members = await self._louvain_detector.get_community_members(community.uuid)

        if existing_members:
            return existing_members

        # For new communities, we need to determine members
        # This is typically done by the detection algorithm
        # Here we return entities that are highly connected
        # Match all relationship types between entities, not just RELATES_TO
        query = """
            MATCH (e:Entity {project_id: $project_id})
            OPTIONAL MATCH (e)-[r]-(:Entity)
            WITH e, count(r) AS rel_count
            ORDER BY rel_count DESC
            LIMIT $limit
            RETURN e.uuid AS uuid,
                   e.name AS name,
                   e.entity_type AS entity_type,
                   e.summary AS summary
        """

        result = await self._neo4j_client.execute_query(
            query,
            project_id=project_id,
            limit=community.member_count or 10,
        )

        return [dict(record) for record in result.records]
