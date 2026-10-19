//! AT-SPI object identifiers and native X11/portal primitives only.
#[path = "linux_application.rs"]
mod application;
#[path = "linux_capture.rs"]
mod capture;
use crate::backend::{
    App, Backend, NativeError, Observation, Rect, Result, Window, check_cancel, required,
};
use async_trait::async_trait;
use serde_json::{Value, json};
use sky_cua_linux::{
    apps::discovery::{DiscoveredApp, discover_apps},
    atspi::{self, actions},
    portal::remote_desktop::MouseButton,
    x11,
};
use std::{
    path::Path,
    sync::{Arc, atomic::AtomicBool},
};

pub struct LinuxBackend {
    portal: crate::linux_portal::Portal,
    audio: crate::linux_audio::Audio,
    watchdog: Option<crate::input_watchdog::Watchdog>,
    device_lease: tokio::sync::Mutex<Option<crate::device_lease::DeviceLease>>,
    x11_capture: Arc<std::sync::Mutex<Option<crate::linux_x11_capture::Capture>>>,
    held: tokio::sync::Mutex<std::collections::BTreeSet<String>>,
    drag_active: tokio::sync::Mutex<bool>,
    state_root: Option<std::path::PathBuf>,
}
impl LinuxBackend {
    pub fn new() -> Self {
        let watchdog = crate::input_watchdog::Watchdog::start().ok();
        let state = watchdog
            .as_ref()
            .and_then(|guard| guard.private_root("state").ok());
        Self {
            portal: crate::linux_portal::Portal::new(state.clone().unwrap_or_default()),
            audio: crate::linux_audio::Audio::new(),
            watchdog,
            device_lease: tokio::sync::Mutex::new(None),
            x11_capture: Arc::new(std::sync::Mutex::new(None)),
            held: tokio::sync::Mutex::new(Default::default()),
            drag_active: tokio::sync::Mutex::new(false),
            state_root: state,
        }
    }
    fn clipboard_call(&self, id: &str, method: &str, params: &Value) -> Result<Value> {
        self.watchdog
            .as_ref()
            .filter(|guard| guard.alive())
            .ok_or_else(|| NativeError::unsupported("resource guardian"))?
            .clipboard(id, method, params)
    }
    fn portal_ready(&self) -> Result<()> {
        if Self::wayland() && self.state_root.is_none() {
            return Err(NativeError::new(
                "portal_unavailable",
                "cannot create private native portal token directory",
            ));
        }
        Ok(())
    }
    fn map(error: impl Into<NativeError>) -> NativeError {
        error.into()
    }
    fn wayland() -> bool {
        std::env::var_os("WAYLAND_DISPLAY").is_some()
    }
    async fn key_state(&self, key: &str, down: bool) -> Result<()> {
        if Self::wayland() {
            return self.portal.key_state(key, down).await;
        }
        self.watchdog
            .as_ref()
            .filter(|watchdog| watchdog.available())
            .ok_or_else(|| NativeError::unsupported("input watchdog"))?
            .hold(
                crate::input_watchdog::Item::Key(crate::linux_watchdog::keycode(key)?),
                down,
            )
    }
    async fn discovery() -> Result<(
        atspi_connection::AccessibilityConnection,
        Vec<DiscoveredApp>,
    )> {
        let connection = atspi::connect().await.map_err(Self::map)?;
        let apps = discover_apps(&connection, None, true)
            .await
            .map_err(Self::map)?;
        Ok((connection, apps))
    }
    fn window_id(top: &sky_cua_linux::apps::discovery::AccessibleTopLevel) -> String {
        format!(
            "{}:{}",
            top.object_ref
                .name()
                .map(|name| name.as_str())
                .unwrap_or_default(),
            top.object_ref.path()
        )
    }
    async fn ensure_focused(&self, observation: &Observation) -> Result<()> {
        let (_, apps) = Self::discovery().await?;
        let focused = apps
            .into_iter()
            .flat_map(|app| app.top_levels.unwrap_or_default())
            .any(|top| {
                Self::window_id(&top) == observation.window.window_id && (top.active || top.focused)
            });
        if !focused {
            return Err(NativeError::new(
                "target_not_focused",
                "the exact native AT-SPI window lost focus",
            ));
        }
        Ok(())
    }
    async fn point_input(&self, kind: &str, x: f64, y: f64, action: &Value) -> Result<()> {
        let button = match action
            .get("mouse_button")
            .and_then(Value::as_str)
            .unwrap_or("left")
        {
            "left" => MouseButton::Left,
            "right" => MouseButton::Right,
            "middle" => MouseButton::Middle,
            _ => return Err(NativeError::new("invalid_params", "invalid mouse button")),
        };
        if Self::wayland() {
            self.portal_ready()?;
            match kind {
                "click" => self.portal.click_at(x, y, button).await.map_err(Self::map),
                "move" => self
                    .portal
                    .move_pointer_absolute(x, y)
                    .await
                    .map_err(Self::map),
                _ => Err(NativeError::unsupported(kind)),
            }
        } else {
            crate::linux_watchdog::move_pointer(x, y).map_err(Self::map)?;
            if kind == "click" {
                let native = match button {
                    MouseButton::Left => x11::input_xtest::X11MouseButton::Left,
                    MouseButton::Right => x11::input_xtest::X11MouseButton::Right,
                    MouseButton::Middle => x11::input_xtest::X11MouseButton::Middle,
                };
                x11::input_xtest::click(native).map_err(Self::map)?;
            }
            Ok(())
        }
    }
}
#[async_trait]
impl Backend for LinuxBackend {
    async fn artifact_root(&self) -> Result<std::path::PathBuf> {
        self.watchdog
            .as_ref()
            .filter(|guard| guard.alive())
            .ok_or_else(|| NativeError::unsupported("resource guardian"))?
            .private_root(&format!("session-{}", uuid::Uuid::new_v4()))
    }

    async fn acquire(&self) -> Result<()> {
        if let Some(watchdog) = self.watchdog.as_ref().filter(|watchdog| watchdog.alive()) {
            return watchdog.acquire();
        }
        let mut lease = self.device_lease.lock().await;
        if lease.is_none() {
            *lease = Some(crate::device_lease::DeviceLease::acquire()?);
        }
        Ok(())
    }
    async fn capabilities(&self) -> Value {
        let ax = atspi::connect().await.is_ok();
        let portal = sky_cua_linux::portal::remote_desktop::version().await.ok();
        let native_input = if Self::wayland() {
            portal.is_some() && self.state_root.is_some()
        } else {
            x11::input_xtest::xtest_is_available()
        };
        let capture = if Self::wayland() {
            portal.is_some() && self.state_root.is_some()
        } else {
            crate::linux_x11_capture::available()
        };
        let state = |available: bool| {
            if available {
                "available"
            } else {
                "unavailable"
            }
        };
        let (granted, keyboard, pointer) = self.portal.permission_state().await;
        let hold = if !Self::wayland() {
            state(
                native_input
                    && self
                        .watchdog
                        .as_ref()
                        .is_some_and(|watchdog| watchdog.available()),
            )
        } else if !native_input {
            "unavailable"
        } else if !granted {
            "permission_required"
        } else if keyboard {
            "available"
        } else {
            "unsupported"
        };
        let drag = if !Self::wayland() {
            state(
                native_input
                    && self
                        .watchdog
                        .as_ref()
                        .is_some_and(|watchdog| watchdog.available()),
            )
        } else if !native_input {
            "unavailable"
        } else if !granted {
            "permission_required"
        } else if pointer {
            "available"
        } else {
            "unsupported"
        };
        let gst_capture = !Self::wayland()
            || (gstreamer::init().is_ok()
                && ["pipewiresrc", "videoconvert", "pngenc", "appsink"]
                    .into_iter()
                    .all(|name| gstreamer::ElementFactory::find(name).is_some()));
        let mut capabilities = json!({"app_state":{"state":state(ax),"backend":"atspi"},
            "input":{"state":if Self::wayland()&&native_input&&!granted{"permission_required"}else{state(native_input)},"backend":if Self::wayland(){"portal_eis"}else{"x11_xtest"}},
            "screenshots":{"state":if !gst_capture{"unavailable"}else if Self::wayland()&&capture&&!granted{"permission_required"}else{state(capture)},"backend":if Self::wayland(){"portal_pipewire"}else{"x11_composite"},"capture_scope":if Self::wayland(){"authorized_display"}else{"exact_window"}},
            "app_launch":{"state":state(!crate::linux_apps::installed().is_empty()),"backend":"gio_desktop_app_info"},"clipboard":{"state":state(self.watchdog.as_ref().is_some_and(|guard|guard.alive()&&guard.clipboard_available())),"backend":if Self::wayland(){"wayland_data_control"}else{"x11_selection"}},"key_hold":{"state":hold},"drag_step":{"state":drag},"calendar":{"state":"unsupported"},"contacts":{"state":"unsupported"},"messages":{"state":"unsupported"},
            "locked_use":{"state":"unsupported","reason":"locked session input is suspended"}});
        capabilities["clipboard_crash_recovery"]=self.watchdog.as_ref().map(|guard|guard.clipboard_crash_recovery())
            .unwrap_or_else(||json!({"state":"unavailable","reason":"native resource guardian is unavailable"}));
        for (key, value) in self.audio.capabilities().as_object().into_iter().flatten() {
            capabilities[key] = value.clone();
        }
        json!({"platform":"linux","protocol_version":crate::protocol::VERSION,"capabilities":capabilities})
    }
    async fn permissions(&self) -> Value {
        let ax = atspi::connect().await.is_ok();
        let (screen, _, _) = self.portal.permission_state().await;
        let screen = if Self::wayland() {
            screen
        } else {
            crate::linux_x11_capture::available()
        };
        json!({"accessibility":{"state":if ax{"granted"}else{"permission_required"}},"screen_capture":{"state":if screen{"granted"}else{"permission_required"}},"microphone":{"state":"permission_required","detail":"Device enumeration does not establish recording consent."},"system_audio":{"state":"permission_required","detail":"PipeWire/PulseAudio capture consent is checked when explicitly recording."},"calendar":{"state":"unsupported"},"contacts":{"state":"unsupported"},"messages":{"state":"unsupported"},"locked_use":{"state":"unsupported"}})
    }
    async fn request_permission(&self, capability: &str) -> Result<Value> {
        match capability {
            "screen_capture" | "accessibility" if Self::wayland() => {
                self.portal_ready()?;
                self.portal.request().await?;
                Ok(self.permissions().await[capability].clone())
            }
            "screen_capture" | "accessibility" => Ok(self.permissions().await[capability].clone()),
            "microphone" | "system_audio" => Ok(
                json!({"state":"permission_required","detail":"Grant the native PipeWire/PulseAudio device through OS privacy settings."}),
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
        self.application_list().await
    }
    async fn resolve(&self, id: &str) -> Result<Vec<App>> {
        self.resolve_application(id).await
    }
    async fn launch(&self, app: &App) -> Result<Value> {
        self.launch_application(app).await
    }
    async fn app_icon(&self, app: &App, window: Option<&Window>, root: &Path) -> Result<Value> {
        if !Self::wayland() {
            let windows;
            let selected = if let Some(window) = window {
                window
            } else {
                windows = self.windows(app).await?;
                if windows.len() != 1 {
                    return crate::linux_app_icon::installed(app, root);
                }
                &windows[0]
            };
            if let Ok(image) = crate::linux_app_icon::window(app.process_id, selected.bounds) {
                return crate::app_icon::write_png(root, image);
            }
        }
        crate::linux_app_icon::installed(app, root)
    }
    async fn windows(&self, app: &App) -> Result<Vec<Window>> {
        let (connection, apps) = Self::discovery().await?;
        let native = apps
            .into_iter()
            .find(|native| native.info.app_id == app.id)
            .ok_or_else(|| NativeError::new("app_not_found", "AT-SPI app exited"))?;
        Self::native_windows(&connection, &native).await
    }
    async fn observe(&self, app: &App, window: &Window, root: &Path) -> Result<Observation> {
        let (connection, apps) = Self::discovery().await?;
        let native = apps
            .into_iter()
            .find(|native| native.info.app_id == app.id)
            .ok_or_else(|| NativeError::new("app_not_found", "AT-SPI app exited"))?;
        let top = native
            .top_levels
            .unwrap_or_default()
            .into_iter()
            .find(|top| Self::window_id(top) == window.window_id)
            .ok_or_else(|| {
                NativeError::new("stale_element", "observed AT-SPI window disappeared")
            })?;
        let tree = crate::linux_tree::snapshot(&connection, &top.object_ref).await;
        let elements = tree.elements;
        let text = elements
            .iter()
            .map(|element| {
                format!(
                    "[{}] {} {:?} {:?} actions={:?}",
                    element.element_index,
                    element.role,
                    element.name,
                    element.value,
                    element.semantic_actions
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        let capture = self.capture(app, window, root).await;
        let (text, screenshot) = match capture {
            Ok(screenshot) => (text, Some(screenshot)),
            Err(error) => (
                format!("{text}\n! screenshot unavailable: {}", error.kind),
                None,
            ),
        };
        Ok(Observation {
            window: window.clone(),
            text,
            screenshot,
            native: json!({"elements":elements,"ax_tree":{"nodes":tree.nodes,"truncated":tree.truncated}}),
        })
    }
    async fn activate(&self, window: &Window) -> Result<()> {
        if Self::wayland() {
            let connection = atspi::connect().await.map_err(Self::map)?;
            actions::grab_focus(&connection, &window.window_id)
                .await
                .map_err(Self::map)?;
        } else {
            crate::linux_x11::activate(self.resolve_pid(&window.app).await?, window.bounds)?;
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
        self.portal_ready()?;
        self.ensure_focused(observation).await?;
        let kind = required(action, "kind")?;
        let element = action
            .get("element_index")
            .and_then(Value::as_u64)
            .and_then(|index| {
                observation.native["elements"]
                    .as_array()?
                    .iter()
                    .find(|element| element["element_index"].as_u64() == Some(index))
            });
        if matches!(kind, "set_value" | "secondary_action") {
            let reference = element
                .and_then(|element| element["backend_ref"].as_str())
                .ok_or_else(|| {
                    NativeError::new("stale_element", "observed element reference is required")
                })?;
            let connection = atspi::connect().await.map_err(Self::map)?;
            if kind == "set_value" {
                actions::set_value(&connection, reference, required(action, "value")?)
                    .await
                    .map_err(Self::map)?;
            } else {
                let names = actions::available_actions(&connection, reference)
                    .await
                    .map_err(Self::map)?;
                let name = required(action, "action")?;
                let index = names
                    .iter()
                    .position(|native| native == name)
                    .ok_or_else(|| {
                        NativeError::new(
                            "invalid_params",
                            "action name must exactly match an exposed AT-SPI action",
                        )
                    })?;
                actions::invoke_action_by_index(&connection, reference, index as i32)
                    .await
                    .map_err(Self::map)?;
            }
            return Ok(());
        }
        if kind == "select_text" {
            let reference = element
                .and_then(|element| element["backend_ref"].as_str())
                .ok_or_else(|| {
                    NativeError::new("stale_element", "observed text reference is required")
                })?;
            return crate::linux_text::select(reference, action).await;
        }
        if matches!(kind, "key_down" | "key_up") {
            if !Self::wayland()
                && !self
                    .watchdog
                    .as_ref()
                    .is_some_and(|watchdog| watchdog.available())
            {
                return Err(NativeError::unsupported("input watchdog"));
            }
            let keys = required(action, "key")?
                .split('+')
                .map(str::to_owned)
                .collect::<Vec<_>>();
            let mut held = self.held.lock().await;
            let mut added: Vec<String> = Vec::new();
            for key in keys {
                if kind == "key_down" {
                    if !held.contains(&key) {
                        if let Err(error) = self.key_state(&key, true).await {
                            for previous in added.into_iter().rev() {
                                let _ = self.key_state(&previous, false).await;
                                held.remove(&previous);
                            }
                            return Err(error);
                        }
                        added.push(key.clone());
                        held.insert(key);
                    }
                } else if held.remove(&key) {
                    self.key_state(&key, false).await?;
                }
            }
            return Ok(());
        }
        if kind == "paste" {
            let id = required(action, "_session_id")?;
            let saved = self.clipboard_call(id, "clipboard_write", action)?;
            let keys = vec!["Ctrl".to_owned(), "V".to_owned()];
            let result = if Self::wayland() {
                self.portal.press_key_sequence_portal_only(&keys).await
            } else {
                x11::input_xtest::press_key_sequence(&keys).map_err(Self::map)
            };
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
            let restore =
                self.clipboard_call(id, "clipboard_release", &json!({"handle":saved["handle"]}));
            result.and(restore.map(|_| ()))?;
            check_cancel(&cancel)?;
            return Ok(());
        }
        if kind == "type_text" {
            for character in required(action, "text")?.chars() {
                check_cancel(&cancel)?;
                self.ensure_focused(observation).await?;
                if Self::wayland() {
                    self.portal
                        .send_text(&character.to_string())
                        .await
                        .map_err(Self::map)?;
                } else {
                    x11::input_xtest::send_text(&character.to_string()).map_err(Self::map)?;
                }
                tokio::time::sleep(std::time::Duration::from_millis(2)).await;
            }
            return Ok(());
        }
        if kind == "press_key" {
            let keys = required(action, "key")?
                .split('+')
                .map(str::to_owned)
                .collect::<Vec<_>>();
            if keys
                .iter()
                .any(|key| self.held.try_lock().is_ok_and(|held| held.contains(key)))
            {
                return Err(NativeError::new(
                    "input_busy",
                    "release the held chord before pressing it",
                ));
            }
            if Self::wayland() {
                self.portal_ready()?;
                self.portal
                    .press_key_sequence_portal_only(&keys)
                    .await
                    .map_err(Self::map)?;
            } else {
                x11::input_xtest::press_key_sequence(&keys).map_err(Self::map)?;
            }
            return Ok(());
        }
        if kind == "drag" {
            return self.drag(observation, action, cancel).await;
        }
        let (x, y) = if let Some(element) = element {
            let bounds = &element["bounds"];
            (
                bounds["x"].as_f64().unwrap_or(f64::NAN)
                    + bounds["width"].as_f64().unwrap_or(f64::NAN) / 2.0,
                bounds["y"].as_f64().unwrap_or(f64::NAN)
                    + bounds["height"].as_f64().unwrap_or(f64::NAN) / 2.0,
            )
        } else {
            observation.window.bounds.point(
                action
                    .get("x")
                    .and_then(Value::as_f64)
                    .ok_or_else(|| NativeError::new("invalid_params", "x is required"))?,
                action
                    .get("y")
                    .and_then(Value::as_f64)
                    .ok_or_else(|| NativeError::new("invalid_params", "y is required"))?,
            )?
        };
        observation.window.bounds.point(
            x - observation.window.bounds.x,
            y - observation.window.bounds.y,
        )?;
        if kind == "scroll" {
            let pages = action.get("pages").and_then(Value::as_f64).unwrap_or(1.0);
            if !pages.is_finite() || !(0.1..=100.0).contains(&pages) {
                return Err(NativeError::new("invalid_params", "invalid scroll pages"));
            }
            let direction = required(action, "direction")?;
            let steps = (pages * 20.0) as i32
                * if matches!(direction, "down" | "left") {
                    -1
                } else {
                    1
                };
            if !matches!(direction, "up" | "down" | "left" | "right") {
                return Err(NativeError::new(
                    "invalid_params",
                    "invalid scroll direction",
                ));
            }
            if Self::wayland() {
                if matches!(direction, "up" | "down") {
                    self.portal
                        .scroll_vertical_at(x, y, None, steps)
                        .await
                        .map_err(Self::map)?;
                } else {
                    self.portal
                        .scroll_horizontal_at(x, y, None, steps)
                        .await
                        .map_err(Self::map)?;
                }
            } else {
                crate::linux_watchdog::move_pointer(x, y).map_err(Self::map)?;
                if matches!(direction, "up" | "down") {
                    x11::input_xtest::scroll_vertical(None, Some(steps)).map_err(Self::map)?;
                } else {
                    x11::input_xtest::scroll_horizontal(None, Some(steps)).map_err(Self::map)?;
                }
            }
            return Ok(());
        }
        if kind == "drag_step" {
            if Self::wayland() {
                self.portal_ready()?;
                self.portal
                    .move_pointer_absolute(x, y)
                    .await
                    .map_err(Self::map)?;
            } else {
                crate::linux_watchdog::move_pointer(x, y).map_err(Self::map)?;
            }
            let mut active = self.drag_active.lock().await;
            let down = match required(action, "phase")? {
                "begin" => {
                    if *active {
                        return Err(NativeError::new("input_busy", "drag already active"));
                    }
                    Some(true)
                }
                "move" => {
                    if !*active {
                        return Err(NativeError::new(
                            "invalid_params",
                            "begin a drag before moving",
                        ));
                    }
                    None
                }
                "end" => Some(false),
                _ => return Err(NativeError::new("invalid_params", "invalid drag phase")),
            };
            if let Some(down) = down {
                if Self::wayland() {
                    self.portal
                        .pointer_button(MouseButton::Left, down)
                        .await
                        .map_err(Self::map)?;
                } else {
                    self.watchdog
                        .as_ref()
                        .filter(|watchdog| watchdog.available())
                        .ok_or_else(|| NativeError::unsupported("input watchdog"))?
                        .hold(crate::input_watchdog::Item::Button(1), down)?;
                }
                *active = down;
            }
            return Ok(());
        }
        if !matches!(kind, "click" | "move") {
            return Err(NativeError::unsupported(kind));
        }
        let count = action
            .get("click_count")
            .and_then(Value::as_u64)
            .unwrap_or(1);
        if !(1..=3).contains(&count) {
            return Err(NativeError::new("invalid_params", "invalid click count"));
        }
        for _ in 0..count {
            check_cancel(&cancel)?;
            self.point_input(kind, x, y, action).await?;
            tokio::time::sleep(std::time::Duration::from_millis(70)).await;
        }
        Ok(())
    }
    async fn clipboard(&self, id: &str, method: &str, params: &Value) -> Result<Value> {
        self.clipboard_call(id, method, params)
    }
    async fn release_session(&self, id: &str) {
        let _ = self.clipboard_call(id, "clipboard_release", &json!({}));
    }
    async fn locked(&self) -> Result<bool> {
        if let Ok(connection) = zbus::Connection::system().await {
            if let Ok(manager) = zbus::Proxy::new(
                &connection,
                "org.freedesktop.login1",
                "/org/freedesktop/login1",
                "org.freedesktop.login1.Manager",
            )
            .await
            {
                let session: std::result::Result<zbus::zvariant::OwnedObjectPath, _> = manager
                    .call("GetSessionByPID", &(std::process::id(),))
                    .await;
                if let Ok(path) = session {
                    if let Ok(proxy) = zbus::Proxy::new(
                        &connection,
                        "org.freedesktop.login1",
                        path,
                        "org.freedesktop.login1.Session",
                    )
                    .await
                    {
                        if let Ok(locked) = proxy.get_property::<bool>("LockedHint").await {
                            return Ok(locked);
                        }
                    }
                }
            }
        }
        let connection = zbus::Connection::session().await.map_err(|_| {
            NativeError::new("lock_detection_unavailable", "session D-Bus is unavailable")
        })?;
        let proxy = zbus::Proxy::new(
            &connection,
            "org.freedesktop.ScreenSaver",
            "/org/freedesktop/ScreenSaver",
            "org.freedesktop.ScreenSaver",
        )
        .await
        .map_err(|_| {
            NativeError::new(
                "lock_detection_unavailable",
                "screensaver service unavailable",
            )
        })?;
        proxy.call("GetActive", &()).await.map_err(|_| {
            NativeError::new(
                "lock_detection_unavailable",
                "cannot determine Linux session lock state",
            )
        })
    }
    async fn release(&self) {
        let held = std::mem::take(&mut *self.held.lock().await);
        if Self::wayland() {
            for key in held {
                let _ = self.portal.key_state(&key, false).await;
            }
            self.portal.reset_session().await;
        } else if let Some(watchdog) = &self.watchdog {
            let _ = watchdog.release();
        }
        *self.drag_active.lock().await = false;
        self.device_lease.lock().await.take();
        if let Ok(mut capture) = self.x11_capture.lock() {
            capture.take();
        }
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
        self.watchdog
            .as_ref()
            .ok_or_else(|| NativeError::unsupported("resource guardian"))?
            .call("retain_root", json!({"path":root}))?;
        Ok(())
    }
}
