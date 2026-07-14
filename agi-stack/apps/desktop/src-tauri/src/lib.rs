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
    sync::Arc,
};

mod local_runtime;

use agistack_adapters_device::{SqliteMemoryRepository, SqliteVectorIndex};
use agistack_adapters_mem::{HashEmbedding, StubLlm, SystemClock};
use agistack_core::{Episode, MemoryService, SourceType};
use local_runtime::{LocalRuntimeConfig, LocalRuntimeService, LocalRuntimeStatus};
use tauri::{
    webview::PageLoadEvent, Manager, RunEvent, State, TitleBarStyle, Url, WebviewUrl,
    WebviewWindowBuilder,
};

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

fn probe_frontend_dom(window: &tauri::WebviewWindow) {
    if !tauri::is_dev() {
        return;
    }

    let js = r#"
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
          hasAppShell: Boolean(document.querySelector('.app-shell')),
          hasFatalError: Boolean(document.querySelector('.app-fatal-error')),
          hasTauriGlobal: Boolean(window.__TAURI__ || window.__TAURI_INTERNALS__),
          signedOutDock: elementProbe('.signed-out-dock'),
          signedOutWorkflows: elementProbe('.signed-out-workflows'),
          signedOutComposer: elementProbe('.signed-out-composer'),
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
          if (!summary.hasAppShell && location.hostname === '127.0.0.1') {
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
    "#;

    if let Err(error) = window.eval(js) {
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
            ensure_main_window(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ingest,
            search,
            semantic_search,
            frontend_ready,
            local_runtime_status,
            local_runtime_configure
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
