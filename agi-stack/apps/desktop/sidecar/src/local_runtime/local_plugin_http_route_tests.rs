use super::*;

#[tokio::test]
async fn http_route_uses_only_the_installed_signed_project_grant() {
    let (state, bytes) = route_fixture(r#"{"status":201,"body":{"guest":"active"}}"#).await;
    let path = "/api/v1/projects/local-project/example";
    assert_eq!(
        request(&state, "GET", path, Value::Null).await.0,
        StatusCode::NOT_FOUND
    );
    let reference = import(&state, &bytes).await;
    let (status, body) = request(&state, "GET", path, Value::Null).await;
    assert_eq!(
        (status, body),
        (StatusCode::CREATED, json!({"guest":"active"}))
    );
    assert_eq!(
        request(&state, "POST", path, Value::Null).await.0,
        StatusCode::NOT_FOUND
    );
    assert_eq!(
        request(&state, "GET", "/api/v1/projects/other/example", Value::Null)
            .await
            .0,
        StatusCode::FORBIDDEN
    );
    let (status, _) = request(
        &state,
        "POST",
        &format!(
            "/api/v1/local-plugins/v2/installations/{}/revoke",
            reference["bundle_id"].as_str().unwrap()
        ),
        json!({"tenant_id":"local","project_id":"local-project","reference":reference}),
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        request(&state, "GET", path, Value::Null).await.0,
        StatusCode::FORBIDDEN
    );
}

async fn route_fixture(response: &str) -> (Arc<LocalRuntimeState>, Vec<u8>) {
    let wat = format!(
        "(module (memory (export \"memory\") 2) (data (i32.const 65536) {:?}) (func (export \"invoke\") (param i32) (result i32) i32.const {}))",
        response, response.len()
    );
    let (_, _, bytes, key, _) = fixture::signed_fixture_with_bytes(&wat, |manifest| {
        manifest["manifests"][0]["modules"][0]["entrypoint"] = json!("invoke");
        let quotas = json!({"max_wasm_memory_bytes":131072,"max_wasm_fuel":1000000,"max_output_bytes":65536});
        manifest["manifests"][0]["quotas"] = quotas.clone();
        manifest["layers"][0]["entries"][0]["quotas"] = quotas;
        manifest["manifests"][0]["permissions"] =
            json!(["tools.execute", "desktop.http.get.example"]);
        manifest["layers"][0]["entries"][0]["permissions"] =
            json!(["tools.execute", "desktop.http.get.example"]);
    });
    let mut state = local_runtime::tests::test_state(TOKEN);
    Arc::get_mut(&mut state).unwrap().local_plugin_signing_keys = Ok(vec![key]);
    let mut reconciler = desktop_reconciler(&state);
    activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
        .await
        .unwrap();
    (state, bytes)
}

#[tokio::test]
async fn signed_http_route_cannot_read_workspace_without_its_own_capability() {
    let (state,bytes)=route_fixture(r#"{"workspace_read":{"operation":"download","body":{},"contract":{},"download_headers":[],"errors":{}}}"#).await;
    import(&state, &bytes).await;
    let (status, body) = request(
        &state,
        "GET",
        "/api/v1/projects/local-project/example?path=%2Fworkspace%2Fprivate.txt",
        Value::Null,
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(body["code"], "project_route_grant_denied");
}

#[tokio::test]
#[ignore = "requires the published Environments multi-target archive and its publisher public key"]
async fn published_environments_sandbox_http_routes() {
    let root =
        std::path::PathBuf::from(std::env::var_os("MEMSTACK_ENVIRONMENTS_HTTP_RELEASE").unwrap());
    let key =
        agistack_plugin_host::protocol_v2::signed_archive::TrustedEd25519KeyV2::from_spki_pem(
            &std::fs::read_to_string(root.join("public.pem")).unwrap(),
        )
        .unwrap();
    let mut state = local_runtime::tests::test_state(TOKEN);
    Arc::get_mut(&mut state).unwrap().local_plugin_signing_keys = Ok(vec![key]);
    let mut reconciler = desktop_reconciler(&state);
    activate_authority_source(&state, &mut reconciler, &DesktopAuthoritySourceV2::Local)
        .await
        .unwrap();
    import(
        &state,
        &std::fs::read(root.join("environments.mspkg")).unwrap(),
    )
    .await;
    let (status, sandbox) = request(
        &state,
        "GET",
        "/api/v1/projects/local-project/sandbox",
        Value::Null,
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{sandbox}");
    assert_eq!(sandbox["sandbox_id"], "local-local-project");
    assert_eq!(sandbox["status"], "unavailable");
    assert_eq!(sandbox["is_healthy"], false);
    for (path, detail) in [
        ("sandbox", "isolated local sandbox is not configured"),
        (
            "sandbox/desktop",
            "isolated local desktop is not configured",
        ),
    ] {
        let (status, body) = request(
            &state,
            "POST",
            &format!("/api/v1/projects/local-project/{path}"),
            Value::Null,
        )
        .await;
        assert_eq!(status, StatusCode::NOT_IMPLEMENTED);
        assert_eq!(body, json!({"detail":detail, "sandbox":sandbox}));
    }
    assert_eq!(
        request(
            &state,
            "POST",
            "/api/v1/projects/local-project/sandbox/proxy-auth-cookie",
            Value::Null
        )
        .await,
        (StatusCode::OK, json!({"ok":true}))
    );
}
