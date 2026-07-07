use super::*;

pub(super) async fn assert_graph_routing(ctx: &StranglerHttpContext) {
    for (method, path, body_in) in [
        ("GET", "/api/v1/graph/export?project_id=p1", ""),
        (
            "GET",
            "/api/v1/graph/communities/rebuild/jobs/job-1?project_id=p1",
            "",
        ),
        ("GET", "/api/v1/search-enhanced/capabilities", ""),
        ("POST", "/api/v1/graph/import", "{}"),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "rust",
            &format!("P4 graph snapshot {method} {path} -> rust"),
        );
    }

    for (method, path, body_in) in [
        ("POST", "/api/v1/graph/export", "{}"),
        ("GET", "/api/v1/graph/import", ""),
        ("GET", "/api/v1/graph/export/extra", ""),
        ("POST", "/api/v1/graph/import/extra", "{}"),
        ("POST", "/api/v1/search-enhanced/capabilities", "{}"),
        ("POST", "/api/v1/graph/communities/rebuild/jobs/job-1", "{}"),
        (
            "GET",
            "/api/v1/graph/communities/rebuild/jobs/job-1/events",
            "",
        ),
        ("POST", "/api/v1/graph/migrations", "{}"),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("P4 graph snapshot rollback boundary {method} {path} remains python"),
        );
    }
}
