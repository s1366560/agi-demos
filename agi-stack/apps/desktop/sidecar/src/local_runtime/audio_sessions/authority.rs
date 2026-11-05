//! Renderer inputs select scope, never identity. Offline controls retain a verified epoch.
use super::{store::Owner, Request};
use crate::{
    local_runtime::LocalRuntimeState,
    trusted_session::{TrustedSessionBroker, TrustedSessionRuntimeMode},
};
use serde_json::Value;
use std::sync::Arc;

pub(super) async fn resolve(
    state: &Arc<LocalRuntimeState>,
    broker: &TrustedSessionBroker,
    request: &Request,
) -> Result<(Owner, Option<u64>), String> {
    if request.mode == "local" {
        let auth = state
            .session_store
            .validate_session_credential(
                &request.credential,
                chrono::Utc::now().timestamp_millis(),
            )?
            .ok_or("audio_session_authentication_required")?;
        if auth.workspace.tenant_id != request.tenant_id
            || auth.workspace.project_id != request.project_id
        {
            return Err("audio_session_scope_mismatch".into());
        }
        return Ok((
            Owner {
                user_id: auth.user.user_id,
                tenant_id: request.tenant_id.clone(),
                project_id: request.project_id.clone(),
                device_id: state.session_store.installation_id().into(),
            },
            None,
        ));
    }
    if request.mode != "cloud" {
        return Err("audio_session_mode_invalid".into());
    }
    let snapshot = broker
        .snapshot()
        .map_err(|_| "audio_session_authentication_required")?;
    let record = snapshot
        .record
        .ok_or("audio_session_authentication_required")?;
    if record.runtime_mode != TrustedSessionRuntimeMode::Cloud {
        return Err("audio_session_authentication_required".into());
    }
    let cached = state
        .audio_sessions
        .cloud_owner
        .lock()
        .map_err(|_| "audio_session_store_unavailable")?
        .get(&(
            snapshot.epoch,
            request.tenant_id.clone(),
            request.project_id.clone(),
        ))
        .cloned();
    if let Some(owner) = cached {
        return Ok((owner, Some(snapshot.epoch)));
    }
    let base = record
        .api_base_url
        .trim_end_matches('/')
        .trim_end_matches("/api/v1");
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "audio_session_identity_unavailable")?;
    let mut url = url::Url::parse(&format!("{base}/api/v1/projects/"))
        .map_err(|_| "audio_session_scope_invalid")?;
    url.path_segments_mut()
        .map_err(|_| "audio_session_scope_invalid")?
        .pop_if_empty()
        .push(&request.project_id);
    let project: Value = client
        .get(url)
        .bearer_auth(&record.credential)
        .send()
        .await
        .map_err(|_| "audio_session_scope_unavailable")?
        .error_for_status()
        .map_err(|_| "audio_session_scope_unavailable")?
        .json()
        .await
        .map_err(|_| "audio_session_scope_invalid")?;
    if project["tenant_id"].as_str() != Some(request.tenant_id.as_str()) {
        return Err("audio_session_scope_mismatch".into());
    }
    let me: Value = client
        .get(format!("{base}/api/v1/auth/me"))
        .bearer_auth(&record.credential)
        .send()
        .await
        .map_err(|_| "audio_session_identity_unavailable")?
        .error_for_status()
        .map_err(|_| "audio_session_identity_unavailable")?
        .json()
        .await
        .map_err(|_| "audio_session_identity_invalid")?;
    let user_id = me
        .get("user_id")
        .or_else(|| me.get("id"))
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty())
        .ok_or("audio_session_identity_invalid")?
        .to_owned();
    current(broker, Some(snapshot.epoch))?;
    let owner = Owner {
        user_id,
        tenant_id: request.tenant_id.clone(),
        project_id: request.project_id.clone(),
        device_id: state.session_store.installation_id().into(),
    };
    let mut cache = state
        .audio_sessions
        .cloud_owner
        .lock()
        .map_err(|_| "audio_session_store_unavailable")?;
    cache.retain(|(epoch, _, _), _| *epoch == snapshot.epoch);
    cache.insert(
        (
            snapshot.epoch,
            request.tenant_id.clone(),
            request.project_id.clone(),
        ),
        owner.clone(),
    );
    Ok((owner, Some(snapshot.epoch)))
}

pub(super) fn current(broker: &TrustedSessionBroker, epoch: Option<u64>) -> Result<(), String> {
    if let Some(epoch) = epoch {
        let current = broker
            .snapshot()
            .map_err(|_| "audio_session_identity_changed")?;
        if current.epoch != epoch || current.record.is_none() {
            return Err("audio_session_identity_changed".into());
        }
    }
    Ok(())
}
