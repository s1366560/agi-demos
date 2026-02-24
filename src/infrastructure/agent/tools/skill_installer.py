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
from typing import TYPE_CHECKING, Any, Optional

import httpx

from src.infrastructure.agent.tools.base import AgentTool

if TYPE_CHECKING:
    from src.infrastructure.agent.permission.manager import PermissionManager

logger = logging.getLogger(__name__)


class SkillInstallerTool(AgentTool):
    """
    Tool for installing skills from skills.sh ecosystem.

    This tool downloads and installs skills from GitHub repositories
    following the skills.sh format. Skills are installed to the
    .memstack/skills/ directory by default.

    Supported formats:
    - owner/repo (e.g., vercel-labs/agent-skills)
    - owner/repo --skill skill-name (specific skill from multi-skill repo)
    - https://github.com/owner/repo (full GitHub URL)
    - https://skills.sh/owner/repo/skill-name (skills.sh URL)

    Example usage:
        skill_installer(
            skill_source="vercel-labs/agent-skills",
            skill_name="react-best-practices",
            install_location="project"
        )
    """

    # GitHub raw content base URL
    GITHUB_RAW_BASE = "https://raw.githubusercontent.com"

    # Skills.sh API base (redirects to GitHub)
    SKILLS_SH_BASE = "https://skills.sh"

    def __init__(
        self,
        project_path: Path | None = None,
        tenant_id: str | None = None,
        project_id: str | None = None,
        permission_manager: Optional["PermissionManager"] = None,
        session_id: str | None = None,
    ) -> None:
        """
        Initialize the skill installer tool.

        Args:
            project_path: Path to the project directory (for project-level installation)
            permission_manager: Optional permission manager for access control
            session_id: Optional session ID for permission requests
        """
        super().__init__(
            name="skill_installer",
            description=self._build_description(),
        )
        self._project_path = project_path or Path.cwd()
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._permission_manager = permission_manager
        self._session_id = session_id
        self._pending_events: list[Any] = []

    def _build_description(self) -> str:
        """Build the tool description."""
        return """Install a skill from the skills.sh ecosystem (https://skills.sh).

Skills are packages of instructions and guidance that help you perform specialized tasks.
After installation, skills become available through the skill_loader tool.

Usage examples:
- Install all skills from a repo: skill_installer(skill_source="vercel-labs/agent-skills")
- Install specific skill: skill_installer(skill_source="vercel-labs/agent-skills", skill_name="react-best-practices")
- Install to global location: skill_installer(skill_source="vercel-labs/agent-skills", skill_name="react-best-practices", install_location="global")

Popular skills:
- vercel-labs/agent-skills (React best practices, web design guidelines)
- anthropic/claude-code-skills (Claude Code best practices)

The skill will be installed to .memstack/skills/ (project) or ~/.memstack/skills/ (global)."""

    def consume_pending_events(self) -> list[Any]:
        """Consume pending SSE events buffered during execute()."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "skill_source": {
                    "type": "string",
                    "description": "The skill source in owner/repo format (e.g., 'vercel-labs/agent-skills') or a full URL",
                },
                "skill_name": {
                    "type": "string",
                    "description": "Optional: Specific skill name to install from a multi-skill repository (e.g., 'react-best-practices')",
                },
                "install_location": {
                    "type": "string",
                    "enum": ["project", "global"],
                    "description": "Where to install the skill: 'project' (.memstack/skills/) or 'global' (~/.memstack/skills/). Default: project",
                },
                "branch": {
                    "type": "string",
                    "description": "Git branch to use. Default: 'main'",
                },
            },
            "required": ["skill_source"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate that skill_source argument is provided."""
        skill_source = kwargs.get("skill_source")
        return not (not isinstance(skill_source, str) or not skill_source.strip())

    def _parse_skill_source(self, skill_source: str) -> tuple[str, str, str | None]:
        """
        Parse skill source into owner, repo, and optional skill name.

        Args:
            skill_source: Skill source string (various formats supported)

        Returns:
            Tuple of (owner, repo, skill_name_from_url)

        Raises:
            ValueError: If source format is not recognized
        """
        skill_source = skill_source.strip()

        # Remove trailing slashes
        skill_source = skill_source.rstrip("/")

        # Handle skills.sh URLs: https://skills.sh/owner/repo/skill-name
        skills_sh_match = re.match(
            r"^https?://skills\.sh/([^/]+)/([^/]+)(?:/([^/]+))?$",
            skill_source,
        )
        if skills_sh_match:
            owner, repo, skill_name = skills_sh_match.groups()
            return owner, repo, skill_name

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
            "Expected: owner/repo, https://github.com/owner/repo, or https://skills.sh/owner/repo/skill"
        )

    def _get_install_path(self, install_location: str, skill_name: str) -> Path:
        """
        Get the installation path for a skill.

        Args:
            install_location: 'project' or 'global'
            skill_name: Name of the skill (for directory name)

        Returns:
            Path to the skill directory
        """
        if install_location == "global":
            base_path = Path(os.path.expanduser("~/.memstack/skills"))
        else:
            base_path = self._project_path / ".memstack" / "skills"

        return base_path / skill_name

    async def _fetch_file(
        self,
        owner: str,
        repo: str,
        path: str,
        branch: str = "main",
    ) -> str | None:
        """
        Fetch a file from GitHub raw content.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path within the repo
            branch: Git branch (default: main)

        Returns:
            File content as string, or None if not found
        """
        url = f"{self.GITHUB_RAW_BASE}/{owner}/{repo}/{branch}/{path}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, follow_redirects=True)

                if response.status_code == 200:
                    return response.text
                elif response.status_code == 404:
                    logger.debug(f"File not found: {url}")
                    return None
                else:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
                    return None

        except httpx.RequestError as e:
            logger.error(f"Request error fetching {url}: {e}")
            return None

    async def _discover_skills_in_repo(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
    ) -> list[str]:
        """
        Discover available skills in a repository.

        Checks common skill directory patterns:
        - skills/{skill-name}/SKILL.md
        - {skill-name}/SKILL.md (root level)
        - SKILL.md (single skill repo)

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Git branch

        Returns:
            List of discovered skill names
        """
        skills = []

        # Try to fetch the repo's structure via GitHub API
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/skills?ref={branch}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(api_url)

                if response.status_code == 200:
                    contents = response.json()
                    for item in contents:
                        if item.get("type") == "dir":
                            # Check if this directory has a SKILL.md
                            skill_name = item.get("name")
                            skill_md = await self._fetch_file(
                                owner, repo, f"skills/{skill_name}/SKILL.md", branch
                            )
                            if skill_md:
                                skills.append(skill_name)

        except Exception as e:
            logger.debug(f"Could not list skills directory: {e}")

        # Also check for root-level SKILL.md (single-skill repo)
        root_skill = await self._fetch_file(owner, repo, "SKILL.md", branch)
        if root_skill:
            # Use repo name as skill name
            skills.append(repo)

        return skills

    async def _install_skill(
        self,
        owner: str,
        repo: str,
        skill_name: str,
        install_path: Path,
        branch: str = "main",
    ) -> dict[str, Any]:
        """
        Install a single skill to the specified path.

        Args:
            owner: Repository owner
            repo: Repository name
            skill_name: Name of the skill to install
            install_path: Path to install the skill to
            branch: Git branch

        Returns:
            Result dict with status and details
        """
        # Determine the skill path in the repo
        # Try different patterns
        skill_paths = [
            f"skills/{skill_name}/SKILL.md",
            f"{skill_name}/SKILL.md",
            "SKILL.md",  # Root level for single-skill repos
        ]

        skill_content = None
        used_path = None

        for path in skill_paths:
            content = await self._fetch_file(owner, repo, path, branch)
            if content:
                skill_content = content
                used_path = path
                break

        if not skill_content:
            return {
                "success": False,
                "error": f"Could not find SKILL.md for '{skill_name}' in {owner}/{repo}",
                "tried_paths": skill_paths,
            }

        # Create the installation directory
        try:
            install_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {
                "success": False,
                "error": f"Failed to create directory {install_path}: {e}",
            }

        # Write the SKILL.md file
        skill_file = install_path / "SKILL.md"
        try:
            skill_file.write_text(skill_content, encoding="utf-8")
        except OSError as e:
            return {
                "success": False,
                "error": f"Failed to write SKILL.md: {e}",
            }

        # Try to fetch additional files (references, scripts)
        base_path = used_path.rsplit("/", 1)[0] if "/" in used_path else ""  # type: ignore[union-attr, operator]
        additional_files: list[str] = []

        # Note: Additional directories (references, scripts, assets, rules) would
        # require GitHub API to list directory contents. For now, we just install
        # the main SKILL.md file. Future enhancement could iterate over:
        # ["references", "scripts", "assets", "rules"]
        _ = base_path  # Reserved for future use when fetching additional files

        # Create a metadata file to track the source
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
            logger.warning(f"Failed to write metadata file: {e}")

        return {
            "success": True,
            "skill_name": skill_name,
            "install_path": str(install_path),
            "source": f"{owner}/{repo}",
            "source_path": used_path,
            "files_installed": ["SKILL.md"],
        }

    async def _resolve_skill_name(
        self,
        owner: str,
        repo: str,
        skill_name: str | None,
        branch: str,
    ) -> str | dict[str, Any]:
        """Resolve the skill name when not explicitly provided.

        If skill_name is already set, returns it directly.
        Otherwise, discovers skills in the repo and returns a resolved name
        or a response dict if discovery yields zero or multiple skills.

        Args:
            owner: Repository owner.
            repo: Repository name.
            skill_name: Explicit skill name, or None.
            branch: Git branch.

        Returns:
            Resolved skill name string, or a response dict for the caller to return.
        """
        if skill_name:
            return skill_name

        logger.info(f"No skill name specified, discovering skills in {owner}/{repo}")
        available_skills = await self._discover_skills_in_repo(owner, repo, branch)

        if not available_skills:
            return self._error_response(
                f"No skills found in {owner}/{repo}. Please specify a skill_name parameter.",
                hint="Check the repository structure or specify a skill_name",
            )

        if len(available_skills) == 1:
            return available_skills[0]

        return {
            "title": f"Multiple skills available in {owner}/{repo}",
            "output": (
                f"Found {len(available_skills)} skills in the repository.\n"
                f"Please specify which skill to install using the skill_name parameter.\n\n"
                f"Available skills:\n" + "\n".join(f"  - {s}" for s in available_skills)
            ),
            "metadata": {
                "action": "list",
                "source": f"{owner}/{repo}",
                "available_skills": available_skills,
            },
        }

    async def _do_install(
        self,
        owner: str,
        repo: str,
        skill_name: str,
        install_location: str,
        branch: str,
    ) -> dict[str, Any]:
        """Check existence, install skill, and run lifecycle hooks.

        Args:
            owner: Repository owner.
            repo: Repository name.
            skill_name: Resolved skill name.
            install_location: 'project' or 'global'.
            branch: Git branch.

        Returns:
            Response dict (success, skip, or error).
        """
        install_path = self._get_install_path(install_location, skill_name)

        # Check if skill already exists
        if install_path.exists() and (install_path / "SKILL.md").exists():
            return {
                "title": f"Skill '{skill_name}' already installed",
                "output": (
                    f"The skill '{skill_name}' is already installed at:\n"
                    f"  {install_path}\n\n"
                    "To reinstall, delete the existing skill directory first."
                ),
                "metadata": {
                    "action": "skip",
                    "skill_name": skill_name,
                    "install_path": str(install_path),
                    "reason": "already_exists",
                },
            }

        # Install the skill
        logger.info(f"Installing skill '{skill_name}' from {owner}/{repo} to {install_path}")
        result = await self._install_skill(owner, repo, skill_name, install_path, branch)

        if not result.get("success"):
            return self._error_response(
                result.get("error", "Unknown error during installation"),
                **{k: v for k, v in result.items() if k not in ("success", "error")},
            )

        # Invalidate skill loader cache so new skill is discovered
        lifecycle_result = self._invalidate_skill_cache(skill_name=skill_name)
        self._pending_events.append(
            {
                "type": "toolset_changed",
                "data": {
                    "source": "skill_installer",
                    "tenant_id": self._tenant_id,
                    "project_id": self._project_id,
                    "skill_name": skill_name,
                    "lifecycle": lifecycle_result,
                },
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        return {
            "title": f"Successfully installed skill: {skill_name}",
            "output": (
                f"✅ Skill '{skill_name}' has been installed successfully!\n\n"
                f"Source: {owner}/{repo}\n"
                f"Location: {result['install_path']}\n"
                f"Files: {', '.join(result['files_installed'])}\n\n"
                "The skill is now available through the skill_loader tool.\n"
                f"Use: skill_loader(skill_name='{skill_name}')"
            ),
            "metadata": {
                "action": "install",
                "skill_name": skill_name,
                "source": f"{owner}/{repo}",
                "install_path": result["install_path"],
                "files_installed": result["files_installed"],
                "lifecycle": lifecycle_result,
            },
        }

    async def execute(self, **kwargs: Any) -> str | dict[str, Any]:  # type: ignore[override]
        """
        Execute skill installation.

        Args:
            **kwargs: Parameters including:
                - skill_source: Required. Owner/repo or URL
                - skill_name: Optional. Specific skill to install
                - install_location: Optional. 'project' or 'global'
                - branch: Optional. Git branch (default: main)

        Returns:
            Structured dict with {title, output, metadata} on success,
            or error dict on failure.
        """
        skill_source = kwargs.get("skill_source", "").strip()
        skill_name = kwargs.get("skill_name", "").strip() or None
        install_location = kwargs.get("install_location", "project").strip()
        branch = kwargs.get("branch", "main").strip()

        if not skill_source:
            return self._error_response("skill_source parameter is required")

        if install_location not in ("project", "global"):
            return self._error_response(
                f"Invalid install_location: {install_location}. Must be 'project' or 'global'"
            )

        try:
            owner, repo, url_skill_name = self._parse_skill_source(skill_source)

            # Use skill name from URL if not explicitly provided
            if not skill_name and url_skill_name:
                skill_name = url_skill_name

            # Resolve skill name (discover if needed)
            resolved = await self._resolve_skill_name(owner, repo, skill_name, branch)
            if isinstance(resolved, dict):
                return resolved
            skill_name = resolved

            return await self._do_install(owner, repo, skill_name, install_location, branch)

        except ValueError as e:
            return self._error_response(str(e))
        except Exception as e:
            logger.error(f"Failed to install skill from '{skill_source}': {e}")
            return self._error_response(f"Installation failed: {e!s}")

    def _invalidate_skill_cache(self, *, skill_name: str) -> dict[str, Any]:
        """
        Invalidate skill loader caches so newly installed skill is discovered.

        This enables the skill to be immediately available through skill_loader
        without requiring a restart of the agent worker.
        """
        from src.infrastructure.agent.tools.self_modifying_lifecycle import (
            SelfModifyingLifecycleOrchestrator,
        )

        lifecycle_result = SelfModifyingLifecycleOrchestrator.run_post_change(
            source="skill_installer",
            tenant_id=self._tenant_id,
            project_id=self._project_id,
            clear_tool_definitions=False,
            metadata={"skill_name": skill_name},
        )
        logger.info(
            "Skill installer lifecycle completed for tenant=%s project=%s: %s",
            self._tenant_id,
            self._project_id,
            lifecycle_result["cache_invalidation"],
        )
        return lifecycle_result

    def _error_response(self, message: str, **extra: Any) -> dict[str, Any]:
        """
        Create an error response.

        Args:
            message: Error message
            **extra: Additional metadata

        Returns:
            Error response dict
        """
        return {
            "title": "Skill Installation Failed",
            "output": f"❌ {message}",
            "metadata": {
                "action": "error",
                "error": message,
                **extra,
            },
        }
