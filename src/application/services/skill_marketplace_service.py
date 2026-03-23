"""Skill Marketplace service -- catalog browsing, install, and uninstall."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.domain.model.agent.skill.skill import Skill, SkillScope, SkillSource, SkillStatus
from src.domain.model.agent.skill.skill_catalog import SkillCatalogEntry
from src.domain.model.agent.tenant_skill_config import TenantSkillAction, TenantSkillConfig
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.domain.ports.repositories.tenant_skill_config_repository import (
    TenantSkillConfigRepositoryPort,
)

logger = logging.getLogger(__name__)


def _skill_to_catalog_entry(skill: Skill) -> SkillCatalogEntry:
    """Project a Skill domain entity into a read-only SkillCatalogEntry."""
    trigger_keywords = tuple(tp.pattern for tp in skill.trigger_patterns)

    metadata = skill.metadata or {}

    source_map = {
        SkillSource.FILESYSTEM: "builtin",
        SkillSource.DATABASE: "marketplace",
        SkillSource.HYBRID: "marketplace",
    }
    install_source = source_map.get(skill.source, "custom")
    if skill.is_system_skill:
        install_source = "builtin"

    return SkillCatalogEntry(
        id=skill.id,
        name=skill.name,
        version=skill.version_label or "1.0.0",
        description=skill.description,
        author=metadata.get("author", "system"),
        category=metadata.get("category", "general"),
        tags=tuple(metadata.get("tags", ())),
        trigger_keywords=trigger_keywords,
        install_source=install_source,
        download_count=skill.usage_count,
        rating=float(metadata.get("rating", 0.0)),
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


class SkillMarketplaceService:
    """Browse, install, and uninstall skills from the marketplace catalog.

    The catalog is a read-only projection over the existing skill
    infrastructure.  "Installing" a skill means enabling it for a
    tenant via TenantSkillConfig; "uninstalling" disables it.
    """

    def __init__(
        self,
        skill_repo: SkillRepositoryPort,
        tenant_skill_config_repo: TenantSkillConfigRepositoryPort,
    ) -> None:
        self._skill_repo = skill_repo
        self._tenant_config_repo = tenant_skill_config_repo

    async def list_catalog(
        self,
        category: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SkillCatalogEntry], int]:
        """Return a paginated catalog of active skills.

        Args:
            category: Optional category filter.
            search: Optional free-text search against name/description.
            page: 1-based page number.
            page_size: Items per page.

        Returns:
            (entries, total_count) tuple.
        """
        skills = await self._skill_repo.list_by_tenant(
            tenant_id="__system__",
            status=SkillStatus.ACTIVE,
            scope=SkillScope.SYSTEM,
            limit=1000,
        )

        tenant_skills = await self._skill_repo.list_by_tenant(
            tenant_id="__system__",
            status=SkillStatus.ACTIVE,
            scope=SkillScope.TENANT,
            limit=1000,
        )
        skills.extend(tenant_skills)

        entries = [_skill_to_catalog_entry(s) for s in skills]

        if category:
            lower_cat = category.lower()
            entries = [e for e in entries if e.category.lower() == lower_cat]

        if search:
            lower_q = search.lower()
            entries = [
                e
                for e in entries
                if lower_q in e.name.lower()
                or lower_q in e.description.lower()
                or any(lower_q in t.lower() for t in e.tags)
            ]

        total = len(entries)

        start = (page - 1) * page_size
        end = start + page_size
        return entries[start:end], total

    async def get_entry(self, skill_id: str) -> SkillCatalogEntry | None:
        """Return a single catalog entry by skill ID."""
        skill = await self._skill_repo.get_by_id(skill_id)
        if skill is None:
            return None
        return _skill_to_catalog_entry(skill)

    async def install_skill(self, tenant_id: str, skill_id: str) -> bool:
        """Enable a marketplace skill for a tenant.

        If the skill was previously disabled via TenantSkillConfig,
        the config record is removed so the skill becomes active again.

        Returns:
            True if the skill was successfully installed/enabled.
        """
        skill = await self._skill_repo.get_by_id(skill_id)
        if skill is None:
            return False

        existing = await self._tenant_config_repo.get_by_tenant_and_skill(tenant_id, skill.name)
        if existing and existing.is_disabled():
            await self._tenant_config_repo.delete(existing.id)
            logger.info(
                "Marketplace install: re-enabled skill '%s' for tenant %s",
                skill.name,
                tenant_id,
            )

        return True

    async def uninstall_skill(self, tenant_id: str, skill_id: str) -> bool:
        """Disable a marketplace skill for a tenant.

        Creates a DISABLE TenantSkillConfig so the skill is excluded
        from the tenant's available skills.

        Returns:
            True if the skill was successfully uninstalled/disabled.
        """
        skill = await self._skill_repo.get_by_id(skill_id)
        if skill is None:
            return False

        existing = await self._tenant_config_repo.get_by_tenant_and_skill(tenant_id, skill.name)
        if existing:
            if existing.is_disabled():
                return True
            existing.action = TenantSkillAction.DISABLE
            existing.override_skill_id = None
            existing.updated_at = datetime.now(UTC)
            await self._tenant_config_repo.update(existing)
        else:
            config = TenantSkillConfig.create_disable(
                tenant_id=tenant_id,
                system_skill_name=skill.name,
            )
            await self._tenant_config_repo.create(config)

        logger.info(
            "Marketplace uninstall: disabled skill '%s' for tenant %s",
            skill.name,
            tenant_id,
        )
        return True

    async def list_installed(self, tenant_id: str) -> list[SkillCatalogEntry]:
        """Return catalog entries for all skills active for a tenant.

        Skills that are disabled via TenantSkillConfig are excluded.
        """
        skills = await self._skill_repo.list_by_tenant(
            tenant_id=tenant_id,
            status=SkillStatus.ACTIVE,
            limit=1000,
        )

        disabled_configs = await self._tenant_config_repo.get_configs_map(tenant_id)
        disabled_names = {name for name, cfg in disabled_configs.items() if cfg.is_disabled()}

        return [_skill_to_catalog_entry(s) for s in skills if s.name not in disabled_names]
