use super::*;

pub(super) async fn assert_skill_evolution_routing(ctx: &StranglerHttpContext) {
    for (method, path, body_in) in [
        ("GET", "/api/v1/skills/evolution/config", ""),
        ("PUT", "/api/v1/skills/evolution/config", "{'enabled':true}"),
        ("GET", "/api/v1/skills/evolution/overview", ""),
        ("POST", "/api/v1/skills/evolution/run", "{}"),
        ("POST", "/api/v1/skills/evolution/jobs/job-1/apply", "{}"),
        ("POST", "/api/v1/skills/evolution/jobs/job-1/reject", "{}"),
        ("GET", "/api/v1/skills/skill-1/evolution", ""),
        ("POST", "/api/v1/skills/skill-1/evolution/run", "{}"),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "rust",
            &format!("P5 skill evolution {method} {path} -> rust"),
        );
    }

    for (method, path, body_in) in [
        ("POST", "/api/v1/skills/evolution/config", "{}"),
        ("GET", "/api/v1/skills/evolution/config/extra", ""),
        ("POST", "/api/v1/skills/evolution/overview", "{}"),
        ("GET", "/api/v1/skills/evolution/jobs/job-1/apply", ""),
        (
            "POST",
            "/api/v1/skills/evolution/jobs/job-1/apply/extra",
            "{}",
        ),
        ("POST", "/api/v1/skills/evolution/jobs/job-1/cancel", "{}"),
        ("POST", "/api/v1/skills/skill-1/evolution", "{}"),
        ("GET", "/api/v1/skills/skill-1/evolution/run", ""),
        ("POST", "/api/v1/skills/skill-1/evolution/run/extra", "{}"),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("P5 skill evolution rollback boundary {method} {path} remains python"),
        );
    }
}
