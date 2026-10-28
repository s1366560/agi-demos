#[tokio::test]
async fn edge_facade_audit_reuses_the_exact_authorization_origin() {
    for decision in [
        None,
        Some(BrowserOriginDecision::Site),
        Some(BrowserOriginDecision::Decline),
    ] {
        let endpoint = claim_tab_endpoint("https://edge.test/authorized")
            .script(METHOD_ATTACH, vec![ok(json!({}))]);
        let requests = endpoint.requests();
        let fixture = build_fixture(endpoint);
        if let Some(decision) = decision {
            fixture
                .store
                .insert_browser_origin_grant(&grant("edge.test", decision))
                .unwrap();
        }
        let output = fixture
            .host
            .call(
                TOOL_FACADE_WRITE,
                r#"{"browserId":"edge","tabId":7,"operation":"tab.claim","args":[]}"#,
            )
            .await
            .unwrap();
        let output: Value = serde_json::from_str(&output).unwrap();
        let expected_outcome = match decision {
            Some(BrowserOriginDecision::Site) => {
                assert_eq!(output["tabId"], 7);
                "ok"
            }
            Some(BrowserOriginDecision::Decline) => {
                assert_eq!(output["error"], "origin_declined");
                "declined"
            }
            _ => {
                assert_eq!(output["error"], "origin_consent_required");
                "consent_required"
            }
        };
        assert_eq!(requests.backends_of(METHOD_GET_TABS), ["edge-extension"]);
        assert_eq!(
            requests.count(METHOD_ATTACH),
            usize::from(expected_outcome == "ok")
        );
        let entries = fixture.store.list_browser_action_audit(10, None).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].origin.as_deref(), Some("edge.test"));
        assert_eq!(entries[0].outcome, expected_outcome);
        assert_eq!(entries[0].target_summary, "tab:7");
    }
}

#[tokio::test]
async fn failed_origin_authorization_is_not_retried_for_audit() {
    let endpoint = MockEndpoint::new().script(
        METHOD_GET_TABS,
        vec![Err(CoreError::Tool("edge disconnected".into()))],
    );
    let requests = endpoint.requests();
    let fixture = build_fixture(endpoint);
    assert!(fixture
        .host
        .call(
            TOOL_FACADE_WRITE,
            r#"{"browserId":"edge","tabId":7,"operation":"tab.claim","args":[]}"#,
        )
        .await
        .is_err());
    assert_eq!(requests.backends_of(METHOD_GET_TABS), ["edge-extension"]);
    let entries = fixture.store.list_browser_action_audit(10, None).unwrap();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].origin, None);
    assert_eq!(entries[0].outcome, "error");
}

#[tokio::test]
async fn unbound_facade_error_never_falls_back_to_chrome_for_audit() {
    let endpoint = MockEndpoint::new();
    let requests = endpoint.requests();
    let fixture = build_fixture(endpoint);
    assert!(fixture
        .host
        .call(
            TOOL_FACADE_WRITE,
            r#"{"browserId":"missing-browser","tabId":7,"operation":"tab.claim","args":[]}"#,
        )
        .await
        .is_err());
    assert_eq!(requests.count(METHOD_GET_TABS), 0);
    let entries = fixture.store.list_browser_action_audit(10, None).unwrap();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].origin, None);
    assert_eq!(entries[0].outcome, "error");
}

#[tokio::test]
async fn read_audit_fallback_preserves_the_bound_edge_instance() {
    let browser_id = "edge:00000000000000000000000000000001:00000000000000000000000000000002";
    let endpoint = claim_tab_endpoint("https://edge.test/current").script(
        "facadeCapabilities",
        vec![ok(json!({"tab": ["cdp"], "browser": []}))],
    );
    let requests = endpoint.requests();
    let fixture = build_fixture(endpoint);
    let output = fixture
        .host
        .call(
            facade::TOOL_READ,
            &json!({
                "browserId": browser_id, "tabId": 7, "operation": "capabilities.list", "args": [],
            })
            .to_string(),
        )
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&output).unwrap(),
        json!(["cdp"])
    );
    assert_eq!(requests.backends_of("facadeCapabilities"), [browser_id]);
    assert_eq!(requests.backends_of(METHOD_GET_TABS), [browser_id]);
    let entries = fixture.store.list_browser_action_audit(10, None).unwrap();
    assert_eq!(entries[0].origin.as_deref(), Some("edge.test"));
}

#[tokio::test]
async fn credential_fill_audit_never_adds_a_probe_or_changes_the_bound_backend() {
    let endpoint = fill_endpoint(json!(["username", "password"]));
    let requests = endpoint.requests();
    let fixture = build_fixture(endpoint);
    grant_origin(&fixture, "foo.test");
    consent_credential_fill(&fixture, "foo.test");
    store_credential(&fixture, "foo.test", "alice", "test-secret");
    fixture
        .host
        .call(
            TOOL_FILL_CREDENTIALS,
            r#"{"browserId":"edge","tabId":7,"origin":"foo.test"}"#,
        )
        .await
        .unwrap();
    assert_eq!(requests.backends_of(METHOD_GET_TABS), ["edge-extension"]);
    assert_eq!(requests.backends_of(METHOD_EXECUTE_CDP), ["edge-extension"]);
    let entries = fixture.store.list_browser_action_audit(10, None).unwrap();
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].origin.as_deref(), Some("foo.test"));
    assert_eq!(entries[0].target_summary, "foo.test");
    assert_eq!(entries[0].outcome, "ok");
}

#[tokio::test]
async fn credential_fill_denial_audits_declared_origin_without_reading_the_page() {
    let endpoint = MockEndpoint::new();
    let requests = endpoint.requests();
    let fixture = build_fixture(endpoint);
    let output = fixture
        .host
        .call(
            TOOL_FILL_CREDENTIALS,
            r#"{"browserId":"edge","tabId":7,"origin":"foo.test"}"#,
        )
        .await
        .unwrap();
    assert_eq!(
        serde_json::from_str::<Value>(&output).unwrap()["error"],
        "origin_consent_required"
    );
    assert_eq!(requests.count(METHOD_GET_TABS), 0);
    assert_eq!(requests.count(METHOD_EXECUTE_CDP), 0);
    let entries = fixture.store.list_browser_action_audit(10, None).unwrap();
    assert_eq!(entries[0].origin.as_deref(), Some("foo.test"));
    assert_eq!(entries[0].outcome, "consent_required");
}
