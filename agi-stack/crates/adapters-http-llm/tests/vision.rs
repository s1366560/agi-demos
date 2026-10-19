use std::sync::{
    Arc, Mutex,
    atomic::{AtomicU64, Ordering},
};

use agistack_adapters_http_llm::{AnthropicLlm, HttpLlm, with_model_request_log};
use agistack_core::{
    agent::types::{MediaAttachment, Role, TranscriptEntry},
    model_request::{ModelRequestLog, ModelRequestStatus},
    ports::{CoreResult, LlmPort},
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

const PNG: &str =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=";
static NEXT: AtomicU64 = AtomicU64::new(0);
struct ImageFile(std::path::PathBuf);
impl ImageFile {
    fn new() -> Self {
        let path = std::env::temp_dir().join(format!(
            "memstack-vision-{}-{}.png",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::write(&path, STANDARD.decode(PNG).unwrap()).unwrap();
        Self(path)
    }
    fn attachment(&self) -> MediaAttachment {
        MediaAttachment {
            artifact_path: self.0.to_string_lossy().into(),
            mime_type: "image/png".into(),
        }
    }
}
impl Drop for ImageFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

async fn server(sse: bool, anthropic: bool) -> (String, Arc<Mutex<Vec<Value>>>) {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let captured = Arc::new(Mutex::new(Vec::new()));
    let sink = captured.clone();
    tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                return;
            };
            let mut bytes = Vec::new();
            let header_end = loop {
                let mut buffer = [0; 1024];
                let length = socket.read(&mut buffer).await.unwrap();
                if length == 0 {
                    return;
                }
                bytes.extend_from_slice(&buffer[..length]);
                if let Some(index) = bytes.windows(4).position(|window| window == b"\r\n\r\n") {
                    break index + 4;
                }
            };
            let headers = String::from_utf8_lossy(&bytes[..header_end]);
            let length = headers
                .lines()
                .find_map(|line| {
                    line.to_ascii_lowercase()
                        .strip_prefix("content-length:")
                        .map(|length| length.trim().parse::<usize>().unwrap())
                })
                .unwrap();
            while bytes.len() < header_end + length {
                let mut buffer = [0; 1024];
                let count = socket.read(&mut buffer).await.unwrap();
                if count == 0 {
                    return;
                }
                bytes.extend_from_slice(&buffer[..count]);
            }
            sink.lock()
                .unwrap()
                .push(serde_json::from_slice(&bytes[header_end..header_end + length]).unwrap());
            let answer = r#"{"kind":"finish","answer":"visible"}"#;
            let body = if anthropic {
                format!(
                    "data: {}\n\ndata: {{\"type\":\"message_stop\"}}\n\n",
                    json!({"type":"content_block_delta","delta":{"type":"text_delta","text":answer}})
                )
            } else if sse {
                format!(
                    "data: {}\n\ndata: [DONE]\n\n",
                    json!({"choices":[{"delta":{"content":answer}}]})
                )
            } else {
                json!({"choices":[{"message":{"content":answer}}]}).to_string()
            };
            let content_type = if sse {
                "text/event-stream"
            } else {
                "application/json"
            };
            let response = format!(
                "HTTP/1.1 200 OK\r\ncontent-type: {content_type}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = socket.write_all(response.as_bytes()).await;
        }
    });
    (format!("http://{address}"), captured)
}

#[derive(Default)]
struct Log(Mutex<Vec<Value>>);
#[async_trait::async_trait]
impl ModelRequestLog for Log {
    async fn prepare_request(&self, _: &str, body: Value) -> CoreResult<String> {
        self.0.lock().unwrap().push(body);
        Ok("request".into())
    }
    async fn settle_request(&self, _: &str, _: ModelRequestStatus) -> CoreResult<()> {
        Ok(())
    }
    fn cancel_request(&self, _: &str) {}
}

#[tokio::test]
async fn openai_decision_uses_real_image_blocks_without_logging_image_bytes() {
    for stream in [false, true] {
        let image = ImageFile::new();
        let (base, wire) = server(stream, false).await;
        let model = HttpLlm::new(base, "configured-vision-model");
        let transcript = vec![
            TranscriptEntry::new(0, Role::Observation, "screen text")
                .with_media(vec![image.attachment()]),
        ];
        let log = Arc::new(Log::default());
        let deltas = Mutex::new(String::new());
        if stream {
            with_model_request_log(
                log.clone(),
                model.decide_with_tools_stream("inspect", 1, &transcript, &[], &|text| {
                    deltas.lock().unwrap().push_str(text)
                }),
            )
            .await
            .unwrap();
            assert_eq!(*deltas.lock().unwrap(), "visible");
        } else {
            with_model_request_log(log.clone(), model.decide("inspect", 1, &transcript, &[]))
                .await
                .unwrap();
        }
        let wire = wire.lock().unwrap();
        let content = &wire[0]["messages"][1]["content"];
        assert_eq!(content[0]["type"], "text");
        assert!(!content[0]["text"].as_str().unwrap().contains(PNG));
        assert_eq!(content[1]["type"], "image_url");
        assert_eq!(
            content[1]["image_url"]["url"],
            format!("data:image/png;base64,{PNG}")
        );
        let recorded = log.0.lock().unwrap();
        assert!(!recorded[0].to_string().contains(PNG));
        assert_eq!(
            recorded[0]["messages"][1]["content"][1]["image_url"]["url"],
            "[image payload withheld]"
        );
    }
}

#[tokio::test]
async fn anthropic_stream_sends_native_image_source_and_redacts_request_log() {
    let image = ImageFile::new();
    let (base, wire) = server(true, true).await;
    let model = AnthropicLlm::new(base, "configured-vision-model");
    let log = Arc::new(Log::default());
    let mut deltas = String::new();
    with_model_request_log(
        log.clone(),
        model.complete_with_media_stream("system", "inspect", &[image.attachment()], |text| {
            deltas.push_str(text)
        }),
    )
    .await
    .unwrap();
    assert!(deltas.contains("visible"));
    let wire = wire.lock().unwrap();
    let content = &wire[0]["messages"][0]["content"];
    assert_eq!(
        content[1],
        json!({"type":"image","source":{"type":"base64","media_type":"image/png","data":PNG}})
    );
    assert!(!log.0.lock().unwrap()[0].to_string().contains(PNG));
}

#[tokio::test]
async fn text_output_with_a_path_does_not_create_media_or_read_files() {
    let (base, wire) = server(false, false).await;
    let model = HttpLlm::new(base, "text-model");
    let transcript = vec![TranscriptEntry::new(
        0,
        Role::Observation,
        r#"{"screenshot":{"file_path":"/missing/not-trusted.png"}}"#,
    )];
    model.decide("inspect", 1, &transcript, &[]).await.unwrap();
    let wire = wire.lock().unwrap();
    assert!(wire[0]["messages"][1]["content"].is_string());
}

#[tokio::test]
async fn unsupported_vision_and_invalid_artifacts_fail_before_http_dispatch() {
    let image = ImageFile::new();
    let error = HttpLlm::new("http://127.0.0.1:1", "text-model")
        .with_vision_support(false)
        .complete_with_media("s", "u", &[image.attachment()])
        .await
        .unwrap_err();
    assert!(error.to_string().contains("vision_unsupported"));
    let error = HttpLlm::new("http://127.0.0.1:1", "vision-model")
        .complete_with_media(
            "s",
            "u",
            &[MediaAttachment {
                artifact_path: "relative.png".into(),
                mime_type: "image/png".into(),
            }],
        )
        .await
        .unwrap_err();
    assert!(error.to_string().contains("vision_invalid_artifact"));
}
