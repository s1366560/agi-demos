//! Instance selection stays structural: family, profile, worker and connection.
use super::{
    BrokerHelloIdentity, BrokerSession, BrowserBridgeServer, BACKEND_CHROME_EXTENSION,
    BACKEND_EDGE_EXTENSION, BACKEND_IAB,
};
use agistack_core::ports::{CoreError, CoreResult};
use serde_json::{json, Value};
use std::sync::{atomic::Ordering, Arc};
use uuid::Uuid;

fn family(backend: &str) -> &str {
    match backend {
        BACKEND_CHROME_EXTENSION => "chrome",
        BACKEND_EDGE_EXTENSION => "edge",
        _ => "iab",
    }
}

pub(super) fn browser_id(hello: &BrokerHelloIdentity) -> String {
    let profile = hello
        .profile_id
        .as_deref()
        .and_then(|value| Uuid::parse_str(value).ok())
        .unwrap_or(Uuid::nil());
    format!(
        "{}:{}:{}",
        family(&hello.backend),
        profile.simple(),
        Uuid::new_v4().simple()
    )
}

impl BrowserBridgeServer {
    pub(super) fn admit(
        &self,
        session: Arc<BrokerSession>,
    ) -> CoreResult<Option<Arc<BrokerSession>>> {
        let mut sessions = self.backends.lock().expect("browser bridge instances");
        if self.is_stopped() {
            return Err(CoreError::Tool("browser bridge is stopped".into()));
        }
        let prior = sessions
            .iter()
            .find(|(_, prior)| {
                prior.backend == session.backend
                    && prior.hello.profile_id == session.hello.profile_id
                    && prior.hello.extension_instance_id == session.hello.extension_instance_id
            })
            .map(|(id, _)| id.clone());
        let previous = prior.and_then(|id| sessions.remove(&id));
        sessions.insert(session.browser_id.clone(), session);
        Ok(previous)
    }

    pub(super) fn resolve_session(&self, selector: &str) -> CoreResult<Arc<BrokerSession>> {
        let sessions = self.backends.lock().expect("browser bridge instances");
        if self.is_stopped() {
            return Err(CoreError::Tool("browser bridge is stopped".into()));
        }
        if let Some(session) = sessions
            .get(selector)
            .filter(|session| !session.closed.load(Ordering::SeqCst))
        {
            return Ok(Arc::clone(session));
        }
        let backend = match selector {
            "chrome" | BACKEND_CHROME_EXTENSION => BACKEND_CHROME_EXTENSION,
            "edge" | BACKEND_EDGE_EXTENSION => BACKEND_EDGE_EXTENSION,
            BACKEND_IAB => BACKEND_IAB,
            _ => {
                return Err(CoreError::Tool(
                    "browser_instance_expired: select a live browser instance".into(),
                ))
            }
        };
        let mut matches = sessions
            .values()
            .filter(|session| session.backend == backend && !session.closed.load(Ordering::SeqCst));
        let Some(session) = matches.next() else {
            return Err(CoreError::Tool(format!(
                "browser bridge backend '{backend}' is not connected"
            )));
        };
        if matches.next().is_some() {
            return Err(CoreError::Tool(
                "browser_instance_ambiguous: select a profile and instance from the inventory"
                    .into(),
            ));
        }
        Ok(Arc::clone(session))
    }

    pub(super) fn browser_inventory(&self) -> Value {
        let sessions = self.backends.lock().expect("browser bridge instances");
        let mut result = sessions.values().filter(|session| !session.closed.load(Ordering::SeqCst))
            .map(|session| json!({
                "id":session.browser_id,"type":family(&session.backend),"backend":family(&session.backend),
                "metadata":{
                    "profileId":session.hello.profile_id,
                    "extensionInstanceId":session.hello.extension_instance_id,
                    "connectionGeneration":session.browser_id.rsplit(':').next(),
                    "extensionId":session.hello.extension_id,
                    "extensionVersion":session.hello.extension_version,
                }
            })).collect::<Vec<_>>();
        result.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
        json!(result)
    }
}
