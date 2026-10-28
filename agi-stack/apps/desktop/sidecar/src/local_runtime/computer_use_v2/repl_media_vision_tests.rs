//! Public screenshot bytes cross real Node, scoped storage, and the HTTP model boundary.
use super::*;
use crate::local_runtime::{
    computer_use_v2::{call_identity, cloud_tests},
    cua_repl,
    knowledge_authority_v2::agent_access::{self, RunAuthorization},
};
use agistack_adapters_browser::{BridgeEndpoint, BrowserToolHost, protocol::BridgeNotification};
use agistack_adapters_http_llm::HttpLlm;
use agistack_core::{
    agent::{
        tool_policy::ToolPolicyContext,
        types::{Role, TranscriptEntry},
    },
    ports::{LlmPort, ToolHost},
};
use async_trait::async_trait;
use axum::{Json, Router, extract::State, routing::post};
use base64::{Engine, engine::general_purpose::STANDARD};
use std::sync::{Arc, Mutex};
use tokio::sync::broadcast;

struct ScreenshotEndpoint(String);

#[async_trait]
impl BridgeEndpoint for ScreenshotEndpoint {
    async fn request(&self, method: &str, params: Value) -> CoreResult<Value> {
        if method == "getTabs" {
            return Ok(
                json!({"tabs":[{"tabId":7,"title":"Owned fixture","url":"https://fixture.test/","active":false}]}),
            );
        }
        if method == "attach" {
            return Ok(json!({}));
        }
        assert_eq!(method, "executeCdp");
        let result = match params["method"].as_str().unwrap() {
            "Page.getFrameTree" => json!({"frameTree":{"frame":{"id":"main"}}}),
            "Page.createIsolatedWorld" => json!({"executionContextId":1}),
            "Runtime.evaluate" => json!({"result":{"value":"Owned fixture"}}),
            "Page.getLayoutMetrics" => {
                json!({"cssLayoutViewport":{"clientWidth":2,"clientHeight":2}})
            }
            "Page.captureScreenshot" => {
                assert_eq!(params["params"]["format"], "jpeg");
                json!({"data":self.0})
            }
            method => panic!("unexpected screenshot CDP method: {method}"),
        };
        Ok(json!({"result":result}))
    }

    fn scoped_browsers(&self) -> Option<Value> {
        Some(json!([{"id":"chrome","type":"chrome"}]))
    }

    fn subscribe_notifications(&self) -> broadcast::Receiver<BridgeNotification> {
        broadcast::channel(1).1
    }
}

async fn capture_model_request(
    State(requests): State<Arc<Mutex<Vec<Value>>>>,
    Json(body): Json<Value>,
) -> Json<Value> {
    requests.lock().unwrap().push(body);
    Json(
        json!({"choices":[{"message":{"content":"{\"kind\":\"finish\",\"answer\":\"image accepted\"}"}}]}),
    )
}

#[tokio::test]
async fn bare_browser_jpeg_is_scoped_and_reaches_model_as_jpeg() {
    let token = "local-repl-screenshot-vision";
    let (state, conversation, run, root) = cua_repl::test_support::state(token);
    cloud_tests::publish_factory(&state, true).await;
    let auth = state
        .session_store
        .validate_session_credential(token, chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let owner = Owner {
        user_id: auth.user.user_id.clone(),
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: auth.workspace.project_id.clone(),
        device_id: state.session_store.installation_id().into(),
    };
    let authorization = RunAuthorization::capture(
        auth,
        Some(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap()
                .into(),
        ),
        &conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    let _control = state
        .claim_agent_run(&conversation.id, Some(&run.id))
        .unwrap();
    let profile = state.execution_profile(&conversation).unwrap();
    let mut encoded = std::io::Cursor::new(Vec::new());
    image::DynamicImage::new_rgb8(2, 2)
        .write_to(&mut encoded, image::ImageFormat::Jpeg)
        .unwrap();
    let jpeg = encoded.into_inner();
    let browser: Arc<dyn ToolHost> = Arc::new(BrowserToolHost::new(ScreenshotEndpoint(
        STANDARD.encode(&jpeg),
    )));
    let result = agent_access::scope(Some(authorization), async {
        let host = cua_repl::wrap_tools(&state, browser, &conversation, &run, &profile, None);
        let context = ToolPolicyContext {
            session_id: "screenshot-vision-engine",
            round: 1,
            tool: "cua_repl_js",
        };
        let bind = call_identity::scope(
            &context,
            host.call_with_content(
                "cua_repl_js",
                &json!({"code":"var qaTab = await cua.getTab(\"7\", {browser:\"chrome\"});"}).to_string(),
            ),
        )
        .await
        .unwrap();
        let bind_output: Value = serde_json::from_str(&bind.output_json).unwrap();
        assert_eq!(bind_output["ok"], true, "{bind_output}");
        call_identity::scope(
            &context,
            host.call_with_content(
                "cua_repl_js",
                &json!({"code":"var qaScreenshot = await qaTab.screenshot(); nodeRepl.emitImage(qaScreenshot);"}).to_string(),
            ),
        )
        .await
        .unwrap()
    })
    .await;
    let output: Value = serde_json::from_str(&result.output_json).unwrap();
    assert_eq!(output["ok"], true, "{output}");
    assert_eq!(result.media.len(), 1);
    let media = &result.media[0];
    assert_eq!(media.mime_type, "image/jpeg");
    assert_eq!(
        std::path::Path::new(&media.artifact_path)
            .extension()
            .unwrap(),
        "jpg"
    );
    assert_eq!(std::fs::read(&media.artifact_path).unwrap(), jpeg);
    let descriptor = &output["artifacts"][0];
    assert_eq!(descriptor["mime_type"], "image/jpeg");
    assert_eq!(descriptor["kind"], "image");
    let id = descriptor["artifact_id"].as_str().unwrap();
    assert_eq!(
        artifacts::attachment(&state, &owner, &conversation.id, id).unwrap(),
        *media
    );
    assert!(artifacts::attachment(&state, &owner, "other-conversation", id).is_err());
    let mut foreign = owner.clone();
    foreign.user_id = "other-user".into();
    assert!(artifacts::preview(&state, &foreign, id).is_err());
    state.cua_repl.shutdown();
    assert!(
        artifacts::preview(&state, &owner, id).unwrap()["data_url"]
            .as_str()
            .unwrap()
            .starts_with("data:image/jpeg;base64,")
    );

    let requests = Arc::new(Mutex::new(Vec::new()));
    let app = Router::new()
        .route("/chat/completions", post(capture_model_request))
        .with_state(requests.clone());
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let model = HttpLlm::new(format!("http://{address}"), "fixture-vision");
    let transcript = vec![
        TranscriptEntry::new(1, Role::Observation, result.output_json).with_media(result.media),
    ];
    model
        .decide_with_tools("Inspect the screenshot", 2, &transcript, &[])
        .await
        .unwrap();
    assert_eq!(requests.lock().unwrap().len(), 1);
    assert_eq!(
        requests.lock().unwrap()[0]["messages"][1]["content"][1]["image_url"]["url"],
        format!("data:image/jpeg;base64,{}", STANDARD.encode(&jpeg))
    );
    server.abort();
    drop(state);
    std::fs::remove_dir_all(root).unwrap();
}
