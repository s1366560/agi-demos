use super::{assert_backend, StranglerHttpContext};

pub(super) async fn assert_attachment_routing(ctx: &StranglerHttpContext) {
    for path in [
        "/api/v1/attachments?conversation_id=conversation-1",
        "/api/v1/attachments/?conversation_id=conversation-1&status=ready",
        "/api/v1/attachments/attachment-1",
    ] {
        let body = ctx.authed_body("GET", path, "").await;
        assert_backend(&body, "rust", path);
        assert!(
            body.contains(ctx.bearer),
            "attachment strangler request should preserve authorization: {body}"
        );
    }

    let delete_path = "/api/v1/attachments/attachment-1";
    let delete_body = ctx.authed_body("DELETE", delete_path, "").await;
    assert_backend(&delete_body, "rust", delete_path);
    assert!(
        delete_body.contains(ctx.bearer),
        "attachment delete strangler request should preserve authorization: {delete_body}"
    );

    let simple_upload_path = "/api/v1/attachments/upload/simple";
    let simple_upload_body = ctx.authed_body("POST", simple_upload_path, "").await;
    assert_backend(&simple_upload_body, "rust", simple_upload_path);
    assert!(
        simple_upload_body.contains(ctx.bearer),
        "attachment simple upload strangler request should preserve authorization: {simple_upload_body}"
    );

    for (method, path, body) in [
        ("GET", "/api/v1/attachments/upload", ""),
        ("POST", "/api/v1/attachments/upload/initiate", "{}"),
        ("GET", "/api/v1/attachments/upload/simple", ""),
        ("POST", "/api/v1/attachments/upload/simple/extra", ""),
        ("POST", "/api/v1/attachments/upload/complete", "{}"),
        ("POST", "/api/v1/attachments/upload/abort", ""),
        ("GET", "/api/v1/attachments/attachment-1/download", ""),
        ("DELETE", "/api/v1/attachments/upload", ""),
        ("DELETE", "/api/v1/attachments/attachment-1/download", ""),
    ] {
        let response = ctx.authed_body(method, path, body).await;
        assert_backend(&response, "python", path);
    }
}
