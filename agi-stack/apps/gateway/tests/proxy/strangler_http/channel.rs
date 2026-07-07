use super::*;

pub(super) async fn assert_channel_routing(ctx: &StranglerHttpContext) {
    let body = ctx
        .public_body(
            "POST",
            "/api/v1/channels/configs/config-1/webhook/feishu",
            r#"{"type":"event_callback"}"#,
        )
        .await;
    assert_backend(
        &body,
        "rust",
        "P5 Feishu channel webhook ingress POST exact route -> rust",
    );

    for path in [
        "/api/v1/channels/configs/config-1/connect",
        "/api/v1/channels/configs/config-1/disconnect",
        "/api/v1/channels/configs/config-1/health-check",
    ] {
        let body = ctx.authed_body("POST", path, "{}").await;
        assert_backend(
            &body,
            "rust",
            &format!("P5 channel lifecycle exact route {path} -> rust"),
        );
    }

    for (method, path, body_in) in [
        (
            "GET",
            "/api/v1/channels/configs/config-1/webhook/feishu",
            "",
        ),
        (
            "POST",
            "/api/v1/channels/configs/config-1/webhook/slack",
            "{}",
        ),
        (
            "POST",
            "/api/v1/channels/configs/config-1/webhook/feishu/extra",
            "{}",
        ),
        ("POST", "/api/v1/channels/configs/config-1/test", "{}"),
        ("GET", "/api/v1/channels/configs/config-1/connect", ""),
        (
            "POST",
            "/api/v1/channels/configs/config-1/connect/extra",
            "{}",
        ),
        ("GET", "/api/v1/channels/configs/config-1/disconnect", ""),
        (
            "POST",
            "/api/v1/channels/configs/config-1/disconnect/extra",
            "{}",
        ),
        ("GET", "/api/v1/channels/configs/config-1/health-check", ""),
        (
            "POST",
            "/api/v1/channels/configs/config-1/health-check/extra",
            "{}",
        ),
    ] {
        let body = ctx.public_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("P5 channel webhook rollback boundary {method} {path} remains python"),
        );
    }
}
