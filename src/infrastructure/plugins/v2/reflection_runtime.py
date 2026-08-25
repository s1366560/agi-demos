"""Generation-owned Reflection runtime, effects, and operation seams."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NoReturn, Protocol, cast, runtime_checkable
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.reflection_events import (
    ReflectionCompleteStatus,
    build_reflection_complete_payload,
)
from src.application.services.reflection_runner import ReflectionRunner
from src.application.services.reflection_service import ReflectionService
from src.domain.model.flow.friction_signal import FrictionKind, FrictionSignal
from src.domain.model.flow.reflection_verdict import ReflectionVerdict
from src.domain.model.lane_contract import LaneContractRegistry
from src.domain.ports.repositories.friction_ledger import FrictionLedger
from src.infrastructure.adapters.secondary.cache.redis_friction_ledger import (
    RedisFrictionLedger,
)

from .llm_client_service import TenantLlmClientFactoryProtocolV2
from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.application.services.lane_experience_service import LaneJitContext

REFLECTION_RUNTIME_MODULE_V2 = "builtin://memstack/runtime/reflection"
REFLECTION_RUNTIME_SERVICE_V2 = "service:runtime.reflection"
REFLECTION_RUNTIME_SESSIONS_INJECT_V2 = "sessions"
REFLECTION_RUNTIME_LLM_CLIENTS_INJECT_V2 = "llm_clients"
REFLECTION_COMPLETE_EVENT_V2 = "reflection.complete"

type ReflectionSessionFactoryV2 = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type ReflectionRunnerFactoryV2 = Callable[..., ReflectionRunner]
type ReflectionSourceV2 = Literal["runner", "tool"]

logger = logging.getLogger(__name__)


@runtime_checkable
class AsyncSessionFactoryProviderProtocolV2(Protocol):
    """Structural contract for the injected process session factory."""

    @property
    def factory(self) -> ReflectionSessionFactoryV2: ...


@runtime_checkable
class ReflectionRunnerProtocolV2(Protocol):
    """Lifecycle surface required from the periodic runner."""

    def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True, kw_only=True)
class ReflectionRuntimeConfigV2:
    """Profile-owned process and reflection-window settings."""

    enabled: bool
    interval_seconds: float
    per_project_timeout_seconds: float
    window_minutes: int
    lane_order: tuple[str, ...]


@runtime_checkable
class ReflectionRuntimeServiceProtocolV2(Protocol):
    """Consumer contract for generation-pinned Reflection operations."""

    async def list_active_project_ids(self) -> list[str]: ...

    async def record_lane_change(
        self,
        *,
        project_id: str,
        task_id: str,
        from_lane: str,
        to_lane: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> FrictionSignal | None: ...

    async def reflect_project(
        self,
        *,
        project_id: str,
        tenant_id: str | None,
        source: ReflectionSourceV2,
        run_id: str | None = None,
    ) -> list[ReflectionVerdict]: ...

    async def build_lane_jit_context(
        self,
        *,
        project_id: str,
        tenant_id: str | None,
        lane_id: str,
        card_body: str,
    ) -> LaneJitContext | None: ...


@dataclass(frozen=True, kw_only=True)
class ReflectionRuntimeServiceV2:
    """One generation's immutable dependencies over a shared process ledger."""

    runtime: ReflectionRuntimeManagerV2
    sessions: AsyncSessionFactoryProviderProtocolV2
    llm_clients: TenantLlmClientFactoryProtocolV2
    context: ContextV2
    config: ReflectionRuntimeConfigV2

    async def list_active_project_ids(self) -> list[str]:
        from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
            SqlProjectRepository,
        )

        async with self.sessions.factory() as session:
            projects = await SqlProjectRepository(session).list_active_projects(limit=1000)
        return [project.id for project in projects]

    async def record_lane_change(
        self,
        *,
        project_id: str,
        task_id: str,
        from_lane: str,
        to_lane: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> FrictionSignal | None:
        if not project_id or not task_id or from_lane == to_lane:
            return None
        try:
            source_index = self.config.lane_order.index(from_lane)
            target_index = self.config.lane_order.index(to_lane)
        except ValueError:
            return None
        if target_index >= source_index:
            return None

        signal = FrictionSignal(
            project_id=project_id,
            task_id=task_id,
            kind=FrictionKind.BOUNCE,
            source_lane=from_lane,
            target_lane=to_lane,
            metadata=dict(metadata or {}),
        )
        try:
            await self.runtime.ledger.append(signal)
        except Exception:
            logger.exception(
                "FrictionLedger.append failed for project=%s task=%s",
                project_id,
                task_id,
            )
            return None
        return signal

    async def reflect_project(
        self,
        *,
        project_id: str,
        tenant_id: str | None,
        source: ReflectionSourceV2,
        run_id: str | None = None,
    ) -> list[ReflectionVerdict]:
        from src.application.services.reflection_factory import (
            build_litellm_reflector,
            build_reflection_service,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
            SqlPlaybookRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_reflection_verdict_repository import (
            SqlReflectionVerdictRepository,
        )

        try:
            async with self.sessions.factory() as session:
                resolved_tenant_id = await _resolve_project_tenant_v2(
                    session,
                    project_id=project_id,
                    tenant_id=tenant_id,
                )
                llm_client = await self.llm_clients.create(
                    db=session,
                    tenant_id=resolved_tenant_id,
                )
                service = build_reflection_service(
                    ledger=self.runtime.ledger,
                    playbooks=SqlPlaybookRepository(session),
                    reflector=build_litellm_reflector(llm_client),
                    verdict_log=SqlReflectionVerdictRepository(session),
                    window_minutes=self.config.window_minutes,
                )
                verdicts = await service.reflect_window(project_id)
                await session.commit()
        except Exception as exc:
            await self._emit_completion(
                project_id=project_id,
                verdicts=[],
                status="failed",
                source=source,
                run_id=run_id,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise

        await self._emit_completion(
            project_id=project_id,
            verdicts=verdicts,
            status="success",
            source=source,
            run_id=run_id,
        )
        return verdicts

    async def build_lane_jit_context(
        self,
        *,
        project_id: str,
        tenant_id: str | None,
        lane_id: str,
        card_body: str,
    ) -> LaneJitContext | None:
        from src.application.services.lane_experience_service import LaneExperienceService
        from src.infrastructure.adapters.secondary.persistence.sql_playbook_repository import (
            SqlPlaybookRepository,
        )

        contract = LaneContractRegistry.default().get(lane_id)
        if contract is None:
            return None
        async with self.sessions.factory() as session:
            _ = await _resolve_project_tenant_v2(
                session,
                project_id=project_id,
                tenant_id=tenant_id,
            )
            service = LaneExperienceService(
                friction_ledger=self.runtime.ledger,
                playbook_repository=SqlPlaybookRepository(session),
            )
            return await service.build(
                project_id=project_id,
                lane_contract=contract,
                card_body=card_body,
            )

    async def _emit_completion(
        self,
        *,
        project_id: str,
        verdicts: list[ReflectionVerdict],
        status: ReflectionCompleteStatus,
        source: ReflectionSourceV2,
        run_id: str | None,
        error: str | None = None,
    ) -> None:
        payload = build_reflection_complete_payload(
            project_id=project_id,
            verdicts=verdicts,
            status=status,
            source=source,
            run_id=run_id,
            error=error,
        )
        _ = await self.context.dispatch(REFLECTION_COMPLETE_EVENT_V2, payload)


@dataclass(frozen=True, kw_only=True)
class UnavailableReflectionRuntimeServiceV2:
    """Fail-closed service for a data plane without a Reflection manager."""

    unavailable_code: str = "reflection_runtime_manager_unavailable"

    async def list_active_project_ids(self) -> list[str]:
        self._raise()

    async def record_lane_change(
        self,
        *,
        project_id: str,
        task_id: str,
        from_lane: str,
        to_lane: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> FrictionSignal | None:
        del project_id, task_id, from_lane, to_lane, metadata
        self._raise()

    async def reflect_project(
        self,
        *,
        project_id: str,
        tenant_id: str | None,
        source: ReflectionSourceV2,
        run_id: str | None = None,
    ) -> list[ReflectionVerdict]:
        del project_id, tenant_id, source, run_id
        self._raise()

    async def build_lane_jit_context(
        self,
        *,
        project_id: str,
        tenant_id: str | None,
        lane_id: str,
        card_body: str,
    ) -> LaneJitContext | None:
        del project_id, tenant_id, lane_id, card_body
        self._raise()

    def _raise(self) -> NoReturn:
        raise RuntimeV2Error(
            self.unavailable_code,
            "Reflection runtime manager is not installed on this data plane",
        )


def _default_ledger_factory_v2(redis_client: object) -> FrictionLedger:
    return RedisFrictionLedger(cast("Redis", redis_client))


@dataclass(kw_only=True)
class ReflectionRuntimeManagerV2:
    """Reference-count one periodic runner and durable ledger across generations."""

    redis_client: object
    runner_factory: ReflectionRunnerFactoryV2 = ReflectionRunner
    ledger_factory: Callable[[object], FrictionLedger] = _default_ledger_factory_v2
    _runner: ReflectionRunnerProtocolV2 | None = None
    _ledger: FrictionLedger | None = None
    _config: ReflectionRuntimeConfigV2 | None = None
    _session_factory: ReflectionSessionFactoryV2 | None = None
    _generation_references: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def generation_references(self) -> int:
        return self._generation_references

    @property
    def runner(self) -> ReflectionRunnerProtocolV2 | None:
        return self._runner

    @property
    def ledger(self) -> FrictionLedger:
        if self._ledger is None:
            raise RuntimeV2Error(
                "reflection_runtime_inactive",
                "Reflection ledger is not active for this process generation",
            )
        return self._ledger

    async def acquire_generation(
        self,
        *,
        sessions: AsyncSessionFactoryProviderProtocolV2,
        config: ReflectionRuntimeConfigV2,
    ) -> None:
        async with self._lock:
            if self._generation_references > 0:
                if self._config != config or self._session_factory is not sessions.factory:
                    raise RuntimeV2Error(
                        "reflection_runtime_process_boundary_mismatch",
                        "Reflection config or session factory changed inside a process boundary",
                    )
                self._generation_references += 1
                return

            ledger = self.ledger_factory(self.redis_client)
            runner: ReflectionRunnerProtocolV2 | None = None
            if config.enabled:
                runner = self.runner_factory(
                    project_ids_provider=_current_reflection_project_ids_v2,
                    service_factory=_current_runner_reflection_service_v2,
                    interval_seconds=config.interval_seconds,
                    per_project_timeout_seconds=config.per_project_timeout_seconds,
                    sweep_context_factory=_reflection_sweep_boundary_v2,
                )
                try:
                    runner.start()
                except BaseException:
                    try:
                        await runner.stop()
                    except Exception:
                        logger.exception("Failed to clean up Reflection runtime candidate")
                    raise

            self._ledger = ledger
            self._runner = runner
            self._config = config
            self._session_factory = sessions.factory
            self._generation_references = 1

    async def release_generation(self) -> None:
        async with self._lock:
            if self._generation_references <= 0:
                raise RuntimeV2Error(
                    "reflection_runtime_reference_underflow",
                    "Reflection runtime generation reference count underflow",
                )
            self._generation_references -= 1
            if self._generation_references != 0:
                return
            try:
                if self._runner is not None:
                    await self._runner.stop()
            finally:
                self._runner = None
                self._ledger = None
                self._config = None
                self._session_factory = None


@dataclass(frozen=True, kw_only=True)
class _RunnerReflectionServiceV2:
    runtime: ReflectionRuntimeServiceProtocolV2
    project_id: str

    async def reflect_window(self, project_id: str) -> list[ReflectionVerdict]:
        if project_id != self.project_id:
            raise RuntimeV2Error(
                "reflection_runner_project_mismatch",
                "Reflection runner service was invoked for a different project",
            )
        return await self.runtime.reflect_project(
            project_id=project_id,
            tenant_id=None,
            source="runner",
        )


async def _current_reflection_project_ids_v2() -> list[str]:
    return await current_reflection_runtime_v2().list_active_project_ids()


async def _current_runner_reflection_service_v2(project_id: str) -> ReflectionService:
    return cast(
        "ReflectionService",
        _RunnerReflectionServiceV2(
            runtime=current_reflection_runtime_v2(),
            project_id=project_id,
        ),
    )


@asynccontextmanager
async def _reflection_sweep_boundary_v2() -> AsyncIterator[None]:
    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

    from .boundary import current_process_generation_host_v2, pin_operation_context_v2

    host = current_process_generation_host_v2()
    async with pin_operation_context_v2(
        host,
        operation_id=f"reflection-sweep:{uuid4()}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        services={
            "service:operation.metadata": {"kind": "reflection-sweep"},
        },
    ):
        yield


async def _resolve_project_tenant_v2(
    session: AsyncSession,
    *,
    project_id: str,
    tenant_id: str | None,
) -> str:
    from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
        SqlProjectRepository,
    )

    normalized_project_id = project_id.strip()
    if not normalized_project_id:
        raise RuntimeV2Error(
            "reflection_project_missing",
            "Reflection requires a non-empty project_id",
        )
    project = await SqlProjectRepository(session).find_by_id(normalized_project_id)
    if project is None:
        raise RuntimeV2Error(
            "reflection_project_not_found",
            "Reflection project does not exist",
        )
    normalized_tenant_id = (tenant_id or "").strip()
    if normalized_tenant_id and normalized_tenant_id != project.tenant_id:
        raise RuntimeV2Error(
            "reflection_tenant_scope_mismatch",
            "Reflection project is outside the pinned tenant scope",
        )
    return project.tenant_id


async def _publish_reflection_complete_v2(
    redis_client: object,
    payload: object,
) -> None:
    from src.domain.events.envelope import EventEnvelope
    from src.infrastructure.adapters.secondary.messaging.redis_unified_event_bus import (
        RedisUnifiedEventBusAdapter,
    )

    if not isinstance(payload, dict):
        raise RuntimeV2Error(
            "invalid_reflection_complete_payload",
            "Reflection completion payload must be an object",
        )
    typed_payload = cast("dict[str, object]", payload)
    project_id = typed_payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise RuntimeV2Error(
            "invalid_reflection_complete_project",
            "Reflection completion payload requires project_id",
        )
    try:
        bus = RedisUnifiedEventBusAdapter(cast("Redis", redis_client))
        _ = await bus.publish(
            EventEnvelope(event_type="reflection_complete", payload=typed_payload),
            f"project:{project_id}:reflection_complete",
        )
    except Exception:
        logger.exception(
            "Failed to publish reflection_complete",
            extra={"project_id": project_id, "status": typed_payload.get("status")},
        )


def _reflection_runtime_config_v2(config: Mapping[str, Any]) -> ReflectionRuntimeConfigV2:
    if config.get("strategy") != "periodic-reflection":
        raise ValueError("Reflection runtime requires strategy periodic-reflection")
    enabled = config.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("Reflection runtime enabled must be a boolean")
    interval = _positive_number_v2(config, "interval_seconds")
    timeout = _positive_number_v2(config, "per_project_timeout_seconds")
    window_minutes = config.get("window_minutes")
    if (
        not isinstance(window_minutes, int)
        or isinstance(window_minutes, bool)
        or window_minutes <= 0
    ):
        raise ValueError("Reflection runtime window_minutes must be a positive integer")
    raw_lane_order = config.get("lane_order")
    if not isinstance(raw_lane_order, list):
        raise ValueError("Reflection runtime lane_order must be a non-empty string array")
    lane_items: list[str] = []
    for item in cast("list[object]", raw_lane_order):
        if not isinstance(item, str) or not item.strip():
            raise ValueError("Reflection runtime lane_order must be a non-empty string array")
        lane_items.append(item)
    lane_order = tuple(lane_items)
    if len(lane_order) < 2 or len(set(lane_order)) != len(lane_order):
        raise ValueError("Reflection runtime lane_order must contain unique ordered lanes")
    return ReflectionRuntimeConfigV2(
        enabled=enabled,
        interval_seconds=interval,
        per_project_timeout_seconds=timeout,
        window_minutes=window_minutes,
        lane_order=lane_order,
    )


def _positive_number_v2(config: Mapping[str, Any], name: str) -> float:
    value = config.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"Reflection runtime {name} must be positive")
    return float(value)


def reflection_runtime_definition_v2(
    runtime: ReflectionRuntimeManagerV2 | None = None,
) -> PluginDefinitionV2:
    """Bind Reflection ingestion, execution, events, and scheduler to one V2 effect."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        resolved_config = _reflection_runtime_config_v2(config)
        runtime_manager = runtime
        if runtime_manager is None:
            _ = context.provide(
                REFLECTION_RUNTIME_SERVICE_V2,
                UnavailableReflectionRuntimeServiceV2(),
                label="reflection-runtime-unavailable",
            )
            return None
        sessions = context.require(REFLECTION_RUNTIME_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryProviderProtocolV2):
            raise RuntimeV2Error(
                "invalid_reflection_runtime_sessions",
                "Reflection sessions inject has an invalid implementation",
            )
        llm_clients = context.require(REFLECTION_RUNTIME_LLM_CLIENTS_INJECT_V2)
        if not isinstance(llm_clients, TenantLlmClientFactoryProtocolV2):
            raise RuntimeV2Error(
                "invalid_reflection_runtime_llm_clients",
                "Reflection LLM client inject has an invalid implementation",
            )

        async def publish_completion(payload: object) -> None:
            await _publish_reflection_complete_v2(runtime_manager.redis_client, payload)

        _ = context.on(REFLECTION_COMPLETE_EVENT_V2, publish_completion)
        await runtime_manager.acquire_generation(sessions=sessions, config=resolved_config)
        service = ReflectionRuntimeServiceV2(
            runtime=runtime_manager,
            sessions=sessions,
            llm_clients=llm_clients,
            context=context,
            config=resolved_config,
        )
        try:
            _ = context.provide(
                REFLECTION_RUNTIME_SERVICE_V2,
                service,
                label="reflection-runtime",
            )
        except Exception:
            await runtime_manager.release_generation()
            raise

        async def dispose() -> None:
            await runtime_manager.release_generation()

        return dispose

    return PluginDefinitionV2(
        module_ref=REFLECTION_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(REFLECTION_RUNTIME_MODULE_V2),
        apply=apply,
    )


def current_reflection_runtime_v2() -> ReflectionRuntimeServiceProtocolV2:
    """Resolve Reflection from the exact generation pinned to the operation."""
    from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

    from .boundary import current_generation_v2

    service = current_generation_v2().resolve(
        REFLECTION_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(service, ReflectionRuntimeServiceProtocolV2):
        raise RuntimeV2Error(
            "invalid_reflection_runtime",
            "Resolved Reflection runtime service has an invalid implementation",
        )
    return service


__all__ = [
    "REFLECTION_COMPLETE_EVENT_V2",
    "REFLECTION_RUNTIME_LLM_CLIENTS_INJECT_V2",
    "REFLECTION_RUNTIME_MODULE_V2",
    "REFLECTION_RUNTIME_SERVICE_V2",
    "REFLECTION_RUNTIME_SESSIONS_INJECT_V2",
    "AsyncSessionFactoryProviderProtocolV2",
    "ReflectionRuntimeConfigV2",
    "ReflectionRuntimeManagerV2",
    "ReflectionRuntimeServiceProtocolV2",
    "ReflectionRuntimeServiceV2",
    "UnavailableReflectionRuntimeServiceV2",
    "current_reflection_runtime_v2",
    "reflection_runtime_definition_v2",
]
