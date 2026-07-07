use super::*;

pub(super) async fn assert_agent_command_routing(ctx: &StranglerHttpContext) {
    let body = ctx.authed_body("GET", "/api/v1/agent/commands", "").await;
    assert_backend(&body, "rust", "agent commands should route to rust");

    for (method, path, body_in) in [
        ("POST", "/api/v1/agent/commands", "{}"),
        ("GET", "/api/v1/agent/commands/extra", ""),
        ("GET", "/api/v1/agent/tools", ""),
        ("GET", "/api/v1/agent/tools/capabilities", ""),
        ("GET", "/api/v1/agent/workflows/patterns", ""),
        ("GET", "/api/v1/agent/conversations/c1/messages", ""),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("agent command rollback boundary {method} {path} remains python"),
        );
    }
}
