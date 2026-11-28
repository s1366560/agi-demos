use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_billing_routing(ctx: &StranglerHttpContext) {
    for (method, path, body) in [
        ("GET", "/api/v1/tenants/tenant-1/billing", ""),
        ("GET", "/api/v1/tenants/tenant-1/invoices", ""),
        ("POST", "/api/v1/tenants/tenant-1/upgrade", "{}"),
        ("POST", "/api/v1/tenants/tenant-1/billing", "{}"),
        ("POST", "/api/v1/tenants/tenant-1/invoices", "{}"),
        ("GET", "/api/v1/tenants/tenant-1/invoices/invoice-1", ""),
        ("GET", "/api/v1/tenants/tenant-1/upgrade", ""),
        ("POST", "/api/v1/tenants/tenant-1/upgrade/extra", "{}"),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
