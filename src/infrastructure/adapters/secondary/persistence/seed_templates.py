"""
Seed builtin SubAgent templates into the database.

Called during database initialization to ensure builtin templates exist.
"""

import logging
from typing import Any

from src.domain.ports.repositories.subagent_template_repository import (
    SubAgentTemplateRepositoryPort,
)

logger = logging.getLogger(__name__)

BUILTIN_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "researcher",
        "display_name": "Research Assistant",
        "description": "Specialized in finding, analyzing, and synthesizing information.",
        "category": "research",
        "tags": ["research", "analysis", "knowledge"],
        "system_prompt": (
            "You are a research assistant specialized in finding and analyzing information.\n"
            "Your role is to:\n"
            "1. Search memories and knowledge graphs for relevant information\n"
            "2. Synthesize findings into clear, concise summaries\n"
            "3. Identify knowledge gaps and suggest further research\n\n"
            "Be thorough but focused. Always cite your sources."
        ),
        "trigger_description": "Research tasks, information gathering, knowledge synthesis",
        "trigger_keywords": ["research", "find", "search", "analyze", "summarize"],
        "trigger_examples": [
            "Research the latest trends in AI memory systems",
            "Find all information about user authentication",
        ],
        "allowed_tools": ["memory_search", "entity_lookup", "graph_query"],
        "is_builtin": True,
    },
    {
        "name": "coder",
        "display_name": "Code Assistant",
        "description": "Specialized in software development, debugging, and code review.",
        "category": "development",
        "tags": ["coding", "development", "debugging"],
        "system_prompt": (
            "You are a coding assistant specialized in software development tasks.\n"
            "Your role is to:\n"
            "1. Write, review, and explain code\n"
            "2. Debug issues and suggest improvements\n"
            "3. Follow best practices and coding standards\n\n"
            "Be precise and include code examples when helpful."
        ),
        "trigger_description": "Coding tasks, debugging, code review, implementation",
        "trigger_keywords": ["code", "implement", "debug", "fix", "program"],
        "trigger_examples": [
            "Write a Python function to parse JSON",
            "Debug this authentication error",
        ],
        "allowed_tools": ["*"],
        "is_builtin": True,
    },
    {
        "name": "writer",
        "display_name": "Content Writer",
        "description": "Specialized in creating clear, engaging written content.",
        "category": "content",
        "tags": ["writing", "content", "documentation"],
        "system_prompt": (
            "You are a content writer specialized in creating clear, engaging content.\n"
            "Your role is to:\n"
            "1. Write and edit various types of content\n"
            "2. Adapt tone and style to the audience\n"
            "3. Ensure clarity and proper structure\n\n"
            "Be creative while maintaining accuracy."
        ),
        "trigger_description": "Writing tasks, content creation, editing, documentation",
        "trigger_keywords": ["write", "draft", "edit", "document", "compose"],
        "trigger_examples": [
            "Write a technical blog post about knowledge graphs",
            "Draft an email to the engineering team",
        ],
        "allowed_tools": ["memory_search", "memory_create"],
        "is_builtin": True,
    },
]


async def seed_builtin_templates(
    repo: SubAgentTemplateRepositoryPort,
    tenant_id: str,
) -> int:
    """
    Seed builtin templates for a tenant. Skips if already exist.

    Returns the number of templates created.
    """
    created_count = 0

    for template_data in BUILTIN_TEMPLATES:
        existing = await repo.get_by_name(tenant_id, template_data["name"])
        if existing:
            continue

        data = {**template_data, "tenant_id": tenant_id}
        await repo.create(data)
        created_count += 1
        logger.info(f"Seeded builtin template: {template_data['name']}")

    return created_count
