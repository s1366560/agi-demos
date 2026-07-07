use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_llm_provider_routing(ctx: &StranglerHttpContext) {
    let body = ctx.authed_body("GET", "/api/v1/llm-providers", "").await;
    assert_backend(&body, "rust", "llm provider list should route to rust");
    let body = ctx.authed_body("GET", "/api/v1/llm-providers/", "").await;
    assert_backend(
        &body,
        "rust",
        "llm provider list trailing slash should route to rust",
    );
    let body = ctx
        .authed_body(
            "POST",
            "/api/v1/llm-providers",
            r#"{"name":"test-openai","provider_type":"openai","api_key":"sk-test","llm_model":"gpt-4o"}"#,
        )
        .await;
    assert_backend(&body, "rust", "llm provider create should route to rust");
    let body = ctx
        .authed_body(
            "GET",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555",
            "",
        )
        .await;
    assert_backend(&body, "rust", "llm provider detail should route to rust");
    let body = ctx
        .authed_body(
            "PUT",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555",
            r#"{"name":"updated-openai"}"#,
        )
        .await;
    assert_backend(&body, "rust", "llm provider update should route to rust");
    let body = ctx
        .authed_body(
            "DELETE",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555",
            "",
        )
        .await;
    assert_backend(&body, "rust", "llm provider delete should route to rust");

    let body = ctx
        .authed_body("GET", "/api/v1/llm-providers/types", "")
        .await;
    assert_backend(&body, "rust", "llm provider types should route to rust");
    let body = ctx
        .authed_body("GET", "/api/v1/llm-providers/env-detection", "")
        .await;
    assert_backend(
        &body,
        "rust",
        "llm provider env detection should route to rust",
    );
    let body = ctx
        .authed_body("GET", "/api/v1/llm-providers/models/catalog", "")
        .await;
    assert_backend(&body, "rust", "llm model catalog should route to rust");
    let body = ctx
        .authed_body(
            "GET",
            "/api/v1/llm-providers/models/catalog/search?q=claude&limit=1",
            "",
        )
        .await;
    assert_backend(
        &body,
        "rust",
        "llm model catalog search should route to rust",
    );
    let body = ctx
        .authed_body("GET", "/api/v1/llm-providers/models/anthropic", "")
        .await;
    assert_backend(&body, "rust", "llm provider models should route to rust");
    let body = ctx
        .authed_body(
            "GET",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health",
            "",
        )
        .await;
    assert_backend(
        &body,
        "rust",
        "llm provider latest health should route to rust",
    );
    let body = ctx
        .authed_body(
            "GET",
            "/api/v1/llm-providers/tenants/tenant-1/assignments",
            "",
        )
        .await;
    assert_backend(
        &body,
        "rust",
        "llm provider tenant assignment list should route to rust",
    );
    let body = ctx
        .authed_body(
            "GET",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/usage",
            "",
        )
        .await;
    assert_backend(&body, "rust", "llm provider usage should route to rust");

    for (method, path) in [
        ("POST", "/api/v1/llm-providers/types"),
        ("POST", "/api/v1/llm-providers/env-detection"),
        ("GET", "/api/v1/llm-providers/env-detection/extra"),
        ("GET", "/api/v1/llm-providers/types/extra"),
        ("POST", "/api/v1/llm-providers/models/catalog"),
        ("POST", "/api/v1/llm-providers/models/catalog/search"),
        ("GET", "/api/v1/llm-providers/models/catalog/refresh"),
        ("GET", "/api/v1/llm-providers/models/anthropic/extra"),
        (
            "POST",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health",
        ),
        (
            "GET",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health-check",
        ),
        (
            "POST",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/health-check",
        ),
        ("POST", "/api/v1/llm-providers/tenants/tenant-1/assignments"),
        ("GET", "/api/v1/llm-providers/tenants/tenant-1/provider"),
        (
            "POST",
            "/api/v1/llm-providers/tenants/tenant-1/providers/provider-1",
        ),
        (
            "DELETE",
            "/api/v1/llm-providers/tenants/tenant-1/providers/provider-1",
        ),
        (
            "POST",
            "/api/v1/llm-providers/11111111-2222-4333-8444-555555555555/usage",
        ),
        ("GET", "/api/v1/llm-providers/system/status"),
        (
            "POST",
            "/api/v1/llm-providers/system/reset-circuit-breaker/openai",
        ),
    ] {
        let body = ctx.authed_body(method, path, "{}").await;
        assert_backend(&body, "python", path);
    }
}
