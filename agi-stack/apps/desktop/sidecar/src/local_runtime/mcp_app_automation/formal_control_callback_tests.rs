//! The production control dispatcher must serve lifecycle commands during approval.
use super::*;
use crate::control::{
    local_requests::{Dispatch, LocalControlRequests},
    ControlRequest,
};
use crate::local_runtime::LocalRuntimeService;
use std::collections::HashMap;
use tokio::sync::{mpsc, oneshot};

struct ControlPipe {
    input: mpsc::Sender<Value>,
    output: mpsc::Receiver<Value>,
    saved: HashMap<String, Value>,
    worker: JoinHandle<()>,
}

impl ControlPipe {
    fn start(state: Arc<LocalRuntimeState>) -> Self {
        let runtime = LocalRuntimeService {
            state,
            api_base_url: "http://127.0.0.1:1".into(),
        };
        let (input, mut incoming) = mpsc::channel::<Value>(16);
        let (outgoing, output) = mpsc::channel(16);
        let worker = tokio::spawn(async move {
            let mut requests = LocalControlRequests::default();
            while let Some(line) = incoming.recv().await {
                let request: ControlRequest =
                    serde_json::from_slice(&serde_json::to_vec(&line).unwrap()).unwrap();
                let response = match requests.dispatch(&runtime, &request, &outgoing).await {
                    Dispatch::Response(value) => serde_json::to_value(value).unwrap(),
                    Dispatch::Unhandled => panic!("unexpected fixture command"),
                    Dispatch::Pending => continue,
                };
                if outgoing.send(response).await.is_err() {
                    break;
                }
            }
            requests.shutdown().await;
        });
        Self {
            input,
            output,
            saved: HashMap::new(),
            worker,
        }
    }

    async fn send(&self, id: &str, command: &str, args: Value) {
        self.input
            .send(json!({"type":"request","id":id,"command":command,"args":args}))
            .await
            .unwrap();
    }

    async fn receive(&mut self, id: &str) -> Value {
        if let Some(response) = self.saved.remove(id) {
            return response;
        }
        tokio::time::timeout(Duration::from_secs(2), async {
            loop {
                let response = self.output.recv().await.unwrap();
                let actual = response["id"].as_str().unwrap().to_owned();
                if actual == id {
                    return response;
                }
                assert!(self.saved.insert(actual, response).is_none());
            }
        })
        .await
        .expect("control input blocked by an approval waiter")
    }

    async fn pending(
        &self,
        fixture: &FormalFixture,
    ) -> (
        Value,
        oneshot::Sender<CoreResult<Value>>,
        JoinHandle<CoreResult<Value>>,
    ) {
        let input = self.input.clone();
        let (release, wait) = oneshot::channel();
        let (pending, callback) = fixture.pending_with(&fixture.code(), move |_, arguments| {
            tokio::spawn(async move {
                input.send(json!({"type":"request","id":"callback","command":"mcp_app_operation","args":arguments})).await.unwrap();
                wait.await.unwrap()
            })
        }).await;
        (pending, release, callback)
    }

    async fn stop(
        self,
        release: oneshot::Sender<CoreResult<Value>>,
        callback: JoinHandle<CoreResult<Value>>,
    ) {
        drop(self.input);
        let _ = release.send(Err(CoreError::Tool("fixture stopped".into())));
        let _ = callback.await;
        self.worker.await.unwrap();
    }
}

fn cancel_input(fixture: &FormalFixture, request_id: &str, nonce: &str) -> Value {
    json!({"requestId":request_id,"tabId":fixture.renderer_id,"mountNonce":nonce})
}

#[tokio::test]
async fn formal_control_status_and_detach_remain_live_while_callback_waits_for_approval() {
    let fixture = FormalFixture::new().await;
    let mut pipe = ControlPipe::start(fixture.state.clone());
    let (pending, release, callback) = pipe.pending(&fixture).await;
    fixture.wait_for_approval(&pending).await;
    pipe.send("status", "local_runtime_status", json!({})).await;
    let status = pipe.receive("status").await;
    pipe.send(
        "detach",
        "mcp_app_operation",
        json!({"tabId":fixture.renderer_id,"operation":"detach","mountNonce":"fixture-mount"}),
    )
    .await;
    let detach = pipe.receive("detach").await;
    let attached =
        fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].attached;
    let counts = fixture.counts().await;
    pipe.stop(release, callback).await;
    fixture.finish(None).await;
    assert_eq!(status["ok"], true, "{status}");
    assert_eq!(detach["ok"], true, "{detach}");
    assert!(!attached);
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}

#[tokio::test]
async fn formal_control_exact_cancellation_ack_precedes_immediate_http_approval() {
    let fixture = FormalFixture::new().await;
    let mut pipe = ControlPipe::start(fixture.state.clone());
    let (pending, release, callback) = pipe.pending(&fixture).await;
    let request = fixture.wait_for_approval(&pending).await;
    let llm = fixture.llm(Some(fixture.code()));
    pipe.send(
        "wrong-mount",
        "mcp_app_operation_cancel",
        cancel_input(&fixture, "callback", "replaced-mount"),
    )
    .await;
    let wrong_mount = pipe.receive("wrong-mount").await;
    pipe.send(
        "wrong-id",
        "mcp_app_operation_cancel",
        cancel_input(&fixture, "another-callback", "fixture-mount"),
    )
    .await;
    let wrong_id = pipe.receive("wrong-id").await;
    pipe.send(
        "cancel",
        "mcp_app_operation_cancel",
        cancel_input(&fixture, "callback", "fixture-mount"),
    )
    .await;
    let cancel = pipe.receive("cancel").await;
    // No sleep/yield/receipt read: the next action after the cancellation ack is
    // the real authenticated approval handler and automatic engine continuation.
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    tokio::time::timeout(Duration::from_secs(25), llm.ready.notified())
        .await
        .unwrap();
    let result = pipe.receive("callback").await;
    let counts = fixture.counts().await;
    pipe.stop(release, callback).await;
    fixture.finish(Some(&llm)).await;
    assert_eq!(wrong_mount["ok"], false, "{wrong_mount}");
    assert_eq!(wrong_mount["error"], "mcp_app_cancel_mount_mismatch");
    assert_eq!(wrong_id["result"]["cancelled"], false, "{wrong_id}");
    assert_eq!(cancel["result"]["cancelled"], true, "{cancel}");
    assert_eq!(status, StatusCode::OK, "{receipt}");
    assert_eq!(result["ok"], false, "{result}");
    assert!(result["error"]
        .as_str()
        .unwrap()
        .contains("mcp_app_request_cancelled"));
    assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
}

#[tokio::test]
async fn formal_control_unmatched_cancellation_preserves_the_original_callback_once() {
    let fixture = FormalFixture::new().await;
    let mut pipe = ControlPipe::start(fixture.state.clone());
    let (pending, release, callback) = pipe.pending(&fixture).await;
    let request = fixture.wait_for_approval(&pending).await;
    let llm = fixture.llm(Some(fixture.code()));
    pipe.send(
        "wrong-mount",
        "mcp_app_operation_cancel",
        cancel_input(&fixture, "callback", "another-mount"),
    )
    .await;
    let rejected = pipe.receive("wrong-mount").await;
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    tokio::time::timeout(Duration::from_secs(25), llm.ready.notified())
        .await
        .unwrap();
    let result = pipe.receive("callback").await;
    let counts = fixture.counts().await;
    let transcript = llm.observed.lock().unwrap().clone();
    pipe.stop(release, callback).await;
    fixture.finish(Some(&llm)).await;
    assert_eq!(rejected["ok"], false, "{rejected}");
    assert_eq!(status, StatusCode::OK, "{receipt}");
    assert_eq!(result["ok"], true, "{result}");
    assert_eq!(payload(&result["result"])["counts"]["main"], 1);
    assert_eq!(counts, json!({"main":1,"sibling":0,"hidden":0}));
    let observed = transcript
        .iter()
        .filter_map(|entry| serde_json::from_str::<Value>(entry).ok())
        .find(|value| value["cell_id"] == pending["repl_continuation"]["cell_id"])
        .unwrap();
    assert_eq!(observed["ok"], true, "{observed}");
    assert_eq!(
        observed["value"][0], 1,
        "the original Node cell must start once"
    );
}

#[tokio::test]
async fn formal_control_callback_limit_includes_completed_but_undelivered_responses() {
    let (state, _, _, root) = cua_repl::test_support::state(LAUNCH);
    let runtime = LocalRuntimeService {
        state,
        api_base_url: "http://127.0.0.1:1".into(),
    };
    let mut requests = LocalControlRequests::default();
    let (outgoing, mut receiver) = mpsc::channel(1);
    outgoing
        .send(json!({"fixture":"backpressure"}))
        .await
        .unwrap();
    let input = |id: &str| {
        serde_json::from_value::<ControlRequest>(json!({"type":"request","id":id,"command":"mcp_app_operation","args":{"operation":"tools/call","tabId":"unknown-tab","mountNonce":"fixture-mount","arguments":{}}})).unwrap()
    };
    for index in 0..32 {
        assert!(matches!(
            requests
                .dispatch(&runtime, &input(&format!("callback-{index}")), &outgoing)
                .await,
            Dispatch::Pending
        ));
    }
    // Each invalid App lookup has finished; its response cannot be delivered.
    // Joining cancellation waits for that exact finished marker without draining output.
    let cancel: ControlRequest = serde_json::from_value(json!({"type":"request","id":"cancel","command":"mcp_app_operation_cancel","args":{"requestId":"callback-0","tabId":"unknown-tab","mountNonce":"fixture-mount"}})).unwrap();
    assert!(matches!(
        requests.dispatch(&runtime, &cancel, &outgoing).await,
        Dispatch::Response(_)
    ));
    let duplicate = requests
        .dispatch(&runtime, &input("callback-0"), &outgoing)
        .await;
    let overflow = requests
        .dispatch(&runtime, &input("overflow"), &outgoing)
        .await;
    requests.shutdown().await;
    receiver.close();
    runtime.state.cua_repl.shutdown();
    std::fs::remove_dir_all(root).unwrap();
    let Dispatch::Response(duplicate) = duplicate else {
        panic!("duplicate request admitted")
    };
    let Dispatch::Response(overflow) = overflow else {
        panic!("response backpressure bypassed callback limit")
    };
    assert_eq!(
        serde_json::to_value(duplicate).unwrap()["error"],
        "mcp_app_request_id_active"
    );
    assert_eq!(
        serde_json::to_value(overflow).unwrap()["error"],
        "mcp_app_callback_limit"
    );
}
