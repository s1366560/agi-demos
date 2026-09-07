//! Contract-aware service and event context for protocol v2.

use std::{
    any::Any,
    collections::BTreeMap,
    future::Future,
    sync::{Arc, Mutex},
};

use futures::future::join_all;
use serde_json::Value;

use super::{
    runtime::{EffectDisposerV2, FiberPhaseV2, RuntimeV2Error},
    scope_contains, EventContractV2, EventModeV2, PluginContractV2, ProfileEntryV2, ScopeV2,
};

type ServiceValueV2 = Arc<dyn Any + Send + Sync>;
type ServiceInterceptorV2 =
    Arc<dyn Fn(ServiceValueV2) -> Result<ServiceValueV2, RuntimeV2Error> + Send + Sync>;
type BoxEventFutureV2 =
    std::pin::Pin<Box<dyn Future<Output = Result<Value, RuntimeV2Error>> + Send + 'static>>;
type EventHandlerV2 = Arc<dyn Fn(Value) -> BoxEventFutureV2 + Send + Sync>;

struct EffectRecordV2 {
    label: String,
    disposer: Option<EffectDisposerV2>,
    error: Option<String>,
}

#[derive(Clone)]
pub(super) struct ServiceRecordV2 {
    service: String,
    version: String,
    value: ServiceValueV2,
    scope: ScopeV2,
    isolation: Option<String>,
    owner_entry_id: String,
}

#[derive(Clone)]
pub(super) struct EventListenerRecordV2 {
    event: String,
    handler: EventHandlerV2,
    scope: ScopeV2,
    owner_entry_id: String,
}

pub(super) type ServiceStoreV2 = Arc<Mutex<Vec<ServiceRecordV2>>>;
pub(super) type EventStoreV2 = Arc<Mutex<Vec<EventListenerRecordV2>>>;

pub(super) fn service_store_v2() -> ServiceStoreV2 {
    Arc::new(Mutex::new(Vec::new()))
}

pub(super) fn event_store_v2() -> EventStoreV2 {
    Arc::new(Mutex::new(Vec::new()))
}

#[derive(Clone)]
pub struct ContextV2 {
    entry_id: String,
    scope: ScopeV2,
    contract: Arc<PluginContractV2>,
    event_contracts: Arc<BTreeMap<String, EventContractV2>>,
    inject: BTreeMap<String, String>,
    isolation: BTreeMap<String, String>,
    interceptors: BTreeMap<String, Vec<ServiceInterceptorV2>>,
    phase: Arc<Mutex<FiberPhaseV2>>,
    effects: Arc<Mutex<Vec<EffectRecordV2>>>,
    services: ServiceStoreV2,
    events: EventStoreV2,
}

impl ContextV2 {
    pub(super) fn new(
        entry: &ProfileEntryV2,
        contract: Arc<PluginContractV2>,
        event_contracts: Arc<BTreeMap<String, EventContractV2>>,
        services: ServiceStoreV2,
        events: EventStoreV2,
    ) -> Self {
        Self {
            entry_id: entry.entry_id.clone(),
            scope: entry.scope.clone(),
            contract,
            event_contracts,
            inject: entry.inject.clone(),
            isolation: entry.isolate.clone(),
            interceptors: BTreeMap::new(),
            phase: Arc::new(Mutex::new(FiberPhaseV2::Pending)),
            effects: Arc::new(Mutex::new(Vec::new())),
            services,
            events,
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

    pub(super) fn set_phase(&self, phase: FiberPhaseV2) {
        *lock(&self.phase) = phase;
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
            contract: Arc::clone(&self.contract),
            event_contracts: Arc::clone(&self.event_contracts),
            inject,
            isolation: self.isolation.clone(),
            interceptors: self.interceptors.clone(),
            phase: Arc::clone(&self.phase),
            effects: Arc::clone(&self.effects),
            services: Arc::clone(&self.services),
            events: Arc::clone(&self.events),
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
        let service = service.into();
        let provisions: Vec<_> = self
            .contract
            .services
            .provides
            .iter()
            .filter(|item| item.service == service)
            .collect();
        let provision = match provisions.as_slice() {
            [] => {
                return Err(RuntimeV2Error::UndeclaredProvide {
                    entry_id: self.entry_id.clone(),
                    service,
                });
            }
            [provision] => *provision,
            _ => {
                return Err(RuntimeV2Error::AmbiguousProvidedContract {
                    entry_id: self.entry_id.clone(),
                    service,
                });
            }
        };
        self.provide_declared(service, provision.version.clone(), value)
    }

    pub fn provide_versioned<T>(
        &self,
        service: impl Into<String>,
        version: &str,
        value: T,
    ) -> Result<(), RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        let service = service.into();
        if !self
            .contract
            .services
            .provides
            .iter()
            .any(|item| item.service == service && item.version == version)
        {
            if self
                .contract
                .services
                .provides
                .iter()
                .any(|item| item.service == service)
            {
                return Err(RuntimeV2Error::ProvideVersionMismatch {
                    entry_id: self.entry_id.clone(),
                    service,
                });
            }
            return Err(RuntimeV2Error::UndeclaredProvide {
                entry_id: self.entry_id.clone(),
                service,
            });
        }
        self.provide_declared(service, version.to_owned(), value)
    }

    fn provide_declared<T>(
        &self,
        service: String,
        version: String,
        value: T,
    ) -> Result<(), RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        self.ensure_active()?;
        let record = ServiceRecordV2 {
            isolation: self.isolation.get(&service).cloned(),
            owner_entry_id: self.entry_id.clone(),
            scope: self.scope.clone(),
            service: service.clone(),
            version: version.clone(),
            value: Arc::new(value),
        };
        {
            let mut services = lock(&self.services);
            if services.iter().any(|item| {
                item.service == record.service
                    && item.version == record.version
                    && item.scope == record.scope
                    && item.isolation == record.isolation
            }) {
                return Err(RuntimeV2Error::ServiceConflict { service, version });
            }
            services.push(record.clone());
        }
        let services = Arc::clone(&self.services);
        let owner = record.owner_entry_id.clone();
        let key = record.service.clone();
        let provided_version = record.version.clone();
        let scope = record.scope.clone();
        let isolation = record.isolation.clone();
        self.effect(
            format!("provide:{service}"),
            Box::new(move || {
                Box::pin(async move {
                    lock(&services).retain(|item| {
                        !(item.owner_entry_id == owner
                            && item.service == key
                            && item.version == provided_version
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
        self.require_declared(alias, None)
    }

    pub fn require_versioned<T>(&self, alias: &str, version: &str) -> Result<Arc<T>, RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        self.require_declared(alias, Some(version))
    }

    fn require_declared<T>(
        &self,
        alias: &str,
        requested_version: Option<&str>,
    ) -> Result<Arc<T>, RuntimeV2Error>
    where
        T: Any + Send + Sync + 'static,
    {
        let requirement = self
            .contract
            .services
            .requires
            .iter()
            .find(|item| item.alias == alias)
            .ok_or_else(|| RuntimeV2Error::UndeclaredRequire {
                entry_id: self.entry_id.clone(),
                alias: alias.to_owned(),
            })?;
        if requested_version.is_some_and(|version| version != requirement.version) {
            return Err(RuntimeV2Error::RequireVersionMismatch {
                entry_id: self.entry_id.clone(),
                alias: alias.to_owned(),
            });
        }
        let service = self.inject.get(alias).cloned().ok_or_else(|| {
            RuntimeV2Error::MissingRequiredInject {
                entry_id: self.entry_id.clone(),
                alias: alias.to_owned(),
            }
        })?;
        if service != requirement.service {
            return Err(RuntimeV2Error::InjectServiceMismatch {
                entry_id: self.entry_id.clone(),
                alias: alias.to_owned(),
                service: requirement.service.clone(),
            });
        }
        let mut value = resolve_service(
            &lock(&self.services),
            &service,
            Some(&requirement.version),
            &self.scope,
            self.isolation.get(&service).map(String::as_str),
        )?;
        for interceptor in self.interceptors.get(&service).into_iter().flatten() {
            value = interceptor(value)?;
        }
        Arc::downcast::<T>(value).map_err(|_| RuntimeV2Error::ServiceTypeMismatch(service))
    }

    pub fn on<F, Fut>(&self, event: &str, handler: F) -> Result<(), RuntimeV2Error>
    where
        F: Fn(Value) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<Value, RuntimeV2Error>> + Send + 'static,
    {
        self.ensure_active()?;
        let declared = self
            .contract
            .events
            .handles
            .iter()
            .find(|item| item.event == event)
            .ok_or_else(|| RuntimeV2Error::UndeclaredEventHandler {
                entry_id: self.entry_id.clone(),
                event: event.to_owned(),
            })?;
        self.ensure_canonical_event(declared)?;
        let handler: EventHandlerV2 = Arc::new(move |payload| Box::pin(handler(payload)));
        lock(&self.events).push(EventListenerRecordV2 {
            event: event.to_owned(),
            handler: Arc::clone(&handler),
            scope: self.scope.clone(),
            owner_entry_id: self.entry_id.clone(),
        });
        let events = Arc::clone(&self.events);
        let owner = self.entry_id.clone();
        let event_name = event.to_owned();
        self.effect(
            format!("event:{event}"),
            Box::new(move || {
                Box::pin(async move {
                    lock(&events).retain(|item| {
                        !(item.owner_entry_id == owner
                            && item.event == event_name
                            && Arc::ptr_eq(&item.handler, &handler))
                    });
                    Ok(())
                })
            }),
        )
    }

    pub async fn dispatch(&self, event: &str, payload: Value) -> Result<Value, RuntimeV2Error> {
        let declaration = self
            .contract
            .events
            .emits
            .iter()
            .find(|item| item.event == event)
            .ok_or_else(|| RuntimeV2Error::UndeclaredEventDispatch {
                entry_id: self.entry_id.clone(),
                event: event.to_owned(),
            })?;
        self.ensure_canonical_event(declaration)?;
        validate_event_value(
            &declaration.payload_schema,
            &payload,
            event,
            EventValueKindV2::Payload,
        )?;
        let handlers: Vec<EventHandlerV2> = lock(&self.events)
            .iter()
            .filter(|item| item.event == event && scope_contains(&item.scope, &self.scope))
            .map(|item| Arc::clone(&item.handler))
            .collect();

        match declaration.mode {
            EventModeV2::Emit => {
                let results =
                    join_all(handlers.iter().map(|handler| handler(payload.clone()))).await;
                let mut values = Vec::with_capacity(results.len());
                for result in results {
                    let value = result?;
                    validate_event_value(
                        &declaration.result_schema,
                        &value,
                        event,
                        EventValueKindV2::Result,
                    )?;
                    values.push(value);
                }
                Ok(Value::Array(values))
            }
            EventModeV2::Serial => {
                let mut values = Vec::with_capacity(handlers.len());
                for handler in handlers {
                    let value = handler(payload.clone()).await?;
                    validate_event_value(
                        &declaration.result_schema,
                        &value,
                        event,
                        EventValueKindV2::Result,
                    )?;
                    values.push(value);
                }
                Ok(Value::Array(values))
            }
            EventModeV2::Bail => {
                let mut result = Value::Null;
                for handler in handlers {
                    result = handler(payload.clone()).await?;
                    if !result.is_null() {
                        break;
                    }
                }
                validate_event_value(
                    &declaration.result_schema,
                    &result,
                    event,
                    EventValueKindV2::Result,
                )?;
                Ok(result)
            }
            EventModeV2::Waterfall => {
                let mut result = payload;
                for handler in handlers {
                    result = handler(result).await?;
                    validate_event_value(
                        &declaration.result_schema,
                        &result,
                        event,
                        EventValueKindV2::Result,
                    )?;
                    validate_event_value(
                        &declaration.payload_schema,
                        &result,
                        event,
                        EventValueKindV2::Payload,
                    )?;
                }
                validate_event_value(
                    &declaration.result_schema,
                    &result,
                    event,
                    EventValueKindV2::Result,
                )?;
                Ok(result)
            }
        }
    }

    fn ensure_canonical_event(&self, declaration: &EventContractV2) -> Result<(), RuntimeV2Error> {
        if self.event_contracts.get(&declaration.event) == Some(declaration) {
            Ok(())
        } else {
            Err(RuntimeV2Error::EventContractMismatch(
                declaration.event.clone(),
            ))
        }
    }

    fn ensure_active(&self) -> Result<(), RuntimeV2Error> {
        match self.phase() {
            FiberPhaseV2::Loading | FiberPhaseV2::Active => Ok(()),
            _ => Err(RuntimeV2Error::InactiveEffect),
        }
    }

    pub(super) async fn dispose_registered_effects(&self) {
        let mut records = std::mem::take(&mut *lock(&self.effects));
        for record in records.iter_mut().rev() {
            if let Some(disposer) = record.disposer.take() {
                if let Err(error) = disposer().await {
                    record.error = Some(error.to_string());
                }
            }
        }
        *lock(&self.effects) = records;
    }

    pub(super) fn effect_diagnostics(&self) -> Vec<(String, Option<String>)> {
        lock(&self.effects)
            .iter()
            .map(|item| (item.label.clone(), item.error.clone()))
            .collect()
    }
}

pub(super) fn resolve_service(
    records: &[ServiceRecordV2],
    service: &str,
    version: Option<&str>,
    scope: &ScopeV2,
    isolation: Option<&str>,
) -> Result<ServiceValueV2, RuntimeV2Error> {
    let mut candidates: Vec<_> = records
        .iter()
        .filter(|item| {
            item.service == service
                && version.is_none_or(|version| item.version == version)
                && item.isolation.as_deref() == isolation
                && scope_contains(&item.scope, scope)
        })
        .collect();
    candidates.sort_by_key(|item| std::cmp::Reverse(super::scope_rank(&item.scope)));
    let Some(first) = candidates.first() else {
        return Err(RuntimeV2Error::MissingService(service.to_owned()));
    };
    let rank = super::scope_rank(&first.scope);
    if candidates
        .iter()
        .filter(|item| super::scope_rank(&item.scope) == rank)
        .count()
        > 1
    {
        return Err(RuntimeV2Error::AmbiguousService(service.to_owned()));
    }
    Ok(Arc::clone(&first.value))
}

#[derive(Clone, Copy)]
enum EventValueKindV2 {
    Payload,
    Result,
}

fn validate_event_value(
    schema: &BTreeMap<String, Value>,
    value: &Value,
    event: &str,
    kind: EventValueKindV2,
) -> Result<(), RuntimeV2Error> {
    let schema =
        serde_json::to_value(schema).map_err(|error| event_value_error(kind, event, error))?;
    let validator = jsonschema::draft202012::new(&schema)
        .map_err(|error| event_value_error(kind, event, error))?;
    validator
        .validate(value)
        .map_err(|error| event_value_error(kind, event, error))
}

fn event_value_error(
    kind: EventValueKindV2,
    event: &str,
    error: impl std::fmt::Display,
) -> RuntimeV2Error {
    match kind {
        EventValueKindV2::Payload => RuntimeV2Error::InvalidEventPayload {
            event: event.to_owned(),
            detail: error.to_string(),
        },
        EventValueKindV2::Result => RuntimeV2Error::InvalidEventResult {
            event: event.to_owned(),
            detail: error.to_string(),
        },
    }
}

fn lock<T>(mutex: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}
