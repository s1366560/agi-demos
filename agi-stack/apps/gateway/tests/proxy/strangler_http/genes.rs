use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_gene_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/genes/",
        "/api/v1/genes/gene-1",
        "/api/v1/genes/genomes",
        "/api/v1/genes/genomes/genome-1",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
        assert!(
            body.contains(ctx.bearer),
            "gene strangler request should preserve authorization: {body}"
        );
    }

    for (method, path) in [
        ("GET", "/api/v1/genes"),
        ("POST", "/api/v1/genes/"),
        ("PUT", "/api/v1/genes/gene-1"),
        ("GET", "/api/v1/genes/evolution"),
        ("GET", "/api/v1/genes/instances/inst-1/genes"),
        ("GET", "/api/v1/genes/gene-1/ratings"),
        ("GET", "/api/v1/genes/gene-1/reviews"),
        ("POST", "/api/v1/genes/genomes"),
        ("PUT", "/api/v1/genes/genomes/genome-1"),
        ("POST", "/api/v1/genes/genomes/genome-1/publish"),
        ("GET", "/api/v1/genes/genomes/genome-1/ratings"),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
