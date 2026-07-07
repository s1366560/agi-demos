use super::*;

pub(super) async fn assert_identity_and_shares_routing(ctx: &StranglerHttpContext) {
    assert_current_user_routes(ctx).await;
    assert_tenant_read_and_device_routes(ctx).await;
    assert_tenant_writes(ctx).await;
    assert_invitation_routes(ctx).await;
    assert_trust_routes(ctx).await;
    assert_public_share_routes(ctx).await;
}

async fn assert_current_user_routes(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/auth/me",
        "/api/v1/auth/me/",
        "/api/v1/users/me",
        "/api/v1/users/me/",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", &format!("current-user {path} GET -> rust"));
    }

    for (method, path, body_in) in [
        ("POST", "/api/v1/auth/me", "{}"),
        ("GET", "/api/v1/auth/keys", ""),
        ("PUT", "/api/v1/users/me", "{}"),
        ("GET", "/api/v1/auth/me/extra", ""),
        ("GET", "/api/v1/users/me/extra", ""),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "python",
            &format!("current-user rollback boundary {method} {path} remains python"),
        );
    }
}

async fn assert_tenant_read_and_device_routes(ctx: &StranglerHttpContext) {
    let body = ctx.authed_body("GET", "/api/v1/tenants", "").await;
    assert_backend(&body, "rust", "tenant list GET -> rust");

    let body = ctx.authed_body("GET", "/api/v1/tenants/acme", "").await;
    assert_backend(&body, "rust", "tenant detail GET -> rust");

    for (path, body_in) in [
        ("/api/v1/auth/device/code", "{}"),
        ("/api/v1/auth/device/approve", "{'user_code':'ABCDEFGH'}"),
        ("/api/v1/auth/device/token", "{'device_code':'dev'}"),
    ] {
        let body = ctx.authed_body("POST", path, body_in).await;
        assert_backend(&body, "rust", &format!("device-code {path} POST -> rust"));
    }

    let body = ctx.public_body("GET", "/api/v1/auth/device/code", "").await;
    assert_backend(&body, "python", "device-code GET remains python");

    let body = ctx
        .public_body("POST", "/api/v1/auth/device/code/extra", "{}")
        .await;
    assert_backend(&body, "python", "device-code child path remains python");
}

async fn assert_tenant_writes(ctx: &StranglerHttpContext) {
    let body = ctx
        .authed_body("POST", "/api/v1/tenants", "{'name':'Acme'}")
        .await;
    assert_backend(&body, "rust", "tenant POST -> rust");

    let body = ctx
        .authed_body("PUT", "/api/v1/tenants/acme", "{'name':'Acme 2'}")
        .await;
    assert_backend(&body, "rust", "tenant PUT -> rust");

    for (method, path, body_in) in [
        ("POST", "/api/v1/tenants/acme/members", "{'user_id':'u1'}"),
        ("POST", "/api/v1/tenants/acme/members/u1", ""),
        (
            "PATCH",
            "/api/v1/tenants/acme/members/u1",
            "{'role':'viewer'}",
        ),
        ("DELETE", "/api/v1/tenants/acme/members/u1", ""),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(
            &body,
            "rust",
            &format!("tenant member write {method} {path} -> rust"),
        );
    }

    let body = ctx.authed_body("DELETE", "/api/v1/tenants/acme", "").await;
    assert_backend(&body, "rust", "tenant DELETE -> rust");

    let body = ctx
        .authed_body("GET", "/api/v1/tenants/acme/members", "")
        .await;
    assert_backend(&body, "python", "tenant members sibling remains python");
}

async fn assert_invitation_routes(ctx: &StranglerHttpContext) {
    let body = ctx
        .authed_body(
            "POST",
            "/api/v1/tenants/acme/invitations",
            "{'email':'ada@example.test'}",
        )
        .await;
    assert_backend(&body, "rust", "tenant invitation POST -> rust");

    let body = ctx
        .authed_body("GET", "/api/v1/tenants/acme/invitations", "")
        .await;
    assert_backend(&body, "rust", "tenant invitations GET -> rust");

    let body = ctx
        .authed_body("DELETE", "/api/v1/tenants/acme/invitations/inv1", "")
        .await;
    assert_backend(&body, "rust", "tenant invitation DELETE -> rust");

    let body = ctx
        .authed_body("GET", "/api/v1/tenants/acme/invitations/inv1", "")
        .await;
    assert_backend(
        &body,
        "python",
        "uncovered invitation child GET remains python",
    );

    let body = ctx
        .authed_body("GET", "/api/v1/tenants/acme/invitations/inv1/audit", "")
        .await;
    assert_backend(&body, "python", "deeper invitation sibling remains python");

    let body = ctx
        .public_body("GET", "/api/v1/invitations/verify/token1", "")
        .await;
    assert_backend(&body, "rust", "public invitation verify -> rust");

    let body = ctx
        .authed_body("POST", "/api/v1/invitations/accept/token1", "{}")
        .await;
    assert_backend(&body, "rust", "invitation accept -> rust");

    let body = ctx
        .public_body("GET", "/api/v1/invitations/verify/token1/extra", "")
        .await;
    assert_backend(
        &body,
        "python",
        "deeper public invitation path remains python",
    );
}

async fn assert_trust_routes(ctx: &StranglerHttpContext) {
    for (method, path, body_in) in [
        ("GET", "/api/v1/tenants/acme/trust/policies", ""),
        (
            "POST",
            "/api/v1/tenants/acme/trust/policies",
            "{'grant_type':'always'}",
        ),
        ("GET", "/api/v1/tenants/acme/trust/policies/check", ""),
        ("POST", "/api/v1/tenants/acme/trust/approval-requests", "{}"),
        (
            "POST",
            "/api/v1/tenants/acme/trust/approval-requests/rec1/resolve",
            "{'decision':'allow_once'}",
        ),
        ("GET", "/api/v1/tenants/acme/trust/decision-records", ""),
        (
            "GET",
            "/api/v1/tenants/acme/trust/decision-records/rec1",
            "",
        ),
    ] {
        let body = ctx.authed_body(method, path, body_in).await;
        assert_backend(&body, "rust", &format!("trust {method} {path} -> rust"));
    }

    let body = ctx
        .authed_body("DELETE", "/api/v1/tenants/acme/trust/policies", "")
        .await;
    assert_backend(&body, "python", "trust uncovered DELETE remains python");

    let body = ctx
        .authed_body("GET", "/api/v1/tenants/acme/trust/policies/check/extra", "")
        .await;
    assert_backend(&body, "python", "deeper trust sibling remains python");
}

async fn assert_public_share_routes(ctx: &StranglerHttpContext) {
    let body = ctx
        .public_body("GET", "/api/v1/shared/share_token", "")
        .await;
    assert_backend(&body, "rust", "public share GET -> rust");

    let body = ctx
        .public_body("GET", "/api/v1/shared/share_token/extra", "")
        .await;
    assert_backend(&body, "python", "deeper public share path remains python");

    let body = ctx
        .public_body("POST", "/api/v1/shared/share_token", "{}")
        .await;
    assert_backend(&body, "python", "public share POST remains python");
}
