use super::*;

pub(super) async fn assert_subagent_routing(ctx: &StranglerHttpContext) {
    let body = ctx
        .authed_body("GET", "/api/v1/subagents/templates/categories", "")
        .await;
    assert_backend(
        &body,
        "rust",
        "subagent template categories should route to rust",
    );

    for (method, path, body_in) in [
        ("POST", "/api/v1/subagents/templates/categories", "{}"),
        ("GET", "/api/v1/subagents/templates/categories/extra", ""),
        ("GET", "/api/v1/subagents/templates/list", ""),
        ("GET", "/api/v1/subagents/templates/template-1", ""),
        ("POST", "/api/v1/subagents/templates/", "{}"),
        (
            "POST",
            "/api/v1/subagents/templates/template-1/install",
            "{}",
        ),
        ("GET", "/api/v1/subagents", ""),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("subagent template rollback boundary {method} {path} remains python"),
        );
    }
}
