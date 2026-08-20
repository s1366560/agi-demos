//! Executor-neutral Context/Fiber/Loader/generation lifecycle for protocol v2.

use std::{
    any::Any,
    collections::{BTreeMap, BTreeSet},
    future::Future,
    pin::Pin,
    sync::{Arc, Mutex},
};

use arc_swap::ArcSwapOption;
use async_trait::async_trait;
use serde_json::Value;
use thiserror::Error;

use super::{
    scope_contains, scope_rank, DataPlaneTargetV2, ProfileEntryV2, ProfileSnapshotV2, ScopeV2,
};

type BoxEffectFutureV2 = Pin<Box<dyn Future<Output = Result<(), RuntimeV2Error>> + Send + 'static>>;
pub type EffectDisposerV2 = Box<dyn FnOnce() -> BoxEffectFutureV2 + Send + 'static>;
type ServiceValueV2 = Arc<dyn Any + Send + Sync>;
type ServiceInterceptorV2 =
    Arc<dyn Fn(ServiceValueV2) -> Result<ServiceValueV2, RuntimeV2Error> + Send + Sync>;

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
    #[error("entry {entry_id} parent is disabled: {parent_id}")]
    InactiveParentEntry { entry_id: String, parent_id: String },
    #[error("entry {entry_id} injects missing service {service}")]
    MissingInjectProvider { entry_id: String, service: String },
    #[error("entry {entry_id} has ambiguous service {service}")]
    AmbiguousInjectProvider { entry_id: String, service: String },
    #[error("entry dependency cycle includes {0}")]
    EntryDependencyCycle(String),
    #[error("service {0} already has a provider in this scope and isolation")]
    ServiceConflict(String),
    #[error("service {0} is unavailable")]
    MissingService(String),
    #[error("service {0} has multiple nearest providers")]
    AmbiguousService(String),
    #[error("entry {entry_id} did not inject {alias}")]
    UndeclaredInject { entry_id: String, alias: String },
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

struct EffectRecordV2 {
    label: String,
    disposer: Option<EffectDisposerV2>,
    error: Option<String>,
}

#[derive(Clone)]
struct ServiceRecordV2 {
    service: String,
    value: ServiceValueV2,
    scope: ScopeV2,
    isolation: Option<String>,
    owner_entry_id: String,
}

#[derive(Clone)]
pub struct ContextV2 {
    entry_id: String,
    scope: ScopeV2,
    inject: BTreeMap<String, String>,
    isolation: BTreeMap<String, String>,
    interceptors: BTreeMap<String, Vec<ServiceInterceptorV2>>,
    privileged: bool,
    phase: Arc<Mutex<FiberPhaseV2>>,
    effects: Arc<Mutex<Vec<EffectRecordV2>>>,
    services: Arc<Mutex<Vec<ServiceRecordV2>>>,
}

impl ContextV2 {
    fn new(entry: &ProfileEntryV2, services: Arc<Mutex<Vec<ServiceRecordV2>>>) -> Self {
        Self {
            entry_id: entry.entry_id.clone(),
            scope: entry.scope.clone(),
            inject: entry.inject.clone(),
            isolation: entry.isolate.clone(),
            interceptors: BTreeMap::new(),
            privileged: false,
            phase: Arc::new(Mutex::new(FiberPhaseV2::Pending)),
            effects: Arc::new(Mutex::new(Vec::new())),
            services,
        }
    }

    pub fn entry_id(&self) -> &str {
        &self.entry_id
    }

    pub fn scope(&self) -> &ScopeV2 {
        &self.scope
    }

    pub fn phase(&self) -> FiberPhaseV2 {
        *lock(&self.phase)
    }

    pub fn extend(
        &self,
        entry_id: impl Into<String>,
        scope: ScopeV2,
        inject: BTreeMap<String, String>,
    ) -> Self {
        Self {
            entry_id: entry_id.into(),
            scope,
            inject,
            isolation: self.isolation.clone(),
            interceptors: self.interceptors.clone(),
            privileged: self.privileged,
            phase: Arc::clone(&self.phase),
            effects: Arc::clone(&self.effects),
            services: Arc::clone(&self.services),
        }
    }

    pub fn isolate(&self, service: impl Into<String>, label: impl Into<String>) -> Self {
        let mut context = self.clone();
        context.isolation.insert(service.into(), label.into());
        context
    }

    pub fn intercept<T, F>(&self, service: impl Into<String>, interceptor: F) -> Self
    where
        T: Any + Send + Sync + 'static,
        F: Fn(Arc<T>) -> Arc<T> + Send + Sync + 'static,
    {
        let service = service.into();
        let adapter: ServiceInterceptorV2 = Arc::new(move |value| {
            let typed = Arc::downcast::<T>(value)
                .map_err(|_| RuntimeV2Error::ServiceTypeMismatch("interceptor".into()))?;
            Ok(interceptor(typed))
        });
        let mut context = self.clone();
        context
            .interceptors
            .entry(service)
            .or_default()
            .push(adapter);
        context
    }

    pub fn effect(
        &self,
        label: impl Into<String>,
        disposer: EffectDisposerV2,
    ) -> Result<(), RuntimeV2Error> {
        self.ensure_active()?;
        lock(&self.effects).push(EffectRecordV2 {
            label: label.into(),
            disposer: Some(disposer),
            error: None,
        });
        Ok(())
    }

    pub fn provide<T>(&self, service: impl Into<String>, value: T) -> Result<(), RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        self.ensure_active()?;
        let service = service.into();
        let record = ServiceRecordV2 {
            isolation: self.isolation.get(&service).cloned(),
            owner_entry_id: self.entry_id.clone(),
            scope: self.scope.clone(),
            service: service.clone(),
            value: Arc::new(value),
        };
        {
            let mut services = lock(&self.services);
            if services.iter().any(|item| {
                item.service == record.service
                    && item.scope == record.scope
                    && item.isolation == record.isolation
            }) {
                return Err(RuntimeV2Error::ServiceConflict(service));
            }
            services.push(record.clone());
        }
        let services = Arc::clone(&self.services);
        let owner = record.owner_entry_id.clone();
        let key = record.service.clone();
        let scope = record.scope.clone();
        let isolation = record.isolation.clone();
        self.effect(
            format!("provide:{service}"),
            Box::new(move || {
                Box::pin(async move {
                    lock(&services).retain(|item| {
                        !(item.owner_entry_id == owner
                            && item.service == key
                            && item.scope == scope
                            && item.isolation == isolation)
                    });
                    Ok(())
                })
            }),
        )
    }

    pub fn require<T>(&self, alias: &str) -> Result<Arc<T>, RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        let service = if self.privileged {
            self.inject
                .get(alias)
                .cloned()
                .unwrap_or_else(|| alias.to_owned())
        } else {
            self.inject
                .get(alias)
                .cloned()
                .ok_or_else(|| RuntimeV2Error::UndeclaredInject {
                    entry_id: self.entry_id.clone(),
                    alias: alias.to_owned(),
                })?
        };
        let mut value = resolve_service(
            &lock(&self.services),
            &service,
            &self.scope,
            self.isolation.get(&service).map(String::as_str),
        )?;
        for interceptor in self.interceptors.get(&service).into_iter().flatten() {
            value = interceptor(value)?;
        }
        Arc::downcast::<T>(value).map_err(|_| RuntimeV2Error::ServiceTypeMismatch(service))
    }

    fn ensure_active(&self) -> Result<(), RuntimeV2Error> {
        match self.phase() {
            FiberPhaseV2::Loading | FiberPhaseV2::Active => Ok(()),
            _ => Err(RuntimeV2Error::InactiveEffect),
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
    pub provides: Vec<String>,
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
        services: Arc<Mutex<Vec<ServiceRecordV2>>>,
    ) -> Self {
        let context = ContextV2::new(&entry, services);
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
        *lock(&self.context.phase) = FiberPhaseV2::Loading;
        let result = self
            .definition
            .module
            .apply(&mut self.context, &self.entry.config)
            .await;
        match result {
            Ok(()) => {
                *lock(&self.context.phase) = FiberPhaseV2::Active;
                Ok(())
            }
            Err(error) => {
                *lock(&self.context.phase) = FiberPhaseV2::Failed;
                dispose_effects(&self.context.effects).await;
                Err(error)
            }
        }
    }

    pub async fn dispose(&mut self) {
        match self.phase() {
            FiberPhaseV2::Disposed | FiberPhaseV2::Unloading => return,
            FiberPhaseV2::Pending => {
                *lock(&self.context.phase) = FiberPhaseV2::Disposed;
                return;
            }
            _ => {}
        }
        *lock(&self.context.phase) = FiberPhaseV2::Unloading;
        dispose_effects(&self.context.effects).await;
        *lock(&self.context.phase) = FiberPhaseV2::Disposed;
    }

    pub fn effect_diagnostics(&self) -> Vec<(String, Option<String>)> {
        lock(&self.context.effects)
            .iter()
            .map(|item| (item.label.clone(), item.error.clone()))
            .collect()
    }
}

pub struct LoaderV2 {
    definitions: BTreeMap<String, PluginDefinitionV2>,
    target: DataPlaneTargetV2,
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
        let entries: BTreeMap<String, ProfileEntryV2> =
            project_snapshot_entries_v2(&snapshot, &self.target)
                .into_iter()
                .filter(|entry| entry.enabled)
                .map(|entry| (entry.entry_id.clone(), entry.clone()))
                .collect();
        let mut definitions = BTreeMap::new();
        for entry in entries.values() {
            let definition = self
                .definitions
                .get(&entry.module_ref)
                .ok_or_else(|| RuntimeV2Error::MissingModuleDefinition(entry.module_ref.clone()))?;
            if let Some(parent_id) = &entry.parent_entry_id {
                if !entries.contains_key(parent_id) {
                    return Err(RuntimeV2Error::InactiveParentEntry {
                        entry_id: entry.entry_id.clone(),
                        parent_id: parent_id.clone(),
                    });
                }
            }
            definitions.insert(entry.entry_id.clone(), definition.clone());
        }
        let order = entry_order(&entries, &definitions)?;
        let services = Arc::new(Mutex::new(Vec::new()));
        let mut fibers: Vec<FiberV2> = Vec::with_capacity(order.len());
        for entry_id in order {
            let mut fiber = FiberV2::new(
                entries[&entry_id].clone(),
                definitions[&entry_id].clone(),
                Arc::clone(&services),
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
    services: Arc<Mutex<Vec<ServiceRecordV2>>>,
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
        let value = resolve_service(&lock(&self.services), service, scope, isolation)?;
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

async fn dispose_effects(effects: &Arc<Mutex<Vec<EffectRecordV2>>>) {
    let mut records = std::mem::take(&mut *lock(effects));
    for record in records.iter_mut().rev() {
        if let Some(disposer) = record.disposer.take() {
            if let Err(error) = disposer().await {
                record.error = Some(error.to_string());
            }
        }
    }
    *lock(effects) = records;
}

fn resolve_service(
    records: &[ServiceRecordV2],
    service: &str,
    scope: &ScopeV2,
    isolation: Option<&str>,
) -> Result<ServiceValueV2, RuntimeV2Error> {
    let mut candidates: Vec<_> = records
        .iter()
        .filter(|item| {
            item.service == service
                && item.isolation.as_deref() == isolation
                && scope_contains(&item.scope, scope)
        })
        .collect();
    candidates.sort_by_key(|item| std::cmp::Reverse(scope_rank(&item.scope)));
    let Some(first) = candidates.first() else {
        return Err(RuntimeV2Error::MissingService(service.to_owned()));
    };
    let rank = scope_rank(&first.scope);
    if candidates
        .iter()
        .filter(|item| scope_rank(&item.scope) == rank)
        .count()
        > 1
    {
        return Err(RuntimeV2Error::AmbiguousService(service.to_owned()));
    }
    Ok(Arc::clone(&first.value))
}

fn entry_order(
    entries: &BTreeMap<String, ProfileEntryV2>,
    definitions: &BTreeMap<String, PluginDefinitionV2>,
) -> Result<Vec<String>, RuntimeV2Error> {
    let mut dependencies: BTreeMap<String, BTreeSet<String>> = entries
        .keys()
        .map(|entry_id| (entry_id.clone(), BTreeSet::new()))
        .collect();
    for (entry_id, entry) in entries {
        if let Some(parent_id) = &entry.parent_entry_id {
            dependencies
                .get_mut(entry_id)
                .ok_or_else(|| RuntimeV2Error::EntryDependencyCycle(entry_id.clone()))?
                .insert(parent_id.clone());
        }
        for service in entry.inject.values() {
            let mut providers: Vec<_> = definitions
                .iter()
                .filter(|(provider_id, definition)| {
                    definition.provides.contains(service)
                        && scope_contains(&entries[*provider_id].scope, &entry.scope)
                        && entries[*provider_id].isolate.get(service) == entry.isolate.get(service)
                })
                .map(|(provider_id, _)| provider_id.clone())
                .collect();
            providers.sort_by_key(|provider_id| {
                std::cmp::Reverse(scope_rank(&entries[provider_id].scope))
            });
            let Some(first) = providers.first() else {
                return Err(RuntimeV2Error::MissingInjectProvider {
                    entry_id: entry_id.clone(),
                    service: service.clone(),
                });
            };
            let rank = scope_rank(&entries[first].scope);
            let nearest: Vec<_> = providers
                .iter()
                .filter(|provider_id| scope_rank(&entries[*provider_id].scope) == rank)
                .collect();
            if nearest.len() != 1 {
                return Err(RuntimeV2Error::AmbiguousInjectProvider {
                    entry_id: entry_id.clone(),
                    service: service.clone(),
                });
            }
            if first != entry_id {
                dependencies
                    .get_mut(entry_id)
                    .ok_or_else(|| RuntimeV2Error::EntryDependencyCycle(entry_id.clone()))?
                    .insert(first.clone());
            }
        }
    }

    fn visit(
        entry_id: &str,
        dependencies: &BTreeMap<String, BTreeSet<String>>,
        visiting: &mut BTreeSet<String>,
        visited: &mut BTreeSet<String>,
        ordered: &mut Vec<String>,
    ) -> Result<(), RuntimeV2Error> {
        if visited.contains(entry_id) {
            return Ok(());
        }
        if !visiting.insert(entry_id.to_owned()) {
            return Err(RuntimeV2Error::EntryDependencyCycle(entry_id.to_owned()));
        }
        for dependency in &dependencies[entry_id] {
            visit(dependency, dependencies, visiting, visited, ordered)?;
        }
        visiting.remove(entry_id);
        visited.insert(entry_id.to_owned());
        ordered.push(entry_id.to_owned());
        Ok(())
    }

    let mut ordered = Vec::new();
    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    for entry_id in entries.keys() {
        visit(
            entry_id,
            &dependencies,
            &mut visiting,
            &mut visited,
            &mut ordered,
        )?;
    }
    Ok(ordered)
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}
