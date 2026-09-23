//! The credential-free, fixed iframe bootstrap is not an API authority surface.
use axum::{http::header, response::Html, routing::get, Router};

const SANDBOX_PROXY: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../../src/infrastructure/adapters/primary/web/static/sandbox_proxy.html"
));

pub(super) fn router() -> Router {
    Router::new().route(
        "/static/sandbox_proxy.html",
        get(|| async {
            (
                [
                    (header::CACHE_CONTROL, "no-store"),
                    (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
                ],
                Html(SANDBOX_PROXY),
            )
        }),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::{to_bytes, Body},
        http::{Request, StatusCode},
    };
    use tower::ServiceExt;

    #[tokio::test]
    async fn only_fixed_iframe_bootstrap_is_public_while_api_authority_remains_required() {
        let state = super::super::tests::test_state("app-proxy-public-test");
        let app = super::super::local_router(state);
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/static/sandbox_proxy.html")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(
            response.headers()[header::CONTENT_TYPE],
            "text/html; charset=utf-8"
        );
        assert_eq!(response.headers()[header::CACHE_CONTROL], "no-store");
        assert_eq!(
            response.headers()[header::X_CONTENT_TYPE_OPTIONS],
            "nosniff"
        );
        let html = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        assert_eq!(html.as_ref(), SANDBOX_PROXY.as_bytes());
        for path in [
            "/api/v1/mcp/apps",
            "/api/v1/auth/local-session",
            "/static/private.html",
            "/static/sandbox_proxy.html/private",
        ] {
            let response = app
                .clone()
                .oneshot(Request::builder().uri(path).body(Body::empty()).unwrap())
                .await
                .unwrap();
            assert_eq!(response.status(), StatusCode::UNAUTHORIZED, "{path}");
        }
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/static/sandbox_proxy.html")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::METHOD_NOT_ALLOWED);
    }
}
