use super::{owner, parameter, resource, BodyScopeFormatV2, PROJECT, TENANT};

#[test]
fn builtin_surfaces_use_their_declared_feature_owner() {
    for (method, route, feature) in [
        ("GET", "/api/v1/llm-providers", "tenant-providers"),
        ("POST", "/api/v1/skills", "tenant-skills"),
        ("GET", "/api/v1/graph/memory/graph", "project-graph"),
        ("GET", "/api/v1/graph/entities", "project-entities"),
        (
            "POST",
            "/api/v1/graph/communities/rebuild",
            "project-communities",
        ),
        (
            "GET",
            "/api/v1/projects/:project_id/cron-jobs",
            "project-cron-jobs",
        ),
        (
            "GET",
            "/api/v1/channels/configs/:config_id",
            "project-channels",
        ),
        (
            "GET",
            "/api/v1/tenants/:tenant_id/audit-logs",
            "tenant-audit-logs",
        ),
        (
            "POST",
            "/api/v1/tenants/:tenant_id/upgrade",
            "tenant-billing",
        ),
        ("GET", "/api/v1/deploys/", "tenant-deploy"),
        ("GET", "/api/v1/instances/", "tenant-instances"),
        (
            "GET",
            "/api/v1/subagents/templates/categories",
            "tenant-agents",
        ),
    ] {
        assert_eq!(
            owner(method, route).expect("builtin owner").feature_ids,
            &[feature]
        );
    }
}

#[test]
fn lookup_requires_the_exact_method_and_matched_template() {
    for (method, route) in [
        ("GET", "/api/v1/skills-unknown"),
        ("GET", "/api/v1/skills/a"),
        ("GET", "/api/v1/skills/:skill_id/unknown"),
        ("DELETE", "/api/v1/skills"),
        ("POST", "/api/v1/projects/:project_id/cron-jobs"),
        ("get", "/api/v1/skills"),
    ] {
        assert!(owner(method, route).is_none(), "{method} {route}");
    }
    assert!(owner("GET", "/api/v1/skills/:skill_id").is_some());
    assert_eq!(
        owner("HEAD", "/api/v1/skills/:skill_id"),
        owner("GET", "/api/v1/skills/:skill_id")
    );
}

#[test]
fn scope_sources_match_the_actual_handler_arguments() {
    let memory = owner("GET", "/api/v1/memories/:id").expect("memory owner");
    assert_eq!(memory.path_parameters, &[parameter("id", "memory_id")]);
    assert_eq!(memory.resources, &[resource("memory", "memory_id")]);
    assert!(memory.query_parameters.is_empty());
    assert!(memory.body_parameters.is_empty());

    let create = owner("POST", "/api/v1/memories").expect("memory creation owner");
    assert_eq!(create.body_parameters, PROJECT);
    assert!(create.query_parameters.is_empty());

    let audit = owner("GET", "/api/v1/tenants/:tenant_id/audit-logs").expect("audit owner");
    assert_eq!(audit.path_parameters, TENANT);
    assert!(audit.query_parameters.is_empty());
    assert!(audit.body_parameters.is_empty());
}

#[test]
fn same_route_can_have_different_resource_ancestry_by_method() {
    let list = owner("GET", "/api/v1/tenant-webhooks/:id").expect("webhook list owner");
    assert_eq!(list.path_parameters, &[parameter("id", "tenant_id")]);
    assert!(list.resources.is_empty());

    let update = owner("PUT", "/api/v1/tenant-webhooks/:id").expect("webhook update owner");
    assert_eq!(update.path_parameters, &[parameter("id", "webhook_id")]);
    assert_eq!(update.resources, &[resource("webhook", "webhook_id")]);
}

#[test]
fn resource_only_routes_declare_persisted_scope_resolution() {
    for (method, route, kind, id) in [
        (
            "POST",
            "/api/v1/channels/configs/:config_id/connect",
            "channel",
            "config_id",
        ),
        ("GET", "/api/v1/deploys/:deploy_id", "deploy", "deploy_id"),
        (
            "PUT",
            "/api/v1/instances/:instance_id/config",
            "instance",
            "instance_id",
        ),
        (
            "POST",
            "/api/v1/skills/evolution/jobs/:job_id/apply",
            "skill_evolution",
            "job_id",
        ),
        (
            "GET",
            "/api/v1/support/tickets/:ticket_id",
            "support_ticket",
            "ticket_id",
        ),
    ] {
        let declared = owner(method, route).expect("resource owner");
        assert_eq!(
            declared.resources,
            &[resource(kind, id)],
            "{method} {route}"
        );
    }
}

#[test]
fn skill_import_declares_multipart_project_and_query_tenant_separately() {
    let zip = owner("POST", "/api/v1/skills/import/zip").expect("zip import owner");
    assert_eq!(zip.body_format, BodyScopeFormatV2::Multipart);
    assert_eq!(zip.body_parameters, PROJECT);
    assert_eq!(zip.query_parameters, TENANT);
    let json = owner("POST", "/api/v1/skills/import").expect("JSON import owner");
    assert_eq!(json.body_format, BodyScopeFormatV2::Json);
    assert_eq!(json.body_parameters, PROJECT);
}

#[test]
fn project_updates_declare_only_owned_payload_fields() {
    let update = owner("PUT", "/api/v1/projects/:id").expect("project update owner");
    assert_eq!(update.feature_ids, &["project-settings"]);
    assert_eq!(update.path_parameters, &[parameter("id", "project_id")]);
    let owners: Vec<_> = update
        .payload_field_owners
        .iter()
        .map(|field| (field.field, field.feature_id))
        .collect();
    assert_eq!(
        owners,
        vec![
            ("memory_rules", "project-memories"),
            ("graph_config", "project-graph")
        ]
    );
    assert!(update.query_parameters.is_empty());
    assert!(update.body_parameters.is_empty());
}

#[test]
fn bootstrap_and_running_execution_recovery_remain_available() {
    for (method, route) in [
        ("GET", "/health"),
        ("POST", "/api/v1/auth/token"),
        ("GET", "/api/v1/auth/me"),
        ("GET", "/api/v1/tenants"),
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/projects/:id"),
        ("GET", "/api/v1/workspace-context"),
        ("POST", "/api/v1/workspace-context/switch"),
        ("GET", "/api/v1/system/features"),
        ("POST", "/api/v1/agent/hitl/respond"),
        ("POST", "/v1/agent/resume"),
        ("GET", "/api/v1/agent/conversations"),
        ("GET", "/api/v1/agent/conversations/:conversation_id/messages"),
        ("GET", "/api/v1/agent/conversations/:conversation_id/session"),
        ("GET", "/api/v1/agent/conversations/:conversation_id/events"),
        ("GET", "/api/v1/agent/conversations/:conversation_id/messages/:message_id/model-requests/:attempt_id"),
        ("GET", "/api/v1/graph/communities/rebuild/jobs/:job_id"),
        ("POST", "/api/v1/tenants/:tenant_id/trust/approval-requests/:record_id/resolve"),
        ("POST", "/api/v1/channels/configs/:config_id/webhook/feishu"),
    ] {
        assert!(owner(method, route).is_none(), "{method} {route}");
    }
}

#[test]
fn new_agent_workspace_actions_are_owned() {
    for (method, route) in [
        ("GET", "/api/v1/agent/commands"),
        ("POST", "/api/v1/agent/conversations"),
        ("PATCH", "/api/v1/agent/conversations/:conversation_id/mode"),
    ] {
        let declared = owner(method, route).expect("agent workspace owner");
        assert_eq!(declared.feature_ids, &["tenant-agent-workspace"]);
    }
}
