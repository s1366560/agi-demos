use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_admin_dlq_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/admin/dlq/messages?status=pending&limit=10&offset=0",
        "/api/v1/admin/dlq/messages/",
        "/api/v1/admin/dlq/messages/dlq-1",
        "/api/v1/admin/dlq/stats",
        "/api/v1/admin/dlq/stats/",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
        assert!(
            body.contains(ctx.bearer),
            "admin DLQ strangler request should preserve authorization: {body}"
        );
    }

    for (method, path, body) in [
        (
            "DELETE",
            "/api/v1/admin/dlq/messages/dlq-1?reason=operator",
            "",
        ),
        ("POST", "/api/v1/admin/dlq/messages/dlq-1/retry", "{}"),
        (
            "POST",
            "/api/v1/admin/dlq/messages/retry",
            "{\"message_ids\":[\"dlq-1\"]}",
        ),
        (
            "POST",
            "/api/v1/admin/dlq/messages/discard",
            "{\"message_ids\":[\"dlq-1\"],\"reason\":\"operator\"}",
        ),
        ("POST", "/api/v1/admin/dlq/cleanup/expired", ""),
        ("POST", "/api/v1/admin/dlq/cleanup/resolved", ""),
    ] {
        let body = ctx.authed_body(method, path, body).await;
        assert_backend(&body, "rust", path);
    }

    for (method, path, body) in [
        ("GET", "/api/v1/admin/dlq/messages/retry", ""),
        ("GET", "/api/v1/admin/dlq/cleanup/expired", ""),
    ] {
        let body = ctx.authed_body(method, path, body).await;
        assert_backend(&body, "python", path);
    }
}
