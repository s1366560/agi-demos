use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_billing_routing(ctx: &StranglerHttpContext) {
    let response = ctx
        .authed_body("GET", "/api/v1/tenants/tenant-1/billing", "")
        .await;
    assert_backend(&response, "rust", "GET tenant billing");

    let response = ctx
        .authed_body("GET", "/api/v1/tenants/tenant-1/invoices", "")
        .await;
    assert_backend(&response, "rust", "GET tenant invoices");

    let response = ctx
        .authed_body("POST", "/api/v1/tenants/tenant-1/upgrade", "{}")
        .await;
    assert_backend(&response, "rust", "POST tenant upgrade");

    for (method, path, body) in [
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
