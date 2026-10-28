use super::*;
use agistack_adapters_mem::InMemoryObjectStore;
use agistack_core::{
    agent::types::{Role, TranscriptEntry},
    ports::LlmPort,
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use tokio::sync::mpsc;
#[path = "resume_authority_tests.rs"]
mod resume_authority_tests;
#[path = "control_tests.rs"]
mod control_tests;
#[path = "steps_tests.rs"]
mod steps_tests;
#[path = "outer_permission_tests.rs"]
mod outer_permission_tests;
#[path = "audio_tests.rs"]
mod audio_tests;
#[path = "permission_tests.rs"]
mod permission_tests;
const PNG: &str =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=";
struct Authority {
    current: std::sync::atomic::AtomicBool,
    running: std::sync::atomic::AtomicBool,
}
#[async_trait]
impl authority::Authority for Authority {
    async fn prepare(
        &self,
        _: &Owner,
        _: &str,
        _: &str,
        _: &str,
    ) -> CoreResult<authority::RunAuthority> {
        Ok(run())
    }
    async fn recheck(&self, _: &Owner, _: &str, _: &authority::RunAuthority) -> CoreResult<()> {
        if self.current.load(std::sync::atomic::Ordering::SeqCst) {
            Ok(())
        } else {
            Err(CoreError::Tool("fixture_authority_revoked".into()))
        }
    }
    async fn recheck_running(
        &self,
        owner: &Owner,
        conversation: &str,
        run: &authority::RunAuthority,
    ) -> CoreResult<()> {
        if !self.running.load(std::sync::atomic::Ordering::SeqCst) {
            return Err(CoreError::Tool("fixture_run_not_running".into()));
        }
        self.recheck(owner, conversation, run).await
    }
}
fn run() -> authority::RunAuthority {
    authority::RunAuthority {
        run_id: "run".into(),
        run_kind: "plan".into(),
        permission_profile: "full_access".into(),
        authorization_revision: 3,
        plan_version_id: "approved-plan".into(),
        allowed_mcp_servers: vec![],
        agent_profile: agent_profile::AgentProfile {
            source: "fixture".into(),
            selected_agent_id: None,
            allowed_tools: None,
            allowed_mcp_servers: vec![],
        },
    }
}
fn owner() -> Owner {
    Owner {
        user_id: "user".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    }
}
fn fixture() -> (Broker, Arc<Authority>, mpsc::Receiver<Value>) {
    let authority = Arc::new(Authority {
        current: std::sync::atomic::AtomicBool::new(true),
        running: std::sync::atomic::AtomicBool::new(true),
    });
    let broker = Broker::new(authority.clone(), Arc::new(InMemoryObjectStore::new()));
    let (send, receive) = mpsc::channel(16);
    broker.devices.lock().unwrap().insert(
        "connection".into(),
        broker::Device {
            connection_id: "connection".into(),
            owner: owner(),
            device_id: "device".into(),
            tools: vec![
                ToolDefinition::name_only("computer_get_app_state"),
                ToolDefinition::name_only("computer_click"),
            ],
            send,
        },
    );
    (broker, authority, receive)
}
fn context(round: u64, tool: &str) -> CallIdentity {
    CallIdentity {
        session_id: "engine-session".into(),
        round,
        tool: tool.into(),
    }
}
fn dispatch(
    broker: &Broker,
    round: u64,
    tool: &str,
    input: &str,
) -> tokio::task::JoinHandle<CoreResult<ToolResult>> {
    let broker = broker.clone();
    let context = context(round, tool);
    let input = input.to_owned();
    tokio::spawn(async move {
        broker
            .request(&owner(), "conversation", &run(), &context, &input)
            .await
    })
}
#[tokio::test]
async fn read_only_connector_effect_is_exact_and_claim_rechecks_changed_catalog() {
    let (broker, _, mut receive) = fixture();
    let row = json!({"provider":"google","account_id":"account","server_id":"server","server_name":"server-display","managed_account":true,"connector":"calendar","operation":"opaque.17","effect":"read"});
    let schema = json!({agistack_adapters_cua::CONNECTOR_OPERATION_EFFECTS:[row]});
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .push(ToolDefinition::new(
            "computer_connector_call",
            "Declared operations",
            schema,
        ));
    let mut authority = run();
    authority.permission_profile = "read_only".into();
    let input=json!({"provider":"google","account_id":"account","connector":"calendar","operation":"opaque.17","arguments":{}}).to_string();
    let call_context = context(1, "computer_connector_call");
    let cloned = broker.clone();
    let cloned_authority = authority.clone();
    let cloned_input = input.clone();
    let call = tokio::spawn(async move {
        cloned
            .request(
                &owner(),
                "conversation",
                &cloned_authority,
                &call_context,
                &cloned_input,
            )
            .await
    });
    let request = receive.recv().await.unwrap();
    let id = request["request_id"].as_str().unwrap();
    let mut devices = broker.devices.lock().unwrap();
    let schema = devices
        .get_mut("connection")
        .unwrap()
        .tools
        .last_mut()
        .unwrap()
        .input_schema
        .as_mut()
        .unwrap();
    schema[agistack_adapters_cua::CONNECTOR_OPERATION_EFFECTS][0]["effect"] = json!("mutate");
    drop(devices);
    assert!(broker.claim(id, "user", "device").is_err());
    assert!(broker
        .request(
            &owner(),
            "conversation",
            &authority,
            &context(2, "computer_connector_call"),
            &input
        )
        .await
        .is_err());
    let unknown=json!({"provider":"google","account_id":"account","connector":"calendar","operation":"read_calendar_by_name","arguments":{}}).to_string();
    assert!(broker
        .request(
            &owner(),
            "conversation",
            &authority,
            &context(3, "computer_connector_call"),
            &unknown
        )
        .await
        .is_err());
    call.abort();
    broker.disconnect("connection");
}
#[tokio::test]
async fn socket_owner_claim_typed_media_and_real_provider_image_blocks_round_trip() {
    let (broker, _, mut receive) = fixture();
    let call = dispatch(&broker, 1, "computer_get_app_state", "{}");
    let control = receive.recv().await.unwrap();
    let id = control["request_id"].as_str().unwrap();
    assert_eq!(control["type"], "computer_use_request");
    assert_eq!(control.as_object().unwrap().len(), 3);
    assert!(control["expires_at"].as_i64().is_some());
    assert!(broker.claim(id, "other-user", "device").is_err());
    let (claim, _, _) = broker.claim(id, "user", "device").unwrap();
    assert_eq!(claim.run_id, "run");
    assert_eq!(claim.round, 1);
    assert_eq!(claim.authorization_revision, 3);
    assert!(broker.claim(id, "user", "device").is_err());
    let descriptor = broker::Descriptor {
        artifact_id: "artifact".into(),
        mime_type: "image/png".into(),
        size_bytes: STANDARD.decode(PNG).unwrap().len() as u64,
    };
    assert!(broker
        .receive_result("foreign", id, "{}".into(), false, vec![descriptor.clone()])
        .is_err());
    assert!(broker
        .receive_result(
            "connection",
            id,
            "{\"screenshot\":{\"artifact_id\":\"artifact\"}}".into(),
            false,
            vec![descriptor]
        )
        .unwrap());
    assert!(broker
        .receive_media("connection", id, "artifact", "image/png", 1, PNG, true)
        .is_err());
    assert!(broker
        .receive_media("connection", id, "artifact", "image/png", 0, PNG, true)
        .unwrap());
    broker.complete(id).await.unwrap();
    let result = call.await.unwrap().unwrap();
    assert_eq!(result.media.len(), 1);
    assert_eq!(
        std::fs::read(&result.media[0].artifact_path).unwrap(),
        STANDARD.decode(PNG).unwrap()
    );
    assert!(!result.output_json.contains("artifact_path"));
    // The cloud LLM transport reads the image artifact and sends actual pixels.
    let captured = Arc::new(Mutex::new(Value::Null));
    let capture = captured.clone();
    let router=axum::Router::new().route("/chat/completions",post(move |Json(body):Json<Value>|{let capture=capture.clone();async move{*capture.lock().unwrap()=body;Json(json!({"choices":[{"message":{"content":"{\"kind\":\"finish\",\"answer\":\"visible\"}"}}]}))}}));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    let transcript = vec![
        TranscriptEntry::new(1, Role::Observation, result.output_json.clone())
            .with_media(result.media.clone()),
    ];
    let model =
        agistack_adapters_http_llm::HttpLlm::new(format!("http://{address}"), "fixture-vision");
    model
        .decide_with_tools("read image", 2, &transcript, &[])
        .await
        .unwrap();
    let body = captured.lock().unwrap();
    let content = body["messages"]
        .as_array()
        .unwrap()
        .iter()
        .find_map(|message| message["content"].as_array())
        .unwrap();
    let image = content
        .iter()
        .find(|item| item["type"] == "image_url")
        .unwrap();
    assert_eq!(
        image["image_url"]["url"],
        format!("data:image/png;base64,{PNG}")
    );
    drop(body);
    server.abort();
    let replay = broker
        .request(
            &owner(),
            "conversation",
            &run(),
            &context(1, "computer_get_app_state"),
            "{}",
        )
        .await
        .unwrap();
    assert_eq!(replay, result);
    assert!(receive.try_recv().is_err());
    let root = broker.cache.lock().unwrap().clone().unwrap();
    std::fs::remove_dir_all(root).unwrap();
}

#[tokio::test]
async fn cancellation_marks_unknown_and_changed_tool_or_arguments_cannot_repeat_a_call() {
    let (broker, _, mut receive) = fixture();
    let call = dispatch(&broker, 1, "computer_click", "{\"x\":1}");
    let control = receive.recv().await.unwrap();
    let id = control["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    call.abort();
    let _ = call.await;
    assert_eq!(receive.recv().await.unwrap()["type"], "computer_use_cancel");
    assert!(broker
        .request(
            &owner(),
            "conversation",
            &run(),
            &context(1, "computer_click"),
            "{\"x\":1}"
        )
        .await
        .unwrap_err()
        .to_string()
        .contains("outcome_unknown"));
    for (tool, input) in [
        ("computer_click", "{\"x\":2}"),
        ("computer_get_app_state", "{\"x\":1}"),
    ] {
        assert!(broker
            .request(&owner(), "conversation", &run(), &context(1, tool), input)
            .await
            .unwrap_err()
            .to_string()
            .contains("identity_conflict"));
    }
    let next = dispatch(&broker, 2, "computer_click", "{\"x\":1}");
    let second = receive.recv().await.unwrap();
    assert_ne!(second["request_id"], control["request_id"]);
    next.abort();
    let _ = next.await;
}

#[tokio::test]
async fn read_only_ceiling_and_revoked_run_prevent_device_dispatch() {
    let (broker, authority, mut receive) = fixture();
    let mut readonly = run();
    readonly.permission_profile = "read_only".into();
    assert!(broker
        .request(
            &owner(),
            "conversation",
            &readonly,
            &context(1, "computer_click"),
            "{}"
        )
        .await
        .unwrap_err()
        .to_string()
        .contains("permission_denied"));
    authority
        .current
        .store(false, std::sync::atomic::Ordering::SeqCst);
    assert!(broker
        .request(
            &owner(),
            "conversation",
            &run(),
            &context(1, "computer_get_app_state"),
            "{}"
        )
        .await
        .is_err());
    assert!(receive.try_recv().is_err());
}

#[tokio::test]
async fn media_size_offset_disconnect_and_error_results_are_enforced() {
    let (broker, _, mut receive) = fixture();
    let call = dispatch(&broker, 1, "computer_get_app_state", "{}");
    let control = receive.recv().await.unwrap();
    let id = control["request_id"].as_str().unwrap();
    broker.claim(id, "user", "device").unwrap();
    let oversized = broker::Descriptor {
        artifact_id: "audio".into(),
        mime_type: "audio/wav".into(),
        size_bytes: 65 * 1024 * 1024,
    };
    assert!(broker
        .receive_result("connection", id, "{}".into(), false, vec![oversized])
        .is_err());
    broker
        .receive_result(
            "connection",
            id,
            "{\"error\":\"fixture_denied\"}".into(),
            true,
            vec![],
        )
        .unwrap();
    assert!(call
        .await
        .unwrap()
        .unwrap_err()
        .to_string()
        .contains("fixture_denied"));
    assert_eq!(receive.recv().await.unwrap()["type"], "computer_use_cancel");
    let next = dispatch(&broker, 2, "computer_get_app_state", "{}");
    let _ = receive.recv().await.unwrap();
    broker.disconnect("connection");
    assert!(next
        .await
        .unwrap()
        .unwrap_err()
        .to_string()
        .contains("outcome_unknown"));
}

#[tokio::test]
async fn outer_mcp_claim_pins_catalog_and_requires_current_roster_and_permission() {
    let (broker, _, mut receive) = fixture();
    let binding = json!({"server_id":"owned","server_name":"owned-server","revision":1,"catalog_digest":"catalog-1"});
    broker.devices.lock().unwrap().get_mut("connection").unwrap().tools.push(
        ToolDefinition::new("mcp_owned", "Owned MCP", json!({"type":"object",catalog::MCP_BINDING:binding})),
    );
    let mut authority = run();
    authority.allowed_mcp_servers = vec!["owned".into()];
    authority.agent_profile.allowed_mcp_servers = authority.allowed_mcp_servers.clone();
    let call_context = context(1,"mcp_owned");
    let copied = broker.clone();
    let allowed = authority.clone();
    let task = tokio::spawn(async move {
        copied.request(&owner(),"conversation",&allowed,&call_context,"{\"value\":1}").await
    });
    let event = receive.recv().await.unwrap();
    let id = event["request_id"].as_str().unwrap();
    let (claim, _, _) = broker.claim(id,"user","device").unwrap();
    assert_eq!(event["expires_at"], claim.expires_at);
    assert_eq!(claim.mcp_binding,Some(binding.clone()));
    assert_eq!(claim.input_json,"{\"value\":1}");
    task.abort(); let _ = task.await;
    let mut denied = authority.clone();
    denied.allowed_mcp_servers.clear();
    assert!(broker.request(&owner(),"conversation",&denied,&context(2,"mcp_owned"),"{}").await.is_err());
    denied = authority.clone(); denied.permission_profile = "read_only".into();
    let pending = broker.request(&owner(),"conversation",&denied,&context(3,"mcp_owned"),"{}").await.unwrap();
    assert_eq!(serde_json::from_str::<Value>(&pending.output_json).unwrap()["error"], "cua_permission_required");
    let copied = broker.clone(); let allowed = authority.clone();
    let task = tokio::spawn(async move {copied.request(&owner(),"conversation",&allowed,&context(4,"mcp_owned"),"{}").await});
    // Aborting the prior request also sends cancellation; consume only the next request.
    let next = loop { let event = receive.recv().await.unwrap(); if event["type"]=="computer_use_request" {break event;} };
    {
        let mut devices = broker.devices.lock().unwrap();
        let schema = devices.get_mut("connection").unwrap().tools.last_mut().unwrap().input_schema.as_mut().unwrap();
        schema[catalog::MCP_BINDING]["catalog_digest"] = json!("catalog-2");
    }
    assert!(broker.claim(next["request_id"].as_str().unwrap(),"user","device").is_err());
    task.abort(); let _ = task.await;
    broker.devices.lock().unwrap().get_mut("connection").unwrap().tools.last_mut().unwrap().input_schema.as_mut().unwrap()[catalog::STEP_ONLY] = json!(true);
    assert!(broker.request(&owner(),"conversation",&authority,&context(5,"mcp_owned"),"{}").await.unwrap_err().to_string().contains("step_context_required"));
}

#[path = "repl_media_tests.rs"]
mod repl_media_tests;

#[path = "repl_wire_tests.rs"]
mod repl_wire_tests;
