//! Owned native process teardown and stale-connection isolation.
use super::*;

impl CuaClient {
    /// Permanently fence admission before shutdown awaits another service.
    pub fn begin_shutdown(&self) {
        self.shutting_down.store(true, Ordering::Release);
    }

    pub(super) fn allow_during_shutdown(&self, method: &str) -> Result<(), CuaError> {
        if self.shutting_down.load(Ordering::Acquire)
            && !matches!(
                method,
                "stop_session"
                    | "end_session"
                    | "audio_status"
                    | "audio_stop"
                    | "audio_ack"
                    | "audio_session_status"
                    | "audio_session_stop"
                    | "audio_session_pause"
            )
        {
            return Err(CuaError::Unreachable("helper is shutting down".into()));
        }
        Ok(())
    }

    /// Send every owned stop before waiting on export locks or unrelated services.
    pub async fn stop_all_sessions(self: &Arc<Self>, reason: &str) {
        let connection = self.state.lock().await.as_ref().cloned();
        let Some(connection) = connection else { return };
        let ids = connection
            .sessions
            .lock()
            .await
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        let mut requests = tokio::task::JoinSet::new();
        for id in ids {
            let client = self.clone();
            let reason = reason.to_owned();
            requests.spawn(async move {
                let _ = client.stop_session_with_reason(&id, &reason).await;
            });
        }
        while requests.join_next().await.is_some() {}
    }
}

impl Connection {
    pub(super) fn abort(&self, reason: &str) {
        self.alive.store(false, Ordering::Release);
        let removed = self
            .input_bindings
            .remove_connection(&self.input_binding_id);
        self.input_telemetry.send_modify(|latest| {
            latest.retain(|id, event| removed.get(id) != Some(&event.input_generation))
        });
        // EOF reaches the native reader immediately and releases held input.
        if let Ok(mut writer) = self.writer.try_lock() {
            writer.take();
        }
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut child) = child.take() {
                if let Ok(runtime) = tokio::runtime::Handle::try_current() {
                    let writer = Arc::clone(&self.writer);
                    let task = runtime.spawn(async move {
                        let _ = timeout(Duration::from_millis(200), async {
                            writer.lock().await.take();
                        })
                        .await;
                        if timeout(Duration::from_millis(500), child.wait())
                            .await
                            .is_err()
                        {
                            let _ = child.start_kill();
                            let _ = child.wait().await;
                        }
                    });
                    if let Ok(mut reaper) = self.reaper.lock() {
                        *reaper = Some(task);
                    }
                } else {
                    let _ = child.start_kill();
                }
            }
        }
        if let Ok(mut pending) = self.pending.lock() {
            for (_, tx) in std::mem::take(&mut *pending) {
                let _ = tx.send(Err(CuaError::Unreachable(reason.into())));
            }
        }
    }
}
impl Drop for Connection {
    fn drop(&mut self) {
        self.abort("helper connection closed");
    }
}
