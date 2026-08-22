"""Complete protocol-v2 Bundle/ProfileSource candidate reconciliation."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TypeVar, cast

from src.domain.model.plugins.generated_v2 import (
    BundleReferenceV2,
    DataPlaneTargetV2,
    DesiredBundleSetV2,
    PluginModuleV2,
    ProfileSourceReferenceV2,
    ProfileSourceV2,
    ScopeKindV2,
    ScopeV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .artifacts import (
    PluginArtifactResolverV2,
    RepositoryPythonArtifactResolverV2,
    ResolvedPluginArtifactV2,
)
from .bundle_archive import VerifiedBundleArchiveV2, parse_bundle_archive_v2
from .composer import compose_profile_v2
from .layer_composer import compose_profile_sources_v2
from .protocol import (
    control_envelope_v2,
    parse_desired_bundle_set_v2,
    parse_profile_source_v2,
)
from .reconciler import (
    GenerationPublicationStagerV2,
    PreparedGenerationPublicationV2,
)
from .runtime import LoaderV2, PluginDefinitionV2, RuntimeGenerationV2, RuntimeV2Error
from .runtime_contracts import ModuleCatalogEntryV2
from .runtime_host import PlatformPluginPublicationV2, PlatformPluginRuntimeHostV2

logger = logging.getLogger(__name__)

MAX_DESIRED_BUNDLE_SET_BYTES_V2 = 2 * 1024 * 1024
MAX_PROFILE_SOURCE_BYTES_V2 = 8 * 1024 * 1024

type DesiredBundleSetLoaderV2 = Callable[[], bytes | Awaitable[bytes]]
type BundleFetcherV2 = Callable[[BundleReferenceV2], bytes | Awaitable[bytes]]
type ProfileSourceFetcherV2 = Callable[[ProfileSourceReferenceV2], bytes | Awaitable[bytes]]
type GenerationHealthCheckV2 = Callable[[RuntimeGenerationV2], None | Awaitable[None]]
type ProfileWatchCallbackV2 = Callable[["ProfileWatchEventV2"], None | Awaitable[None]]

_T = TypeVar("_T")


class ProfileWatcherV2Error(ValueError):
    """Stable candidate-build failure raised before runtime staging."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ProfileWatchOutcomeV2(StrEnum):
    APPLIED = "applied"
    REJECTED = "rejected"


@dataclass(frozen=True, kw_only=True)
class BundleTrustPolicyV2:
    """Explicit trust and permission policy applied to every fetched `.mspkg`."""

    trusted_public_keys: tuple[str, ...]
    approved_permissions: frozenset[str]
    require_signature: bool = True
    require_provenance: bool = True


@dataclass(frozen=True, kw_only=True)
class ProfileWatchEventV2:
    """One complete-candidate apply or contained rejection."""

    outcome: ProfileWatchOutcomeV2
    desired_set_id: str | None
    desired_set_revision: int | None
    desired_set_digest: str | None
    attempted_generation: int
    requested_version: int
    applied_descriptor: PluginGenerationDescriptorV2 | None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, kw_only=True)
class ProfileWatchScheduleV2:
    """Polling cadence and monotonic local publication counters."""

    interval_seconds: float = 1.0
    start_generation: int = 1
    start_version: int = 1


class CandidateBundleArtifactResolverV2:
    """Bind verified target bytes to the executable artifact used by one candidate task."""

    def __init__(
        self,
        delegate: PluginArtifactResolverV2,
        *,
        target: DataPlaneTargetV2 = DataPlaneTargetV2.PYTHON,
    ) -> None:
        self._delegate = delegate
        self._target = target
        self._bound: ContextVar[Mapping[tuple[DataPlaneTargetV2, str], bytes] | None] = ContextVar(
            "memstack_candidate_bundle_artifacts_v2", default=None
        )

    @contextlib.contextmanager
    def bind(self, archives: Sequence[VerifiedBundleArchiveV2]) -> Iterator[None]:
        artifacts: dict[tuple[DataPlaneTargetV2, str], bytes] = {}
        for archive in archives:
            for artifact in archive.manifest.artifacts:
                if artifact.target is not self._target:
                    continue
                content = archive.artifacts[artifact.artifact_id]
                key = (artifact.target, artifact.digest)
                previous = artifacts.get(key)
                if previous is not None and previous != content:
                    raise ProfileWatcherV2Error(
                        "candidate_artifact_conflict",
                        f"candidate repeats {artifact.target.value} artifact {artifact.digest}",
                    )
                artifacts[key] = content
        token = self._bound.set(MappingProxyType(artifacts))
        try:
            yield
        finally:
            self._bound.reset(token)

    def resolve(self, module: PluginModuleV2) -> ResolvedPluginArtifactV2:
        artifacts = self._bound.get()
        if artifacts is None:
            raise RuntimeV2Error(
                "candidate_artifacts_unbound",
                f"module {module.module_ref} was resolved outside a complete candidate",
            )
        expected = artifacts.get((self._target, module.artifact.digest))
        if expected is None:
            raise RuntimeV2Error(
                "candidate_artifact_missing",
                f"module {module.module_ref} has no verified {self._target.value} artifact",
            )
        resolved = self._delegate.resolve(module)
        if resolved.canonical_bytes != expected:
            raise RuntimeV2Error(
                "candidate_execution_artifact_mismatch",
                f"module {module.module_ref} executable bytes differ from its verified bundle",
            )
        return resolved


class ProfileWatcherV2:
    """Poll desired state and atomically replace only complete, healthy generations."""

    def __init__(
        self,
        *,
        desired_set_loader: DesiredBundleSetLoaderV2,
        bundle_fetcher: BundleFetcherV2,
        profile_source_fetcher: ProfileSourceFetcherV2,
        trust_policy: BundleTrustPolicyV2,
        definitions: Sequence[PluginDefinitionV2] = (),
        target_catalog: Mapping[str, ModuleCatalogEntryV2] | None = None,
        execution_artifact_resolver: PluginArtifactResolverV2 | None = None,
        scope: ScopeV2 = ScopeV2(kind=ScopeKindV2.ROOT),
        health_checks: Sequence[GenerationHealthCheckV2] = (),
        publication_stager: GenerationPublicationStagerV2 | None = None,
        on_event: ProfileWatchCallbackV2 | None = None,
        schedule: ProfileWatchScheduleV2 = ProfileWatchScheduleV2(),
    ) -> None:
        if schedule.interval_seconds <= 0:
            raise ValueError("v2 profile watch interval must be positive")
        if schedule.start_generation < 1 or schedule.start_version < 1:
            raise ValueError("v2 profile generation and version must start at one or greater")
        self._desired_set_loader = desired_set_loader
        self._bundle_fetcher = bundle_fetcher
        self._profile_source_fetcher = profile_source_fetcher
        self._trust_policy = trust_policy
        self._scope = scope
        self._health_checks = tuple(health_checks)
        self._publication_stager = publication_stager
        self._on_event = on_event
        self._interval = schedule.interval_seconds
        self._next_generation = schedule.start_generation
        self._next_version = schedule.start_version
        self._last_good_desired_set: DesiredBundleSetV2 | None = None
        self._poll_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

        execution_resolver = execution_artifact_resolver or RepositoryPythonArtifactResolverV2()
        self._candidate_artifacts = CandidateBundleArtifactResolverV2(execution_resolver)
        loader = LoaderV2(
            definitions,
            target_catalog=target_catalog,
            artifact_resolver=self._candidate_artifacts,
        )
        self.host = PlatformPluginRuntimeHostV2(loader=loader)

    @property
    def last_good(self) -> PlatformPluginPublicationV2 | None:
        return self.host.current_publication

    @property
    def last_good_desired_set(self) -> DesiredBundleSetV2 | None:
        return self._last_good_desired_set

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="memstack-profile-watch-v2")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        _ = task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def close(self) -> None:
        await self.stop()
        await self.host.close()
        self._last_good_desired_set = None

    async def poll_once(self) -> ProfileWatchEventV2 | None:
        async with self._poll_lock:
            desired_set: DesiredBundleSetV2 | None = None
            try:
                desired_set = await self._load_desired_set()
                if (
                    self._last_good_desired_set is not None
                    and desired_set.digest == self._last_good_desired_set.digest
                ):
                    return None
                archives = await self._load_archives(desired_set)
                profile_source = await self._load_profile_source(desired_set.profile_source)
                if self._trust_policy.require_provenance and profile_source.provenance is None:
                    raise ProfileWatcherV2Error(
                        "profile_source_provenance_required",
                        f"profile source {profile_source.source_id} has no provenance",
                    )
                composition = compose_profile_sources_v2(
                    desired_set=desired_set,
                    bundles=tuple(archive.manifest for archive in archives),
                    profile_source=profile_source,
                    scope=self._scope,
                )
                manifests = {manifest.plugin_id: manifest for manifest in composition.manifests}
                snapshot = compose_profile_v2(
                    composition.document,
                    manifests,
                    generation=self._next_generation,
                )
                with self._candidate_artifacts.bind(archives):
                    publication = await self.host.apply(
                        snapshot,
                        control_envelope_v2(snapshot, version=self._next_version),
                        publication_stager=self._prepare_publication,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                event = self._rejected_event(desired_set, exc)
                await self._notify(event)
                return event

            if not publication.accepted:
                event = self._receipt_rejected_event(desired_set, publication)
                await self._notify(event)
                return event

            self._last_good_desired_set = desired_set
            event = self._event(ProfileWatchOutcomeV2.APPLIED, desired_set=desired_set)
            self._next_generation += 1
            self._next_version += 1
            await self._notify(event)
            return event

    async def _run(self) -> None:
        while True:
            _ = await self.poll_once()
            await asyncio.sleep(self._interval)

    async def _load_desired_set(self) -> DesiredBundleSetV2:
        raw = await _resolve(self._desired_set_loader())
        payload = _json_payload(
            raw,
            kind="desired_bundle_set",
            maximum_bytes=MAX_DESIRED_BUNDLE_SET_BYTES_V2,
        )
        return parse_desired_bundle_set_v2(payload)

    async def _load_archives(
        self,
        desired_set: DesiredBundleSetV2,
    ) -> tuple[VerifiedBundleArchiveV2, ...]:
        archives: list[VerifiedBundleArchiveV2] = []
        for reference in desired_set.bundles:
            raw = await _resolve(self._bundle_fetcher(reference))
            archive = parse_bundle_archive_v2(
                raw,
                source=reference.source,
                trusted_public_keys=self._trust_policy.trusted_public_keys,
                approved_permissions=self._trust_policy.approved_permissions,
                require_signature=self._trust_policy.require_signature,
                require_provenance=self._trust_policy.require_provenance,
            )
            archives.append(archive)
        return tuple(archives)

    async def _load_profile_source(
        self,
        reference: ProfileSourceReferenceV2,
    ) -> ProfileSourceV2:
        raw = await _resolve(self._profile_source_fetcher(reference))
        payload = _json_payload(
            raw,
            kind="profile_source",
            maximum_bytes=MAX_PROFILE_SOURCE_BYTES_V2,
        )
        return parse_profile_source_v2(payload)

    async def _prepare_publication(
        self,
        generation: RuntimeGenerationV2,
    ) -> PreparedGenerationPublicationV2:
        for check in self._health_checks:
            await _resolve(check(generation))
        if self._publication_stager is not None:
            return await self._publication_stager(generation)
        return PreparedGenerationPublicationV2(commit=lambda: None, rollback=lambda: None)

    def _receipt_rejected_event(
        self,
        desired_set: DesiredBundleSetV2,
        publication: PlatformPluginPublicationV2,
    ) -> ProfileWatchEventV2:
        return self._event(
            ProfileWatchOutcomeV2.REJECTED,
            desired_set=desired_set,
            error_code=publication.receipt.error_code or "candidate_rejected",
            error_message=publication.receipt.error_message or "candidate was rejected",
        )

    def _rejected_event(
        self,
        desired_set: DesiredBundleSetV2 | None,
        error: Exception,
    ) -> ProfileWatchEventV2:
        code = getattr(error, "code", "candidate_build_failed")
        return self._event(
            ProfileWatchOutcomeV2.REJECTED,
            desired_set=desired_set,
            error_code=code if isinstance(code, str) else "candidate_build_failed",
            error_message=f"{type(error).__name__}: {error}",
        )

    def _event(
        self,
        outcome: ProfileWatchOutcomeV2,
        *,
        desired_set: DesiredBundleSetV2 | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ProfileWatchEventV2:
        active = self.host.manager.current
        return ProfileWatchEventV2(
            outcome=outcome,
            desired_set_id=None if desired_set is None else desired_set.desired_set_id,
            desired_set_revision=None if desired_set is None else desired_set.revision,
            desired_set_digest=None if desired_set is None else desired_set.digest,
            attempted_generation=self._next_generation,
            requested_version=self._next_version,
            applied_descriptor=None if active is None else active.descriptor,
            error_code=error_code,
            error_message=error_message,
        )

    async def _notify(self, event: ProfileWatchEventV2) -> None:
        if self._on_event is None:
            return
        try:
            await _resolve(self._on_event(event))
        except Exception:
            logger.exception("protocol-v2 profile watcher event callback failed")


def _json_payload(raw: object, *, kind: str, maximum_bytes: int) -> object:
    if not isinstance(raw, bytes):
        raise ProfileWatcherV2Error(f"{kind}_invalid", f"{kind} fetcher must return bytes")
    if len(raw) > maximum_bytes:
        raise ProfileWatcherV2Error(f"{kind}_too_large", f"{kind} exceeds size limit")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileWatcherV2Error(f"{kind}_invalid", f"{kind} is not valid JSON") from exc


async def _resolve(value: _T | Awaitable[_T]) -> _T:
    if inspect.isawaitable(value):
        return await cast(Awaitable[_T], value)
    return value


__all__ = [
    "BundleFetcherV2",
    "BundleTrustPolicyV2",
    "CandidateBundleArtifactResolverV2",
    "DesiredBundleSetLoaderV2",
    "GenerationHealthCheckV2",
    "ProfileSourceFetcherV2",
    "ProfileWatchEventV2",
    "ProfileWatchOutcomeV2",
    "ProfileWatchScheduleV2",
    "ProfileWatcherV2",
    "ProfileWatcherV2Error",
]
