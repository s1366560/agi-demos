use super::*;

#[tokio::test]
async fn gateway_routes_preview_host_http_to_rust_and_preserves_host() {
    let rust_mock = Router::new()
        .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
        .with_state("rust");
    let python_mock = Router::new()
        .fallback(get(echo).post(echo).put(echo).patch(echo).delete(echo))
        .with_state("python");

    let rust_url = spawn(rust_mock).await;
    let python_url = spawn(python_mock).await;
    let gateway_url = spawn(app(gateway_state(Upstreams {
        rust: rust_url,
        python: python_url,
    })))
    .await;

    let http = client();
    let r = http
        .post(format!(
            "{gateway_url}/docs/app?ms_preview_session=session1"
        ))
        .header("host", "web.p1.preview.localhost:8000")
        .header("authorization", "Bearer ms_sk_preview_http")
        .body("{'probe':'preview'}")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"rust\""),
        "preview host HTTP -> rust: {body}"
    );
    assert!(body.contains("\"method\":\"POST\""), "{body}");
    assert!(body.contains("\"path\":\"/docs/app\""), "{body}");
    assert!(
        body.contains("\"host\":\"web.p1.preview.localhost:8000\""),
        "original preview host preserved for Rust parser: {body}"
    );
    assert!(body.contains("preview"), "{body}");

    let r = http
        .get(format!("{gateway_url}/docs/app"))
        .header("host", "web.p1.other.localhost:8000")
        .send()
        .await
        .unwrap();
    let body = r.text().await.unwrap();
    assert!(
        body.contains("\"backend\":\"python\""),
        "non-preview host remains python: {body}"
    );
}
