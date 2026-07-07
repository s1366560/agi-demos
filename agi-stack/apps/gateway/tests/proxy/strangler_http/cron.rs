use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_cron_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/projects/project-1/cron-jobs",
        "/api/v1/projects/project-1/cron-jobs/job-1",
        "/api/v1/projects/project-1/cron-jobs/job-1/runs",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
    }

    for (method, path) in [
        ("POST", "/api/v1/projects/project-1/cron-jobs"),
        ("PATCH", "/api/v1/projects/project-1/cron-jobs/job-1"),
        ("DELETE", "/api/v1/projects/project-1/cron-jobs/job-1"),
        ("POST", "/api/v1/projects/project-1/cron-jobs/job-1/toggle"),
        ("POST", "/api/v1/projects/project-1/cron-jobs/job-1/run"),
        (
            "GET",
            "/api/v1/projects/project-1/cron-jobs/job-1/runs/extra",
        ),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
