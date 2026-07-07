use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_events_routing(ctx: &StranglerHttpContext) {
    for (method, path, body) in [
        ("GET", "/api/v1/events", ""),
        ("GET", "/api/v1/events?tenant_id=tenant-1&page=2", ""),
        ("GET", "/api/v1/events/types", ""),
        ("GET", "/api/v1/events/types?tenant_id=tenant-1", ""),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "rust", path);
    }

    for (method, path, body) in [
        ("GET", "/api/v1/events/filter", ""),
        ("GET", "/api/v1/events/export", ""),
        ("GET", "/api/v1/events/types/extra", ""),
        ("POST", "/api/v1/events", "{}"),
        ("POST", "/api/v1/events/types", "{}"),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
