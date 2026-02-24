"""
LLM Prompt templates for entity and relationship extraction.

This module provides prompt templates for:
- Entity extraction from text
- Relationship discovery between entities
- Reflexion (checking for missed entities)
- Entity deduplication
- Community summarization

All prompts are designed for structured JSON output.
"""

from datetime import UTC
from typing import Any

# =============================================================================
# Default Entity Types (legacy format for backward compatibility)
# =============================================================================

DEFAULT_ENTITY_TYPES = """
0. Entity - Default entity classification. Use this if no other type fits.
1. Person - A human individual (names, roles, titles)
2. Organization - Companies, institutions, groups, teams
3. Location - Physical places, addresses, regions, countries
4. Concept - Abstract ideas, methodologies, theories
5. Event - Specific occurrences, meetings, incidents
6. Artifact - Objects, tools, products, software
"""

DEFAULT_RELATIONSHIP_TYPES = """
1. WORKS_AT - Person works at an organization
2. LOCATED_IN - Entity is located in a place
3. PART_OF - Entity is part of another entity
4. KNOWS - Person knows another person
5. CREATED_BY - Entity was created by another entity
6. RELATED_TO - General relationship between entities
7. MANAGES - Person manages another entity
8. USES - Entity uses another entity (tool, technology)
"""


# =============================================================================
# Entity Extraction Prompts
# =============================================================================

ENTITY_EXTRACTION_SYSTEM_PROMPT = """You are an expert entity extractor. Your task is to identify and extract all important entities from the given text.

Rules:
1. Extract entities exactly as they appear in the text (preserve original names)
2. Classify each entity with the most appropriate type
3. Provide a brief, factual summary for each entity
4. Do NOT extract temporal information (dates, times) as entities
5. Do NOT extract relationships or actions as entities
6. Be explicit in naming - use full names when available
7. Return results as valid JSON"""


def build_entity_extraction_prompt(
    content: str,
    entity_types: str | None = None,
    entity_types_context: list[dict[str, Any]] | None = None,
    previous_context: str | None = None,
    custom_instructions: str | None = None,
) -> str:
    """
    Build the user prompt for entity extraction.

    Args:
        content: Text content to extract entities from
        entity_types: Custom entity types string (legacy, uses default if not provided)
        entity_types_context: Graphiti-compatible entity types with integer IDs
                             Takes precedence over entity_types if provided
        previous_context: Optional previous messages for context
        custom_instructions: Optional custom extraction instructions

    Returns:
        Formatted user prompt string
    """
    # Build entity types section
    if entity_types_context:
        # Use Graphiti-compatible format with integer IDs
        types_lines = []
        for ctx in entity_types_context:
            types_lines.append(
                f"{ctx['entity_type_id']}. {ctx['entity_type_name']} - {ctx['entity_type_description']}"
            )
        types_section = "\n".join(types_lines)
    else:
        # Legacy format
        types_section = entity_types or DEFAULT_ENTITY_TYPES

    context_section = ""
    if previous_context:
        context_section = f"""
<PREVIOUS_CONTEXT>
{previous_context}
</PREVIOUS_CONTEXT>
"""

    custom_section = ""
    if custom_instructions:
        custom_section = f"""
<ADDITIONAL_INSTRUCTIONS>
{custom_instructions}
</ADDITIONAL_INSTRUCTIONS>
"""

    return (
        f"""<ENTITY_TYPES>
{types_section}
</ENTITY_TYPES>
{context_section}
<TEXT>
{content}
</TEXT>
{custom_section}
Extract all significant entities from the TEXT above. For each entity:
- Identify its name as it appears in the text
- Classify it using the entity_type_id from ENTITY_TYPES (the number before the type name)
- Write a brief summary (1-2 sentences) describing what this entity is

IMPORTANT: You MUST use entity_type_id (integer) to classify entities:
- Use the ID number that appears before each type name in ENTITY_TYPES
- If no specific type matches, use entity_type_id: 0 (the default Entity type)
- Entity type ID 0 is always the fallback for unclassified entities

Respond with a JSON object in this exact format:
{{
    "entities": [
        {{
            "name": "Entity name",
            "entity_type_id": 1,
            "summary": "Brief description of the entity"
        }}
    ]
}}

Notes:
- entity_type_id MUST be an integer matching an ID from ENTITY_TYPES
- Use entity_type_id: 0 for the default Entity type if no specific type matches
- If no entities are found, return: {{"entities": []}}"""
        ""
    )


# =============================================================================
# Reflexion Prompts (Check for Missed Entities)
# =============================================================================

REFLEXION_SYSTEM_PROMPT = """You are an AI assistant that reviews entity extraction results to identify any entities that may have been missed.

Your task is to:
1. Analyze the original text
2. Compare against the list of already extracted entities
3. Identify any significant entities that were NOT extracted
4. Be thorough but avoid duplicates"""


def build_reflexion_prompt(
    content: str,
    extracted_entities: list[dict[str, Any]],
    previous_context: str | None = None,
) -> str:
    """
    Build the user prompt for reflexion (checking missed entities).

    Args:
        content: Original text content
        extracted_entities: List of entities already extracted (EntityNode objects or dicts)
        previous_context: Optional previous messages for context

    Returns:
        Formatted user prompt string
    """

    # Handle both EntityNode objects and dictionaries
    def get_entity_info(e) -> str:
        if hasattr(e, "name"):
            # EntityNode object
            return f"- {e.name} ({e.entity_type or 'Unknown'}): {e.summary or ''}"
        else:
            # Dictionary
            return f"- {e.get('name', 'Unknown')} ({e.get('entity_type', 'Unknown')}): {e.get('summary', '')}"

    entities_str = "\n".join(get_entity_info(e) for e in extracted_entities)

    context_section = ""
    if previous_context:
        context_section = f"""
<PREVIOUS_CONTEXT>
{previous_context}
</PREVIOUS_CONTEXT>
"""

    return f"""{context_section}
<TEXT>
{content}
</TEXT>

<EXTRACTED_ENTITIES>
{entities_str}
</EXTRACTED_ENTITIES>

Review the TEXT and EXTRACTED_ENTITIES above. Identify any significant entities that were missed in the extraction.

Guidelines:
- Only report entities that are clearly mentioned in the TEXT
- Do not report entities already in EXTRACTED_ENTITIES
- Do not report dates, times, or temporal expressions
- Do not report actions or relationships

Respond with a JSON object in this exact format:
{{
    "missed_entities": [
        {{
            "name": "Missed entity name",
            "entity_type": "Type of entity",
            "summary": "Brief description"
        }}
    ],
    "explanation": "Brief explanation of why these were missed (optional)"
}}

If no entities were missed, return: {{"missed_entities": [], "explanation": "All significant entities were captured"}}"""


# =============================================================================
# Relationship Extraction Prompts
# =============================================================================

RELATIONSHIP_EXTRACTION_SYSTEM_PROMPT = """You are an expert at discovering relationships between entities in text.

Your task is to:
1. Identify factual relationships between the given entities
2. Classify each relationship with an appropriate type in SCREAMING_SNAKE_CASE
3. Write a natural language fact describing each relationship
4. Extract temporal information when relationships have time bounds
5. Provide confidence scores based on how explicitly the relationship is stated
6. Avoid hallucinating relationships not supported by the text

Rules:
1. Only extract relationships between entities in the provided list
2. Each relationship must have a source and target entity
3. Use SCREAMING_SNAKE_CASE for relationship types (e.g., WORKS_AT, FOUNDED)
4. The fact should paraphrase the relationship from the source text
5. Weight should be 0.0-1.0 (1.0 = explicitly stated, lower = implied)
6. Extract valid_at/invalid_at dates only if clearly stated or resolvable"""


def build_relationship_extraction_prompt(
    content: str,
    entities: list[dict[str, Any]],
    relationship_types: str | None = None,
    previous_context: str | None = None,
    custom_instructions: str | None = None,
    reference_time: str | None = None,
) -> str:
    """
    Build the user prompt for relationship extraction.

    Args:
        content: Text content to analyze
        entities: List of entities to find relationships between
        relationship_types: Custom relationship types (uses default if not provided)
        previous_context: Optional previous messages for context
        custom_instructions: Optional custom extraction instructions
        reference_time: ISO 8601 timestamp for resolving relative time expressions

    Returns:
        Formatted user prompt string
    """
    from datetime import datetime

    types_section = relationship_types or DEFAULT_RELATIONSHIP_TYPES

    # Use current time if not provided
    if reference_time is None:
        reference_time = datetime.now(UTC).isoformat()

    # Format entities list
    entities_str = "\n".join(
        f"{i + 1}. {e.get('name', 'Unknown')} ({e.get('entity_type', 'Unknown')})"
        for i, e in enumerate(entities)
    )

    context_section = ""
    if previous_context:
        context_section = f"""
<PREVIOUS_CONTEXT>
{previous_context}
</PREVIOUS_CONTEXT>
"""

    custom_section = ""
    if custom_instructions:
        custom_section = f"""
<ADDITIONAL_INSTRUCTIONS>
{custom_instructions}
</ADDITIONAL_INSTRUCTIONS>
"""

    return f"""<RELATIONSHIP_TYPES>
{types_section}
</RELATIONSHIP_TYPES>

<ENTITIES>
{entities_str}
</ENTITIES>
{context_section}
<TEXT>
{content}
</TEXT>

<REFERENCE_TIME>
{reference_time}
</REFERENCE_TIME>
{custom_section}
Discover all factual relationships between the ENTITIES based on the TEXT.

Guidelines:
1. Only create relationships between entities in the ENTITIES list
2. Use entity names exactly as they appear in ENTITIES
3. Choose relationship types from RELATIONSHIP_TYPES or create new ones in SCREAMING_SNAKE_CASE
4. Write a natural language fact describing the relationship (paraphrase from source)
5. Set weight (0.0-1.0): 1.0 for explicitly stated, 0.7-0.9 for strongly implied, 0.5-0.6 for weakly implied
6. Extract valid_at (when fact became true) and invalid_at (when fact stopped being true) if mentioned

Temporal Rules:
- Use ISO 8601 format with UTC (e.g., 2025-01-17T00:00:00Z)
- Use REFERENCE_TIME to resolve relative time expressions (e.g., "last week", "yesterday")
- If only a date is mentioned, use 00:00:00 for time
- If only a year is mentioned, use January 1st
- Leave valid_at/invalid_at as null if no time information is available

Respond with a JSON object in this exact format:
{{
    "relationships": [
        {{
            "from_entity": "Source entity name (exact match from ENTITIES)",
            "to_entity": "Target entity name (exact match from ENTITIES)",
            "relationship_type": "RELATIONSHIP_TYPE_IN_CAPS",
            "fact": "Natural language fact describing the relationship",
            "weight": 0.8,
            "valid_at": "2025-01-17T00:00:00Z",
            "invalid_at": null
        }}
    ]
}}

If no relationships are found, return: {{"relationships": []}}"""


# =============================================================================
# Entity Deduplication Prompts
# =============================================================================

DEDUPE_SYSTEM_PROMPT = """You are an expert at identifying duplicate entities that refer to the same real-world object.

Your task is to:
1. Compare new entities against existing entities
2. Identify which new entities are duplicates of existing ones
3. Consider aliases, abbreviations, and variations in naming
4. Be conservative - only match if you're confident they're the same entity"""


def build_dedupe_prompt(
    new_entities: list[dict[str, Any]],
    existing_entities: list[dict[str, Any]],
) -> str:
    """
    Build the user prompt for entity deduplication.

    Args:
        new_entities: List of newly extracted entities
        existing_entities: List of existing entities in the graph

    Returns:
        Formatted user prompt string
    """
    new_str = "\n".join(
        f"NEW-{i + 1}. {e.get('name', 'Unknown')} ({e.get('entity_type', 'Unknown')}): {e.get('summary', '')}"
        for i, e in enumerate(new_entities)
    )

    existing_str = "\n".join(
        f"EXISTING-{i + 1}. {e.get('name', 'Unknown')} ({e.get('entity_type', 'Unknown')}): {e.get('summary', '')}"
        for i, e in enumerate(existing_entities)
    )

    return f"""<NEW_ENTITIES>
{new_str}
</NEW_ENTITIES>

<EXISTING_ENTITIES>
{existing_str}
</EXISTING_ENTITIES>

Compare NEW_ENTITIES against EXISTING_ENTITIES and identify duplicates.

Guidelines:
1. Match entities that clearly refer to the same real-world object
2. Consider nicknames, abbreviations, and name variations
3. Entities must have compatible types (e.g., both Person, both Organization)
4. When in doubt, do NOT mark as duplicate

Respond with a JSON object in this exact format:
{{
    "duplicates": [
        {{
            "new_entity": "Name from NEW_ENTITIES",
            "existing_entity": "Name from EXISTING_ENTITIES",
            "confidence": 0.95,
            "reason": "Why these are the same entity"
        }}
    ],
    "unique": ["List of NEW_ENTITY names that are NOT duplicates"]
}}

If no duplicates are found, return: {{"duplicates": [], "unique": ["all", "new", "entity", "names"]}}"""


# =============================================================================
# Community Summarization Prompts
# =============================================================================

COMMUNITY_SUMMARY_SYSTEM_PROMPT = """You are an expert at summarizing groups of related entities.

Your task is to:
1. Analyze a group of related entities
2. Generate a concise name for the community
3. Write a summary describing what these entities have in common
4. Keep summaries factual and informative"""


def build_community_summary_prompt(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]] | None = None,
) -> str:
    """
    Build the user prompt for community summarization.

    Args:
        entities: List of entities in the community
        relationships: Optional list of relationships within the community

    Returns:
        Formatted user prompt string
    """
    entities_str = "\n".join(
        f"- {e.get('name', 'Unknown')} ({e.get('entity_type', 'Unknown')}): {e.get('summary', '')}"
        for e in entities
    )

    relationships_section = ""
    if relationships:
        rel_str = "\n".join(
            f"- {r.get('from_entity', '?')} --[{r.get('relationship_type', '?')}]--> {r.get('to_entity', '?')}"
            for r in relationships
        )
        relationships_section = f"""
<RELATIONSHIPS>
{rel_str}
</RELATIONSHIPS>
"""

    return f"""<ENTITIES>
{entities_str}
</ENTITIES>
{relationships_section}
Generate a summary for this community of related entities.

Respond with a JSON object in this exact format:
{{
    "name": "Short descriptive name for this community (2-5 words)",
    "summary": "A concise paragraph describing what these entities have in common and their significance"
}}"""


# =============================================================================
# Entity Summary Update Prompts
# =============================================================================

ENTITY_SUMMARY_SYSTEM_PROMPT = """You are an expert at creating and updating entity summaries based on new information.

Your task is to:
1. Review the existing entity summary
2. Incorporate new information from the provided text
3. Keep the summary concise and factual
4. Preserve important existing information while adding new details"""


def build_entity_summary_prompt(
    entity_name: str,
    entity_type: str,
    existing_summary: str,
    new_content: str,
) -> str:
    """
    Build the user prompt for entity summary update.

    Args:
        entity_name: Name of the entity
        entity_type: Type of the entity
        existing_summary: Current summary of the entity
        new_content: New text content mentioning the entity

    Returns:
        Formatted user prompt string
    """
    return f"""<ENTITY>
Name: {entity_name}
Type: {entity_type}
Current Summary: {existing_summary}
</ENTITY>

<NEW_INFORMATION>
{new_content}
</NEW_INFORMATION>

Update the entity summary to incorporate relevant new information.

Guidelines:
1. Keep the summary concise (2-3 sentences)
2. Preserve important existing information
3. Add new details that are clearly stated in NEW_INFORMATION
4. Do not hallucinate or infer information not present in the text
5. Write in third person

Respond with a JSON object in this exact format:
{{
    "summary": "Updated summary incorporating new information"
}}"""
