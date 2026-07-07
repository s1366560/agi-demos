use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_maintenance_routing(ctx: &StranglerHttpContext) {
    for path in ["/api/v1/maintenance/status", "/api/v1/maintenance/status/"] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(
            &body,
            "rust",
            &format!("maintenance status {path} routes to rust"),
        );
    }

    for (method, path, body_in) in [
        ("POST", "/api/v1/maintenance/status", "{}"),
        ("GET", "/api/v1/maintenance", ""),
        ("GET", "/api/v1/maintenance/status/extra", ""),
        ("POST", "/api/v1/maintenance/refresh/incremental", "{}"),
        ("POST", "/api/v1/maintenance/optimize", "{}"),
        ("POST", "/api/v1/maintenance/invalidate/stale-edges", "{}"),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("maintenance rollback boundary {method} {path} remains python"),
        );
    }
}
