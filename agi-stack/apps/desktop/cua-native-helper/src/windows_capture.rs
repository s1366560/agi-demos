//! Window-specific Windows Graphics Capture; no fallback to whole-desktop capture.
use crate::backend::{NativeError, Result};
use serde_json::{json, Value};
use std::{
    path::{Path, PathBuf},
    sync::mpsc::{sync_channel, SyncSender},
    time::Duration,
};
use windows_capture::{
    capture::{Context, GraphicsCaptureApiHandler},
    encoder::ImageFormat,
    frame::Frame,
    graphics_capture_api::InternalCaptureControl,
    settings::{
        ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings,
        MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings,
    },
    window::Window,
};

struct Flags {
    path: PathBuf,
    result: SyncSender<Result<Value>>,
}
struct SingleFrame(Flags);
impl GraphicsCaptureApiHandler for SingleFrame {
    type Flags = Flags;
    type Error = NativeError;
    fn new(context: Context<Self::Flags>) -> Result<Self> {
        Ok(Self(context.flags))
    }
    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame<'_>,
        control: InternalCaptureControl,
    ) -> Result<()> {
        let result=frame.save_as_image(&self.0.path,ImageFormat::Png).map_err(|_|NativeError::new("capture_failed","WGC frame encoding failed")).and_then(|_|{
            let url=url::Url::from_file_path(&self.0.path).map_err(|_|NativeError::new("artifact_unavailable","invalid screenshot path"))?;
            Ok(json!({"url":url.as_str(),"width":frame.width(),"height":frame.height(),"mime_type":"image/png","backend":"wgc"}))
        });
        let _ = self.0.result.try_send(result);
        control.stop();
        Ok(())
    }
    fn on_closed(&mut self) -> Result<()> {
        let _ = self.0.result.try_send(Err(NativeError::new(
            "target_changed",
            "captured native HWND closed",
        )));
        Ok(())
    }
}
pub fn available() -> bool {
    windows::Graphics::Capture::GraphicsCaptureSession::IsSupported().unwrap_or(false)
}
pub async fn screenshot(window_id: &str, root: &Path) -> Result<Value> {
    let hwnd = window_id
        .strip_prefix("hwnd:0x")
        .and_then(|handle| usize::from_str_radix(handle, 16).ok())
        .ok_or_else(|| NativeError::new("invalid_params", "exact native HWND is required"))?;
    let path = root.join(format!("{}.png", uuid::Uuid::new_v4()));
    tokio::task::spawn_blocking(move || {
        let target = Window::from_raw_hwnd(hwnd as *mut std::ffi::c_void);
        if !target.is_valid() {
            return Err(NativeError::new(
                "target_changed",
                "native HWND is no longer capturable",
            ));
        }
        let (result, receiver) = sync_channel(1);
        let settings = Settings::new(
            target,
            CursorCaptureSettings::WithoutCursor,
            DrawBorderSettings::WithBorder,
            SecondaryWindowSettings::Exclude,
            MinimumUpdateIntervalSettings::Default,
            DirtyRegionSettings::Default,
            ColorFormat::Bgra8,
            Flags { path, result },
        );
        let control = SingleFrame::start_free_threaded(settings).map_err(|_| {
            NativeError::new(
                "capture_unavailable",
                "Windows Graphics Capture could not initialize",
            )
        })?;
        let result = receiver.recv_timeout(Duration::from_secs(5)).map_err(|_| {
            NativeError::new(
                "capture_timeout",
                "WGC delivered no frame before the deadline",
            )
        });
        let _ = control.stop();
        result?
    })
    .await
    .map_err(|_| NativeError::new("capture_failed", "WGC worker failed"))?
}
