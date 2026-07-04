use super::*;

#[path = "strangler_http/base.rs"]
mod base;
#[path = "strangler_http/identity.rs"]
mod identity;
#[path = "strangler_http/projects_sandbox.rs"]
mod projects_sandbox;

pub(super) struct StranglerHttpContext {
    pub(super) gateway_url: String,
    pub(super) http: reqwest::Client,
    pub(super) bearer: &'static str,
}

impl StranglerHttpContext {
    async fn new() -> Self {
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
        let gateway_url = spawn(app(gateway_state(Upstreams {
            rust: rust_url,
            python: python_url,
        })))
        .await;

        Self {
            gateway_url,
            http: client(),
            bearer: "Bearer ms_sk_e2e_testkey",
        }
    }

    pub(super) fn url(&self, path: &str) -> String {
        format!("{}{}", self.gateway_url, path)
    }

    pub(super) fn request(&self, method: &str, path: &str, body: &str) -> reqwest::RequestBuilder {
        match method {
            "GET" => self.http.get(self.url(path)),
            "POST" => self.http.post(self.url(path)).body(body.to_string()),
            "PUT" => self.http.put(self.url(path)).body(body.to_string()),
            "PATCH" => self.http.patch(self.url(path)).body(body.to_string()),
            "DELETE" => self.http.delete(self.url(path)),
            _ => unreachable!("unsupported test method {method}"),
        }
    }

    pub(super) fn authed(&self, request: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        request.header("authorization", self.bearer)
    }

    pub(super) async fn body(&self, request: reqwest::RequestBuilder) -> String {
        request
            .send()
            .await
            .expect("gateway proxy request should complete")
            .text()
            .await
            .expect("gateway proxy response body should be readable")
    }

    pub(super) async fn authed_body(&self, method: &str, path: &str, body: &str) -> String {
        self.body(self.authed(self.request(method, path, body)))
            .await
    }

    pub(super) async fn public_body(&self, method: &str, path: &str, body: &str) -> String {
        self.body(self.request(method, path, body)).await
    }
}

pub(super) fn assert_backend(body: &str, backend: &str, context: &str) {
    assert!(
        body.contains(&format!("\"backend\":\"{backend}\"")),
        "{context}: {body}"
    );
}

#[tokio::test]
async fn gateway_routes_strangled_to_rust_and_rest_to_python_with_auth_passthrough() {
    let ctx = StranglerHttpContext::new().await;

    base::assert_base_routing(&ctx).await;
    identity::assert_identity_and_shares_routing(&ctx).await;
    projects_sandbox::assert_project_and_sandbox_routing(&ctx).await;
}
