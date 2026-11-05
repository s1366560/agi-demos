//! Deadline cleanup releases native resources while retaining the logical HITL session.
use super::*;
use std::sync::atomic::{AtomicI64, AtomicU64};
use tokio::time::{sleep, Duration};

#[derive(Default)]
pub(super) struct ResourceLease {
    generation: AtomicU64,
    expired: AtomicBool,
    deadline: AtomicI64,
    continuity_deadline_ms: AtomicI64,
    pub(super) gate: tokio::sync::Mutex<()>,
}
impl ResourceLease {
    pub(super) fn invalidate(&self) {
        self.continuity_deadline_ms.store(0, Ordering::SeqCst);
        self.generation.fetch_add(1, Ordering::SeqCst);
    }
    pub(super) fn current(&self) -> bool {
        !self.expired.load(Ordering::SeqCst)
            && (self.deadline.load(Ordering::SeqCst) > chrono::Utc::now().timestamp()
                || self.continuity_current())
    }
    pub(super) fn renew_continuity(&self, expires_at_ms: i64) {
        self.continuity_deadline_ms
            .store(expires_at_ms, Ordering::SeqCst);
    }
    pub(super) fn clear_continuity(&self) {
        self.continuity_deadline_ms.store(0, Ordering::SeqCst);
    }
    fn continuity_current(&self) -> bool {
        self.continuity_deadline_ms.load(Ordering::SeqCst) > chrono::Utc::now().timestamp_millis()
    }
    pub(super) fn released(&self) -> bool {
        self.expired.load(Ordering::SeqCst)
    }
}
pub(super) async fn renew(
    state: &Arc<LocalRuntimeState>,
    session: &Arc<Session>,
    lease: cloud::CloudLease,
    expires: i64,
) -> Result<(), String> {
    renew_inner(state, session, lease, expires, false).await
}
pub(super) async fn renew_paused(
    state: &Arc<LocalRuntimeState>,
    session: &Arc<Session>,
    lease: cloud::CloudLease,
    expires: i64,
) -> Result<(), String> {
    renew_inner(state, session, lease, expires, true).await
}
async fn renew_inner(
    state: &Arc<LocalRuntimeState>,
    session: &Arc<Session>,
    lease: cloud::CloudLease,
    expires: i64,
    resume_paused: bool,
) -> Result<(), String> {
    let _gate = session.resources.gate.lock().await;
    if session.stopped.load(Ordering::SeqCst) || !lease.current(state) {
        return Err("cua_cloud_lease_expired".into());
    }
    if session.resources.expired.load(Ordering::SeqCst) {
        let reset = async {
            state
                .computer_use
                .client()?
                .request_in_session(&session.context, "reset_session", json!({}))
                .await
                .map_err(|_| "cua_native_session_reset_failed")?;
            if session.stopped.load(Ordering::SeqCst) || !lease.current(state) {
                return Err("cua_cloud_lease_expired".to_owned());
            }
            if resume_paused {
                state
                    .computer_use
                    .client()?
                    .request_in_session(&session.context, "pause_session", json!({}))
                    .await
                    .map_err(|_| "cua_native_pause_unavailable")?;
            }
            Ok(())
        }
        .await;
        if let Err(error) = reset {
            release_native(state, session).await;
            return Err(error);
        }
    }
    if session.stopped.load(Ordering::SeqCst) || !lease.current(state) {
        release_native(state, session).await;
        return Err("cua_cloud_lease_expired".into());
    }
    let generation = session.resources.generation.fetch_add(1, Ordering::SeqCst) + 1;
    session.resources.deadline.store(expires, Ordering::SeqCst);
    session.resources.expired.store(false, Ordering::SeqCst);
    let state = Arc::downgrade(state);
    let session = session.clone();
    tokio::spawn(async move {
        loop {
            let Some(state) = state.upgrade() else {
                return;
            };
            if session.stopped.load(Ordering::SeqCst)
                || session.resources.generation.load(Ordering::SeqCst) != generation
            {
                return;
            }
            if expires <= chrono::Utc::now().timestamp() || !lease.current(&state) {
                if expire(&state, &session, generation).await {
                    return;
                }
            }
            drop(state);
            sleep(Duration::from_millis(250)).await;
        }
    });
    Ok(())
}
async fn expire(state: &LocalRuntimeState, session: &Arc<Session>, generation: u64) -> bool {
    let _gate = session.resources.gate.lock().await;
    if session.stopped.load(Ordering::SeqCst)
        || session.resources.generation.load(Ordering::SeqCst) != generation
    {
        return true;
    }
    if session.resources.continuity_current() {
        return false;
    }
    release_native(state, session).await;
    true
}
// The caller holds resources.gate so teardown cannot race an implicit begin_session.
pub(super) async fn release_native(state: &LocalRuntimeState, session: &Arc<Session>) {
    session.resources.clear_continuity();
    state
        .computer_use
        .locked_use
        .invalidate(&session.context.session_id);
    session.resources.expired.store(true, Ordering::SeqCst);
    if let Some(client) = state.computer_use.client.get() {
        let _ = client
            .stop_session_with_reason(&session.context.session_id, "lease_expired")
            .await;
        super::recordings::refresh_session(state, session).await;
        let _ = client.end_session(&session.context.session_id).await;
    }
}
