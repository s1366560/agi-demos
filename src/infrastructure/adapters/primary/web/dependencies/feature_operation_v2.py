"""Authorize feature operations against the accepted private-scope publication."""

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from src.domain.model.plugins.generated_v2 import ProfileEntryV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies.plugin_scope_auth_v2 import (
    resolve_plugin_read_scope_v2,
)
from src.infrastructure.adapters.primary.web.startup.scoped_profile_runtime_v2 import (
    ScopedProfileRuntimeV2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error


async def require_feature_operation_v2(
    *,
    request: HTTPConnection,
    db: AsyncSession,
    current_user: User,
    feature_ids: tuple[str, ...],
    scope: ScopeV2,
) -> None:
    """Admit one new operation; an in-flight operation keeps its existing lease."""
    authorized = await resolve_plugin_read_scope_v2(
        db, current_user=current_user, requested_scope=scope
    )
    runtime = getattr(request.app.state, "scoped_profile_runtime_v2", None)
    if not isinstance(runtime, ScopedProfileRuntimeV2):
        raise RuntimeV2Error("scoped_runtime_missing", "feature configuration is unavailable")
    service = runtime.instances(authorized)
    await service.initialize(current_user.id)
    snapshot = await service.effective_snapshot()
    entries = {entry.entry_id: entry for entry in snapshot.entries}
    for feature_id in feature_ids:
        entry = entries.get(f"builtin-web-feature-{feature_id}")
        if entry is not None and _entry_is_enabled(entry.entry_id, entries):
            continue
        legacy = entries.get("builtin-web-default-routes")
        if entry is None and legacy is not None and _entry_is_enabled(legacy.entry_id, entries):
            continue
        raise RuntimeV2Error("feature_disabled", "feature is disabled in the accepted scope")


def _entry_is_enabled(entry_id: str, entries: dict[str, ProfileEntryV2]) -> bool:
    seen: set[str] = set()
    current: str | None = entry_id
    while current is not None:
        if current in seen:
            return False
        seen.add(current)
        entry = entries.get(current)
        if entry is None or not entry.enabled:
            return False
        current = getattr(entry, "parent_entry_id", None)
    return True
