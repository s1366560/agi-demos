"""Resolve plugin-owned skills from current scope authority before each invocation."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.agent.skill import Skill
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill
from src.infrastructure.adapters.secondary.persistence.plugin_marketplace_models_v3 import (
    MarketplaceRecordV3,
)
from src.infrastructure.adapters.secondary.persistence.sql_skill_repository import (
    SqlSkillRepository,
)


async def resolve_marketplace_skill(
    tenant_id: str,
    project_id: str,
    name: str,
    *,
    sessions: async_sessionmaker[AsyncSession] = async_session_factory,
) -> Skill | None:
    """Return one immutable invocation snapshot, or reject a retired owned name.

    User-created same-name resources remain independent of historical installations.
    No cache or filesystem fallback may revive a disabled or removed plugin resource.
    """
    async with sessions() as db:
        skills = list(
            await db.scalars(
                select(DBSkill).where(
                    DBSkill.tenant_id == tenant_id,
                    DBSkill.name == name,
                    or_(DBSkill.project_id == project_id, DBSkill.project_id.is_(None)),
                )
            )
        )
        skills.sort(key=lambda skill: skill.project_id == project_id, reverse=True)
        installations = list(
            await db.scalars(
                select(MarketplaceRecordV3).where(
                    MarketplaceRecordV3.kind == "installation",
                    MarketplaceRecordV3.tenant_id == tenant_id,
                    MarketplaceRecordV3.project_id.in_([project_id, ""]),
                )
            )
        )
        for skill in skills:
            owner = (skill.metadata_json or {}).get("marketplace_installation_id")
            if not owner:
                return None
            installation = next((row for row in installations if row.id == owner), None)
            if (
                installation is not None
                and installation.project_id == (skill.project_id or "")
                and installation.payload.get("status") == "enabled"
                and skill.id in installation.payload.get("owned_skills", [])
                and skill.status == "active"
            ):
                return await SqlSkillRepository(db).get_by_id(skill.id)
            raise ValueError("Plugin skill is disabled or unavailable")
        if any(
            resource.get("name") == name
            for row in installations
            for resource in row.payload.get("package", {}).get("resources", {}).get("skills", [])
        ):
            raise ValueError("Plugin skill is disabled or unavailable")
        return None
