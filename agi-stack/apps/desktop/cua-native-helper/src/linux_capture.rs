use super::*;

impl LinuxBackend {
    pub(super) async fn resolve_pid(&self, id: &str) -> Result<Option<u32>> {
        Ok(Self::discovery()
            .await?
            .1
            .into_iter()
            .find(|app| app.info.app_id == id)
            .and_then(|app| app.info.pid))
    }
    pub(super) async fn capture(&self, app: &App, window: &Window, root: &Path) -> Result<Value> {
        let capture_id = uuid::Uuid::new_v4().to_string();
        if !Self::wayland() {
            let path = root.join(format!("{capture_id}.png"));
            let output = path.clone();
            let bounds = window.bounds;
            let pid = app.process_id;
            let capture = self.x11_capture.clone();
            let xid = tokio::task::spawn_blocking(move || {
                let mut guard = capture.lock().map_err(|_| {
                    NativeError::new("capture_unavailable", "native capture owner unavailable")
                })?;
                if guard.is_none() {
                    *guard = Some(crate::linux_x11_capture::Capture::new()?);
                }
                guard
                    .as_mut()
                    .ok_or_else(|| NativeError::unsupported("exact window capture"))?
                    .capture(pid, bounds, &output)
            })
            .await
            .map_err(|_| {
                NativeError::new("capture_failed", "native window capture worker failed")
            })??;
            let (width, height) = image::image_dimensions(&path)
                .map_err(|_| NativeError::new("capture_failed", "invalid native window pixels"))?;
            return Ok(
                json!({"url":url::Url::from_file_path(path).map_err(|_|NativeError::new("artifact_unavailable", "invalid file URL"))?.as_str(),"mime_type":"image/png","width":width,"height":height,"capture_scope":"exact_window","native_window_id":format!("0x{xid:x}")}),
            );
        }
        if !window.focused {
            return Err(NativeError::new(
                "target_not_focused",
                "focus the native target before capturing an authorized display region",
            ));
        }
        let (path, logical, source_node) = if Self::wayland() {
            self.portal_ready()?;
            let frame = self
                .portal
                .capture_frame(&capture_id)
                .await
                .map_err(Self::map)?;
            let logical = frame.logical;
            (
                frame.path,
                Rect {
                    x: logical.x,
                    y: logical.y,
                    width: logical.width,
                    height: logical.height,
                },
                frame.source_node,
            )
        } else {
            return Err(NativeError::unsupported("capture backend"));
        };
        let image = image::open(&path)
            .map_err(|_| NativeError::new("capture_failed", "cannot decode desktop image"))?;
        if !self.windows(app).await?.iter().any(|current| {
            current.window_id == window.window_id
                && current.focused
                && current.bounds == window.bounds
        }) {
            let _ = std::fs::remove_file(&path);
            return Err(NativeError::new(
                "capture_geometry_changed",
                "native target focus or geometry changed during portal capture",
            ));
        }
        let scale_x = image.width() as f64 / logical.width;
        let scale_y = image.height() as f64 / logical.height;
        let x = ((window.bounds.x - logical.x) * scale_x).round();
        let y = ((window.bounds.y - logical.y) * scale_y).round();
        let width = (window.bounds.width * scale_x).round();
        let height = (window.bounds.height * scale_y).round();
        if ![x, y, width, height].iter().all(|value| value.is_finite())
            || x < 0.0
            || y < 0.0
            || width <= 0.0
            || height <= 0.0
            || x + width > image.width() as f64
            || y + height > image.height() as f64
        {
            return Err(NativeError::new(
                "capture_geometry_unavailable",
                "window is outside the captured display",
            ));
        }
        let output = root.join(format!("{capture_id}.png"));
        let cropped = image.crop_imm(x as u32, y as u32, width as u32, height as u32);
        cropped
            .save(&output)
            .map_err(|_| NativeError::new("capture_failed", "cannot save window screenshot"))?;
        let _ = std::fs::remove_file(path);
        Ok(
            json!({"url":url::Url::from_file_path(&output).map_err(|_|NativeError::new("artifact_unavailable","invalid file URL"))?.as_str(),"mime_type":"image/png","width":cropped.width(),"height":cropped.height(),"capture_scope":"authorized_display","capture_region":window.bounds,"authorized_source_geometry":logical,"authorized_source_node":source_node,"exact_window_capture":{"state":"unavailable","reason":"portal monitor source does not expose an exact native application/window identity"}}),
        )
    }
    pub(super) async fn drag(
        &self,
        observation: &Observation,
        action: &Value,
        cancel: Arc<AtomicBool>,
    ) -> Result<()> {
        let coordinate = |key: &str| {
            action
                .get(key)
                .and_then(Value::as_f64)
                .ok_or_else(|| NativeError::new("invalid_params", format!("{key} is required")))
        };
        let (from_x, from_y) = observation
            .window
            .bounds
            .point(coordinate("from_x")?, coordinate("from_y")?)?;
        let (to_x, to_y) = observation
            .window
            .bounds
            .point(coordinate("to_x")?, coordinate("to_y")?)?;
        if Self::wayland() {
            self.portal_ready()?;
            let native_cancel = sky_cua_platform::model::CuaCancellation::new();
            let trigger = native_cancel.clone();
            let watcher = tokio::spawn(async move {
                while !cancel.load(std::sync::atomic::Ordering::Acquire) {
                    tokio::time::sleep(std::time::Duration::from_millis(5)).await;
                }
                trigger.cancel();
            });
            let points = (0..=24)
                .map(|step| {
                    let t = step as f64 / 24.0;
                    (from_x + (to_x - from_x) * t, from_y + (to_y - from_y) * t)
                })
                .collect::<Vec<_>>();
            let result = self
                .portal
                .drag(
                    &points,
                    std::time::Duration::from_millis(8),
                    Some(&native_cancel),
                )
                .await
                .map_err(Self::map);
            watcher.abort();
            return result;
        }
        crate::linux_watchdog::move_pointer(from_x, from_y).map_err(Self::map)?;
        self.watchdog
            .as_ref()
            .filter(|watchdog| watchdog.available())
            .ok_or_else(|| NativeError::unsupported("input watchdog"))?
            .hold(crate::input_watchdog::Item::Button(1), true)?;
        let result = async {
            for step in 1..=24 {
                check_cancel(&cancel)?;
                self.ensure_focused(observation).await?;
                let t = step as f64 / 24.0;
                crate::linux_watchdog::move_pointer(
                    from_x + (to_x - from_x) * t,
                    from_y + (to_y - from_y) * t,
                )
                .map_err(Self::map)?;
                tokio::time::sleep(std::time::Duration::from_millis(8)).await;
            }
            Ok(())
        }
        .await;
        if let Some(watchdog) = &self.watchdog {
            let _ = watchdog.hold(crate::input_watchdog::Item::Button(1), false);
        }
        result
    }
}
