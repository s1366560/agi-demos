"""Authorize an exact non-root desired reference without granting runtime trust."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import DesiredBundleSetV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    resolve_plugin_publication_scope_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_repository_v2 import (
    PlatformPluginProfileSourceRepositoryV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


async def authorize_desired_profile_source_v2(
    db: AsyncSession, *, user: User, scope: ScopeV2, desired: DesiredBundleSetV2
) -> ScopeV2:
    canonical = await resolve_plugin_publication_scope_v2(
        db, current_user=user, requested_scope=scope
    )
    reference = desired.profile_source
    source = await PlatformPluginProfileSourceRepositoryV2(db).read_exact(
        scope=canonical,
        source_id=reference.source_id,
        revision=reference.revision,
        digest=reference.digest,
    )
    if source is None:
        raise RuntimeV2Error(
            "profile_source_unavailable", "exact scoped profile source is unavailable"
        )
    return canonical
