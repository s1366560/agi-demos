use super::super::*;
use super::*;

#[tokio::test]
async fn service_ensure_get_restart_and_terminate_lifecycle() {
    let service = with_test_runtime_auth(ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "redis:7-alpine",
    ));

    assert!(service.get("p1").await.unwrap().is_none());

    let created = service
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap();
    assert_eq!(created.project_id, "p1");
    assert_eq!(created.tenant_id, "t1");
    assert_eq!(created.profile, SandboxProfile::Lite);
    assert_eq!(created.status_str(), "running");
    assert!(created.healthy());

    let fetched = service.get("p1").await.unwrap().unwrap();
    assert_eq!(fetched.sandbox_id, created.sandbox_id);

    let restarted = service.restart("p1").await.unwrap();
    assert_eq!(restarted.sandbox_id, created.sandbox_id);
    assert_eq!(restarted.status_str(), "running");

    assert!(service.terminate("p1").await.unwrap());
    assert!(!service.terminate("p1").await.unwrap());
    assert!(service.get("p1").await.unwrap().is_none());
}
#[tokio::test]
async fn service_cloud_ensure_fails_closed_without_runtime_auth() {
    let service =
        ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");

    let err = service
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap_err();

    assert_eq!(err.status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(
        err.detail,
        "Sandbox runtime authentication is not configured"
    );
}

#[tokio::test]
async fn service_cloud_status_remains_readable_without_runtime_auth() {
    let runtime = Arc::new(InMemoryContainerRuntime::new());
    let registry = Arc::new(InMemorySandboxRegistry::new());
    let authenticated = with_test_runtime_auth(ProjectSandboxService::with_registry(
        runtime.clone(),
        "redis:7-alpine",
        registry.clone(),
    ));
    authenticated
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap();

    let status_only = ProjectSandboxService::with_registry(runtime, "redis:7-alpine", registry);
    let fetched = status_only.get("p1").await.unwrap().unwrap();
    let listed = status_only.list("t1", None, 50, 0).await.unwrap();

    assert_eq!(fetched.project_id, "p1");
    assert_eq!(listed.len(), 1);
    assert!(fetched.runtime_auth_token.is_none());
}
#[tokio::test]
async fn service_ensure_local_tunnel_from_project_config_without_container_runtime() {
    let mut configs = BTreeMap::new();
    configs.insert(
        "p-local".to_string(),
        ProjectSandboxConfig {
            sandbox_type: "local".to_string(),
            local_config: json!({
                "workspace_path": "/Users/me/workspace",
                "tunnel_url": "wss://local.example/mcp?trace=1",
                "host": "localhost",
                "port": 19001,
                "auth_token": "local-secret"
            }),
        },
    );
    let config_source = Arc::new(StaticConfigSource {
        configs: Mutex::new(configs),
    });
    let runtime = Arc::new(RecordingRuntime::default());
    let service = ProjectSandboxService::new(runtime.clone(), "redis:7-alpine")
        .with_project_config_source(config_source);

    let created = service
        .ensure("p-local", "t1", Some(SandboxProfile::Full))
        .await
        .unwrap();

    assert_eq!(created.sandbox_id, "local-p-local");
    assert_eq!(created.project_id, "p-local");
    assert_eq!(created.tenant_id, "t1");
    assert_eq!(created.sandbox_type, "local");
    assert_eq!(created.status_str(), "running");
    assert!(created.healthy());
    assert_eq!(created.mcp_port, Some(19001));
    assert_eq!(
        created.endpoint.as_deref(),
        Some("wss://local.example/mcp?trace=1&token=local-secret")
    );
    assert_eq!(created.endpoint, created.websocket_url);
    assert_eq!(runtime.call_count(), 0);

    let fetched = service.get("p-local").await.unwrap().unwrap();
    assert_eq!(fetched.sandbox_id, created.sandbox_id);
    assert_eq!(fetched.endpoint, created.endpoint);
    assert_eq!(runtime.call_count(), 0);

    let restarted = service.restart("p-local").await.unwrap();
    assert_eq!(restarted.status_str(), "running");
    assert_eq!(runtime.call_count(), 0);

    assert!(service.terminate("p-local").await.unwrap());
    assert!(service.get("p-local").await.unwrap().is_none());
    assert_eq!(runtime.call_count(), 0);
}
#[tokio::test]
async fn service_lists_sandboxes_by_tenant_and_status() {
    let service = with_test_runtime_auth(ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "redis:7-alpine",
    ));
    service
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap();
    service
        .ensure("p2", "t1", Some(SandboxProfile::Standard))
        .await
        .unwrap();
    service
        .ensure("p3", "t2", Some(SandboxProfile::Full))
        .await
        .unwrap();

    let t1 = service.list("t1", None, 50, 0).await.unwrap();
    assert_eq!(t1.len(), 2);
    assert!(t1.iter().all(|sandbox| sandbox.tenant_id == "t1"));

    let running = service.list("t1", Some("running"), 50, 0).await.unwrap();
    assert_eq!(running.len(), 2);

    let stopped = service.list("t1", Some("stopped"), 50, 0).await.unwrap();
    assert!(stopped.is_empty());

    let page = service.list("t1", None, 1, 1).await.unwrap();
    assert_eq!(page.len(), 1);
}
#[tokio::test]
async fn service_terminal_sessions_are_durable_for_resume() {
    let service =
        ProjectSandboxService::new(Arc::new(InMemoryContainerRuntime::new()), "redis:7-alpine");
    let session = service.create_terminal_session("p1").await.unwrap();
    assert_eq!(session.project_id, "p1");
    assert!(!session.session_id.is_empty());
    assert_eq!(session.size(), TerminalSize::default());
    assert!(!session.connected);

    let recorder = service.terminal_session_recorder("p1".into(), session.session_id.clone());
    recorder
        .store(
            TerminalSize {
                cols: 132,
                rows: 43,
            },
            true,
        )
        .await
        .unwrap();

    let restored = service
        .get_terminal_session("p1", &session.session_id)
        .await
        .unwrap()
        .unwrap();
    assert!(restored.connected);
    assert_eq!(
        restored.size(),
        TerminalSize {
            cols: 132,
            rows: 43,
        }
    );
}
#[tokio::test]
async fn service_executes_tool_and_matches_python_wire_shape() {
    let host = StaticToolHost {
        output: json!({
            "content": [{ "type": "text", "text": "ok" }],
            "isError": false
        })
        .to_string(),
    };
    let service = with_test_runtime_auth(ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "redis:7-alpine",
    ))
    .with_tool_host(Arc::new(host));
    service
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap();

    let response = service
        .execute_tool("p1", "bash", &json!({ "cmd": "echo ok" }), 30.0)
        .await
        .unwrap();

    assert!(response.success);
    assert!(!response.is_error);
    assert_eq!(response.content[0]["text"], "ok");
    let execute_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_execute.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&execute_golden, &serde_json::to_value(&response).unwrap());
}
#[tokio::test]
async fn service_prefers_record_mcp_endpoint_for_tool_execution() {
    let registry = Arc::new(InMemorySandboxRegistry::new());
    let connector = Arc::new(RecordingConnector {
        urls: Mutex::new(Vec::new()),
        output: json!({
            "content": [{ "type": "text", "text": "from mcp" }],
            "isError": false
        })
        .to_string(),
    });
    let fallback = StaticToolHost {
        output: json!({
            "content": [{ "type": "text", "text": "from fallback" }],
            "isError": false
        })
        .to_string(),
    };
    let service = ProjectSandboxService::with_registry(
        Arc::new(InMemoryContainerRuntime::new()),
        "redis:7-alpine",
        registry.clone(),
    );
    let service = with_test_runtime_auth(service)
        .with_tool_host(Arc::new(fallback))
        .with_tool_connector(connector.clone());
    service
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap();
    let mut record = registry.get("p1").await.unwrap().unwrap();
    record.metadata_json = json!({
        "profile": "lite",
        "endpoint": "ws://sandbox-mcp.test:8765"
    });
    registry.save(&record, "running", None).await.unwrap();

    let response = service
        .execute_tool("p1", "bash", &json!({ "cmd": "pwd" }), 30.0)
        .await
        .unwrap();

    assert_eq!(response.content[0]["text"], "from mcp");
    assert_eq!(
        connector.urls.lock().unwrap().as_slice(),
        &["ws://sandbox-mcp.test:8765"]
    );
}

const TEST_MCP_URL: &str = "ws://sandbox-mcp.test:8765";

fn mcp_output() -> String {
    json!({
        "content": [{ "type": "text", "text": "from mcp" }],
        "isError": false
    })
    .to_string()
}

/// A service whose tool executions go through a `CachingToolConnector`
/// wrapping `dialer`, with project `p1` running at `TEST_MCP_URL`.
async fn service_with_cached_connector(
    registry: Arc<InMemorySandboxRegistry>,
    dialer: Arc<dyn SandboxToolConnector>,
) -> ProjectSandboxService {
    let service = with_test_runtime_auth(ProjectSandboxService::with_registry(
        Arc::new(InMemoryContainerRuntime::new()),
        "redis:7-alpine",
        registry.clone(),
    ))
    .with_tool_connector(Arc::new(CachingToolConnector::new(dialer)));
    service
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap();
    let mut record = registry.get("p1").await.unwrap().unwrap();
    record.metadata_json = json!({
        "profile": "lite",
        "endpoint": TEST_MCP_URL
    });
    registry.save(&record, "running", None).await.unwrap();
    service
}

#[tokio::test]
async fn service_reuses_cached_tool_host_across_tool_executions() {
    let registry = Arc::new(InMemorySandboxRegistry::new());
    let dialer = Arc::new(RecordingConnector {
        urls: Mutex::new(Vec::new()),
        output: mcp_output(),
    });
    let service = service_with_cached_connector(registry, dialer.clone()).await;

    let first = service
        .execute_tool("p1", "bash", &json!({ "cmd": "pwd" }), 30.0)
        .await
        .unwrap();
    let second = service
        .execute_tool("p1", "bash", &json!({ "cmd": "ls" }), 30.0)
        .await
        .unwrap();

    assert_eq!(first.content[0]["text"], "from mcp");
    assert_eq!(second.content[0]["text"], "from mcp");
    // Two executions, one dial: the MCP handshake happens once per endpoint.
    assert_eq!(dialer.urls.lock().unwrap().as_slice(), &[TEST_MCP_URL]);
}

#[tokio::test]
async fn service_single_flights_concurrent_tool_host_dials() {
    let registry = Arc::new(InMemorySandboxRegistry::new());
    let dialer = Arc::new(RecordingConnector {
        urls: Mutex::new(Vec::new()),
        output: mcp_output(),
    });
    let service = service_with_cached_connector(registry, dialer.clone()).await;

    let args = json!({ "cmd": "pwd" });
    let results = futures_util::future::join_all(
        (0..4).map(|_| service.execute_tool("p1", "bash", &args, 30.0)),
    )
    .await;

    for result in results {
        assert!(result.unwrap().success);
    }
    assert_eq!(dialer.urls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn service_evicts_and_redials_dead_cached_tool_host() {
    let registry = Arc::new(InMemorySandboxRegistry::new());
    let dialer = Arc::new(FlakyConnector {
        urls: Mutex::new(Vec::new()),
        failing_dials: 1,
        error_message: "mcp connection task is closed".to_string(),
        output: mcp_output(),
    });
    let service = service_with_cached_connector(registry, dialer.clone()).await;

    // The first dialed connection is dead: the cached host evicts it,
    // re-dials, and retries — one successful execution, two dials.
    let healed = service
        .execute_tool("p1", "bash", &json!({ "cmd": "pwd" }), 30.0)
        .await
        .unwrap();
    assert_eq!(healed.content[0]["text"], "from mcp");
    assert_eq!(dialer.urls.lock().unwrap().len(), 2);

    // The healed connection is cached: later executions dial no more.
    let reused = service
        .execute_tool("p1", "bash", &json!({ "cmd": "ls" }), 30.0)
        .await
        .unwrap();
    assert_eq!(reused.content[0]["text"], "from mcp");
    assert_eq!(dialer.urls.lock().unwrap().len(), 2);
}

#[tokio::test]
async fn service_keeps_cached_tool_host_after_tool_level_error() {
    let registry = Arc::new(InMemorySandboxRegistry::new());
    let dialer = Arc::new(FlakyConnector {
        urls: Mutex::new(Vec::new()),
        failing_dials: usize::MAX,
        error_message: "Unknown tool: bash".to_string(),
        output: mcp_output(),
    });
    let service = service_with_cached_connector(registry, dialer.clone()).await;

    // Tool-level failures travel over a healthy connection: they surface as
    // execution errors but must not evict the cached connection.
    for _ in 0..2 {
        let err = service
            .execute_tool("p1", "bash", &json!({ "cmd": "pwd" }), 30.0)
            .await
            .unwrap_err();
        assert_eq!(err.status, StatusCode::INTERNAL_SERVER_ERROR);
    }
    assert_eq!(dialer.urls.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn service_drops_cached_tool_host_on_terminate() {
    let registry = Arc::new(InMemorySandboxRegistry::new());
    let dialer = Arc::new(RecordingConnector {
        urls: Mutex::new(Vec::new()),
        output: mcp_output(),
    });
    let service = service_with_cached_connector(registry.clone(), dialer.clone()).await;
    service
        .execute_tool("p1", "bash", &json!({ "cmd": "pwd" }), 30.0)
        .await
        .unwrap();
    assert_eq!(dialer.urls.lock().unwrap().len(), 1);

    assert!(service.terminate("p1").await.unwrap());

    // A sandbox recreated at the same endpoint must not inherit the torn-down
    // connection: terminate evicted it, so execution re-dials.
    service
        .ensure("p1", "t1", Some(SandboxProfile::Lite))
        .await
        .unwrap();
    let mut record = registry.get("p1").await.unwrap().unwrap();
    record.metadata_json = json!({
        "profile": "lite",
        "endpoint": TEST_MCP_URL
    });
    registry.save(&record, "running", None).await.unwrap();
    let response = service
        .execute_tool("p1", "bash", &json!({ "cmd": "pwd" }), 30.0)
        .await
        .unwrap();
    assert_eq!(response.content[0]["text"], "from mcp");
    assert_eq!(dialer.urls.lock().unwrap().len(), 2);
}

#[tokio::test]
async fn caching_tool_connector_dials_once_per_url_and_evicts() {
    let dialer = Arc::new(RecordingConnector {
        urls: Mutex::new(Vec::new()),
        output: mcp_output(),
    });
    let connector = CachingToolConnector::new(dialer.clone());

    let first = connector.connect_tool_host(TEST_MCP_URL).await.unwrap();
    let second = connector.connect_tool_host(TEST_MCP_URL).await.unwrap();
    assert!(Arc::ptr_eq(&first, &second));
    assert_eq!(dialer.urls.lock().unwrap().len(), 1);

    connector.evict_tool_host(TEST_MCP_URL).await;
    let third = connector.connect_tool_host(TEST_MCP_URL).await.unwrap();
    assert!(!Arc::ptr_eq(&first, &third));
    assert_eq!(dialer.urls.lock().unwrap().len(), 2);
}
#[tokio::test]
async fn service_registers_lists_previews_and_stops_http_services() {
    let service = with_test_runtime_auth(ProjectSandboxService::new(
        Arc::new(InMemoryContainerRuntime::new()),
        "redis:7-alpine",
    ));

    let registered = service
        .register_http_service(
            "p1",
            "t1",
            RegisterHttpServiceRequest {
                service_id: Some("web".to_string()),
                name: "Docs".to_string(),
                source_type: HttpServiceSourceType::SandboxInternal,
                internal_port: Some(3000),
                internal_scheme: "http".to_string(),
                path_prefix: "docs".to_string(),
                external_url: None,
                auto_open: true,
            },
        )
        .await
        .unwrap();
    assert_eq!(registered.service_id, "web");
    assert_eq!(registered.sandbox_id.as_deref(), Some("mem-000000"));
    assert_eq!(registered.service_url, "http://127.0.0.1:3000/docs");
    assert_eq!(
        registered.preview_url,
        build_http_preview_proxy_url("p1", "web")
    );
    assert_eq!(
        registered.ws_preview_url.as_deref(),
        Some(build_http_preview_ws_proxy_url("p1", "web").as_str())
    );

    let listed = service.list_http_services("p1").await.unwrap();
    assert_eq!(listed.len(), 1);
    assert_eq!(listed[0].service_id, "web");

    let preview = service.preview_session("p1", "web").await.unwrap();
    assert_eq!(preview.expires_in_seconds, preview_session_ttl_seconds());
    assert!(preview
        .preview_url
        .starts_with(&build_http_preview_proxy_url("p1", "web")));
    assert!(preview
        .preview_url
        .contains(&format!("{PREVIEW_SESSION_QUERY_PARAM}=")));

    let removed = service
        .remove_http_service("p1", "web")
        .await
        .unwrap()
        .unwrap();
    assert_eq!(removed.service_id, "web");
    assert!(service.list_http_services("p1").await.unwrap().is_empty());
    assert!(matches!(
        service.preview_session("p1", "web").await,
        Err(SandboxApiError {
            status: StatusCode::NOT_FOUND,
            ..
        })
    ));

    let external = service
        .register_http_service(
            "p1",
            "t1",
            RegisterHttpServiceRequest {
                service_id: Some("external".to_string()),
                name: "External".to_string(),
                source_type: HttpServiceSourceType::ExternalUrl,
                internal_port: None,
                internal_scheme: "http".to_string(),
                path_prefix: "/".to_string(),
                external_url: Some("https://example.test/app".to_string()),
                auto_open: false,
            },
        )
        .await
        .unwrap();
    assert_eq!(external.preview_url, "https://example.test/app");
    let external_preview = service.preview_session("p1", "external").await.unwrap();
    assert_eq!(external_preview.preview_url, "https://example.test/app");
    assert_eq!(external_preview.expires_in_seconds, 0);
}
