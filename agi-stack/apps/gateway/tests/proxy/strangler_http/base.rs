use super::*;

pub(super) async fn assert_base_routing(ctx: &StranglerHttpContext) {
    // Strangled GET -> Rust upstream, Authorization forwarded verbatim.
    let r = ctx
        .http
        .get(ctx.url("/api/v1/memories/"))
        .header("authorization", ctx.bearer)
        .send()
        .await
        .expect("memories route should return a response");
    assert_eq!(r.status(), StatusCode::OK);
    let body = r.text().await.expect("memories response body should read");
    assert_backend(&body, "rust", "memories GET -> rust");
    assert!(
        body.contains("\"path\":\"/api/v1/memories/\""),
        "path preserved: {body}"
    );
    assert!(
        body.contains(&format!("\"auth\":\"{}\"", ctx.bearer)),
        "bearer forwarded: {body}"
    );

    // Non-strangled GET -> Python upstream.
    let body = ctx
        .body(
            ctx.http
                .get(ctx.url("/api/v1/not-strangled"))
                .header("authorization", ctx.bearer),
        )
        .await;
    assert_backend(&body, "python", "not-strangled GET -> python");

    // Strangled POST with a body -> Rust upstream, method + body preserved.
    let body = ctx
        .body(
            ctx.http
                .post(ctx.url("/api/v1/episodes/"))
                .header("authorization", ctx.bearer)
                .body("{'content':'hello'}"),
        )
        .await;
    assert_backend(&body, "rust", "episodes POST -> rust");
    assert!(
        body.contains("\"method\":\"POST\""),
        "method preserved: {body}"
    );
    assert!(body.contains("hello"), "body forwarded: {body}");

    // A prefix that only *looks* strangled has no segment boundary.
    let body = ctx.public_body("GET", "/api/v1/memories_admin", "").await;
    assert_backend(&body, "python", "memories_admin remains python");

    // Upstream 307 is relayed, not followed.
    let r = ctx
        .http
        .get(ctx.url("/api/v1/redirect"))
        .send()
        .await
        .expect("redirect route should return a response");
    assert_eq!(r.status(), StatusCode::TEMPORARY_REDIRECT);
    assert_eq!(
        r.headers()
            .get("location")
            .expect("redirect response should include location"),
        "/moved"
    );
}
