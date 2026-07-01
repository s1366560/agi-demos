//! The **strangler-fig gateway** (plan.md Section 14.1) — the single front door
//! that lets the Rust rewrite replace the Python backend one capability at a
//! time, with zero frontend changes and instant rollback.
//!
//! ```text
//!  client ──▶ gateway ──▶ /api/v1/memories|episodes|recall  ──▶ agistack-server (Rust)
//!                     └──▶ everything else                    ──▶ Python backend (legacy)
//! ```
//!
//! A capability is "strangled" by moving its path prefix into
//! [`STRANGLED_PREFIXES`]. Because both backends speak the same `/api/v1`
//! contract, same `ms_sk_` bearer auth, and same JSON shapes (guaranteed by the
//! P1 parity work), the client cannot tell which backend served a request — the
//! essence of the strangler pattern. Rollback = move the prefix back.
//!
//! The gateway is a dumb, deterministic reverse proxy: **routing is pure path
//! prefix matching** (no semantics), and it forwards method/headers/body
//! verbatim — including `Authorization`, so bearer auth passes through unchanged.

use std::sync::Arc;

use axum::{
    body::Body,
    extract::State,
    http::{HeaderMap, HeaderName, Request, Response, StatusCode},
};

/// Path prefixes already served by the Rust server. Everything else falls
/// through to the Python upstream. Add a prefix here to strangle a capability;
/// remove it to roll back.
pub const STRANGLED_PREFIXES: &[&str] = &[
    "/api/v1/memories",
    "/api/v1/episodes",
    "/api/v1/recall",
    // P2 login vertical (surgical — coarse prefix match, so only fully-covered
    // paths are listed). `/auth/token` and `/auth/oauth/*` are complete in Rust;
    // other `/auth/*` siblings (force-change-password, me, ...) and `/tenants/*`
    // stay in Python until their whole resource is covered (see identity.rs).
    "/api/v1/auth/token",
    "/api/v1/auth/oauth",
];

/// Max proxied body size (request or response) — 25 MiB, generous for JSON
/// payloads while bounding memory. Larger streaming bodies (e.g. agent token
/// streams, P3) will need a streaming path; not required for P1.
const MAX_BODY_BYTES: usize = 25 * 1024 * 1024;

/// Where the two backends live. Both are plain base URLs (no trailing slash),
/// e.g. `http://127.0.0.1:8088` (Rust) and `http://127.0.0.1:8000` (Python).
#[derive(Clone, Debug)]
pub struct Upstreams {
    pub rust: String,
    pub python: String,
}

/// True when `path` belongs to an already-strangled capability and should be
/// routed to the Rust server. Pure prefix match — deterministic, no judgment.
pub fn is_strangled(path: &str) -> bool {
    STRANGLED_PREFIXES.iter().any(|p| {
        // Match the prefix exactly or as a path segment boundary so
        // `/api/v1/memories` and `/api/v1/memories/123` match but a hypothetical
        // `/api/v1/memories_admin` does not.
        path == *p || path.starts_with(&format!("{p}/"))
    })
}

/// Pick the upstream base URL for a request path.
pub fn upstream_for<'a>(path: &str, upstreams: &'a Upstreams) -> &'a str {
    if is_strangled(path) {
        &upstreams.rust
    } else {
        &upstreams.python
    }
}

/// Shared gateway state: a reusable HTTP client + the upstream addresses.
#[derive(Clone)]
pub struct GatewayState {
    pub client: reqwest::Client,
    pub upstreams: Arc<Upstreams>,
}

impl GatewayState {
    pub fn new(upstreams: Upstreams) -> Self {
        let client = reqwest::Client::builder()
            // Do not follow redirects: a 307 from a backend must reach the client
            // unchanged (mirrors FastAPI trailing-slash semantics end to end).
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .expect("build reqwest client");
        Self {
            client,
            upstreams: Arc::new(upstreams),
        }
    }
}

/// Hop-by-hop headers (RFC 7230 §6.1) plus framing headers we must not copy
/// verbatim, since the proxied body is re-framed by the client/server.
fn is_hop_by_hop(name: &HeaderName) -> bool {
    matches!(
        name.as_str(),
        "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailer"
            | "transfer-encoding"
            | "upgrade"
            | "content-length"
            | "host"
    )
}

/// Copy end-to-end headers from `src` into `dst`, dropping hop-by-hop/framing
/// headers. `Authorization` is end-to-end, so bearer tokens pass through.
fn copy_end_to_end_headers(src: &HeaderMap, dst: &mut HeaderMap) {
    for (name, value) in src.iter() {
        if !is_hop_by_hop(name) {
            dst.append(name.clone(), value.clone());
        }
    }
}

/// The catch-all proxy handler: forward any request to the upstream chosen by
/// its path, preserving method, end-to-end headers (incl. `Authorization`), and
/// body, then relay the upstream's status/headers/body back to the client.
pub async fn proxy(State(state): State<GatewayState>, req: Request<Body>) -> Response<Body> {
    let (parts, body) = req.into_parts();
    let path = parts.uri.path().to_string();
    let path_and_query = parts
        .uri
        .path_and_query()
        .map(|pq| pq.as_str())
        .unwrap_or("/");

    let upstream = upstream_for(&path, &state.upstreams);
    let url = format!("{upstream}{path_and_query}");

    let body_bytes = match axum::body::to_bytes(body, MAX_BODY_BYTES).await {
        Ok(bytes) => bytes,
        Err(_) => return error_response(StatusCode::PAYLOAD_TOO_LARGE, "request body too large"),
    };

    // Build the upstream request: same method + end-to-end headers + body.
    let mut forward_headers = HeaderMap::new();
    copy_end_to_end_headers(&parts.headers, &mut forward_headers);

    let upstream_response = state
        .client
        .request(parts.method.clone(), &url)
        .headers(forward_headers)
        .body(body_bytes)
        .send()
        .await;

    let resp = match upstream_response {
        Ok(resp) => resp,
        Err(err) => {
            // Upstream unreachable / transport error -> 502, like a real gateway.
            return error_response(
                StatusCode::BAD_GATEWAY,
                &format!("upstream request failed: {err}"),
            );
        }
    };

    let status = resp.status();
    let mut response_headers = HeaderMap::new();
    copy_end_to_end_headers(resp.headers(), &mut response_headers);

    let resp_bytes = match resp.bytes().await {
        Ok(bytes) => bytes,
        Err(err) => {
            return error_response(
                StatusCode::BAD_GATEWAY,
                &format!("reading upstream response failed: {err}"),
            )
        }
    };

    let mut out = Response::new(Body::from(resp_bytes));
    *out.status_mut() = status;
    *out.headers_mut() = response_headers;
    out
}

/// A minimal JSON error envelope matching the `{"detail": ...}` shape the rest
/// of the stack uses.
fn error_response(status: StatusCode, detail: &str) -> Response<Body> {
    let body = format!("{{\"detail\":\"{}\"}}", detail.replace('"', "'"));
    let mut resp = Response::new(Body::from(body));
    *resp.status_mut() = status;
    resp.headers_mut().insert(
        axum::http::header::CONTENT_TYPE,
        axum::http::HeaderValue::from_static("application/json"),
    );
    resp
}

/// Build the gateway router: a single catch-all that proxies every method and
/// path. Callers `serve` this or drive it in tests.
pub fn app(state: GatewayState) -> axum::Router {
    use axum::routing::any;
    axum::Router::new()
        .fallback(any(proxy))
        .with_state(state)
}

#[cfg(test)]
mod unit {
    use super::*;

    fn ups() -> Upstreams {
        Upstreams {
            rust: "http://rust:8088".into(),
            python: "http://python:8000".into(),
        }
    }

    #[test]
    fn strangled_prefixes_route_to_rust() {
        assert!(is_strangled("/api/v1/memories"));
        assert!(is_strangled("/api/v1/memories/"));
        assert!(is_strangled("/api/v1/memories/abc123"));
        assert!(is_strangled("/api/v1/episodes/"));
        assert!(is_strangled("/api/v1/recall/short"));
        // P2 login vertical.
        assert!(is_strangled("/api/v1/auth/token"));
        assert!(is_strangled("/api/v1/auth/oauth/google/callback"));
        for p in [
            "/api/v1/memories",
            "/api/v1/episodes/",
            "/api/v1/recall/short",
            "/api/v1/auth/token",
            "/api/v1/auth/oauth/github/callback",
        ] {
            assert_eq!(upstream_for(p, &ups()), "http://rust:8088");
        }
    }

    #[test]
    fn everything_else_routes_to_python() {
        for p in [
            "/api/v1/projects",
            // Other `/auth/*` siblings remain in Python (surgical strangling).
            "/api/v1/auth/force-change-password",
            "/api/v1/auth/me",
            "/api/v1/auth/tokens", // not a segment boundary of `/auth/token`
            // Tenants read is implemented but its flip is deferred.
            "/api/v1/tenants",
            "/api/v1/tenants/t1",
            "/api/v1/agent/ws",
            "/api/v1/memories_admin", // not a segment boundary -> not strangled
            "/health",
            "/",
        ] {
            assert!(!is_strangled(p), "{p} should not be strangled");
            assert_eq!(upstream_for(p, &ups()), "http://python:8000");
        }
    }

    #[test]
    fn authorization_is_end_to_end() {
        // The bearer token must survive proxying -> not hop-by-hop.
        assert!(!is_hop_by_hop(&HeaderName::from_static("authorization")));
        // Framing/hop-by-hop headers are dropped.
        assert!(is_hop_by_hop(&HeaderName::from_static("content-length")));
        assert!(is_hop_by_hop(&HeaderName::from_static("connection")));
        assert!(is_hop_by_hop(&HeaderName::from_static("transfer-encoding")));
    }
}
