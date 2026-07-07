use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_engine_routing(ctx: &StranglerHttpContext) {
    let body = ctx.public_body("GET", "/api/v1/engines", "").await;
    assert_backend(&body, "rust", "runtime engine catalog should route to rust");
    let body = ctx.public_body("GET", "/api/v1/engines/", "").await;
    assert_backend(
        &body,
        "rust",
        "runtime engine catalog trailing slash should route to rust",
    );

    for (method, path, body_in) in [
        ("POST", "/api/v1/engines", "{}"),
        ("GET", "/api/v1/engines/python-3.12", ""),
        ("POST", "/api/v1/sandbox/create", "{}"),
        ("GET", "/api/v1/sandbox/list", ""),
        ("GET", "/api/v1/sandbox/sandbox-1", ""),
    ] {
        let body = ctx.public_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("runtime engine rollback boundary {method} {path} remains python"),
        );
    }
}
