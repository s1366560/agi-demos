use super::*;
use std::path::Path;

pub(crate) fn root_identity(path: &Path) -> Result<(u64, u64)> {
    #[cfg(any(target_os = "windows", target_os = "linux"))]
    {
        crate::input_guardian::Root::identity(path)
    }
    #[cfg(all(unix, not(target_os = "linux")))]
    {
        use std::os::unix::fs::MetadataExt;
        let metadata = std::fs::symlink_metadata(path)
            .map_err(|_| NativeError::unsupported("private artifacts"))?;
        if !metadata.is_dir() || metadata.file_type().is_symlink() {
            return Err(NativeError::unsupported("private artifacts"));
        }
        Ok((metadata.dev(), metadata.ino()))
    }
}
fn clear_artifacts(
    session: &Session,
    retained: &std::collections::BTreeSet<std::path::PathBuf>,
) -> Result<()> {
    if root_identity(&session.root)? != session.root_identity {
        return Err(NativeError::new(
            "artifact_identity_changed",
            "private session directory identity changed",
        ));
    }
    let entries = std::fs::read_dir(&session.root)
        .map_err(|_| NativeError::unsupported("private artifact cleanup"))?;
    for entry in entries {
        let entry = entry.map_err(|_| NativeError::unsupported("private artifact cleanup"))?;
        // Generated capture/audio/icon files are direct children. Never traverse a link or directory.
        let kind = entry
            .file_type()
            .map_err(|_| NativeError::unsupported("private artifact cleanup"))?;
        if (kind.is_file() || kind.is_symlink()) && !retained.contains(&entry.path()) {
            std::fs::remove_file(entry.path())
                .map_err(|_| NativeError::unsupported("private artifact cleanup"))?;
        }
    }
    Ok(())
}
impl Sessions {
    pub(super) async fn suspend(
        &self,
        method: &str,
        id: &str,
        session: &Arc<Mutex<Session>>,
        reason: &str,
    ) -> Result<Value> {
        let owner = session.lock().await.context.clone();
        self.audio.request_end(&owner, reason).await;
        {
            let mut state = session.lock().await;
            if matches!(method, "pause_session" | "cancel") && state.phase == Phase::Stopped {
                return Err(NativeError::new(
                    "user_stopped_session",
                    "stopped native sessions cannot be paused or resumed",
                ));
            }
            state.phase = match method {
                "pause_session" => Phase::Pausing,
                "cancel" => state.phase,
                _ => Phase::Stopped,
            };
            state.cancel.store(true, Ordering::Release);
            state.snapshot = None;
        }
        self.cancel(id).await;
        // Cancellation reaches the old operation before this lock. Cleanup finishes before resume can rearm.
        let _operation = self.operation.lock().await;
        let audio = self.audio.stop(&owner, None, reason).await?;
        let retained = self.audio.retained(&owner).await;
        self.backend.release_session(id).await;
        let cleanup = {
            let mut state = session.lock().await;
            state.snapshot = None;
            let result = clear_artifacts(&state, &retained);
            if result.is_ok() && state.phase == Phase::Pausing {
                state.phase = Phase::Paused;
            }
            result
        };
        if method == "end_session" {
            self.sessions.lock().await.remove(id);
            self.closed.lock().await.insert(id.into(), session.clone());
        }
        cleanup?;
        if matches!(method, "pause_session" | "cancel")
            && session.lock().await.phase == Phase::Stopped
        {
            return Err(NativeError::new(
                "user_stopped_session",
                "terminal stop superseded this pause",
            ));
        }
        let phase = match session.lock().await.phase {
            Phase::Stopped => "stopped",
            Phase::Paused | Phase::Pausing => "paused",
            Phase::Active => "cancelled",
        };
        Ok(json!({"ok":true,"phase":phase,"recordings":audio["recordings"]}))
    }
    pub(super) async fn resume(&self, session: &Arc<Mutex<Session>>) -> Result<Value> {
        let mut state = session.lock().await;
        match state.phase {
            Phase::Stopped => Err(NativeError::new(
                "user_stopped_session",
                "stopped native sessions cannot be resumed",
            )),
            Phase::Pausing => Err(NativeError::new(
                "session_pausing",
                "native cleanup is still completing",
            )),
            Phase::Active => Err(NativeError::new(
                "session_not_paused",
                "only a paused native session can be resumed",
            )),
            Phase::Paused => {
                state.phase = Phase::Active;
                state.input_generation = uuid::Uuid::new_v4().to_string();
                state.snapshot = None;
                state.cancel = Arc::new(AtomicBool::new(false));
                Ok(
                    json!({"ok":true,"phase":"idle","requires_observation":true,"input_mode":state.context.input_mode,"input_generation":state.input_generation}),
                )
            }
        }
    }
}
