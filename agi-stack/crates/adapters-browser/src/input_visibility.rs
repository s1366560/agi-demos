//! Serialize trusted input and temporarily unthrottle hidden Chromium renderers.
//!
//! Focus emulation does not activate a tab or an OS window. Chromium accepts
//! mouse packets for hidden tabs without delivering button events, so the
//! complete high-level input sequence needs this scoped renderer preparation.
use std::future::Future;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use agistack_core::ports::CoreResult;
use serde_json::{Value, json};
use tokio::sync::{Mutex as AsyncMutex, OwnedMutexGuard};

use crate::host::{Backend, BridgeEndpoint, BrowserToolHost, tool_err};

const FOCUS_METHOD: &str = "Emulation.setFocusEmulationEnabled";
const CLEANUP_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Default)]
pub(crate) struct InputState {
    pending_releases: Vec<Value>,
    // Retained after a failed cleanup, so the next operation repairs it before
    // inspecting visibility (which an outstanding emulation would disguise).
    restore_pending: bool,
}

type Releases = Arc<Mutex<Vec<Option<Value>>>>;
struct InputScope {
    owner: usize,
    backend: Backend,
    tab: u64,
    releases: Releases,
}
tokio::task_local! { static INPUT_SCOPE: InputScope; }

pub(crate) struct ReleaseRegistration {
    releases: Releases,
    index: usize,
}
impl ReleaseRegistration {
    pub(crate) fn disarm(&self) {
        self.releases.lock().unwrap()[self.index] = None;
    }
    pub(crate) fn set_session(&self, session: &str) {
        if let Some(args) = &mut self.releases.lock().unwrap()[self.index] {
            args["sessionId"] = json!(session);
        }
    }
}

struct InputGuard<E: BridgeEndpoint> {
    endpoint: Arc<E>,
    backend: Backend,
    tab: u64,
    state: Option<OwnedMutexGuard<InputState>>,
    releases: Releases,
}
impl<E: BridgeEndpoint> InputGuard<E> {
    fn cleanup(&mut self) -> Option<tokio::task::JoinHandle<CoreResult<()>>> {
        let mut state = self.state.take()?;
        let endpoint = self.endpoint.clone();
        let backend = self.backend;
        let tab = self.tab;
        let releases = std::mem::take(&mut *self.releases.lock().unwrap());
        state
            .pending_releases
            .extend(releases.into_iter().flatten().rev());
        let runtime = tokio::runtime::Handle::try_current().ok()?;
        Some(runtime.spawn(async move { repair_state(&*endpoint, backend, tab, &mut state).await }))
    }
}
impl<E: BridgeEndpoint> Drop for InputGuard<E> {
    fn drop(&mut self) {
        // The detached cleanup task retains the tab mutex until all releases
        // and restoration finish, including when the caller itself is aborted.
        let _ = self.cleanup();
    }
}

async fn bounded_cdp<E: BridgeEndpoint>(
    endpoint: &E,
    backend: Backend,
    args: Value,
) -> CoreResult<Value> {
    tokio::time::timeout(
        CLEANUP_TIMEOUT,
        endpoint.request_on(&backend.wire_name(), "executeCdp", args),
    )
    .await
    .map_err(|_| tool_err("browser input state request timed out"))?
}

async fn restore<E: BridgeEndpoint>(
    endpoint: &E,
    backend: Backend,
    tab: u64,
    state: &mut InputState,
) -> CoreResult<()> {
    if state.restore_pending {
        bounded_cdp(
            endpoint,
            backend,
            json!({"tabId":tab,"method":FOCUS_METHOD,"params":{"enabled":false}}),
        )
        .await?;
        state.restore_pending = false;
    }
    Ok(())
}

async fn repair_state<E: BridgeEndpoint>(
    endpoint: &E,
    backend: Backend,
    tab: u64,
    state: &mut InputState,
) -> CoreResult<()> {
    let mut first_error = None;
    // An uncertain release must never be forgotten. Retry only releases, and
    // refuse fresh input until every pending release has been acknowledged.
    let mut index = 0;
    while index < state.pending_releases.len() {
        let args = state.pending_releases[index].clone();
        match bounded_cdp(endpoint, backend, args).await {
            Ok(_) => {
                state.pending_releases.remove(index);
            }
            Err(error) => {
                first_error.get_or_insert(error);
                index += 1;
            }
        }
    }
    if let Err(error) = restore(endpoint, backend, tab, state).await {
        first_error.get_or_insert(error);
    }
    match first_error {
        Some(error) => Err(error),
        None => Ok(()),
    }
}

impl<E: BridgeEndpoint> BrowserToolHost<E> {
    fn input_scope_matches(&self, backend: Backend, tab: u64) -> bool {
        INPUT_SCOPE
            .try_with(|scope| {
                scope.owner == Arc::as_ptr(&self.state) as usize
                    && scope.backend == backend
                    && scope.tab == tab
            })
            .unwrap_or(false)
    }

    fn input_mutex(&self, backend: Backend, tab: u64) -> Arc<AsyncMutex<InputState>> {
        self.state
            .input_states
            .lock()
            .unwrap()
            .entry((backend, tab))
            .or_default()
            .clone()
    }

    pub(crate) fn register_input_release(
        &self,
        backend: Backend,
        tab: u64,
        args: Value,
    ) -> Option<ReleaseRegistration> {
        if !self.input_scope_matches(backend, tab) {
            return None;
        }
        INPUT_SCOPE
            .try_with(|scope| {
                let mut releases = scope.releases.lock().unwrap();
                let index = releases.len();
                releases.push(Some(args));
                ReleaseRegistration {
                    releases: scope.releases.clone(),
                    index,
                }
            })
            .ok()
    }

    /// Full-CDP callers share the same lock. Their explicitly selected focus
    /// setting runs after scoped restoration and therefore cannot be clobbered.
    pub(crate) async fn serialize_input_request(
        &self,
        backend: Backend,
        method: &str,
        params: &Value,
    ) -> CoreResult<Option<OwnedMutexGuard<InputState>>> {
        let Some(tab) = params["tabId"].as_u64() else {
            return Ok(None);
        };
        let cdp_method = params["method"].as_str().unwrap_or_default();
        if method != "executeCdp"
            || !(cdp_method.starts_with("Input.") || cdp_method == FOCUS_METHOD)
            || self.input_scope_matches(backend, tab)
        {
            return Ok(None);
        }
        let mut state = self.input_mutex(backend, tab).lock_owned().await;
        repair_state(&*self.endpoint, backend, tab, &mut state).await?;
        Ok(Some(state))
    }

    pub(crate) fn with_input_visibility<'a, T: Send + 'a>(
        &'a self,
        backend: Backend,
        tab: u64,
        operation: impl Future<Output = CoreResult<T>> + Send + 'a,
    ) -> impl Future<Output = CoreResult<T>> + Send + 'a {
        // Box before constructing the guard future: nesting a large operation
        // inside TaskLocalFuture otherwise duplicates its storage throughout
        // the browser dispatch state machines, including read-only branches.
        let operation = Box::pin(operation);
        async move {
            if self.input_scope_matches(backend, tab) {
                return operation.await;
            }
            let mut state = self.input_mutex(backend, tab).lock_owned().await;
            repair_state(&*self.endpoint, backend, tab, &mut state).await?;
            self.ensure_attached(backend, tab).await?;
            // An already enabled focus emulation makes visibilityState "visible".
            // In that case preserve it; CDP has no focus-emulation getter.
            let (_, context_id) = self.world_context(backend, tab).await?;
            let visibility = self
                .execute_cdp(
                    backend,
                    tab,
                    "Runtime.evaluate",
                    json!({
                        "expression": "document.visibilityState",
                        "returnByValue": true,
                        "contextId": context_id,
                    }),
                )
                .await?;
            let hidden = match visibility["result"]["value"].as_str() {
                Some("hidden") => true,
                Some("visible") => false,
                _ => return Err(tool_err("browser input visibility is unavailable")),
            };
            let releases = Arc::new(Mutex::new(Vec::new()));
            let mut guard = InputGuard {
                endpoint: self.endpoint.clone(),
                backend,
                tab,
                state: Some(state),
                releases: releases.clone(),
            };
            if hidden {
                // Arm before awaiting; a cancelled/failed response may still have
                // changed the renderer and must be restored.
                guard.state.as_mut().unwrap().restore_pending = true;
                bounded_cdp(
                    &*self.endpoint,
                    backend,
                    json!({"tabId":tab,"method":FOCUS_METHOD,"params":{"enabled":true}}),
                )
                .await?;
            }
            let result = INPUT_SCOPE
                .scope(
                    InputScope {
                        owner: Arc::as_ptr(&self.state) as usize,
                        backend,
                        tab,
                        releases,
                    },
                    operation,
                )
                .await;
            let cleanup = guard
                .cleanup()
                .unwrap()
                .await
                .map_err(|_| tool_err("browser input state cleanup task failed"))?;
            match result {
                Err(error) => Err(error),
                Ok(value) => {
                    cleanup?;
                    Ok(value)
                }
            }
        }
    }
}

#[cfg(test)]
#[path = "input_visibility_tests.rs"]
mod tests;
