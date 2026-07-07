use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_graph_store_routing(ctx: &StranglerHttpContext) {
    let body = ctx
        .authed_body("GET", "/api/v1/graph-stores/types", "")
        .await;
    assert_backend(&body, "rust", "graph-store types should route to rust");

    for path in [
        "/api/v1/graph-stores",
        "/api/v1/graph-stores/",
        "/api/v1/graph-stores/store-1",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
    }

    for (method, path) in [
        ("POST", "/api/v1/graph-stores"),
        ("POST", "/api/v1/graph-stores/"),
        ("PUT", "/api/v1/graph-stores/store-1"),
        ("DELETE", "/api/v1/graph-stores/store-1"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "rust", path);
    }

    for (method, path) in [
        ("POST", "/api/v1/graph-stores/types"),
        ("POST", "/api/v1/graph-stores/test"),
        ("GET", "/api/v1/graph-stores/test"),
        ("PUT", "/api/v1/graph-stores/test"),
        ("DELETE", "/api/v1/graph-stores/test"),
        ("POST", "/api/v1/graph-stores/store-1/test"),
        ("GET", "/api/v1/graph-stores/types/extra"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
