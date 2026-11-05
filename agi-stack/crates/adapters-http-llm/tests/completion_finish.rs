//! Completion termination is a protocol fact, including empty SSE terminal chunks.
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex,
};

use agistack_adapters_http_llm::HttpLlm;
use agistack_core::{agent::types::AgentAction, ports::LlmPort};
use serde_json::{json, Value};
use tokio::{
    io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader},
    net::TcpListener,
    task::JoinHandle,
};

struct MockServer {
    base: String,
    requests: Arc<AtomicUsize>,
    task: JoinHandle<()>,
}
impl Drop for MockServer {
    fn drop(&mut self) {
        self.task.abort();
    }
}

async fn serve(content_type: &'static str, body: String) -> MockServer {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let requests = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&requests);
    let task = tokio::spawn(async move {
        loop {
            let Ok((socket, _)) = listener.accept().await else {
                break;
            };
            let mut socket = BufReader::new(socket);
            let mut length = 0;
            loop {
                let mut line = String::new();
                if socket.read_line(&mut line).await.unwrap() == 0 || line == "\r\n" {
                    break;
                }
                if let Some((name, value)) = line.split_once(':') {
                    if name.eq_ignore_ascii_case("content-length") {
                        length = value.trim().parse::<usize>().unwrap();
                    }
                }
            }
            socket.read_exact(&mut vec![0; length]).await.unwrap();
            counter.fetch_add(1, Ordering::SeqCst);
            let response = format!(
                "HTTP/1.1 200 OK\r\ncontent-type: {content_type}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                body.len()
            );
            socket
                .get_mut()
                .write_all(response.as_bytes())
                .await
                .unwrap();
        }
    });
    MockServer {
        base,
        requests,
        task,
    }
}

fn completion(content: Value, reason: Value) -> Value {
    json!({"choices":[{"message":{"content":content},"finish_reason":reason}]})
}

fn sse(value: Value) -> String {
    format!("data: {value}\n\n")
}

fn assert_reason_error(error: impl std::fmt::Display, reason: &str) {
    let message = error.to_string();
    assert!(
        message.contains(&format!("finish_reason={reason}")),
        "{message}"
    );
    assert!(
        message.len() < 160,
        "provider diagnostics must stay bounded"
    );
    assert!(!message.contains("owned-secret"));
    assert!(!message.contains("bad repaired action json"));
}

#[tokio::test]
async fn ordinary_rejects_known_incomplete_reasons_before_action_or_repair() {
    for (reason, content) in [
        (
            "length",
            json!(r#"{"kind":"call_tool","tool":"fixture","input_json":{}}"#),
        ),
        (
            "length",
            json!(r#"{"kind":"call_tool","tool":"owned-secret"#),
        ),
        ("content_filter", Value::Null),
    ] {
        let server = serve(
            "application/json",
            completion(content, json!(reason)).to_string(),
        )
        .await;
        let error = HttpLlm::new(&server.base, "fixture")
            .with_api_key("owned-secret")
            .decide("neutral fixture", 0, &[], &[])
            .await
            .unwrap_err();
        assert_reason_error(error, reason);
        assert_eq!(server.requests.load(Ordering::SeqCst), 1, "must not repair");
    }
}

#[tokio::test]
async fn ordinary_preserves_legacy_reasons_and_first_choice_selection() {
    for reason in [
        Value::Null,
        json!("stop"),
        json!("owned-secret-future-reason"),
    ] {
        let body = completion(json!(r#"{"kind":"finish","answer":"neutral"}"#), reason);
        let server = serve("application/json", body.to_string()).await;
        let action = HttpLlm::new(&server.base, "fixture")
            .decide("neutral", 0, &[], &[])
            .await
            .unwrap();
        assert!(matches!(action, AgentAction::Finish { answer } if answer == "neutral"));
    }
    let mut body = completion(
        json!(r#"{"kind":"finish","answer":"first"}"#),
        json!("stop"),
    );
    body["choices"]
        .as_array_mut()
        .unwrap()
        .push(completion(Value::Null, json!("length"))["choices"][0].clone());
    let server = serve("application/json", body.to_string()).await;
    assert_eq!(
        HttpLlm::new(&server.base, "fixture")
            .complete("neutral", "neutral")
            .await
            .unwrap(),
        r#"{"kind":"finish","answer":"first"}"#
    );
    body["choices"][0]["finish_reason"] = json!("length");
    let server = serve("application/json", body.to_string()).await;
    assert_reason_error(
        HttpLlm::new(&server.base, "fixture")
            .complete("neutral", "neutral")
            .await
            .unwrap_err(),
        "length",
    );
}

#[tokio::test]
async fn stream_checks_empty_terminal_chunks_before_accepting_tool_actions() {
    for reason in ["length", "content_filter"] {
        for delta in [None, Some(json!({})), Some(json!({"content":null}))] {
            let mut terminal = json!({"choices":[{"index":0,"finish_reason":reason}]});
            if let Some(delta) = delta {
                terminal["choices"][0]["delta"] = delta;
            }
            let body = sse(
                json!({"choices":[{"index":0,"delta":{"content":r#"{"kind":"call_tool","tool":"fixture","input_json":{}}"#}}]}),
            ) + &sse(terminal)
                + "data: [DONE]\n\n";
            let server = serve("text/event-stream", body).await;
            let error = HttpLlm::new(&server.base, "fixture")
                .decide_with_tools_stream("neutral", 0, &[], &[], &|_| {})
                .await
                .unwrap_err();
            assert_reason_error(error, reason);
            assert_eq!(server.requests.load(Ordering::SeqCst), 1, "must not repair");
        }
    }
}

#[tokio::test]
async fn truncated_stream_retains_committed_prefix_without_repair_or_second_answer() {
    let body = sse(
        json!({"choices":[{"delta":{"content":r#"{"kind":"finish","answer":"neutral prefix"#}}]}),
    ) + &sse(json!({"choices":[{"delta":{},"finish_reason":"length"}]}))
        + "data: [DONE]\n\n";
    let server = serve("text/event-stream", body).await;
    let output = Mutex::new(String::new());
    let error = HttpLlm::new(&server.base, "fixture")
        .decide_with_tools_stream("neutral", 0, &[], &[], &|text| {
            output.lock().unwrap().push_str(text)
        })
        .await
        .unwrap_err();
    assert_reason_error(error, "length");
    assert_eq!(*output.lock().unwrap(), "neutral prefix");
    assert_eq!(server.requests.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn streamed_json_fallback_checks_reason_before_any_delta() {
    for reason in ["length", "content_filter"] {
        let body = completion(
            json!(r#"{"kind":"finish","answer":"owned-secret"}"#),
            json!(reason),
        );
        let server = serve("application/json", body.to_string()).await;
        let output = Mutex::new(String::new());
        let error = HttpLlm::new(&server.base, "fixture")
            .stream_complete("neutral", "neutral", |text| {
                output.lock().unwrap().push_str(text)
            })
            .await
            .unwrap_err();
        assert_reason_error(error, reason);
        assert!(output.lock().unwrap().is_empty());
        assert_eq!(server.requests.load(Ordering::SeqCst), 1);
    }
}

#[tokio::test]
async fn legacy_streams_and_usage_only_chunks_remain_compatible() {
    for reason in [
        None,
        Some(Value::Null),
        Some(json!("stop")),
        Some(json!("provider_specific")),
    ] {
        let mut terminal = json!({"choices":[{"delta":{}}]});
        if let Some(reason) = reason {
            terminal["choices"][0]["finish_reason"] = reason;
        }
        let body = sse(
            json!({"choices":[{"delta":{"content":r#"{"kind":"finish","answer":"neutral"}"#}}]}),
        ) + &sse(terminal)
            + &sse(json!({"choices":[],"usage":{"completion_tokens":12}}))
            + "data: [DONE]\n\n";
        let server = serve("text/event-stream", body).await;
        let action = HttpLlm::new(&server.base, "fixture")
            .decide_with_tools_stream("neutral", 0, &[], &[], &|_| {})
            .await
            .unwrap();
        assert!(matches!(action, AgentAction::Finish { answer } if answer == "neutral"));
        assert_eq!(server.requests.load(Ordering::SeqCst), 1);
    }
}
