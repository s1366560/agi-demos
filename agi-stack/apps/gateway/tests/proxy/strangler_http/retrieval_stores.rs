use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_retrieval_store_routing(ctx: &StranglerHttpContext) {
    let body = ctx
        .authed_body("GET", "/api/v1/retrieval-stores/types", "")
        .await;
    assert_backend(&body, "rust", "retrieval-store types should route to rust");

    for path in [
        "/api/v1/retrieval-stores",
        "/api/v1/retrieval-stores/",
        "/api/v1/retrieval-stores/store-1",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
    }

    for (method, path) in [
        ("POST", "/api/v1/retrieval-stores"),
        ("POST", "/api/v1/retrieval-stores/"),
        ("PUT", "/api/v1/retrieval-stores/store-1"),
        ("DELETE", "/api/v1/retrieval-stores/store-1"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "rust", path);
    }

    for (method, path) in [
        ("POST", "/api/v1/retrieval-stores/types"),
        ("POST", "/api/v1/retrieval-stores/test"),
        ("GET", "/api/v1/retrieval-stores/test"),
        ("PUT", "/api/v1/retrieval-stores/test"),
        ("DELETE", "/api/v1/retrieval-stores/test"),
        ("POST", "/api/v1/retrieval-stores/store-1/test"),
        ("GET", "/api/v1/retrieval-stores/types/extra"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
