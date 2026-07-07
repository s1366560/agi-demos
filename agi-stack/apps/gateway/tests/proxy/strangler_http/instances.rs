use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_instance_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/instances/",
        "/api/v1/instances/inst-1",
        "/api/v1/instances/inst-1/config",
        "/api/v1/instances/inst-1/llm-config",
        "/api/v1/instances/inst-1/members",
        "/api/v1/instances/inst-1/members/search-users",
        "/api/v1/instances/inst-1/channels",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
    }
    for (method, path) in [
        ("PUT", "/api/v1/instances/inst-1/config"),
        ("PUT", "/api/v1/instances/inst-1/config/pending"),
        ("PUT", "/api/v1/instances/inst-1/llm-config"),
        ("POST", "/api/v1/instances/inst-1/members"),
        ("PUT", "/api/v1/instances/inst-1/members/member-1"),
        ("DELETE", "/api/v1/instances/inst-1/members/user-1"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "rust", path);
    }

    for (method, path) in [
        ("GET", "/api/v1/instances"),
        ("POST", "/api/v1/instances/"),
        ("PUT", "/api/v1/instances/inst-1"),
        ("DELETE", "/api/v1/instances/inst-1"),
        ("POST", "/api/v1/instances/inst-1/scale"),
        ("POST", "/api/v1/instances/inst-1/restart"),
        ("GET", "/api/v1/instances/inst-1/config/pending"),
        ("POST", "/api/v1/instances/inst-1/config/apply"),
        ("POST", "/api/v1/instances/inst-1/config"),
        ("POST", "/api/v1/instances/inst-1/llm-config"),
        ("POST", "/api/v1/instances/inst-1/members/search-users"),
        ("PUT", "/api/v1/instances/inst-1/members"),
        ("DELETE", "/api/v1/instances/inst-1/members"),
        ("GET", "/api/v1/instances/inst-1/files"),
        ("POST", "/api/v1/instances/inst-1/channels"),
        ("PUT", "/api/v1/instances/inst-1/channels/channel-1"),
        ("POST", "/api/v1/instances/inst-1/channels/channel-1/test"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
