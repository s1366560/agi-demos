//! End-to-end proof of the strangler gateway (plan.md Section 14.4 step 4):
//! two mock upstreams (a stand-in Rust server and a stand-in Python backend) +
//! the real gateway. We assert that strangled prefixes reach the Rust upstream,
//! everything else reaches the Python upstream, the `Authorization` bearer is
//! forwarded unchanged, method + body are preserved, and upstream redirects are
//! relayed (not followed). No full Python stack required.

use std::net::SocketAddr;

use axum::{
    body::Body,
    extract::{
        ws::{Message as AxumWsMessage, WebSocketUpgrade},
        State,
    },
    http::{header::CONTENT_TYPE, HeaderMap, HeaderValue, Request, Response, StatusCode, Uri},
    response::IntoResponse,
    routing::get,
    Router,
};
use futures_util::{SinkExt, StreamExt};
use tokio_tungstenite::{
    connect_async,
    tungstenite::{client::IntoClientRequest, Message as TungsteniteMessage},
};

use agistack_gateway::{app, GatewayState, Upstreams};

fn gateway_state(upstreams: Upstreams) -> GatewayState {
    GatewayState::try_new(upstreams).expect("test reqwest client should build")
}

/// A mock upstream that echoes which backend served the request plus the method,
/// path, forwarded `Authorization`, and body — so the test can assert routing
/// and header/body passthrough.
async fn echo(State(backend): State<&'static str>, req: Request<Body>) -> Response<Body> {
    let (parts, body) = req.into_parts();
    let auth = parts
        .headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let host = parts
        .headers
        .get("host")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let method = parts.method.as_str().to_string();
    let path = parts.uri.path().to_string();
    let body_bytes = axum::body::to_bytes(body, 1 << 20)
        .await
        .unwrap_or_default();
    let body_str = String::from_utf8_lossy(&body_bytes).replace('"', "'");
    let json = format!(
        "{{\"backend\":\"{backend}\",\"method\":\"{method}\",\"path\":\"{path}\",\"host\":\"{host}\",\"auth\":\"{auth}\",\"body\":\"{body_str}\"}}"
    );
    let mut resp = Response::new(Body::from(json));
    resp.headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    resp
}

async fn redirect() -> Response<Body> {
    let mut resp = Response::new(Body::empty());
    *resp.status_mut() = StatusCode::TEMPORARY_REDIRECT;
    resp.headers_mut().insert(
        axum::http::header::LOCATION,
        HeaderValue::from_static("/moved"),
    );
    resp
}

async fn ws_echo(
    State(backend): State<&'static str>,
    headers: HeaderMap,
    uri: Uri,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    let protocol = headers
        .get("sec-websocket-protocol")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let auth = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let host = headers
        .get("host")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    let path = uri.path().to_string();
    ws.protocols(["memstack.auth", "binary"])
        .on_upgrade(move |mut socket| async move {
            let Some(Ok(AxumWsMessage::Text(text))) = socket.recv().await else {
                return;
            };
            let body = format!(
                "{{\"backend\":\"{backend}\",\"path\":\"{path}\",\"host\":\"{host}\",\"protocol\":\"{protocol}\",\"auth\":\"{auth}\",\"message\":{text}}}"
            );
            let _ = socket.send(AxumWsMessage::Text(body)).await;
        })
}

/// Bind an axum app on an ephemeral port and serve it in the background; return
/// its base URL (e.g. `http://127.0.0.1:54321`).
async fn spawn(router: Router) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, router).await.unwrap();
    });
    format!("http://{addr}")
}

fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .unwrap()
}

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

#[tokio::test]
async fn gateway_proxies_agent_ws_to_rust_with_protocol_auth_passthrough() {
    let rust_mock = Router::new()
        .route("/api/v1/agent/ws", get(ws_echo))
        .fallback(get(echo))
        .with_state("rust");
    let python_mock = Router::new().fallback(get(echo)).with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;
    let gateway_url = spawn(app(gateway_state(Upstreams {
        rust: rust_url,
        python: python_url,
    })))
    .await;

    let ws_url = gateway_url.replacen("http://", "ws://", 1) + "/api/v1/agent/ws?session_id=s1";
    let mut request = ws_url.into_client_request().unwrap();
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static("memstack.auth, ms_sk_ws_e2e"),
    );
    request.headers_mut().insert(
        "authorization",
        HeaderValue::from_static("Bearer ms_sk_ws_header"),
    );

    let (mut ws, response) = connect_async(request).await.unwrap();
    assert_eq!(
        response
            .headers()
            .get("sec-websocket-protocol")
            .and_then(|v| v.to_str().ok()),
        Some("memstack.auth")
    );

    ws.send(TungsteniteMessage::Text(
        "{\"type\":\"heartbeat\"}".to_string(),
    ))
    .await
    .unwrap();
    let message = ws.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(body) = message else {
        panic!("expected text message, got {message:?}");
    };
    assert!(body.contains("\"backend\":\"rust\""), "{body}");
    assert!(body.contains("\"path\":\"/api/v1/agent/ws\""), "{body}");
    assert!(
        body.contains("\"protocol\":\"memstack.auth, ms_sk_ws_e2e\""),
        "{body}"
    );
    assert!(
        body.contains("\"auth\":\"Bearer ms_sk_ws_header\""),
        "{body}"
    );
    assert!(body.contains("\"type\":\"heartbeat\""), "{body}");
}

#[tokio::test]
async fn gateway_proxies_p5_sandbox_ws_to_rust_with_protocol_auth_passthrough() {
    let rust_mock = Router::new()
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/websockify",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal/proxy/ws",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/mcp/proxy",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws",
            get(ws_echo),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/http-services/:service_id/proxy/ws/*path",
            get(ws_echo),
        )
        .fallback(get(echo))
        .with_state("rust");
    let python_mock = Router::new().fallback(get(echo)).with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;
    let gateway_url = spawn(app(gateway_state(Upstreams {
        rust: rust_url,
        python: python_url,
    })))
    .await;

    for (path, protocol, expected_selected_protocol) in [
        (
            "/api/v1/projects/p1/sandbox/terminal/proxy/ws?session_id=term1",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/mcp/proxy?token=ms_sk_ws_p5",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws?token=ms_sk_ws_p5",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket?token=ms_sk_ws_p5",
            "memstack.auth, ms_sk_ws_p5",
            "memstack.auth",
        ),
        (
            "/api/v1/projects/p1/sandbox/desktop/proxy/websockify?token=ms_sk_ws_p5",
            "binary",
            "binary",
        ),
    ] {
        let ws_url = gateway_url.replacen("http://", "ws://", 1) + path;
        let mut request = ws_url.into_client_request().unwrap();
        request.headers_mut().insert(
            "sec-websocket-protocol",
            HeaderValue::from_str(protocol).unwrap(),
        );
        request.headers_mut().insert(
            "authorization",
            HeaderValue::from_static("Bearer ms_sk_ws_header"),
        );

        let (mut ws, response) = connect_async(request).await.unwrap();
        assert_eq!(
            response
                .headers()
                .get("sec-websocket-protocol")
                .and_then(|v| v.to_str().ok()),
            Some(expected_selected_protocol),
            "{path}"
        );

        ws.send(TungsteniteMessage::Text(
            "{\"type\":\"p5_probe\"}".to_string(),
        ))
        .await
        .unwrap();
        let message = ws.next().await.unwrap().unwrap();
        let TungsteniteMessage::Text(body) = message else {
            panic!("expected text message, got {message:?}");
        };
        assert!(body.contains("\"backend\":\"rust\""), "{body}");
        assert!(
            body.contains("\"auth\":\"Bearer ms_sk_ws_header\""),
            "{body}"
        );
        assert!(body.contains("\"type\":\"p5_probe\""), "{body}");
        assert!(
            body.contains(&format!("\"protocol\":\"{protocol}\"")),
            "{body}"
        );
    }
}

#[tokio::test]
async fn gateway_routes_preview_host_http_to_rust_and_preserves_host() {
    let rust_mock = Router::new()
        .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
        .with_state("rust");
    let python_mock = Router::new()
        .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
        .with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;
    let gateway_url = spawn(app(gateway_state(Upstreams {
        rust: rust_url,
        python: python_url,
    })))
    .await;

    let http = client();
    let r = http
        .post(format!(
            "{gateway_url}/docs/app?ms_preview_session=session1"
        ))
        .header("host", "web.p1.preview.localhost:8000")
        .header("authorization", "Bearer ms_sk_preview_http")
        .body("{'probe':'preview'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "preview host HTTP -> rust: {body}"
    );
    assert!(body.contains("\"method\":\"POST\""), "{body}");
    assert!(body.contains("\"path\":\"/docs/app\""), "{body}");
    assert!(
        body.contains("\"host\":\"web.p1.preview.localhost:8000\""),
        "original preview host preserved for Rust parser: {body}"
    );
    assert!(body.contains("preview"), "{body}");

    let r = http
        .get(format!("{gateway_url}/docs/app"))
        .header("host", "web.p1.other.localhost:8000")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "non-preview host remains python: {body}"
    );
}

#[tokio::test]
async fn gateway_routes_preview_host_ws_to_rust_and_preserves_host() {
    let rust_mock = Router::new().fallback(get(ws_echo)).with_state("rust");
    let python_mock = Router::new().fallback(get(echo)).with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;
    let gateway_url = spawn(app(gateway_state(Upstreams {
        rust: rust_url,
        python: python_url,
    })))
    .await;

    let ws_url =
        gateway_url.replacen("http://", "ws://", 1) + "/socket?ms_preview_session=session1";
    let mut request = ws_url.into_client_request().unwrap();
    request.headers_mut().insert(
        "host",
        HeaderValue::from_static("web.p1.preview.localhost:8000"),
    );
    request.headers_mut().insert(
        "sec-websocket-protocol",
        HeaderValue::from_static("memstack.auth, ms_sk_preview_ws"),
    );
    request.headers_mut().insert(
        "authorization",
        HeaderValue::from_static("Bearer ms_sk_preview_ws_header"),
    );

    let (mut ws, response) = connect_async(request).await.unwrap();
    assert_eq!(
        response
            .headers()
            .get("sec-websocket-protocol")
            .and_then(|v| v.to_str().ok()),
        Some("memstack.auth")
    );

    ws.send(TungsteniteMessage::Text(
        "{\"type\":\"preview_probe\"}".to_string(),
    ))
    .await
    .unwrap();
    let message = ws.next().await.unwrap().unwrap();
    let TungsteniteMessage::Text(body) = message else {
        panic!("expected text message, got {message:?}");
    };
    assert!(body.contains("\"backend\":\"rust\""), "{body}");
    assert!(body.contains("\"path\":\"/socket\""), "{body}");
    assert!(
        body.contains("\"host\":\"web.p1.preview.localhost:8000\""),
        "{body}"
    );
    assert!(
        body.contains("\"protocol\":\"memstack.auth, ms_sk_preview_ws\""),
        "{body}"
    );
    assert!(
        body.contains("\"auth\":\"Bearer ms_sk_preview_ws_header\""),
        "{body}"
    );
    assert!(body.contains("\"type\":\"preview_probe\""), "{body}");
}
