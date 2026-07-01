//! End-to-end proof of the strangler gateway (plan.md Section 14.4 step 4):
//! two mock upstreams (a stand-in Rust server and a stand-in Python backend) +
//! the real gateway. We assert that strangled prefixes reach the Rust upstream,
//! everything else reaches the Python upstream, the `Authorization` bearer is
//! forwarded unchanged, method + body are preserved, and upstream redirects are
//! relayed (not followed). No full Python stack required.

use std::net::SocketAddr;

use axum::{
    body::Body,
    extract::State,
    http::{header::CONTENT_TYPE, HeaderValue, Request, Response, StatusCode},
    routing::get,
    Router,
};

use agistack_gateway::{app, GatewayState, Upstreams};

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
    let method = parts.method.as_str().to_string();
    let path = parts.uri.path().to_string();
    let body_bytes = axum::body::to_bytes(body, 1 << 20).await.unwrap_or_default();
    let body_str = String::from_utf8_lossy(&body_bytes).replace('"', "'");
    let json = format!(
        "{{\"backend\":\"{backend}\",\"method\":\"{method}\",\"path\":\"{path}\",\"auth\":\"{auth}\",\"body\":\"{body_str}\"}}"
    );
    let mut resp = Response::new(Body::from(json));
    resp.headers_mut()
        .insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
    resp
}

async fn redirect() -> Response<Body> {
    let mut resp = Response::new(Body::empty());
    *resp.status_mut() = StatusCode::TEMPORARY_REDIRECT;
    resp.headers_mut()
        .insert(axum::http::header::LOCATION, HeaderValue::from_static("/moved"));
    resp
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
        .fallback(get(echo).post(echo).delete(echo))
        .with_state("rust");
    let python_mock = Router::new()
        .route("/api/v1/redirect", get(redirect))
        .fallback(get(echo).post(echo).delete(echo))
        .with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;

    // The real gateway pointing at both mocks.
    let gateway_state = GatewayState::new(Upstreams {
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
    assert!(body.contains("\"backend\":\"rust\""), "routed to rust: {body}");
    assert!(body.contains("\"path\":\"/api/v1/memories/\""), "path preserved: {body}");
    assert!(
        body.contains(&format!("\"auth\":\"{bearer}\"")),
        "bearer forwarded: {body}"
    );

    // 2) Non-strangled GET -> Python upstream.
    let r = http
        .get(format!("{gateway_url}/api/v1/projects"))
        .header("authorization", bearer)
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(body.contains("\"backend\":\"python\""), "routed to python: {body}");

    // 3) Strangled POST with a body -> Rust upstream, method + body preserved.
    let r = http
        .post(format!("{gateway_url}/api/v1/episodes/"))
        .header("authorization", bearer)
        .body("{'content':'hello'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(body.contains("\"backend\":\"rust\""), "episodes -> rust: {body}");
    assert!(body.contains("\"method\":\"POST\""), "method preserved: {body}");
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
}
