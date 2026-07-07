use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_notification_routing(ctx: &StranglerHttpContext) {
    for (method, path, body) in [
        ("GET", "/api/v1/notifications/", ""),
        (
            "GET",
            "/api/v1/notifications/?unread_only=true&limit=10",
            "",
        ),
        ("PUT", "/api/v1/notifications/n1/read", "{}"),
        ("PUT", "/api/v1/notifications/read-all", "{}"),
        ("DELETE", "/api/v1/notifications/n1", ""),
        (
            "POST",
            "/api/v1/notifications/create",
            r#"{"type":"general","title":"Notice"}"#,
        ),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "rust", path);
    }

    for (method, path, body) in [
        ("GET", "/api/v1/notifications", ""),
        ("POST", "/api/v1/notifications/", "{}"),
        ("GET", "/api/v1/notifications/n1/read", ""),
        ("POST", "/api/v1/notifications/n1/read", "{}"),
        ("DELETE", "/api/v1/notifications/read-all", ""),
        ("DELETE", "/api/v1/notifications/create", ""),
        ("PUT", "/api/v1/notifications/n1/archive", "{}"),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
