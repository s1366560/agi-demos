use super::{provider::Provider, transport::Connection, validate_configs, CdpEndpointConfig};
use agistack_adapters_browser::protocol::BridgeNotification;
use serde_json::{json, Value};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::Duration;
use tokio::sync::{broadcast, watch};
use tokio::task::JoinHandle;
use uuid::Uuid;

struct Slot {
    config: CdpEndpointConfig,
    current: Mutex<Option<Arc<Provider>>>,
    status: Mutex<&'static str>,
    error: Mutex<Option<String>>,
}

pub(crate) struct CdpRegistry {
    slots: Vec<Arc<Slot>>,
    stopped: AtomicBool,
    shutdown: watch::Sender<bool>,
    tasks: Mutex<Vec<JoinHandle<()>>>,
    notifications: broadcast::Sender<BridgeNotification>,
}

impl CdpRegistry {
    pub(crate) fn start(
        configs: &[CdpEndpointConfig],
        notifications: broadcast::Sender<BridgeNotification>,
    ) -> Result<Arc<Self>, String> {
        validate_configs(configs)?;
        let (shutdown, _) = watch::channel(false);
        let registry = Arc::new(Self {
            slots: configs
                .iter()
                .cloned()
                .map(|config| {
                    Arc::new(Slot {
                        config,
                        current: Mutex::new(None),
                        status: Mutex::new("disabled"),
                        error: Mutex::new(None),
                    })
                })
                .collect(),
            stopped: AtomicBool::new(false),
            shutdown,
            tasks: Mutex::new(Vec::new()),
            notifications,
        });
        for slot in registry.slots.iter().filter(|slot| slot.config.enabled) {
            let slot = slot.clone();
            let shutdown = registry.shutdown.subscribe();
            let notifications = registry.notifications.clone();
            registry
                .tasks
                .lock()
                .expect("cdp registry tasks")
                .push(tokio::spawn(run(slot, shutdown, notifications)));
        }
        Ok(registry)
    }
    pub(crate) fn inventory(&self) -> Vec<Value> {
        if self.stopped.load(Ordering::SeqCst) {
            return vec![];
        }
        self.slots.iter().filter_map(|slot| {
            let provider = slot.current.lock().expect("cdp provider").clone()?;
            if provider.connection.is_closed() { return None; }
            Some(json!({"id":provider.identity,"type":"cdp","family":"cdp","backend":"cdp","metadata":{
                "providerId":slot.config.id,"stableId":format!("cdp:{}",slot.config.id),"name":slot.config.name,
                "connectionGeneration":provider.identity.rsplit(':').next()
            }}))
        }).collect()
    }
    pub(crate) fn statuses(&self) -> Vec<Value> {
        self.slots.iter().map(|slot| json!({"id":slot.config.id,"name":slot.config.name,"status":*slot.status.lock().expect("cdp status"),"error":*slot.error.lock().expect("cdp status error")})).collect()
    }
    fn provider(&self, selector: &str) -> Result<Arc<Provider>, String> {
        if self.stopped.load(Ordering::SeqCst) {
            return Err("cdp_registry_stopped".into());
        }
        let mut matches = self.slots.iter().filter_map(|slot| {
            let provider = slot.current.lock().expect("cdp provider").clone()?;
            (!provider.connection.is_closed()
                && (selector == "cdp"
                    || selector == provider.identity
                    || selector == format!("cdp:{}", slot.config.id)))
            .then_some(provider)
        });
        let provider = matches
            .next()
            .ok_or("browser_instance_expired: select a live CDP browser instance")?;
        if matches.next().is_some() {
            return Err("browser_instance_ambiguous: select an exact CDP provider".into());
        }
        Ok(provider)
    }
    pub(crate) fn resolve(&self, selector: &str) -> Result<String, String> {
        self.provider(selector)
            .map(|provider| provider.identity.clone())
    }
    pub(crate) async fn request(
        &self,
        selector: &str,
        method: &str,
        params: Value,
    ) -> Result<Value, String> {
        self.provider(selector)?.request(method, params).await
    }
    pub(crate) fn stop(&self) {
        if self.stopped.swap(true, Ordering::SeqCst) {
            return;
        }
        let _ = self.shutdown.send(true);
        for slot in &self.slots {
            if let Some(provider) = slot.current.lock().expect("cdp provider").take() {
                provider.connection.close();
                disconnected(&self.notifications, &provider.identity);
            }
            *slot.status.lock().expect("cdp status") = "disabled";
        }
        for task in self.tasks.lock().expect("cdp registry tasks").drain(..) {
            task.abort();
        }
    }
}
impl Drop for CdpRegistry {
    fn drop(&mut self) {
        self.stop();
    }
}

fn disconnected(notifications: &broadcast::Sender<BridgeNotification>, identity: &str) {
    let _ = notifications.send(BridgeNotification {
        method: "onBrowserDisconnected".into(),
        params: json!({"backend":identity}),
    });
}

async fn run(
    slot: Arc<Slot>,
    mut shutdown: watch::Receiver<bool>,
    notifications: broadcast::Sender<BridgeNotification>,
) {
    let mut failures: usize = 0;
    loop {
        *slot.status.lock().expect("cdp status") = "connecting";
        let attempt = async {
            let connection = Connection::connect(&slot.config.endpoint).await?;
            let events = connection.events();
            let id = Uuid::parse_str(&slot.config.id).map_err(|_| "cdp_provider_id_invalid")?;
            let provider = Provider::new(
                format!("cdp:{}:{}", id.simple(), Uuid::new_v4().simple()),
                connection,
                notifications.clone(),
            );
            provider.initialize().await?;
            *slot.current.lock().expect("cdp provider") = Some(provider.clone());
            *slot.status.lock().expect("cdp status") = "connected";
            *slot.error.lock().expect("cdp status error") = None;
            provider.run(events).await;
            provider.connection.close();
            slot.current.lock().expect("cdp provider").take();
            disconnected(&notifications, &provider.identity);
            Err::<(), String>("cdp_connection_closed".into())
        };
        let error = tokio::select! {
            _ = shutdown.changed() => break,
            result = attempt => result.err(),
        };
        *slot.error.lock().expect("cdp status error") = error;
        *slot.status.lock().expect("cdp status") = "disconnected";
        let delay = [250, 1000, 4000, 10000][failures.min(3)];
        failures = failures.saturating_add(1);
        tokio::select! {
            _ = shutdown.changed() => break,
            _ = tokio::time::sleep(Duration::from_millis(delay)) => {},
        }
    }
}
