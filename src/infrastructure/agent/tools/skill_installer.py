"""Skill installer tool for ReAct agent.

This tool enables agents to install skills from the skills.sh ecosystem
(https://skills.sh). Skills are stored as SKILL.md files containing
instructions and guidance for specific tasks.

Installation process:
1. Parse skill identifier (owner/repo format or full URL)
2. Fetch skill content from GitHub (skills.sh uses GitHub repos)
3. Create skill directory in .memstack/skills/
4. Save SKILL.md file and any associated files

Reference: https://skills.sh/docs

Features:
- Supports skills.sh format (owner/repo, e.g., vercel-labs/agent-skills)
- Supports specific skill selection within a repo (--skill parameter)
- Default installation to .memstack/skills/ (project-level)
- Optional global installation to ~/.memstack/skills/
- Permission manager integration (optional)
"""

import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)



# === New @tool_define based implementation ===


# ---------------------------------------------------------------------------
# Module-level state for dependency injection
# ---------------------------------------------------------------------------

_skill_inst_project_path: Path | None = None
_skill_inst_tenant_id: str = ""
_skill_inst_project_id: str = ""
_skill_inst_permission_manager: Any = None
_skill_inst_session_id: str = ""


def configure_skill_installer(
    project_path: Path | None = None,
    tenant_id: str = "",
    project_id: str = "",
    permission_manager: Any = None,
    session_id: str = "",
) -> None:
    """Configure dependencies for the skill_installer tool.

    Called at agent startup to inject services needed by the tool.
    """
    global _skill_inst_project_path, _skill_inst_tenant_id
    global _skill_inst_project_id, _skill_inst_permission_manager
    global _skill_inst_session_id
    _skill_inst_project_path = project_path
    _skill_inst_tenant_id = tenant_id
    _skill_inst_project_id = project_id
    _skill_inst_permission_manager = permission_manager
    _skill_inst_session_id = session_id


# ---------------------------------------------------------------------------
# Constants (mirrored from class)
# ---------------------------------------------------------------------------

_GITHUB_RAW_BASE = "https://raw.githubusercontent.com"
_SKILLS_SH_BASE = "https://skills.sh"


# ---------------------------------------------------------------------------
# Internal helpers (extracted from class methods)
# ---------------------------------------------------------------------------


def _inst_get_install_path(install_location: str, skill_name: str) -> Path:
    """Get the installation path for a skill."""
    if install_location == "global":
        base_path = Path(os.path.expanduser("~/.memstack/skills"))
    else:
        project_path = _skill_inst_project_path or Path.cwd()
        base_path = project_path / ".memstack" / "skills"
    return base_path / skill_name


def _inst_parse_skill_source(skill_source: str) -> tuple[str, str, str | None]:
    """Parse skill source into owner, repo, and optional skill name.

    Raises:
        ValueError: If source format is not recognized.
    """
    skill_source = skill_source.strip().rstrip("/")

    # Handle skills.sh URLs: https://skills.sh/owner/repo/skill-name
    skills_sh_match = re.match(
        r"^https?://skills\.sh/([^/]+)/([^/]+)(?:/([^/]+))?$",
        skill_source,
    )
    if skills_sh_match:
        owner, repo, sname = skills_sh_match.groups()
        return owner, repo, sname

    # Handle GitHub URLs: https://github.com/owner/repo
    github_match = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+)(?:\.git)?$",
        skill_source,
    )
    if github_match:
        owner, repo = github_match.groups()
        return owner, repo, None

    # Handle owner/repo format
    simple_match = re.match(r"^([^/]+)/([^/]+)$", skill_source)
    if simple_match:
        owner, repo = simple_match.groups()
        return owner, repo, None

    raise ValueError(
        f"Invalid skill source format: {skill_source}. "
        "Expected: owner/repo, https://github.com/owner/repo, "
        "or https://skills.sh/owner/repo/skill"
    )


async def _inst_fetch_file(
    owner: str,
    repo: str,
    path: str,
    branch: str = "main",
) -> str | None:
    """Fetch a file from GitHub raw content."""
    url = f"{_GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, follow_redirects=True)

            if response.status_code == 200:
                return response.text
            if response.status_code == 404:
                logger.debug("File not found: %s", url)
                return None
            logger.warning("Failed to fetch %s: HTTP %s", url, response.status_code)
            return None

    except httpx.RequestError as e:
        logger.error("Request error fetching %s: %s", url, e)
        return None


async def _inst_discover_skills_in_repo(
    owner: str,
    repo: str,
    branch: str = "main",
) -> list[str]:
    """Discover available skills in a repository."""
    skills: list[str] = []

    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/skills?ref={branch}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url)

            if response.status_code == 200:
                contents = response.json()
                for item in contents:
                    if item.get("type") == "dir":
                        sname = item.get("name")
                        skill_md = await _inst_fetch_file(
                            owner, repo, f"skills/{sname}/SKILL.md", branch
                        )
                        if skill_md:
                            skills.append(sname)

    except Exception as e:
        logger.debug("Could not list skills directory: %s", e)

    root_skill = await _inst_fetch_file(owner, repo, "SKILL.md", branch)
    if root_skill:
        skills.append(repo)

    return skills


async def _inst_install_skill(
    owner: str,
    repo: str,
    skill_name: str,
    install_path: Path,
    branch: str = "main",
) -> dict[str, Any]:
    """Install a single skill to the specified path."""
    skill_paths = [
        f"skills/{skill_name}/SKILL.md",
        f"{skill_name}/SKILL.md",
        "SKILL.md",
    ]

    skill_content = None
    used_path = None

    for spath in skill_paths:
        content = await _inst_fetch_file(owner, repo, spath, branch)
        if content:
            skill_content = content
            used_path = spath
            break

    if not skill_content:
        return {
            "success": False,
            "error": f"Could not find SKILL.md for '{skill_name}' in {owner}/{repo}",
            "tried_paths": skill_paths,
        }

    return _inst_write_skill_files(
        owner, repo, skill_name, install_path, branch, skill_content, used_path
    )


def _inst_write_skill_files(
    owner: str,
    repo: str,
    skill_name: str,
    install_path: Path,
    branch: str,
    skill_content: str,
    used_path: str | None,
) -> dict[str, Any]:
    """Write skill files to disk and return result dict."""
    try:
        install_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"success": False, "error": f"Failed to create directory {install_path}: {e}"}

    skill_file = install_path / "SKILL.md"
    try:
        skill_file.write_text(skill_content, encoding="utf-8")
    except OSError as e:
        return {"success": False, "error": f"Failed to write SKILL.md: {e}"}

    additional_files: list[str] = []
    base_path = used_path.rsplit("/", 1)[0] if used_path and "/" in used_path else ""
    _ = base_path  # Reserved for future use when fetching additional files

    metadata = {
        "source": f"{owner}/{repo}",
        "skill_name": skill_name,
        "branch": branch,
        "source_path": used_path,
        "installed_files": ["SKILL.md", *additional_files],
    }

    metadata_file = install_path / ".skill-meta.json"
    try:
        import json

        metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to write metadata file: %s", e)

    return {
        "success": True,
        "skill_name": skill_name,
        "install_path": str(install_path),
        "source": f"{owner}/{repo}",
        "source_path": used_path,
        "files_installed": ["SKILL.md"],
    }


async def _inst_resolve_skill_name(
    owner: str,
    repo: str,
    skill_name: str | None,
    branch: str,
) -> str | dict[str, Any] | ToolResult:
    """Resolve the skill name when not explicitly provided.

    Returns the resolved skill name string, or a response dict.
    """
    if skill_name:
        return skill_name

    logger.info("No skill name specified, discovering skills in %s/%s", owner, repo)
    available_skills = await _inst_discover_skills_in_repo(owner, repo, branch)

    if not available_skills:
        return _inst_error_response(
            f"No skills found in {owner}/{repo}. Please specify a skill_name parameter.",
            hint="Check the repository structure or specify a skill_name",
        )

    if len(available_skills) == 1:
        return available_skills[0]

    return {
        "title": f"Multiple skills available in {owner}/{repo}",
        "output": (
            f"Found {len(available_skills)} skills in the repository.\n"
            "Please specify which skill to install using the skill_name parameter.\n\n"
            "Available skills:\n" + "\n".join(f"  - {s}" for s in available_skills)
        ),
        "metadata": {
            "action": "list",
            "source": f"{owner}/{repo}",
            "available_skills": available_skills,
        },
    }


def _inst_invalidate_skill_cache(
    *,
    skill_name: str,
    tenant_id: str,
    project_id: str,
) -> dict[str, Any]:
    """Invalidate skill loader caches so newly installed skill is discovered."""
    from src.infrastructure.agent.tools.self_modifying_lifecycle import (
        SelfModifyingLifecycleOrchestrator,
    )

    lifecycle_result: dict[str, Any] = SelfModifyingLifecycleOrchestrator.run_post_change(
        source="skill_installer",
        tenant_id=tenant_id,
        project_id=project_id,
        clear_tool_definitions=False,
        metadata={"skill_name": skill_name},
    )
    logger.info(
        "Skill installer lifecycle completed for tenant=%s project=%s: %s",
        tenant_id,
        project_id,
        lifecycle_result["cache_invalidation"],
    )
    return lifecycle_result


async def _inst_do_install(
    ctx: ToolContext,
    owner: str,
    repo: str,
    skill_name: str,
    install_location: str,
    branch: str,
    tenant_id: str,
    project_id: str,
) -> ToolResult:
    """Check existence, install skill, and run lifecycle hooks."""
    install_path = _inst_get_install_path(install_location, skill_name)

    if install_path.exists() and (install_path / "SKILL.md").exists():
        return ToolResult(
            output=(
                f"The skill '{skill_name}' is already installed at:\n"
                f"  {install_path}\n\n"
                "To reinstall, delete the existing skill directory first."
            ),
            title=f"Skill '{skill_name}' already installed",
            metadata={
                "action": "skip",
                "skill_name": skill_name,
                "install_path": str(install_path),
                "reason": "already_exists",
            },
        )

    logger.info(
        "Installing skill '%s' from %s/%s to %s",
        skill_name, owner, repo, install_path,
    )
    result = await _inst_install_skill(owner, repo, skill_name, install_path, branch)

    if not result.get("success"):
        return ToolResult(
            output=f"Skill Installation Failed: {result.get('error', 'Unknown error')}",
            is_error=True,
            title="Skill Installation Failed",
            metadata={
                "action": "error",
                "error": result.get("error", "Unknown error"),
                **{k: v for k, v in result.items() if k not in ("success", "error")},
            },
        )

    lifecycle_result = _inst_invalidate_skill_cache(
        skill_name=skill_name,
        tenant_id=tenant_id,
        project_id=project_id,
    )
    await ctx.emit(
        {
            "type": "toolset_changed",
            "data": {
                "source": "skill_installer",
                "tenant_id": tenant_id,
                "project_id": project_id,
                "skill_name": skill_name,
                "lifecycle": lifecycle_result,
            },
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )

    return ToolResult(
        output=(
            f"Skill '{skill_name}' has been installed successfully!\n\n"
            f"Source: {owner}/{repo}\n"
            f"Location: {result['install_path']}\n"
            f"Files: {', '.join(result['files_installed'])}\n\n"
            "The skill is now available through the skill_loader tool.\n"
            f"Use: skill_loader(skill_name='{skill_name}')"
        ),
        title=f"Successfully installed skill: {skill_name}",
        metadata={
            "action": "install",
            "skill_name": skill_name,
            "source": f"{owner}/{repo}",
            "install_path": result["install_path"],
            "files_installed": result["files_installed"],
            "lifecycle": lifecycle_result,
        },
    )


def _inst_error_response(message: str, **extra: Any) -> ToolResult:
    """Create an error ToolResult."""
    return ToolResult(
        output=f"Skill Installation Failed: {message}",
        is_error=True,
        title="Skill Installation Failed",
        metadata={"action": "error", "error": message, **extra},
    )


def _inst_validate_inputs(
    skill_source: str,
    install_location: str,
) -> ToolResult | None:
    """Return an error ToolResult if inputs are invalid, else None."""
    if not skill_source:
        return _inst_error_response("skill_source parameter is required")
    if install_location not in ("project", "global"):
        return _inst_error_response(
            f"Invalid install_location: {install_location}. "
            "Must be 'project' or 'global'"
        )
    return None

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


@tool_define(
    name="skill_installer",
    description=(
        "Install a skill from the skills.sh ecosystem (https://skills.sh). "
        "Skills are packages of instructions and guidance that help you "
        "perform specialized tasks. After installation, skills become "
        "available through the skill_loader tool.\n\n"
        "Usage examples:\n"
        "- Install all skills from a repo: "
        "skill_installer(skill_source='vercel-labs/agent-skills')\n"
        "- Install specific skill: "
        "skill_installer(skill_source='vercel-labs/agent-skills', "
        "skill_name='react-best-practices')\n"
        "- Install to global location: "
        "skill_installer(skill_source='vercel-labs/agent-skills', "
        "skill_name='react-best-practices', install_location='global')\n\n"
        "Popular skills:\n"
        "- vercel-labs/agent-skills (React best practices, web design guidelines)\n"
        "- anthropic/claude-code-skills (Claude Code best practices)\n\n"
        "The skill will be installed to .memstack/skills/ (project) "
        "or ~/.memstack/skills/ (global)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill_source": {
                "type": "string",
                "description": (
                    "The skill source in owner/repo format "
                    "(e.g., 'vercel-labs/agent-skills') or a full URL"
                ),
            },
            "skill_name": {
                "type": "string",
                "description": (
                    "Optional: Specific skill name to install from a "
                    "multi-skill repository (e.g., 'react-best-practices')"
                ),
            },
            "install_location": {
                "type": "string",
                "enum": ["project", "global"],
                "description": (
                    "Where to install the skill: 'project' (.memstack/skills/) "
                    "or 'global' (~/.memstack/skills/). Default: project"
                ),
            },
            "branch": {
                "type": "string",
                "description": "Git branch to use. Default: 'main'",
            },
        },
        "required": ["skill_source"],
    },
    permission="skill",
    category="knowledge",
    tags=frozenset({"skill", "install"}),
)
async def skill_installer_tool(
    ctx: ToolContext,
    *,
    skill_source: str,
    skill_name: str = "",
    install_location: str = "project",
    branch: str = "main",
) -> ToolResult:
    """Install a skill from the skills.sh ecosystem."""
    skill_source = skill_source.strip()
    resolved_name: str | None = skill_name.strip() or None
    install_location = install_location.strip()
    branch = branch.strip()

    tenant_id = _skill_inst_tenant_id
    project_id = _skill_inst_project_id

    validation_err = _inst_validate_inputs(skill_source, install_location)
    if validation_err is not None:
        return validation_err

    try:
        owner, repo, url_skill_name = _inst_parse_skill_source(skill_source)

        if not resolved_name and url_skill_name:
            resolved_name = url_skill_name

        resolved = await _inst_resolve_skill_name(owner, repo, resolved_name, branch)
        if isinstance(resolved, ToolResult):
            return resolved
        if isinstance(resolved, dict):
            return ToolResult(
                output=resolved.get("output", ""),
                title=resolved.get("title"),
                metadata=resolved.get("metadata", {}),
            )
        final_name: str = resolved

        return await _inst_do_install(
            ctx, owner, repo, final_name, install_location, branch,
            tenant_id, project_id,
        )

    except ValueError as e:
        return _inst_error_response(str(e))
    except Exception as e:
        logger.error("Failed to install skill from '%s': %s", skill_source, e)
        return _inst_error_response(f"Installation failed: {e!s}")
