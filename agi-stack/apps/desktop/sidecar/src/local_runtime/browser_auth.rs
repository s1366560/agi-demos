//! Ephemeral secure authentication prompts. Credential values never enter the agent transcript.
use std::collections::{BTreeMap, BTreeSet};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::sync::oneshot;
use zeroize::Zeroize;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Field {
    pub id: String,
    pub label: String,
    #[serde(rename = "type")]
    pub input_type: String,
    #[serde(default)]
    pub autocomplete: Option<String>,
    #[serde(default)]
    pub required: bool,
    pub selector: Value,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SignInOption {
    pub id: String,
    pub label: String,
    #[serde(default)]
    pub field_ids: Vec<String>,
    #[serde(default)]
    pub selector: Option<Value>,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Submit {
    pub selector: Value,
    pub action: String,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AuthRequest {
    pub origin: String,
    pub fields: Vec<Field>,
    #[serde(default)]
    pub options: Vec<SignInOption>,
    #[serde(default)]
    pub submit: Option<Submit>,
    #[serde(default)]
    pub account_identifier: Option<String>,
    #[serde(default)]
    pub qr_code: bool,
}

impl AuthRequest {
    pub(super) fn parse(value: &Value) -> Result<Self, String> {
        let request: Self =
            serde_json::from_value(value.clone()).map_err(|_| "browser_auth_request_invalid")?;
        let url = url::Url::parse(&request.origin).map_err(|_| "browser_auth_origin_invalid")?;
        if !matches!(url.scheme(), "https" | "http")
            || url.origin().ascii_serialization() != request.origin
        {
            return Err("browser_auth_origin_invalid".into());
        }
        if request.qr_code
            && (!request.fields.is_empty()
                || !request.options.is_empty()
                || request.submit.is_some())
        {
            return Err("browser_auth_qr_request_invalid".into());
        }
        if request.fields.len() > 16
            || request.options.len() > 16
            || request.options.len() == 1
            || (request.fields.is_empty() && request.options.is_empty() && !request.qr_code)
        {
            return Err("browser_auth_request_invalid".into());
        }
        if request
            .account_identifier
            .as_ref()
            .is_some_and(|value| !bounded_text(value, 256))
        {
            return Err("browser_auth_account_invalid".into());
        }
        let mut ids = BTreeSet::new();
        for field in &request.fields {
            if !identifier(&field.id)
                || !ids.insert(field.id.clone())
                || !bounded_text(&field.label, 100)
                || !matches!(
                    field.input_type.as_str(),
                    "text" | "password" | "email" | "tel" | "number" | "search"
                )
                || field
                    .autocomplete
                    .as_ref()
                    .is_some_and(|value| !bounded_text(value, 100))
                || !selector(&field.selector)
            {
                return Err("browser_auth_field_invalid".into());
            }
        }
        let mut options = BTreeSet::new();
        for option in &request.options {
            let fields: BTreeSet<_> = option.field_ids.iter().collect();
            if !identifier(&option.id)
                || !options.insert(&option.id)
                || !bounded_text(&option.label, 100)
                || fields.len() != option.field_ids.len()
                || fields.iter().any(|id| !ids.contains(*id))
                || option.selector.is_some() == !option.field_ids.is_empty()
                || option
                    .selector
                    .as_ref()
                    .is_some_and(|value| !selector(value))
            {
                return Err("browser_auth_option_invalid".into());
            }
        }
        if request.submit.as_ref().is_some_and(|submit| {
            !matches!(submit.action.as_str(), "click" | "press_enter")
                || !selector(&submit.selector)
        }) {
            return Err("browser_auth_submit_invalid".into());
        }
        Ok(request)
    }

    fn selected_fields<'a>(&'a self, selected: Option<&str>) -> Result<Vec<&'a Field>, String> {
        if self.options.is_empty() {
            if selected.is_some() {
                return Err("browser_auth_option_invalid".into());
            }
            return Ok(self.fields.iter().collect());
        }
        let option = self
            .options
            .iter()
            .find(|option| Some(option.id.as_str()) == selected)
            .ok_or("browser_auth_option_required")?;
        Ok(self
            .fields
            .iter()
            .filter(|field| option.field_ids.contains(&field.id))
            .collect())
    }
}

fn bounded_text(value: &str, max: usize) -> bool {
    !value.trim().is_empty() && value.chars().count() <= max && !value.chars().any(char::is_control)
}
fn identifier(value: &str) -> bool {
    (1..=64).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
}
fn selector(value: &Value) -> bool {
    value.as_object().is_some_and(|object| object.len() == 1)
        && value["steps"]
            .as_array()
            .is_some_and(|steps| !steps.is_empty() && steps.len() <= 16)
        && value.to_string().len() <= 8192
}

#[derive(Clone, PartialEq, Eq)]
pub(super) struct AuthOwner {
    pub conversation_id: String,
    pub run_id: String,
    pub run_revision: u64,
    pub backend: String,
    pub tab_id: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AuthResponse {
    pub action: String,
    #[serde(default)]
    pub selected_option: Option<String>,
    #[serde(default)]
    pub values: BTreeMap<String, String>,
}
impl Drop for AuthResponse {
    fn drop(&mut self) {
        for value in self.values.values_mut() {
            value.zeroize();
        }
    }
}

pub(super) struct AuthReply {
    pub declined: bool,
    pub selected_option: Option<String>,
    pub values: BTreeMap<String, String>,
}
impl Drop for AuthReply {
    fn drop(&mut self) {
        for value in self.values.values_mut() {
            value.zeroize();
        }
    }
}

struct Pending {
    current: Arc<dyn Fn() -> bool + Send + Sync>,
    qr_image: Option<zeroize::Zeroizing<String>>,
    owner: AuthOwner,
    request: AuthRequest,
    deadline: Instant,
    expires_at: String,
    response: oneshot::Sender<AuthReply>,
}

#[derive(Clone, Default)]
pub(super) struct BrowserAuthBroker {
    pending: Arc<Mutex<BTreeMap<String, Pending>>>,
}

pub(super) struct AuthTicket {
    pub id: String,
    broker: BrowserAuthBroker,
    response: Option<oneshot::Receiver<AuthReply>>,
    deadline: Instant,
}
impl Drop for AuthTicket {
    fn drop(&mut self) {
        if let Ok(mut pending) = self.broker.pending.lock() {
            pending.remove(&self.id);
        }
    }
}
impl AuthTicket {
    pub(super) async fn receive(&mut self) -> Result<AuthReply, String> {
        let receiver = self
            .response
            .take()
            .ok_or("browser_auth_already_consumed")?;
        tokio::time::timeout_at(self.deadline.into(), receiver)
            .await
            .map_err(|_| "browser_auth_expired")?
            .map_err(|_| "browser_auth_cancelled".into())
    }
}

impl BrowserAuthBroker {
    pub(super) fn cancel_run(&self, run_id: &str) {
        self.pending
            .lock()
            .expect("browser auth requests")
            .retain(|_, pending| pending.owner.run_id != run_id);
    }

    pub(super) fn begin(
        &self,
        owner: AuthOwner,
        request: AuthRequest,
    ) -> Result<AuthTicket, String> {
        self.begin_current(owner, request, Arc::new(|| true), None)
    }

    pub(super) fn begin_current(
        &self,
        owner: AuthOwner,
        request: AuthRequest,
        current: Arc<dyn Fn() -> bool + Send + Sync>,
        qr_image: Option<String>,
    ) -> Result<AuthTicket, String> {
        if !current() {
            return Err("browser_auth_run_changed".into());
        }
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| "browser_auth_unavailable")?;
        pending.retain(|_, item| item.deadline > Instant::now() && (item.current)());
        if pending.len() >= 16
            || pending.values().any(|item| {
                item.owner.backend == owner.backend && item.owner.tab_id == owner.tab_id
            })
        {
            return Err("browser_auth_request_already_pending".into());
        }
        let id = uuid::Uuid::new_v4().to_string();
        let deadline = Instant::now() + Duration::from_secs(300);
        let (sender, receiver) = oneshot::channel();
        pending.insert(
            id.clone(),
            Pending {
                current,
                qr_image: qr_image.map(zeroize::Zeroizing::new),
                owner,
                request,
                deadline,
                expires_at: (chrono::Utc::now() + chrono::Duration::seconds(300)).to_rfc3339(),
                response: sender,
            },
        );
        Ok(AuthTicket {
            id,
            broker: self.clone(),
            response: Some(receiver),
            deadline,
        })
    }

    /// Presentation data is available only to the authenticated native UI, never a tool result.
    pub(super) fn pending_for(&self, conversation_id: &str) -> Result<Value, String> {
        let mut prompts = self.pending_for_ui(conversation_id)?;
        if let Some(prompts) = prompts.as_array_mut() {
            for prompt in prompts {
                if let Some(prompt) = prompt.as_object_mut() {
                    prompt.remove("qr_image");
                }
            }
        }
        Ok(prompts)
    }

    pub(super) fn pending_for_ui(&self, conversation_id: &str) -> Result<Value, String> {
        let pending = self
            .pending
            .lock()
            .map_err(|_| "browser_auth_unavailable")?;
        Ok(json!(pending.iter().filter(|(_, item)| item.owner.conversation_id == conversation_id && item.deadline > Instant::now() && (item.current)())
            .map(|(id,item)| json!({"request_id":id,"conversation_id":item.owner.conversation_id,"run_id":item.owner.run_id,
                "run_revision":item.owner.run_revision,"origin":item.request.origin,"expires_at":item.expires_at,
                "account_identifier":item.request.account_identifier,"qr_image":item.qr_image.as_ref().map(|image|image.as_str()),
                "fields":item.request.fields.iter().map(|field| json!({"id":field.id,"label":field.label,"type":field.input_type,"required":field.required})).collect::<Vec<_>>(),
                "options":item.request.options.iter().map(|option| json!({"id":option.id,"label":option.label,"field_ids":option.field_ids})).collect::<Vec<_>>()
            })).collect::<Vec<_>>()))
    }

    pub(super) fn owner(&self, request_id: &str) -> Result<AuthOwner, String> {
        self.pending
            .lock()
            .map_err(|_| "browser_auth_unavailable")?
            .get(request_id)
            .filter(|item| item.deadline > Instant::now() && (item.current)())
            .map(|item| item.owner.clone())
            .ok_or_else(|| "browser_auth_expired".into())
    }

    /// The authenticated route verifies conversation/run ownership before calling this method.
    pub(super) fn respond(
        &self,
        request_id: &str,
        owner: &AuthOwner,
        mut response: AuthResponse,
    ) -> Result<(), String> {
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| "browser_auth_unavailable")?;
        let item = pending
            .get(request_id)
            .filter(|item| {
                item.owner == *owner && item.deadline > Instant::now() && (item.current)()
            })
            .ok_or("browser_auth_expired")?;
        if response.action == "decline" {
            if !response.values.is_empty() || response.selected_option.is_some() {
                return Err("browser_auth_response_invalid".into());
            }
        } else if response.action == "submit" {
            let fields = item
                .request
                .selected_fields(response.selected_option.as_deref())?;
            if response
                .values
                .keys()
                .any(|id| !fields.iter().any(|field| field.id == *id))
                || response
                    .values
                    .values()
                    .any(|value| value.len() > 4096 || value.contains('\0'))
                || fields.iter().any(|field| {
                    field.required && response.values.get(&field.id).is_none_or(String::is_empty)
                })
            {
                return Err("browser_auth_response_invalid".into());
            }
        } else {
            return Err("browser_auth_response_invalid".into());
        }
        let item = pending.remove(request_id).ok_or("browser_auth_expired")?;
        item.response
            .send(AuthReply {
                declined: response.action == "decline",
                selected_option: response.selected_option.take(),
                values: std::mem::take(&mut response.values),
            })
            .map_err(|_| "browser_auth_cancelled".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn request() -> AuthRequest {
        AuthRequest::parse(&json!({"origin":"https://example.com","fields":[{"id":"password","label":"Password","type":"password","required":true,"selector":{"steps":[{"kind":"locator","args":["input[type=password]"]}]}}]})).unwrap()
    }
    fn owner() -> AuthOwner {
        AuthOwner {
            conversation_id: "conversation".into(),
            run_id: "run".into(),
            run_revision: 1,
            backend: "chrome".into(),
            tab_id: 1,
        }
    }
    #[tokio::test]
    async fn prompt_values_are_ephemeral_single_use_and_owner_bound() {
        let broker = BrowserAuthBroker::default();
        let owner = owner();
        let mut ticket = broker.begin(owner.clone(), request()).unwrap();
        assert_eq!(broker.pending_for("other").unwrap(), json!([]));
        assert!(!broker
            .pending_for("conversation")
            .unwrap()
            .to_string()
            .contains("selector"));
        let mut other = owner.clone();
        other.run_revision = 2;
        let response = || AuthResponse {
            action: "submit".into(),
            selected_option: None,
            values: BTreeMap::from([("password".into(), "secret-test-value".into())]),
        };
        assert!(broker.respond(&ticket.id, &other, response()).is_err());
        broker.respond(&ticket.id, &owner, response()).unwrap();
        let reply = ticket.receive().await.unwrap();
        assert_eq!(reply.values["password"], "secret-test-value");
        assert!(broker.respond(&ticket.id, &owner, response()).is_err());
        assert_eq!(broker.pending_for("conversation").unwrap(), json!([]));
    }
    #[test]
    fn dropped_prompt_cancels_and_request_rejects_noncanonical_or_mixed_fields() {
        let broker = BrowserAuthBroker::default();
        let ticket = broker.begin(owner(), request()).unwrap();
        let id = ticket.id.clone();
        drop(ticket);
        assert!(broker.owner(&id).is_err());
        let mut value = serde_json::to_value(request()).unwrap();
        value["origin"] = json!("https://example.com/login");
        assert!(AuthRequest::parse(&value).is_err());
        value["origin"] = json!("https://example.com");
        value["fields"][0]["value"] = json!("must-not-be-accepted");
        assert!(AuthRequest::parse(&value).is_err());
    }
    #[test]
    fn qr_image_is_native_ui_only_and_revocation_closes_its_authority() {
        use std::sync::atomic::{AtomicBool, Ordering};
        let live = Arc::new(AtomicBool::new(true));
        let guard = live.clone();
        let broker = BrowserAuthBroker::default();
        let request =
            AuthRequest::parse(&json!({"origin":"https://example.com","fields":[],"qr_code":true}))
                .unwrap();
        let ticket = broker
            .begin_current(
                owner(),
                request,
                Arc::new(move || guard.load(Ordering::SeqCst)),
                Some("data:image/png;base64,test-only".into()),
            )
            .unwrap();
        assert!(!broker
            .pending_for("conversation")
            .unwrap()
            .to_string()
            .contains("base64"));
        assert_eq!(
            broker.pending_for_ui("conversation").unwrap()[0]["qr_image"],
            "data:image/png;base64,test-only"
        );
        live.store(false, Ordering::SeqCst);
        assert_eq!(broker.pending_for_ui("conversation").unwrap(), json!([]));
        assert!(broker
            .respond(
                &ticket.id,
                &owner(),
                AuthResponse {
                    action: "submit".into(),
                    selected_option: None,
                    values: BTreeMap::new()
                }
            )
            .is_err());
        assert!(AuthRequest::parse(&json!({"origin":"https://example.com","fields":[],"qr_code":true,"options":[{"id":"choice","label":"Choice","selector":{"steps":[]}}]})).is_err());
    }
}
