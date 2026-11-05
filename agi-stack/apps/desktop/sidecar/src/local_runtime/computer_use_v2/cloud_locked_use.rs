//! Run continuity is revalidated independently of the one-shot tool claim.
use super::*;

#[derive(Clone)]
pub(in crate::local_runtime::computer_use_v2) struct Continuity {
    lease: CloudLease,
    body: Value,
    expires_at_ms: i64,
}

impl Continuity {
    pub(in crate::local_runtime::computer_use_v2) async fn acquire(
        state: &LocalRuntimeState,
        session: &Session,
        lease: &CloudLease,
    ) -> Result<Self, String> {
        if !lease.current(state) {
            return Err("cua_cloud_lease_expired".into());
        }
        let cloud = session.cloud.as_ref().ok_or("cua_cloud_session_required")?;
        let origin = crate::local_runtime::execution_authority::current_step_origin();
        let step = crate::local_runtime::execution_authority::current_step_id();
        let mut value = Self {
            lease: lease.clone(),
            expires_at_ms: 0,
            body: json!({"device_id":session.owner.device_id,"session_id":cloud.engine_session_id,
                "cell_id":origin.as_ref().map(|origin| &origin.cell_id),"step_id":step,
                "parent_request_id":origin.and_then(|origin|origin.parent_request_id)}),
        };
        value.renew(state, session).await?;
        Ok(value)
    }

    fn connection_current(&self, state: &LocalRuntimeState, session: &Session) -> bool {
        let Some(cloud) = &session.cloud else {
            return false;
        };
        !self.lease.cancelled.load(Ordering::SeqCst)
            && self.lease.alive.load(Ordering::SeqCst)
            && self.lease.broker.snapshot().is_ok_and(|snapshot| {
                snapshot.epoch == self.lease.epoch && snapshot.record.is_some()
            })
            && state
                .computer_use
                .cloud_connections
                .lock()
                .is_ok_and(|connections| {
                    connections
                        .get(&cloud.connection_id)
                        .is_some_and(|connection| {
                            connection.ready
                                && connection.epoch == self.lease.epoch
                                && connection.owner == session.owner
                                && Arc::ptr_eq(&connection.alive, &self.lease.alive)
                        })
                })
    }

    pub(in crate::local_runtime::computer_use_v2) fn current(
        &self,
        state: &LocalRuntimeState,
        session: &Session,
    ) -> bool {
        self.expires_at_ms > chrono::Utc::now().timestamp_millis()
            && self.connection_current(state, session)
    }

    pub(in crate::local_runtime::computer_use_v2) fn ttl_ms(&self) -> Result<i64, String> {
        let remaining = self.expires_at_ms - chrono::Utc::now().timestamp_millis();
        if remaining < 1000 {
            return Err("cua_cloud_continuity_expired".into());
        }
        Ok(remaining.min(5000))
    }
    pub(in crate::local_runtime::computer_use_v2) fn resource_deadline(&self) -> i64 {
        self.expires_at_ms
    }

    pub(in crate::local_runtime::computer_use_v2) async fn renew(
        &mut self,
        state: &LocalRuntimeState,
        session: &Session,
    ) -> Result<(), String> {
        if !self.connection_current(state, session) {
            return Err("cua_cloud_continuity_revoked".into());
        }
        let transport = transport(&self.lease.broker)?;
        let mut url = url::Url::parse(&format!("{}/api/v1/agent/device/requests/", transport.base))
            .map_err(|_| "cua_cloud_authority_invalid")?;
        url.path_segments_mut()
            .map_err(|_| "cua_cloud_authority_invalid")?
            .pop_if_empty()
            .push(&self.lease.request_id)
            .push("continuity-authority");
        let response: Value = tokio::time::timeout(std::time::Duration::from_millis(900), async {
            transport
                .client
                .post(url)
                .bearer_auth(&transport.credential)
                .json(&self.body)
                .send()
                .await
                .map_err(|_| "cua_cloud_continuity_unavailable")?
                .error_for_status()
                .map_err(|_| "cua_cloud_continuity_rejected")?
                .json()
                .await
                .map_err(|_| "cua_cloud_continuity_invalid")
        })
        .await
        .map_err(|_| "cua_cloud_continuity_timeout")??;
        let now = chrono::Utc::now().timestamp_millis();
        let expires = response["expires_at_ms"]
            .as_i64()
            .ok_or("cua_cloud_continuity_invalid")?;
        let cloud = session.cloud.as_ref().ok_or("cua_cloud_session_required")?;
        if response["request_id"] != self.lease.request_id
            || response["user_id"] != session.owner.user_id
            || response["tenant_id"] != session.owner.tenant_id
            || response["project_id"] != session.owner.project_id
            || response["device_id"] != session.owner.device_id
            || response["run_id"] != session.context.run_id
            || response["conversation_id"] != session.context.conversation_id
            || response["session_id"] != cloud.engine_session_id
            || response["authorization_revision"] != self.lease.authorization_revision
            || expires <= now
            || expires > now + 5000
            || !self.connection_current(state, session)
        {
            return Err("cua_cloud_continuity_scope_invalid".into());
        }
        self.expires_at_ms = expires;
        Ok(())
    }
}
