use super::{declared, parameter, resource, FeatureOperationOwnerV2, PROJECT, TENANT_PROJECT};

pub(super) fn owner(method: &str, route: &str) -> Option<FeatureOperationOwnerV2> {
    let owner = match (method, route) {
        ("GET", "/api/v1/memories" | "/api/v1/memories/") => {
            declared(&["project-memories"]).query(PROJECT).aggregate()
        }
        ("POST", "/api/v1/memories" | "/api/v1/memories/") => {
            declared(&["project-memories"]).body(PROJECT).aggregate()
        }
        ("GET" | "DELETE", "/api/v1/memories/:id") => declared(&["project-memories"])
            .path(const { &[parameter("id", "memory_id")] })
            .resources(const { &[resource("memory", "memory_id")] })
            .aggregate(),
        (
            "POST",
            "/api/v1/search-enhanced/advanced"
            | "/api/v1/search-enhanced/graph-traversal"
            | "/api/v1/search-enhanced/temporal"
            | "/api/v1/search-enhanced/faceted"
            | "/api/v1/memory/search",
        ) => declared(&["project-search"])
            .body(TENANT_PROJECT)
            .aggregate(),
        ("POST", "/api/v1/search-enhanced/community") => {
            declared(&["project-search"]).body(PROJECT).aggregate()
        }
        ("GET", "/api/v1/search-enhanced/capabilities") => {
            declared(&["project-search"]).aggregate()
        }
        ("GET", "/api/v1/graph/memory/graph") => {
            declared(&["project-graph"]).query(PROJECT).aggregate()
        }
        ("POST", "/api/v1/graph/memory/graph/subgraph") => declared(&["project-graph"])
            .body(TENANT_PROJECT)
            .aggregate(),
        (
            "GET",
            "/api/v1/graph/entities/" | "/api/v1/graph/entities" | "/api/v1/graph/entities/types",
        ) => declared(&["project-entities"]).query(PROJECT).aggregate(),
        ("GET", "/api/v1/graph/entities/:uuid" | "/api/v1/graph/entities/:uuid/relationships") => {
            declared(&["project-entities"])
                .query(PROJECT)
                .path(const { &[parameter("uuid", "entity_id")] })
                .resources(const { &[resource("graph_entity", "entity_id")] })
                .aggregate()
        }
        ("GET", "/api/v1/graph/communities/" | "/api/v1/graph/communities")
        | ("POST", "/api/v1/graph/communities/rebuild") => declared(&["project-communities"])
            .query(PROJECT)
            .aggregate(),
        ("GET", "/api/v1/graph/communities/:uuid" | "/api/v1/graph/communities/:uuid/members") => {
            declared(&["project-communities"])
                .query(PROJECT)
                .path(const { &[parameter("uuid", "community_id")] })
                .resources(const { &[resource("graph_community", "community_id")] })
                .aggregate()
        }
        (
            "GET",
            "/api/v1/projects/:project_id/cron-jobs"
            | "/api/v1/projects/:project_id/cron-jobs/capabilities",
        ) => declared(&["project-cron-jobs"]).path(PROJECT),
        (
            "GET",
            "/api/v1/projects/:project_id/cron-jobs/:job_id"
            | "/api/v1/projects/:project_id/cron-jobs/:job_id/runs",
        ) => declared(&["project-cron-jobs"])
            .path(
                const {
                    &[
                        parameter("project_id", "project_id"),
                        parameter("job_id", "job_id"),
                    ]
                },
            )
            .resources(const { &[resource("cron", "job_id")] }),
        (
            "GET",
            "/api/v1/channels/projects/:project_id/configs"
            | "/api/v1/channels/projects/:project_id/observability/outbox"
            | "/api/v1/channels/projects/:project_id/observability/summary"
            | "/api/v1/channels/projects/:project_id/observability/session-bindings",
        ) => declared(&["project-channels"]).path(PROJECT),
        (
            "GET",
            "/api/v1/channels/configs/:config_id" | "/api/v1/channels/configs/:config_id/status",
        )
        | (
            "POST",
            "/api/v1/channels/configs/:config_id/connect"
            | "/api/v1/channels/configs/:config_id/disconnect"
            | "/api/v1/channels/configs/:config_id/health-check",
        ) => declared(&["project-channels"])
            .path(const { &[parameter("config_id", "config_id")] })
            .resources(const { &[resource("channel", "config_id")] }),
        (
            "GET" | "POST",
            "/api/v1/projects/:project_id/schema/entities"
            | "/api/v1/projects/:project_id/schema/edges"
            | "/api/v1/projects/:project_id/schema/mappings",
        )
        | (
            "PUT" | "DELETE",
            "/api/v1/projects/:project_id/schema/entities/:entity_id"
            | "/api/v1/projects/:project_id/schema/edges/:edge_id",
        )
        | ("DELETE", "/api/v1/projects/:project_id/schema/mappings/:map_id") => {
            declared(&["project-schema"]).path(PROJECT)
        }
        ("GET", "/api/v1/maintenance/status" | "/api/v1/maintenance/status/") => {
            declared(&["project-maintenance"])
                .query(PROJECT)
                .aggregate()
        }
        _ => return None,
    };
    Some(owner)
}
