//! HTTP LLM/embedding adapter against a **canned mock server** — no real key,
//! no network. The mock is a raw `tokio` TCP listener that replies with a fixed
//! HTTP response, so these tests add no heavy mock-framework dependency and run
//! fully offline (they prove parsing + error mapping, not a live provider).

use std::sync::Arc;

use agistack_adapters_http_llm::{HttpEmbedding, HttpLlm};
use agistack_core::agent::types::{AgentAction, Role, TranscriptEntry};
use agistack_core::model::{Episode, SourceType};
use agistack_core::ports::{CoreError, EmbeddingPort, LlmPort};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

/// Spawn a one-route mock that returns `status`/`body` for every request, and
/// records the raw request bytes it received. Returns (base_url, captured).
async fn mock(status: u16, body: &'static str) -> (String, Arc<tokio::sync::Mutex<Vec<String>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let captured = Arc::new(tokio::sync::Mutex::new(Vec::<String>::new()));
    let sink = captured.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut sock, _)) = listener.accept().await else {
                break;
            };
            let mut buf = vec![0u8; 8192];
            let n = sock.read(&mut buf).await.unwrap_or(0);
            sink.lock()
                .await
                .push(String::from_utf8_lossy(&buf[..n]).to_string());
            let reason = if status == 200 { "OK" } else { "ERROR" };
            let resp = format!(
                "HTTP/1.1 {status} {reason}\r\ncontent-type: application/json\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            let _ = sock.write_all(resp.as_bytes()).await;
            let _ = sock.flush().await;
        }
    });
    (format!("http://{addr}"), captured)
}

fn chat_body(content: &str) -> String {
    // Build a valid OpenAI chat-completions envelope whose message.content is the
    // model's (string) answer. serde_json::to_string escapes content correctly.
    serde_json::json!({ "choices": [{ "message": { "content": content } }] }).to_string()
}

#[tokio::test]
async fn extract_memory_parses_chat_json() {
    let draft = r#"{"title":"Local-first","content":"apps store data on device","tags":["local-first","sqlite"],"entities":[{"name":"SQLite","kind":"tech"}]}"#;
    let body: &'static str = Box::leak(chat_body(draft).into_boxed_str());
    let (base, captured) = mock(200, body).await;

    let llm = HttpLlm::new(base, "test-model").with_api_key("ms_sk_x");
    let episode = Episode {
        content: "We use SQLite for local-first storage".into(),
        source_type: SourceType::Text,
        valid_at_ms: 0,
        name: None,
        project_id: Some("p1".into()),
        user_id: None,
    };
    let got = llm.extract_memory(&episode).await.unwrap();
    assert_eq!(got.title, "Local-first");
    assert_eq!(got.tags, vec!["local-first", "sqlite"]);
    assert_eq!(got.entities.len(), 1);
    assert_eq!(got.entities[0].name, "SQLite");

    // The bearer key reached the wire and the request hit /chat/completions.
    let reqs = captured.lock().await;
    assert!(reqs[0].contains("POST /chat/completions"));
    assert!(reqs[0].contains("authorization: Bearer ms_sk_x"));
}

#[tokio::test]
async fn decide_parses_call_tool_action() {
    // The action enum is `#[serde(tag = "kind")]`, so the model's JSON maps 1:1.
    let action = r#"{"kind":"call_tool","tool":"len","input_json":"{\"text\":\"hi\"}"}"#;
    let body: &'static str = Box::leak(chat_body(action).into_boxed_str());
    let (base, _c) = mock(200, body).await;

    let llm = HttpLlm::new(base, "m");
    let got = llm
        .decide("count chars", 0, &[], &["len".to_string()])
        .await
        .unwrap();
    match got {
        AgentAction::CallTool { tool, input_json } => {
            assert_eq!(tool, "len");
            assert_eq!(input_json, r#"{"text":"hi"}"#);
        }
        other => panic!("expected CallTool, got {other:?}"),
    }
}

#[tokio::test]
async fn decide_tolerates_markdown_fenced_finish() {
    // Real models often wrap JSON in ```json fences — the adapter strips them.
    let fenced = "```json\n{\"kind\":\"finish\",\"answer\":\"42\"}\n```";
    let body: &'static str = Box::leak(chat_body(fenced).into_boxed_str());
    let (base, _c) = mock(200, body).await;

    let llm = HttpLlm::new(base, "m");
    let transcript = vec![TranscriptEntry::new(0, Role::Observation, "len=42")];
    let got = llm.decide("len", 1, &transcript, &[]).await.unwrap();
    assert_eq!(
        got,
        AgentAction::Finish {
            answer: "42".into()
        }
    );
}

#[tokio::test]
async fn stream_complete_collects_openai_sse_deltas() {
    let stream_body = concat!(
        "event: message\n",
        "data: {\"choices\":[{\"index\":0,\"delta\":{\"role\":\"assistant\"}}]}\n\n",
        "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"Hel\"}}]}\r\n\r\n",
        "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"lo\"}}]}\n\n",
        "data: [DONE]\n\n"
    );
    let body: &'static str = Box::leak(stream_body.to_string().into_boxed_str());
    let (base, captured) = mock(200, body).await;

    let llm = HttpLlm::new(base, "m").with_api_key("stream-key");
    let mut deltas = Vec::new();
    let full = llm
        .stream_complete("s", "u", |delta| deltas.push(delta.to_string()))
        .await
        .unwrap();

    assert_eq!(deltas, vec!["Hel", "lo"]);
    assert_eq!(full, "Hello");
    let reqs = captured.lock().await;
    assert!(reqs[0].contains("POST /chat/completions"));
    assert!(reqs[0].contains("authorization: Bearer stream-key"));
    assert!(reqs[0].contains("\"stream\":true"));
}

#[tokio::test]
async fn embedding_parses_data_vector() {
    let body: &'static str = r#"{"data":[{"embedding":[0.1,0.2,0.3,0.4]}]}"#;
    let (base, captured) = mock(200, body).await;

    let emb = HttpEmbedding::new(base, "text-embed").with_api_key("k");
    let v = emb.embed("hello").await.unwrap();
    assert_eq!(v, vec![0.1, 0.2, 0.3, 0.4]);
    assert!(captured.lock().await[0].contains("POST /embeddings"));
}

#[tokio::test]
async fn http_500_maps_to_core_error() {
    let (base, _c) = mock(500, r#"{"error":"boom"}"#).await;
    let llm = HttpLlm::new(base, "m");
    let err = llm.decide("x", 0, &[], &[]).await.unwrap_err();
    assert!(matches!(err, CoreError::Llm(_)), "got {err:?}");
}

#[tokio::test]
async fn bad_json_content_maps_to_core_error() {
    // 200 OK but the model returned prose, not JSON -> parse error surfaces.
    let body: &'static str = Box::leak(chat_body("I cannot help with that.").into_boxed_str());
    let (base, _c) = mock(200, body).await;
    let llm = HttpLlm::new(base, "m");
    let err = llm.decide("x", 0, &[], &[]).await.unwrap_err();
    assert!(matches!(err, CoreError::Llm(_)), "got {err:?}");
}
