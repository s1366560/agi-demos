use super::*;

#[tokio::test]
async fn gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough() {
    // Two distinguishable mock upstreams.
    let rust_mock = Router::new()
        .route("/api/v1/agent/ws", get(ws_echo))
        .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
        .with_state("rust");
    let python_mock = Router::new()
        .route("/api/v1/redirect", get(redirect))
        .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
        .with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;

    // The real gateway pointing at both mocks.
    let gateway_state = gateway_state(Upstreams {
        rust: rust_url.clone(),
        python: python_url.clone(),
    });
    let gateway_url = spawn(app(gateway_state)).await;

    let http = client();
    let bearer = "Bearer ms_sk_e2e_testkey";

    // 1) Strangled GET -> Rust upstream, Authorization forwarded verbatim.
    let r = http
        .get(format!("{gateway_url}/api/v1/memories/"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), StatusCode::OK);
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "routed to rust: {body}"
    );
    assert!(
        body.contains("\"path\":\"/api/v1/memories/\""),
        "path preserved: {body}"
    );
    assert!(
        body.contains(&format!("\"auth\":\"{bearer}\"")),
        "bearer forwarded: {body}"
    );

    // 2) Non-strangled GET -> Python upstream.
    let r = http
        .get(format!("{gateway_url}/api/v1/not-strangled"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "routed to python: {body}"
    );

    // 3) Strangled POST with a body -> Rust upstream, method + body preserved.
    let r = http
        .post(format!("{gateway_url}/api/v1/episodes/"))
        .header("authorization", bearer)
        .body("{'content':'hello'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "episodes -> rust: {body}"
    );
    assert!(
        body.contains("\"method\":\"POST\""),
        "method preserved: {body}"
    );
    assert!(body.contains("hello"), "body forwarded: {body}");

    // 4) A prefix that only *looks* strangled (no segment boundary) -> Python.
    let r = http
        .get(format!("{gateway_url}/api/v1/memories_admin"))
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "memories_admin is not strangled: {body}"
    );

    // 5) Upstream 307 is relayed, not followed (redirect passthrough).
    let r = http
        .get(format!("{gateway_url}/api/v1/redirect"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), StatusCode::TEMPORARY_REDIRECT);
    assert_eq!(r.headers().get("location").unwrap(), "/moved");

    // 6) P2 tenant read flip is method-aware: GET list/detail -> Rust.
    let r = http
        .get(format!("{gateway_url}/api/v1/tenants"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant list GET -> rust: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/tenants/acme"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant detail GET -> rust: {body}"
    );

    // 6b) P2 device-code auth flip is method/exact-path scoped.
    for (path, body_in) in [
        ("/api/v1/auth/device/code", "{}"),
        ("/api/v1/auth/device/approve", "{'user_code':'ABCDEFGH'}"),
        ("/api/v1/auth/device/token", "{'device_code':'dev'}"),
    ] {
        let r = http
            .post(format!("{gateway_url}{path}"))
            .header("authorization", bearer)
            .body(body_in)
            .send()
            .await
            .unwrap();
        let body = r.text().await.unwrap();
        assert!(
            body.contains("\"backend\":\"rust\""),
            "device-code {path} POST -> rust: {body}"
        );
    }

    let r = http
        .get(format!("{gateway_url}/api/v1/auth/device/code"))
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "device-code GET remains python: {body}"
    );

    let r = http
        .post(format!("{gateway_url}/api/v1/auth/device/code/extra"))
        .body("{}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "device-code child path remains python: {body}"
    );

    // 7) Covered tenant writes flip to Rust; destructive tenant delete and
    // uncovered read siblings stay on Python.
    let r = http
        .post(format!("{gateway_url}/api/v1/tenants"))
        .header("authorization", bearer)
        .body("{'name':'Acme'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant POST -> rust: {body}"
    );

    let r = http
        .put(format!("{gateway_url}/api/v1/tenants/acme"))
        .header("authorization", bearer)
        .body("{'name':'Acme 2'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant PUT -> rust: {body}"
    );

    for (method, path, body_in) in [
        ("POST", "/api/v1/tenants/acme/members", "{'user_id':'u1'}"),
        ("POST", "/api/v1/tenants/acme/members/u1", ""),
        (
            "PATCH",
            "/api/v1/tenants/acme/members/u1",
            "{'role':'viewer'}",
        ),
        ("DELETE", "/api/v1/tenants/acme/members/u1", ""),
    ] {
        let request = match method {
            "POST" => http.post(format!("{gateway_url}{path}")).body(body_in),
            "PATCH" => http.patch(format!("{gateway_url}{path}")).body(body_in),
            "DELETE" => http.delete(format!("{gateway_url}{path}")),
            _ => unreachable!(),
        };
        let r = request
            .header("authorization", bearer)
            .send()
            .await
            .unwrap();
        let body = r.text().await.unwrap();
        assert!(
            body.contains("\"backend\":\"rust\""),
            "tenant member write {method} {path} -> rust: {body}"
        );
    }

    let r = http
        .delete(format!("{gateway_url}/api/v1/tenants/acme"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant DELETE -> rust: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/tenants/acme/members"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "tenant members sibling remains python: {body}"
    );

    // 7b) P2 invitations are tenant-scoped but only exact covered methods flip.
    let r = http
        .post(format!("{gateway_url}/api/v1/tenants/acme/invitations"))
        .header("authorization", bearer)
        .body("{'email':'ada@example.test'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant invitation POST -> rust: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/tenants/acme/invitations"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant invitations GET -> rust: {body}"
    );

    let r = http
        .delete(format!(
            "{gateway_url}/api/v1/tenants/acme/invitations/inv1"
        ))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "tenant invitation DELETE -> rust: {body}"
    );

    let r = http
        .get(format!(
            "{gateway_url}/api/v1/tenants/acme/invitations/inv1"
        ))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "uncovered invitation child GET remains python: {body}"
    );

    let r = http
        .get(format!(
            "{gateway_url}/api/v1/tenants/acme/invitations/inv1/audit"
        ))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "deeper invitation sibling remains python: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/invitations/verify/token1"))
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "public invitation verify -> rust: {body}"
    );

    let r = http
        .post(format!("{gateway_url}/api/v1/invitations/accept/token1"))
        .header("authorization", bearer)
        .body("{}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "invitation accept -> rust: {body}"
    );

    let r = http
        .get(format!(
            "{gateway_url}/api/v1/invitations/verify/token1/extra"
        ))
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "deeper public invitation path remains python: {body}"
    );

    // 7c) P2 trust is tenant-scoped and only exact covered resources flip.
    for (method, path, body_in) in [
        ("GET", "/api/v1/tenants/acme/trust/policies", ""),
        (
            "POST",
            "/api/v1/tenants/acme/trust/policies",
            "{'grant_type':'always'}",
        ),
        ("GET", "/api/v1/tenants/acme/trust/policies/check", ""),
        ("POST", "/api/v1/tenants/acme/trust/approval-requests", "{}"),
        (
            "POST",
            "/api/v1/tenants/acme/trust/approval-requests/rec1/resolve",
            "{'decision':'allow_once'}",
        ),
        ("GET", "/api/v1/tenants/acme/trust/decision-records", ""),
        (
            "GET",
            "/api/v1/tenants/acme/trust/decision-records/rec1",
            "",
        ),
    ] {
        let request = match method {
            "GET" => http.get(format!("{gateway_url}{path}")),
            "POST" => http.post(format!("{gateway_url}{path}")).body(body_in),
            _ => unreachable!(),
        };
        let r = request
            .header("authorization", bearer)
            .send()
            .await
            .unwrap();
        let body = r.text().await.unwrap();
        assert!(
            body.contains("\"backend\":\"rust\""),
            "trust {method} {path} -> rust: {body}"
        );
    }

    let r = http
        .delete(format!("{gateway_url}/api/v1/tenants/acme/trust/policies"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "trust uncovered DELETE remains python: {body}"
    );

    let r = http
        .get(format!(
            "{gateway_url}/api/v1/tenants/acme/trust/policies/check/extra"
        ))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "deeper trust sibling remains python: {body}"
    );

    // 8) P2 public memory shares are GET + single-token scoped.
    let r = http
        .get(format!("{gateway_url}/api/v1/shared/share_token"))
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "public share GET -> rust: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/shared/share_token/extra"))
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "deeper public share path remains python: {body}"
    );

    let r = http
        .post(format!("{gateway_url}/api/v1/shared/share_token"))
        .body("{}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "public share POST remains python: {body}"
    );

    // 9) P2 project read flip is method-aware and excludes P5 sandbox siblings.
    let r = http
        .get(format!("{gateway_url}/api/v1/projects"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "project list GET -> rust: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/projects/p1"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "project detail GET -> rust: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/projects/p1/stats"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "project stats GET -> rust: {body}"
    );

    let r = http
        .get(format!("{gateway_url}/api/v1/projects/p1/members"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "project members GET -> rust: {body}"
    );

    for (method, path, body_in) in [
        ("POST", "/api/v1/projects/p1/members", "{'user_id':'u1'}"),
        (
            "PATCH",
            "/api/v1/projects/p1/members/u1",
            "{'role':'viewer'}",
        ),
        ("DELETE", "/api/v1/projects/p1/members/u1", ""),
    ] {
        let request = match method {
            "POST" => http.post(format!("{gateway_url}{path}")).body(body_in),
            "PATCH" => http.patch(format!("{gateway_url}{path}")).body(body_in),
            "DELETE" => http.delete(format!("{gateway_url}{path}")),
            _ => unreachable!(),
        };
        let r = request
            .header("authorization", bearer)
            .send()
            .await
            .unwrap();
        let body = r.text().await.unwrap();
        assert!(
            body.contains("\"backend\":\"rust\""),
            "project member write {method} {path} -> rust: {body}"
        );
    }

    let r = http
        .get(format!("{gateway_url}/api/v1/projects/p1/members/u1"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "project member child remains python: {body}"
    );

    let r = http
        .post(format!("{gateway_url}/api/v1/projects/sandboxes/members"))
        .header("authorization", bearer)
        .body("{'user_id':'u1'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "project sandboxes members POST remains python: {body}"
    );

    let r = http
        .post(format!("{gateway_url}/api/v1/projects"))
        .header("authorization", bearer)
        .body("{'name':'Acme','tenant_id':'t1'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "project POST -> rust: {body}"
    );

    let r = http
        .put(format!("{gateway_url}/api/v1/projects/p1"))
        .header("authorization", bearer)
        .body("{'name':'Acme 2'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "project PUT -> rust: {body}"
    );

    let r = http
        .delete(format!("{gateway_url}/api/v1/projects/p1"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "project DELETE -> rust: {body}"
    );

    // 9b) P5 sandbox HTTP control plane flips to Rust without taking proxy/WS
    // data-plane siblings. Rollback is deleting the matching gateway rule block.
    for (method, path, body_in) in [
        ("GET", "/api/v1/projects/sandboxes", ""),
        ("GET", "/api/v1/projects/p1/sandbox", ""),
        ("POST", "/api/v1/projects/p1/sandbox", "{}"),
        ("DELETE", "/api/v1/projects/p1/sandbox", ""),
        ("GET", "/api/v1/projects/p1/sandbox/health", ""),
        ("GET", "/api/v1/projects/p1/sandbox/stats", ""),
        ("GET", "/api/v1/projects/p1/sandbox/sync", ""),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/execute",
            "{'tool':'list'}",
        ),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/proxy-auth-cookie",
            "{}",
        ),
        ("POST", "/api/v1/projects/p1/sandbox/restart", "{}"),
        ("POST", "/api/v1/projects/p1/sandbox/desktop", "{}"),
        ("DELETE", "/api/v1/projects/p1/sandbox/desktop", ""),
        ("POST", "/api/v1/projects/p1/sandbox/terminal", "{}"),
        ("DELETE", "/api/v1/projects/p1/sandbox/terminal", ""),
        ("GET", "/api/v1/projects/p1/sandbox/http-services", ""),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/http-services",
            "{'service_id':'web'}",
        ),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
            "{}",
        ),
        (
            "DELETE",
            "/api/v1/projects/p1/sandbox/http-services/web",
            "",
        ),
        ("GET", "/api/v1/projects/p1/sandbox/desktop/proxy", ""),
        (
            "GET",
            "/api/v1/projects/p1/sandbox/desktop/proxy/app.js",
            "",
        ),
        (
            "GET",
            "/api/v1/projects/p1/sandbox/http-services/web/proxy",
            "",
        ),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/http-services/web/proxy",
            "{}",
        ),
        (
            "DELETE",
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/docs",
            "",
        ),
    ] {
        let request = match method {
            "GET" => http.get(format!("{gateway_url}{path}")),
            "POST" => http.post(format!("{gateway_url}{path}")).body(body_in),
            "DELETE" => http.delete(format!("{gateway_url}{path}")),
            _ => unreachable!(),
        };
        let r = request
            .header("authorization", bearer)
            .send()
            .await
            .unwrap();
        let body = r.text().await.unwrap();
        assert!(
            body.contains("\"backend\":\"rust\""),
            "P5 sandbox control-plane {method} {path} -> rust: {body}"
        );
    }

    for (method, path, body_in) in [
        ("POST", "/api/v1/projects/sandboxes", "{}"),
        ("GET", "/api/v1/projects/sandboxes/stats", ""),
        ("GET", "/api/v1/projects/sandboxes/members", ""),
        (
            "POST",
            "/api/v1/projects/sandboxes/members",
            "{'user_id':'u1'}",
        ),
        ("PUT", "/api/v1/projects/p1/sandbox", "{}"),
        ("GET", "/api/v1/projects/p1/sandbox/restart", ""),
        (
            "GET",
            "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
            "",
        ),
        (
            "GET",
            "/api/v1/projects/sandboxes/sandbox/http-services/web/proxy",
            "",
        ),
    ] {
        let request = match method {
            "GET" => http.get(format!("{gateway_url}{path}")),
            "POST" => http.post(format!("{gateway_url}{path}")).body(body_in),
            "PUT" => http.put(format!("{gateway_url}{path}")).body(body_in),
            _ => unreachable!(),
        };
        let r = request
            .header("authorization", bearer)
            .send()
            .await
            .unwrap();
        let body = r.text().await.unwrap();
        assert!(
            body.contains("\"backend\":\"python\""),
            "P5 rollback/data-plane boundary {method} {path} remains python: {body}"
        );
    }
}
