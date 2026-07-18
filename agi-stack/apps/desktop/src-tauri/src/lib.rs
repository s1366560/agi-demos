//! Tauri desktop shell for agi-stack.
//!
//! This is the **PC** platform shell (03-platform-adapters §5): it links the
//! *same* portable [`agistack_core`] with the embedded **device** adapters
//! (`agistack-adapters-device`, SQLite) and exposes `ingest` / `search` /
//! `semantic_search` as Tauri commands to a minimal HTML frontend.
//!
//! Invariant: the core stays runtime-agnostic. Tokio lives only here in the
//! shell (Tauri's async command runtime); the core never names a runtime. The
//! command logic is factored into [`DesktopCore`] so it is unit-testable
//! **headlessly** — without launching a webview — which is exactly what the
//! `#[cfg(test)]` smoke test below does.

use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::Arc,
};

mod local_runtime;
mod trusted_session;

use agistack_adapters_device::{SqliteMemoryRepository, SqliteVectorIndex};
use agistack_adapters_mem::{HashEmbedding, StubLlm, SystemClock};
use agistack_core::{Episode, MemoryService, SourceType};
use local_runtime::{LocalRuntimeConfig, LocalRuntimeService, LocalRuntimeStatus};
use tauri::{
    webview::PageLoadEvent, Manager, RunEvent, State, TitleBarStyle, Url, WebviewUrl,
    WebviewWindowBuilder,
};
use trusted_session::{
    trusted_session_clear, trusted_session_load, trusted_session_save, TrustedSessionBroker,
};
use url::{Host, Position};

/// Embedding width for the on-device hash embedding (toy; Wave F upgrades the
/// vector path to sqlite-vec + a real embedding).
const DIM: usize = 32;

/// The desktop core: the portable [`MemoryService`] wired to SQLite-backed
/// device adapters. Cheap to clone (`Arc`-backed), so commands clone it out of
/// Tauri state before awaiting.
#[derive(Clone)]
pub struct DesktopCore {
    service: MemoryService,
}

impl DesktopCore {
    /// Open (or create) the on-disk SQLite databases at `db_path`.
    pub fn open(db_path: &str) -> Result<Self, String> {
        let repo = Arc::new(SqliteMemoryRepository::open(db_path).map_err(err)?);
        let vectors = Arc::new(SqliteVectorIndex::open(db_path).map_err(err)?);
        Ok(Self::wire(repo, vectors))
    }

    /// In-memory wiring for tests / ephemeral runs.
    pub fn in_memory() -> Result<Self, String> {
        let repo = Arc::new(SqliteMemoryRepository::in_memory().map_err(err)?);
        let vectors = Arc::new(SqliteVectorIndex::in_memory().map_err(err)?);
        Ok(Self::wire(repo, vectors))
    }

    fn wire(repo: Arc<SqliteMemoryRepository>, vectors: Arc<SqliteVectorIndex>) -> Self {
        // SystemClock is the native wall clock (desktop is native, so no wasm
        // gating concern here); the wasm shell injects WasmClock instead.
        let service = MemoryService::new(
            repo,
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(DIM)),
            Arc::new(SystemClock),
        )
        .with_vectors(vectors);
        Self { service }
    }

    /// Ingest an episode; returns the created `Memory` as a JSON string.
    pub async fn ingest(
        &self,
        project_id: &str,
        author_id: &str,
        content: &str,
    ) -> Result<String, String> {
        let episode = Episode {
            content: content.to_string(),
            source_type: SourceType::Text,
            valid_at_ms: 0,
            name: None,
            project_id: Some(project_id.to_string()),
            user_id: None,
        };
        let memory = self
            .service
            .ingest_episode(project_id, author_id, &episode)
            .await
            .map_err(err)?;
        serde_json::to_string(&memory).map_err(err)
    }

    /// Keyword search; returns a JSON array of matching memories.
    pub async fn search(&self, project_id: &str, q: &str, limit: usize) -> Result<String, String> {
        let hits = self
            .service
            .search(project_id, q, limit)
            .await
            .map_err(err)?;
        serde_json::to_string(&hits).map_err(err)
    }

    /// Vector/semantic search; returns a JSON array of matching memories.
    pub async fn semantic_search(
        &self,
        project_id: &str,
        q: &str,
        limit: usize,
    ) -> Result<String, String> {
        let hits = self
            .service
            .semantic_search(project_id, q, limit)
            .await
            .map_err(err)?;
        serde_json::to_string(&hits).map_err(err)
    }
}

fn err<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct ApiBaseUrl(Url);

impl ApiBaseUrl {
    fn parse(raw_url: &str) -> Result<Self, String> {
        if raw_url.chars().any(char::is_whitespace) {
            return Err("API base URL must not include whitespace".to_string());
        }
        let url = Url::parse(raw_url).map_err(|_| "invalid API base URL".to_string())?;
        if !matches!(url.scheme(), "http" | "https") {
            return Err("API base URL must use http or https".to_string());
        }
        if !is_secure_web_url(&url) {
            return Err("API base URL must use https or loopback http".to_string());
        }
        if url.host_str().is_none() {
            return Err("API base URL must include a host".to_string());
        }
        if raw_authority_has_userinfo(raw_url)
            || !url[Position::BeforeUsername..Position::BeforeHost].is_empty()
        {
            return Err("API base URL must not include user info".to_string());
        }
        if url.fragment().is_some() {
            return Err("API base URL must not include a fragment".to_string());
        }
        Ok(Self(url))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DeviceAuthorizationUrl(Url);

impl DeviceAuthorizationUrl {
    fn parse(
        raw_url: &str,
        api_base_url: &ApiBaseUrl,
        expected_user_code: &str,
    ) -> Result<Self, String> {
        validate_device_user_code(expected_user_code)?;
        if raw_url.chars().any(char::is_whitespace) {
            return Err("device authorization URL must not include whitespace".to_string());
        }
        let url =
            Url::parse(raw_url).map_err(|_| "invalid device authorization URL".to_string())?;
        if !matches!(url.scheme(), "http" | "https") {
            return Err("device authorization URL must use http or https".to_string());
        }
        if !is_secure_web_url(&url) {
            return Err("device authorization URL must use https or loopback http".to_string());
        }
        if url.host_str().is_none() {
            return Err("device authorization URL must include a host".to_string());
        }
        if raw_authority_has_userinfo(raw_url)
            || !url[Position::BeforeUsername..Position::BeforeHost].is_empty()
        {
            return Err("device authorization URL must not include user info".to_string());
        }
        if url.path() != "/device" {
            return Err("device authorization URL path must be /device".to_string());
        }
        if url.fragment().is_some() {
            return Err("device authorization URL must not include a fragment".to_string());
        }
        if url.origin() != api_base_url.0.origin() {
            return Err("device authorization URL must use the API origin".to_string());
        }

        let mut query_pairs = url.query_pairs();
        let Some((query_key, user_code)) = query_pairs.next() else {
            return Err("device authorization URL must include user_code".to_string());
        };
        if query_key != "user_code"
            || user_code != expected_user_code
            || query_pairs.next().is_some()
        {
            return Err(
                "device authorization URL must contain exactly the expected user_code".to_string(),
            );
        }

        Ok(Self(url))
    }

    fn as_str(&self) -> &str {
        self.0.as_str()
    }
}

fn is_secure_web_url(url: &Url) -> bool {
    if url.scheme() == "https" {
        return true;
    }
    if url.scheme() != "http" {
        return false;
    }
    match url.host() {
        Some(Host::Domain(host)) => host.eq_ignore_ascii_case("localhost"),
        Some(Host::Ipv4(address)) => address.is_loopback(),
        Some(Host::Ipv6(address)) => address.is_loopback(),
        None => false,
    }
}

fn validate_device_user_code(user_code: &str) -> Result<(), String> {
    const DEVICE_USER_CODE_ALPHABET: &str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    if user_code.len() == 8
        && user_code
            .chars()
            .all(|character| DEVICE_USER_CODE_ALPHABET.contains(character))
    {
        Ok(())
    } else {
        Err("device user code does not match the expected protocol shape".to_string())
    }
}

fn raw_authority_has_userinfo(raw_url: &str) -> bool {
    let trimmed_url = raw_url.trim_matches(char::is_whitespace);
    let Some((_, after_scheme)) = trimmed_url.split_once("://") else {
        return false;
    };
    let authority = after_scheme
        .split(['/', '?', '#'])
        .next()
        .unwrap_or_default();
    authority.contains('@')
}

// Every build uses one native variant, while unit tests exercise all three
// specifications so cross-platform behavior stays reviewable on any host.
#[allow(dead_code)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum OpenerPlatform {
    MacOs,
    Windows,
    Linux,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct OpenerCommandSpec {
    program: &'static str,
    args: Vec<String>,
}

#[cfg(target_os = "macos")]
const CURRENT_OPENER_PLATFORM: OpenerPlatform = OpenerPlatform::MacOs;
#[cfg(target_os = "windows")]
const CURRENT_OPENER_PLATFORM: OpenerPlatform = OpenerPlatform::Windows;
#[cfg(target_os = "linux")]
const CURRENT_OPENER_PLATFORM: OpenerPlatform = OpenerPlatform::Linux;

fn opener_command_spec(
    platform: OpenerPlatform,
    authorization_url: &DeviceAuthorizationUrl,
) -> OpenerCommandSpec {
    let url = authorization_url.as_str().to_string();
    match platform {
        OpenerPlatform::MacOs => OpenerCommandSpec {
            program: "open",
            args: vec![url],
        },
        OpenerPlatform::Windows => OpenerCommandSpec {
            // Avoid `cmd /C start`: cmd.exe would parse metacharacters in the
            // user code even when std::process::Command passes separate args.
            program: "rundll32.exe",
            args: vec!["url.dll,FileProtocolHandler".to_string(), url],
        },
        OpenerPlatform::Linux => OpenerCommandSpec {
            program: "xdg-open",
            args: vec![url],
        },
    }
}

fn launch_device_authorization_url(
    authorization_url: &DeviceAuthorizationUrl,
) -> Result<(), String> {
    let spec = opener_command_spec(CURRENT_OPENER_PLATFORM, authorization_url);
    let mut child = Command::new(spec.program)
        .args(spec.args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("failed to launch device authorization browser: {error}"))?;
    let _ = std::thread::Builder::new()
        .name("device-authorization-opener".to_string())
        .spawn(move || {
            let _ = child.wait();
        });
    Ok(())
}

// --- Tauri commands: thin shells over DesktopCore. ---

#[tauri::command]
async fn ingest(
    core: State<'_, DesktopCore>,
    project_id: String,
    author_id: String,
    content: String,
) -> Result<String, String> {
    let core = core.inner().clone();
    core.ingest(&project_id, &author_id, &content).await
}

#[tauri::command]
async fn search(
    core: State<'_, DesktopCore>,
    project_id: String,
    q: String,
    limit: usize,
) -> Result<String, String> {
    let core = core.inner().clone();
    core.search(&project_id, &q, limit).await
}

#[tauri::command]
async fn semantic_search(
    core: State<'_, DesktopCore>,
    project_id: String,
    q: String,
    limit: usize,
) -> Result<String, String> {
    let core = core.inner().clone();
    core.semantic_search(&project_id, &q, limit).await
}

#[tauri::command]
fn frontend_ready(summary: String) {
    if tauri::is_dev() {
        eprintln!("agistack desktop frontend ready: {summary}");
    }
}

#[tauri::command]
fn local_runtime_status(runtime: State<'_, LocalRuntimeService>) -> LocalRuntimeStatus {
    runtime.status()
}

#[tauri::command]
fn local_runtime_configure(
    runtime: State<'_, LocalRuntimeService>,
    config: LocalRuntimeConfig,
) -> Result<LocalRuntimeStatus, String> {
    runtime.configure(config)
}

#[tauri::command]
fn open_device_authorization_url(
    url: String,
    api_base_url: String,
    expected_user_code: String,
) -> Result<(), String> {
    let api_base_url = ApiBaseUrl::parse(&api_base_url)?;
    let authorization_url =
        DeviceAuthorizationUrl::parse(&url, &api_base_url, &expected_user_code)?;
    launch_device_authorization_url(&authorization_url)
}

fn desktop_db_file_path(app_data_dir: &Path) -> PathBuf {
    app_data_dir.join("agistack-desktop.db")
}

fn default_local_workspace_root() -> PathBuf {
    if let Ok(root) = std::env::var("AGISTACK_WORKSPACE_ROOT") {
        return PathBuf::from(root);
    }
    let Ok(mut dir) = std::env::current_dir() else {
        return PathBuf::from(".");
    };
    loop {
        if dir.join("AGENTS.md").exists() || dir.join(".git").exists() {
            return dir;
        }
        if !dir.pop() {
            return std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        }
    }
}

fn setup_error(message: String) -> Box<dyn std::error::Error> {
    Box::new(std::io::Error::other(message))
}

fn main_window_url() -> Result<WebviewUrl, Box<dyn std::error::Error>> {
    if tauri::is_dev() {
        let url =
            Url::parse("http://127.0.0.1:5173/").map_err(|error| setup_error(error.to_string()))?;
        Ok(WebviewUrl::External(url))
    } else {
        Ok(WebviewUrl::App("index.html".into()))
    }
}

fn tauri_runtime_marker_script() -> &'static str {
    r#"
      (() => {
        document.documentElement.dataset.runtimeShell = 'tauri';
        document.documentElement.setAttribute('data-tauri-window', 'true');
      })()
    "#
}

fn mark_tauri_runtime(window: &tauri::WebviewWindow) {
    if let Err(error) = window.eval(tauri_runtime_marker_script()) {
        eprintln!("failed to mark agistack desktop runtime: {error}");
    }
}

fn frontend_dom_probe_script() -> &'static str {
    r#"
      (() => {
        document.documentElement.dataset.runtimeShell = 'tauri';
        document.documentElement.setAttribute('data-tauri-window', 'true');

        const elementProbe = (selector) => {
          const element = document.querySelector(selector);
          if (!element) return null;
          const rect = element.getBoundingClientRect();
          const style = window.getComputedStyle(element);
          const centerX = rect.left + rect.width / 2;
          const centerY = rect.top + rect.height / 2;
          const topElement = document.elementFromPoint(centerX, centerY);
          return {
            selector,
            rect: {
              x: Math.round(rect.x),
              y: Math.round(rect.y),
              width: Math.round(rect.width),
              height: Math.round(rect.height),
            },
            display: style.display,
            visibility: style.visibility,
            opacity: style.opacity,
            overflow: style.overflow,
            background: style.backgroundColor,
            topElement: topElement
              ? {
                tag: topElement.tagName,
                className: String(topElement.className || ''),
                ariaLabel: topElement.getAttribute('aria-label'),
                text: topElement.textContent?.replace(/\s+/g, ' ').trim().slice(0, 80) ?? '',
              }
              : null,
          };
        };

        const summarize = (phase, extra = {}) => ({
          phase,
          title: document.title,
          text: document.body?.innerText?.replace(/\s+/g, ' ').trim().slice(0, 240) ?? '',
          rootChildren: document.getElementById('root')?.childElementCount ?? 0,
          hasLoginScreen: Boolean(document.querySelector('.desktop-login-screen')),
          hasAppShell: Boolean(document.querySelector('.app-shell')),
          hasSettingsWindow: Boolean(document.querySelector('.settings-window-dialog')),
          hasFatalError: Boolean(document.querySelector('.app-fatal-error')),
          hasTauriGlobal: Boolean(window.__TAURI__ || window.__TAURI_INTERNALS__),
          loginScreen: elementProbe('.desktop-login-screen'),
          appShell: elementProbe('.app-shell'),
          settingsWindow: elementProbe('.settings-window-dialog'),
          ...extra,
        });

        const report = (summary) => {
          const invoke = window.__TAURI__?.core?.invoke;
          if (invoke) {
            void invoke('frontend_ready', { summary: JSON.stringify(summary) });
          }
        };

        setTimeout(async () => {
          let summary = summarize('probe');
          if (
            !summary.hasLoginScreen &&
            !summary.hasAppShell &&
            location.hostname === '127.0.0.1'
          ) {
            try {
              await import('/src/main.tsx');
              summary = summarize('probe-after-dev-import');
            } catch (error) {
              summary = summarize('probe-import-failed', {
                importError: String(error?.stack || error?.message || error),
              });
            }
          }
          report(summary);
        }, 750);
      })()
    "#
}

fn probe_frontend_dom(window: &tauri::WebviewWindow) {
    if !tauri::is_dev() {
        return;
    }

    if let Err(error) = window.eval(frontend_dom_probe_script()) {
        eprintln!("failed to probe agistack desktop dom: {error}");
    }
}

fn ensure_main_window(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let window = if let Some(window) = app.get_webview_window("main") {
        window
    } else {
        let url = main_window_url()?;
        WebviewWindowBuilder::new(app, "main", url)
            .title("agi-stack Desktop")
            .title_bar_style(TitleBarStyle::Visible)
            .hidden_title(false)
            .inner_size(1728.0, 1024.0)
            .min_inner_size(1080.0, 720.0)
            .center()
            .visible(true)
            .focused(true)
            .on_page_load(|window, payload| {
                if tauri::is_dev() {
                    eprintln!(
                        "agistack desktop page load {:?} {}",
                        payload.event(),
                        payload.url()
                    );
                }
                if matches!(payload.event(), PageLoadEvent::Finished) {
                    mark_tauri_runtime(&window);
                    probe_frontend_dom(&window);
                }
            })
            .build()?
    };
    window.set_title("agi-stack Desktop")?;
    window.show()?;
    app.show()?;
    window.set_focus()?;
    mark_tauri_runtime(&window);
    probe_frontend_dom(&window);
    Ok(())
}

#[cfg(target_os = "macos")]
fn should_restore_main_window(has_visible_windows: bool) -> bool {
    !has_visible_windows
}

fn handle_run_event(app: &tauri::AppHandle, event: RunEvent) {
    match event {
        RunEvent::Ready => {
            if let Err(error) = ensure_main_window(app) {
                eprintln!("failed to create agistack desktop window: {error}");
            }
        }
        #[cfg(target_os = "macos")]
        RunEvent::Reopen {
            has_visible_windows,
            ..
        } if should_restore_main_window(has_visible_windows) => {
            if let Err(error) = ensure_main_window(app) {
                eprintln!("failed to restore agistack desktop window: {error}");
            }
        }
        _ => {}
    }
}

fn open_app_data_core(app: &tauri::AppHandle) -> Result<DesktopCore, Box<dyn std::error::Error>> {
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| setup_error(error.to_string()))?;
    std::fs::create_dir_all(&app_data_dir)?;
    let db_path = desktop_db_file_path(&app_data_dir)
        .to_string_lossy()
        .into_owned();
    DesktopCore::open(&db_path).map_err(setup_error)
}

/// Launch the desktop app. The SQLite store lives under the OS app-data
/// directory so production runs do not create `agistack-desktop.db` in the
/// process working directory.
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_data_dir = app
                .path()
                .app_data_dir()
                .map_err(|error| setup_error(error.to_string()))?;
            std::fs::create_dir_all(&app_data_dir)?;
            let core = open_app_data_core(app.handle())?;
            let local_runtime = tauri::async_runtime::block_on(LocalRuntimeService::start(
                app_data_dir,
                default_local_workspace_root(),
            ))
            .map_err(setup_error)?;
            app.manage(core);
            app.manage(local_runtime);
            app.manage(TrustedSessionBroker::native());
            ensure_main_window(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ingest,
            search,
            semantic_search,
            frontend_ready,
            local_runtime_status,
            local_runtime_configure,
            open_device_authorization_url,
            trusted_session_save,
            trusted_session_load,
            trusted_session_clear
        ])
        .build(tauri::generate_context!())
        .expect("error while building the agistack desktop application")
        .run(handle_run_event);
}

#[cfg(test)]
mod tests {
    use super::*;

    // Headless proof: the desktop wiring (core + SQLite device adapters) runs a
    // full ingest -> keyword search -> semantic search round-trip WITHOUT a
    // webview. This is the "headless fallback" called out in 05-roadmap §4.4.
    #[test]
    fn desktop_db_file_path_uses_app_data_dir() {
        let app_data = PathBuf::from("app-data");
        assert_eq!(
            desktop_db_file_path(&app_data),
            app_data.join("agistack-desktop.db")
        );
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn macos_reopen_restores_window_only_when_none_are_visible() {
        assert!(should_restore_main_window(false));
        assert!(!should_restore_main_window(true));
    }

    #[test]
    fn tauri_runtime_marker_sets_native_shell_attributes() {
        let script = tauri_runtime_marker_script();
        assert!(script.contains("dataset.runtimeShell = 'tauri'"));
        assert!(script.contains("data-tauri-window"));
    }

    #[test]
    fn frontend_probe_tracks_current_auth_and_workspace_surfaces() {
        let script = frontend_dom_probe_script();
        assert!(script.contains(".desktop-login-screen"));
        assert!(script.contains(".app-shell"));
        assert!(script.contains(".settings-window-dialog"));
        assert!(!script.contains(".signed-out-"));
    }

    #[test]
    fn device_authorization_url_accepts_only_the_device_endpoint() {
        for (api_base_url, raw_url) in [
            (
                "https://auth.example.com/api/v1",
                "https://auth.example.com/device?user_code=ABCDEFGH",
            ),
            (
                "http://127.0.0.1:8000/api/v1",
                "http://127.0.0.1:8000/device?user_code=ABCD2345",
            ),
            (
                "http://[::1]:8000/api/v1",
                "http://[::1]:8000/device?user_code=ABCD2345",
            ),
            (
                "https://auth.example.com:443/api/v1",
                "https://auth.example.com/device?user_code=ABCDEFGH",
            ),
        ] {
            let api_base_url = ApiBaseUrl::parse(api_base_url).expect("valid API base URL");
            let expected_user_code = raw_url
                .split("user_code=")
                .nth(1)
                .expect("test URL includes user code");
            let authorization_url =
                DeviceAuthorizationUrl::parse(raw_url, &api_base_url, expected_user_code)
                    .expect("valid device authorization URL");

            assert_eq!(authorization_url.as_str(), raw_url);
        }
    }

    #[test]
    fn device_authorization_url_rejects_unsafe_url_components() {
        let api_base_url =
            ApiBaseUrl::parse("https://auth.example.com/api/v1").expect("valid API base URL");
        for raw_url in [
            "file:///device",
            "javascript:alert(1)",
            "https://auth.example.com/",
            "https://auth.example.com/device",
            "https://auth.example.com/device?user_code=",
            "https://auth.example.com/device/",
            "https://auth.example.com/other/device",
            "https://user@auth.example.com/device",
            "https://:secret@auth.example.com/device",
            "https://@auth.example.com/device",
            "https:\t//@auth.example.com/device",
            "https://auth.example.com/device#fragment",
            "https://auth.example.com/device#",
            "https://auth.example.com/device?redirect_uri=https%3A%2F%2Fevil.example",
            "https://auth.example.com/device?user_code=ABCDEFGJ",
            "https://auth.example.com/device?user_code=one&user_code=two",
        ] {
            assert!(
                DeviceAuthorizationUrl::parse(raw_url, &api_base_url, "ABCDEFGH").is_err(),
                "unsafe URL must be rejected: {raw_url}"
            );
        }
    }

    #[test]
    fn device_authorization_url_rejects_a_different_origin() {
        let api_base_url =
            ApiBaseUrl::parse("https://auth.example.com:8443/api/v1").expect("valid API base URL");

        for raw_url in [
            "http://auth.example.com:8443/device",
            "https://login.example.com:8443/device",
            "https://auth.example.com:9443/device",
        ] {
            assert!(
                DeviceAuthorizationUrl::parse(raw_url, &api_base_url, "ABCDEFGH").is_err(),
                "cross-origin URL must be rejected: {raw_url}"
            );
        }
    }

    #[test]
    fn api_base_url_rejects_unsafe_url_components() {
        for raw_url in [
            "file:///api/v1",
            "javascript:alert(1)",
            "https://user@auth.example.com/api/v1",
            "https://@auth.example.com/api/v1",
            "https:\t//@auth.example.com/api/v1",
            "https://auth.example.com/api/v1#fragment",
            "https://auth.example.com/api/v1#",
            "http://auth.example.com/api/v1",
        ] {
            assert!(
                ApiBaseUrl::parse(raw_url).is_err(),
                "unsafe API base URL must be rejected: {raw_url}"
            );
        }
    }

    #[test]
    fn opener_command_specs_are_cross_platform_and_shell_free() {
        let api_base_url =
            ApiBaseUrl::parse("https://auth.example.com/api/v1").expect("valid API base URL");
        let authorization_url = DeviceAuthorizationUrl::parse(
            "https://auth.example.com/device?user_code=ABCDEFGH",
            &api_base_url,
            "ABCDEFGH",
        )
        .expect("valid device authorization URL");

        assert_eq!(
            opener_command_spec(OpenerPlatform::MacOs, &authorization_url),
            OpenerCommandSpec {
                program: "open",
                args: vec![authorization_url.as_str().to_string()],
            }
        );
        assert_eq!(
            opener_command_spec(OpenerPlatform::Linux, &authorization_url),
            OpenerCommandSpec {
                program: "xdg-open",
                args: vec![authorization_url.as_str().to_string()],
            }
        );
        assert_eq!(
            opener_command_spec(OpenerPlatform::Windows, &authorization_url),
            OpenerCommandSpec {
                program: "rundll32.exe",
                args: vec![
                    "url.dll,FileProtocolHandler".to_string(),
                    authorization_url.as_str().to_string(),
                ],
            }
        );
    }

    #[test]
    fn default_capability_allows_drag_regions() {
        let capability: serde_json::Value =
            serde_json::from_str(include_str!("../capabilities/default.json"))
                .expect("valid default capability");
        let windows = capability["windows"].as_array().expect("windows array");
        let permissions = capability["permissions"]
            .as_array()
            .expect("permissions array");

        assert!(
            windows.iter().any(|window| window == "main"),
            "default capability must cover the main desktop window"
        );
        assert!(
            permissions
                .iter()
                .any(|permission| permission == "core:window:allow-start-dragging"),
            "data-tauri-drag-region requires start_dragging permission at runtime"
        );
    }

    #[test]
    fn tauri_config_defers_main_window_creation_to_rust() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).expect("valid tauri config");
        let main_window = config["app"]["windows"]
            .as_array()
            .expect("windows array")
            .iter()
            .find(|window| window["label"] == "main")
            .expect("main window config");

        assert_eq!(
            main_window["create"], false,
            "Rust ensure_main_window owns native window creation so dev/prod use the same visible path"
        );
        assert_eq!(
            main_window["titleBarStyle"], "Visible",
            "use the standard native titlebar so window controls stay outside the app chrome"
        );
        assert_eq!(
            main_window["hiddenTitle"], false,
            "the native title is visible in the single system titlebar"
        );
    }

    #[test]
    fn desktop_core_round_trip_headless() {
        // A tiny single-threaded executor — no tokio in the test, mirroring the
        // core's runtime-agnostic contract.
        let core = DesktopCore::in_memory().expect("in-memory wiring");
        futures::executor::block_on(async {
            let created = core
                .ingest(
                    "p1",
                    "u1",
                    "Local-first desktop apps persist data in sqlite",
                )
                .await
                .expect("ingest");
            assert!(created.contains("\"id\""), "ingest returns a memory json");

            let hits: serde_json::Value =
                serde_json::from_str(&core.search("p1", "sqlite", 10).await.unwrap()).unwrap();
            assert_eq!(hits.as_array().unwrap().len(), 1, "keyword hit");

            let miss: serde_json::Value =
                serde_json::from_str(&core.search("p1", "postgres", 10).await.unwrap()).unwrap();
            assert!(miss.as_array().unwrap().is_empty(), "keyword miss");

            let sem: serde_json::Value = serde_json::from_str(
                &core
                    .semantic_search("p1", "on-device storage", 5)
                    .await
                    .unwrap(),
            )
            .unwrap();
            assert!(!sem.as_array().unwrap().is_empty(), "semantic hit");
        });
    }
}
