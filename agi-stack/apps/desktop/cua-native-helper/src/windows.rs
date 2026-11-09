//! Windows HWND discovery with MTA UIA, explicit native patterns, SendInput, and WGC.
use crate::backend::{
    check_cancel, required, App, Backend, NativeError, Observation, Rect, Result, Window,
};
use crate::{windows_input::Input, windows_uia};
use async_trait::async_trait;
use serde_json::{json, Value};
use sky_cua_platform::{model::WindowTarget, DesktopBackend};
use sky_cua_windows::WindowsDesktopBackend;
use std::{
    path::Path,
    sync::{atomic::AtomicBool, Arc},
};
use windows::Win32::System::Com::{CoInitializeEx, COINIT_MULTITHREADED};
pub struct WindowsBackend {
    native: WindowsDesktopBackend,
    mta: bool,
    audio: crate::windows_audio::Audio,
    input: Input,
}
impl WindowsBackend {
    pub fn new() -> Self {
        let mta = unsafe {
            use windows::Win32::{
                System::WinRT::{RoInitialize, RO_INIT_MULTITHREADED},
                UI::HiDpi::*,
            };
            let dpi = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
                .is_ok()
                || AreDpiAwarenessContextsEqual(
                    GetThreadDpiAwarenessContext(),
                    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
                )
                .as_bool();
            dpi && CoInitializeEx(None, COINIT_MULTITHREADED).is_ok()
                && RoInitialize(RO_INIT_MULTITHREADED).is_ok()
        };
        Self {
            native: WindowsDesktopBackend::new(),
            mta,
            audio: crate::windows_audio::Audio::new(),
            input: Input::default(),
        }
    }
    fn map(error: sky_cua_platform::BackendError) -> NativeError {
        NativeError::new(&error.code, error.message)
    }
    async fn focused(&self, observation: &Observation) -> Result<()> {
        if input_desktop_locked()?
            || self
                .native
                .focused_window()
                .await
                .map_err(Self::map)?
                .as_ref()
                .map(|window| window.window_id.as_str())
                != Some(observation.window.window_id.as_str())
        {
            return Err(NativeError::new(
                "target_not_focused",
                "the native input desktop/window changed",
            ));
        }
        Ok(())
    }
}
#[async_trait]
impl Backend for WindowsBackend {
    async fn artifact_root(&self) -> Result<std::path::PathBuf> {
        self.input
            .guardian()?
            .private_root(&format!("session-{}", uuid::Uuid::new_v4()))
    }

    async fn acquire(&self) -> Result<()> {
        self.input.acquire()
    }
    async fn capabilities(&self) -> Value {
        let ready = self.mta && windows_uia::available();
        let state = if ready { "available" } else { "unavailable" };
        let mut caps = json!({"app_state":{"state":state,"backend":"uia_mta"},"input":{"state":state,"backend":"sendinput"},"key_hold":{"state":if self.input.held_input_available(){"available"}else{"unavailable"}},"drag_step":{"state":if self.input.held_input_available(){"available"}else{"unavailable"}},"input_watchdog":{"state":if self.input.held_input_available(){"available"}else{"unavailable"}},
            "screenshots":{"state":if crate::windows_capture::available(){"available"}else{"unavailable"},"backend":"wgc"},
            "app_launch":{"state":if crate::windows_apps::installed().is_ok_and(|apps| !apps.is_empty()){"available"}else{"unavailable"},"backend":"apps_folder_native"},"clipboard":{"state":if self.input.guardian().is_ok_and(|guard|guard.clipboard_available()){"available"}else{"unavailable"},"backend":"win32_global_memory"},"calendar":{"state":"unsupported"},"contacts":{"state":"unsupported"},"messages":{"state":"unsupported"},
            "locked_use":{"state":"unsupported","reason":"secure desktop input is suspended"}});
        caps["clipboard_crash_recovery"]=self.input.guardian().map(|guard|guard.clipboard_crash_recovery())
            .unwrap_or_else(|_|json!({"state":"unavailable","reason":"native resource guardian is unavailable"}));
        for (key, value) in self.audio.capabilities().as_object().into_iter().flatten() {
            caps[key] = value.clone();
        }
        json!({"platform":"windows","protocol_version":crate::protocol::VERSION,"capabilities":caps})
    }
    async fn permissions(&self) -> Value {
        let ax = self.mta && windows_uia::available();
        json!({"accessibility":{"state":if ax{"granted"}else{"permission_required"}},"screen_capture":{"state":if crate::windows_capture::available(){"permission_required"}else{"unsupported"},"detail":"WGC support is present; capture permission is checked for the selected native window."},"microphone":microphone_permission(false).await.unwrap_or_else(|_|json!({"state":"permission_required"})),"system_audio":{"state":"permission_required","detail":"WASAPI endpoint presence does not prove capture consent."},"calendar":{"state":"unsupported"},"contacts":{"state":"unsupported"},"messages":{"state":"unsupported"},"locked_use":{"state":"unsupported"}})
    }
    async fn request_permission(&self, capability: &str) -> Result<Value> {
        match capability {
            "microphone" => microphone_permission(true).await,
            "accessibility" => Ok(
                json!({"state":if self.mta&&windows_uia::available(){"granted"}else{"permission_required"}}),
            ),
            "screen_capture" | "system_audio" => Ok(
                json!({"state":"permission_required","detail":"Grant capture in the native WGC or Windows privacy dialog for the selected application."}),
            ),
            "calendar" | "contacts" | "messages" | "locked_use" => {
                Ok(json!({"state":"unsupported"}))
            }
            _ => Err(NativeError::new(
                "invalid_params",
                "unknown system capability",
            )),
        }
    }
    async fn apps(&self) -> Result<Vec<App>> {
        if !self.mta {
            return Err(NativeError::new(
                "uia_unavailable",
                "COM MTA initialization failed",
            ));
        }
        let mut apps = std::collections::BTreeMap::new();
        for app in self.native.list_apps().await.map_err(Self::map)? {
            let id = app
                .pid
                .map(|pid| format!("pid:{pid}"))
                .unwrap_or(app.app_id);
            apps.entry(id.clone()).or_insert_with(|| {
                let mut running = App::new(id, app.name, app.pid, app.executable);
                running.native_registration_id = app.app_user_model_id.filter(|id| !id.is_empty());
                running
            });
        }
        for app in apps.values_mut() {
            app.windows = self.windows(app).await?;
        }
        let running = apps.values().cloned().collect::<Vec<_>>();
        for mut installed in crate::windows_apps::installed().unwrap_or_default() {
            for running in &running {
                if installed.native_registration_id.is_some()
                    && installed.native_registration_id == running.native_registration_id
                {
                    installed.windows.extend(running.windows.clone());
                    installed.is_running = true;
                }
            }
            apps.insert(installed.id.clone(), installed);
        }
        Ok(apps.into_values().collect())
    }
    async fn resolve(&self, identifier: &str) -> Result<Vec<App>> {
        if identifier.starts_with("shell:") {
            return crate::windows_apps::resolve(identifier);
        }
        let pid = identifier
            .strip_prefix("pid:")
            .and_then(|pid| pid.parse::<u32>().ok());
        Ok(self
            .native
            .list_apps()
            .await
            .map_err(Self::map)?
            .into_iter()
            .filter(|app| pid.is_some_and(|pid| app.pid == Some(pid)))
            .map(|app| {
                App::new(
                    format!("pid:{}", app.pid.unwrap()),
                    app.name,
                    app.pid,
                    app.executable,
                )
            })
            .collect())
    }
    async fn launch(&self, app: &App) -> Result<Value> {
        crate::windows_apps::start(app)
    }
    async fn app_icon(&self, app: &App, _: Option<&Window>, root: &Path) -> Result<Value> {
        crate::windows_app_icon::icon(app, root)
    }
    async fn windows(&self, app: &App) -> Result<Vec<Window>> {
        Ok(self
            .native
            .list_windows()
            .await
            .map_err(Self::map)?
            .into_iter()
            .filter(|window| window.pid == app.process_id)
            .filter_map(|window| {
                let bounds = window.bounds?;
                let (modal, window_type) = windows_uia::window_metadata(&window.window_id);
                Some(Window {
                    modal,
                    window_type,
                    window_id: window.window_id,
                    app: app.id.clone(),
                    title: window.title.unwrap_or_default(),
                    focused: window.focused,
                    bounds: Rect {
                        x: bounds.x,
                        y: bounds.y,
                        width: bounds.width,
                        height: bounds.height,
                    },
                })
            })
            .collect())
    }
    async fn observe(&self, _: &App, window: &Window, root: &Path) -> Result<Observation> {
        let native = windows_uia::snapshot(&window.window_id)?;
        let text = native["elements"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|e| {
                format!(
                    "[{}] {} {} value={} actions={}",
                    e["element_index"], e["role"], e["name"], e["value"], e["actions"]
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        let screenshot = Some(crate::windows_capture::screenshot(&window.window_id, root).await?);
        Ok(Observation {
            window: window.clone(),
            text,
            screenshot,
            native,
        })
    }
    async fn activate(&self, window: &Window) -> Result<()> {
        let result = self
            .native
            .activate_window(WindowTarget {
                window_id: Some(window.window_id.clone()),
                ..Default::default()
            })
            .await
            .map_err(Self::map)?;
        if !result.success {
            return Err(NativeError::new(&result.code, result.message));
        }
        Ok(())
    }
    async fn action(
        &self,
        observation: &Observation,
        action: &Value,
        cancel: Arc<AtomicBool>,
    ) -> Result<()> {
        check_cancel(&cancel)?;
        self.focused(observation).await?;
        let kind = required(action, "kind")?;
        if matches!(kind, "set_value" | "secondary_action" | "select_text") {
            return windows_uia::action(observation, action);
        }
        if kind == "paste" {
            let id = required(action, "_session_id")?;
            let saved = self
                .input
                .guardian()?
                .clipboard(id, "clipboard_write", action)?;
            let result = self.input.press("Ctrl+V").await;
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
            let restored = self.input.guardian()?.clipboard(
                id,
                "clipboard_release",
                &json!({"handle":saved["handle"]}),
            );
            result.and(restored.map(|_| ()))?;
            check_cancel(&cancel)?;
            return Ok(());
        }
        if kind == "type_text" {
            for character in required(action, "text")?.chars() {
                check_cancel(&cancel)?;
                self.focused(observation).await?;
                Input::scalar(character)?;
                tokio::time::sleep(std::time::Duration::from_millis(2)).await;
            }
            return Ok(());
        }
        if kind == "press_key" {
            return self.input.press(required(action, "key")?).await;
        }
        if matches!(kind, "key_down" | "key_up") {
            return self
                .input
                .hold(required(action, "key")?, kind == "key_down")
                .await;
        }
        let number = |key: &str| {
            action[key]
                .as_f64()
                .ok_or_else(|| NativeError::new("invalid_params", format!("{key} is required")))
        };
        if kind == "drag" {
            let from = observation
                .window
                .bounds
                .point(number("from_x")?, number("from_y")?)?;
            let to = observation
                .window
                .bounds
                .point(number("to_x")?, number("to_y")?)?;
            return self.input.drag(from, to, cancel).await;
        }
        let (x, y) = if let Some(index) = action["element_index"].as_u64() {
            let native = windows_uia::resolve(observation, index)?;
            let bounds = unsafe { native.CurrentBoundingRectangle() }.map_err(|_| {
                NativeError::new("stale_element", "native element bounds unavailable")
            })?;
            let x = (bounds.left + bounds.right) as f64 / 2.0;
            let y = (bounds.top + bounds.bottom) as f64 / 2.0;
            observation.window.bounds.point(
                x - observation.window.bounds.x,
                y - observation.window.bounds.y,
            )?
        } else {
            observation
                .window
                .bounds
                .point(number("x")?, number("y")?)?
        };
        match kind {
            "move" => Input::move_to(x, y),
            "click" => {
                Input::move_to(x, y)?;
                let count = action["click_count"].as_u64().unwrap_or(1);
                if !(1..=3).contains(&count) {
                    return Err(NativeError::new("invalid_params", "invalid click count"));
                }
                for _ in 0..count {
                    check_cancel(&cancel)?;
                    self.input
                        .click(action["mouse_button"].as_str().unwrap_or("left"))?;
                    tokio::time::sleep(std::time::Duration::from_millis(70)).await;
                }
                Ok(())
            }
            "scroll" => {
                Input::move_to(x, y)?;
                Input::scroll(
                    required(action, "direction")?,
                    action["pages"].as_f64().unwrap_or(1.0),
                )
            }
            "drag_step" => self.input.drag_step(x, y, required(action, "phase")?).await,
            _ => Err(NativeError::unsupported(kind)),
        }
    }
    async fn clipboard(&self, id: &str, method: &str, params: &Value) -> Result<Value> {
        self.input.guardian()?.clipboard(id, method, params)
    }
    async fn release_session(&self, id: &str) {
        if let Ok(guard) = self.input.guardian() {
            let _ = guard.clipboard(id, "clipboard_release", &json!({}));
        }
    }
    async fn locked(&self) -> Result<bool> {
        input_desktop_locked()
    }
    async fn release(&self) {
        self.input.release().await;
    }
    async fn audio_start(
        &self,
        id: &str,
        source: &str,
        root: &Path,
        cancel: Arc<AtomicBool>,
    ) -> Result<Value> {
        self.audio.start(id, source, root, cancel).await
    }
    async fn audio_stop(&self, id: &str) -> Result<Value> {
        self.audio.stop(id).await
    }
    async fn audio_status(&self, id: &str) -> Result<Value> {
        Ok(self.audio.status(id).await)
    }
    async fn retain_artifact_root(&self, root: &Path) -> Result<()> {
        self.input
            .guardian()?
            .call("retain_root", json!({"path":root}))?;
        Ok(())
    }
}
fn input_desktop_locked() -> Result<bool> {
    use windows::Win32::System::StationsAndDesktops::{
        CloseDesktop, GetUserObjectInformationW, OpenInputDesktop, DESKTOP_READOBJECTS, UOI_NAME,
    };
    // SAFETY: the returned desktop handle is closed, and the UTF-16 buffer is bounded.
    unsafe {
        let desktop = match OpenInputDesktop(Default::default(), false, DESKTOP_READOBJECTS) {
            Ok(desktop) => desktop,
            Err(_) => return Ok(true),
        };
        let mut name = [0u16; 256];
        let mut needed = 0;
        let result = GetUserObjectInformationW(
            windows::Win32::Foundation::HANDLE(desktop.0),
            UOI_NAME,
            Some(name.as_mut_ptr().cast()),
            std::mem::size_of_val(&name) as u32,
            Some(&mut needed),
        );
        let _ = CloseDesktop(desktop);
        result.map_err(|_| {
            NativeError::new(
                "lock_detection_unavailable",
                "cannot query active input desktop",
            )
        })?;
        let end = name
            .iter()
            .position(|character| *character == 0)
            .unwrap_or(name.len());
        Ok(String::from_utf16_lossy(&name[..end]) != "Default")
    }
}

pub fn private_root(path: &Path) -> Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows::{
        core::{w, BOOL, PWSTR},
        Win32::{
            Foundation::{LocalFree, HLOCAL},
            Security::{Authorization::*, *},
        },
    };
    std::fs::create_dir(path).map_err(|_| {
        NativeError::new("artifact_unavailable", "cannot create native artifact root")
    })?;
    // Protected owner-rights DACL prevents inheritance of a broadly readable TEMP ACL.
    let result = unsafe {
        let mut descriptor = PSECURITY_DESCRIPTOR::default();
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            w!("D:P(A;;FA;;;OW)"),
            SDDL_REVISION_1,
            &mut descriptor,
            None,
        )
        .map_err(|_| {
            NativeError::new("artifact_unavailable", "private artifact ACL unavailable")
        })?;
        let mut present = BOOL::default();
        let mut defaulted = BOOL::default();
        let mut acl = std::ptr::null_mut();
        let result = GetSecurityDescriptorDacl(descriptor, &mut present, &mut acl, &mut defaulted)
            .and_then(|_| {
                let mut name = path
                    .as_os_str()
                    .encode_wide()
                    .chain([0])
                    .collect::<Vec<_>>();
                SetNamedSecurityInfoW(
                    PWSTR(name.as_mut_ptr()),
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    Some(acl),
                    None,
                )
                .ok()
            });
        let _ = LocalFree(Some(HLOCAL(descriptor.0)));
        result
    };
    if result.is_err() {
        let _ = std::fs::remove_dir(path);
        return Err(NativeError::new(
            "artifact_unavailable",
            "cannot protect native artifact root",
        ));
    }
    Ok(())
}

async fn microphone_permission(request: bool) -> Result<Value> {
    use windows::{
        core::HSTRING,
        Security::Authorization::AppCapabilityAccess::{
            AppCapability, AppCapabilityAccessStatus as Status,
        },
    };
    let capability = AppCapability::Create(&HSTRING::from("microphone")).map_err(|_| {
        NativeError::new(
            "permission_required",
            "Windows microphone privacy status unavailable",
        )
    })?;
    let status = if request {
        capability
            .RequestAccessAsync()
            .map_err(|_| {
                NativeError::new(
                    "permission_required",
                    "Windows microphone privacy request unavailable",
                )
            })?
            .await
    } else {
        capability.CheckAccess()
    }
    .map_err(|_| {
        NativeError::new(
            "permission_required",
            "Windows microphone privacy status unavailable",
        )
    })?;
    let state = if status == Status::Allowed {
        "granted"
    } else if status == Status::DeniedBySystem || status == Status::DeniedByUser {
        "denied"
    } else {
        "permission_required"
    };
    Ok(
        json!({"state":state,"detail":if status==Status::NotDeclaredByApp{"The packaged desktop capability must declare microphone access."}else{"Windows AppCapability access status."}}),
    )
}
