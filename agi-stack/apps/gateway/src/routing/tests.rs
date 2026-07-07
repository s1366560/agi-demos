use super::*;
use axum::http::{HeaderMap, HeaderName, Method};

fn ups() -> Upstreams {
    Upstreams {
        rust: "http://rust:8088".into(),
        python: "http://python:8000".into(),
    }
}

#[test]
fn strangled_prefixes_route_to_rust() {
    let get = Method::GET;
    assert!(is_strangled("/api/v1/memories"));
    assert!(is_strangled("/api/v1/memories/"));
    assert!(is_strangled("/api/v1/memories/abc123"));
    assert!(is_strangled("/api/v1/episodes/"));
    assert!(is_strangled("/api/v1/recall/short"));
    // P2 login vertical.
    assert!(is_strangled("/api/v1/auth/token"));
    assert!(is_strangled("/api/v1/auth/oauth/google/callback"));
    assert!(is_strangled_request(&get, "/api/v1/tenants"));
    assert!(is_strangled_request(&get, "/api/v1/tenants/"));
    assert!(is_strangled_request(&get, "/api/v1/tenants/acme"));
    assert!(is_strangled_request(&Method::POST, "/api/v1/tenants"));
    assert!(is_strangled_request(&Method::PUT, "/api/v1/tenants/acme"));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/tenants/acme"
    ));
    assert!(is_strangled_request(&get, "/api/v1/projects"));
    assert!(is_strangled_request(&Method::POST, "/api/v1/projects"));
    assert!(is_strangled_request(&get, "/api/v1/projects/p1"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/projects/p1/schema/entities"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/projects/p1/schema/edges"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/projects/p1/schema/mappings"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/projects/p1/schema/entities"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/projects/p1/schema/entities/e1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/projects/p1/schema/entities/e1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/projects/p1/schema/edges"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/projects/p1/schema/edges/e1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/projects/p1/schema/edges/e1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/projects/p1/schema/mappings"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/projects/p1/schema/mappings/m1"
    ));
    assert!(is_strangled_request(&get, "/api/v1/projects/p1/cron-jobs"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/projects/p1/cron-jobs/job-1"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/projects/p1/cron-jobs/job-1/runs"
    ));
    assert!(is_strangled_request(&Method::PUT, "/api/v1/projects/p1"));
    assert!(is_strangled_request(&Method::DELETE, "/api/v1/projects/p1"));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/tenants/acme/members"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/tenants/acme/members/u1"
    ));
    assert!(is_strangled_request(
        &Method::PATCH,
        "/api/v1/tenants/acme/members/u1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/tenants/acme/members/u1"
    ));
    assert!(is_strangled_request(&get, "/api/v1/agent/ws"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/agent/conversations/c1/events"
    ));
    assert!(is_strangled_request(&get, "/api/v1/events/types"));
    assert!(is_strangled_request(&get, "/api/v1/events"));
    assert!(is_strangled_request(&get, "/api/v1/data/stats"));
    assert!(is_strangled_request(&get, "/api/v1/maintenance/status"));
    assert!(is_strangled_request(&Method::POST, "/api/v1/data/export"));
    assert!(is_strangled_request(&Method::POST, "/api/v1/data/cleanup"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/tenants/acme/audit-logs"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/tenants/acme/audit-logs/filter"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/tenants/acme/audit-logs/export"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/tenants/acme/audit-logs/runtime-hooks"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/tenants/acme/audit-logs/runtime-hooks/summary"
    ));
    assert!(is_strangled_request(&get, "/api/v1/notifications/"));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/notifications/n1/read"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/notifications/read-all"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/notifications/n1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/notifications/create"
    ));
    assert!(is_strangled_request(&get, "/api/v1/llm-providers"));
    assert!(is_strangled_request(&get, "/api/v1/llm-providers/"));
    assert!(is_strangled_request(&Method::POST, "/api/v1/llm-providers"));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/llm-providers/"
    ));
    assert!(is_strangled_request(&get, "/api/v1/llm-providers/types"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/env-detection"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/models/catalog"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/models/catalog/search"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/models/anthropic"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/tenants/tenant-1/assignments"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/usage"
    ));
    assert!(is_strangled_request(&get, "/api/v1/deploys/"));
    assert!(is_strangled_request(&get, "/api/v1/deploys/deploy-1"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/deploys/instances/inst-1/latest"
    ));
    assert!(is_strangled_request(&get, "/api/v1/instances/"));
    assert!(is_strangled_request(&get, "/api/v1/instances/inst-1"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/instances/inst-1/config"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/instances/inst-1/config"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/instances/inst-1/config/pending"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/instances/inst-1/llm-config"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/instances/inst-1/llm-config"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/instances/inst-1/members"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/instances/inst-1/members"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/instances/inst-1/members/search-users"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/instances/inst-1/members/member-1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/instances/inst-1/members/user-1"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/instances/inst-1/channels"
    ));
    assert!(is_strangled_request(&get, "/api/v1/genes/"));
    assert!(is_strangled_request(&get, "/api/v1/genes/gene-1"));
    assert!(is_strangled_request(&get, "/api/v1/genes/genomes"));
    assert!(is_strangled_request(&get, "/api/v1/genes/genomes/genome-1"));
    assert!(is_strangled_request(&get, "/api/v1/tenants/acme/billing"));
    assert!(is_strangled_request(&get, "/api/v1/tenants/acme/invoices"));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/tenants/acme/upgrade"
    ));
    assert!(is_strangled_request(&get, "/api/v1/support/tickets"));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/support/tickets"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/support/tickets/ticket-1"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/support/tickets/ticket-1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/support/tickets/ticket-1/close"
    ));
    assert!(is_strangled_request(&get, "/support/tickets"));
    assert!(is_strangled_request(&Method::POST, "/support/tickets"));
    assert!(is_strangled_request(&get, "/support/tickets/ticket-1"));
    assert!(is_strangled_request(
        &Method::PUT,
        "/support/tickets/ticket-1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/support/tickets/ticket-1/close"
    ));
    assert!(is_strangled_request(&get, "/api/v1/artifacts"));
    assert!(is_strangled_request(&get, "/api/v1/artifacts/"));
    assert!(is_strangled_request(&get, "/api/v1/artifacts/artifact-1"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/artifacts/categories/list"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/artifacts/artifact-1/content"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/artifacts/artifact-1"
    ));
    assert!(is_strangled_request(&get, "/api/v1/attachments"));
    assert!(is_strangled_request(&get, "/api/v1/attachments/"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/attachments/attachment-1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/attachments/attachment-1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/attachments/upload/simple"
    ));
    assert!(is_strangled_request(&get, "/api/v1/engines"));
    assert!(is_strangled_request(&get, "/api/v1/system/features"));
    assert!(is_strangled_request(&get, "/api/v1/system/info"));
    assert!(is_strangled_request(&get, "/api/v1/auth/me"));
    assert!(is_strangled_request(&get, "/api/v1/users/me"));
    assert!(is_strangled_request(&get, "/api/v1/graph-stores/types"));
    assert!(is_strangled_request(&get, "/api/v1/graph-stores"));
    assert!(is_strangled_request(&get, "/api/v1/graph-stores/"));
    assert!(is_strangled_request(&Method::POST, "/api/v1/graph-stores"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/graph-stores/graph-store-1"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/graph-stores/graph-store-1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/graph-stores/graph-store-1"
    ));
    assert!(is_strangled_request(&get, "/api/v1/retrieval-stores/types"));
    assert!(is_strangled_request(&get, "/api/v1/retrieval-stores"));
    assert!(is_strangled_request(&get, "/api/v1/retrieval-stores/"));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/retrieval-stores"
    ));
    assert!(is_strangled_request(
        &get,
        "/api/v1/retrieval-stores/retrieval-store-1"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/retrieval-stores/retrieval-store-1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/retrieval-stores/retrieval-store-1"
    ));
    assert!(is_strangled_request(&get, "/api/v1/admin/dlq/messages"));
    assert!(is_strangled_request(&get, "/api/v1/admin/dlq/messages/"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/admin/dlq/messages/dlq-1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/admin/dlq/messages/dlq-1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/admin/dlq/messages/dlq-1/retry"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/admin/dlq/messages/retry"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/admin/dlq/messages/discard"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/admin/dlq/cleanup/expired"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/admin/dlq/cleanup/resolved"
    ));
    assert!(is_strangled_request(&get, "/api/v1/admin/dlq/stats"));
    assert!(is_strangled_request(&get, "/api/v1/admin/dlq/stats/"));
    assert!(is_strangled_request(
        &get,
        "/api/v1/tenant-webhooks/tenant-1"
    ));
    assert!(is_strangled_request(
        &Method::POST,
        "/api/v1/tenant-webhooks/tenant-1"
    ));
    assert!(is_strangled_request(
        &Method::PUT,
        "/api/v1/tenant-webhooks/webhook-1"
    ));
    assert!(is_strangled_request(
        &Method::DELETE,
        "/api/v1/tenant-webhooks/webhook-1"
    ));
    assert!(is_strangled_request(&get, "/api/v1/shared/share_token"));
    for p in [
        "/api/v1/memories",
        "/api/v1/episodes/",
        "/api/v1/recall/short",
        "/api/v1/auth/token",
        "/api/v1/auth/oauth/github/callback",
    ] {
        assert_eq!(upstream_for(p, &ups()), "http://rust:8088");
    }
    for p in [
        "/api/v1/tenants",
        "/api/v1/tenants/",
        "/api/v1/tenants/acme",
        "/api/v1/shared/share_token",
    ] {
        assert_eq!(upstream_for_request(&get, p, &ups()), "http://rust:8088");
    }
}

#[test]
fn everything_else_routes_to_python() {
    let get = Method::GET;
    let post = Method::POST;
    for p in [
        "/api/v1/projects",
        // Other `/auth/*` siblings remain in Python (surgical strangling).
        "/api/v1/auth/force-change-password",
        "/api/v1/auth/keys",
        "/api/v1/auth/tokens", // not a segment boundary of `/auth/token`
        "/api/v1/users",
        // Tenant reads are method-scoped; sibling routes stay in Python.
        "/api/v1/tenants/t1/members",
        "/api/v1/tenants/t1/stats",
        "/api/v1/agent/sessions",
        "/api/v1/memories_admin", // not a segment boundary -> not strangled
        "/health",
        "/",
    ] {
        assert!(!is_strangled(p), "{p} should not be strangled");
        assert_eq!(upstream_for(p, &ups()), "http://python:8000");
    }
    assert_eq!(
        upstream_for_request(&get, "/api/v1/tenants/t1/members", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenants/t1/stats", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/agent/ws", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/agent/conversations/c1/events", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/agent/conversations/c1/messages", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/events/types", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/events", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/events/filter", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/events/types/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/data/stats", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/data/export", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/data/export/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/data/cleanup", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/data/cleanup/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenants/acme/audit-logs", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenants/acme/audit-logs/export", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/tenants/acme/audit-logs/export/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &get,
            "/api/v1/tenants/acme/audit-logs/runtime-hooks/summary/extra",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/notifications", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/notifications/", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/notifications/n1/read", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::POST, "/api/v1/notifications/n1/read", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/notifications/read-all", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/notifications/create", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/notifications/n1/archive", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/llm-providers", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/llm-providers/", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/llm-providers", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/llm-providers/", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(
            &get,
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555",
            &ups()
        ),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(
            &Method::PUT,
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555",
            &ups()
        ),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555",
            &ups()
        ),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/llm-providers/types", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/llm-providers/env-detection", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/llm-providers/env-detection/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/llm-providers/types/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/llm-providers/models/catalog", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/llm-providers/models/catalog/search", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/llm-providers/models/catalog/refresh", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/llm-providers/models/anthropic/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &get,
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health-check",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health-check",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/llm-providers/tenants/tenant-1/assignments",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &get,
            "/api/v1/llm-providers/tenants/tenant-1/provider",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/llm-providers/tenants/tenant-1/providers/provider-1",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/llm-providers/tenants/tenant-1/providers/provider-1",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/usage",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/llm-providers/system/status", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/llm-providers/system/reset-circuit-breaker/openai",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/deploys", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/deploys/", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/deploys/deploy-1/success", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/deploys/deploy-1/failed", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/deploys/deploy-1/cancel", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/deploys/deploy-1/progress", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/deploys/instances/inst-1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/instances", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/instances/", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/instances/inst-1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/instances/inst-1/config/pending", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/instances/inst-1/config/apply", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/instances/inst-1/config", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/instances/inst-1/llm-config", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::POST,
            "/api/v1/instances/inst-1/members/search-users",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/instances/inst-1/members", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/instances/inst-1/members", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/instances/inst-1/files", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/instances/inst-1/channels", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::PUT,
            "/api/v1/instances/inst-1/channels/channel-1",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/instances/inst-1/channels/channel-1/test",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/genes", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/genes/", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/genes/gene-1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/genes/evolution", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/genes/instances/inst-1/genes", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/genes/gene-1/ratings", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/genes/gene-1/reviews", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/genes/genomes", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/genes/genomes/genome-1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/genes/genomes/genome-1/publish", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/genes/genomes/genome-1/ratings", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenants/acme/billing", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenants/acme/invoices", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/tenants/acme/invoices/i1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/tenants/acme/upgrade", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenants/acme/upgrade/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/support/tickets/ticket-1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/support/tickets/ticket-1/reopen", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/support/tickets/ticket-1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/support/tickets/ticket-1/reopen", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/support/tickets/ticket-1/close", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/artifacts", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/artifacts/artifact-1/download", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/artifacts/categories/list", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/artifacts/categories/list/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/artifacts/artifact-1/refresh-url", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/artifacts/artifact-1/content", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::PUT,
            "/api/v1/artifacts/artifact-1/content/extra",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/artifacts/categories/content", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/artifacts/artifact-1/content",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/artifacts/categories", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/attachments/upload/simple", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/attachments/upload/simple", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/attachments/upload/simple/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/attachments/upload", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/attachments/attachment-1/download", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/attachments/attachment-1", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/attachments/upload", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/attachments/attachment-1/download",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/graph-stores/types", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/graph-stores", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/graph-stores", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/graph-stores/graph-store-1", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/graph-stores/test", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/graph-stores/test", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/graph-stores/graph-store-1", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/graph-stores/graph-store-1",
            &ups()
        ),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/graph-stores/graph-store-1/test", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/graph-stores/types/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/retrieval-stores/types", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/retrieval-stores", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/retrieval-stores", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/retrieval-stores/retrieval-store-1", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/retrieval-stores/test", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/retrieval-stores/test", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::PUT,
            "/api/v1/retrieval-stores/retrieval-store-1",
            &ups()
        ),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/retrieval-stores/retrieval-store-1",
            &ups()
        ),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(
            &post,
            "/api/v1/retrieval-stores/retrieval-store-1/test",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/retrieval-stores/types/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/admin/dlq/messages/retry", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/admin/dlq/cleanup/expired", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/tenant-webhooks", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenant-webhooks", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/tenant-webhooks", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/tenant-webhooks", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/tenant-webhooks/tenant-1/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/tenant-webhooks/tenant-1/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::PUT,
            "/api/v1/tenant-webhooks/webhook-1/extra",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/tenant-webhooks/webhook-1/extra",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::DELETE, "/api/v1/projects/sandboxes", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&Method::PUT, "/api/v1/projects/sandboxes", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/shared/share_token/extra", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/shared/share_token", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&get, "/api/v1/projects/p1/schema/entities/e1", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::PUT,
            "/api/v1/projects/p1/schema/mappings/m1",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::POST,
            "/api/v1/projects/p1/schema/entities/e1",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/projects/p1/cron-jobs", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::PATCH,
            "/api/v1/projects/p1/cron-jobs/job-1",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &Method::DELETE,
            "/api/v1/projects/p1/cron-jobs/job-1",
            &ups()
        ),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/projects/p1/cron-jobs/job-1/toggle", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(&post, "/api/v1/projects/p1/cron-jobs/job-1/run", &ups()),
        "http://python:8000"
    );
    assert_eq!(
        upstream_for_request(
            &get,
            "/api/v1/projects/p1/cron-jobs/job-1/runs/extra",
            &ups()
        ),
        "http://python:8000"
    );
}

#[test]
fn p7_runtime_engine_catalog_rule_is_exact() {
    assert_eq!(
        upstream_for_request(&Method::GET, "/api/v1/engines", &ups()),
        "http://rust:8088"
    );
    assert_eq!(
        upstream_for_request(&Method::GET, "/api/v1/engines/", &ups()),
        "http://rust:8088"
    );

    for (method, path) in [
        (Method::POST, "/api/v1/engines"),
        (Method::GET, "/api/v1/engines/python-3.12"),
        (Method::POST, "/api/v1/sandbox/create"),
        (Method::GET, "/api/v1/sandbox/list"),
        (Method::GET, "/api/v1/sandbox/sandbox-1"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p7_system_metadata_rules_are_exact() {
    for path in ["/api/v1/system/features", "/api/v1/system/info"] {
        assert_eq!(
            upstream_for_request(&Method::GET, path, &ups()),
            "http://rust:8088",
            "GET {path} should route to rust",
        );
        assert_eq!(
            upstream_for_request(&Method::GET, &format!("{path}/"), &ups()),
            "http://rust:8088",
            "GET {path}/ should route to rust",
        );
    }

    for (method, path) in [
        (Method::POST, "/api/v1/system/features"),
        (Method::POST, "/api/v1/system/info"),
        (Method::GET, "/api/v1/system"),
        (Method::GET, "/api/v1/system/status"),
        (Method::GET, "/api/v1/system/features/extra"),
        (Method::GET, "/api/v1/system/info/extra"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p7_maintenance_status_rules_are_exact() {
    for path in ["/api/v1/maintenance/status", "/api/v1/maintenance/status/"] {
        assert_eq!(
            upstream_for_request(&Method::GET, path, &ups()),
            "http://rust:8088",
            "GET {path} should route to rust",
        );
    }

    for (method, path) in [
        (Method::POST, "/api/v1/maintenance/status"),
        (Method::GET, "/api/v1/maintenance"),
        (Method::GET, "/api/v1/maintenance/status/extra"),
        (Method::POST, "/api/v1/maintenance/refresh/incremental"),
        (Method::POST, "/api/v1/maintenance/optimize"),
        (Method::POST, "/api/v1/maintenance/invalidate/stale-edges"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p2_current_user_rules_are_exact() {
    for path in ["/api/v1/auth/me", "/api/v1/users/me"] {
        assert_eq!(
            upstream_for_request(&Method::GET, path, &ups()),
            "http://rust:8088",
            "GET {path} should route to rust",
        );
        assert_eq!(
            upstream_for_request(&Method::GET, &format!("{path}/"), &ups()),
            "http://rust:8088",
            "GET {path}/ should route to rust",
        );
    }

    for (method, path) in [
        (Method::POST, "/api/v1/auth/me"),
        (Method::PUT, "/api/v1/users/me"),
        (Method::GET, "/api/v1/auth/keys"),
        (Method::GET, "/api/v1/auth/me/extra"),
        (Method::GET, "/api/v1/users/me/extra"),
        (Method::GET, "/api/v1/users"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p5_sandbox_http_control_plane_rules_are_exact() {
    for (method, path) in [
        (Method::GET, "/api/v1/sandbox/profiles"),
        (Method::GET, "/api/v1/projects/sandboxes"),
        (Method::GET, "/api/v1/projects/p1/sandbox"),
        (Method::POST, "/api/v1/projects/p1/sandbox"),
        (Method::DELETE, "/api/v1/projects/p1/sandbox"),
        (Method::GET, "/api/v1/projects/p1/sandbox/health"),
        (Method::GET, "/api/v1/projects/p1/sandbox/stats"),
        (Method::GET, "/api/v1/projects/p1/sandbox/sync"),
        (Method::POST, "/api/v1/projects/p1/sandbox/execute"),
        (
            Method::POST,
            "/api/v1/projects/p1/sandbox/proxy-auth-cookie",
        ),
        (Method::POST, "/api/v1/projects/p1/sandbox/restart"),
        (Method::POST, "/api/v1/projects/p1/sandbox/desktop"),
        (Method::DELETE, "/api/v1/projects/p1/sandbox/desktop"),
        (Method::POST, "/api/v1/projects/p1/sandbox/terminal"),
        (Method::DELETE, "/api/v1/projects/p1/sandbox/terminal"),
        (Method::GET, "/api/v1/projects/p1/sandbox/http-services"),
        (Method::POST, "/api/v1/projects/p1/sandbox/http-services"),
        (
            Method::POST,
            "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
        ),
        (
            Method::DELETE,
            "/api/v1/projects/p1/sandbox/http-services/web",
        ),
        (Method::GET, "/api/v1/projects/p1/sandbox/desktop/proxy"),
        (
            Method::GET,
            "/api/v1/projects/p1/sandbox/desktop/proxy/app.js",
        ),
        (
            Method::GET,
            "/api/v1/projects/p1/sandbox/desktop/proxy/websockify",
        ),
        (
            Method::GET,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy",
        ),
        (
            Method::POST,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy",
        ),
        (
            Method::PUT,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
        ),
        (
            Method::PATCH,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
        ),
        (
            Method::DELETE,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
        ),
        (
            Method::OPTIONS,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/api/data",
        ),
        (
            Method::GET,
            "/api/v1/projects/p1/sandbox/http-services/web/proxy/ws/socket",
        ),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://rust:8088",
            "{method} {path} should route to rust",
        );
    }

    for (method, path) in [
        (Method::POST, "/api/v1/sandbox/profiles"),
        (Method::GET, "/api/v1/sandbox/profiles/extra"),
        (Method::GET, "/api/v1/sandbox"),
        (Method::POST, "/api/v1/sandbox/create"),
        (Method::POST, "/api/v1/projects/sandboxes"),
        (Method::GET, "/api/v1/projects/sandboxes/stats"),
        (Method::GET, "/api/v1/projects/sandboxes/members"),
        (Method::POST, "/api/v1/projects/sandboxes/members"),
        (Method::PUT, "/api/v1/projects/p1/sandbox"),
        (Method::GET, "/api/v1/projects/p1/sandbox/restart"),
        (
            Method::GET,
            "/api/v1/projects/p1/sandbox/http-services/web/preview-session",
        ),
        (
            Method::GET,
            "/api/v1/projects/sandboxes/sandbox/http-services/web/proxy",
        ),
        (Method::GET, "/api/v1/projects/p1/sandbox/terminal/proxy/ws"),
        (Method::GET, "/api/v1/projects/p1/sandbox/mcp/proxy"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p4_graph_search_rules_are_exact() {
    for (method, path) in [
        (Method::GET, "/api/v1/graph/communities"),
        (Method::GET, "/api/v1/graph/communities/"),
        (Method::POST, "/api/v1/graph/communities/rebuild"),
        (Method::GET, "/api/v1/graph/communities/rebuild/jobs/job-1"),
        (Method::GET, "/api/v1/graph/communities/community-1"),
        (Method::GET, "/api/v1/graph/communities/community-1/members"),
        (Method::GET, "/api/v1/graph/entities"),
        (Method::GET, "/api/v1/graph/entities/"),
        (Method::POST, "/api/v1/graph/entities"),
        (Method::POST, "/api/v1/graph/entities/"),
        (Method::GET, "/api/v1/graph/entities/types"),
        (Method::GET, "/api/v1/graph/entities/entity-1"),
        (Method::GET, "/api/v1/graph/entities/entity-1/relationships"),
        (Method::POST, "/api/v1/graph/relationships"),
        (Method::POST, "/api/v1/graph/relationships/"),
        (Method::GET, "/api/v1/graph/export"),
        (Method::POST, "/api/v1/graph/import"),
        (Method::GET, "/api/v1/graph/memory/graph"),
        (Method::POST, "/api/v1/graph/memory/graph/subgraph"),
        (Method::POST, "/api/v1/search-enhanced/advanced"),
        (Method::POST, "/api/v1/search-enhanced/graph-traversal"),
        (Method::POST, "/api/v1/search-enhanced/community"),
        (Method::POST, "/api/v1/search-enhanced/temporal"),
        (Method::POST, "/api/v1/search-enhanced/faceted"),
        (Method::GET, "/api/v1/search-enhanced/capabilities"),
        (Method::POST, "/api/v1/memory/search"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://rust:8088",
            "{method} {path} should route to rust",
        );
    }

    for (method, path) in [
        (Method::POST, "/api/v1/graph/communities"),
        (Method::GET, "/api/v1/graph/communities/rebuild"),
        (Method::POST, "/api/v1/graph/communities/rebuild/jobs/job-1"),
        (
            Method::GET,
            "/api/v1/graph/communities/rebuild/jobs/job-1/events",
        ),
        (
            Method::POST,
            "/api/v1/graph/communities/community-1/members",
        ),
        (Method::GET, "/api/v1/graph/communities/community-1/extra"),
        (Method::DELETE, "/api/v1/graph/entities"),
        (Method::POST, "/api/v1/graph/entities/types"),
        (Method::GET, "/api/v1/graph/entities/types/extra"),
        (Method::POST, "/api/v1/graph/entities/entity-1"),
        (
            Method::POST,
            "/api/v1/graph/entities/entity-1/relationships",
        ),
        (Method::GET, "/api/v1/graph/relationships"),
        (Method::POST, "/api/v1/graph/relationships/rel-1"),
        (Method::POST, "/api/v1/graph/memory/graph"),
        (Method::GET, "/api/v1/graph/memory/graph/subgraph"),
        (Method::POST, "/api/v1/graph/export"),
        (Method::GET, "/api/v1/graph/import"),
        (Method::GET, "/api/v1/graph/export/extra"),
        (Method::POST, "/api/v1/graph/import/extra"),
        (Method::GET, "/api/v1/search-enhanced/advanced"),
        (Method::POST, "/api/v1/search-enhanced/capabilities"),
        (Method::GET, "/api/v1/memory/search"),
        (Method::POST, "/api/v1/memory/search/extra"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p5_skill_store_rules_are_exact() {
    for (method, path) in [
        (Method::GET, "/api/v1/skills"),
        (Method::GET, "/api/v1/skills/"),
        (Method::POST, "/api/v1/skills"),
        (Method::POST, "/api/v1/skills/"),
        (Method::GET, "/api/v1/skills/system/list"),
        (Method::POST, "/api/v1/skills/system/import"),
        (Method::POST, "/api/v1/skills/import"),
        (Method::POST, "/api/v1/skills/import/zip"),
        (Method::GET, "/api/v1/skills/evolution/config"),
        (Method::PUT, "/api/v1/skills/evolution/config"),
        (Method::GET, "/api/v1/skills/evolution/overview"),
        (Method::POST, "/api/v1/skills/evolution/run"),
        (Method::POST, "/api/v1/skills/evolution/jobs/job-1/apply"),
        (Method::POST, "/api/v1/skills/evolution/jobs/job-1/reject"),
        (Method::GET, "/api/v1/skills/skill-1"),
        (Method::PUT, "/api/v1/skills/skill-1"),
        (Method::DELETE, "/api/v1/skills/skill-1"),
        (Method::GET, "/api/v1/skills/skill-1/content"),
        (Method::PUT, "/api/v1/skills/skill-1/content"),
        (Method::PATCH, "/api/v1/skills/skill-1/status"),
        (Method::GET, "/api/v1/skills/skill-1/versions"),
        (Method::GET, "/api/v1/skills/skill-1/versions/2"),
        (Method::POST, "/api/v1/skills/skill-1/rollback"),
        (Method::GET, "/api/v1/skills/skill-1/export"),
        (Method::GET, "/api/v1/skills/skill-1/evolution"),
        (Method::POST, "/api/v1/skills/skill-1/evolution/run"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://rust:8088",
            "{method} {path} should route to rust",
        );
    }

    for (method, path) in [
        (Method::PATCH, "/api/v1/skills"),
        (Method::DELETE, "/api/v1/skills"),
        (Method::POST, "/api/v1/skills/system/list"),
        (Method::GET, "/api/v1/skills/system"),
        (Method::GET, "/api/v1/skills/system/import"),
        (Method::POST, "/api/v1/skills/system/import/extra"),
        (Method::GET, "/api/v1/skills/system/list/extra"),
        (Method::GET, "/api/v1/skills/import/zip"),
        (Method::POST, "/api/v1/skills/import/zip/extra"),
        (Method::POST, "/api/v1/skills/evolution/config"),
        (Method::GET, "/api/v1/skills/evolution/config/extra"),
        (Method::POST, "/api/v1/skills/evolution/overview"),
        (Method::GET, "/api/v1/skills/evolution/overview/extra"),
        (Method::GET, "/api/v1/skills/evolution/jobs/job-1/apply"),
        (
            Method::POST,
            "/api/v1/skills/evolution/jobs/job-1/apply/extra",
        ),
        (Method::POST, "/api/v1/skills/evolution/jobs/job-1/cancel"),
        (Method::POST, "/api/v1/skills/skill-1/content"),
        (Method::PUT, "/api/v1/skills/skill-1/status"),
        (Method::POST, "/api/v1/skills/skill-1/versions"),
        (Method::GET, "/api/v1/skills/skill-1/versions/2/extra"),
        (Method::GET, "/api/v1/skills/skill-1/rollback"),
        (Method::POST, "/api/v1/skills/skill-1/export"),
        (Method::POST, "/api/v1/skills/skill-1/evolution"),
        (Method::GET, "/api/v1/skills/skill-1/evolution/run"),
        (Method::POST, "/api/v1/skills/skill-1/evolution/run/extra"),
        (Method::POST, "/api/v1/skills/skill-1/publish"),
        (Method::POST, "/api/v1/skills/skill-1/clone"),
        (Method::GET, "/api/v1/skills/skill-1/files"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p5_channel_config_rules_are_exact() {
    for (method, path) in [
        (Method::GET, "/api/v1/channels/projects/project-1/configs"),
        (
            Method::GET,
            "/api/v1/channels/projects/project-1/observability/outbox",
        ),
        (
            Method::GET,
            "/api/v1/channels/projects/project-1/observability/summary",
        ),
        (
            Method::GET,
            "/api/v1/channels/projects/project-1/observability/session-bindings",
        ),
        (Method::GET, "/api/v1/channels/configs/config-1"),
        (Method::GET, "/api/v1/channels/configs/config-1/status"),
        (Method::POST, "/api/v1/channels/configs/config-1/connect"),
        (Method::POST, "/api/v1/channels/configs/config-1/disconnect"),
        (
            Method::POST,
            "/api/v1/channels/configs/config-1/health-check",
        ),
        (
            Method::POST,
            "/api/v1/channels/configs/config-1/webhook/feishu",
        ),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://rust:8088",
            "{method} {path} should route to rust",
        );
    }

    for (method, path) in [
        (Method::POST, "/api/v1/channels/projects/project-1/configs"),
        (Method::GET, "/api/v1/channels/projects/project-1/plugins"),
        (
            Method::POST,
            "/api/v1/channels/projects/project-1/observability/summary",
        ),
        (
            Method::GET,
            "/api/v1/channels/projects/project-1/observability/summary/extra",
        ),
        (
            Method::POST,
            "/api/v1/channels/projects/project-1/observability/outbox",
        ),
        (
            Method::GET,
            "/api/v1/channels/projects/project-1/observability/outbox/extra",
        ),
        (Method::PUT, "/api/v1/channels/configs/config-1"),
        (Method::DELETE, "/api/v1/channels/configs/config-1"),
        (Method::POST, "/api/v1/channels/configs/config-1/test"),
        (Method::POST, "/api/v1/channels/configs/config-1/status"),
        (Method::GET, "/api/v1/channels/configs/config-1/connect"),
        (
            Method::POST,
            "/api/v1/channels/configs/config-1/connect/extra",
        ),
        (Method::GET, "/api/v1/channels/configs/config-1/disconnect"),
        (
            Method::POST,
            "/api/v1/channels/configs/config-1/disconnect/extra",
        ),
        (
            Method::GET,
            "/api/v1/channels/configs/config-1/health-check",
        ),
        (
            Method::POST,
            "/api/v1/channels/configs/config-1/health-check/extra",
        ),
        (
            Method::GET,
            "/api/v1/channels/configs/config-1/webhook/feishu",
        ),
        (
            Method::POST,
            "/api/v1/channels/configs/config-1/webhook/slack",
        ),
        (
            Method::POST,
            "/api/v1/channels/configs/config-1/webhook/feishu/extra",
        ),
        (Method::GET, "/api/v1/channels/status"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p5_tenant_skill_config_rules_are_exact() {
    for (method, path) in [
        (Method::GET, "/api/v1/tenant/skills/config"),
        (Method::GET, "/api/v1/tenant/skills/config/"),
        (Method::GET, "/api/v1/tenant/skills/config/code-review"),
        (Method::GET, "/api/v1/tenant/skills/config/status"),
        (
            Method::GET,
            "/api/v1/tenant/skills/config/status/code-review",
        ),
        (Method::POST, "/api/v1/tenant/skills/config/disable"),
        (Method::POST, "/api/v1/tenant/skills/config/override"),
        (Method::POST, "/api/v1/tenant/skills/config/enable"),
        (Method::DELETE, "/api/v1/tenant/skills/config/code-review"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://rust:8088",
            "{method} {path} should route to rust",
        );
    }

    for (method, path) in [
        (Method::POST, "/api/v1/tenant/skills/config"),
        (Method::PUT, "/api/v1/tenant/skills/config"),
        (Method::PATCH, "/api/v1/tenant/skills/config"),
        (Method::GET, "/api/v1/tenant/skills"),
        (
            Method::GET,
            "/api/v1/tenant/skills/config/status/code-review/extra",
        ),
        (
            Method::POST,
            "/api/v1/tenant/skills/config/status/code-review",
        ),
        (Method::POST, "/api/v1/tenant/skills/config/code-review"),
        (Method::PUT, "/api/v1/tenant/skills/config/code-review"),
        (Method::DELETE, "/api/v1/tenant/skills/config"),
        (
            Method::GET,
            "/api/v1/tenant/skills/config/code-review/content",
        ),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p3_subagent_template_category_rule_is_exact() {
    assert_eq!(
        upstream_for_request(
            &Method::GET,
            "/api/v1/subagents/templates/categories",
            &ups()
        ),
        "http://rust:8088"
    );

    for (method, path) in [
        (Method::POST, "/api/v1/subagents/templates/categories"),
        (Method::GET, "/api/v1/subagents/templates/categories/extra"),
        (Method::GET, "/api/v1/subagents/templates/list"),
        (Method::GET, "/api/v1/subagents/templates/template-1"),
        (Method::POST, "/api/v1/subagents/templates/"),
        (
            Method::POST,
            "/api/v1/subagents/templates/template-1/install",
        ),
        (Method::GET, "/api/v1/subagents"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p3_agent_command_catalog_rule_is_exact() {
    assert_eq!(
        upstream_for_request(&Method::GET, "/api/v1/agent/commands", &ups()),
        "http://rust:8088"
    );

    for (method, path) in [
        (Method::POST, "/api/v1/agent/commands"),
        (Method::GET, "/api/v1/agent/commands/extra"),
        (Method::GET, "/api/v1/agent/tools"),
        (Method::GET, "/api/v1/agent/tools/capabilities"),
        (Method::GET, "/api/v1/agent/workflows/patterns"),
        (Method::GET, "/api/v1/agent/conversations/c1/messages"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn p6_workspace_autonomy_tick_rule_is_exact() {
    assert_eq!(
        upstream_for_request(
            &Method::POST,
            "/api/v1/workspaces/ws-1/autonomy/tick",
            &ups()
        ),
        "http://rust:8088"
    );

    for (method, path) in [
        (Method::GET, "/api/v1/workspaces/ws-1/autonomy/tick"),
        (Method::POST, "/api/v1/workspaces/ws-1/autonomy"),
        (Method::POST, "/api/v1/workspaces/ws-1/autonomy/tick/extra"),
        (Method::POST, "/api/v1/workspaces/ws-1/plan"),
        (Method::POST, "/api/v1/workspaces/ws-1/runtime/tick"),
    ] {
        assert_eq!(
            upstream_for_request(&method, path, &ups()),
            "http://python:8000",
            "{method} {path} should remain on python",
        );
    }
}

#[test]
fn preview_hosts_are_host_scoped_and_route_to_rust() {
    assert!(is_preview_host_for_suffix(
        "web.p1.preview.localhost:8000",
        "preview.localhost"
    ));
    assert!(is_preview_host_for_suffix(
        "WEB.P1.PREVIEW.LOCALHOST",
        "preview.localhost"
    ));
    assert!(is_preview_host_for_suffix(
        "https://web.p1.preview.example.test",
        "preview.example.test"
    ));

    for host in [
        "",
        "preview.localhost:8000",
        "web.preview.localhost:8000",
        "web.p1.other.localhost:8000",
        "deep.web.p1.preview.localhost:8000",
        "web.p1.preview.localhost.evil.test",
    ] {
        assert!(
            !is_preview_host_for_suffix(host, "preview.localhost"),
            "{host} should not match preview host shape",
        );
    }

    let mut headers = HeaderMap::new();
    headers.insert(
        HeaderName::from_static("host"),
        axum::http::HeaderValue::from_static("web.p1.preview.localhost:8000"),
    );
    assert_eq!(
        upstream_for_request_with_headers(&Method::GET, "/docs", &headers, &ups()),
        "http://rust:8088"
    );

    headers.insert(
        HeaderName::from_static("host"),
        axum::http::HeaderValue::from_static("web.p1.other.localhost:8000"),
    );
    assert_eq!(
        upstream_for_request_with_headers(&Method::GET, "/docs", &headers, &ups()),
        "http://python:8000"
    );
}
