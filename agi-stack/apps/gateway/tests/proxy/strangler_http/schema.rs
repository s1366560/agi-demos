use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_schema_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/projects/project-1/schema/entities",
        "/api/v1/projects/project-1/schema/edges",
        "/api/v1/projects/project-1/schema/mappings",
    ] {
        let response = ctx.authed_body("GET", path, "").await;
        assert_backend(&response, "rust", path);
    }

    for (method, path, body) in [
        (
            "POST",
            "/api/v1/projects/project-1/schema/entities",
            r#"{"name":"Person"}"#,
        ),
        (
            "PUT",
            "/api/v1/projects/project-1/schema/entities/entity-1",
            r#"{"description":"Updated"}"#,
        ),
        (
            "DELETE",
            "/api/v1/projects/project-1/schema/entities/entity-1",
            "",
        ),
        (
            "POST",
            "/api/v1/projects/project-1/schema/edges",
            r#"{"name":"WORKS_AT"}"#,
        ),
        (
            "PUT",
            "/api/v1/projects/project-1/schema/edges/edge-1",
            r#"{"description":"Updated"}"#,
        ),
        (
            "DELETE",
            "/api/v1/projects/project-1/schema/edges/edge-1",
            "",
        ),
        (
            "POST",
            "/api/v1/projects/project-1/schema/mappings",
            r#"{"source_type":"Person","target_type":"Company","edge_type":"WORKS_AT"}"#,
        ),
        (
            "DELETE",
            "/api/v1/projects/project-1/schema/mappings/map-1",
            "",
        ),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "rust", path);
    }

    for (method, path, body) in [
        (
            "GET",
            "/api/v1/projects/project-1/schema/entities/entity-1",
            "",
        ),
        (
            "PUT",
            "/api/v1/projects/project-1/schema/mappings/map-1",
            "{}",
        ),
        (
            "POST",
            "/api/v1/projects/project-1/schema/entities/entity-1",
            "{}",
        ),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
