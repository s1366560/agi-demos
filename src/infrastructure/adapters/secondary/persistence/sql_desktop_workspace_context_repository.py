"""SQLAlchemy repository for authoritative desktop workspace context."""

from datetime import UTC, datetime
from typing import override
from uuid import uuid4

from sqlalchemy import and_, case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextError,
    WorkspaceContextErrorCode,
    WorkspaceContextSnapshot,
    WorkspaceContextSwitchOutcome,
    WorkspaceContextSwitchRequest,
)
from src.domain.ports.repositories.workspace_context_repository import (
    WorkspaceContextRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    DesktopWorkspaceContext,
    DesktopWorkspaceContextEvent,
    Project,
    UserProject,
    UserTenant,
)

_CONTEXT_LOCK_SEED = 0x41_47_49_43
_MAX_REVISION = (1 << 63) - 1
_DEFAULT_PROJECT_NAMES = ("Default project", "默认项目")


class SqlDesktopWorkspaceContextRepository(WorkspaceContextRepository):
    """Postgres-authoritative context store with SQLite-compatible unit behavior."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    @override
    async def get_or_initialize(
        self,
        user_id: str,
        observed_at: datetime,
    ) -> WorkspaceContextAccess:
        self._validate_user_id(user_id)
        await self._lock_context(user_id)
        current = await self._load_context(user_id)
        if current is not None:
            membership_role = await self._accessible_membership_role(
                user_id,
                current.tenant_id,
                current.project_id,
            )
            if membership_role is not None:
                return WorkspaceContextAccess(
                    context=self._snapshot_from_context(current),
                    membership_role=membership_role,
                )

        candidate = await self._load_default_scope(user_id)
        if candidate is None:
            raise WorkspaceContextError(WorkspaceContextErrorCode.UNAVAILABLE)
        tenant_id, project_id, membership_role = candidate

        if current is not None:
            revision = self._next_revision(current.revision)
            previous_tenant_id = current.tenant_id
            previous_project_id = current.project_id
            current.tenant_id = tenant_id
            current.project_id = project_id
            current.revision = revision
            current.updated_at = observed_at
            await self._add_event(
                user_id=user_id,
                actor_api_key_id=None,
                from_tenant_id=previous_tenant_id,
                from_project_id=previous_project_id,
                to_tenant_id=tenant_id,
                to_project_id=project_id,
                revision=revision,
                idempotency_key=f"system:workspace-context-repair:{revision}",
                observed_at=observed_at,
            )
        else:
            last_revision = await self._load_last_event_revision(user_id)
            revision = self._next_revision(last_revision) if last_revision is not None else 0
            self._session.add(
                DesktopWorkspaceContext(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    project_id=project_id,
                    revision=revision,
                    updated_at=observed_at,
                )
            )
            if last_revision is not None:
                await self._add_event(
                    user_id=user_id,
                    actor_api_key_id=None,
                    from_tenant_id=None,
                    from_project_id=None,
                    to_tenant_id=tenant_id,
                    to_project_id=project_id,
                    revision=revision,
                    idempotency_key=f"system:workspace-context-repair:{revision}",
                    observed_at=observed_at,
                )

        await self._session.flush()
        return WorkspaceContextAccess(
            context=WorkspaceContextSnapshot(
                tenant_id=tenant_id,
                project_id=project_id,
                revision=revision,
                updated_at=observed_at,
            ),
            membership_role=membership_role,
        )

    @override
    async def switch(
        self,
        user_id: str,
        *,
        actor_api_key_id: str | None,
        request: WorkspaceContextSwitchRequest,
        observed_at: datetime,
    ) -> WorkspaceContextSwitchOutcome:
        self._validate_switch(user_id, request)
        await self._lock_context(user_id)

        existing_event = await self._load_event(user_id, request.idempotency_key)
        if existing_event is not None:
            if (
                existing_event.to_tenant_id != request.tenant_id
                or existing_event.to_project_id != request.project_id
            ):
                raise WorkspaceContextError(WorkspaceContextErrorCode.IDEMPOTENCY_CONFLICT)
            return WorkspaceContextSwitchOutcome(
                context=self._snapshot_from_event(existing_event),
                changed=False,
            )

        current = await self._load_context(user_id)
        actual_revision = (
            current.revision
            if current is not None
            else (await self._load_last_event_revision(user_id) or 0)
        )
        if request.expected_revision != actual_revision:
            raise WorkspaceContextError(
                WorkspaceContextErrorCode.REVISION_CONFLICT,
                expected_revision=request.expected_revision,
                actual_revision=actual_revision,
            )
        await self._require_membership(user_id, request.tenant_id)
        await self._require_project(user_id, request.tenant_id, request.project_id)

        revision = self._next_revision(actual_revision)
        previous_tenant_id = current.tenant_id if current is not None else None
        previous_project_id = current.project_id if current is not None else None
        if current is None:
            self._session.add(
                DesktopWorkspaceContext(
                    user_id=user_id,
                    tenant_id=request.tenant_id,
                    project_id=request.project_id,
                    revision=revision,
                    updated_at=observed_at,
                )
            )
        else:
            current.tenant_id = request.tenant_id
            current.project_id = request.project_id
            current.revision = revision
            current.updated_at = observed_at
        await self._add_event(
            user_id=user_id,
            actor_api_key_id=actor_api_key_id,
            from_tenant_id=previous_tenant_id,
            from_project_id=previous_project_id,
            to_tenant_id=request.tenant_id,
            to_project_id=request.project_id,
            revision=revision,
            idempotency_key=request.idempotency_key,
            observed_at=observed_at,
        )
        await self._session.flush()
        return WorkspaceContextSwitchOutcome(
            context=WorkspaceContextSnapshot(
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                revision=revision,
                updated_at=observed_at,
            ),
            changed=True,
        )

    async def _lock_context(self, user_id: str) -> None:
        bind = self._session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        _ = await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, :seed))"),
            {"user_id": user_id, "seed": _CONTEXT_LOCK_SEED},
        )

    async def _load_context(self, user_id: str) -> DesktopWorkspaceContext | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(DesktopWorkspaceContext)
                .where(DesktopWorkspaceContext.user_id == user_id)
                .with_for_update()
            )
        )
        return result.scalar_one_or_none()

    async def _load_default_scope(self, user_id: str) -> tuple[str, str, str] | None:
        default_project_rank = case(
            (Project.name.in_(_DEFAULT_PROJECT_NAMES), 0),
            else_=1,
        )
        result = await self._session.execute(
            refresh_select_statement(
                select(Project.tenant_id, Project.id, UserTenant.role)
                .select_from(UserTenant)
                .join(Project, Project.tenant_id == UserTenant.tenant_id)
                .join(
                    UserProject,
                    and_(
                        UserProject.project_id == Project.id,
                        UserProject.user_id == UserTenant.user_id,
                    ),
                )
                .where(UserTenant.user_id == user_id)
                .order_by(
                    UserTenant.created_at.asc(),
                    UserTenant.id.asc(),
                    Project.tenant_id.asc(),
                    default_project_rank.asc(),
                    Project.created_at.desc(),
                    Project.id.asc(),
                )
                .limit(1)
            )
        )
        row = result.one_or_none()
        return None if row is None else (str(row[0]), str(row[1]), str(row[2] or "member"))

    async def _accessible_membership_role(
        self,
        user_id: str,
        tenant_id: str,
        project_id: str,
    ) -> str | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserTenant.role)
                .select_from(UserTenant)
                .join(Project, Project.tenant_id == UserTenant.tenant_id)
                .join(
                    UserProject,
                    and_(
                        UserProject.project_id == Project.id,
                        UserProject.user_id == UserTenant.user_id,
                    ),
                )
                .where(
                    UserTenant.user_id == user_id,
                    UserTenant.tenant_id == tenant_id,
                    Project.id == project_id,
                )
                .order_by(UserTenant.created_at.asc(), UserTenant.id.asc())
                .limit(1)
            )
        )
        role = result.scalar_one_or_none()
        return None if role is None else str(role or "member")

    async def _load_event(
        self,
        user_id: str,
        idempotency_key: str,
    ) -> DesktopWorkspaceContextEvent | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(DesktopWorkspaceContextEvent).where(
                    DesktopWorkspaceContextEvent.user_id == user_id,
                    DesktopWorkspaceContextEvent.idempotency_key == idempotency_key,
                )
            )
        )
        return result.scalar_one_or_none()

    async def _load_last_event_revision(self, user_id: str) -> int | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(func.max(DesktopWorkspaceContextEvent.revision)).where(
                    DesktopWorkspaceContextEvent.user_id == user_id
                )
            )
        )
        revision = result.scalar_one()
        return None if revision is None else int(revision)

    async def _require_membership(self, user_id: str, tenant_id: str) -> None:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserTenant.id)
                .where(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id)
                .limit(1)
            )
        )
        if result.scalar_one_or_none() is None:
            raise WorkspaceContextError(WorkspaceContextErrorCode.MEMBERSHIP_REQUIRED)

    async def _require_project(self, user_id: str, tenant_id: str, project_id: str) -> None:
        result = await self._session.execute(
            refresh_select_statement(
                select(UserProject.id)
                .join(Project, Project.id == UserProject.project_id)
                .where(
                    UserProject.user_id == user_id,
                    Project.tenant_id == tenant_id,
                    Project.id == project_id,
                )
                .limit(1)
            )
        )
        if result.scalar_one_or_none() is None:
            raise WorkspaceContextError(WorkspaceContextErrorCode.PROJECT_UNAVAILABLE)

    async def _add_event(
        self,
        *,
        user_id: str,
        actor_api_key_id: str | None,
        from_tenant_id: str | None,
        from_project_id: str | None,
        to_tenant_id: str,
        to_project_id: str,
        revision: int,
        idempotency_key: str,
        observed_at: datetime,
    ) -> None:
        self._session.add(
            DesktopWorkspaceContextEvent(
                id=str(uuid4()),
                user_id=user_id,
                actor_api_key_id=actor_api_key_id,
                from_tenant_id=from_tenant_id,
                from_project_id=from_project_id,
                to_tenant_id=to_tenant_id,
                to_project_id=to_project_id,
                revision=revision,
                idempotency_key=idempotency_key,
                value_json={
                    "tenant_id": to_tenant_id,
                    "project_id": to_project_id,
                    "revision": revision,
                    "updated_at": observed_at.isoformat(),
                },
                created_at=observed_at,
            )
        )

    @staticmethod
    def _snapshot_from_context(context: DesktopWorkspaceContext) -> WorkspaceContextSnapshot:
        return WorkspaceContextSnapshot(
            tenant_id=context.tenant_id,
            project_id=context.project_id,
            revision=context.revision,
            updated_at=SqlDesktopWorkspaceContextRepository._ensure_utc(context.updated_at),
        )

    @staticmethod
    def _snapshot_from_event(event: DesktopWorkspaceContextEvent) -> WorkspaceContextSnapshot:
        return WorkspaceContextSnapshot(
            tenant_id=event.to_tenant_id,
            project_id=event.to_project_id,
            revision=event.revision,
            updated_at=SqlDesktopWorkspaceContextRepository._ensure_utc(event.created_at),
        )

    @staticmethod
    def _ensure_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _validate_user_id(user_id: str) -> None:
        if not user_id.strip():
            raise WorkspaceContextError(WorkspaceContextErrorCode.INVALID_INPUT)

    @classmethod
    def _validate_switch(cls, user_id: str, request: WorkspaceContextSwitchRequest) -> None:
        cls._validate_user_id(user_id)
        idempotency_key = request.idempotency_key.strip()
        if (
            not request.tenant_id.strip()
            or not request.project_id.strip()
            or request.expected_revision < 0
            or not idempotency_key
            or len(idempotency_key) > 255
        ):
            raise WorkspaceContextError(WorkspaceContextErrorCode.INVALID_INPUT)

    @staticmethod
    def _next_revision(revision: int) -> int:
        if revision >= _MAX_REVISION:
            raise WorkspaceContextError(WorkspaceContextErrorCode.REVISION_EXHAUSTED)
        return revision + 1
