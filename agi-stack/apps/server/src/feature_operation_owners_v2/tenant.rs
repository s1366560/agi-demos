use super::{
    declared, parameter, resource, FeatureOperationOwnerV2, PayloadFieldOwnerV2, ScopeParameterV2,
    PROJECT, TENANT,
};

pub(super) fn owner(method: &str, route: &str) -> Option<FeatureOperationOwnerV2> {
    let owner = match (method, route) {
        ("GET" | "POST", "/api/v1/llm-providers" | "/api/v1/llm-providers/")
        | (
            "GET",
            "/api/v1/llm-providers/types"
            | "/api/v1/llm-providers/models/catalog"
            | "/api/v1/llm-providers/models/catalog/search"
            | "/api/v1/llm-providers/models/:provider_type"
            | "/api/v1/llm-providers/env-detection"
            | "/api/v1/llm-providers/:provider_id/health"
            | "/api/v1/llm-providers/:provider_id/usage",
        )
        | (
            "POST",
            "/api/v1/llm-providers/test-connection"
            | "/api/v1/llm-providers/:provider_id/health-check",
        )
        | ("GET" | "PUT" | "DELETE", "/api/v1/llm-providers/:provider_id") => {
            declared(&["tenant-providers"])
        }
        ("GET", "/api/v1/llm-providers/tenants/:tenant_id/assignments") => {
            declared(&["tenant-providers"]).path(TENANT)
        }
        (
            "GET",
            "/api/v1/tenants/:tenant_id/audit-logs"
            | "/api/v1/tenants/:tenant_id/audit-logs/filter"
            | "/api/v1/tenants/:tenant_id/audit-logs/runtime-hooks"
            | "/api/v1/tenants/:tenant_id/audit-logs/runtime-hooks/summary"
            | "/api/v1/tenants/:tenant_id/audit-logs/export",
        ) => declared(&["tenant-audit-logs"]).path(TENANT),
        ("GET", "/api/v1/tenants/:tenant_id/billing" | "/api/v1/tenants/:tenant_id/invoices")
        | ("POST", "/api/v1/tenants/:tenant_id/upgrade") => {
            declared(&["tenant-billing"]).path(TENANT)
        }
        ("GET", "/api/v1/instances/") => declared(&["tenant-instances"]),
        (
            "GET",
            "/api/v1/instances/:instance_id"
            | "/api/v1/instances/:instance_id/config"
            | "/api/v1/instances/:instance_id/llm-config"
            | "/api/v1/instances/:instance_id/members"
            | "/api/v1/instances/:instance_id/members/search-users"
            | "/api/v1/instances/:instance_id/channels",
        )
        | (
            "PUT",
            "/api/v1/instances/:instance_id/config"
            | "/api/v1/instances/:instance_id/config/pending"
            | "/api/v1/instances/:instance_id/llm-config"
            | "/api/v1/instances/:instance_id/members/:member_id",
        )
        | ("DELETE", "/api/v1/instances/:instance_id/members/:member_id") => {
            declared(&["tenant-instances"])
                .path(const { &[parameter("instance_id", "instance_id")] })
                .resources(const { &[resource("instance", "instance_id")] })
        }
        ("POST", "/api/v1/instances/:instance_id/members") => declared(&["tenant-instances"])
            .path(const { &[parameter("instance_id", "instance_id")] })
            .body(const { &[parameter("instance_id", "instance_id")] })
            .resources(const { &[resource("instance", "instance_id")] }),
        ("GET", "/api/v1/deploys/") => declared(&["tenant-deploy"])
            .query(const { &[parameter("instance_id", "instance_id")] })
            .resources(const { &[resource("instance", "instance_id")] }),
        ("GET", "/api/v1/deploys/instances/:instance_id/latest") => declared(&["tenant-deploy"])
            .path(const { &[parameter("instance_id", "instance_id")] })
            .resources(const { &[resource("instance", "instance_id")] }),
        ("GET", "/api/v1/deploys/:deploy_id") => declared(&["tenant-deploy"])
            .path(const { &[parameter("deploy_id", "deploy_id")] })
            .resources(const { &[resource("deploy", "deploy_id")] }),
        ("GET", "/api/v1/events" | "/api/v1/events/types") => {
            declared(&["tenant-events"]).query(TENANT)
        }
        (
            "GET",
            "/api/v1/genes/"
            | "/api/v1/genes/genomes"
            | "/api/v1/genes/genomes/:genome_id"
            | "/api/v1/genes/:gene_id",
        ) => declared(&["tenant-genes"]).query(TENANT),
        ("GET", "/api/v1/subagents/templates/categories") => declared(&["tenant-agents"]),
        ("GET", "/api/v1/graph-stores/types" | "/api/v1/retrieval-stores/types") => {
            declared(&["tenant-backend-stores"])
        }
        (
            "GET" | "POST",
            "/api/v1/graph-stores"
            | "/api/v1/graph-stores/"
            | "/api/v1/retrieval-stores"
            | "/api/v1/retrieval-stores/",
        )
        | (
            "GET" | "PUT" | "DELETE",
            "/api/v1/graph-stores/:store_id" | "/api/v1/retrieval-stores/:store_id",
        ) => declared(&["tenant-backend-stores"]).query(TENANT),
        ("GET" | "POST", "/api/v1/tenant-webhooks/:id") => {
            declared(&["tenant-webhooks"]).path(const { &[parameter("id", "tenant_id")] })
        }
        ("PUT" | "DELETE", "/api/v1/tenant-webhooks/:id") => declared(&["tenant-webhooks"])
            .path(const { &[parameter("id", "webhook_id")] })
            .resources(const { &[resource("webhook", "webhook_id")] }),
        (
            "GET",
            "/api/v1/admin/dlq/messages"
            | "/api/v1/admin/dlq/messages/"
            | "/api/v1/admin/dlq/messages/:message_id"
            | "/api/v1/admin/dlq/stats"
            | "/api/v1/admin/dlq/stats/",
        )
        | (
            "POST",
            "/api/v1/admin/dlq/messages/retry"
            | "/api/v1/admin/dlq/messages/discard"
            | "/api/v1/admin/dlq/messages/:message_id/retry"
            | "/api/v1/admin/dlq/cleanup/expired"
            | "/api/v1/admin/dlq/cleanup/resolved",
        )
        | ("DELETE", "/api/v1/admin/dlq/messages/:message_id") => {
            declared(&["tenant-dead-letter-queue"])
        }
        ("GET", "/api/v1/support/tickets" | "/support/tickets") => FeatureOperationOwnerV2 {
            support_tenant_aggregate: true,
            ..declared(&["project-support"]).query(
                const {
                    &[
                        parameter("tenant_id", "tenant_id"),
                        ScopeParameterV2 {
                            field: "status",
                            parameter: "support_status",
                            empty_is_absent: true,
                        },
                    ]
                },
            )
        },
        ("POST", "/api/v1/support/tickets" | "/support/tickets") => {
            declared(&["project-support"]).body(TENANT)
        }
        ("GET" | "PUT", "/api/v1/support/tickets/:ticket_id" | "/support/tickets/:ticket_id")
        | (
            "POST",
            "/api/v1/support/tickets/:ticket_id/close" | "/support/tickets/:ticket_id/close",
        ) => declared(&["project-support"])
            .path(const { &[parameter("ticket_id", "ticket_id")] })
            .resources(const { &[resource("support_ticket", "ticket_id")] }),
        ("GET" | "POST", "/api/v1/tenants/:tenant_id/trust/policies")
        | ("GET", "/api/v1/tenants/:tenant_id/trust/policies/check")
        | ("POST", "/api/v1/tenants/:tenant_id/trust/approval-requests") => {
            declared(&["tenant-trust-policies"]).path(TENANT)
        }
        (
            "GET",
            "/api/v1/tenants/:tenant_id/trust/decision-records"
            | "/api/v1/tenants/:tenant_id/trust/decision-records/:record_id",
        ) => declared(&["tenant-decision-records"]).path(TENANT),
        ("PUT" | "DELETE", "/api/v1/tenants/:id") => {
            declared(&["tenant-org-settings"]).path(const { &[parameter("id", "tenant_id")] })
        }
        ("POST", "/api/v1/tenants/:tenant_id/members")
        | ("POST" | "PATCH" | "DELETE", "/api/v1/tenants/:tenant_id/members/:user_id") => {
            declared(&["tenant-users"]).path(TENANT)
        }
        ("POST", "/api/v1/projects" | "/api/v1/projects/") => {
            declared(&["tenant-projects"]).body(TENANT)
        }
        ("DELETE", "/api/v1/projects/:id") => {
            declared(&["project-settings"]).path(const { &[parameter("id", "project_id")] })
        }
        ("PUT", "/api/v1/projects/:id") => FeatureOperationOwnerV2 {
            payload_field_owners: &[
                PayloadFieldOwnerV2 {
                    field: "memory_rules",
                    feature_id: "project-memories",
                },
                PayloadFieldOwnerV2 {
                    field: "graph_config",
                    feature_id: "project-graph",
                },
            ],
            ..declared(&["project-settings"]).path(const { &[parameter("id", "project_id")] })
        },
        ("GET" | "POST", "/api/v1/projects/:id/members")
        | ("PATCH" | "DELETE", "/api/v1/projects/:id/members/:user_id") => {
            declared(&["project-team"]).path(const { &[parameter("id", "project_id")] })
        }
        ("GET", "/api/v1/agent/commands") => declared(&["tenant-agent-workspace"]),
        ("POST", "/api/v1/agent/conversations") => {
            declared(&["tenant-agent-workspace"]).body(PROJECT)
        }
        ("PATCH", "/api/v1/agent/conversations/:conversation_id/mode") => {
            declared(&["tenant-agent-workspace"])
                .query(PROJECT)
                .path(const { &[parameter("conversation_id", "conversation_id")] })
                .resources(const { &[resource("conversation", "conversation_id")] })
        }
        _ => return None,
    };
    Some(owner)
}
