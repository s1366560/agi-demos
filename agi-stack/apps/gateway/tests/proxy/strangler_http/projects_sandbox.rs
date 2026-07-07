use super::*;

pub(super) async fn assert_project_and_sandbox_routing(ctx: &StranglerHttpContext) {
    assert_project_routes(ctx).await;
    assert_sandbox_routes(ctx).await;
}

async fn assert_project_routes(ctx: &StranglerHttpContext) {
    let body = ctx.authed_body("GET", "/api/v1/projects", "").await;
    assert_backend(&body, "rust", "project list GET -> rust");

    let body = ctx.authed_body("GET", "/api/v1/projects/p1", "").await;
    assert_backend(&body, "rust", "project detail GET -> rust");

    let body = ctx
        .authed_body("GET", "/api/v1/projects/p1/stats", "")
        .await;
    assert_backend(&body, "rust", "project stats GET -> rust");

    let body = ctx
        .authed_body("GET", "/api/v1/projects/p1/members", "")
        .await;
    assert_backend(&body, "rust", "project members GET -> rust");

    for (method, path, body_in) in [
        ("POST", "/api/v1/projects/p1/members", "{'user_id':'u1'}"),
        (
            "PATCH",
            "/api/v1/projects/p1/members/u1",
            "{'role':'viewer'}",
        ),
        ("DELETE", "/api/v1/projects/p1/members/u1", ""),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "rust",
            &format!("project member write {method} {path} -> rust"),
        );
    }

    let body = ctx
        .authed_body("GET", "/api/v1/projects/p1/members/u1", "")
        .await;
    assert_backend(&body, "python", "project member child remains python");

    let body = ctx
        .authed_body(
            "POST",
            "/api/v1/projects/sandboxes/members",
            "{'user_id':'u1'}",
        )
        .await;
    assert_backend(
        &body,
        "python",
        "project sandboxes members POST remains python",
    );

    let body = ctx
        .authed_body(
            "POST",
            "/api/v1/projects",
            "{'name':'Acme','tenant_id':'t1'}",
        )
        .await;
    assert_backend(&body, "rust", "project POST -> rust");

    let body = ctx
        .authed_body("PUT", "/api/v1/projects/p1", "{'name':'Acme 2'}")
        .await;
    assert_backend(&body, "rust", "project PUT -> rust");

    let body = ctx.authed_body("DELETE", "/api/v1/projects/p1", "").await;
    assert_backend(&body, "rust", "project DELETE -> rust");
}

async fn assert_sandbox_routes(ctx: &StranglerHttpContext) {
    // P5 sandbox HTTP control plane flips to Rust without taking unrelated
    // rollback or data-plane siblings.
    for (method, path, body_in) in [
        ("GET", "/api/v1/sandbox/profiles", ""),
        ("GET", "/api/v1/projects/sandboxes", ""),
        ("GET", "/api/v1/projects/p1/sandbox", ""),
        ("POST", "/api/v1/projects/p1/sandbox", "{}"),
        ("DELETE", "/api/v1/projects/p1/sandbox", ""),
        ("GET", "/api/v1/projects/p1/sandbox/health", ""),
        ("GET", "/api/v1/projects/p1/sandbox/stats", ""),
        ("GET", "/api/v1/projects/p1/sandbox/sync", ""),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/execute",
            "{'tool':'list'}",
        ),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/proxy-auth-cookie",
            "{}",
        ),
        ("POST", "/api/v1/projects/p1/sandbox/restart", "{}"),
        ("POST", "/api/v1/projects/p1/sandbox/desktop", "{}"),
        ("DELETE", "/api/v1/projects/p1/sandbox/desktop", ""),
        ("POST", "/api/v1/projects/p1/sandbox/terminal", "{}"),
        ("DELETE", "/api/v1/projects/p1/sandbox/terminal", ""),
        ("GET", "/api/v1/projects/p1/sandbox/http-services", ""),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/http-services",
            "{'service_id':'web'}",
        ),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
            "{}",
        ),
        (
            "DELETE",
            "/api/v1/projects/p1/sandbox/http-services/web",
            "",
        ),
        ("GET", "/api/v1/projects/p1/sandbox/desktop/proxy", ""),
        (
            "GET",
            "/api/v1/projects/p1/sandbox/desktop/proxy/app.js",
            "",
        ),
        (
            "GET",
            "/api/v1/projects/p1/sandbox/http-services/web/proxy",
            "",
        ),
        (
            "POST",
            "/api/v1/projects/p1/sandbox/http-services/web/proxy",
            "{}",
        ),
        (
            "DELETE",
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/docs",
            "",
        ),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "rust",
            &format!("P5 sandbox control-plane {method} {path} -> rust"),
        );
    }

    for (method, path, body_in) in [
        ("POST", "/api/v1/sandbox/profiles", "{}"),
        ("GET", "/api/v1/sandbox/profiles/extra", ""),
        ("GET", "/api/v1/sandbox", ""),
        ("POST", "/api/v1/sandbox/create", "{}"),
        ("POST", "/api/v1/projects/sandboxes", "{}"),
        ("GET", "/api/v1/projects/sandboxes/stats", ""),
        ("GET", "/api/v1/projects/sandboxes/members", ""),
        (
            "POST",
            "/api/v1/projects/sandboxes/members",
            "{'user_id':'u1'}",
        ),
        ("PUT", "/api/v1/projects/p1/sandbox", "{}"),
        ("GET", "/api/v1/projects/p1/sandbox/restart", ""),
        (
            "GET",
            "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
            "",
        ),
        (
            "GET",
            "/api/v1/projects/sandboxes/sandbox/http-services/web/proxy",
            "",
        ),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("P5 rollback/data-plane boundary {method} {path} remains python"),
        );
    }
}
