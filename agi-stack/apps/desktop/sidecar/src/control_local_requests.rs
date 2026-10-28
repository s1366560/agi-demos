//! Approval-bound App callbacks must not block the private lifecycle channel.
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use serde::Deserialize;
use serde_json::{json, Value};
use tokio::{
    sync::{mpsc, oneshot, watch},
    task::JoinSet,
};

use super::{failure, ControlRequest, ControlResponse, LocalRuntimeService};

const MAX_CALLBACKS: usize = 32;

pub(crate) enum Dispatch {
    Unhandled,
    Response(ControlResponse),
    Pending,
}

#[derive(Clone, PartialEq, Eq)]
struct Mount {
    tab_id: String,
    nonce: String,
}

impl Mount {
    fn read(input: &Value) -> Result<Self, String> {
        let field = |name: &str| {
            input[name]
                .as_str()
                .filter(|value| !value.is_empty() && value.len() <= 128)
                .map(str::to_owned)
                .ok_or_else(|| "mcp_app_mount_required".to_owned())
        };
        Ok(Self {
            tab_id: field("tabId")?,
            nonce: field("mountNonce")?,
        })
    }
}

struct PendingCall {
    mount: Mount,
    cancel: Option<oneshot::Sender<()>>,
    finished: watch::Receiver<bool>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CancelRequest {
    request_id: String,
    tab_id: String,
    mount_nonce: String,
}

#[derive(Default)]
pub(crate) struct LocalControlRequests {
    pending: Arc<Mutex<HashMap<String, PendingCall>>>,
    tasks: JoinSet<()>,
}

impl LocalControlRequests {
    pub(crate) async fn dispatch(
        &mut self,
        runtime: &LocalRuntimeService,
        request: &ControlRequest,
        output: &mpsc::Sender<Value>,
    ) -> Dispatch {
        if !matches!(
            request.command.as_str(),
            "local_runtime_status" | "mcp_app_operation" | "mcp_app_operation_cancel"
        ) {
            return Dispatch::Unhandled;
        }
        if request.message_type != "request" || request.id.is_empty() || request.id.len() > 128 {
            return Dispatch::Response(failure(
                request.id.clone(),
                "sidecar control request is invalid",
            ));
        }
        while self.tasks.try_join_next().is_some() {}
        let result = match request.command.as_str() {
            "local_runtime_status" => {
                serde_json::to_value(runtime.status()).map_err(|error| error.to_string())
            }
            "mcp_app_operation_cancel" => {
                self.cancel(request.args.clone().unwrap_or(Value::Null))
                    .await
            }
            "mcp_app_operation" => match request.args.clone() {
                Some(input) if input["operation"] == "tools/call" => {
                    return match self.start(runtime, request.id.clone(), input, output.clone()) {
                        Ok(()) => Dispatch::Pending,
                        Err(error) => Dispatch::Response(failure(request.id.clone(), &error)),
                    };
                }
                Some(input) => runtime.mcp_app_operation(input).await,
                None => Err("mcp_app_request_required".into()),
            },
            _ => unreachable!("recognized local command"),
        };
        Dispatch::Response(response(request.id.clone(), result))
    }

    fn start(
        &mut self,
        runtime: &LocalRuntimeService,
        id: String,
        input: Value,
        output: mpsc::Sender<Value>,
    ) -> Result<(), String> {
        let mount = Mount::read(&input)?;
        let (cancel, cancelled) = oneshot::channel();
        let (finished, completion) = watch::channel(false);
        {
            let mut pending = self.pending.lock().expect("control App callbacks");
            if pending.contains_key(&id) {
                return Err("mcp_app_request_id_active".into());
            }
            if self.tasks.len() >= MAX_CALLBACKS {
                return Err("mcp_app_callback_limit".into());
            }
            pending.insert(
                id.clone(),
                PendingCall {
                    mount,
                    cancel: Some(cancel),
                    finished: completion,
                },
            );
        }
        let pending = self.pending.clone();
        let runtime = runtime.clone();
        self.tasks.spawn(async move {
            let result = tokio::select! {
                biased;
                _ = cancelled => Err("mcp_app_request_cancelled: an already dispatched operation may have effects; do not retry".into()),
                result = runtime.mcp_app_operation(input) => result,
            };
            // Dropping a cancelled callback future closes its REPL oneshot receiver.
            // The pending operation checks that receiver before any later dispatch.
            let _ = finished.send(true);
            if let Ok(value) = serde_json::to_value(response(id.clone(), result)) {
                let _ = output.send(value).await;
            }
            pending.lock().expect("control App callbacks").remove(&id);
        });
        Ok(())
    }

    async fn cancel(&self, input: Value) -> Result<Value, String> {
        let request: CancelRequest = serde_json::from_value(input)
            .map_err(|_| "mcp_app_cancel_request_invalid".to_owned())?;
        if request.request_id.is_empty() || request.request_id.len() > 128 {
            return Err("mcp_app_cancel_request_invalid".into());
        }
        let mount = Mount {
            tab_id: request.tab_id,
            nonce: request.mount_nonce,
        };
        let finished = {
            let mut pending = self.pending.lock().expect("control App callbacks");
            match pending.get_mut(&request.request_id) {
                Some(call) if call.mount == mount => {
                    if let Some(cancel) = call.cancel.take() {
                        let _ = cancel.send(());
                    }
                    Some(call.finished.clone())
                }
                Some(_) => return Err("mcp_app_cancel_mount_mismatch".into()),
                None => None,
            }
        };
        let cancelled = finished.is_some();
        if let Some(mut finished) = finished {
            // The ack follows the actual drop, so approval immediately after it
            // cannot race the REPL receiver's closed check.
            finished
                .wait_for(|value| *value)
                .await
                .map_err(|_| "mcp_app_callback_worker_stopped".to_owned())?;
        }
        // This acknowledges the waiter cancellation, never reversal of a side effect.
        Ok(json!({"cancelled":cancelled}))
    }

    pub(crate) async fn shutdown(&mut self) {
        self.tasks.shutdown().await;
        self.pending.lock().expect("control App callbacks").clear();
    }
}

fn response(id: String, result: Result<Value, String>) -> ControlResponse {
    match result {
        Ok(result) => ControlResponse {
            message_type: "response",
            id,
            ok: true,
            result: Some(result),
            error: None,
        },
        Err(error) => failure(id, &error),
    }
}
