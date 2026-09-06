"""Canonical ledger scope identities and transaction-owned version allocation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlatformPluginV2PublicationModel,
    PlatformPluginV2ScopeHeadModel,
)
from src.infrastructure.adapters.secondary.persistence.plugin_scope_columns_v2 import (
    PluginScopeColumnsV2,
)
from src.infrastructure.plugins.v2.scope import scope_key_v2, validate_scope_v2


class ScopeLedgerBindingV2:
    """One repository's immutable scope; it is an identity, not an authorization grant."""

    def __init__(self, scope: ScopeV2, error_factory: Callable[[str, str], ValueError]) -> None:
        super().__init__()
        self._error = error_factory
        self.scope = validate_scope_v2(scope)
        self.key = scope_key_v2(self.scope)

    @property
    def fields(self) -> dict[str, Any]:
        return {
            "scope_key": self.key,
            "scope_kind": self.scope.kind.value,
            "tenant_id": self.scope.tenant_id,
            "project_id": self.scope.project_id,
            "session_id": self.scope.session_id,
        }

    def require_row(self, row: PluginScopeColumnsV2) -> None:
        scope = validate_scope_v2(
            ScopeV2(
                kind=ScopeKindV2(row.scope_kind),
                tenant_id=row.tenant_id,
                project_id=row.project_id,
                session_id=row.session_id,
            )
        )
        if scope != self.scope or row.scope_key != self.key:
            raise self._error(
                "publication_scope_mismatch", "plugin v2 ledger row belongs to another scope"
            )

    async def lock(self, session: AsyncSession) -> PlatformPluginV2ScopeHeadModel:
        """Atomically create then lock the head before any publication or receipt write."""
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = postgres_insert(PlatformPluginV2ScopeHeadModel)
        elif dialect == "sqlite":
            statement = sqlite_insert(PlatformPluginV2ScopeHeadModel)
        else:
            raise ValueError("plugin v2 scope ledger requires PostgreSQL or SQLite")
        _ = await session.execute(
            statement.values(**self.fields, version_high_watermark=0).on_conflict_do_nothing(
                index_elements=["scope_key"]
            )
        )
        result = await session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ScopeHeadModel)
                .where(PlatformPluginV2ScopeHeadModel.scope_key == self.key)
                .with_for_update()
            )
        )
        head = result.scalar_one()
        self.require_row(head)
        # Existing imports/legacy publications can predate this head's creation.
        maximum = await session.scalar(
            select(func.max(PlatformPluginV2PublicationModel.requested_version)).where(
                PlatformPluginV2PublicationModel.scope_key == self.key
            )
        )
        head.version_high_watermark = max(head.version_high_watermark, maximum or 0)
        return head

    async def allocate(self, session: AsyncSession) -> int:
        head = await self.lock(session)
        head.version_high_watermark += 1
        await session.flush()
        return head.version_high_watermark

    async def insert_publication(
        self, session: AsyncSession, model: PlatformPluginV2PublicationModel
    ) -> None:
        """Recover the transaction when different scope heads race on one global nonce."""
        try:
            async with session.begin_nested():
                session.add(model)
                await session.flush()
        except IntegrityError as error:
            existing = await session.scalar(
                select(PlatformPluginV2PublicationModel.id).where(
                    PlatformPluginV2PublicationModel.nonce == model.nonce
                )
            )
            if existing is None:
                raise
            raise self._error(
                "publication_nonce_conflict", "plugin v2 publication nonce is already in use"
            ) from error
