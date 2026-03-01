"""Load SKILL.md-based skills from plugin directories.

Plugins can declare skill directories in their manifest via the ``skills``
field (e.g., ``"skills": ["./skills"]``).  This module resolves those paths
relative to the plugin's manifest directory and uses the existing
``FileSystemSkillScanner`` + ``MarkdownParser`` infrastructure to discover
and parse SKILL.md files, producing ``Skill`` domain entities with
``source=SkillSource.PLUGIN``.

The factory-based skill registration path (``register_skill_factory``) is
kept for backward compatibility; SKILL.md is the preferred approach.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.domain.model.agent.skill import Skill, SkillScope, SkillSource, TriggerPattern, TriggerType
from src.infrastructure.agent.plugins.discovery import DiscoveredPlugin
from src.infrastructure.agent.plugins.registry import PluginDiagnostic
from src.infrastructure.skill.filesystem_scanner import FileSystemSkillScanner, SkillFileInfo
from src.infrastructure.skill.markdown_parser import (
    MarkdownParseError,
    MarkdownParser,
    SkillMarkdown,
)

logger = logging.getLogger(__name__)


def load_plugin_skills_from_markdown(
    discovered_plugins: list[DiscoveredPlugin],
    tenant_id: str,
    project_id: str | None = None,
) -> tuple[list[Skill], list[PluginDiagnostic]]:
    """Scan discovered plugins for SKILL.md files and build Skill entities.

    For each plugin that declares ``skills`` paths in its manifest, resolve
    the path relative to the plugin directory (derived from ``manifest_path``)
    and scan for SKILL.md files.

    Args:
        discovered_plugins: Plugins discovered by the plugin runtime.
        tenant_id: Tenant owning the skills.
        project_id: Optional project scope.

    Returns:
        Tuple of (skills, diagnostics).
    """
    scanner = FileSystemSkillScanner()
    parser = MarkdownParser()

    all_skills: list[Skill] = []
    all_diagnostics: list[PluginDiagnostic] = []

    for plugin in discovered_plugins:
        if not plugin.skills:
            continue

        plugin_dir = _resolve_plugin_dir(plugin)
        if plugin_dir is None:
            all_diagnostics.append(
                PluginDiagnostic(
                    plugin_name=plugin.name,
                    code="skill_dir_resolve_failed",
                    message=(
                        f"Cannot resolve plugin directory for skill loading "
                        f"(manifest_path={plugin.manifest_path})"
                    ),
                    level="warning",
                )
            )
            continue

        for skill_path_str in plugin.skills:
            resolved = _resolve_skill_path(plugin_dir, skill_path_str)
            if not resolved.exists() or not resolved.is_dir():
                all_diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin.name,
                        code="skill_dir_not_found",
                        message=f"Skill directory not found: {resolved}",
                        level="warning",
                    )
                )
                continue

            scan_result = scanner.scan_directory(resolved, source_type="plugin", is_system=False)

            for error in scan_result.errors:
                all_diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin.name,
                        code="skill_scan_error",
                        message=error,
                        level="warning",
                    )
                )

            for file_info in scan_result.skills:
                skill = _load_single_skill(
                    parser=parser,
                    file_info=file_info,
                    plugin_name=plugin.name,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                if skill is not None:
                    all_skills.append(skill)
                    logger.debug(
                        "Loaded plugin SKILL.md '%s' from plugin '%s' at %s",
                        skill.name,
                        plugin.name,
                        file_info.file_path,
                    )
                else:
                    all_diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin.name,
                            code="skill_load_failed",
                            message=f"Failed to load skill from {file_info.file_path}",
                            level="warning",
                        )
                    )

    if all_skills:
        logger.info(
            "Loaded %d SKILL.md-based plugin skill(s) from %d plugin(s)",
            len(all_skills),
            len({s.source for s in all_skills} or discovered_plugins),
        )

    return all_skills, all_diagnostics


def _resolve_plugin_dir(plugin: DiscoveredPlugin) -> Path | None:
    """Derive the plugin's root directory from its manifest_path."""
    if plugin.manifest_path:
        manifest = Path(plugin.manifest_path)
        if manifest.is_file():
            return manifest.parent
        # manifest_path might already be the directory
        if manifest.is_dir():
            return manifest
    return None


def _resolve_skill_path(plugin_dir: Path, skill_path_str: str) -> Path:
    """Resolve a skill path entry relative to the plugin directory.

    Paths starting with ``./`` or not absolute are treated as relative
    to the plugin directory.
    """
    skill_path = Path(skill_path_str)
    if skill_path.is_absolute():
        return skill_path.resolve()
    return (plugin_dir / skill_path).resolve()


def _load_single_skill(
    *,
    parser: MarkdownParser,
    file_info: SkillFileInfo,
    plugin_name: str,
    tenant_id: str,
    project_id: str | None,
) -> Skill | None:
    """Parse a single SKILL.md and create a Skill domain entity."""
    try:
        markdown = parser.parse_file(str(file_info.file_path))
        return _create_plugin_skill(
            markdown=markdown,
            file_info=file_info,
            plugin_name=plugin_name,
            tenant_id=tenant_id,
            project_id=project_id,
        )
    except MarkdownParseError as exc:
        logger.warning("Failed to parse plugin SKILL.md %s: %s", file_info.file_path, exc)
        return None
    except ValueError as exc:
        logger.warning("Invalid plugin skill definition %s: %s", file_info.file_path, exc)
        return None
    except Exception:
        logger.exception("Unexpected error loading plugin SKILL.md %s", file_info.file_path)
        return None


def _create_plugin_skill(
    *,
    markdown: SkillMarkdown,
    file_info: SkillFileInfo,
    plugin_name: str,
    tenant_id: str,
    project_id: str | None,
) -> Skill:
    """Convert parsed SKILL.md to a Skill domain entity for a plugin.

    Follows the same pattern as
    ``FileSystemSkillLoader._create_skill_from_markdown`` but sets
    ``source=SkillSource.PLUGIN`` and uses a plugin-scoped ID.
    """
    trigger_patterns = (
        [TriggerPattern(pattern=p) for p in markdown.trigger_patterns]
        if markdown.trigger_patterns
        else []
    )

    tools = [t.lower() for t in markdown.tools] if markdown.tools else ["*"]

    return Skill(
        id=f"plugin-{plugin_name}-{markdown.name}",
        tenant_id=tenant_id,
        project_id=project_id,
        name=markdown.name,
        description=markdown.description,
        trigger_type=TriggerType.HYBRID,
        trigger_patterns=trigger_patterns,
        tools=tools,
        prompt_template=markdown.content,
        source=SkillSource.PLUGIN,
        file_path=str(file_info.file_path),
        full_content=markdown.full_content,
        scope=SkillScope.TENANT,
        is_system_skill=False,
        agent_modes=markdown.agent,
        license=markdown.license,
        compatibility=markdown.compatibility,
        version_label=markdown.version,
    )
