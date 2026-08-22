"""Append-only, scope-private DesiredBundleSetV2 persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import DesiredBundleSetV2, ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2DesiredBundleSetModel,
)
from src.infrastructure.plugins.v2.protocol import (
    PluginProtocolV2Error,
    desired_bundle_set_v2_to_payload,
    parse_desired_bundle_set_v2,
)
from src.infrastructure.plugins.v2.scope import scope_key_v2, validate_scope_v2


class PlatformPluginDesiredBundleSetV2Error(ValueError):
    """Stable desired-state conflict or storage-integrity failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, kw_only=True)
class PlatformPluginDesiredBundleSetRecordV2:
    """One immutable desired-set revision and its scope/audit metadata."""

    record_id: str
    scope: ScopeV2
    desired_set: DesiredBundleSetV2
    actor_id: str | None
    created_at: datetime


class PlatformPluginDesiredBundleSetRepositoryV2:
    """Persist monotonic desired-set revisions without touching v1 desired rows."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def record_desired_set(
        self,
        *,
        scope: ScopeV2,
        desired_set: DesiredBundleSetV2,
        expected_revision: int | None,
        actor_id: str | None,
    ) -> PlatformPluginDesiredBundleSetRecordV2:
        """Compare-and-swap one complete desired state and append its immutable revision."""
        canonical_scope = self._validated_scope(scope)
        validated_desired = parse_desired_bundle_set_v2(
            desired_bundle_set_v2_to_payload(desired_set)
        )
        payload = desired_bundle_set_v2_to_payload(validated_desired)
        current = await self._current_model(canonical_scope, for_update=True)
        if current is not None and current.payload == payload:
            return self._record(current)

        current_revision = None if current is None else current.revision
        if expected_revision != current_revision:
            raise PlatformPluginDesiredBundleSetV2Error(
                "desired_set_head_conflict",
                "expected desired-set revision does not match the current scope head",
            )
        if current is not None:
            if validated_desired.desired_set_id != current.desired_set_id:
                raise PlatformPluginDesiredBundleSetV2Error(
                    "desired_set_identity_conflict",
                    "desired_set_id cannot change within one scope history",
                )
            if validated_desired.revision != current.revision + 1:
                raise PlatformPluginDesiredBundleSetV2Error(
                    "desired_set_revision_gap",
                    "desired-set revisions must advance by exactly one",
                )

        model = PlatformPluginV2DesiredBundleSetModel(
            id=PlatformPluginV2DesiredBundleSetModel.generate_id(),
            scope_key=scope_key_v2(canonical_scope),
            scope_kind=canonical_scope.kind.value,
            tenant_id=canonical_scope.tenant_id,
            project_id=canonical_scope.project_id,
            session_id=canonical_scope.session_id,
            desired_set_id=validated_desired.desired_set_id,
            revision=validated_desired.revision,
            digest=validated_desired.digest,
            payload=payload,
            actor_id=actor_id,
            created_at=datetime.now(UTC),
        )
        self._session.add(model)
        await self._session.flush()
        return self._record(model)

    async def current_desired_set(
        self,
        scope: ScopeV2,
    ) -> PlatformPluginDesiredBundleSetRecordV2 | None:
        """Return the latest immutable revision for one exact scope."""
        canonical_scope = self._validated_scope(scope)
        model = await self._current_model(canonical_scope, for_update=False)
        return None if model is None else self._record(model)

    async def list_history(
        self,
        scope: ScopeV2,
        *,
        limit: int = 100,
    ) -> list[PlatformPluginDesiredBundleSetRecordV2]:
        """Return newest-first desired-state history for one exact scope."""
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("desired-set history limit must be between 1 and 1000")
        canonical_scope = self._validated_scope(scope)
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2DesiredBundleSetModel)
                .where(
                    PlatformPluginV2DesiredBundleSetModel.scope_key == scope_key_v2(canonical_scope)
                )
                .order_by(
                    PlatformPluginV2DesiredBundleSetModel.revision.desc(),
                    PlatformPluginV2DesiredBundleSetModel.id.desc(),
                )
                .limit(limit)
            )
        )
        return [self._record(model) for model in result.scalars().all()]

    async def _current_model(
        self,
        scope: ScopeV2,
        *,
        for_update: bool,
    ) -> PlatformPluginV2DesiredBundleSetModel | None:
        statement = (
            select(PlatformPluginV2DesiredBundleSetModel)
            .where(PlatformPluginV2DesiredBundleSetModel.scope_key == scope_key_v2(scope))
            .order_by(
                PlatformPluginV2DesiredBundleSetModel.revision.desc(),
                PlatformPluginV2DesiredBundleSetModel.id.desc(),
            )
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(refresh_select_statement(statement))
        return result.scalars().first()

    def _record(
        self,
        model: PlatformPluginV2DesiredBundleSetModel,
    ) -> PlatformPluginDesiredBundleSetRecordV2:
        try:
            scope = validate_scope_v2(
                ScopeV2(
                    kind=ScopeKindV2(model.scope_kind),
                    tenant_id=model.tenant_id,
                    project_id=model.project_id,
                    session_id=model.session_id,
                )
            )
            desired_set = parse_desired_bundle_set_v2(model.payload)
        except (PluginProtocolV2Error, ValueError) as exc:
            raise PlatformPluginDesiredBundleSetV2Error(
                "desired_set_storage_corrupt",
                "stored desired-set record is invalid",
            ) from exc
        exact = (model.desired_set_id, model.revision, model.digest)
        parsed = (desired_set.desired_set_id, desired_set.revision, desired_set.digest)
        if exact != parsed or model.scope_key != scope_key_v2(scope):
            raise PlatformPluginDesiredBundleSetV2Error(
                "desired_set_storage_corrupt",
                "stored desired-set columns differ from their payload",
            )
        return PlatformPluginDesiredBundleSetRecordV2(
            record_id=model.id,
            scope=scope,
            desired_set=desired_set,
            actor_id=model.actor_id,
            created_at=self._as_utc(model.created_at),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _validated_scope(scope: ScopeV2) -> ScopeV2:
        try:
            return validate_scope_v2(scope)
        except PluginProtocolV2Error as exc:
            raise PlatformPluginDesiredBundleSetV2Error(
                "desired_set_scope_invalid",
                str(exc),
            ) from exc


__all__ = [
    "PlatformPluginDesiredBundleSetRecordV2",
    "PlatformPluginDesiredBundleSetRepositoryV2",
    "PlatformPluginDesiredBundleSetV2Error",
]
