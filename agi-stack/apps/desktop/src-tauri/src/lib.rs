//! Tauri shell for the MemStack Mission Control desktop client.
//!
//! The shell owns native window lifecycle, project-scoped local runtime state,
//! trusted-session persistence, and secure device-authorization browser launch.

use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

mod application_vault;
mod local_runtime;
mod trusted_session;

use application_vault::ApplicationCredentialVault;
use local_runtime::{LocalRuntimeConfig, LocalRuntimeService, LocalRuntimeStatus};
use tauri::{
    webview::PageLoadEvent, Manager, RunEvent, State, TitleBarStyle, Url, WebviewUrl,
    WebviewWindowBuilder,
};
use trusted_session::{
    local_trusted_session_clear, local_trusted_session_load, local_trusted_session_save,
    trusted_session_clear, trusted_session_load, trusted_session_save, TrustedSessionBroker,
};
use url::{Host, Position};

#[derive(Debug, Clone, PartialEq, Eq)]
struct DeviceAuthorizationBaseUrl(Url);

impl DeviceAuthorizationBaseUrl {
    fn parse(raw_url: &str) -> Result<Self, String> {
        if raw_url.chars().any(char::is_whitespace) {
            return Err("authorization portal URL must not include whitespace".to_string());
        }
        let url =
            Url::parse(raw_url).map_err(|_| "invalid authorization portal URL".to_string())?;
        if !matches!(url.scheme(), "http" | "https") {
            return Err("authorization portal URL must use http or https".to_string());
        }
        if !is_secure_web_url(&url) {
            return Err("authorization portal URL must use https or loopback http".to_string());
        }
        if url.host_str().is_none() {
            return Err("authorization portal URL must include a host".to_string());
        }
        if raw_authority_has_userinfo(raw_url)
            || !url[Position::BeforeUsername..Position::BeforeHost].is_empty()
        {
            return Err("authorization portal URL must not include user info".to_string());
        }
        if url.fragment().is_some() {
            return Err("authorization portal URL must not include a fragment".to_string());
        }
        Ok(Self(url))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DeviceAuthorizationUrl(Url);

impl DeviceAuthorizationUrl {
    fn parse(
        raw_url: &str,
        authorization_base_url: &DeviceAuthorizationBaseUrl,
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
        if url.origin() != authorization_base_url.0.origin() {
            return Err(
                "device authorization URL must use the authorization portal origin".to_string(),
            );
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
    device_authorization_base_url: String,
    expected_user_code: String,
) -> Result<(), String> {
    let authorization_base_url = DeviceAuthorizationBaseUrl::parse(&device_authorization_base_url)?;
    let authorization_url =
        DeviceAuthorizationUrl::parse(&url, &authorization_base_url, &expected_user_code)?;
    launch_device_authorization_url(&authorization_url)
}

fn default_local_workspace_root() -> PathBuf {
    if let Ok(root) = std::env::var("AGISTACK_WORKSPACE_ROOT") {
        return PathBuf::from(root);
    }
    let user_home = std::env::var_os("HOME").map(PathBuf::from);
    let launch_directory = std::env::current_dir()
        .unwrap_or_else(|_| user_home.clone().unwrap_or_else(|| PathBuf::from(".")));
    resolve_local_workspace_root(&launch_directory, user_home.as_deref())
}

fn resolve_local_workspace_root(launch_directory: &Path, user_home: Option<&Path>) -> PathBuf {
    for dir in launch_directory.ancestors() {
        if dir.join("AGENTS.md").exists() || dir.join(".git").exists() {
            return dir.to_path_buf();
        }
    }
    user_home
        .filter(|path| path.is_absolute() && path.parent().is_some())
        .unwrap_or(launch_directory)
        .to_path_buf()
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
          composerModelButton: elementProbe('.composer-model-button'),
          modelOptions: Array.from(
            document.querySelectorAll('.composer-model-popover button'),
          ).map((button) => button.textContent?.replace(/\s+/g, ' ').trim() ?? ''),
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
          const selectGlmModel = () => {
            const modelButton = document.querySelector('.composer-model-button');
            if (!modelButton) {
              report(summarize('probe-model-button-missing'));
              return;
            }
            modelButton.click();
            setTimeout(() => {
              report(summarize('probe-model-menu-open'));
              const option = Array.from(
                document.querySelectorAll('.composer-model-popover button'),
              ).find((button) => button.textContent?.includes('glm-5.2'));
              if (!option) return;
              option.click();
              setTimeout(() => report(summarize('probe-model-selected')), 2500);
            }, 500);
          };
          const firstSessionButton = document.querySelector('.workspace-tree-session-row');
          if (firstSessionButton && !window.__AGISTACK_GLM_SMOKE__) {
            window.__AGISTACK_GLM_SMOKE__ = true;
            firstSessionButton.click();
            setTimeout(selectGlmModel, 2500);
          }
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

/// Launch the Mission Control desktop shell and its project-scoped local runtime.
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let app_data_dir = app
                .path()
                .app_data_dir()
                .map_err(|error| setup_error(error.to_string()))?;
            std::fs::create_dir_all(&app_data_dir)?;
            let credential_vault = ApplicationCredentialVault::open(&app_data_dir)
                .map_err(|error| setup_error(error.to_string()))?;
            let local_runtime = tauri::async_runtime::block_on(LocalRuntimeService::start(
                app_data_dir,
                default_local_workspace_root(),
                credential_vault.clone(),
            ))
            .map_err(setup_error)?;
            app.manage(local_runtime);
            app.manage(TrustedSessionBroker::native(credential_vault));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            frontend_ready,
            local_runtime_status,
            local_runtime_configure,
            open_device_authorization_url,
            trusted_session_save,
            trusted_session_load,
            trusted_session_clear,
            local_trusted_session_save,
            local_trusted_session_load,
            local_trusted_session_clear
        ])
        .build(tauri::generate_context!())
        .expect("error while building the agistack desktop application")
        .run(handle_run_event);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(target_os = "macos")]
    #[test]
    fn macos_reopen_restores_window_only_when_none_are_visible() {
        assert!(should_restore_main_window(false));
        assert!(!should_restore_main_window(true));
    }

    #[test]
    fn release_launch_outside_a_repository_falls_back_to_the_user_home() {
        let launch_directory = Path::new("/");
        let user_home = Path::new("/Users/desktop-user");

        assert_eq!(
            resolve_local_workspace_root(launch_directory, Some(user_home)),
            user_home
        );
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
        for (authorization_base_url, raw_url) in [
            (
                "https://auth.example.com/api/v1",
                "https://auth.example.com/device?user_code=ABCDEFGH",
            ),
            (
                "http://127.0.0.1:3000",
                "http://127.0.0.1:3000/device?user_code=ABCD2345",
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
            let authorization_base_url = DeviceAuthorizationBaseUrl::parse(authorization_base_url)
                .expect("valid authorization base URL");
            let expected_user_code = raw_url
                .split("user_code=")
                .nth(1)
                .expect("test URL includes user code");
            let authorization_url =
                DeviceAuthorizationUrl::parse(raw_url, &authorization_base_url, expected_user_code)
                    .expect("valid device authorization URL");

            assert_eq!(authorization_url.as_str(), raw_url);
        }
    }

    #[test]
    fn device_authorization_url_rejects_unsafe_url_components() {
        let authorization_base_url =
            DeviceAuthorizationBaseUrl::parse("https://auth.example.com/api/v1")
                .expect("valid authorization base URL");
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
                DeviceAuthorizationUrl::parse(raw_url, &authorization_base_url, "ABCDEFGH")
                    .is_err(),
                "unsafe URL must be rejected: {raw_url}"
            );
        }
    }

    #[test]
    fn device_authorization_url_rejects_a_different_origin() {
        let authorization_base_url =
            DeviceAuthorizationBaseUrl::parse("https://auth.example.com:8443/api/v1")
                .expect("valid authorization base URL");

        for raw_url in [
            "http://auth.example.com:8443/device",
            "https://login.example.com:8443/device",
            "https://auth.example.com:9443/device",
        ] {
            assert!(
                DeviceAuthorizationUrl::parse(raw_url, &authorization_base_url, "ABCDEFGH")
                    .is_err(),
                "cross-origin URL must be rejected: {raw_url}"
            );
        }
    }

    #[test]
    fn device_authorization_base_url_rejects_unsafe_authorities() {
        for raw_url in [
            "file:///device",
            "http://auth.example.com",
            "http://localhost.example",
            "http://127.0.0.1.example",
            "http://[::2]",
            "https://user@auth.example.com",
            "https://@auth.example.com",
            "https:\t//@auth.example.com",
            "https://auth.example.com#fragment",
        ] {
            assert!(
                DeviceAuthorizationBaseUrl::parse(raw_url).is_err(),
                "unsafe authorization base URL must be rejected: {raw_url}"
            );
        }
    }

    #[test]
    fn opener_command_specs_are_cross_platform_and_shell_free() {
        let authorization_base_url =
            DeviceAuthorizationBaseUrl::parse("https://auth.example.com/api/v1")
                .expect("valid authorization base URL");
        let authorization_url = DeviceAuthorizationUrl::parse(
            "https://auth.example.com/device?user_code=ABCDEFGH",
            &authorization_base_url,
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
    fn setup_defers_fallible_window_creation_until_the_ready_event() {
        let source = include_str!("lib.rs");
        let setup = source
            .split_once(".setup(|app|")
            .expect("setup closure")
            .1
            .split_once(".invoke_handler")
            .expect("invoke handler after setup")
            .0;

        assert!(
            !setup.contains("ensure_main_window"),
            "a recoverable release-resource error must not panic inside macOS didFinishLaunching"
        );
        assert!(source.contains("RunEvent::Ready =>"));
        assert!(source.contains("if let Err(error) = ensure_main_window(app)"));
    }
}
