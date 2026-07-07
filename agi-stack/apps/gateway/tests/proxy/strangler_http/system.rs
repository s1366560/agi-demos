use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_system_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/system/features",
        "/api/v1/system/features/",
        "/api/v1/system/info",
        "/api/v1/system/info/",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(
            &body,
            "rust",
            &format!("system metadata {path} should route to rust"),
        );
    }

    for (method, path, body_in) in [
        ("POST", "/api/v1/system/features", "{}"),
        ("POST", "/api/v1/system/info", "{}"),
        ("GET", "/api/v1/system", ""),
        ("GET", "/api/v1/system/status", ""),
        ("GET", "/api/v1/system/features/extra", ""),
        ("GET", "/api/v1/system/info/extra", ""),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("system metadata rollback boundary {method} {path} remains python"),
        );
    }
}
