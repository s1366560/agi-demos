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
        "/api/v1/auth/me",
        "/api/v1/auth/tokens", // not a segment boundary of `/auth/token`
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
}

#[test]
fn p5_sandbox_http_control_plane_rules_are_exact() {
    for (method, path) in [
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
        (Method::POST, "/api/v1/graph/import"),
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
        (Method::POST, "/api/v1/skills/evolution/run"),
        (Method::POST, "/api/v1/skills/skill-1/content"),
        (Method::PUT, "/api/v1/skills/skill-1/status"),
        (Method::POST, "/api/v1/skills/skill-1/versions"),
        (Method::GET, "/api/v1/skills/skill-1/versions/2/extra"),
        (Method::GET, "/api/v1/skills/skill-1/rollback"),
        (Method::POST, "/api/v1/skills/skill-1/export"),
        (Method::POST, "/api/v1/skills/skill-1/evolution"),
        (Method::GET, "/api/v1/skills/skill-1/evolution/run"),
        (Method::POST, "/api/v1/skills/skill-1/evolution/run"),
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
            "/api/v1/channels/projects/project-1/observability/session-bindings",
        ),
        (Method::GET, "/api/v1/channels/configs/config-1"),
        (Method::GET, "/api/v1/channels/configs/config-1/status"),
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
            Method::GET,
            "/api/v1/channels/projects/project-1/observability/summary",
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
