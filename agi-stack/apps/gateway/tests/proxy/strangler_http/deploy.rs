use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_deploy_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/deploys/",
        "/api/v1/deploys/deploy-1",
        "/api/v1/deploys/instances/inst-1/latest",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
    }

    for (method, path) in [
        ("GET", "/api/v1/deploys"),
        ("POST", "/api/v1/deploys/"),
        ("POST", "/api/v1/deploys/deploy-1/success"),
        ("POST", "/api/v1/deploys/deploy-1/failed"),
        ("POST", "/api/v1/deploys/deploy-1/cancel"),
        ("GET", "/api/v1/deploys/deploy-1/progress"),
        ("GET", "/api/v1/deploys/instances/inst-1"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
