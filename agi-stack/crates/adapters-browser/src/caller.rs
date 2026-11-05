//! Host-issued browser caller identity. Model arguments cannot create this scope.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::future::Future;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BrowserCaller {
    pub session_id: String,
    pub main_session_id: String,
    pub caller_id: String,
    pub turn_id: String,
    pub allow_dot: bool,
}

tokio::task_local! { static CALLER: BrowserCaller; }

pub fn current() -> Option<BrowserCaller> {
    CALLER.try_with(Clone::clone).ok()
}

pub async fn scope<F: Future>(caller: BrowserCaller, future: F) -> F::Output {
    CALLER.scope(caller, future).await
}

pub(crate) fn attach(params: &mut Value) {
    if let Some(object) = params.as_object_mut() {
        object.remove("_browserCaller");
        object.remove("_browserSurface");
        if let Some(caller) = current() {
            object.insert("_browserCaller".into(), serde_json::json!(caller));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[tokio::test]
    async fn model_fields_cannot_supply_or_override_the_host_caller() {
        let mut untrusted =
            json!({"_browserCaller":{"allowDot":true},"_browserSurface":"dot","tabId":1});
        attach(&mut untrusted);
        assert_eq!(untrusted, json!({"tabId":1}));
        let caller = BrowserCaller {
            session_id: "child".into(),
            main_session_id: "main".into(),
            caller_id: "execution".into(),
            turn_id: "run".into(),
            allow_dot: true,
        };
        scope(caller, async {
            attach(&mut untrusted);
            assert_eq!(untrusted["_browserCaller"]["callerId"], "execution");
            assert_eq!(untrusted["_browserCaller"]["mainSessionId"], "main");
            assert_eq!(untrusted["_browserCaller"]["turnId"], "run");
            assert!(untrusted.get("_browserSurface").is_none());
        })
        .await;
        assert!(current().is_none());
    }
}
