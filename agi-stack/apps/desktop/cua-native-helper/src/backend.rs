use std::{
    path::Path,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
};

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub type Result<T> = std::result::Result<T, NativeError>;

#[derive(Debug, Clone)]
pub struct NativeError {
    pub kind: String,
    pub message: String,
}
impl NativeError {
    pub fn new(kind: &str, message: impl Into<String>) -> Self {
        Self {
            kind: kind.into(),
            message: message.into(),
        }
    }
    pub fn unsupported(capability: &str) -> Self {
        Self::new(
            "capability_unsupported",
            format!("{capability} is unavailable on this native backend"),
        )
    }
}
impl std::fmt::Display for NativeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.kind, self.message)
    }
}
impl std::error::Error for NativeError {}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct App {
    pub id: String,
    pub app_id: String,
    pub display_name: String,
    pub process_id: Option<u32>,
    pub app_path: Option<String>,
    pub identity_digest: String,
    pub is_running: bool,
    #[serde(default)]
    pub windows: Vec<Window>,
    #[cfg(target_os = "windows")]
    #[serde(skip)]
    pub native_registration_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub installed_id: Option<String>,
}
impl App {
    pub fn new(id: String, name: String, pid: Option<u32>, path: Option<String>) -> Self {
        let path = path
            .and_then(|path| std::fs::canonicalize(path).ok())
            .map(|path| path.to_string_lossy().into_owned());
        let identity_digest = path
            .as_deref()
            .and_then(|path| {
                use std::io::Read;
                let mut file = std::fs::File::open(path).ok()?;
                let mut identity = Sha256::new();
                identity.update(path.as_bytes());
                let mut buffer = [0u8; 65536];
                loop {
                    let count = file.read(&mut buffer).ok()?;
                    if count == 0 {
                        break;
                    }
                    identity.update(&buffer[..count]);
                }
                Some(format!("{:x}", identity.finalize()))
            })
            .unwrap_or_default();
        Self {
            app_id: id.clone(),
            id,
            display_name: name,
            process_id: pid,
            app_path: path,
            identity_digest,
            is_running: pid.is_some(),
            windows: Vec::new(),
            #[cfg(target_os = "windows")]
            native_registration_id: None,
            installed_id: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Window {
    pub window_id: String,
    pub app: String,
    pub title: String,
    pub bounds: Rect,
    pub focused: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub modal: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub window_type: Option<String>,
}
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}
impl Rect {
    pub fn point(&self, x: f64, y: f64) -> Result<(f64, f64)> {
        if !x.is_finite()
            || !y.is_finite()
            || x < 0.0
            || y < 0.0
            || x >= self.width
            || y >= self.height
        {
            return Err(NativeError::new(
                "invalid_params",
                "coordinates must lie inside the observed window",
            ));
        }
        Ok((self.x + x, self.y + y))
    }
}

#[derive(Debug, Clone)]
pub struct Observation {
    pub window: Window,
    pub text: String,
    pub screenshot: Option<Value>,
    pub native: Value,
}

pub fn check_cancel(cancel: &AtomicBool) -> Result<()> {
    if cancel.load(Ordering::Acquire) {
        return Err(NativeError::new(
            "user_stopped_session",
            "computer use was stopped",
        ));
    }
    Ok(())
}

#[async_trait]
pub trait Backend: Send + Sync {
    async fn artifact_root(&self) -> Result<std::path::PathBuf> {
        let root =
            std::env::temp_dir().join(format!("memstack-cua-native-{}", uuid::Uuid::new_v4()));
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            std::fs::DirBuilder::new()
                .mode(0o700)
                .create(&root)
                .map_err(|_| NativeError::unsupported("private artifacts"))?;
        }
        #[cfg(target_os = "windows")]
        crate::windows::private_root(&root)?;
        Ok(root)
    }
    async fn capabilities(&self) -> Value;
    async fn permissions(&self) -> Value {
        json!({"accessibility":{"state":"unsupported"},"screen_capture":{"state":"unsupported"},"microphone":{"state":"unsupported"},"system_audio":{"state":"unsupported"},"calendar":{"state":"unsupported"},"contacts":{"state":"unsupported"},"messages":{"state":"unsupported"},"locked_use":{"state":"unsupported"}})
    }
    async fn request_permission(&self, _: &str) -> Result<Value> {
        Err(NativeError::unsupported("native system permission request"))
    }
    async fn apps(&self) -> Result<Vec<App>>;
    async fn resolve(&self, identifier: &str) -> Result<Vec<App>> {
        let pid = identifier
            .strip_prefix("pid:")
            .and_then(|pid| pid.parse::<u32>().ok());
        Ok(self
            .apps()
            .await?
            .into_iter()
            .filter(|app| {
                app.id == identifier || pid.is_some_and(|pid| app.process_id == Some(pid))
            })
            .collect())
    }
    async fn launch(&self, _: &App) -> Result<Value> {
        Err(NativeError::unsupported("installed application launch"))
    }
    async fn app_icon(&self, _: &App, _: Option<&Window>, _: &Path) -> Result<Value> {
        Err(NativeError::unsupported("native application icon"))
    }
    async fn windows(&self, app: &App) -> Result<Vec<Window>>;
    async fn observe(&self, app: &App, window: &Window, root: &Path) -> Result<Observation>;
    async fn activate(&self, window: &Window) -> Result<()>;
    async fn action(
        &self,
        observation: &Observation,
        action: &Value,
        cancel: Arc<AtomicBool>,
    ) -> Result<()>;
    async fn release(&self) {}
    async fn acquire(&self) -> Result<()> {
        Ok(())
    }
    async fn release_session(&self, _: &str) {}
    async fn clipboard(&self, _: &str, _: &str, _: &Value) -> Result<Value> {
        Err(NativeError::unsupported("clipboard"))
    }
    async fn locked(&self) -> Result<bool> {
        Err(NativeError::unsupported("lock detection"))
    }
    async fn audio_start(&self, _: &str, _: &str, _: &Path, _: Arc<AtomicBool>) -> Result<Value> {
        Err(NativeError::unsupported("audio recording"))
    }
    async fn audio_stop(&self, _: &str) -> Result<Value> {
        Err(NativeError::unsupported("audio recording"))
    }
    async fn audio_status(&self, _: &str) -> Result<Value> {
        Ok(json!({"state":"idle"}))
    }
    async fn retain_artifact_root(&self, _: &Path) -> Result<()> {
        Ok(())
    }
}

pub fn platform_backend() -> Arc<dyn Backend> {
    #[cfg(target_os = "windows")]
    {
        return Arc::new(crate::windows::WindowsBackend::new());
    }
    #[cfg(target_os = "linux")]
    {
        return Arc::new(crate::linux::LinuxBackend::new());
    }
    #[cfg(not(any(target_os = "windows", target_os = "linux")))]
    {
        Arc::new(UnsupportedBackend)
    }
}

#[cfg(not(any(target_os = "windows", target_os = "linux")))]
struct UnsupportedBackend;
#[cfg(not(any(target_os = "windows", target_os = "linux")))]
#[async_trait]
impl Backend for UnsupportedBackend {
    async fn capabilities(&self) -> Value {
        json!({"platform":std::env::consts::OS,"capabilities":{"app_state":{"state":"unsupported","reason":"use the platform-specific signed helper"}}})
    }
    async fn apps(&self) -> Result<Vec<App>> {
        Err(NativeError::unsupported("native desktop"))
    }
    async fn windows(&self, _: &App) -> Result<Vec<Window>> {
        Err(NativeError::unsupported("native desktop"))
    }
    async fn observe(&self, _: &App, _: &Window, _: &Path) -> Result<Observation> {
        Err(NativeError::unsupported("native desktop"))
    }
    async fn activate(&self, _: &Window) -> Result<()> {
        Err(NativeError::unsupported("native desktop"))
    }
    async fn action(&self, _: &Observation, _: &Value, _: Arc<AtomicBool>) -> Result<()> {
        Err(NativeError::unsupported("native desktop"))
    }
}

pub fn required<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|text| !text.is_empty())
        .ok_or_else(|| NativeError::new("invalid_params", format!("{key} is required")))
}

#[cfg(test)]
mod identity_tests {
    #[test]
    fn native_code_digest_tracks_bytes_and_canonical_path() {
        let root = tempfile::tempdir().unwrap();
        let code = root.path().join("native-code");
        std::fs::write(&code, b"one").unwrap();
        let app = || {
            super::App::new(
                "pid:1".into(),
                "Fixture".into(),
                Some(1),
                Some(code.to_string_lossy().into_owned()),
            )
        };
        let first = app();
        std::fs::write(&code, b"two").unwrap();
        let second = app();
        assert_ne!(first.identity_digest, second.identity_digest);
        assert_eq!(
            first.app_path,
            Some(code.canonicalize().unwrap().to_string_lossy().into_owned())
        );
        assert!(
            super::App::new("pid:2".into(), "Unknown".into(), Some(2), None)
                .identity_digest
                .is_empty()
        );
    }
}

#[cfg(any(target_os = "windows", target_os = "linux"))]
impl From<sky_cua_platform::BackendError> for NativeError {
    fn from(error: sky_cua_platform::BackendError) -> Self {
        Self::new(&error.code, error.message)
    }
}
