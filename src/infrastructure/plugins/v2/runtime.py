"""Fiber, loader, operation, and generation semantics for plugin runtime v2."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol, cast

from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    EventContractV2,
    PluginContractV2,
    PluginModuleV2,
    ProfileEntryV2,
    ProfileSnapshotV2,
    ScopeKindV2,
    ScopeV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2

from .artifacts import (
    PluginArtifactResolverV2,
    RepositoryPythonArtifactResolverV2,
    ResolvedPluginArtifactV2,
)
from .bundle_archive import VerifiedBundleArchiveV2
from .lifecycle_tasks import OwnedLifecycleTaskV2
from .runtime_context import (
    AsyncDisposerV2,
    ContextV2,
    EffectDiagnosticV2,
    EffectResultV2,
    FiberDiagnosticV2,
    FiberPhaseV2,
    RuntimeV2Error,
    _EffectStack,
    _EventBusV2,
    _ProviderStore,
)
from .runtime_contracts import (
    ModuleCatalogEntryV2,
    entry_order_v2,
    event_contract_catalog_v2,
    generated_contract_digest_v2,
    generated_target_catalog_v2,
    preflight_entries_v2,
)
from .verified_execution_artifacts import attest_execution_artifacts_v2

type PluginApplyV2 = Callable[
    [ContextV2, Mapping[str, Any]],
    EffectResultV2 | Awaitable[EffectResultV2],
]
type _PluginModuleRowV2 = tuple[str, str, PluginModuleV2]


@dataclass(frozen=True, kw_only=True)
class PluginDefinitionV2:
    """A trusted runtime entry bound to one exact generated contract digest."""

    module_ref: str
    contract_digest: str
    apply: PluginApplyV2


class FiberV2:
    """One entry activation with explicit state and asynchronous LIFO cleanup."""

    def __init__(
        self,
        *,
        entry: ProfileEntryV2,
        definition: PluginDefinitionV2,
        contract: PluginContractV2,
        event_contracts: Mapping[str, EventContractV2],
        providers: _ProviderStore,
        events: _EventBusV2,
    ) -> None:
        self.entry = entry
        self.definition = definition
        self.contract = contract
        self.phase = FiberPhaseV2.PENDING
        self.error: BaseException | None = None
        self._effects = _EffectStack(lambda: self.phase)
        self.context = ContextV2(
            entry_id=entry.entry_id,
            scope=entry.scope,
            providers=providers,
            events=events,
            effects=self._effects,
            contract=contract,
            event_contracts=event_contracts,
            inject=entry.inject,
            isolation=entry.isolate,
        )
        self._disposal = OwnedLifecycleTaskV2(self._dispose, name="plugin-fiber-drain-v2")

    async def start(self) -> None:
        if self.phase != FiberPhaseV2.PENDING:
            raise RuntimeV2Error("invalid_fiber_transition", f"cannot start from {self.phase}")
        self.phase = FiberPhaseV2.LOADING
        try:
            result = self.definition.apply(self.context, self.entry.config)
            if inspect.isawaitable(result):
                result = await result
            await self._effects.add_result(result, label="apply")
            self.phase = FiberPhaseV2.ACTIVE
        except BaseException as exc:
            self.error = exc
            self.phase = FiberPhaseV2.FAILED
            try:
                await self._effects.dispose()
            except BaseException as cleanup_error:
                raise BaseExceptionGroup(
                    "Fiber activation and cleanup failed", [exc, cleanup_error]
                ) from None
            raise

    async def dispose(self) -> None:
        if not self._disposal.started and self.phase is not FiberPhaseV2.PENDING:
            self.phase = FiberPhaseV2.UNLOADING
        await self._disposal.wait()

    async def _dispose(self) -> None:
        if self.phase == FiberPhaseV2.PENDING:
            self.phase = FiberPhaseV2.DISPOSED
            return
        self.phase = FiberPhaseV2.UNLOADING
        try:
            await self._effects.dispose()
        finally:
            self.phase = FiberPhaseV2.DISPOSED

    def diagnostics(self) -> FiberDiagnosticV2:
        return FiberDiagnosticV2(
            entry_id=self.entry.entry_id,
            phase=self.phase,
            effects=self._effects.diagnostics(),
            error=None if self.error is None else f"{type(self.error).__name__}: {self.error}",
        )


class RuntimeGenerationV2:
    """An immutable published entry set; mutable state is private lifecycle metadata."""

    def __init__(
        self,
        *,
        snapshot: ProfileSnapshotV2,
        fibers: Sequence[FiberV2],
        providers: _ProviderStore,
        events: _EventBusV2,
        event_contracts: Mapping[str, EventContractV2],
    ) -> None:
        self.snapshot = snapshot
        self.fibers = tuple(fibers)
        self._providers = providers
        self._events = events
        self._event_contracts = MappingProxyType(dict(event_contracts))
        self._lease_count = 0
        self._retired = False
        self._disposed = False
        self._disposal = OwnedLifecycleTaskV2(self._dispose, name="plugin-generation-drain-v2")

    @property
    def generation(self) -> int:
        return self.snapshot.generation

    @property
    def digest(self) -> str:
        return self.snapshot.digest

    @property
    def descriptor(self) -> PluginGenerationDescriptorV2:
        return PluginGenerationDescriptorV2(
            profile_id=self.snapshot.profile_id,
            generation=self.snapshot.generation,
            digest=self.snapshot.digest,
        )

    def resolve(
        self,
        service: str,
        scope: ScopeV2,
        *,
        version: str = "1.0.0",
        isolation: str | None = None,
    ) -> object:
        if self._disposed:
            raise RuntimeV2Error("disposed_generation", "generation is disposed")
        return self._providers.resolve(service, version, scope, isolation)

    async def dispose(self) -> None:
        await self._disposal.wait()

    async def _dispose(self) -> None:
        errors: list[BaseException] = []
        for fiber in reversed(self.fibers):
            try:
                await fiber.dispose()
            except BaseException as error:
                errors.append(error)
        self._disposed = True
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("Generation cleanup failed", errors)


class OperationContextV2:
    """An isolated, disposable service overlay for one request, turn, or operation."""

    def __init__(
        self,
        *,
        generation: RuntimeGenerationV2,
        operation_id: str,
        scope: ScopeV2,
    ) -> None:
        self.generation = generation
        self.operation_id = operation_id
        self.phase = FiberPhaseV2.PENDING
        self._effects = _EffectStack(lambda: self.phase)
        providers = _ProviderStore(generation._providers)
        events = _EventBusV2(generation._events)
        root = ContextV2(
            entry_id=f"operation:{operation_id}",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
            providers=providers,
            events=events,
            effects=self._effects,
            event_contracts=generation._event_contracts,
            privileged=True,
        )
        contexts = [root]
        for child_scope in _operation_scope_chain(scope)[1:]:
            contexts.append(contexts[-1].extend(scope=child_scope))
        self.contexts = tuple(contexts)
        self.context = self.contexts[-1]
        self._disposal = OwnedLifecycleTaskV2(self._dispose, name="plugin-operation-drain-v2")

    @property
    def descriptor(self) -> PluginGenerationDescriptorV2:
        return self.generation.descriptor

    async def __aenter__(self) -> OperationContextV2:
        if self.phase is not FiberPhaseV2.PENDING:
            raise RuntimeV2Error(
                "invalid_operation_transition",
                f"cannot start operation from {self.phase}",
            )
        self.phase = FiberPhaseV2.LOADING
        self.phase = FiberPhaseV2.ACTIVE
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.dispose()

    def provide(
        self,
        service: str,
        value: object,
        *,
        version: str = "1.0.0",
        label: str | None = None,
    ) -> AsyncDisposerV2:
        return self.context.provide(service, value, version=version, label=label)

    def require(self, service: str, *, version: str = "1.0.0") -> object:
        self._ensure_active()
        return self.context.require(service, version=version)

    async def dispatch(self, event: str, payload: object) -> object:
        self._ensure_active()
        return await self.context.dispatch(event, payload)

    async def effect(
        self,
        setup: Callable[[], EffectResultV2 | Awaitable[EffectResultV2]],
        *,
        label: str,
    ) -> None:
        await self.context.effect(setup, label=label)

    async def dispose(self) -> None:
        if not self._disposal.started and self.phase is not FiberPhaseV2.PENDING:
            self.phase = FiberPhaseV2.UNLOADING
        await self._disposal.wait()

    async def _dispose(self) -> None:
        if self.phase is FiberPhaseV2.PENDING:
            self.phase = FiberPhaseV2.DISPOSED
            return
        self.phase = FiberPhaseV2.UNLOADING
        try:
            await self._effects.dispose()
        finally:
            self.phase = FiberPhaseV2.DISPOSED

    def _ensure_active(self) -> None:
        if self.phase is not FiberPhaseV2.ACTIVE:
            raise RuntimeV2Error(
                "inactive_operation",
                "inactive plugin operation cannot resolve or dispatch capabilities",
            )


class LoaderV2:
    """Stages a complete generation from a strict snapshot and trusted module catalog."""

    def __init__(
        self,
        definitions: Sequence[PluginDefinitionV2] = (),
        *,
        target: DataPlaneTargetV2 = DataPlaneTargetV2.PYTHON,
        target_catalog: Mapping[str, ModuleCatalogEntryV2] | None = None,
        artifact_resolver: PluginArtifactResolverV2 | None = None,
    ) -> None:
        self._definitions: dict[str, PluginDefinitionV2] = {}
        self._target = target
        catalog = generated_target_catalog_v2(target) if target_catalog is None else target_catalog
        self._target_catalog = MappingProxyType(dict(catalog))
        self._artifact_resolver = artifact_resolver or RepositoryPythonArtifactResolverV2()
        for definition in definitions:
            self.register_module(definition)

    def register_module(self, definition: PluginDefinitionV2) -> None:
        if definition.module_ref in self._definitions:
            raise RuntimeV2Error(
                "duplicate_module_definition",
                f"module {definition.module_ref} is already registered",
            )
        self._definitions[definition.module_ref] = definition

    def verify_archives(
        self, snapshot: ProfileSnapshotV2, archives: Sequence[VerifiedBundleArchiveV2]
    ) -> None:
        rows = tuple(row for row in _module_rows_v2(snapshot) if self._target in row[2].targets)
        _ = self._attest_artifacts(rows, snapshot=snapshot, verified_archives=archives)

    async def stage(
        self,
        snapshot: ProfileSnapshotV2,
        *,
        verified_archives: Sequence[VerifiedBundleArchiveV2] | None = None,
    ) -> RuntimeGenerationV2:
        module_rows = _module_rows_v2(snapshot)
        modules_by_key = {
            (plugin_id, module.module_ref): module for plugin_id, _version, module in module_rows
        }
        target_rows = tuple(row for row in module_rows if self._target in row[2].targets)
        resolved_artifacts = self._attest_artifacts(
            target_rows, snapshot=snapshot, verified_archives=verified_archives
        )
        enabled = {
            entry.entry_id: entry
            for entry in project_snapshot_entries_v2(snapshot, self._target)
            if entry.enabled
        }
        modules = self._entry_modules(enabled, modules_by_key)
        preflight_entries_v2(enabled, modules)
        order = entry_order_v2(enabled, modules)
        event_contracts = event_contract_catalog_v2(modules.values())
        definitions = self._load_definitions(order, modules, resolved_artifacts)
        providers = _ProviderStore()
        events = _EventBusV2()
        fibers: list[FiberV2] = []
        try:
            for entry_id in order:
                fiber = FiberV2(
                    entry=enabled[entry_id],
                    definition=definitions[entry_id],
                    contract=modules[entry_id].contract,
                    event_contracts=event_contracts,
                    providers=providers,
                    events=events,
                )
                fibers.append(fiber)
                await fiber.start()
        except BaseException as error:
            candidate = RuntimeGenerationV2(
                snapshot=snapshot,
                fibers=fibers,
                providers=providers,
                events=events,
                event_contracts=event_contracts,
            )
            try:
                await candidate.dispose()
            except BaseException as cleanup_error:
                raise BaseExceptionGroup(
                    "Generation staging and cleanup failed", [error, cleanup_error]
                ) from None
            raise
        return RuntimeGenerationV2(
            snapshot=snapshot,
            fibers=fibers,
            providers=providers,
            events=events,
            event_contracts=event_contracts,
        )

    def _attest_artifacts(
        self,
        target_rows: Sequence[_PluginModuleRowV2],
        *,
        snapshot: ProfileSnapshotV2,
        verified_archives: Sequence[VerifiedBundleArchiveV2] | None = None,
    ) -> dict[str, ResolvedPluginArtifactV2]:
        from .external_wasm_admission import admit_external_wasm_artifacts_v2

        catalog, resolved = admit_external_wasm_artifacts_v2(
            manifests=snapshot.manifests,
            entries=snapshot.entries,
            target=self._target,
            target_catalog=self._target_catalog,
            archives=verified_archives,
        )
        if set(resolved).intersection(self._definitions):
            raise RuntimeV2Error(
                "external_preloaded_definition_forbidden",
                "external WASM definitions must be loaded from verified artifact bytes",
            )
        return attest_execution_artifacts_v2(
            target_rows,
            target_catalog=catalog,
            target=self._target,
            resolver=self._artifact_resolver,
            verified_archives=verified_archives,
            resolved_overrides=resolved,
        )

    def _entry_modules(
        self,
        enabled: Mapping[str, ProfileEntryV2],
        modules_by_key: Mapping[tuple[str, str], PluginModuleV2],
    ) -> dict[str, PluginModuleV2]:
        modules: dict[str, PluginModuleV2] = {}
        for entry in enabled.values():
            module = modules_by_key[(entry.plugin_ref, entry.module_ref)]
            definition = self._definitions.get(entry.module_ref)
            if definition is not None and definition.contract_digest != module.contract_digest:
                raise RuntimeV2Error(
                    "contract_digest_mismatch",
                    f"runtime module {entry.module_ref} contract digest differs from manifest",
                )
            modules[entry.entry_id] = module
            if entry.parent_entry_id is not None and entry.parent_entry_id not in enabled:
                raise RuntimeV2Error(
                    "inactive_parent_entry",
                    f"entry {entry.entry_id} parent is disabled",
                )
        return modules

    def _load_definitions(
        self,
        order: Sequence[str],
        modules: Mapping[str, PluginModuleV2],
        resolved_artifacts: Mapping[str, ResolvedPluginArtifactV2],
    ) -> dict[str, PluginDefinitionV2]:
        loaded_definitions: dict[str, PluginDefinitionV2] = {}
        definitions: dict[str, PluginDefinitionV2] = {}
        for entry_id in order:
            module = modules[entry_id]
            definition = self._definitions.get(module.module_ref)
            if definition is None:
                definition = loaded_definitions.get(module.module_ref)
            if definition is None:
                resolved = resolved_artifacts.get(module.module_ref)
                if resolved is None:
                    raise RuntimeV2Error(
                        "missing_module_artifact",
                        f"entry {entry_id} module {module.module_ref} has no resolved artifact",
                    )
                definition = _definition_from_artifact_v2(module, resolved)
                loaded_definitions[module.module_ref] = definition
            definitions[entry_id] = definition
        return definitions


def _module_rows_v2(snapshot: ProfileSnapshotV2) -> tuple[_PluginModuleRowV2, ...]:
    rows = tuple(
        (manifest.plugin_id, manifest.version, module)
        for manifest in snapshot.manifests
        for module in manifest.modules
    )
    module_refs = [module.module_ref for _plugin_id, _version, module in rows]
    if len(module_refs) != len(set(module_refs)):
        raise RuntimeV2Error(
            "duplicate_module_ref",
            "snapshot declares a module_ref more than once",
        )
    return rows


def _definition_from_artifact_v2(
    module: PluginModuleV2,
    artifact: ResolvedPluginArtifactV2,
) -> PluginDefinitionV2:
    entrypoint = artifact.load()
    if isinstance(entrypoint, PluginDefinitionV2):
        definition = entrypoint
    elif callable(entrypoint):
        callable_entrypoint = entrypoint
        accepts_zero = _signature_accepts_v2(callable_entrypoint, ())
        accepts_apply = _signature_accepts_v2(callable_entrypoint, (object(), {}))
        if accepts_zero == accepts_apply:
            raise RuntimeV2Error(
                "ambiguous_plugin_entrypoint",
                f"module {module.module_ref} entrypoint must be an apply function or factory",
            )
        if accepts_zero:
            candidate = callable_entrypoint()
            if not isinstance(candidate, PluginDefinitionV2):
                raise RuntimeV2Error(
                    "invalid_plugin_definition",
                    f"module {module.module_ref} factory did not return PluginDefinitionV2",
                )
            definition = candidate
        else:
            definition = PluginDefinitionV2(
                module_ref=module.module_ref,
                contract_digest=module.contract_digest,
                apply=cast(PluginApplyV2, callable_entrypoint),
            )
    else:
        raise RuntimeV2Error(
            "invalid_plugin_entrypoint",
            f"module {module.module_ref} entrypoint is not callable",
        )
    if (
        definition.module_ref != module.module_ref
        or definition.contract_digest != module.contract_digest
    ):
        raise RuntimeV2Error(
            "plugin_definition_mismatch",
            f"module {module.module_ref} runtime definition differs from manifest",
        )
    return definition


def _signature_accepts_v2(
    value: Callable[..., object],
    arguments: tuple[object, ...],
) -> bool:
    try:
        _ = inspect.signature(value).bind(*arguments)
    except (TypeError, ValueError):
        return False
    return True


def project_snapshot_entries_v2(
    snapshot: ProfileSnapshotV2,
    target: DataPlaneTargetV2,
) -> tuple[ProfileEntryV2, ...]:
    """Project a fully validated snapshot onto one data plane without mutating it."""
    module_targets = {
        (manifest.plugin_id, module.module_ref): module.targets
        for manifest in snapshot.manifests
        for module in manifest.modules
    }
    return tuple(
        entry
        for entry in snapshot.entries
        if target in module_targets[(entry.plugin_ref, entry.module_ref)]
    )


class GenerationLeaseV2:
    def __init__(self, manager: GenerationManagerV2, generation: RuntimeGenerationV2) -> None:
        self._manager = manager
        self.generation = generation
        self._released = False
        self._release_task = OwnedLifecycleTaskV2(
            self._release, name="plugin-generation-lease-release-v2"
        )

    async def __aenter__(self) -> RuntimeGenerationV2:
        return self.generation

    async def __aexit__(self, *_args: object) -> None:
        await self.release()

    async def release(self) -> None:
        await self._release_task.wait()

    async def _release(self) -> None:
        self._released = True
        await self._manager._release(self.generation)


@dataclass(frozen=True, kw_only=True)
class GenerationRetirementDiagnosticV2:
    generation: RuntimeGenerationV2
    error: BaseException


class GenerationManagerV2:
    """Atomically publishes generations and drains retired generations after leases."""

    def __init__(self) -> None:
        self._current: RuntimeGenerationV2 | None = None
        self._owned_generations: set[RuntimeGenerationV2] = set()
        self._lock = asyncio.Lock()
        self._retirements: dict[RuntimeGenerationV2, OwnedLifecycleTaskV2] = {}
        self._retirement_diagnostics: list[GenerationRetirementDiagnosticV2] = []
        self._close_task: OwnedLifecycleTaskV2 | None = None

    @property
    def current(self) -> RuntimeGenerationV2 | None:
        return self._current

    @property
    def retirement_diagnostics(self) -> tuple[GenerationRetirementDiagnosticV2, ...]:
        return tuple(self._retirement_diagnostics)

    async def publish(
        self,
        generation: RuntimeGenerationV2,
        *,
        commit: Callable[[], None] | None = None,
        defer_retirement: bool = False,
    ) -> RuntimeGenerationV2 | None:
        """Publish one generation with an optional no-await companion commit."""
        retirement: OwnedLifecycleTaskV2 | None = None
        async with self._lock:
            if generation is self._current:
                return None
            if generation._disposed or generation._retired or generation._disposal.started:
                raise RuntimeV2Error(
                    "generation_not_publishable", "disposed or retired generation cannot publish"
                )
            if commit is not None:
                commit()
            previous = self._current
            self._current = generation
            self._close_task = None
            self._owned_generations.add(generation)
            if previous is not None:
                previous._retired = True
                if previous._lease_count == 0:
                    self._owned_generations.discard(previous)
                    retirement = self._retire(previous)
        # Reconciler and host bind their identities without awaiting retired effects.
        if retirement is not None and not defer_retirement:
            await retirement.wait()
        return previous

    def _retire(self, generation: RuntimeGenerationV2) -> OwnedLifecycleTaskV2:
        async def drain() -> None:
            try:
                await generation.dispose()
            except BaseException as error:
                self._retirement_diagnostics.append(
                    GenerationRetirementDiagnosticV2(generation=generation, error=error)
                )
                raise
            finally:
                self._retirements.pop(generation, None)

        task = self._retirements.get(generation)
        if task is None:
            task = OwnedLifecycleTaskV2(drain, name="plugin-retirement-v2")
            self._retirements[generation] = task
            task.start()
        return task

    async def acquire(self) -> GenerationLeaseV2:
        async with self._lock:
            generation = self._current
            if generation is None:
                raise RuntimeV2Error("generation_unavailable", "no generation is published")
            generation._lease_count += 1
        return GenerationLeaseV2(self, generation)

    async def retain(self, generation: RuntimeGenerationV2) -> GenerationLeaseV2:
        """Acquire a second lease for an exact generation that is already leased."""
        async with self._lock:
            if (
                generation not in self._owned_generations
                or generation._disposed
                or generation._lease_count <= 0
            ):
                raise RuntimeV2Error(
                    "generation_retain_unavailable",
                    "exact plugin generation can no longer be retained",
                )
            generation._lease_count += 1
        return GenerationLeaseV2(self, generation)

    async def close(self) -> None:
        if self._close_task is None:
            expected = self._current
            self._close_task = OwnedLifecycleTaskV2(
                lambda: self._close(expected), name="plugin-manager-close-v2"
            )
        await self._close_task.wait()

    async def _close(self, current: RuntimeGenerationV2 | None) -> None:
        dispose: RuntimeGenerationV2 | None = None
        async with self._lock:
            if self._current is current:
                self._current = None
            if current is not None:
                current._retired = True
                if current._lease_count == 0:
                    dispose = current
                    self._owned_generations.discard(current)
            retirements = tuple(self._retirements.values())
        for retirement in retirements:
            # Original failures remain available in retirement_diagnostics.
            with suppress(BaseException):
                await retirement.wait()
        if dispose is not None:
            await dispose.dispose()

    async def _release(self, generation: RuntimeGenerationV2) -> None:
        dispose = False
        async with self._lock:
            if generation not in self._owned_generations:
                raise RuntimeV2Error(
                    "generation_lease_not_owned",
                    "plugin generation lease does not belong to this manager",
                )
            generation._lease_count -= 1
            if generation._lease_count < 0:
                raise RuntimeV2Error("lease_underflow", "generation lease count underflow")
            dispose = generation._retired and generation._lease_count == 0
            if dispose:
                self._owned_generations.discard(generation)
        if dispose:
            await self._retire(generation).wait()


def _operation_scope_chain(scope: ScopeV2) -> tuple[ScopeV2, ...]:
    root = ScopeV2(kind=ScopeKindV2.ROOT)
    if scope.kind is ScopeKindV2.ROOT:
        return (root,)
    if scope.tenant_id is None:
        raise RuntimeV2Error("invalid_operation_scope", "tenant scope identifier is required")
    tenant = ScopeV2(kind=ScopeKindV2.TENANT, tenant_id=scope.tenant_id)
    if scope.kind is ScopeKindV2.TENANT:
        return root, tenant
    if scope.project_id is None:
        raise RuntimeV2Error("invalid_operation_scope", "project scope identifier is required")
    project = ScopeV2(
        kind=ScopeKindV2.PROJECT,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
    )
    if scope.kind is ScopeKindV2.PROJECT:
        return root, tenant, project
    if scope.session_id is None:
        raise RuntimeV2Error("invalid_operation_scope", "session scope identifier is required")
    session = ScopeV2(
        kind=ScopeKindV2.SESSION,
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        session_id=scope.session_id,
    )
    return root, tenant, project, session


class SupportsApplyV2(Protocol):
    def __call__(
        self,
        context: ContextV2,
        config: Mapping[str, Any],
    ) -> EffectResultV2 | Awaitable[EffectResultV2]: ...


__all__ = [
    "AsyncDisposerV2",
    "ContextV2",
    "EffectDiagnosticV2",
    "EffectResultV2",
    "FiberDiagnosticV2",
    "FiberPhaseV2",
    "FiberV2",
    "GenerationLeaseV2",
    "GenerationManagerV2",
    "LoaderV2",
    "OperationContextV2",
    "PluginDefinitionV2",
    "RuntimeGenerationV2",
    "RuntimeV2Error",
    "generated_contract_digest_v2",
    "project_snapshot_entries_v2",
]
