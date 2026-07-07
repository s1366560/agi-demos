use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_data_routing(ctx: &StranglerHttpContext) {
    let body = ctx
        .authed_body("GET", "/api/v1/data/stats?tenant_id=tenant-1", "")
        .await;
    assert_backend(&body, "rust", "P7 data stats GET routes to rust");
    let body = ctx.authed_body("POST", "/api/v1/data/export", "{}").await;
    assert_backend(&body, "rust", "P7 data export POST routes to rust");
    let body = ctx.authed_body("POST", "/api/v1/data/cleanup", "{}").await;
    assert_backend(&body, "rust", "P7 data cleanup POST routes to rust");

    for (method, path, body_in) in [
        ("POST", "/api/v1/data/stats", "{}"),
        ("GET", "/api/v1/data/export", ""),
        ("POST", "/api/v1/data/export/extra", "{}"),
        ("GET", "/api/v1/data/cleanup", ""),
        ("POST", "/api/v1/data/cleanup/extra", "{}"),
        ("GET", "/api/v1/data/stats/extra", ""),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("P7 data rollback boundary {method} {path} remains python"),
        );
    }
}
