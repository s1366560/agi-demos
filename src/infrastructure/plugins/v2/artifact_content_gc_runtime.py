"""Generation-owned object storage and Artifact content orphan GC runtime."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.configuration.config import get_settings
from src.domain.ports.services.storage_service_port import StorageServicePort
from src.infrastructure.adapters.secondary.persistence.artifact_content_orphan_gc_worker import (
    MAX_ARTIFACT_ORPHAN_GC_BATCH_SIZE,
    ArtifactContentOrphanGcWorker,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.storage.s3_storage_adapter import S3StorageAdapter

from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

ASYNC_SESSION_FACTORY_MODULE_V2 = "builtin://memstack/persistence/async-session-factory"
ASYNC_SESSION_FACTORY_SERVICE_V2 = "service:persistence.async-session-factory"
OBJECT_STORAGE_PROVIDER_MODULE_V2 = "builtin://memstack/storage/object-storage-provider"
OBJECT_STORAGE_SERVICE_V2 = "service:storage.object-storage"
ARTIFACT_CONTENT_GC_MODULE_V2 = "builtin://memstack/persistence/artifact-content-orphan-gc"
ARTIFACT_CONTENT_GC_RUNTIME_SERVICE_V2 = "service:runtime.artifact-content-orphan-gc"
ARTIFACT_CONTENT_GC_SESSIONS_INJECT_V2 = "sessions"
ARTIFACT_CONTENT_GC_STORAGE_INJECT_V2 = "storage"

_ENABLED_ENV_V2 = "ARTIFACT_CONTENT_ORPHAN_GC_ENABLED"
_POLL_ENV_V2 = "ARTIFACT_CONTENT_ORPHAN_GC_POLL_SECONDS"
_BATCH_ENV_V2 = "ARTIFACT_CONTENT_ORPHAN_GC_BATCH_SIZE"
_LEASE_ENV_V2 = "ARTIFACT_CONTENT_ORPHAN_GC_LEASE_SECONDS"

type ObjectStorageFactoryV2 = Callable[[], StorageServicePort]
type ArtifactContentOrphanGcWorkerFactoryV2 = Callable[..., ArtifactContentOrphanGcWorker]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AsyncSessionFactoryServiceV2:
    """Explicit process session-factory Provider value."""

    factory: async_sessionmaker[AsyncSession]


@dataclass(frozen=True, kw_only=True)
class ObjectStorageServiceV2:
    """Object storage adapter selected by the active generation."""

    storage_service: StorageServicePort
    strategy: str


@dataclass(frozen=True, kw_only=True)
class ArtifactContentOrphanGcConfigV2:
    """Validated worker settings pinned to one process-boundary effect."""

    enabled: bool
    poll_interval_seconds: float
    batch_size: int
    lease_seconds: int


@dataclass(kw_only=True)
class ArtifactContentOrphanGcRuntimeV2:
    """Reference-count one durable worker across overlapping generations."""

    worker_factory: ArtifactContentOrphanGcWorkerFactoryV2
    _worker: ArtifactContentOrphanGcWorker | None = None
    _config: ArtifactContentOrphanGcConfigV2 | None = None
    _generation_references: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def generation_references(self) -> int:
        return self._generation_references

    @property
    def worker(self) -> ArtifactContentOrphanGcWorker | None:
        return self._worker

    async def acquire_generation(
        self,
        *,
        sessions: AsyncSessionFactoryServiceV2,
        storage: ObjectStorageServiceV2,
        config: ArtifactContentOrphanGcConfigV2,
    ) -> None:
        """Start the worker only for the first staged generation."""
        async with self._lock:
            if self._generation_references > 0:
                if self._config != config:
                    raise RuntimeV2Error(
                        "artifact_content_gc_process_boundary_mismatch",
                        "Artifact content GC config changed inside a process boundary",
                    )
                self._generation_references += 1
                return

            self._config = config
            if config.enabled:
                worker = self.worker_factory(
                    session_factory=sessions.factory,
                    storage_service=storage.storage_service,
                    poll_interval_seconds=config.poll_interval_seconds,
                    batch_size=config.batch_size,
                    lease_seconds=config.lease_seconds,
                )
                try:
                    worker.start()
                except BaseException:
                    try:
                        await worker.stop()
                    except Exception:
                        logger.exception("Failed to clean up Artifact content GC candidate")
                    self._config = None
                    raise
                self._worker = worker
            self._generation_references = 1

    async def release_generation(self) -> None:
        """Stop after the last active or draining generation releases the effect."""
        async with self._lock:
            if self._generation_references <= 0:
                raise RuntimeV2Error(
                    "artifact_content_gc_reference_underflow",
                    "Artifact content GC generation reference count underflow",
                )
            self._generation_references -= 1
            if self._generation_references != 0:
                return
            worker = self._worker
            self._worker = None
            self._config = None
            if worker is not None:
                await worker.stop()


def _default_object_storage_factory_v2() -> StorageServicePort:
    settings = get_settings()
    return S3StorageAdapter(
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.s3_endpoint_url,
        no_proxy=settings.s3_no_proxy,
    )


def _environment_bool_v2(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _environment_positive_float_v2(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _environment_positive_int_v2(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _gc_config_v2(config: Mapping[str, Any]) -> ArtifactContentOrphanGcConfigV2:
    if config.get("strategy") != "durable-bounded-worker":
        raise ValueError("Artifact content GC requires strategy durable-bounded-worker")
    enabled = config.get("enabled")
    poll_interval_seconds = config.get("poll_interval_seconds")
    batch_size = config.get("batch_size")
    lease_seconds = config.get("lease_seconds")
    environment_overrides = config.get("environment_overrides")
    if not isinstance(enabled, bool):
        raise ValueError("Artifact content GC enabled must be a boolean")
    if isinstance(poll_interval_seconds, bool) or not isinstance(
        poll_interval_seconds, (int, float)
    ):
        raise ValueError("Artifact content GC poll interval must be numeric")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int):
        raise ValueError("Artifact content GC batch size must be an integer")
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
        raise ValueError("Artifact content GC lease duration must be an integer")
    if not isinstance(environment_overrides, bool):
        raise ValueError("Artifact content GC environment_overrides must be a boolean")

    resolved_poll = float(poll_interval_seconds)
    resolved_batch = batch_size
    resolved_lease = lease_seconds
    if environment_overrides:
        enabled = _environment_bool_v2(_ENABLED_ENV_V2, enabled)
        resolved_poll = _environment_positive_float_v2(_POLL_ENV_V2, resolved_poll)
        resolved_batch = _environment_positive_int_v2(_BATCH_ENV_V2, resolved_batch)
        resolved_lease = _environment_positive_int_v2(_LEASE_ENV_V2, resolved_lease)
    if resolved_poll <= 0:
        raise ValueError("Artifact content GC poll interval must be positive")
    if resolved_batch < 1 or resolved_batch > MAX_ARTIFACT_ORPHAN_GC_BATCH_SIZE:
        raise ValueError("Artifact content GC batch size is out of range")
    if resolved_lease < 1:
        raise ValueError("Artifact content GC lease duration must be positive")
    return ArtifactContentOrphanGcConfigV2(
        enabled=enabled,
        poll_interval_seconds=resolved_poll,
        batch_size=resolved_batch,
        lease_seconds=resolved_lease,
    )


def async_session_factory_definition_v2() -> PluginDefinitionV2:
    """Publish the SQLAlchemy process session factory through an explicit seam."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "sqlalchemy-async-sessionmaker":
            raise ValueError(
                "async session factory requires strategy sqlalchemy-async-sessionmaker"
            )
        _ = context.provide(
            ASYNC_SESSION_FACTORY_SERVICE_V2,
            AsyncSessionFactoryServiceV2(factory=async_session_factory),
            label="async-session-factory",
        )

    return PluginDefinitionV2(
        module_ref=ASYNC_SESSION_FACTORY_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ASYNC_SESSION_FACTORY_MODULE_V2),
        apply=apply,
    )


def object_storage_provider_definition_v2(
    storage_factory: ObjectStorageFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Publish the configured S3-compatible adapter through a service key."""
    factory = storage_factory or _default_object_storage_factory_v2

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        strategy = config.get("strategy")
        if strategy != "s3-settings":
            raise ValueError("object storage Provider requires strategy s3-settings")
        _ = context.provide(
            OBJECT_STORAGE_SERVICE_V2,
            ObjectStorageServiceV2(storage_service=factory(), strategy=strategy),
            label="object-storage-provider",
        )

    return PluginDefinitionV2(
        module_ref=OBJECT_STORAGE_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(OBJECT_STORAGE_PROVIDER_MODULE_V2),
        apply=apply,
    )


def artifact_content_orphan_gc_definition_v2(
    worker_factory: ArtifactContentOrphanGcWorkerFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Bind the durable GC worker to one reversible process-boundary effect."""
    runtime = ArtifactContentOrphanGcRuntimeV2(
        worker_factory=worker_factory or ArtifactContentOrphanGcWorker
    )

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        sessions = context.require(ARTIFACT_CONTENT_GC_SESSIONS_INJECT_V2)
        if not isinstance(sessions, AsyncSessionFactoryServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_gc_sessions",
                "Artifact content GC sessions inject has an invalid implementation",
            )
        storage = context.require(ARTIFACT_CONTENT_GC_STORAGE_INJECT_V2)
        if not isinstance(storage, ObjectStorageServiceV2):
            raise RuntimeV2Error(
                "invalid_artifact_content_gc_storage",
                "Artifact content GC storage inject has an invalid implementation",
            )
        await runtime.acquire_generation(
            sessions=sessions,
            storage=storage,
            config=_gc_config_v2(config),
        )
        try:
            _ = context.provide(
                ARTIFACT_CONTENT_GC_RUNTIME_SERVICE_V2,
                runtime,
                label="artifact-content-orphan-gc",
            )
        except Exception:
            await runtime.release_generation()
            raise

        async def dispose() -> None:
            await runtime.release_generation()

        return dispose

    return PluginDefinitionV2(
        module_ref=ARTIFACT_CONTENT_GC_MODULE_V2,
        contract_digest=generated_contract_digest_v2(ARTIFACT_CONTENT_GC_MODULE_V2),
        apply=apply,
    )


def artifact_content_gc_definitions_v2() -> tuple[PluginDefinitionV2, ...]:
    """Return persistence/storage Providers followed by the GC Consumer."""
    return (
        async_session_factory_definition_v2(),
        object_storage_provider_definition_v2(),
        artifact_content_orphan_gc_definition_v2(),
    )


__all__ = [
    "ARTIFACT_CONTENT_GC_MODULE_V2",
    "ARTIFACT_CONTENT_GC_RUNTIME_SERVICE_V2",
    "ARTIFACT_CONTENT_GC_SESSIONS_INJECT_V2",
    "ARTIFACT_CONTENT_GC_STORAGE_INJECT_V2",
    "ASYNC_SESSION_FACTORY_MODULE_V2",
    "ASYNC_SESSION_FACTORY_SERVICE_V2",
    "OBJECT_STORAGE_PROVIDER_MODULE_V2",
    "OBJECT_STORAGE_SERVICE_V2",
    "ArtifactContentOrphanGcConfigV2",
    "ArtifactContentOrphanGcRuntimeV2",
    "ArtifactContentOrphanGcWorkerFactoryV2",
    "AsyncSessionFactoryServiceV2",
    "ObjectStorageFactoryV2",
    "ObjectStorageServiceV2",
    "artifact_content_gc_definitions_v2",
    "artifact_content_orphan_gc_definition_v2",
    "async_session_factory_definition_v2",
    "object_storage_provider_definition_v2",
]
