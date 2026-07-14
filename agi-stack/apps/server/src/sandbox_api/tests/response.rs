use super::super::*;
use super::*;

#[test]
fn profile_validation_matches_python_enum_values() {
    assert_eq!(
        SandboxProfile::parse(Some("LITE")).unwrap(),
        Some(SandboxProfile::Lite)
    );
    assert_eq!(
        SandboxProfile::parse(Some("standard")).unwrap(),
        Some(SandboxProfile::Standard)
    );
    assert_eq!(
        SandboxProfile::parse(Some("full")).unwrap(),
        Some(SandboxProfile::Full)
    );
    assert!(SandboxProfile::parse(Some("gpu")).is_err());
    assert_eq!(
        parse_status_filter(Some("CONNECTING")).unwrap(),
        Some("connecting".to_string())
    );
    assert!(parse_status_filter(Some("gpu")).is_err());
}
#[test]
fn sandbox_router_builds_with_http_service_proxy_routes() {
    let _ = router();
}

#[test]
fn sandbox_profiles_match_python_wire_shape() {
    let response = SandboxProfilesResponse {
        profiles: SANDBOX_PROFILE_INFOS,
    };
    assert_eq!(response.profiles.len(), 3);
    assert_eq!(response.profiles[0].profile_type, "lite");
    assert_eq!(response.profiles[1].profile_type, "standard");
    assert_eq!(response.profiles[2].profile_type, "full");

    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/sandbox_profiles_response.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(&response).unwrap();
    agistack_parity::assert_parity(&golden, &actual);
}

#[test]
fn response_keeps_python_wire_fields_and_null_proxy_urls() {
    let mut info = sample_info();
    info.runtime_auth_token = Some(SandboxRuntimeToken::from_exposed("private-capability"));
    let response = ProjectSandboxResponse::from(info);
    assert_eq!(response.status, "running");
    assert!(response.is_healthy);
    assert_eq!(response.created_at.as_deref(), Some("1970-01-01T00:00:00Z"));
    assert_eq!(response.endpoint, None);
    assert_eq!(response.websocket_url, None);
    assert_eq!(response.mcp_port, None);
    assert_eq!(response.desktop_url, None);
    assert_eq!(response.terminal_url, None);

    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_response.json"
    ))
    .unwrap();
    let actual = serde_json::to_value(&response).unwrap();
    assert!(!actual.to_string().contains("private-capability"));
    assert!(actual.get("runtime_auth_token").is_none());
    agistack_parity::assert_parity(&golden, &actual);
}
#[test]
fn response_surfaces_persisted_mcp_connection_fields() {
    let mut info = sample_info();
    info.endpoint = Some("ws://localhost:18765".to_string());
    info.websocket_url = Some("ws://localhost:18765".to_string());
    info.mcp_port = Some(18765);
    let response = ProjectSandboxResponse::from(info);
    assert_eq!(response.endpoint.as_deref(), Some("ws://localhost:18765"));
    assert_eq!(
        response.websocket_url.as_deref(),
        Some("ws://localhost:18765")
    );
    assert_eq!(response.mcp_port, Some(18765));
}
#[test]
fn runtime_ports_are_projected_into_python_connection_fields() {
    let record = SandboxRecord::new(
        "s1".to_string(),
        "p1".to_string(),
        "t1".to_string(),
        SandboxProfile::Standard,
        0,
    );
    let info = ProjectSandboxInfo::from_record(
        record,
        ContainerStatus {
            id: "s1".to_string(),
            state: ContainerState::Running,
            running: true,
            exit_code: None,
            ports: vec![
                PortBinding {
                    container_port: MCP_CONTAINER_PORT,
                    host_port: 18765,
                    host_ip: Some("127.0.0.1".to_string()),
                },
                PortBinding {
                    container_port: DESKTOP_CONTAINER_PORT,
                    host_port: 16080,
                    host_ip: Some("127.0.0.1".to_string()),
                },
                PortBinding {
                    container_port: TERMINAL_CONTAINER_PORT,
                    host_port: 17681,
                    host_ip: Some("127.0.0.1".to_string()),
                },
            ],
        },
    );
    let response = ProjectSandboxResponse::from(info);
    assert_eq!(response.mcp_port, Some(18765));
    assert_eq!(response.endpoint.as_deref(), Some("ws://localhost:18765"));
    assert_eq!(response.desktop_port, Some(16080));
    assert_eq!(
        response.desktop_url.as_deref(),
        Some("https://localhost:16080")
    );
    assert_eq!(response.terminal_port, Some(17681));
    assert_eq!(
        response.terminal_url.as_deref(),
        Some("ws://localhost:17681")
    );
}
#[test]
fn interactive_control_responses_match_python_wire_shape() {
    let mut info = sample_info();
    info.desktop_url = Some("https://localhost:16080".to_string());
    info.desktop_port = Some(16080);
    info.terminal_url = Some("ws://localhost:17681".to_string());
    info.terminal_port = Some(17681);

    let desktop = DesktopServiceResponse::from_info(&info, DESKTOP_DEFAULT_RESOLUTION.to_string());
    assert!(desktop.success);
    assert_eq!(desktop.url.as_deref(), Some("https://localhost:16080"));
    assert_eq!(desktop.display.as_str(), DESKTOP_DEFAULT_DISPLAY);
    assert_eq!(desktop.resolution.as_str(), DESKTOP_DEFAULT_RESOLUTION);
    assert_eq!(desktop.port, 16080);
    assert!(!desktop.audio_enabled);
    assert!(desktop.dynamic_resize);
    assert_eq!(desktop.encoding.as_str(), DESKTOP_DEFAULT_ENCODING);
    let desktop_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_desktop_start.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&desktop_golden, &serde_json::to_value(&desktop).unwrap());

    let custom_desktop = DesktopServiceResponse::from_info(&info, "1280x720".to_string());
    assert_eq!(custom_desktop.resolution, "1280x720");

    let terminal =
        TerminalServiceResponse::from_info_with_session(&info, Some("term-abc123".into()));
    assert!(terminal.success);
    assert_eq!(terminal.url.as_deref(), Some("ws://localhost:17681"));
    assert_eq!(terminal.port, 17681);
    assert_eq!(terminal.session_id.as_deref(), Some("term-abc123"));
    let terminal_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_terminal_start.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&terminal_golden, &serde_json::to_value(&terminal).unwrap());

    let stop = SandboxServiceStopResponse { success: true };
    let stop_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_service_stop.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&stop_golden, &serde_json::to_value(&stop).unwrap());

    let missing = sample_info();
    assert!(
        !DesktopServiceResponse::from_info(&missing, DESKTOP_DEFAULT_RESOLUTION.to_string())
            .success
    );
    assert!(!TerminalServiceResponse::from_info(&missing).success);
}
#[test]
fn http_service_control_responses_match_python_wire_shape() {
    let service = HttpServiceProxyInfo {
        service_id: "web".to_string(),
        name: "Docs".to_string(),
        source_type: HttpServiceSourceType::SandboxInternal,
        status: "running".to_string(),
        service_url: "http://127.0.0.1:3000/docs".to_string(),
        preview_url: "http://web.p1.preview.localhost:8000/".to_string(),
        ws_preview_url: Some("ws://web.p1.preview.localhost:8000/".to_string()),
        sandbox_id: Some("s1".to_string()),
        auto_open: true,
        restart_token: Some("1700000000000".to_string()),
        updated_at: "1970-01-01T00:00:00.000+00:00".to_string(),
    };

    let response = HttpServiceResponse::from(service.clone());
    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_http_service_response.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &serde_json::to_value(&response).unwrap());

    let list = ListHttpServicesResponse {
        services: vec![HttpServiceResponse::from(service.clone())],
        total: 1,
    };
    let list_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_http_services_list.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&list_golden, &serde_json::to_value(&list).unwrap());

    let mut stopped = service;
    stopped.status = "stopped".to_string();
    let action = HttpServiceActionResponse {
        success: true,
        message: "HTTP service web stopped".to_string(),
        service: Some(HttpServiceResponse::from(stopped)),
    };
    let action_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_http_service_action.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&action_golden, &serde_json::to_value(&action).unwrap());

    let preview = HttpServicePreviewSessionResponse {
        preview_url: append_query_param(
            "http://web.p1.preview.localhost:8000/",
            PREVIEW_SESSION_QUERY_PARAM,
            &agistack_adapters_secrets::generate_urlsafe_token(32),
        ),
        expires_in_seconds: 86_400,
    };
    let preview_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_http_service_preview_session.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&preview_golden, &serde_json::to_value(&preview).unwrap());

    assert_eq!(normalize_http_service_id(Some(" web:1 ")).unwrap(), "web:1");
    assert!(normalize_http_service_id(Some("bad/id")).is_err());
    assert_eq!(normalize_path_prefix("docs"), "/docs");
    assert!(validate_external_http_url("https://example.test/app").is_ok());
    assert!(validate_external_http_url("ftp://example.test/app").is_err());
}
#[test]
fn proxy_auth_cookie_response_and_header_match_python_contract() {
    let response = SandboxProxyAuthCookieResponse {
        success: true,
        expires_in_seconds: SANDBOX_PROXY_AUTH_COOKIE_MAX_AGE_SECONDS,
    };
    let golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_proxy_auth_cookie.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&golden, &serde_json::to_value(&response).unwrap());

    let cookie = sandbox_proxy_auth_cookie("p1", "ms_sk_test", false).unwrap();
    assert_eq!(
        cookie.to_str().unwrap(),
        "sandbox_proxy_token=ms_sk_test; HttpOnly; SameSite=Strict; Max-Age=3600; Path=/api/v1/projects/p1/sandbox"
    );

    let secure_cookie = sandbox_proxy_auth_cookie("p1", "ms_sk_test", true).unwrap();
    assert!(secure_cookie.to_str().unwrap().ends_with("; Secure"));
}
#[test]
fn proxy_auth_cookie_secure_detection_honors_forwarded_proto() {
    let mut headers = HeaderMap::new();
    assert!(!proxy_auth_cookie_secure(&headers));

    headers.insert("x-forwarded-proto", HeaderValue::from_static("https,http"));
    assert!(proxy_auth_cookie_secure(&headers));

    let mut headers = HeaderMap::new();
    headers.insert(
        "forwarded",
        HeaderValue::from_static("for=127.0.0.1;proto=https;host=example.test"),
    );
    assert!(proxy_auth_cookie_secure(&headers));
}
#[test]
fn health_stats_and_action_responses_match_goldens() {
    let info = sample_info();
    let health = HealthCheckResponse {
        project_id: "p1".to_string(),
        sandbox_id: "s1".to_string(),
        healthy: info.healthy(),
        status: info.status_str().to_string(),
        checked_at: rfc3339(0),
    };
    let health_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_health.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&health_golden, &serde_json::to_value(&health).unwrap());

    let stats = SandboxStatsResponse {
        project_id: "p1".to_string(),
        sandbox_id: "s1".to_string(),
        status: "running".to_string(),
        cpu_percent: 0.0,
        memory_usage: 0,
        memory_limit: 0,
        memory_percent: 0.0,
        disk_usage: None,
        disk_limit: None,
        disk_percent: None,
        network_rx_bytes: None,
        network_tx_bytes: None,
        pids: 0,
        uptime_seconds: Some(12),
        created_at: Some(rfc3339(0)),
        collected_at: rfc3339(12_000),
    };
    let stats_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_stats.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&stats_golden, &serde_json::to_value(&stats).unwrap());

    let action = SandboxActionResponse {
        success: true,
        message: "Sandbox s1 restarted successfully".to_string(),
        sandbox: Some(ProjectSandboxResponse::from(sample_info())),
    };
    let action_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_action.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&action_golden, &serde_json::to_value(&action).unwrap());

    let list = ListProjectSandboxesResponse {
        sandboxes: vec![ProjectSandboxResponse::from(sample_info())],
        total: 1,
    };
    let list_golden: serde_json::Value = serde_json::from_str(include_str!(
        "../../../tests/golden/project_sandbox_list.json"
    ))
    .unwrap();
    agistack_parity::assert_parity(&list_golden, &serde_json::to_value(&list).unwrap());
}
