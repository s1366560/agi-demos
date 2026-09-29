use std::sync::{Arc, Mutex};

use agistack_adapters_http_llm::HttpLlm;
use agistack_core::agent::types::AgentAction;
use agistack_core::ports::LlmPort;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

fn sse(fragment: &str) -> String {
    format!(
        "data: {}\n\n",
        serde_json::json!({"choices":[{"delta":{"content":fragment}}]})
    )
}

#[tokio::test]
async fn agent_answer_arrives_before_provider_finishes() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let (release, wait) = tokio::sync::oneshot::channel();
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut request = [0; 8192];
        let n = socket.read(&mut request).await.unwrap();
        assert!(String::from_utf8_lossy(&request[..n]).contains("\"stream\":true"));
        let first = sse(r#"{"kind":"finish","answer":"Hello "#);
        let last = format!("{}data: [DONE]\n\n", sse("world\"}"));
        let header = format!(
            "HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ncontent-length: {}\r\n\r\n",
            first.len() + last.len()
        );
        socket.write_all(header.as_bytes()).await.unwrap();
        socket.write_all(first.as_bytes()).await.unwrap();
        socket.flush().await.unwrap();
        // The server cannot finish until the client proves it received a delta.
        wait.await.unwrap();
        socket.write_all(last.as_bytes()).await.unwrap();
    });
    let llm = HttpLlm::new(base, "test");
    let output = Arc::new(Mutex::new(String::new()));
    let sink = output.clone();
    let (delta_tx, mut delta_rx) = tokio::sync::mpsc::unbounded_channel();
    let client = tokio::spawn(async move {
        llm.decide_with_tools_stream("hi", 1, &[], &[], &|text| {
            sink.lock().unwrap().push_str(text);
            delta_tx.send(text.to_owned()).unwrap();
        })
        .await
        .unwrap()
    });
    assert_eq!(
        tokio::time::timeout(std::time::Duration::from_secs(5), delta_rx.recv())
            .await
            .unwrap()
            .unwrap(),
        "Hello "
    );
    assert!(!client.is_finished());
    release.send(()).unwrap();
    assert!(
        matches!(client.await.unwrap(), AgentAction::Finish { answer } if answer == "Hello world")
    );
    server.await.unwrap();
    assert_eq!(*output.lock().unwrap(), "Hello world");
}

#[tokio::test]
async fn streamed_malformed_answer_is_not_repaired_or_concatenated() {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let server = tokio::spawn(async move {
        let (mut socket, _) = listener.accept().await.unwrap();
        let mut request = [0; 8192];
        socket.read(&mut request).await.unwrap();
        let body = format!(
            "{}data: [DONE]\n\n",
            sse(r#"{"kind":"finish","answer":"partial"#)
        );
        let response = format!("HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\ncontent-length: {}\r\n\r\n{body}", body.len());
        socket.write_all(response.as_bytes()).await.unwrap();
    });
    let output = Mutex::new(String::new());
    let error = HttpLlm::new(base, "test")
        .decide_with_tools_stream("hi", 1, &[], &[], &|text| {
            output.lock().unwrap().push_str(text);
        })
        .await
        .unwrap_err();
    server.await.unwrap();
    assert_eq!(*output.lock().unwrap(), "partial");
    assert!(error
        .to_string()
        .contains("invalid action after answer streaming began"));
}
