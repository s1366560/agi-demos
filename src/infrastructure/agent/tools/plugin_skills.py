"""Convert plugin-provided skill definitions to Skill domain entities.

Plugin skills are loaded from two sources (in order of preference):

1. **SKILL.md files** (preferred) -- Plugins declare ``"skills": ["./skills"]``
   in their manifest and provide SKILL.md files under that directory.  These are
   loaded by ``plugin_skill_loader.load_plugin_skills_from_markdown()``.

2. **Factory callables** (backward compat) -- Plugins register
   ``PluginSkillFactory`` callables via ``register_skill_factory()``.  Each
   factory returns ``list[dict[str, Any]]`` with at minimum: ``name``,
   ``description``, ``tools``.

Optional factory dict fields: ``trigger_type``, ``trigger_patterns``,
``prompt_template``, ``agent_modes``, ``scope``, ``metadata``, ``full_content``.
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.model.agent.skill.skill import Skill, SkillScope, TriggerType
from src.domain.model.agent.skill.skill_source import SkillSource
from src.infrastructure.agent.plugins.discovery import DiscoveredPlugin
from src.infrastructure.agent.plugins.plugin_skill_loader import (
    load_plugin_skills_from_markdown,
)
from src.infrastructure.agent.plugins.registry import (
    AgentPluginRegistry,
    PluginSkillBuildContext,
)

logger = logging.getLogger(__name__)


def _skill_dict_to_domain(
    skill_dict: dict[str, Any],
    *,
    tenant_id: str,
    project_id: str | None = None,
) -> Skill | None:
    """Convert a single plugin skill dict to a Skill domain entity.

    Args:
        skill_dict: Skill definition dict from plugin factory.
        tenant_id: Tenant owning the skill.
        project_id: Optional project scope.

    Returns:
        Skill domain entity, or None if conversion fails.
    """
    try:
        name = skill_dict.get("name")
        description = skill_dict.get("description")
        tools = skill_dict.get("tools")

        if not name or not isinstance(name, str):
            logger.warning("Plugin skill dict missing required 'name' field, skipping")
            return None
        if not description or not isinstance(description, str):
            logger.warning("Plugin skill '%s' missing required 'description' field, skipping", name)
            return None
        if not tools or not isinstance(tools, list):
            logger.warning("Plugin skill '%s' missing required 'tools' field, skipping", name)
            return None

        # Parse optional trigger_type
        raw_trigger_type = skill_dict.get("trigger_type", "keyword")
        try:
            trigger_type = TriggerType(raw_trigger_type)
        except ValueError:
            trigger_type = TriggerType.KEYWORD

        # Parse optional scope
        raw_scope = skill_dict.get("scope", "tenant")
        try:
            scope = SkillScope(raw_scope)
        except ValueError:
            scope = SkillScope.TENANT

        skill = Skill.create(
            tenant_id=tenant_id,
            name=name,
            description=description,
            tools=tools,
            trigger_type=trigger_type,
            trigger_patterns=skill_dict.get("trigger_patterns"),
            project_id=project_id,
            prompt_template=skill_dict.get("prompt_template"),
            metadata=skill_dict.get("metadata"),
            agent_modes=skill_dict.get("agent_modes"),
            scope=scope,
            full_content=skill_dict.get("full_content"),
        )
        # Override source to PLUGIN (Skill.create defaults to DATABASE)
        skill.source = SkillSource.PLUGIN
        return skill

    except Exception:
        logger.exception(
            "Failed to convert plugin skill dict: %s",
            skill_dict.get("name", "<unknown>"),
        )
        return None


async def build_plugin_skills(
    registry: AgentPluginRegistry,
    context: PluginSkillBuildContext,
    *,
    discovered_plugins: list[DiscoveredPlugin] | None = None,
) -> list[Skill]:
    """Build Skill domain entities from plugin SKILL.md files and factories.

    Loading order:
    1. SKILL.md files from discovered plugin directories (preferred path).
    2. Factory callables registered in the plugin registry (backward compat).

    SKILL.md skills take precedence: if a factory produces a skill with the
    same name as a SKILL.md skill, the factory skill is silently skipped.

    Args:
        registry: The plugin registry containing skill factories.
        context: Build context with tenant_id, project_id, agent_mode.
        discovered_plugins: Plugins discovered by the runtime manager.
            When provided, their ``skills`` manifest entries are scanned
            for SKILL.md files.

    Returns:
        List of successfully converted Skill domain entities.
    """
    skills: list[Skill] = []
    markdown_skill_names: set[str] = set()

    # --- 1. SKILL.md-based loading (preferred) ---
    if discovered_plugins:
        md_skills, md_diagnostics = load_plugin_skills_from_markdown(
            discovered_plugins,
            tenant_id=context.tenant_id,
            project_id=context.project_id or None,
        )
        for diag in md_diagnostics:
            log_fn = logger.error if diag.level == "error" else logger.info
            log_fn(
                "Plugin SKILL.md diagnostic [%s/%s]: %s",
                diag.plugin_name,
                diag.code,
                diag.message,
            )
        skills.extend(md_skills)
        markdown_skill_names = {s.name for s in md_skills}

    # --- 2. Factory-based loading (backward compat) ---
    plugin_skill_dicts, diagnostics = await registry.build_skills(context)

    for diag in diagnostics:
        log_fn = logger.error if diag.level == "error" else logger.info
        log_fn("Plugin skill diagnostic [%s/%s]: %s", diag.plugin_name, diag.code, diag.message)

    for skill_dict in plugin_skill_dicts:
        skill = _skill_dict_to_domain(
            skill_dict,
            tenant_id=context.tenant_id,
            project_id=context.project_id,
        )
        if skill is not None:
            if skill.name in markdown_skill_names:
                logger.debug(
                    "Factory skill '%s' skipped (SKILL.md version takes precedence)",
                    skill.name,
                )
                continue
            skills.append(skill)
            logger.debug("Converted plugin factory skill '%s' to Skill entity", skill.name)

    logger.info(
        "Built %d plugin Skill(s) (%d from SKILL.md, %d from factories)",
        len(skills),
        len(markdown_skill_names),
        len(skills) - len(markdown_skill_names),
    )
    return skills
