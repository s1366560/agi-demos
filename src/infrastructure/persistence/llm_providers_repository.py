"""
LLM Provider SQLAlchemy Repository Implementation

Implements the ProviderRepository interface using SQLAlchemy.
Provides all CRUD operations, tenant resolution, and usage tracking.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.llm_providers.models import (
    EmbeddingConfig,
    LLMUsageLog,
    LLMUsageLogCreate,
    NoActiveProviderError,
    OperationType,
    ProviderConfig,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderHealth,
    ProviderHealthCreate,
    ProviderType,
    ResolvedProvider,
    TenantProviderMapping,
    UsageStatistics,
)
from src.domain.llm_providers.repositories import ProviderRepository
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.llm.provider_credentials import to_storable_api_key
from src.infrastructure.persistence.llm_providers_models import (
    LLMProvider as LLMProviderORM,
    LLMUsageLog as LLMUsageLogORM,
    ProviderHealth as ProviderHealthORM,
    TenantProviderMapping as TenantProviderMappingORM,
)
from src.infrastructure.security.encryption_service import get_encryption_service


class SQLAlchemyProviderRepository(ProviderRepository):
    """
    SQLAlchemy implementation of ProviderRepository.

    Handles all database operations for LLM provider configuration
    with proper encryption/decryption of API keys.
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        """
        Initialize repository with database session.

        Args:
            session: Async database session. If None, creates new session.
        """
        self.session = session
        self.encryption_service = get_encryption_service()

    async def _get_session(self) -> AsyncSession:
        """Get database session."""
        if self.session is None:
            raise RuntimeError(
                "Database session not provided. "
                "SQLAlchemyProviderRepository must be initialized with a session."
            )
        return self.session

    async def _run_with_session(self, operation: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        """Run operation with existing session or create a new ephemeral one."""
        if self.session:
            return await operation(self.session)

        async with async_session_factory() as session:
            return await operation(session)

    @staticmethod
    def _build_embedding_payload(
        embedding_model: str | None,
        embedding_config: EmbeddingConfig | None,
    ) -> dict[str, Any] | None:
        """Build normalized embedding payload for config JSON storage."""
        payload = embedding_config.model_dump(exclude_none=True) if embedding_config else {}
        if embedding_model and not payload.get("model"):
            payload["model"] = embedding_model
        return payload or None

    def _extract_embedding_config(self, orm: LLMProviderORM) -> EmbeddingConfig | None:
        """Hydrate structured embedding config from JSON config and legacy column."""
        config_data = orm.config if isinstance(orm.config, dict) else {}
        embedding_data = config_data.get("embedding")
        payload = embedding_data.copy() if isinstance(embedding_data, dict) else {}
        if orm.embedding_model and not payload.get("model"):
            payload["model"] = orm.embedding_model
        if not payload:
            return None
        try:
            return EmbeddingConfig(**payload)
        except Exception:
            # Keep read path resilient for historical malformed JSON.
            return None

    def _orm_to_config(self, orm: LLMProviderORM, tenant_id: str = "default") -> ProviderConfig:
        """Convert ORM model to domain model."""
        embedding_config = self._extract_embedding_config(orm)
        embedding_model = orm.embedding_model or (
            embedding_config.model if embedding_config else None
        )
        return ProviderConfig(
            id=orm.id,
            name=orm.name,
            provider_type=orm.provider_type,
            tenant_id=tenant_id,
            api_key_encrypted=orm.api_key_encrypted,
            base_url=orm.base_url,
            llm_model=orm.llm_model,
            llm_small_model=orm.llm_small_model,
            embedding_model=embedding_model,
            embedding_config=embedding_config,
            reranker_model=orm.reranker_model,
            config=orm.config,
            is_active=orm.is_active,
            is_default=orm.is_default,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    async def create(self, config: ProviderConfigCreate) -> ProviderConfig:
        """Create a new provider configuration with idempotent upsert on name conflict."""

        async def op(session: AsyncSession) -> ProviderConfig:
            # Encrypt API key before storing
            storable_api_key = to_storable_api_key(config.provider_type, config.api_key)
            api_key_encrypted = self.encryption_service.encrypt(storable_api_key)
            embedding_payload = self._build_embedding_payload(
                config.embedding_model,
                config.embedding_config,
            )
            provider_config = dict(config.config or {})
            if embedding_payload:
                provider_config["embedding"] = embedding_payload
            elif isinstance(provider_config.get("embedding"), dict):
                embedding_payload = dict(provider_config["embedding"])

            # Build values dict for insert
            values = {
                "id": uuid4(),
                "name": config.name,
                "provider_type": config.provider_type.value,
                "api_key_encrypted": api_key_encrypted,
                "base_url": config.base_url,
                "llm_model": config.llm_model,
                "llm_small_model": config.llm_small_model,
                "embedding_model": (
                    embedding_payload.get("model") if embedding_payload else config.embedding_model
                ),
                "reranker_model": config.reranker_model,
                "config": provider_config,
                "is_active": config.is_active,
                "is_default": config.is_default,
            }

            # Use PostgreSQL ON CONFLICT DO NOTHING for atomic upsert
            # This allows multiple processes to safely attempt creation simultaneously
            stmt = pg_insert(LLMProviderORM).values(values)
            stmt = stmt.on_conflict_do_nothing(constraint="llm_providers_name_key")

            await session.execute(stmt)
            await session.commit()

            # Fetch the created (or existing) provider
            result = await session.execute(
                select(LLMProviderORM).where(LLMProviderORM.name == config.name)
            )
            orm = result.scalar_one()

            return self._orm_to_config(orm)

        return cast(ProviderConfig, await self._run_with_session(op))

    async def get_by_id(self, provider_id: UUID) -> ProviderConfig | None:
        """Get provider by ID."""

        async def op(session: AsyncSession) -> ProviderConfig | None:
            from uuid import UUID as _UUID

            pid = _UUID(str(provider_id))
            result = await session.execute(select(LLMProviderORM).where(LLMProviderORM.id == pid))
            orm = result.scalar_one_or_none()
            return self._orm_to_config(orm) if orm else None

        return cast("ProviderConfig | None", await self._run_with_session(op))

    async def get_by_name(self, name: str) -> ProviderConfig | None:
        """Get provider by name."""

        async def op(session: AsyncSession) -> ProviderConfig | None:
            result = await session.execute(
                select(LLMProviderORM).where(LLMProviderORM.name == name)
            )
            orm = result.scalar_one_or_none()
            return self._orm_to_config(orm) if orm else None

        return cast("ProviderConfig | None", await self._run_with_session(op))

    async def list_all(self, include_inactive: bool = False) -> list[ProviderConfig]:
        """List all providers."""

        async def op(session: AsyncSession) -> list[Any]:
            query = select(LLMProviderORM)
            if not include_inactive:
                query = query.where(LLMProviderORM.is_active)

            result = await session.execute(query.order_by(LLMProviderORM.created_at))
            orms = result.scalars().all()
            return [self._orm_to_config(orm) for orm in orms]

        return cast(list[ProviderConfig], await self._run_with_session(op))

    async def list_active(self) -> list[ProviderConfig]:
        """List all active providers."""
        return await self.list_all(include_inactive=False)

    def _apply_simple_field_updates(
        self, orm: LLMProviderORM, config: ProviderConfigUpdate
    ) -> None:
        """Apply simple scalar field updates from config to ORM."""
        simple_fields: list[tuple[str, str | None]] = [
            ("name", None),
            ("base_url", None),
            ("llm_model", None),
            ("llm_small_model", None),
            ("reranker_model", None),
        ]
        for field_name, orm_attr in simple_fields:
            value = getattr(config, field_name, None)
            if value is not None:
                setattr(orm, orm_attr or field_name, value)

        if config.provider_type is not None:
            orm.provider_type = config.provider_type.value
        if config.is_active is not None:
            orm.is_active = config.is_active
        if config.is_default is not None:
            orm.is_default = config.is_default

    def _apply_api_key_update(
        self, orm: LLMProviderORM, config: ProviderConfigUpdate
    ) -> None:
        """Encrypt and apply API key update if provided."""
        if config.api_key is None:
            return
        provider_type = config.provider_type or ProviderType(orm.provider_type)
        storable_api_key = to_storable_api_key(provider_type, config.api_key)
        orm.api_key_encrypted = self.encryption_service.encrypt(storable_api_key)

    def _apply_embedding_config_update(
        self,
        orm: LLMProviderORM,
        config: ProviderConfigUpdate,
        updated_config: dict[str, Any],
    ) -> bool:
        """Apply embedding_config update. Returns True if config dict was modified."""
        embedding_payload = self._build_embedding_payload(
            config.embedding_model,
            config.embedding_config,
        )
        if embedding_payload:
            updated_config["embedding"] = embedding_payload
            orm.embedding_model = embedding_payload.get("model")
        else:
            updated_config.pop("embedding", None)
            orm.embedding_model = None
        return True

    def _apply_embedding_model_update(
        self,
        orm: LLMProviderORM,
        config: ProviderConfigUpdate,
        updated_config: dict[str, Any],
    ) -> bool:
        """Apply embedding_model-only update. Returns True if config dict was modified."""
        existing_embedding = (
            dict(updated_config.get("embedding", {}))
            if isinstance(updated_config.get("embedding"), dict)
            else {}
        )
        if config.embedding_model:
            existing_embedding["model"] = config.embedding_model
        else:
            existing_embedding.pop("model", None)
        if existing_embedding:
            updated_config["embedding"] = existing_embedding
        else:
            updated_config.pop("embedding", None)
        orm.embedding_model = config.embedding_model
        return True

    async def update(
        self, provider_id: UUID, config: ProviderConfigUpdate
    ) -> ProviderConfig | None:
        """Update provider configuration."""
        session = await self._get_session()

        from uuid import UUID as _UUID

        pid = _UUID(str(provider_id))
        result = await session.execute(select(LLMProviderORM).where(LLMProviderORM.id == pid))
        orm = result.scalar_one_or_none()

        if not orm:
            return None

        self._apply_simple_field_updates(orm, config)
        self._apply_api_key_update(orm, config)

        should_update_config = config.config is not None
        updated_config = (
            dict(config.config) if config.config is not None else dict(orm.config or {})
        )

        if config.embedding_config is not None:
            should_update_config = self._apply_embedding_config_update(
                orm, config, updated_config
            )
        elif config.embedding_model is not None:
            should_update_config = self._apply_embedding_model_update(
                orm, config, updated_config
            )

        if should_update_config:
            orm.config = updated_config

        await session.flush()
        await session.commit()
        await session.refresh(orm)

        return self._orm_to_config(orm)

    async def delete(self, provider_id: UUID, hard_delete: bool = False) -> bool:
        """Delete provider.

        Args:
            provider_id: Provider ID to delete
            hard_delete: If True, permanently delete from database. If False, soft delete (set is_active=False).
        """

        async def op(session: AsyncSession) -> bool:
            from uuid import UUID as _UUID

            pid = _UUID(str(provider_id))
            result = await session.execute(select(LLMProviderORM).where(LLMProviderORM.id == pid))
            orm = result.scalar_one_or_none()

            if not orm:
                return False

            if hard_delete:
                # Hard delete - remove from database
                await session.delete(orm)
            else:
                # Soft delete
                orm.is_active = False

            await session.flush()
            await session.commit()

            return True

        return cast(bool, await self._run_with_session(op))

    async def find_default_provider(self) -> ProviderConfig | None:
        """Find the default provider."""

        async def op(session: AsyncSession) -> ProviderConfig | None:
            result = await session.execute(
                select(LLMProviderORM)
                .where(LLMProviderORM.is_default)
                .where(LLMProviderORM.is_active)
            )
            orm = result.scalar_one_or_none()
            return self._orm_to_config(orm) if orm else None

        return cast("ProviderConfig | None", await self._run_with_session(op))

    async def find_first_active_provider(self) -> ProviderConfig | None:
        """Find the first active provider as fallback."""

        async def op(session: AsyncSession) -> ProviderConfig | None:
            result = await session.execute(
                select(LLMProviderORM)
                .where(LLMProviderORM.is_active)
                .order_by(LLMProviderORM.created_at)
                .limit(1)
            )
            orm = result.scalar_one_or_none()
            return self._orm_to_config(orm) if orm else None

        return cast("ProviderConfig | None", await self._run_with_session(op))

    async def find_tenant_provider(
        self,
        tenant_id: str,
        operation_type: OperationType = OperationType.LLM,
    ) -> ProviderConfig | None:
        """Find provider assigned to specific tenant."""

        async def op(session: AsyncSession) -> ProviderConfig | None:
            operation_value = operation_type.value
            query = (
                select(LLMProviderORM)
                .join(TenantProviderMappingORM)
                .where(TenantProviderMappingORM.tenant_id == tenant_id)
                .where(TenantProviderMappingORM.operation_type == operation_value)
                .where(LLMProviderORM.is_active)
                .order_by(TenantProviderMappingORM.priority)
                .limit(1)
            )
            result = await session.execute(query)
            orm = result.scalar_one_or_none()
            if orm is None and operation_type != OperationType.LLM:
                fallback_query = (
                    select(LLMProviderORM)
                    .join(TenantProviderMappingORM)
                    .where(TenantProviderMappingORM.tenant_id == tenant_id)
                    .where(TenantProviderMappingORM.operation_type == OperationType.LLM.value)
                    .where(LLMProviderORM.is_active)
                    .order_by(TenantProviderMappingORM.priority)
                    .limit(1)
                )
                fallback_result = await session.execute(fallback_query)
                orm = fallback_result.scalar_one_or_none()
            return self._orm_to_config(orm, tenant_id=tenant_id) if orm else None

        return cast("ProviderConfig | None", await self._run_with_session(op))

    async def resolve_provider(
        self,
        tenant_id: str | None = None,
        operation_type: OperationType = OperationType.LLM,
    ) -> ResolvedProvider:
        """
        Resolve appropriate provider for tenant.

        Resolution hierarchy:
        1. Tenant-specific provider (if configured)
        2. Default provider (if set)
        3. First active provider (fallback)

        Raises:
            NoActiveProviderError: If no active provider found
        """
        provider = None
        resolution_source = ""

        if tenant_id:
            # Try tenant-specific provider
            provider = await self.find_tenant_provider(tenant_id, operation_type=operation_type)
            if provider:
                resolution_source = "tenant"

        if not provider:
            # Try default provider
            provider = await self.find_default_provider()
            if provider:
                resolution_source = "default"

        if not provider:
            # Fallback to first active provider
            provider = await self.find_first_active_provider()
            if provider:
                resolution_source = "fallback"

        if not provider:
            raise NoActiveProviderError("No active LLM provider configured")

        return ResolvedProvider(
            provider=provider,
            resolution_source=resolution_source,
        )

    async def create_health_check(self, health: ProviderHealthCreate) -> ProviderHealth:
        """Create a health check entry."""
        session = await self._get_session()

        orm = ProviderHealthORM(
            provider_id=health.provider_id,
            status=health.status.value,
            error_message=health.error_message,
            response_time_ms=health.response_time_ms,
            # last_check will be set automatically by database default
        )

        session.add(orm)
        await session.flush()
        await session.commit()
        # Don't use refresh with composite keys, access the value directly after flush
        # The last_check will be set by database default during flush

        return ProviderHealth(
            provider_id=orm.provider_id,
            status=orm.status,
            last_check=orm.last_check,
            error_message=orm.error_message,
            response_time_ms=orm.response_time_ms,
        )

    async def get_latest_health(self, provider_id: UUID) -> ProviderHealth | None:
        """Get latest health check for provider."""
        session = await self._get_session()

        result = await session.execute(
            select(ProviderHealthORM)
            .where(ProviderHealthORM.provider_id == provider_id)
            .order_by(desc(ProviderHealthORM.last_check))
            .limit(1)
        )
        orm = result.scalar_one_or_none()

        if not orm:
            return None

        return ProviderHealth(
            provider_id=orm.provider_id,
            status=orm.status,
            last_check=orm.last_check,
            error_message=orm.error_message,
            response_time_ms=orm.response_time_ms,
        )

    async def create_usage_log(self, usage_log: LLMUsageLogCreate) -> LLMUsageLog:
        """Create a usage log entry."""
        session = await self._get_session()

        orm = LLMUsageLogORM(
            id=uuid4(),
            provider_id=usage_log.provider_id,
            tenant_id=usage_log.tenant_id,
            operation_type=usage_log.operation_type.value,
            model_name=usage_log.model_name,
            prompt_tokens=usage_log.prompt_tokens,
            completion_tokens=usage_log.completion_tokens,
            cost_usd=usage_log.cost_usd,
        )

        session.add(orm)
        await session.flush()
        await session.commit()
        await session.refresh(orm)

        return LLMUsageLog(
            id=orm.id,
            provider_id=orm.provider_id,
            tenant_id=orm.tenant_id,
            operation_type=orm.operation_type,
            model_name=orm.model_name,
            prompt_tokens=orm.prompt_tokens,
            completion_tokens=orm.completion_tokens,
            total_tokens=orm.total_tokens,
            cost_usd=orm.cost_usd,
            created_at=orm.created_at,
        )

    async def get_usage_statistics(
        self,
        provider_id: UUID | None = None,
        tenant_id: str | None = None,
        operation_type: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[UsageStatistics]:
        """Get aggregated usage statistics."""
        session = await self._get_session()

        # Build query - simplified without health check join to avoid correlation issues
        query = (
            select(
                LLMUsageLogORM.provider_id,
                LLMUsageLogORM.tenant_id,
                LLMUsageLogORM.operation_type,
                func.count(LLMUsageLogORM.id).label("total_requests"),
                func.sum(LLMUsageLogORM.prompt_tokens).label("total_prompt_tokens"),
                func.sum(LLMUsageLogORM.completion_tokens).label("total_completion_tokens"),
                func.sum(LLMUsageLogORM.prompt_tokens + LLMUsageLogORM.completion_tokens).label(
                    "total_tokens"
                ),
                func.sum(LLMUsageLogORM.cost_usd).label("total_cost_usd"),
                func.min(LLMUsageLogORM.created_at).label("first_request_at"),
                func.max(LLMUsageLogORM.created_at).label("last_request_at"),
            )
            .select_from(LLMUsageLogORM)
            .group_by(
                LLMUsageLogORM.provider_id,
                LLMUsageLogORM.tenant_id,
                LLMUsageLogORM.operation_type,
            )
        )

        # Apply filters
        if provider_id is not None:
            query = query.where(LLMUsageLogORM.provider_id == provider_id)
        if tenant_id is not None:
            query = query.where(LLMUsageLogORM.tenant_id == tenant_id)
        if operation_type is not None:
            query = query.where(LLMUsageLogORM.operation_type == operation_type)
        if start_date is not None:
            query = query.where(LLMUsageLogORM.created_at >= start_date)
        if end_date is not None:
            query = query.where(LLMUsageLogORM.created_at <= end_date)

        result = await session.execute(query)
        rows = result.all()

        statistics = []
        for row in rows:
            stats = UsageStatistics(
                provider_id=row.provider_id,
                tenant_id=row.tenant_id,
                operation_type=row.operation_type,
                total_requests=row.total_requests,
                total_prompt_tokens=row.total_prompt_tokens or 0,
                total_completion_tokens=row.total_completion_tokens or 0,
                total_tokens=row.total_tokens or 0,
                total_cost_usd=row.total_cost_usd,
                avg_response_time_ms=None,  # Simplified query without health check join
                first_request_at=row.first_request_at,
                last_request_at=row.last_request_at,
            )
            statistics.append(stats)

        return statistics

    async def assign_provider_to_tenant(
        self,
        tenant_id: str,
        provider_id: UUID,
        priority: int = 0,
        operation_type: OperationType = OperationType.LLM,
    ) -> TenantProviderMapping:
        """Assign provider to tenant."""
        session = await self._get_session()

        stmt: Any = pg_insert(TenantProviderMappingORM).values(
            id=uuid4(),
            tenant_id=tenant_id,
            provider_id=provider_id,
            operation_type=operation_type.value,
            priority=priority,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "provider_id", "operation_type"],
            set_={"priority": priority},
        ).returning(TenantProviderMappingORM.id)
        result = await session.execute(stmt)
        mapping_id = result.scalar_one()
        await session.commit()
        orm_result = await session.execute(
            select(TenantProviderMappingORM).where(TenantProviderMappingORM.id == mapping_id)
        )
        orm = orm_result.scalar_one()

        return TenantProviderMapping(
            id=orm.id,
            tenant_id=orm.tenant_id,
            provider_id=orm.provider_id,
            operation_type=OperationType(orm.operation_type),
            priority=orm.priority,
            created_at=orm.created_at,
        )

    async def unassign_provider_from_tenant(
        self,
        tenant_id: str,
        provider_id: UUID,
        operation_type: OperationType = OperationType.LLM,
    ) -> bool:
        """Unassign provider from tenant."""
        session = await self._get_session()

        result = await session.execute(
            select(TenantProviderMappingORM).where(
                and_(
                    TenantProviderMappingORM.tenant_id == tenant_id,
                    TenantProviderMappingORM.provider_id == provider_id,
                    TenantProviderMappingORM.operation_type == operation_type.value,
                )
            )
        )
        orm = result.scalar_one_or_none()

        if not orm:
            return False

        await session.delete(orm)
        await session.flush()
        await session.commit()

        return True

    async def get_tenant_providers(
        self,
        tenant_id: str,
        operation_type: OperationType | None = None,
    ) -> list[TenantProviderMapping]:
        """Get all providers assigned to tenant."""
        session = await self._get_session()

        query = (
            select(TenantProviderMappingORM)
            .where(TenantProviderMappingORM.tenant_id == tenant_id)
            .order_by(TenantProviderMappingORM.priority)
        )
        if operation_type is not None:
            query = query.where(TenantProviderMappingORM.operation_type == operation_type.value)

        result = await session.execute(query)
        orms = result.scalars().all()

        return [
            TenantProviderMapping(
                id=orm.id,
                tenant_id=orm.tenant_id,
                provider_id=orm.provider_id,
                operation_type=OperationType(orm.operation_type),
                priority=orm.priority,
                created_at=orm.created_at,
            )
            for orm in orms
        ]
