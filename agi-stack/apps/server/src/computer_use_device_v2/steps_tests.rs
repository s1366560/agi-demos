use super::*;

fn register_steps(broker: &Broker) {
    broker.devices.lock().unwrap().get_mut("connection").unwrap().tools.extend([
        ToolDefinition::new("cua_repl_js", "Cell", json!({"type":"object","required":["code"],"properties":{"code":{"type":"string"}}})),
        ToolDefinition::new("browser_read_operation", "Read", json!({"type":"object"})),
        ToolDefinition::new("browser_write_operation", "Write", json!({"type":"object"})),
    ]);
}
fn body(tool: &str, operation: &str) -> Value {
    json!({"device_id":"device","cell_id":"cell","tool_name":tool,"input_json":json!({"operation":operation,"args":[]}).to_string(),
        "target":{"kind":"browser","id":"iab/1","browser_id":"iab","tab_id":"1"}})
}
async fn outer(
    broker: &Broker,
    receive: &mut mpsc::Receiver<Value>,
    round: u64,
    revision: i32,
) -> (String, tokio::task::JoinHandle<CoreResult<ToolResult>>) {
    let mut authority = run();
    authority.permission_profile = "read_only".into();
    authority.authorization_revision = revision;
    let broker = broker.clone();
    let call = tokio::spawn(async move {
        broker
            .request(
                &owner(),
                "conversation",
                &authority,
                &context(round, "cua_repl_js"),
                r#"{"code":"await fixture()"}"#,
            )
            .await
    });
    let id = receive.recv().await.unwrap()["request_id"]
        .as_str()
        .unwrap()
        .to_owned();
    (id, call)
}
async fn authorize(broker: &Broker, id: &str, step: &str, input: Value) -> CoreResult<Value> {
    broker
        .authorize_step("user", id, step, serde_json::from_value(input).unwrap())
        .await
}
fn finish(broker: &Broker, id: &str, output: Value) {
    broker
        .receive_result("connection", id, output.to_string(), false, vec![])
        .unwrap();
}

#[tokio::test]
async fn step_pending_exact_approval_new_outer_and_one_use_receipt() {
    let (broker, _, mut receive) = fixture();
    register_steps(&broker);
    let (id, call) = outer(&broker, &mut receive, 1, 3).await;
    let (claim, _, _) = broker.claim(&id, "user", "device").unwrap();
    let input = body("browser_write_operation", "tab.goto");
    let pending = authorize(&broker, &id, "step", input.clone())
        .await
        .unwrap();
    assert_eq!(pending["status"], "pending");
    let stored = broker
        .verify_pending_step(&claim, &pending["request"])
        .await
        .unwrap();
    finish(&broker, &id, pending);
    call.await.unwrap().unwrap();
    broker.resolve_step_permission(&stored, true, "committed-hitl").await.unwrap();
    let (next, next_call) = outer(&broker, &mut receive, 2, 3).await;
    broker.claim(&next, "user", "device").unwrap();
    let mut input = input;
    input["parent_request_id"] = json!(id);
    let ready = authorize(&broker, &next, "step", input.clone())
        .await
        .unwrap();
    let continuation = ready["continuation"].clone();
    assert_eq!(continuation, json!({"kind":"hitl","hitl_request_id":"committed-hitl",
        "origin_request_id":id,"previous_authorization_revision":3,"authorization_revision":3,
        "cell_id":"cell","step_id":"step"}));
    input["receipt"] = ready["receipt"].clone();
    let consumed = authorize(&broker, &next, "step", input.clone()).await.unwrap();
    assert_eq!(consumed["status"], "authorized");
    assert_eq!(consumed["continuation"], continuation);
    assert!(authorize(&broker, &next, "step", input).await.is_err());
    let mut release = body("browser_write_operation", "tab.goto");
    release["parent_request_id"] = json!(id);
    release["receipt"] = ready["receipt"].clone();
    release["outcome"] = json!("not_sent");
    let released = authorize(&broker, &next, "step", release).await.unwrap();
    assert_eq!(released["status"], "released");
    assert!(released.get("continuation").is_none());
    finish(&broker, &next, json!({}));
    next_call.await.unwrap().unwrap();
}

#[tokio::test]
async fn step_known_not_sent_release_rebases_only_exact_operation() {
    let (broker, _, mut receive) = fixture();
    register_steps(&broker);
    let (id, call) = outer(&broker, &mut receive, 1, 3).await;
    broker.claim(&id, "user", "device").unwrap();
    let mut input = body("browser_read_operation", "playwright.domSnapshot");
    let ready = authorize(&broker, &id, "step", input.clone())
        .await
        .unwrap();
    assert!(ready.get("continuation").is_none());
    input["receipt"] = ready["receipt"].clone();
    authorize(&broker, &id, "step", input.clone())
        .await
        .unwrap();
    input["outcome"] = json!("unknown");
    assert!(authorize(&broker, &id, "step", input.clone())
        .await
        .is_err());
    input["outcome"] = json!("not_sent");
    assert_eq!(
        authorize(&broker, &id, "step", input.clone())
            .await
            .unwrap()["status"],
        "released"
    );
    finish(&broker, &id, json!({"error":"cua_permission_required"}));
    call.await.unwrap().unwrap();
    let (next, next_call) = outer(&broker, &mut receive, 2, 4).await;
    broker.claim(&next, "user", "device").unwrap();
    input.as_object_mut().unwrap().remove("receipt");
    input.as_object_mut().unwrap().remove("outcome");
    input["parent_request_id"] = json!(id);
    let mut changed = input.clone();
    changed["target"]["id"] = json!("foreign");
    assert!(authorize(&broker, &next, "step", changed).await.is_err());
    let ready = authorize(&broker, &next, "step", input.clone())
        .await
        .unwrap();
    assert_eq!(ready["authorization_revision"], 4);
    assert!(ready.get("continuation").is_none());
    input["receipt"] = ready["receipt"].clone();
    assert_eq!(
        authorize(&broker, &next, "step", input).await.unwrap()["status"],
        "authorized"
    );
    finish(&broker, &next, json!({}));
    next_call.await.unwrap().unwrap();
}

#[tokio::test]
async fn step_scope_catalog_and_cancel_are_checked_before_dispatch() {
    let (broker, authority, mut receive) = fixture();
    register_steps(&broker);
    let (id, call) = outer(&broker, &mut receive, 1, 3).await;
    broker.claim(&id, "user", "device").unwrap();
    assert!(authorize(
        &broker,
        &id,
        "forged",
        body("browser_read_operation", "tab.close")
    )
    .await
    .is_err());
    let input = body("browser_read_operation", "playwright.domSnapshot");
    let ready = authorize(&broker, &id, "step", input.clone())
        .await
        .unwrap();
    let mut consume = input.clone();
    consume["receipt"] = ready["receipt"].clone();
    broker
        .devices
        .lock()
        .unwrap()
        .get_mut("connection")
        .unwrap()
        .tools
        .iter_mut()
        .find(|tool| tool.name == "browser_read_operation")
        .unwrap()
        .description = Some("Changed".into());
    assert!(authorize(&broker, &id, "step", consume).await.is_err());
    authority
        .current
        .store(false, std::sync::atomic::Ordering::SeqCst);
    assert!(authorize(&broker, &id, "another", input.clone())
        .await
        .is_err());
    authority
        .current
        .store(true, std::sync::atomic::Ordering::SeqCst);
    broker.cancel(&id);
    assert!(authorize(&broker, &id, "another", input).await.is_err());
    call.abort();
}

#[test]
fn dynamic_mcp_is_mutating_and_requires_declared_allowed_server() {
    let definition = catalog::validate_definition(&json!({"name":"mcp__fixture","description":"Fixture","inputSchema":{"type":"object","x-cua-step-only":true,
        "x-cua-mcp-binding":{"server_id":"server","server_name":"fixture","revision":1,"catalog_digest":"digest"}},"annotations":{"readOnlyHint":true}})).unwrap();
    assert!(catalog::validate_call(&definition, &json!({}), &[]).is_err());
    assert!(matches!(
        catalog::validate_call(&definition, &json!({}), &["server".into()]).unwrap(),
        catalog::Effect::Mutate
    ));
    assert!(catalog::validate_definition(
        &json!({"name":"arbitrary","description":"Bad","inputSchema":{"type":"object"}})
    )
    .is_err());
}

#[tokio::test]
async fn step_http_route_pending_resume_consumption_and_cancel() {
    let (broker, _, mut receive) = fixture();
    register_steps(&broker);
    let router = Router::new()
        .route(
            "/requests/:request_id/steps/:step_id/authorize",
            post(steps::authorize),
        )
        .layer(Extension(Identity {
            user_id: "user".into(),
            _api_key_id: "fixture".into(),
        }))
        .with_state(steps::StepState(broker.clone()));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move { axum::serve(listener, router).await.unwrap() });
    let client = reqwest::Client::new();
    let (id, call) = outer(&broker, &mut receive, 1, 3).await;
    let (claim, _, _) = broker.claim(&id, "user", "device").unwrap();
    let endpoint = format!("http://{address}/requests/{id}/steps/step/authorize");
    let mut input = body("browser_write_operation", "tab.reload");
    let denied = client.post(&endpoint).json(&json!({"device_id":"foreign","cell_id":"cell","tool_name":"browser_write_operation","input_json":"{}","target":{"kind":"browser","id":"iab/1"}})).send().await.unwrap();
    assert_eq!(denied.status(), reqwest::StatusCode::CONFLICT);
    let pending: Value = client
        .post(&endpoint)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(pending["status"], "pending");
    let stored = broker
        .verify_pending_step(&claim, &pending["request"])
        .await
        .unwrap();
    finish(&broker, &id, pending);
    call.await.unwrap().unwrap();
    broker.resolve_step_permission(&stored, true, "committed-hitl-http").await.unwrap();
    let (next, next_call) = outer(&broker, &mut receive, 2, 3).await;
    broker.claim(&next, "user", "device").unwrap();
    input["parent_request_id"] = json!(id);
    let endpoint = format!("http://{address}/requests/{next}/steps/step/authorize");
    let ready: Value = client
        .post(&endpoint)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    input["receipt"] = ready["receipt"].clone();
    let consumed: Value = client
        .post(&endpoint)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(consumed["status"], "authorized");
    assert_eq!(
        client
            .post(&endpoint)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        reqwest::StatusCode::CONFLICT
    );
    input["outcome"] = json!("not_sent");
    let released: Value = client
        .post(&endpoint)
        .json(&input)
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(released["status"], "released");
    broker.cancel(&next);
    assert_eq!(
        client
            .post(&endpoint)
            .json(&input)
            .send()
            .await
            .unwrap()
            .status(),
        reqwest::StatusCode::CONFLICT
    );
    next_call.abort();
    server.abort();
}

#[test]
fn step_request_transport_covers_the_requested_cell_timeout() {
    assert_eq!(
        catalog::request_timeout("cua_repl_js", r#"{"timeout_ms":300000}"#)
            .unwrap()
            .as_secs(),
        315
    );
    assert_eq!(
        catalog::request_timeout("computer_get_app_state", "{}")
            .unwrap()
            .as_secs(),
        90
    );
    assert!(catalog::request_timeout("cua_repl_js", r#"{"timeout_ms":false}"#).is_err());
}
