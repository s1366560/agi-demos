"""
Skill Reverse Sync Service.

Reads skill files from sandbox containers via MCP tools, creates version
snapshots, and persists to both the database and host filesystem.

This service handles both directions of skill sync:
- Forward: sync from DB/host filesystem to sandbox (via SkillResourceSyncService)
- Reverse: sync from sandbox back to DB + host filesystem (this service)
"""

import base64
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.domain.model.agent.skill import Skill, SkillScope, TriggerPattern, TriggerType
from src.domain.model.agent.skill.skill_source import SkillSource
from src.domain.model.agent.skill.skill_version import SkillVersion
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort
from src.infrastructure.skill.markdown_parser import MarkdownParser

logger = logging.getLogger(__name__)

# Default skill path inside sandbox container
SANDBOX_SKILL_BASE = "/workspace/.memstack/skills"

# Binary file extensions that should be base64-encoded
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".7z",
    ".pptx",
    ".xlsx",
    ".docx",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".wav",
    ".ogg",
    ".pyc",
    ".pyd",
    ".so",
    ".dll",
}


class SkillReverseSync:
    """Service for syncing skills from sandbox back to database and host filesystem."""

    def __init__(
        self,
        skill_repository: SkillRepositoryPort,
        skill_version_repository: SkillVersionRepositoryPort,
        host_project_path: Path,
    ) -> None:
        self._skill_repo = skill_repository
        self._version_repo = skill_version_repository
        self._host_project_path = host_project_path
        self._parser = MarkdownParser()

    async def sync_from_sandbox(
        self,
        skill_name: str,
        tenant_id: str,
        sandbox_adapter: Any,
        sandbox_id: str,
        project_id: Optional[str] = None,
        change_summary: Optional[str] = None,
        created_by: str = "agent",
        skill_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Read skill files from sandbox, persist to DB with version snapshot,
        and write to host filesystem.

        Returns:
            Dict with sync result: skill_id, version_number, version_label, etc.
        """
        container_skill_path = skill_path or f"{SANDBOX_SKILL_BASE}/{skill_name}"

        # Step 1: Read files from sandbox
        files = await self._read_sandbox_files(sandbox_adapter, sandbox_id, container_skill_path)
        if not files:
            return {"error": f"No files found at {container_skill_path} in sandbox"}

        # Step 2: Find and parse SKILL.md
        skill_md_content = files.get("SKILL.md")
        if not skill_md_content:
            return {"error": "SKILL.md not found in skill directory"}

        try:
            parsed = self._parser.parse(skill_md_content)
        except Exception as e:
            return {"error": f"Failed to parse SKILL.md: {e}"}

        # Step 3: Upsert skill to database
        skill = await self._upsert_skill(
            skill_name=parsed.name,
            parsed=parsed,
            tenant_id=tenant_id,
            project_id=project_id,
            skill_md_content=skill_md_content,
        )

        # Step 4: Create version snapshot
        resource_files = {k: v for k, v in files.items() if k != "SKILL.md"}
        version = await self._create_version_snapshot(
            skill=skill,
            skill_md_content=skill_md_content,
            resource_files=resource_files,
            change_summary=change_summary,
            created_by=created_by,
        )

        # Step 5: Update skill's current_version
        skill.current_version = version.version_number
        skill.version_label = version.version_label
        skill.updated_at = datetime.now(timezone.utc)
        await self._skill_repo.update(skill)

        # Step 6: Write to host filesystem
        await self._write_to_host(skill_name, files)

        logger.info(
            f"Skill '{skill_name}' synced: version={version.version_number}, "
            f"label={version.version_label}, files={len(files)}"
        )

        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "version_number": version.version_number,
            "version_label": version.version_label,
            "files_synced": len(files),
            "created_by": created_by,
        }

    async def rollback_to_version(
        self,
        skill_id: str,
        version_number: int,
    ) -> Dict[str, Any]:
        """
        Rollback a skill to a specific version.

        Creates a new version entry recording the rollback action.
        """
        # Get the target version
        target_version = await self._version_repo.get_by_version(skill_id, version_number)
        if not target_version:
            return {"error": f"Version {version_number} not found for skill {skill_id}"}

        # Get the skill
        skill = await self._skill_repo.get_by_id(skill_id)
        if not skill:
            return {"error": f"Skill {skill_id} not found"}

        # Re-parse SKILL.md to update skill fields
        try:
            parsed = self._parser.parse(target_version.skill_md_content)
        except Exception as e:
            return {"error": f"Failed to parse version {version_number} SKILL.md: {e}"}

        # Update skill fields from parsed content
        skill.description = parsed.description
        skill.trigger_patterns = [TriggerPattern(pattern=p) for p in parsed.trigger_patterns]
        skill.tools = parsed.tools
        skill.full_content = target_version.skill_md_content

        # Create new version entry for the rollback
        rollback_summary = f"Rolled back to version {version_number}"
        rollback_version = await self._create_version_snapshot(
            skill=skill,
            skill_md_content=target_version.skill_md_content,
            resource_files=target_version.resource_files,
            change_summary=rollback_summary,
            created_by="rollback",
        )

        # Update skill's current version
        skill.current_version = rollback_version.version_number
        skill.version_label = rollback_version.version_label
        skill.updated_at = datetime.now(timezone.utc)
        await self._skill_repo.update(skill)

        # Write restored files to host filesystem
        all_files = {"SKILL.md": target_version.skill_md_content}
        all_files.update(target_version.resource_files)
        await self._write_to_host(skill.name, all_files)

        logger.info(
            f"Skill '{skill.name}' rolled back to version {version_number}, "
            f"new version={rollback_version.version_number}"
        )

        return {
            "skill_id": skill.id,
            "skill_name": skill.name,
            "rolled_back_to": version_number,
            "new_version_number": rollback_version.version_number,
        }

    async def _read_sandbox_files(
        self,
        sandbox_adapter: Any,
        sandbox_id: str,
        container_path: str,
    ) -> Dict[str, str]:
        """Read all files from a skill directory in the sandbox container."""
        files: Dict[str, str] = {}

        try:
            # List all files
            glob_result = await sandbox_adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="glob",
                arguments={"pattern": "**/*", "path": container_path},
            )

            file_paths = self._extract_file_paths(glob_result)
            if not file_paths:
                logger.warning(f"No files found in sandbox at {container_path}")
                return files

            # Read each file
            for file_path in file_paths:
                try:
                    full_path = (
                        f"{container_path}/{file_path}"
                        if not file_path.startswith("/")
                        else file_path
                    )
                    read_result = await sandbox_adapter.call_tool(
                        sandbox_id=sandbox_id,
                        tool_name="read",
                        arguments={"file_path": full_path},
                    )
                    content = self._extract_content(read_result)
                    if content is not None:
                        # Use relative path as key
                        rel_path = (
                            file_path
                            if not file_path.startswith("/")
                            else file_path.replace(container_path + "/", "", 1)
                        )
                        files[rel_path] = content
                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")

        except Exception as e:
            logger.error(f"Failed to list files in sandbox at {container_path}: {e}")

        return files

    async def _upsert_skill(
        self,
        skill_name: str,
        parsed: Any,
        tenant_id: str,
        project_id: Optional[str],
        skill_md_content: str,
    ) -> Skill:
        """Create or update a skill in the database."""
        existing = await self._skill_repo.get_by_name(tenant_id, skill_name)

        if existing:
            # Update existing skill
            existing.description = parsed.description
            existing.trigger_patterns = [TriggerPattern(pattern=p) for p in parsed.trigger_patterns]
            existing.tools = parsed.tools
            existing.full_content = skill_md_content
            existing.updated_at = datetime.now(timezone.utc)
            if parsed.version:
                existing.version_label = parsed.version
            await self._skill_repo.update(existing)
            return existing
        else:
            # Create new skill
            scope = SkillScope.PROJECT if project_id else SkillScope.TENANT
            skill = Skill.create(
                tenant_id=tenant_id,
                name=skill_name,
                description=parsed.description,
                tools=parsed.tools or ["terminal"],
                trigger_type=TriggerType(parsed.frontmatter.get("trigger_type", "keyword")),
                trigger_patterns=[TriggerPattern(pattern=p) for p in parsed.trigger_patterns],
                project_id=project_id,
                scope=scope,
                full_content=skill_md_content,
                license=parsed.license,
                compatibility=parsed.compatibility,
                allowed_tools_raw=parsed.allowed_tools_raw,
            )
            skill.source = SkillSource.DATABASE
            if parsed.version:
                skill.version_label = parsed.version
            await self._skill_repo.create(skill)
            return skill

    async def _create_version_snapshot(
        self,
        skill: Skill,
        skill_md_content: str,
        resource_files: Dict[str, str],
        change_summary: Optional[str],
        created_by: str,
    ) -> SkillVersion:
        """Create a version snapshot for a skill."""
        # Get next version number
        max_version = await self._version_repo.get_max_version_number(skill.id)
        next_version = max_version + 1

        # Determine version label
        version_label = None
        try:
            parsed = self._parser.parse(skill_md_content)
            version_label = parsed.version
        except Exception:
            pass

        if not version_label:
            version_label = str(next_version)

        # Auto-generate change summary if not provided
        if not change_summary and max_version > 0:
            prev_version = await self._version_repo.get_by_version(skill.id, max_version)
            if prev_version:
                change_summary = self._generate_change_summary(
                    prev_version, skill_md_content, resource_files
                )

        version = SkillVersion(
            id=str(uuid.uuid4()),
            skill_id=skill.id,
            version_number=next_version,
            version_label=version_label,
            skill_md_content=skill_md_content,
            resource_files=resource_files,
            change_summary=change_summary or f"Version {next_version}",
            created_by=created_by,
        )

        await self._version_repo.create(version)
        return version

    def _generate_change_summary(
        self,
        prev_version: SkillVersion,
        new_md_content: str,
        new_resource_files: Dict[str, str],
    ) -> str:
        """Generate a simple change summary by comparing with previous version."""
        changes = []

        if prev_version.skill_md_content != new_md_content:
            changes.append("SKILL.md modified")

        prev_files = set(prev_version.resource_files.keys())
        new_files = set(new_resource_files.keys())

        added = new_files - prev_files
        removed = prev_files - new_files
        common = prev_files & new_files
        modified = {
            f for f in common if prev_version.resource_files.get(f) != new_resource_files.get(f)
        }

        if added:
            changes.append(f"Added: {', '.join(sorted(added))}")
        if removed:
            changes.append(f"Removed: {', '.join(sorted(removed))}")
        if modified:
            changes.append(f"Modified: {', '.join(sorted(modified))}")

        return "; ".join(changes) if changes else "No changes detected"

    async def _write_to_host(self, skill_name: str, files: Dict[str, str]) -> None:
        """Write skill files to host filesystem."""
        skill_dir = self._host_project_path / ".memstack" / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        for rel_path, content in files.items():
            file_path = skill_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Check if content is base64-encoded binary
            ext = Path(rel_path).suffix.lower()
            if ext in BINARY_EXTENSIONS:
                try:
                    binary_data = base64.b64decode(content)
                    file_path.write_bytes(binary_data)
                except Exception:
                    file_path.write_text(content, encoding="utf-8")
            else:
                file_path.write_text(content, encoding="utf-8")

        logger.info(f"Wrote {len(files)} files to {skill_dir}")

    @staticmethod
    def _extract_file_paths(glob_result: Any) -> List[str]:
        """Extract file paths from MCP glob tool result."""
        if isinstance(glob_result, dict):
            # Handle various result formats
            if "files" in glob_result:
                return glob_result["files"]
            if "content" in glob_result:
                content = glob_result["content"]
                if isinstance(content, list):
                    return [
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in content
                        if item
                    ]
                if isinstance(content, str):
                    return [p.strip() for p in content.split("\n") if p.strip()]
            if "result" in glob_result:
                result = glob_result["result"]
                if isinstance(result, list):
                    return result
        if isinstance(glob_result, list):
            return glob_result
        return []

    @staticmethod
    def _extract_content(read_result: Any) -> Optional[str]:
        """Extract text content from MCP read tool result."""
        if isinstance(read_result, dict):
            if "content" in read_result:
                content = read_result["content"]
                if isinstance(content, list):
                    texts = [
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in content
                    ]
                    return "\n".join(texts)
                return str(content)
            if "text" in read_result:
                return read_result["text"]
            if "result" in read_result:
                return str(read_result["result"])
        if isinstance(read_result, str):
            return read_result
        return None
