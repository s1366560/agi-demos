//! Recording generations and durable-export receipts, independent of input leases.
use crate::{
    backend::{Backend, NativeError, Result},
    session::Context,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    sync::{Arc, atomic::AtomicBool},
};
use tokio::sync::Mutex;

struct Recording {
    owner: Context,
    root: PathBuf,
    root_identity: (u64, u64),
    started: DateTime<Utc>,
    receipt: Value,
    files: BTreeSet<PathBuf>,
    requested_end_reason: Option<String>,
}
pub struct Recordings {
    backend: Arc<dyn Backend>,
    state: Mutex<BTreeMap<String, Recording>>,
    gate: Mutex<()>,
}
impl Recordings {
    pub fn new(backend: Arc<dyn Backend>) -> Self {
        Self {
            backend,
            state: Mutex::new(BTreeMap::new()),
            gate: Mutex::new(()),
        }
    }
    pub async fn start(
        self: &Arc<Self>,
        owner: Context,
        source: &str,
        root: &Path,
        cancel: Arc<AtomicBool>,
    ) -> Result<Value> {
        let _gate = self.gate.lock().await;
        if !matches!(source, "microphone" | "system" | "mixed") {
            return Err(NativeError::new(
                "invalid_params",
                "invalid recording source",
            ));
        }
        {
            let state = self.state.lock().await;
            if state
                .values()
                .any(|recording| recording.receipt["status"] == "recording")
            {
                return Err(NativeError::new(
                    "audio_busy",
                    "another recording owns the audio devices",
                ));
            }
            if state
                .values()
                .filter(|recording| recording.owner == owner)
                .count()
                >= 128
            {
                return Err(NativeError::new(
                    "audio_receipt_limit",
                    "recording receipt limit reached",
                ));
            }
        }
        let id = uuid::Uuid::new_v4().to_string();
        let started = Utc::now();
        self.state.lock().await.insert(id.clone(), Recording {
            owner: owner.clone(), root: root.into(), root_identity: crate::session::lifecycle::root_identity(root)?, started,
            receipt: json!({"recording_id":id,"source":source,"status":"recording","started_at":started.to_rfc3339(),"artifacts":[]}),
            files: BTreeSet::new(), requested_end_reason: None,
        });
        if let Err(error) = self.backend.audio_start(&id, source, root, cancel).await {
            self.finish(&id, "start_failed", Some(error.kind.clone()))
                .await;
            return Err(error);
        }
        let weak = Arc::downgrade(self);
        let watched = id.clone();
        tokio::spawn(async move {
            loop {
                tokio::time::sleep(std::time::Duration::from_millis(100)).await;
                let Some(recordings) = weak.upgrade() else {
                    return;
                };
                let _gate = recordings.gate.lock().await;
                if recordings
                    .state
                    .lock()
                    .await
                    .get(&watched)
                    .is_none_or(|recording| recording.receipt["status"] != "recording")
                {
                    return;
                }
                let status = recordings.backend.audio_status(&watched).await;
                match status {
                    Ok(status) if status["recording"] == true => {}
                    Ok(status) => {
                        recordings
                            .finish(
                                &watched,
                                status["end_reason"].as_str().unwrap_or("capture_ended"),
                                status["error_code"].as_str().map(str::to_owned),
                            )
                            .await;
                        return;
                    }
                    Err(error) => {
                        recordings
                            .finish(&watched, "capture_error", Some(error.kind))
                            .await;
                        return;
                    }
                }
            }
        });
        self.status(&owner, Some(&id)).await
    }
    pub async fn status(&self, owner: &Context, id: Option<&str>) -> Result<Value> {
        let state = self.state.lock().await;
        if id.is_some_and(|id| {
            state
                .get(id)
                .is_none_or(|recording| recording.owner != *owner)
        }) {
            return Err(NativeError::new(
                "recording_not_found",
                "recording does not belong to this session",
            ));
        }
        let mut values = state
            .iter()
            .filter(|(key, recording)| {
                recording.owner == *owner && id.is_none_or(|id| id == key.as_str())
            })
            .map(|(_, recording)| {
                let mut receipt = recording.receipt.clone();
                if receipt["status"] == "recording" {
                    receipt["elapsed_ms"] =
                        json!((Utc::now() - recording.started).num_milliseconds().max(0));
                }
                receipt
            })
            .collect::<Vec<_>>();
        values.sort_by(|left, right| {
            left["started_at"]
                .as_str()
                .cmp(&right["started_at"].as_str())
        });
        let active = values
            .iter()
            .any(|receipt| receipt["status"] == "recording");
        let artifacts = values
            .iter()
            .flat_map(|receipt| {
                receipt["artifacts"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .cloned()
            })
            .collect::<Vec<_>>();
        let mut result = json!({"recordings":values,"recording":active,"artifacts":artifacts});
        if result["recordings"]
            .as_array()
            .is_some_and(|values| values.iter().any(|value| value["partial"] == true))
        {
            result["partial"] = json!(true);
        }
        if result["recordings"]
            .as_array()
            .is_some_and(|values| values.len() == 1)
        {
            result["recording_id"] = result["recordings"][0]["recording_id"].clone();
            result["source"] = result["recordings"][0]["source"].clone();
        }
        Ok(result)
    }
    pub async fn stop(&self, owner: &Context, id: Option<&str>, reason: &str) -> Result<Value> {
        let _gate = self.gate.lock().await;
        let values = self.status(owner, id).await?;
        for receipt in values["recordings"].as_array().into_iter().flatten() {
            if let Some(id) = receipt["recording_id"].as_str() {
                self.finish(id, reason, None).await;
            }
        }
        self.status(owner, id).await
    }
    pub async fn request_end(&self, owner: &Context, reason: &str) {
        let mut state = self.state.lock().await;
        for recording in state.values_mut().filter(|recording| {
            recording.owner == *owner && recording.receipt["status"] == "recording"
        }) {
            if recording.requested_end_reason.is_none() {
                recording.requested_end_reason = Some(reason.into());
            }
        }
    }
    /// Gate held: raw stop closes every device before exporting or acknowledging files.
    async fn finish(&self, id: &str, reason: &str, error: Option<String>) {
        {
            let mut state = self.state.lock().await;
            let Some(recording) = state
                .get_mut(id)
                .filter(|recording| recording.receipt["status"] == "recording")
            else {
                return;
            };
            recording.receipt["status"] = json!("stopping");
        }
        let result = self.backend.audio_stop(id).await;
        let mut error = error;
        let mut artifacts = Vec::new();
        let mut sources = Vec::new();
        let mut end_reason = reason.to_owned();
        match result {
            Ok(result) => {
                artifacts = normalize_artifacts(&result);
                sources = result["source_artifacts"]
                    .as_array()
                    .cloned()
                    .unwrap_or_default();
                error = error.or_else(|| result["error_code"].as_str().map(str::to_owned));
                if reason == "capture_ended" {
                    end_reason = result["end_reason"].as_str().unwrap_or(reason).to_owned();
                }
            }
            Err(failure) => {
                error = error.or(Some(failure.kind));
            }
        }
        let root = self
            .state
            .lock()
            .await
            .get(id)
            .map(|recording| recording.root.clone());
        let Some(root) = root else {
            return;
        };
        let mut files = BTreeSet::new();
        artifacts.retain(|artifact| owned_path(artifact, &root).is_some());
        for artifact in artifacts.iter().chain(sources.iter()) {
            if let Some(path) = owned_path(artifact, &root) {
                files.insert(path);
            }
        }
        if !artifacts.is_empty() {
            if let Err(failure) = self.backend.retain_artifact_root(&root).await {
                error = error.or(Some(failure.kind));
            }
        } else {
            error = error.or(Some("audio_empty".into()));
        }
        if error.is_some() {
            for artifact in &mut artifacts {
                artifact["partial"] = json!(true);
            }
        }
        let mut state = self.state.lock().await;
        if let Some(recording) = state.get_mut(id) {
            let ended = Utc::now();
            recording.files = files;
            recording.receipt["status"] = json!(if artifacts.is_empty() {
                "failed"
            } else {
                "pending_export"
            });
            recording.receipt["artifacts"] = json!(artifacts);
            recording.receipt["ended_at"] = json!(ended.to_rfc3339());
            recording.receipt["elapsed_ms"] =
                json!((ended - recording.started).num_milliseconds().max(0));
            recording.receipt["end_reason"] =
                json!(recording.requested_end_reason.take().unwrap_or(end_reason));
            if let Some(error) = error {
                recording.receipt["error_code"] = json!(error);
            }
            if recording.receipt.get("error_code").is_some()
                && recording.receipt["status"] == "pending_export"
            {
                recording.receipt["partial"] = json!(true);
            }
        }
    }
    pub async fn retained(&self, owner: &Context) -> BTreeSet<PathBuf> {
        self.state
            .lock()
            .await
            .values()
            .filter(|recording| recording.owner == *owner && recording.receipt["status"] != "saved")
            .flat_map(|recording| recording.files.iter().cloned())
            .collect()
    }
    pub async fn acknowledge(&self, owner: &Context, id: &str) -> Result<Value> {
        let _gate = self.gate.lock().await;
        self.status(owner, Some(id)).await?;
        {
            let mut state = self.state.lock().await;
            let recording = state.get_mut(id).ok_or_else(|| {
                NativeError::new("recording_not_found", "recording is unavailable")
            })?;
            if matches!(
                recording.receipt["status"].as_str(),
                Some("recording" | "stopping")
            ) {
                return Err(NativeError::new(
                    "recording_active",
                    "active recording cannot be acknowledged",
                ));
            }
            if recording.receipt["status"] != "saved" {
                if crate::session::lifecycle::root_identity(&recording.root)?
                    != recording.root_identity
                {
                    return Err(NativeError::new(
                        "artifact_identity_changed",
                        "recording directory changed",
                    ));
                }
                for path in &recording.files {
                    if path.exists() {
                        std::fs::remove_file(path).map_err(|_| {
                            NativeError::new(
                                "audio_cleanup_failed",
                                "cannot acknowledge recording files",
                            )
                        })?;
                    }
                }
                recording.files.clear();
                recording.receipt["status"] = json!("saved");
                recording.receipt["artifacts"] = json!([]);
            }
        }
        self.status(owner, Some(id)).await
    }
}
pub(crate) fn normalize_artifacts(output: &Value) -> Vec<Value> {
    let mut artifacts = output["artifacts"].as_array().cloned().unwrap_or_else(|| {
        output
            .get("artifact")
            .filter(|artifact| artifact.is_object())
            .cloned()
            .into_iter()
            .collect()
    });
    for artifact in &mut artifacts {
        artifact["kind"] = json!("audio");
    }
    artifacts
}
fn owned_path(artifact: &Value, root: &Path) -> Option<PathBuf> {
    if artifact["mime_type"] != "audio/wav" {
        return None;
    }
    let path = url::Url::parse(artifact["url"].as_str()?)
        .ok()?
        .to_file_path()
        .ok()?;
    let metadata = std::fs::symlink_metadata(&path).ok()?;
    (path.parent() == Some(root)
        && metadata.is_file()
        && !metadata.file_type().is_symlink()
        && metadata.len() > 44
        && metadata.len() <= 64 * 1024 * 1024)
        .then_some(path)
}
