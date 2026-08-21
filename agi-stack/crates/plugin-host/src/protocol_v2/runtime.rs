//! Executor-neutral Context/Fiber/Loader/generation lifecycle for protocol v2.

use std::{
    any::Any,
    collections::BTreeMap,
    future::Future,
    pin::Pin,
    sync::{Arc, Mutex},
};

use arc_swap::ArcSwapOption;
use async_trait::async_trait;
use serde_json::Value;
use thiserror::Error;

pub use super::context::ContextV2;
use super::context::{
    event_store_v2, resolve_service, service_store_v2, EventStoreV2, ServiceStoreV2,
};
use super::contract_runtime::{
    entry_order, event_contract_catalog, parse_target_catalog, preflight_entries, same_targets,
    validate_runtime_contract,
};
use super::{
    DataPlaneTargetV2, EventContractV2, PluginContractV2, ProfileEntryV2, ProfileSnapshotV2,
    ScopeV2, PLUGIN_MODULE_CATALOG_DIGEST_V2, PLUGIN_MODULE_CATALOG_V2_JSON,
};

type BoxEffectFutureV2 = Pin<Box<dyn Future<Output = Result<(), RuntimeV2Error>> + Send + 'static>>;
pub type EffectDisposerV2 = Box<dyn FnOnce() -> BoxEffectFutureV2 + Send + 'static>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FiberPhaseV2 {
    Pending,
    Loading,
    Active,
    Unloading,
    Disposed,
    Failed,
}

#[derive(Debug, Error, Clone, Eq, PartialEq)]
pub enum RuntimeV2Error {
    #[error("inactive context cannot register an effect")]
    InactiveEffect,
    #[error("cannot start Fiber from {0:?}")]
    InvalidFiberTransition(FiberPhaseV2),
    #[error("module {0} is unavailable")]
    MissingModuleDefinition(String),
    #[error("module {0} is already registered")]
    DuplicateModuleDefinition(String),
    #[error("target module catalog is invalid: {0}")]
    InvalidTargetCatalog(String),
    #[error("target module catalog digest mismatch: expected {expected}")]
    CatalogDigestMismatch { expected: String },
    #[error("module {0} is absent from the target catalog")]
    MissingTargetCatalog(String),
    #[error("module {0} contract digest differs across manifest, catalog, and runtime")]
    ContractDigestMismatch(String),
    #[error("module {module_ref} contract schema is invalid: {detail}")]
    InvalidContractSchema { module_ref: String, detail: String },
    #[error("entry {entry_id} parent is disabled: {parent_id}")]
    InactiveParentEntry { entry_id: String, parent_id: String },
    #[error("entry {entry_id} config is invalid: {detail}")]
    InvalidModuleConfig { entry_id: String, detail: String },
    #[error("entry {entry_id} is missing required inject alias {alias}")]
    MissingRequiredInject { entry_id: String, alias: String },
    #[error("entry {entry_id} has unexpected inject alias {alias}")]
    UnexpectedInject { entry_id: String, alias: String },
    #[error("entry {entry_id} alias {alias} must inject {service}")]
    InjectServiceMismatch {
        entry_id: String,
        alias: String,
        service: String,
    },
    #[error("entry {entry_id} isolates undeclared service {service}")]
    UnexpectedIsolation { entry_id: String, service: String },
    #[error("entry {entry_id} injects missing service {service}")]
    MissingInjectProvider { entry_id: String, service: String },
    #[error("entry {entry_id} has no provider for exact service version {service}@{version}")]
    ServiceVersionMismatch {
        entry_id: String,
        service: String,
        version: String,
    },
    #[error("entry {entry_id} has ambiguous service {service}")]
    AmbiguousInjectProvider { entry_id: String, service: String },
    #[error("entry dependency cycle includes {0}")]
    EntryDependencyCycle(String),
    #[error("entries {first_entry_id} and {second_entry_id} provide {service}@{version} in the same scope and isolation")]
    ProviderConflict {
        first_entry_id: String,
        second_entry_id: String,
        service: String,
        version: String,
    },
    #[error("service {service}@{version} already has a provider in this scope and isolation")]
    ServiceConflict { service: String, version: String },
    #[error("service {0} is unavailable")]
    MissingService(String),
    #[error("service {0} has multiple nearest providers")]
    AmbiguousService(String),
    #[error("entry {entry_id} did not declare provide {service}")]
    UndeclaredProvide { entry_id: String, service: String },
    #[error("entry {entry_id} declared another version of {service}")]
    ProvideVersionMismatch { entry_id: String, service: String },
    #[error("entry {entry_id} has multiple declared versions of {service}")]
    AmbiguousProvidedContract { entry_id: String, service: String },
    #[error("entry {entry_id} did not declare require {alias}")]
    UndeclaredRequire { entry_id: String, alias: String },
    #[error("entry {entry_id} declared another version for alias {alias}")]
    RequireVersionMismatch { entry_id: String, alias: String },
    #[error("entry {entry_id} did not declare handler {event}")]
    UndeclaredEventHandler { entry_id: String, event: String },
    #[error("entry {entry_id} did not declare dispatch {event}")]
    UndeclaredEventDispatch { entry_id: String, event: String },
    #[error("event {0} has inconsistent contracts")]
    EventContractMismatch(String),
    #[error("event {event} payload is invalid: {detail}")]
    InvalidEventPayload { event: String, detail: String },
    #[error("event {event} result is invalid: {detail}")]
    InvalidEventResult { event: String, detail: String },
    #[error("service {0} has an unexpected concrete type")]
    ServiceTypeMismatch(String),
    #[error("no generation is published")]
    GenerationUnavailable,
    #[error("generation is retired")]
    GenerationRetired,
    #[error("generation is disposed")]
    GenerationDisposed,
    #[error("generation lease count underflow")]
    LeaseUnderflow,
    #[error("plugin module failed: {0}")]
    Module(String),
}

impl RuntimeV2Error {
    /// Return the stable cross-language runtime rejection code.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InactiveEffect => "inactive_effect",
            Self::InvalidFiberTransition(_) => "invalid_fiber_transition",
            Self::MissingModuleDefinition(_) => "missing_module_definition",
            Self::DuplicateModuleDefinition(_) => "duplicate_module_definition",
            Self::InvalidTargetCatalog(_) => "invalid_target_catalog",
            Self::CatalogDigestMismatch { .. } => "catalog_digest_mismatch",
            Self::MissingTargetCatalog(_) => "missing_target_catalog",
            Self::ContractDigestMismatch(_) => "contract_digest_mismatch",
            Self::InvalidContractSchema { .. } => "invalid_contract_schema",
            Self::InactiveParentEntry { .. } => "inactive_parent_entry",
            Self::InvalidModuleConfig { .. } => "invalid_module_config",
            Self::MissingRequiredInject { .. } => "missing_required_inject",
            Self::UnexpectedInject { .. } => "unexpected_inject",
            Self::InjectServiceMismatch { .. } => "inject_service_mismatch",
            Self::UnexpectedIsolation { .. } => "unexpected_isolation",
            Self::MissingInjectProvider { .. } => "missing_inject_provider",
            Self::ServiceVersionMismatch { .. } => "service_version_mismatch",
            Self::AmbiguousInjectProvider { .. } => "ambiguous_inject_provider",
            Self::EntryDependencyCycle(_) => "entry_dependency_cycle",
            Self::ProviderConflict { .. } => "provider_conflict",
            Self::ServiceConflict { .. } => "service_conflict",
            Self::MissingService(_) => "missing_service",
            Self::AmbiguousService(_) => "ambiguous_service",
            Self::UndeclaredProvide { .. } => "undeclared_provide",
            Self::ProvideVersionMismatch { .. } => "provide_version_mismatch",
            Self::AmbiguousProvidedContract { .. } => "ambiguous_provided_contract",
            Self::UndeclaredRequire { .. } => "undeclared_require",
            Self::RequireVersionMismatch { .. } => "require_version_mismatch",
            Self::UndeclaredEventHandler { .. } => "undeclared_event_handler",
            Self::UndeclaredEventDispatch { .. } => "undeclared_event_dispatch",
            Self::EventContractMismatch(_) => "event_contract_mismatch",
            Self::InvalidEventPayload { .. } => "invalid_event_payload",
            Self::InvalidEventResult { .. } => "invalid_event_result",
            Self::ServiceTypeMismatch(_) => "service_type_mismatch",
            Self::GenerationUnavailable => "generation_unavailable",
            Self::GenerationRetired => "generation_retired",
            Self::GenerationDisposed => "generation_disposed",
            Self::LeaseUnderflow => "lease_underflow",
            Self::Module(_) => "module_failed",
        }
    }
}

#[async_trait]
pub trait PluginModuleRuntimeV2: Send + Sync {
    async fn apply(
        &self,
        context: &mut ContextV2,
        config: &BTreeMap<String, Value>,
    ) -> Result<(), RuntimeV2Error>;
}

#[derive(Clone)]
pub struct PluginDefinitionV2 {
    pub module_ref: String,
    pub contract_digest: String,
    pub module: Arc<dyn PluginModuleRuntimeV2>,
}

pub struct FiberV2 {
    pub entry: ProfileEntryV2,
    pub context: ContextV2,
    definition: PluginDefinitionV2,
}

impl FiberV2 {
    fn new(
        entry: ProfileEntryV2,
        definition: PluginDefinitionV2,
        contract: Arc<PluginContractV2>,
        event_contracts: Arc<BTreeMap<String, EventContractV2>>,
        services: ServiceStoreV2,
        events: EventStoreV2,
    ) -> Self {
        let context = ContextV2::new(&entry, contract, event_contracts, services, events);
        Self {
            entry,
            context,
            definition,
        }
    }

    pub fn phase(&self) -> FiberPhaseV2 {
        self.context.phase()
    }

    pub async fn start(&mut self) -> Result<(), RuntimeV2Error> {
        if self.phase() != FiberPhaseV2::Pending {
            return Err(RuntimeV2Error::InvalidFiberTransition(self.phase()));
        }
        self.context.set_phase(FiberPhaseV2::Loading);
        let result = self
            .definition
            .module
            .apply(&mut self.context, &self.entry.config)
            .await;
        match result {
            Ok(()) => {
                self.context.set_phase(FiberPhaseV2::Active);
                Ok(())
            }
            Err(error) => {
                self.context.set_phase(FiberPhaseV2::Failed);
                self.context.dispose_registered_effects().await;
                Err(error)
            }
        }
    }

    pub async fn dispose(&mut self) {
        match self.phase() {
            FiberPhaseV2::Disposed | FiberPhaseV2::Unloading => return,
            FiberPhaseV2::Pending => {
                self.context.set_phase(FiberPhaseV2::Disposed);
                return;
            }
            _ => {}
        }
        self.context.set_phase(FiberPhaseV2::Unloading);
        self.context.dispose_registered_effects().await;
        self.context.set_phase(FiberPhaseV2::Disposed);
    }

    pub fn effect_diagnostics(&self) -> Vec<(String, Option<String>)> {
        self.context.effect_diagnostics()
    }
}

pub struct LoaderV2 {
    definitions: BTreeMap<String, PluginDefinitionV2>,
    target: DataPlaneTargetV2,
    catalog_json: String,
    expected_catalog_digest: Option<String>,
}

impl LoaderV2 {
    pub fn new(definitions: impl IntoIterator<Item = PluginDefinitionV2>) -> Self {
        Self::for_target(DataPlaneTargetV2::RustServer, definitions)
    }

    pub fn for_target(
        target: DataPlaneTargetV2,
        definitions: impl IntoIterator<Item = PluginDefinitionV2>,
    ) -> Self {
        Self {
            definitions: definitions
                .into_iter()
                .map(|item| (item.module_ref.clone(), item))
                .collect(),
            target,
            catalog_json: PLUGIN_MODULE_CATALOG_V2_JSON.to_owned(),
            expected_catalog_digest: Some(PLUGIN_MODULE_CATALOG_DIGEST_V2.to_owned()),
        }
    }

    pub fn for_target_with_catalog_json(
        target: DataPlaneTargetV2,
        definitions: impl IntoIterator<Item = PluginDefinitionV2>,
        catalog_json: impl Into<String>,
    ) -> Self {
        Self {
            definitions: definitions
                .into_iter()
                .map(|item| (item.module_ref.clone(), item))
                .collect(),
            target,
            catalog_json: catalog_json.into(),
            expected_catalog_digest: None,
        }
    }

    pub fn register_module(
        &mut self,
        definition: PluginDefinitionV2,
    ) -> Result<(), RuntimeV2Error> {
        if self.definitions.contains_key(&definition.module_ref) {
            return Err(RuntimeV2Error::DuplicateModuleDefinition(
                definition.module_ref,
            ));
        }
        self.definitions
            .insert(definition.module_ref.clone(), definition);
        Ok(())
    }

    pub async fn stage(
        &self,
        snapshot: ProfileSnapshotV2,
    ) -> Result<Arc<RuntimeGenerationV2>, RuntimeV2Error> {
        let catalog =
            parse_target_catalog(&self.catalog_json, self.expected_catalog_digest.as_deref())?;
        let mut modules_by_key = BTreeMap::new();
        for manifest in &snapshot.manifests {
            for module in &manifest.modules {
                modules_by_key.insert(
                    (manifest.plugin_id.clone(), module.module_ref.clone()),
                    module.clone(),
                );
                if !module.targets.contains(&self.target) {
                    continue;
                }
                validate_runtime_contract(
                    &module.module_ref,
                    &module.contract,
                    &module.contract_digest,
                )?;
                let catalog_module = catalog.get(&module.module_ref).ok_or_else(|| {
                    RuntimeV2Error::MissingTargetCatalog(module.module_ref.clone())
                })?;
                if !catalog_module.targets.contains(&self.target) {
                    return Err(RuntimeV2Error::MissingTargetCatalog(
                        module.module_ref.clone(),
                    ));
                }
                if catalog_module.contract_digest != module.contract_digest
                    || catalog_module.contract != module.contract
                {
                    return Err(RuntimeV2Error::ContractDigestMismatch(
                        module.module_ref.clone(),
                    ));
                }
                let metadata_matches = catalog_module.plugin_id == manifest.plugin_id
                    && catalog_module.plugin_version == manifest.version
                    && catalog_module.entrypoint == module.entrypoint
                    && catalog_module.artifact_digest == module.artifact.digest
                    && same_targets(&catalog_module.targets, &module.targets);
                if !metadata_matches {
                    return Err(RuntimeV2Error::InvalidTargetCatalog(format!(
                        "module {} metadata differs from manifest",
                        module.module_ref
                    )));
                }
            }
        }
        let entries: BTreeMap<String, ProfileEntryV2> =
            project_snapshot_entries_v2(&snapshot, &self.target)
                .into_iter()
                .filter(|entry| entry.enabled)
                .map(|entry| (entry.entry_id.clone(), entry.clone()))
                .collect();
        let mut definitions = BTreeMap::new();
        let mut modules = BTreeMap::new();
        for entry in entries.values() {
            let definition = self
                .definitions
                .get(&entry.module_ref)
                .ok_or_else(|| RuntimeV2Error::MissingModuleDefinition(entry.module_ref.clone()))?;
            let module = modules_by_key
                .get(&(entry.plugin_ref.clone(), entry.module_ref.clone()))
                .ok_or_else(|| RuntimeV2Error::MissingModuleDefinition(entry.module_ref.clone()))?;
            if definition.contract_digest != module.contract_digest {
                return Err(RuntimeV2Error::ContractDigestMismatch(
                    entry.module_ref.clone(),
                ));
            }
            if let Some(parent_id) = &entry.parent_entry_id {
                if !entries.contains_key(parent_id) {
                    return Err(RuntimeV2Error::InactiveParentEntry {
                        entry_id: entry.entry_id.clone(),
                        parent_id: parent_id.clone(),
                    });
                }
            }
            definitions.insert(entry.entry_id.clone(), definition.clone());
            modules.insert(entry.entry_id.clone(), module.clone());
        }
        preflight_entries(&entries, &modules)?;
        let order = entry_order(&entries, &modules)?;
        let event_contracts = Arc::new(event_contract_catalog(modules.values())?);
        let services = service_store_v2();
        let events = event_store_v2();
        let mut fibers: Vec<FiberV2> = Vec::with_capacity(order.len());
        for entry_id in order {
            let mut fiber = FiberV2::new(
                entries[&entry_id].clone(),
                definitions[&entry_id].clone(),
                Arc::new(modules[&entry_id].contract.clone()),
                Arc::clone(&event_contracts),
                Arc::clone(&services),
                Arc::clone(&events),
            );
            if let Err(error) = fiber.start().await {
                fiber.dispose().await;
                for active in fibers.iter_mut().rev() {
                    active.dispose().await;
                }
                return Err(error);
            }
            fibers.push(fiber);
        }
        Ok(Arc::new(RuntimeGenerationV2 {
            snapshot,
            services,
            fibers: Mutex::new(Some(fibers)),
            lifecycle: Mutex::new(GenerationLifecycleV2::default()),
        }))
    }
}

pub fn project_snapshot_entries_v2<'a>(
    snapshot: &'a ProfileSnapshotV2,
    target: &DataPlaneTargetV2,
) -> Vec<&'a ProfileEntryV2> {
    snapshot
        .entries
        .iter()
        .filter(|entry| {
            snapshot.manifests.iter().any(|manifest| {
                manifest.plugin_id == entry.plugin_ref
                    && manifest.modules.iter().any(|module| {
                        module.module_ref == entry.module_ref && module.targets.contains(target)
                    })
            })
        })
        .collect()
}

#[derive(Default)]
struct GenerationLifecycleV2 {
    leases: usize,
    retired: bool,
    disposed: bool,
}

pub struct RuntimeGenerationV2 {
    pub snapshot: ProfileSnapshotV2,
    services: ServiceStoreV2,
    fibers: Mutex<Option<Vec<FiberV2>>>,
    lifecycle: Mutex<GenerationLifecycleV2>,
}

impl RuntimeGenerationV2 {
    pub fn resolve<T>(
        &self,
        service: &str,
        scope: &ScopeV2,
        isolation: Option<&str>,
    ) -> Result<Arc<T>, RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        if lock(&self.lifecycle).disposed {
            return Err(RuntimeV2Error::GenerationDisposed);
        }
        let value = resolve_service(&lock(&self.services), service, None, scope, isolation)?;
        Arc::downcast::<T>(value)
            .map_err(|_| RuntimeV2Error::ServiceTypeMismatch(service.to_owned()))
    }

    pub fn resolve_versioned<T>(
        &self,
        service: &str,
        version: &str,
        scope: &ScopeV2,
        isolation: Option<&str>,
    ) -> Result<Arc<T>, RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        if lock(&self.lifecycle).disposed {
            return Err(RuntimeV2Error::GenerationDisposed);
        }
        let value = resolve_service(
            &lock(&self.services),
            service,
            Some(version),
            scope,
            isolation,
        )?;
        Arc::downcast::<T>(value)
            .map_err(|_| RuntimeV2Error::ServiceTypeMismatch(service.to_owned()))
    }

    pub fn phases(&self) -> Vec<FiberPhaseV2> {
        lock(&self.fibers)
            .as_ref()
            .map(|fibers| fibers.iter().map(FiberV2::phase).collect())
            .unwrap_or_default()
    }

    async fn dispose(&self) {
        let fibers = lock(&self.fibers).take();
        if let Some(mut fibers) = fibers {
            for fiber in fibers.iter_mut().rev() {
                fiber.dispose().await;
            }
        }
        lock(&self.lifecycle).disposed = true;
    }

    fn try_acquire(&self) -> bool {
        let mut lifecycle = lock(&self.lifecycle);
        if lifecycle.retired || lifecycle.disposed {
            return false;
        }
        lifecycle.leases += 1;
        true
    }

    fn retire(&self) -> bool {
        let mut lifecycle = lock(&self.lifecycle);
        lifecycle.retired = true;
        lifecycle.leases == 0 && !lifecycle.disposed
    }

    fn release(&self) -> Result<bool, RuntimeV2Error> {
        let mut lifecycle = lock(&self.lifecycle);
        lifecycle.leases = lifecycle
            .leases
            .checked_sub(1)
            .ok_or(RuntimeV2Error::LeaseUnderflow)?;
        Ok(lifecycle.retired && lifecycle.leases == 0 && !lifecycle.disposed)
    }
}

pub struct GenerationManagerV2 {
    current: ArcSwapOption<RuntimeGenerationV2>,
}

impl GenerationManagerV2 {
    pub fn new() -> Self {
        Self {
            current: ArcSwapOption::empty(),
        }
    }

    pub async fn publish(&self, generation: Arc<RuntimeGenerationV2>) {
        if let Some(previous) = self.current.swap(Some(generation)) {
            if previous.retire() {
                previous.dispose().await;
            }
        }
    }

    pub fn acquire(&self) -> Result<GenerationLeaseV2, RuntimeV2Error> {
        loop {
            let generation = self
                .current
                .load_full()
                .ok_or(RuntimeV2Error::GenerationUnavailable)?;
            if generation.try_acquire() {
                return Ok(GenerationLeaseV2 {
                    generation: Some(generation),
                });
            }
        }
    }

    pub async fn close(&self) {
        if let Some(current) = self.current.swap(None) {
            if current.retire() {
                current.dispose().await;
            }
        }
    }
}

impl Default for GenerationManagerV2 {
    fn default() -> Self {
        Self::new()
    }
}

pub struct GenerationLeaseV2 {
    generation: Option<Arc<RuntimeGenerationV2>>,
}

impl GenerationLeaseV2 {
    pub fn generation(&self) -> Result<&Arc<RuntimeGenerationV2>, RuntimeV2Error> {
        self.generation
            .as_ref()
            .ok_or(RuntimeV2Error::GenerationRetired)
    }

    pub async fn release(mut self) -> Result<(), RuntimeV2Error> {
        if let Some(generation) = self.generation.take() {
            if generation.release()? {
                generation.dispose().await;
            }
        }
        Ok(())
    }
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}
