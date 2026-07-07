use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_artifact_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/artifacts?project_id=project-1",
        "/api/v1/artifacts/?project_id=project-1",
        "/api/v1/artifacts/artifact-1",
        "/api/v1/artifacts/categories/list",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
        assert!(
            body.contains(ctx.bearer),
            "artifact strangler request should preserve authorization: {body}"
        );
    }

    let body = ctx
        .authed_body("PUT", "/api/v1/artifacts/artifact-1/content", "{}")
        .await;
    assert_backend(&body, "rust", "/api/v1/artifacts/artifact-1/content");
    assert!(
        body.contains(ctx.bearer),
        "artifact content update strangler request should preserve authorization: {body}"
    );

    let body = ctx
        .authed_body("DELETE", "/api/v1/artifacts/artifact-1", "")
        .await;
    assert_backend(&body, "rust", "/api/v1/artifacts/artifact-1");
    assert!(
        body.contains(ctx.bearer),
        "artifact delete strangler request should preserve authorization: {body}"
    );

    for (method, path) in [
        ("POST", "/api/v1/artifacts"),
        ("POST", "/api/v1/artifacts/categories/list"),
        ("GET", "/api/v1/artifacts/categories/list/extra"),
        ("GET", "/api/v1/artifacts/artifact-1/download"),
        ("POST", "/api/v1/artifacts/artifact-1/refresh-url"),
        ("GET", "/api/v1/artifacts/artifact-1/content"),
        ("PUT", "/api/v1/artifacts/artifact-1/content/extra"),
        ("PUT", "/api/v1/artifacts/categories/content"),
        ("DELETE", "/api/v1/artifacts/artifact-1/content"),
        ("DELETE", "/api/v1/artifacts/categories"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
