use super::*;
use ::atspi::proxy::accessible::ObjectRefExt;

fn native_app(app: DiscoveredApp) -> App {
    App::new(
        app.info.app_id,
        app.info.name,
        app.info.pid,
        app.info
            .pid
            .and_then(|pid| std::fs::read_link(format!("/proc/{pid}/exe")).ok())
            .map(|path| path.to_string_lossy().into_owned()),
    )
}
impl LinuxBackend {
    pub(super) async fn native_windows(
        connection: &atspi_connection::AccessibilityConnection,
        app: &DiscoveredApp,
    ) -> Result<Vec<Window>> {
        let mut windows = Vec::new();
        for top in app.top_levels.iter().flatten() {
            let Some(bounds) = top.bounds.as_ref() else {
                continue;
            };
            let accessible = top
                .object_ref
                .as_accessible_proxy(connection.connection())
                .await
                .ok();
            let (modal, window_type) = if let Some(accessible) = accessible {
                (
                    accessible
                        .get_state()
                        .await
                        .ok()
                        .map(|states| states.contains(::atspi::State::Modal)),
                    accessible
                        .get_role()
                        .await
                        .ok()
                        .map(|role| format!("atspi:{role:?}")),
                )
            } else {
                (None, None)
            };
            windows.push(Window {
                window_id: Self::window_id(top),
                app: app.info.app_id.clone(),
                title: top.title.clone(),
                focused: top.active || top.focused,
                modal,
                window_type,
                bounds: Rect {
                    x: bounds.x,
                    y: bounds.y,
                    width: bounds.width,
                    height: bounds.height,
                },
            });
        }
        Ok(windows)
    }
    async fn running_applications(&self) -> Result<Vec<App>> {
        let (_, apps) = Self::discovery().await?;
        Ok(apps.into_iter().map(native_app).collect())
    }
    pub(super) async fn application_list(&self) -> Result<Vec<App>> {
        let mut result = Vec::new();
        if let Ok((connection, apps)) = Self::discovery().await {
            for native in apps {
                let windows = Self::native_windows(&connection, &native).await?;
                let mut app = native_app(native);
                app.windows = windows;
                result.push(app);
            }
        }
        let installed = tokio::task::spawn_blocking(crate::linux_apps::installed)
            .await
            .unwrap_or_default();
        for mut entry in installed {
            for running in &result {
                if crate::linux_apps::matches_running(&entry, running) {
                    entry.windows.extend(running.windows.clone());
                    entry.is_running = true;
                }
            }
            result.push(entry);
        }
        Ok(result)
    }
    pub(super) async fn launch_application(&self, app: &App) -> Result<Value> {
        let approved = app.clone();
        let mut result = tokio::task::spawn_blocking(move || crate::linux_apps::start(&approved))
            .await
            .map_err(|_| NativeError::new("app_launch_failed", "native launch worker failed"))??;
        for _ in 0..50 {
            let candidates = self
                .running_applications()
                .await?
                .into_iter()
                .filter(|running| {
                    running.process_id.is_some()
                        && running.app_path == app.app_path
                        && (result["process_ids"]
                            .as_array()
                            .is_none_or(|pids| pids.is_empty())
                            || result["process_ids"]
                                .as_array()
                                .unwrap()
                                .iter()
                                .any(|pid| pid.as_u64() == running.process_id.map(u64::from)))
                })
                .collect::<Vec<_>>();
            if candidates.len() == 1 {
                result["activated_app"] = serde_json::to_value(&candidates[0]).map_err(|_| {
                    NativeError::new("internal_error", "cannot encode activated application")
                })?;
                result["process_id"] = json!(candidates[0].process_id);
                result["app"] = json!(format!("pid:{}", candidates[0].process_id.unwrap()));
                return Ok(result);
            }
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
        result["state"] = json!("launched_process_not_yet_observable");
        Ok(result)
    }
    pub(super) async fn resolve_application(&self, identifier: &str) -> Result<Vec<App>> {
        if identifier.starts_with("desktop:") {
            let id = identifier.to_owned();
            return tokio::task::spawn_blocking(move || {
                crate::linux_apps::resolve(&id).map(|app| vec![app])
            })
            .await
            .map_err(|_| NativeError::new("app_not_found", "native application lookup failed"))?;
        }
        let pid = identifier
            .strip_prefix("pid:")
            .and_then(|pid| pid.parse::<u32>().ok());
        let (_, apps) = Self::discovery().await?;
        Ok(apps
            .into_iter()
            .filter(|app| {
                app.info.app_id == identifier || pid.is_some_and(|pid| app.info.pid == Some(pid))
            })
            .map(native_app)
            .collect())
    }
}
