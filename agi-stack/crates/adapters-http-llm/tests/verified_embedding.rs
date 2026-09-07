//! Real loopback HTTP transport with synthetic provider responses, not model acceptance.
use std::num::NonZeroUsize;

use agistack_adapters_http_llm::{HttpEmbedding, VerifiedEmbeddingError};
use serde_json::{json, Value};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use tokio::task::JoinHandle;

async fn provider(status: u16, body: String) -> (String, JoinHandle<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = Vec::new();
        loop {
            let mut chunk = [0; 1024];
            let count = stream.read(&mut chunk).await.unwrap();
            assert_ne!(count, 0);
            bytes.extend_from_slice(&chunk[..count]);
            if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                let headers = String::from_utf8_lossy(&bytes[..end]);
                let length: usize = headers
                    .lines()
                    .find_map(|line| {
                        let (key, value) = line.split_once(':')?;
                        key.eq_ignore_ascii_case("content-length")
                            .then(|| value.trim().parse().unwrap())
                    })
                    .unwrap();
                if bytes.len() >= end + 4 + length {
                    break;
                }
            }
        }
        stream.write_all(format!("HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
        String::from_utf8(bytes).unwrap()
    });
    (base, task)
}

fn response(vector: Value) -> Value {
    json!({"model":"embedding-test", "data":[{"index":0,"embedding":vector}]})
}

#[tokio::test]
async fn verified_embedding_preserves_request_and_validated_provenance() {
    let (base, request) = provider(200, response(json!([0.1, -0.2, 0.3])).to_string()).await;
    let result = HttpEmbedding::new(base, "embedding-test")
        .with_api_key("synthetic-test-key")
        .embed_verified("  原文\nexact  ", NonZeroUsize::new(3))
        .await
        .unwrap();
    assert_eq!(result.model(), "embedding-test");
    assert_eq!(result.dimensions().get(), 3);
    assert_eq!(result.vector(), &[0.1_f32, -0.2, 0.3]);
    let request = request.await.unwrap();
    assert!(request.starts_with("POST /embeddings HTTP/1.1"));
    assert!(request.contains("authorization: Bearer synthetic-test-key\r\n"));
    let body: Value = serde_json::from_str(request.split_once("\r\n\r\n").unwrap().1).unwrap();
    assert_eq!(
        body,
        json!({"model":"embedding-test", "input":"  原文\nexact  ", "encoding_format":"float"})
    );
}

#[tokio::test]
async fn rejects_wrong_model_shape_index_dimensions_and_zero_vectors() {
    let cases = [
        (
            json!({"data":[{"index":0,"embedding":[1]}]}),
            VerifiedEmbeddingError::InvalidResponse,
        ),
        (
            json!({"model":"other", "data":[{"index":0,"embedding":[1]}]}),
            VerifiedEmbeddingError::ModelMismatch,
        ),
        (
            json!({"model":"embedding-test", "data":[]}),
            VerifiedEmbeddingError::InvalidResponse,
        ),
        (
            json!({"model":"embedding-test", "data":[{"embedding":[1]}]}),
            VerifiedEmbeddingError::InvalidResponse,
        ),
        (
            json!({"model":"embedding-test", "data":[{"index":1,"embedding":[1]}]}),
            VerifiedEmbeddingError::InvalidResponse,
        ),
        (
            json!({"model":"embedding-test", "data":[{"index":0,"embedding":[1]}, {"index":0,"embedding":[2]}]}),
            VerifiedEmbeddingError::InvalidResponse,
        ),
        (response(json!([])), VerifiedEmbeddingError::InvalidVector),
        (
            response(json!([0.0, -0.0])),
            VerifiedEmbeddingError::InvalidVector,
        ),
        (
            response(json!([1, 2])),
            VerifiedEmbeddingError::DimensionMismatch,
        ),
        (
            response(json!([1e100])),
            VerifiedEmbeddingError::InvalidVector,
        ),
    ];
    for (body, expected) in cases {
        let (base, request) = provider(200, body.to_string()).await;
        assert_eq!(
            HttpEmbedding::new(base, "embedding-test")
                .embed_verified("source", NonZeroUsize::new(1))
                .await
                .unwrap_err(),
            expected,
            "{body}"
        );
        request.await.unwrap();
    }
}

#[tokio::test]
async fn omitted_dimension_observes_first_valid_vector_and_tiny_vectors_are_valid() {
    let (base, request) = provider(200, response(json!([1e-40, 0])).to_string()).await;
    let result = HttpEmbedding::new(base, "embedding-test")
        .embed_verified("source", None)
        .await
        .unwrap();
    assert_eq!(result.dimensions().get(), 2);
    assert!(result.vector()[0] > 0.0);
    request.await.unwrap();
}

#[tokio::test]
async fn invalid_input_is_rejected_before_network_and_failures_do_not_disclose_body() {
    for (url, model, input) in [
        ("http://127.0.0.1:1", "", "source"),
        ("http://127.0.0.1:1", " embedding-test", "source"),
        ("http://127.0.0.1:1", "embedding-test", ""),
        (
            "http://user:private@127.0.0.1:1",
            "embedding-test",
            "source",
        ),
        ("http://127.0.0.1:1?key=private", "embedding-test", "source"),
    ] {
        assert_eq!(
            HttpEmbedding::new(url, model)
                .embed_verified(input, None)
                .await
                .unwrap_err(),
            VerifiedEmbeddingError::InvalidInput
        );
    }
    let (base, request) = provider(401, "private provider diagnostic".into()).await;
    let error = HttpEmbedding::new(base, "embedding-test")
        .embed_verified("source", None)
        .await
        .unwrap_err();
    assert_eq!(error, VerifiedEmbeddingError::HttpStatus(401));
    assert!(!error.to_string().contains("private"));
    request.await.unwrap();
    let (base, request) = provider(200, "private invalid JSON".into()).await;
    assert_eq!(
        HttpEmbedding::new(base, "embedding-test")
            .embed_verified("source", None)
            .await
            .unwrap_err(),
        VerifiedEmbeddingError::InvalidResponse
    );
    request.await.unwrap();
}

#[tokio::test]
async fn redirect_never_forwards_embedding_input_to_another_endpoint() {
    let (other, forwarded) = provider(200, response(json!([1])).to_string()).await;
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let redirect = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = [0; 4096];
        assert!(stream.read(&mut bytes).await.unwrap() > 0);
        stream.write_all(format!("HTTP/1.1 307 Temporary Redirect\r\nLocation: {other}/embeddings\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
    });
    let result = HttpEmbedding::new(base, "embedding-test")
        .embed_verified("source stays at its configured endpoint", None)
        .await;
    let was_forwarded = forwarded.is_finished();
    forwarded.abort();
    redirect.await.unwrap();
    assert_eq!(result.unwrap_err(), VerifiedEmbeddingError::HttpStatus(307));
    assert!(!was_forwarded);
}

#[tokio::test]
async fn cancelling_an_embedding_request_closes_the_in_flight_connection() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let request = tokio::spawn(async move {
        HttpEmbedding::new(base, "embedding-test")
            .embed_verified("source", None)
            .await
    });
    let (mut stream, _) = listener.accept().await.unwrap();
    let mut bytes = [0; 4096];
    assert!(stream.read(&mut bytes).await.unwrap() > 0);
    request.abort();
    assert!(request.await.unwrap_err().is_cancelled());
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        loop {
            match stream.read(&mut bytes).await {
                Ok(0) | Err(_) => break,
                Ok(_) => {}
            }
        }
    })
    .await
    .expect("aborted request retained its socket");
}
