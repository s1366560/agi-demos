use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_support_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/support/tickets",
        "/api/v1/support/tickets?tenant_id=tenant-1&status=open&limit=10&offset=0",
        "/api/v1/support/tickets/ticket-1",
        "/support/tickets",
        "/support/tickets?tenant_id=tenant-1&status=open&limit=10&offset=0",
        "/support/tickets/ticket-1",
    ] {
        let response = ctx.authed_body("GET", path, "").await;
        assert_backend(&response, "rust", path);
    }
    for (method, path, body) in [
        (
            "POST",
            "/api/v1/support/tickets",
            r#"{"subject":"Issue","message":"Help","priority":"high"}"#,
        ),
        (
            "PUT",
            "/api/v1/support/tickets/ticket-1",
            r#"{"subject":"Updated"}"#,
        ),
        ("POST", "/api/v1/support/tickets/ticket-1/close", "{}"),
        (
            "POST",
            "/support/tickets",
            r#"{"subject":"Issue","message":"Help","priority":"high"}"#,
        ),
        (
            "PUT",
            "/support/tickets/ticket-1",
            r#"{"subject":"Updated"}"#,
        ),
        ("POST", "/support/tickets/ticket-1/close", "{}"),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "rust", path);
    }

    for (method, path, body) in [
        ("DELETE", "/api/v1/support/tickets/ticket-1", ""),
        ("POST", "/api/v1/support/tickets/ticket-1/reopen", "{}"),
        ("GET", "/api/v1/support/tickets/ticket-1/close", ""),
        ("DELETE", "/support/tickets/ticket-1", ""),
        ("POST", "/support/tickets/ticket-1/reopen", "{}"),
        ("GET", "/support/tickets/ticket-1/close", ""),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
