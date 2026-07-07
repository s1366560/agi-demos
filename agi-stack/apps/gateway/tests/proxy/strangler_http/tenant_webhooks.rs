use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_tenant_webhook_routing(ctx: &StranglerHttpContext) {
    let response = ctx
        .authed_body("GET", "/api/v1/tenant-webhooks/tenant-1", "")
        .await;
    assert_backend(&response, "rust", "GET tenant webhooks");
    let response = ctx
        .authed_body(
            "POST",
            "/api/v1/tenant-webhooks/tenant-1",
            r#"{"name":"Deploy","url":"https://example.test/hook","events":["memory.created"],"is_active":true}"#,
        )
        .await;
    assert_backend(&response, "rust", "POST tenant webhook");
    let response = ctx
        .authed_body(
            "PUT",
            "/api/v1/tenant-webhooks/webhook-1",
            r#"{"name":"Deploy","url":"https://example.test/hook","events":["memory.created"],"is_active":true}"#,
        )
        .await;
    assert_backend(&response, "rust", "PUT tenant webhook");
    let response = ctx
        .authed_body("DELETE", "/api/v1/tenant-webhooks/webhook-1", "")
        .await;
    assert_backend(&response, "rust", "DELETE tenant webhook");

    for (method, path, body) in [
        ("GET", "/api/v1/tenant-webhooks", ""),
        ("POST", "/api/v1/tenant-webhooks", "{}"),
        ("PUT", "/api/v1/tenant-webhooks", "{}"),
        ("DELETE", "/api/v1/tenant-webhooks", ""),
        ("GET", "/api/v1/tenant-webhooks/tenant-1/extra", ""),
        ("POST", "/api/v1/tenant-webhooks/tenant-1/extra", "{}"),
        ("PUT", "/api/v1/tenant-webhooks/webhook-1/extra", "{}"),
        ("DELETE", "/api/v1/tenant-webhooks/webhook-1/extra", ""),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
