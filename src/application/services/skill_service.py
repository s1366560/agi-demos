"""
Unified Skill Service.

Coordinates file system and database skill sources, providing a unified
interface for skill operations with progressive loading support.

Three-level scoping for multi-tenant isolation:
- system: Built-in skills shared by all tenants (can be disabled/overridden)
- tenant: Tenant-level skills shared within a tenant
- project: Project-specific skills (highest priority)
"""

import logging
from pathlib import Path

from src.application.services.filesystem_skill_loader import FileSystemSkillLoader
from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus
from src.domain.model.agent.skill_source import SkillSource
from src.domain.model.agent.tenant_skill_config import TenantSkillAction, TenantSkillConfig
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.tenant_skill_config_repository import (
    TenantSkillConfigRepositoryPort,
)

logger = logging.getLogger(__name__)


class SkillService:
    """
    Unified skill service that merges file system and database sources.

    Provides three-level skill loading with priority order:
    1. Project-level skills (highest priority)
    2. Tenant-level skills
    3. System-level skills (lowest priority, can be disabled/overridden per tenant)

    Loading tiers:
    - Tier 1: Skill metadata (name, description) for tool description injection
    - Tier 2: Skill details (triggers, tools) for matching
    - Tier 3: Full content (markdown instructions) for execution

    Skills from higher priority levels can override lower priority skills
    with the same name. Tenant configs can disable or override system skills.
    """

    def __init__(
        self,
        skill_repository: SkillRepositoryPort,
        tenant_skill_config_repository: TenantSkillConfigRepositoryPort | None = None,
        filesystem_loader: FileSystemSkillLoader | None = None,
    ) -> None:
        """
        Initialize the skill service.

        Args:
            skill_repository: Repository for database skills
            tenant_skill_config_repository: Repository for tenant skill configs (optional)
            filesystem_loader: Loader for file system skills (optional)
        """
        self._skill_repo = skill_repository
        self._tenant_config_repo = tenant_skill_config_repository
        self._fs_loader = filesystem_loader
        self._initialized = False

    @classmethod
    def create(
        cls,
        skill_repository: SkillRepositoryPort,
        base_path: Path,
        tenant_id: str,
        project_id: str | None = None,
        tenant_skill_config_repository: TenantSkillConfigRepositoryPort | None = None,
        include_system: bool = True,
    ) -> "SkillService":
        """
        Factory method to create a SkillService with file system support.

        Args:
            skill_repository: Repository for database skills
            base_path: Base path to scan for skills
            tenant_id: Tenant ID
            project_id: Optional project ID
            tenant_skill_config_repository: Repository for tenant skill configs
            include_system: Whether to include system skills

        Returns:
            Configured SkillService instance
        """
        fs_loader = FileSystemSkillLoader(
            base_path=base_path,
            tenant_id=tenant_id,
            project_id=project_id,
            include_system=include_system,
        )
        return cls(
            skill_repository=skill_repository,
            tenant_skill_config_repository=tenant_skill_config_repository,
            filesystem_loader=fs_loader,
        )

    async def initialize(self) -> None:
        """
        Initialize the service by loading file system skills.

        Should be called during application startup.
        """
        if self._initialized:
            return

        if self._fs_loader:
            result = await self._fs_loader.load_all()
            logger.info(
                f"Initialized SkillService with {result.count} file system skills",
                extra={"errors": len(result.errors)},
            )

        self._initialized = True

    async def list_available_skills(
        self,
        tenant_id: str,
        project_id: str | None = None,
        tier: int = 1,
        status: SkillStatus | None = None,
        agent_mode: str = "default",
        skip_database: bool = False,
        scope: SkillScope | None = None,
    ) -> list[Skill]:
        """
        List available skills from all sources with three-level loading.

        Loading order (later overrides earlier):
        1. System skills (from filesystem, filtered by tenant config)
        2. Tenant-level skills (from database or filesystem)
        3. Project-level skills (from database or filesystem, highest priority)

        Args:
            tenant_id: Tenant ID
            project_id: Optional project ID for filtering
            tier: Loading tier (1=metadata, 2=details, 3=full content)
            status: Optional status filter
            agent_mode: Agent mode for filtering (e.g., "default", "plan", "explore")
            skip_database: If True, only load from file system (avoids DB session issues)
            scope: Optional scope filter (SYSTEM, TENANT, PROJECT)

        Returns:
            List of Skill entities (content level depends on tier)
        """
        skills_by_name: dict[str, Skill] = {}

        # Get tenant skill configs for system skill filtering
        tenant_configs: dict[str, TenantSkillConfig] = {}
        if self._tenant_config_repo and not skip_database:
            try:
                tenant_configs = await self._tenant_config_repo.get_configs_map(tenant_id)
            except Exception as e:
                logger.warning(f"Failed to load tenant skill configs: {e}")

        # Step 1: Load system skills (lowest priority)
        if scope is None or scope == SkillScope.SYSTEM:
            await self._load_system_skills(
                tenant_id=tenant_id,
                skills_by_name=skills_by_name,
                tenant_configs=tenant_configs,
                status=status,
                agent_mode=agent_mode,
                tier=tier,
            )

        # Step 2: Load tenant-level skills (can override system skills)
        if scope is None or scope == SkillScope.TENANT:
            await self._load_tenant_skills(
                tenant_id=tenant_id,
                skills_by_name=skills_by_name,
                tenant_configs=tenant_configs,
                status=status,
                agent_mode=agent_mode,
                tier=tier,
                skip_database=skip_database,
            )

        # Step 3: Load project-level skills (highest priority)
        if project_id and (scope is None or scope == SkillScope.PROJECT):
            await self._load_project_skills(
                tenant_id=tenant_id,
                project_id=project_id,
                skills_by_name=skills_by_name,
                status=status,
                agent_mode=agent_mode,
                tier=tier,
                skip_database=skip_database,
            )

        return list(skills_by_name.values())

    async def _load_system_skills(
        self,
        tenant_id: str,
        skills_by_name: dict[str, Skill],
        tenant_configs: dict[str, TenantSkillConfig],
        status: SkillStatus | None,
        agent_mode: str,
        tier: int,
    ) -> None:
        """Load system skills, filtered by tenant config."""
        if not self._fs_loader:
            return

        # Set tenant_id before loading (required for Skill domain validation)
        self._fs_loader.set_tenant_id(tenant_id)

        if not self._initialized:
            await self.initialize()

        system_skills = self._fs_loader.get_cached_system_skills()

        for skill in system_skills:
            # Apply tenant config filtering
            config = tenant_configs.get(skill.name)
            if config:
                if config.is_disabled():
                    # Skip disabled system skills
                    logger.debug(f"System skill '{skill.name}' disabled for tenant {tenant_id}")
                    continue
                # Override handled when loading tenant skills

            if status and skill.status != status:
                continue
            if not skill.is_accessible_by_agent(agent_mode):
                continue

            skill_for_tier = self._apply_tier(skill, tier)
            skills_by_name[skill.name] = skill_for_tier

    async def _load_tenant_skills(
        self,
        tenant_id: str,
        skills_by_name: dict[str, Skill],
        tenant_configs: dict[str, TenantSkillConfig],
        status: SkillStatus | None,
        agent_mode: str,
        tier: int,
        skip_database: bool,
    ) -> None:
        """Load tenant-level skills, including overrides for system skills."""
        # Load from file system (tenant scope)
        if self._fs_loader:
            fs_skills = [
                s
                for s in self._fs_loader.get_cached_skills(include_system=False)
                if s.scope == SkillScope.TENANT
            ]

            for skill in fs_skills:
                if status and skill.status != status:
                    continue
                if not skill.is_accessible_by_agent(agent_mode):
                    continue

                skill_for_tier = self._apply_tier(skill, tier)
                skills_by_name[skill.name] = skill_for_tier

        # Load from database (tenant scope)
        if not skip_database:
            try:
                db_skills = await self._skill_repo.list_by_tenant(
                    tenant_id=tenant_id,
                    status=status,
                    scope=SkillScope.TENANT,
                    limit=1000,
                )

                for skill in db_skills:
                    # Skip if already have this skill from filesystem (filesystem takes priority)
                    if skill.name in skills_by_name:
                        existing = skills_by_name[skill.name]
                        if existing.source == SkillSource.FILESYSTEM:
                            continue

                    if not skill.is_accessible_by_agent(agent_mode):
                        continue

                    skill_for_tier = self._apply_tier(skill, tier)
                    skills_by_name[skill.name] = skill_for_tier
            except Exception as e:
                logger.warning(f"Failed to load tenant skills from database: {e}")

        # Handle system skill overrides
        for config in tenant_configs.values():
            if config.is_override() and config.override_skill_id:
                try:
                    override_skill = await self._skill_repo.get_by_id(config.override_skill_id)
                    if override_skill and override_skill.is_accessible_by_agent(agent_mode):
                        # Replace system skill with override
                        skill_for_tier = self._apply_tier(override_skill, tier)
                        skills_by_name[config.system_skill_name] = skill_for_tier
                        logger.debug(
                            f"System skill '{config.system_skill_name}' overridden "
                            f"with '{override_skill.name}' for tenant {config.tenant_id}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to load override skill {config.override_skill_id}: {e}")

    async def _load_project_skills(
        self,
        tenant_id: str,
        project_id: str,
        skills_by_name: dict[str, Skill],
        status: SkillStatus | None,
        agent_mode: str,
        tier: int,
        skip_database: bool,
    ) -> None:
        """Load project-level skills (highest priority)."""
        # Load from file system (project scope)
        if self._fs_loader:
            fs_skills = [
                s
                for s in self._fs_loader.get_cached_skills(include_system=False)
                if s.scope == SkillScope.PROJECT and s.project_id == project_id
            ]

            for skill in fs_skills:
                if status and skill.status != status:
                    continue
                if not skill.is_accessible_by_agent(agent_mode):
                    continue

                skill_for_tier = self._apply_tier(skill, tier)
                skills_by_name[skill.name] = skill_for_tier

        # Load from database (project scope)
        if not skip_database:
            try:
                db_skills = await self._skill_repo.list_by_project(
                    project_id=project_id,
                    status=status,
                    scope=SkillScope.PROJECT,
                )

                for skill in db_skills:
                    # Skip if already have this skill from filesystem (filesystem takes priority)
                    if skill.name in skills_by_name:
                        existing = skills_by_name[skill.name]
                        if (
                            existing.source == SkillSource.FILESYSTEM
                            and existing.scope == SkillScope.PROJECT
                        ):
                            continue

                    if not skill.is_accessible_by_agent(agent_mode):
                        continue

                    skill_for_tier = self._apply_tier(skill, tier)
                    skills_by_name[skill.name] = skill_for_tier
            except Exception as e:
                logger.warning(f"Failed to load project skills from database: {e}")

    def _apply_tier(self, skill: Skill, tier: int) -> Skill:
        """
        Apply tier-based content filtering.

        Tier 1: Name, description, and tools only (for tool description)
        Tier 2: Include triggers and metadata (for matching)
        Tier 3: Full content (for execution)

        Note: tools are always included as they are required by the Skill domain model.
        """
        if tier >= 3:
            return skill

        # Create a copy with limited content
        # Note: tools are always included (required by domain model validation)
        return Skill(
            id=skill.id,
            tenant_id=skill.tenant_id,
            project_id=skill.project_id,
            name=skill.name,
            description=skill.description,
            trigger_type=skill.trigger_type,
            trigger_patterns=skill.trigger_patterns if tier >= 2 else [],
            tools=skill.tools,  # Always include tools (required field)
            prompt_template=None if tier < 3 else skill.prompt_template,
            status=skill.status,
            success_count=skill.success_count,
            failure_count=skill.failure_count,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            metadata=skill.metadata if tier >= 2 else None,
            source=skill.source,
            file_path=skill.file_path if tier >= 2 else None,
            full_content=None if tier < 3 else skill.full_content,
            agent_modes=skill.agent_modes,  # Always include agent_modes
            scope=skill.scope,
            is_system_skill=skill.is_system_skill,
        )

    async def get_skill_by_name(
        self,
        tenant_id: str,
        skill_name: str,
    ) -> Skill | None:
        """
        Get a skill by name.

        Args:
            tenant_id: Tenant ID
            skill_name: Name of the skill

        Returns:
            Skill entity or None if not found
        """
        # Check file system first
        if self._fs_loader:
            if not self._initialized:
                await self.initialize()

            for skill in self._fs_loader.get_cached_skills():
                if skill.name == skill_name:
                    return skill

        # Fall back to database
        return await self._skill_repo.get_by_name(tenant_id, skill_name)

    async def load_skill_content(
        self,
        tenant_id: str,
        skill_name: str,
    ) -> str | None:
        """
        Load the full content of a skill (Tier 3).

        Args:
            tenant_id: Tenant ID
            skill_name: Name of the skill

        Returns:
            Full markdown content or None if not found
        """
        # Try file system first
        if self._fs_loader:
            content = await self._fs_loader.load_skill_content(skill_name)
            if content:
                return content

        # Fall back to database
        skill = await self._skill_repo.get_by_name(tenant_id, skill_name)
        if skill:
            # Use full_content if available, otherwise prompt_template
            return skill.full_content or skill.prompt_template

        return None

    async def sync_filesystem_skills(
        self,
        tenant_id: str,
    ) -> int:
        """
        Sync file system skills to database.

        Creates or updates database records for file system skills.
        Useful for tracking usage statistics across restarts.

        Args:
            tenant_id: Tenant ID

        Returns:
            Number of skills synced
        """
        if not self._fs_loader:
            return 0

        # Force reload from file system
        result = await self._fs_loader.load_all(force_reload=True)
        synced_count = 0

        for loaded in result.skills:
            skill = loaded.skill

            # Check if exists in database
            existing = await self._skill_repo.get_by_name(tenant_id, skill.name)

            if existing:
                # Update existing (preserve usage stats)
                updated_skill = Skill(
                    id=existing.id,
                    tenant_id=existing.tenant_id,
                    project_id=skill.project_id or existing.project_id,
                    name=skill.name,
                    description=skill.description,
                    trigger_type=skill.trigger_type,
                    trigger_patterns=skill.trigger_patterns,
                    tools=skill.tools,
                    prompt_template=skill.prompt_template,
                    status=skill.status,
                    success_count=existing.success_count,  # Preserve
                    failure_count=existing.failure_count,  # Preserve
                    created_at=existing.created_at,
                    updated_at=skill.updated_at,
                    metadata={
                        **(existing.metadata or {}),
                        **(skill.metadata or {}),
                        "synced_from_filesystem": True,
                    },
                    source=SkillSource.HYBRID,
                    file_path=skill.file_path,
                    full_content=skill.full_content,
                    agent_modes=skill.agent_modes,
                    scope=skill.scope,
                    is_system_skill=skill.is_system_skill,
                )
                await self._skill_repo.update(updated_skill)
            else:
                # Create new
                skill_with_source = Skill(
                    id=skill.id,
                    tenant_id=tenant_id,
                    project_id=skill.project_id,
                    name=skill.name,
                    description=skill.description,
                    trigger_type=skill.trigger_type,
                    trigger_patterns=skill.trigger_patterns,
                    tools=skill.tools,
                    prompt_template=skill.prompt_template,
                    status=skill.status,
                    success_count=0,
                    failure_count=0,
                    metadata={
                        **(skill.metadata or {}),
                        "synced_from_filesystem": True,
                    },
                    source=SkillSource.HYBRID,
                    file_path=skill.file_path,
                    full_content=skill.full_content,
                    agent_modes=skill.agent_modes,
                    scope=skill.scope,
                    is_system_skill=skill.is_system_skill,
                )
                await self._skill_repo.create(skill_with_source)

            synced_count += 1

        logger.info(f"Synced {synced_count} skills from filesystem to database")
        return synced_count

    async def find_matching_skills(
        self,
        tenant_id: str,
        query: str,
        threshold: float = 0.5,
        limit: int = 5,
    ) -> list[Skill]:
        """
        Find skills that match a query.

        Searches both file system and database skills.

        Args:
            tenant_id: Tenant ID
            query: Query string to match
            threshold: Minimum match score (0-1)
            limit: Maximum number of results

        Returns:
            List of matching skills sorted by score
        """
        all_skills = await self.list_available_skills(
            tenant_id=tenant_id,
            tier=2,  # Need triggers for matching
            status=SkillStatus.ACTIVE,
        )

        # Score and filter skills
        scored_skills = []
        for skill in all_skills:
            score = skill.matches_query(query)
            if score >= threshold:
                scored_skills.append((score, skill))

        # Sort by score descending
        scored_skills.sort(key=lambda x: x[0], reverse=True)

        return [skill for _, skill in scored_skills[:limit]]

    async def record_skill_usage(
        self,
        tenant_id: str,
        skill_name: str,
        success: bool,
    ) -> Skill | None:
        """
        Record usage of a skill.

        Args:
            tenant_id: Tenant ID
            skill_name: Name of the skill
            success: Whether the execution was successful

        Returns:
            Updated skill or None if not found
        """
        skill = await self._skill_repo.get_by_name(tenant_id, skill_name)
        if not skill:
            # Try to sync from filesystem first
            if self._fs_loader:
                fs_result = await self._fs_loader.load_all()
                loaded = fs_result.get_skill_by_name(skill_name)
                if loaded:
                    await self._skill_repo.create(loaded.skill)
                    skill = loaded.skill

        if skill:
            return await self._skill_repo.increment_usage(skill.id, success)

        return None

    def invalidate_cache(self) -> None:
        """Invalidate caches, forcing reload on next access."""
        if self._fs_loader:
            self._fs_loader.invalidate_cache()
        self._initialized = False

    def format_skill_list_for_tool(self, skills: list[Skill]) -> str:
        """
        Format skills list for injection into tool description.

        Creates a concise list suitable for LLM tool description.

        Args:
            skills: List of skills (Tier 1 metadata)

        Returns:
            Formatted string for tool description
        """
        if not skills:
            return "No skills currently available."

        lines = [
            "Load a skill to get detailed instructions for specific tasks.",
            "Available skills:",
        ]

        for skill in skills:
            lines.append(f"  - {skill.name}: {skill.description}")

        lines.append("")
        lines.append("Use the skill name as the parameter when loading.")

        return "\n".join(lines)

    # =========================================================================
    # Tenant Skill Config Management
    # =========================================================================

    async def list_system_skills(self, tenant_id: str, tier: int = 1) -> list[Skill]:
        """
        List all system skills.

        Args:
            tenant_id: Tenant ID (for skill domain validation)
            tier: Loading tier (1=metadata, 2=details, 3=full content)

        Returns:
            List of system Skill entities
        """
        return await self.list_available_skills(
            tenant_id=tenant_id,
            tier=tier,
            scope=SkillScope.SYSTEM,
        )

    async def disable_system_skill(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> TenantSkillConfig:
        """
        Disable a system skill for a tenant.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill to disable

        Returns:
            Created TenantSkillConfig

        Raises:
            ValueError: If tenant config repo not available or config already exists
        """
        if not self._tenant_config_repo:
            raise ValueError("Tenant skill config repository not available")

        # Check if config already exists
        existing = await self._tenant_config_repo.get_by_tenant_and_skill(
            tenant_id, system_skill_name
        )
        if existing:
            # Update existing config
            existing.action = TenantSkillAction.DISABLE
            existing.override_skill_id = None
            return await self._tenant_config_repo.update(existing)

        # Create new config
        config = TenantSkillConfig.create_disable(
            tenant_id=tenant_id,
            system_skill_name=system_skill_name,
        )
        return await self._tenant_config_repo.create(config)

    async def enable_system_skill(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> None:
        """
        Enable a previously disabled system skill for a tenant.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill to enable

        Raises:
            ValueError: If tenant config repo not available
        """
        if not self._tenant_config_repo:
            raise ValueError("Tenant skill config repository not available")

        await self._tenant_config_repo.delete_by_tenant_and_skill(tenant_id, system_skill_name)

    async def override_system_skill(
        self,
        tenant_id: str,
        system_skill_name: str,
        override_skill_id: str,
    ) -> TenantSkillConfig:
        """
        Override a system skill with a tenant skill.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill to override
            override_skill_id: ID of the tenant skill to use instead

        Returns:
            Created TenantSkillConfig

        Raises:
            ValueError: If tenant config repo not available or override skill not found
        """
        if not self._tenant_config_repo:
            raise ValueError("Tenant skill config repository not available")

        # Verify override skill exists
        override_skill = await self._skill_repo.get_by_id(override_skill_id)
        if not override_skill:
            raise ValueError(f"Override skill not found: {override_skill_id}")
        if override_skill.tenant_id != tenant_id:
            raise ValueError("Override skill must belong to the same tenant")

        # Check if config already exists
        existing = await self._tenant_config_repo.get_by_tenant_and_skill(
            tenant_id, system_skill_name
        )
        if existing:
            # Update existing config
            existing.action = TenantSkillAction.OVERRIDE
            existing.override_skill_id = override_skill_id
            return await self._tenant_config_repo.update(existing)

        # Create new config
        config = TenantSkillConfig.create_override(
            tenant_id=tenant_id,
            system_skill_name=system_skill_name,
            override_skill_id=override_skill_id,
        )
        return await self._tenant_config_repo.create(config)

    async def list_tenant_skill_configs(
        self,
        tenant_id: str,
    ) -> list[TenantSkillConfig]:
        """
        List all skill configs for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of TenantSkillConfig entities
        """
        if not self._tenant_config_repo:
            return []

        return await self._tenant_config_repo.list_by_tenant(tenant_id)

    async def get_tenant_skill_config(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> TenantSkillConfig | None:
        """
        Get a specific tenant skill config.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill

        Returns:
            TenantSkillConfig if found, None otherwise
        """
        if not self._tenant_config_repo:
            return None

        return await self._tenant_config_repo.get_by_tenant_and_skill(tenant_id, system_skill_name)

    async def is_system_skill_disabled(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> bool:
        """
        Check if a system skill is disabled for a tenant.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill

        Returns:
            True if the skill is disabled
        """
        config = await self.get_tenant_skill_config(tenant_id, system_skill_name)
        return config is not None and config.is_disabled()

    async def create_skill(
        self,
        tenant_id: str,
        name: str,
        description: str,
        tools: list[str],
        project_id: str | None = None,
        prompt_template: str | None = None,
        full_content: str | None = None,
        scope: SkillScope = SkillScope.TENANT,
    ) -> Skill:
        """
        Create a new skill in the database.

        Args:
            tenant_id: Tenant ID
            name: Skill name
            description: Skill description
            tools: List of tool names
            project_id: Optional project ID (required for PROJECT scope)
            prompt_template: Optional prompt template
            full_content: Optional full SKILL.md content
            scope: Skill scope (TENANT or PROJECT, cannot create SYSTEM)

        Returns:
            Created Skill entity

        Raises:
            ValueError: If trying to create a SYSTEM scope skill
        """
        if scope == SkillScope.SYSTEM:
            raise ValueError("Cannot create system-level skills via API")

        if scope == SkillScope.PROJECT and not project_id:
            raise ValueError("project_id is required for project-scoped skills")

        skill = Skill.create(
            tenant_id=tenant_id,
            name=name,
            description=description,
            tools=tools,
            project_id=project_id,
            prompt_template=prompt_template,
            full_content=full_content,
            scope=scope,
            is_system_skill=False,
        )

        return await self._skill_repo.create(skill)

    async def update_skill_content(
        self,
        skill_id: str,
        full_content: str,
    ) -> Skill:
        """
        Update a skill's full content.

        Args:
            skill_id: Skill ID
            full_content: New full SKILL.md content

        Returns:
            Updated Skill entity

        Raises:
            ValueError: If skill not found or is a system skill
        """
        skill = await self._skill_repo.get_by_id(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if skill.is_system_skill:
            raise ValueError("Cannot modify system skills")

        skill.full_content = full_content
        skill.prompt_template = full_content  # Keep in sync

        return await self._skill_repo.update(skill)

    async def delete_skill(
        self,
        skill_id: str,
    ) -> None:
        """
        Delete a skill.

        Args:
            skill_id: Skill ID

        Raises:
            ValueError: If skill not found or is a system skill
        """
        skill = await self._skill_repo.get_by_id(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        if skill.is_system_skill:
            raise ValueError("Cannot delete system skills")

        await self._skill_repo.delete(skill_id)
