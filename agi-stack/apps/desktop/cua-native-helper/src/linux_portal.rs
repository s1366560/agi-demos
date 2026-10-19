//! One explicitly approved RemoteDesktop session owns capture and EIS input.
use crate::{
    backend::{NativeError, Rect, Result},
    linux_eis::Eis,
};
use ashpd::desktop::{
    remote_desktop::{Axis, DeviceType, KeyState, RemoteDesktop, SelectDevicesOptions},
    screencast::{Screencast, SelectSourcesOptions, SourceType},
    PersistMode, Session,
};
use sky_cua_linux::portal::remote_desktop::{keysym_for_char, keysym_for_key_name, MouseButton};
use std::{
    os::fd::{AsRawFd, OwnedFd},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Arc,
    },
    time::Duration,
};
use tokio::sync::Mutex;
#[derive(Clone)]
pub struct Stream {
    pub logical_rect: Option<Rect>,
    node: u32,
}
pub struct Frame {
    pub path: PathBuf,
    pub logical: Rect,
    pub source_node: u32,
}
struct Active {
    remote: RemoteDesktop,
    screen: Screencast,
    session: Arc<Session<RemoteDesktop>>,
    closed: Arc<AtomicBool>,
    stream: Stream,
    eis: Option<Eis>,
}
pub struct Portal {
    state: Mutex<Option<Arc<Active>>>,
    generation: AtomicU64,
    root: PathBuf,
}
fn denied() -> NativeError {
    NativeError::new(
        "permission_required",
        "the native RemoteDesktop portal did not grant this capability",
    )
}
impl Portal {
    pub fn new(root: PathBuf) -> Self {
        Self {
            state: Mutex::new(None),
            generation: AtomicU64::new(0),
            root,
        }
    }
    async fn active(&self) -> Result<Arc<Active>> {
        if let Some(active) = self.state.lock().await.as_ref() {
            if active.closed.load(Ordering::Acquire) {
                return Err(denied());
            }
            return Ok(active.clone());
        }
        let generation = self.generation.load(Ordering::Acquire);
        let remote = RemoteDesktop::new().await.map_err(|_| denied())?;
        let screen = Screencast::new().await.map_err(|_| denied())?;
        let session = Arc::new(
            remote
                .create_session(Default::default())
                .await
                .map_err(|_| denied())?,
        );
        let closed = Arc::new(AtomicBool::new(false));
        let observe = session.clone();
        let flag = closed.clone();
        tokio::spawn(async move {
            use futures_util::StreamExt;
            if let Ok(stream) = observe.receive_closed().await {
                futures_util::pin_mut!(stream);
                let _ = stream.next().await;
                flag.store(true, Ordering::Release);
            }
        });
        let started = tokio::time::timeout(Duration::from_secs(60), async {
            remote
                .select_devices(
                    &session,
                    SelectDevicesOptions::default()
                        .set_devices(DeviceType::Keyboard | DeviceType::Pointer)
                        .set_persist_mode(PersistMode::DoNot),
                )
                .await
                .map_err(|_| denied())?
                .response()
                .map_err(|_| denied())?;
            screen
                .select_sources(
                    &session,
                    SelectSourcesOptions::default()
                        .set_sources(enumflags2::BitFlags::from_flag(SourceType::Monitor))
                        .set_multiple(false)
                        .set_persist_mode(PersistMode::DoNot),
                )
                .await
                .map_err(|_| denied())?
                .response()
                .map_err(|_| denied())?;
            remote
                .start(&session, None, Default::default())
                .await
                .map_err(|_| denied())?
                .response()
                .map_err(|_| denied())
        })
        .await;
        let response = match started {
            Ok(Ok(response)) => response,
            _ => {
                let _ = session.close().await;
                return Err(denied());
            }
        };
        let source = response.streams().first().ok_or_else(|| {
            NativeError::new("capture_unavailable", "the portal granted no screen stream")
        })?;
        let logical = source
            .position()
            .zip(source.size())
            .map(|((x, y), (width, height))| Rect {
                x: x as f64,
                y: y as f64,
                width: width as f64,
                height: height as f64,
            });
        let stream = Stream {
            logical_rect: logical,
            node: source.pipe_wire_node_id(),
        };
        let eis = match remote.connect_to_eis(&session, Default::default()).await {
            Ok(fd) => Eis::start(fd).await.ok(),
            Err(_) => None,
        };
        let active = Arc::new(Active {
            remote,
            screen,
            session,
            closed,
            stream,
            eis,
        });
        let mut state = self.state.lock().await;
        if self.generation.load(Ordering::Acquire) != generation {
            drop(state);
            let _ = active.session.close().await;
            return Err(NativeError::new(
                "user_stopped_session",
                "the native portal request was stopped",
            ));
        }
        if let Some(existing) = state.as_ref() {
            let existing = existing.clone();
            drop(state);
            let _ = active.session.close().await;
            return Ok(existing);
        }
        *state = Some(active.clone());
        Ok(active)
    }
    pub async fn permission_state(&self) -> (bool, bool, bool) {
        let state = self.state.lock().await;
        match state.as_ref() {
            Some(active) if !active.closed.load(Ordering::Acquire) => (
                true,
                active
                    .eis
                    .as_ref()
                    .is_some_and(|e| e.capabilities.keyboard.load(Ordering::Acquire)),
                active
                    .eis
                    .as_ref()
                    .is_some_and(|e| e.capabilities.pointer.load(Ordering::Acquire)),
            ),
            _ => (false, false, false),
        }
    }
    pub async fn request(&self) -> Result<()> {
        let closed = self
            .state
            .lock()
            .await
            .as_ref()
            .is_some_and(|a| a.closed.load(Ordering::Acquire));
        if closed {
            self.reset_session().await;
        }
        self.active().await.map(|_| ())
    }
    pub async fn reset_session(&self) {
        self.generation.fetch_add(1, Ordering::AcqRel);
        let old = self.state.lock().await.take();
        if let Some(active) = old {
            if let Some(eis) = &active.eis {
                let _ = eis.release().await;
            }
            let _ = active.session.close().await;
        }
    }
    pub async fn key_state(&self, key: &str, down: bool) -> Result<()> {
        let active = self.active().await?;
        active
            .eis
            .as_ref()
            .ok_or_else(|| NativeError::unsupported("EIS keyboard"))?
            .key(key, down)
            .await
    }
    pub async fn move_pointer_absolute(&self, x: f64, y: f64) -> Result<()> {
        let active = self.active().await?;
        if let Some(eis) = &active.eis {
            if eis.capabilities.pointer.load(Ordering::Acquire) {
                return eis.move_to(x, y).await;
            }
        }
        let rect = active.stream.logical_rect.ok_or_else(|| {
            NativeError::new(
                "capture_geometry_unavailable",
                "native stream geometry unavailable",
            )
        })?;
        rect.point(x - rect.x, y - rect.y)?;
        active
            .remote
            .notify_pointer_motion_absolute(
                &active.session,
                active.stream.node,
                x - rect.x,
                y - rect.y,
                Default::default(),
            )
            .await
            .map_err(|_| denied())
    }
    pub async fn pointer_button(&self, button: MouseButton, down: bool) -> Result<()> {
        let active = self.active().await?;
        let code = match button {
            MouseButton::Left => 0x110,
            MouseButton::Right => 0x111,
            MouseButton::Middle => 0x112,
        };
        let eis = active
            .eis
            .as_ref()
            .ok_or_else(|| NativeError::unsupported("EIS pointer"))?;
        eis.button(code, down).await
    }
    pub async fn click_at(&self, x: f64, y: f64, button: MouseButton) -> Result<()> {
        self.move_pointer_absolute(x, y).await?;
        self.pointer_button(button, true).await?;
        tokio::time::sleep(Duration::from_millis(15)).await;
        self.pointer_button(button, false).await
    }
    pub async fn send_text(&self, text: &str) -> Result<()> {
        let active = self.active().await?;
        for character in text.chars() {
            let sym = keysym_for_char(character)
                .ok_or_else(|| NativeError::unsupported("native Unicode keysym"))?;
            active
                .remote
                .notify_keyboard_keysym(&active.session, sym, KeyState::Pressed, Default::default())
                .await
                .map_err(|_| denied())?;
            active
                .remote
                .notify_keyboard_keysym(
                    &active.session,
                    sym,
                    KeyState::Released,
                    Default::default(),
                )
                .await
                .map_err(|_| denied())?;
        }
        Ok(())
    }
    pub async fn press_key_sequence_portal_only(&self, keys: &[String]) -> Result<()> {
        let active = self.active().await?;
        let mut pressed = Vec::new();
        let result = async {
            for key in keys {
                let sym = keysym_for_key_name(key).ok_or_else(|| {
                    NativeError::new("invalid_params", "unsupported native key name")
                })?;
                active
                    .remote
                    .notify_keyboard_keysym(
                        &active.session,
                        sym,
                        KeyState::Pressed,
                        Default::default(),
                    )
                    .await
                    .map_err(|_| denied())?;
                pressed.push(sym);
            }
            Ok(())
        }
        .await;
        for sym in pressed.into_iter().rev() {
            let _ = active
                .remote
                .notify_keyboard_keysym(
                    &active.session,
                    sym,
                    KeyState::Released,
                    Default::default(),
                )
                .await;
        }
        result
    }
    async fn scroll(
        &self,
        x: f64,
        y: f64,
        axis: Axis,
        delta: Option<f64>,
        steps: i32,
    ) -> Result<()> {
        self.move_pointer_absolute(x, y).await?;
        let active = self.active().await?;
        if let Some(delta) = delta {
            active
                .remote
                .notify_pointer_axis(
                    &active.session,
                    if axis == Axis::Horizontal { delta } else { 0.0 },
                    if axis == Axis::Vertical { delta } else { 0.0 },
                    Default::default(),
                )
                .await
                .map_err(|_| denied())
        } else {
            active
                .remote
                .notify_pointer_axis_discrete(&active.session, axis, steps, Default::default())
                .await
                .map_err(|_| denied())
        }
    }
    pub async fn scroll_vertical_at(
        &self,
        x: f64,
        y: f64,
        delta: Option<f64>,
        steps: i32,
    ) -> Result<()> {
        self.scroll(x, y, Axis::Vertical, delta, steps).await
    }
    pub async fn scroll_horizontal_at(
        &self,
        x: f64,
        y: f64,
        delta: Option<f64>,
        steps: i32,
    ) -> Result<()> {
        self.scroll(x, y, Axis::Horizontal, delta, steps).await
    }
    pub async fn drag(
        &self,
        points: &[(f64, f64)],
        delay: Duration,
        cancel: Option<&sky_cua_platform::model::CuaCancellation>,
    ) -> Result<()> {
        let first = points
            .first()
            .ok_or_else(|| NativeError::new("invalid_params", "drag path is empty"))?;
        self.move_pointer_absolute(first.0, first.1).await?;
        self.pointer_button(MouseButton::Left, true).await?;
        let result = async {
            for (x, y) in points.iter().skip(1) {
                if cancel.is_some_and(|cancel| cancel.is_cancelled()) {
                    return Err(NativeError::new(
                        "user_stopped_session",
                        "native drag was stopped",
                    ));
                }
                self.move_pointer_absolute(*x, *y).await?;
                tokio::time::sleep(delay).await;
            }
            Ok(())
        }
        .await;
        let released = self.pointer_button(MouseButton::Left, false).await;
        result.and(released)
    }
    pub async fn capture_frame(&self, id: &str) -> Result<Frame> {
        let generation = self.generation.load(Ordering::Acquire);
        let active = self.active().await?;
        let logical = active.stream.logical_rect.ok_or_else(|| {
            NativeError::new(
                "capture_geometry_unavailable",
                "portal source lacks logical geometry",
            )
        })?;
        let fd = active
            .screen
            .open_pipe_wire_remote(&active.session, Default::default())
            .await
            .map_err(|_| {
                NativeError::new("capture_unavailable", "PipeWire portal remote unavailable")
            })?;
        let path = self.root.join(format!("{id}.png"));
        let output = path.clone();
        let node = active.stream.node;
        tokio::task::spawn_blocking(move || capture(output, node, fd))
            .await
            .map_err(|_| NativeError::new("capture_failed", "PipeWire capture worker failed"))??;
        if active.closed.load(Ordering::Acquire)
            || generation != self.generation.load(Ordering::Acquire)
        {
            let _ = std::fs::remove_file(&path);
            return Err(NativeError::new(
                "user_stopped_session",
                "portal source changed during capture",
            ));
        }
        Ok(Frame {
            path,
            logical,
            source_node: node,
        })
    }
}
fn capture(path: PathBuf, node: u32, fd: OwnedFd) -> Result<()> {
    use gstreamer as gst;
    let error = || {
        NativeError::new(
            "capture_unavailable",
            "native PipeWire/GStreamer capture unavailable",
        )
    };
    gst::init().map_err(|_| error())?;
    let source = gst::ElementFactory::make("pipewiresrc")
        .property("fd", fd.as_raw_fd())
        .property("path", node.to_string())
        .property("num-buffers", 1i32)
        .build()
        .map_err(|_| error())?;
    capture_source(path, source)
}
fn capture_source(path: PathBuf, source: gstreamer::Element) -> Result<()> {
    use gstreamer::{self as gst, prelude::*};
    use gstreamer_app::AppSink;
    let error = || {
        NativeError::new(
            "capture_unavailable",
            "native GStreamer capture unavailable",
        )
    };
    let convert = gst::ElementFactory::make("videoconvert")
        .build()
        .map_err(|_| error())?;
    let encode = gst::ElementFactory::make("pngenc")
        .property("snapshot", true)
        .build()
        .map_err(|_| error())?;
    let sink = gst::ElementFactory::make("appsink")
        .property("sync", false)
        .property("max-buffers", 1u32)
        .build()
        .map_err(|_| error())?
        .dynamic_cast::<AppSink>()
        .map_err(|_| error())?;
    let pipeline = gst::Pipeline::new();
    pipeline
        .add_many([&source, &convert, &encode, sink.upcast_ref()])
        .map_err(|_| error())?;
    gst::Element::link_many([&source, &convert, &encode, sink.upcast_ref()])
        .map_err(|_| error())?;
    let result = (|| {
        pipeline
            .set_state(gst::State::Playing)
            .map_err(|_| error())?;
        let sample = sink
            .try_pull_sample(gst::ClockTime::from_seconds(8))
            .ok_or_else(error)?;
        let buffer = sample.buffer().ok_or_else(error)?;
        let map = buffer.map_readable().map_err(|_| error())?;
        std::fs::write(&path, map.as_ref())
            .map_err(|_| NativeError::new("artifact_unavailable", "cannot store native screenshot"))
    })();
    let _ = pipeline.set_state(gst::State::Null);
    result
}
