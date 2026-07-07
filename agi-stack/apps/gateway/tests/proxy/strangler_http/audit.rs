use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_audit_routing(ctx: &StranglerHttpContext) {
    for (method, path, body) in [
        ("GET", "/api/v1/tenants/tenant-1/audit-logs", ""),
        ("GET", "/api/v1/tenants/tenant-1/audit-logs?limit=10", ""),
        ("GET", "/api/v1/tenants/tenant-1/audit-logs/filter", ""),
        ("GET", "/api/v1/tenants/tenant-1/audit-logs/export", ""),
        (
            "GET",
            "/api/v1/tenants/tenant-1/audit-logs/runtime-hooks",
            "",
        ),
        (
            "GET",
            "/api/v1/tenants/tenant-1/audit-logs/runtime-hooks/summary",
            "",
        ),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "rust", path);
    }

    for (method, path, body) in [
        ("POST", "/api/v1/tenants/tenant-1/audit-logs/export", "{}"),
        (
            "GET",
            "/api/v1/tenants/tenant-1/audit-logs/export/extra",
            "",
        ),
        (
            "GET",
            "/api/v1/tenants/tenant-1/audit-logs/runtime-hooks/summary/extra",
            "",
        ),
        ("POST", "/api/v1/tenants/tenant-1/audit-logs", "{}"),
        ("POST", "/api/v1/tenants/tenant-1/audit-logs/filter", "{}"),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
