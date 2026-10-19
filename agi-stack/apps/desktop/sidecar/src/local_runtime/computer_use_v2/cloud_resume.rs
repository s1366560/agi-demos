//! Explicit device resume revalidates the completed cloud invocation at its authority server.
use super::*;

#[derive(Clone)]
pub(super) struct ResumeBinding {
    request_id: String,
    authorization_revision: u64,
    lease: CloudLease,
}
impl ResumeBinding {
    pub(super) fn new(request_id: String, authorization_revision: u64, lease: CloudLease) -> Self {
        Self {
            request_id,
            authorization_revision,
            lease,
        }
    }
}

#[derive(Deserialize)]
struct ResumeAuthority {
    request_id: String,
    user_id: String,
    tenant_id: String,
    project_id: String,
    device_id: String,
    conversation_id: String,
    run_id: String,
    session_id: String,
    authorization_revision: u64,
    expires_at: i64,
}

/// This enables the explicit check button, not execution authority. The click rechecks the server.
pub(in crate::local_runtime::computer_use_v2) fn resume_available(
    state: &LocalRuntimeState,
    session: &Session,
) -> Result<(), &'static str> {
    let cloud = session.cloud.as_ref().ok_or("cua_cloud_session_required")?;
    let binding = cloud
        .resume
        .lock()
        .map_err(|_| "cua_cloud_resume_unavailable")?
        .clone()
        .ok_or("cua_cloud_resume_unavailable")?;
    if session.stopped.load(Ordering::SeqCst)
        || binding.lease.cancelled.load(Ordering::SeqCst)
        || !binding.lease.alive.load(Ordering::SeqCst)
    {
        return Err("cua_cloud_session_closed");
    }
    let connections = state
        .computer_use
        .cloud_connections
        .lock()
        .map_err(|_| "cua_cloud_connection_unavailable")?;
    let connection = connections
        .get(&cloud.connection_id)
        .ok_or("cua_cloud_connection_not_registered")?;
    if connection.owner != session.owner
        || !connection.ready
        || connection.epoch != binding.lease.epoch
        || connection
            .conversation_id
            .as_ref()
            .is_some_and(|id| id != &session.context.conversation_id)
        || !Arc::ptr_eq(&connection.alive, &binding.lease.alive)
        || !connection.broker.snapshot().is_ok_and(|snapshot| {
            snapshot.epoch == connection.epoch
                && snapshot
                    .record
                    .is_some_and(|record| record.runtime_mode == TrustedSessionRuntimeMode::Cloud)
        })
    {
        return Err("cua_cloud_authority_changed");
    }
    Ok(())
}

pub(in crate::local_runtime::computer_use_v2) async fn authorize_resume(
    state: &Arc<LocalRuntimeState>,
    session: &Arc<Session>,
) -> Result<(), String> {
    resume_available(state, session).map_err(str::to_owned)?;
    let cloud = session.cloud.as_ref().ok_or("cua_cloud_session_required")?;
    let binding = cloud
        .resume
        .lock()
        .map_err(|_| "cua_cloud_resume_unavailable")?
        .clone()
        .ok_or("cua_cloud_resume_unavailable")?;
    let transport = transport(&binding.lease.broker)?;
    let mut url = url::Url::parse(&format!("{}/api/v1/agent/device/requests/", transport.base))
        .map_err(|_| "cua_cloud_authority_invalid")?;
    url.path_segments_mut()
        .map_err(|_| "cua_cloud_authority_invalid")?
        .pop_if_empty()
        .push(&binding.request_id)
        .push("resume-authority");
    let authority: ResumeAuthority = transport
        .client
        .post(url)
        .bearer_auth(&transport.credential)
        .json(&json!({"device_id":session.owner.device_id,"session_id":cloud.engine_session_id}))
        .send()
        .await
        .map_err(|_| "cua_cloud_authority_unavailable")?
        .error_for_status()
        .map_err(|_| "cua_cloud_resume_denied")?
        .json()
        .await
        .map_err(|_| "cua_cloud_authority_invalid")?;
    let now = chrono::Utc::now().timestamp();
    if authority.request_id != binding.request_id
        || authority.user_id != session.owner.user_id
        || authority.tenant_id != session.owner.tenant_id
        || authority.project_id != session.owner.project_id
        || authority.device_id != session.owner.device_id
        || authority.conversation_id != session.context.conversation_id
        || authority.run_id != session.context.run_id
        || authority.session_id != cloud.engine_session_id
        || authority.authorization_revision != binding.authorization_revision
        || authority.expires_at <= now
        || authority.expires_at > now + 60
    {
        return Err("cua_cloud_resume_scope_invalid".into());
    }
    resume_available(state, session).map_err(str::to_owned)?;
    super::super::presentation::resume_allowed(state, session).map_err(str::to_owned)?;
    if !session.paused.load(Ordering::SeqCst)
        || cloud
            .resume
            .lock()
            .map_err(|_| "cua_cloud_resume_unavailable")?
            .as_ref()
            .is_none_or(|current| current.request_id != binding.request_id)
    {
        return Err("cua_cloud_resume_superseded".into());
    }
    // This lease only bounds native resource cleanup. It never authorizes a tool call.
    let mut resource_lease = binding.lease;
    resource_lease.expires_at = authority.expires_at;
    super::super::resource_lease::renew_paused(state, session, resource_lease, authority.expires_at)
        .await
}
