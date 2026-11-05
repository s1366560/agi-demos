//! UI selection is authenticated independently from agent browser claims.
use super::{scoped_conversation, LocalRuntimeService};
use crate::trusted_session::{TrustedSessionBroker, TrustedSessionRuntimeMode};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ContextRequest {
    conversation_id: String,
    mode: String,
    tenant_id: String,
    project_id: String,
    #[serde(default)]
    credential: String,
}

impl LocalRuntimeService {
    /// Returns only an existing, authorized conversation. This grants no tab control.
    pub(crate) async fn browser_context(
        &self,
        broker: &TrustedSessionBroker,
        input: Value,
    ) -> Result<Value, String> {
        let request: ContextRequest =
            serde_json::from_value(input).map_err(|_| "browser_context_invalid")?;
        if [
            &request.conversation_id,
            &request.tenant_id,
            &request.project_id,
        ]
        .iter()
        .any(|value| value.is_empty() || value.len() > 512)
        {
            return Err("browser_context_invalid".into());
        }
        match request.mode.as_str() {
            "local" => {
                let authenticated = self
                    .state
                    .session_store
                    .validate_session_credential(
                        &request.credential,
                        chrono::Utc::now().timestamp_millis(),
                    )?
                    .ok_or("browser_context_session_required")?;
                if authenticated.workspace.tenant_id != request.tenant_id
                    || authenticated.workspace.project_id != request.project_id
                {
                    return Err("browser_context_scope_changed".into());
                }
                let conversation =
                    scoped_conversation(&self.state, &authenticated, &request.conversation_id)
                        .map_err(|_| "browser_context_conversation_unavailable")?;
                Ok(json!({"session_id":conversation.id}))
            }
            "cloud" => {
                let snapshot = broker
                    .snapshot()
                    .map_err(|_| "browser_context_session_required")?;
                let record = snapshot
                    .record
                    .as_ref()
                    .filter(|record| record.runtime_mode == TrustedSessionRuntimeMode::Cloud)
                    .ok_or("browser_context_session_required")?;
                let base = record.api_base_url.trim_end_matches('/');
                let base = base.strip_suffix("/api/v1").unwrap_or(base);
                let mut url = url::Url::parse(&format!("{base}/api/v1/agent/conversations/"))
                    .map_err(|_| "browser_context_invalid")?;
                url.path_segments_mut()
                    .map_err(|_| "browser_context_invalid")?
                    .pop_if_empty()
                    .push(&request.conversation_id);
                url.query_pairs_mut()
                    .append_pair("project_id", &request.project_id);
                let conversation: Value = reqwest::Client::builder()
                    .redirect(reqwest::redirect::Policy::none())
                    .timeout(std::time::Duration::from_secs(15))
                    .build()
                    .map_err(|_| "browser_context_unavailable")?
                    .get(url)
                    .bearer_auth(&record.credential)
                    .send()
                    .await
                    .map_err(|_| "browser_context_unavailable")?
                    .error_for_status()
                    .map_err(|_| "browser_context_conversation_unavailable")?
                    .json()
                    .await
                    .map_err(|_| "browser_context_invalid")?;
                if conversation["id"].as_str() != Some(request.conversation_id.as_str())
                    || conversation["tenant_id"].as_str() != Some(request.tenant_id.as_str())
                    || conversation["project_id"].as_str() != Some(request.project_id.as_str())
                    || broker
                        .snapshot()
                        .map_err(|_| "browser_context_session_required")?
                        != snapshot
                {
                    return Err("browser_context_changed".into());
                }
                Ok(json!({"session_id":request.conversation_id}))
            }
            _ => Err("browser_context_invalid".into()),
        }
    }
}

#[cfg(test)]
#[path = "browser_context_tests.rs"]
mod tests;
