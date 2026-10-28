//! Independent, coalescing input presentation. Never carries run authority.
use super::*;

pub(super) fn support(state: &LocalRuntimeState) -> Value {
    state.computer_use.input_support.lock().ok().and_then(|value| value.clone())
        .unwrap_or_else(|| json!({"background":{"supported":false,"reason":"helper_unavailable"},"foreground":{"supported":false,"reason":"helper_unavailable"}}))
}

pub(super) async fn refresh_status(
    state: &Arc<LocalRuntimeState>,
    owner: &Owner,
) -> Result<(), String> {
    let instance = {
        let db = state.session_store.connection()?;
        store::instance(&db, owner)?
    };
    let allow_start = instance.installed
        && instance.enabled
        && state
            .computer_use
            .input_support
            .lock()
            .is_ok_and(|value| value.is_none());
    if state
        .computer_use
        .input_support_probe
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return Ok(());
    }
    struct Probe(Arc<LocalRuntimeState>);
    impl Drop for Probe {
        fn drop(&mut self) {
            self.0
                .computer_use
                .input_support_probe
                .store(false, Ordering::SeqCst);
        }
    }
    let probe = Probe(state.clone());
    let task = tokio::spawn(async move {
        let _ = refresh_support(&probe.0, allow_start).await;
        drop(probe);
    });
    // A slow read-only probe must not delay settings or cancel a helper that
    // owns audio/input. Dropping the handle leaves the single bounded RPC alive.
    let _ = tokio::time::timeout(std::time::Duration::from_secs(2), task).await;
    Ok(())
}

pub(super) async fn refresh_support(state: &Arc<LocalRuntimeState>, allow_start: bool) -> bool {
    let response = if allow_start {
        match state.computer_use.client() {
            Ok(client) => Some(client.request("capabilities", json!({})).await),
            Err(_) => None,
        }
    } else if let Some(client) = state.computer_use.client.get() {
        client.capabilities_if_connected().await
    } else {
        None
    };
    let Some(response) = response else {
        return state
            .computer_use
            .input_support
            .lock()
            .is_ok_and(|value| value.is_some());
    };
    let value = response
        .ok()
        .and_then(|value| value.get("input_support").cloned());
    let available = value.is_some();
    if let Ok(mut support) = state.computer_use.input_support.lock() {
        *support = value;
    }
    available
}

pub(super) fn listen(state: &Arc<LocalRuntimeState>, client: &Arc<CuaClient>) {
    let mut receiver = client.subscribe_input_telemetry();
    let weak = Arc::downgrade(state);
    tokio::spawn(async move {
        let mut seen: BTreeMap<String, (String, u64)> = BTreeMap::new();
        while receiver.changed().await.is_ok() {
            let events = receiver.borrow_and_update().clone();
            let Some(state) = weak.upgrade() else {
                return;
            };
            let removed: Vec<_> = seen
                .keys()
                .filter(|id| !events.contains_key(*id))
                .cloned()
                .collect();
            for id in removed {
                terminal(&state.computer_use, &id, "input_binding_closed");
                seen.remove(&id);
            }
            for (id, event) in events {
                let current = state
                    .computer_use
                    .client
                    .get()
                    .and_then(|client| client.current_input_generation(&id));
                if current.as_deref() != Some(event.input_generation.as_str()) {
                    continue;
                }
                let key = (event.input_generation.clone(), event.sequence);
                if seen.get(&id) == Some(&key) {
                    continue;
                }
                let session = state
                    .computer_use
                    .sessions
                    .lock()
                    .ok()
                    .and_then(|sessions| sessions.get(&id).cloned());
                let Some(session) = session.filter(|session| session.context == event.context)
                else {
                    continue;
                };
                if session.stopped.load(Ordering::SeqCst) && event.phase != "stopped" {
                    continue;
                }
                if session.paused.load(Ordering::SeqCst)
                    && !matches!(event.phase.as_str(), "paused" | "stopped")
                {
                    continue;
                }
                seen.insert(id.clone(), key);
                let Ok(mut value) = serde_json::to_value(&event) else {
                    continue;
                };
                let Some(object) = value.as_object_mut() else {
                    continue;
                };
                object.remove("context");
                object.insert(
                    "mode".into(),
                    json!(if session.cloud.is_some() {
                        "cloud"
                    } else {
                        "local"
                    }),
                );
                for (field, content) in [
                    ("tenant_id", &event.context.tenant_id),
                    ("project_id", &event.context.project_id),
                    ("conversation_id", &event.context.conversation_id),
                    ("run_id", &event.context.run_id),
                    ("session_id", &event.context.session_id),
                ] {
                    object.insert(field.into(), json!(content));
                }
                object.insert("input_mode".into(), json!(event.context.input_mode));
                if let Ok(mut presentation) = session.presentation.lock() {
                    presentation["input_generation"] = json!(event.input_generation);
                }
                state.computer_use.input_events.send_modify(|latest| {
                    latest.insert(id, value);
                });
            }
            seen.retain(|id, _| {
                state
                    .computer_use
                    .sessions
                    .lock()
                    .is_ok_and(|sessions| sessions.contains_key(id))
            });
        }
    });
}

/// A display-only terminal receipt also clears a cursor after EOF or a host-side stop.
pub(super) fn terminal(runtime: &ComputerUseRuntimeV2, id: &str, reason: &str) {
    runtime.input_events.send_modify(|latest| {
        if let Some(event) = latest.get_mut(id) {
            event["phase"] = json!("stopped");
            event["sequence"] = json!(event["sequence"]
                .as_u64()
                .unwrap_or(0)
                .saturating_add(1)
                .min(9_007_199_254_740_991));
            event["updated_at"] = json!(chrono::Utc::now().timestamp_millis() as f64 / 1000.0);
            event["reason"] = json!(reason);
            event["virtual_cursor"] = Value::Null;
            event["held_keys"] = json!([]);
            event["held_buttons"] = json!([]);
        }
        // Retain bounded terminal receipts so a coalescing writer can still clear the UI.
        while latest.len() > 128 {
            let oldest = latest
                .iter()
                .filter(|(_, event)| event["phase"] == "stopped")
                .min_by(|(_, a), (_, b)| {
                    a["updated_at"]
                        .as_f64()
                        .unwrap_or(0.0)
                        .total_cmp(&b["updated_at"].as_f64().unwrap_or(0.0))
                })
                .map(|(id, _)| id.clone());
            if let Some(oldest) = oldest {
                latest.remove(&oldest);
            } else {
                break;
            }
        }
    });
}
