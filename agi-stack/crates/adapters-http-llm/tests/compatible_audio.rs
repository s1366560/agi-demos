use std::sync::{Arc, Mutex};

use agistack_adapters_http_llm::HttpLlm;
use agistack_core::{
    agent::types::{AgentAction, MediaAttachment, Role, TranscriptEntry},
    ports::{LlmPort, ToolDefinition},
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

const FIXTURE_KEY: &str = "owned-fixture-credential";

struct Audio(std::path::PathBuf, Vec<u8>);
impl Audio {
    fn new() -> Self {
        let mut bytes = b"RIFF".to_vec();
        bytes.extend_from_slice(&40u32.to_le_bytes());
        bytes.extend_from_slice(b"WAVEfmt ");
        bytes.extend_from_slice(&16u32.to_le_bytes());
        for value in [1u16, 2] {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes.extend_from_slice(&24_000u32.to_le_bytes());
        bytes.extend_from_slice(&96_000u32.to_le_bytes());
        for value in [4u16, 16] {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes.extend_from_slice(b"data");
        bytes.extend_from_slice(&4u32.to_le_bytes());
        bytes.extend_from_slice(&[0; 4]);
        let path = std::env::temp_dir().join(format!(
            "compatible-audio-{}-{}.wav",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::write(&path, &bytes).unwrap();
        Self(path, bytes)
    }
    fn transcript(&self) -> Vec<TranscriptEntry> {
        vec![
            TranscriptEntry::new(0, Role::Human, "Listen to the owned synthetic fixture")
                .with_media(vec![MediaAttachment {
                    artifact_path: self.0.to_string_lossy().into_owned(),
                    mime_type: "audio/wav".into(),
                }]),
        ]
    }
}
static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
impl Drop for Audio {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

struct Server {
    url: String,
    requests: Arc<Mutex<Vec<(String, Value)>>>,
    task: tokio::task::JoinHandle<()>,
}
impl Server {
    async fn new(status: u16, stream: bool, value: Value) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}/api/v3", listener.local_addr().unwrap());
        let requests = Arc::new(Mutex::new(Vec::new()));
        let captured = requests.clone();
        let task = tokio::spawn(async move {
            while let Ok((mut socket, _)) = listener.accept().await {
                let mut bytes = Vec::new();
                let header_end = loop {
                    let mut chunk = [0; 2048];
                    let count = socket.read(&mut chunk).await.unwrap();
                    if count == 0 {
                        return;
                    }
                    bytes.extend_from_slice(&chunk[..count]);
                    if let Some(end) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                        break end + 4;
                    }
                };
                let header = String::from_utf8_lossy(&bytes[..header_end]).into_owned();
                let length = header
                    .lines()
                    .find_map(|line| {
                        line.to_ascii_lowercase()
                            .strip_prefix("content-length:")
                            .map(|n| n.trim().parse::<usize>().unwrap())
                    })
                    .unwrap();
                while bytes.len() < header_end + length {
                    let mut chunk = [0; 2048];
                    let count = socket.read(&mut chunk).await.unwrap();
                    if count == 0 {
                        return;
                    }
                    bytes.extend_from_slice(&chunk[..count]);
                }
                captured.lock().unwrap().push((
                    header,
                    serde_json::from_slice(&bytes[header_end..header_end + length]).unwrap(),
                ));
                let body = if stream {
                    format!("data: {value}\n\ndata: [DONE]\n\n")
                } else {
                    value.to_string()
                };
                let mime = if stream {
                    "text/event-stream"
                } else {
                    "application/json"
                };
                let response = format!("HTTP/1.1 {status} Fixture\r\ncontent-type: {mime}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}", body.len());
                socket.write_all(response.as_bytes()).await.unwrap();
            }
        });
        Self {
            url,
            requests,
            task,
        }
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[tokio::test]
async fn compatible_chat_audio_preserves_tool_actions_in_stream_and_nonstream_requests() {
    for stream in [false, true] {
        let audio = Audio::new();
        let action = json!({"kind":"call_tool","tool":"fixture_counter","input_json":{"count":1}})
            .to_string();
        let value = if stream {
            json!({"choices":[{"delta":{"content":action}}]})
        } else {
            json!({"choices":[{"message":{"content":action}}]})
        };
        let server = Server::new(200, stream, value).await;
        let model = HttpLlm::new(&server.url, "operator-declared-audio")
            .with_api_key(FIXTURE_KEY)
            .with_audio_input_support(true);
        let tools = [ToolDefinition::new(
            "fixture_counter",
            "Update the owned fixture",
            json!({"type":"object","properties":{"count":{"type":"integer"}},"required":["count"]}),
        )];
        let result = if stream {
            model
                .decide_with_tools_stream(
                    "Listen then call the fixture tool",
                    1,
                    &audio.transcript(),
                    &tools,
                    &|_| {},
                )
                .await
        } else {
            model
                .decide_with_tools(
                    "Listen then call the fixture tool",
                    1,
                    &audio.transcript(),
                    &tools,
                )
                .await
        }
        .unwrap();
        assert!(
            matches!(result, AgentAction::CallTool { tool, input_json } if tool == "fixture_counter" && serde_json::from_str::<Value>(&input_json).unwrap() == json!({"count":1}))
        );
        let requests = server.requests.lock().unwrap();
        assert_eq!(requests.len(), 1);
        assert!(requests[0]
            .0
            .starts_with("POST /api/v3/chat/completions HTTP/1.1"));
        assert!(requests[0]
            .0
            .to_ascii_lowercase()
            .contains(&format!("authorization: bearer {FIXTURE_KEY}")));
        let body = &requests[0].1;
        assert_eq!(body["stream"].as_bool().unwrap_or(false), stream);
        let content = &body["messages"][1]["content"];
        assert!(content[0]["text"]
            .as_str()
            .unwrap()
            .contains("fixture_counter"));
        assert_eq!(
            content[1],
            json!({"type":"input_audio","input_audio":{"format":"wav","data":STANDARD.encode(&audio.1)}})
        );
    }
}

#[tokio::test]
async fn compatible_audio_limit_errors_remain_visible_for_http_and_sse_without_credentials() {
    for (stream, status, sse) in [
        (false, 400, false),
        (true, 400, false),
        (true, 200, true),
        (false, 200, false),
        (true, 200, false),
    ] {
        let audio = Audio::new();
        let server = Server::new(status, sse, json!({"error":{"code":"AudioTooLarge","message":format!("Audio exceeds 25000000 bytes; token={FIXTURE_KEY}")}})).await;
        let model = HttpLlm::new(&server.url, "operator-declared-audio")
            .with_api_key(FIXTURE_KEY)
            .with_audio_input_support(true);
        let error = if stream {
            model
                .decide_with_tools_stream("Listen", 1, &audio.transcript(), &[], &|_| {})
                .await
        } else {
            model.decide("Listen", 1, &audio.transcript(), &[]).await
        }
        .unwrap_err()
        .to_string();
        assert!(error.contains("AudioTooLarge"), "{error}");
        assert!(error.contains("25000000"), "{error}");
        assert!(!error.contains(FIXTURE_KEY));
        let requests = server.requests.lock().unwrap();
        assert_eq!(
            requests.len(),
            1,
            "a provider error must not repair or retry without audio"
        );
        assert_eq!(
            requests[0].1["messages"][1]["content"][1]["input_audio"]["data"],
            STANDARD.encode(&audio.1)
        );
    }
}

#[tokio::test]
async fn compatible_audio_never_infers_capability_from_a_model_name_or_makes_a_text_retry() {
    let audio = Audio::new();
    let server = Server::new(200, false, json!({"choices":[]})).await;
    let error = HttpLlm::new(&server.url, "doubao-seed-2-1-lite-260915")
        .decide("Listen", 1, &audio.transcript(), &[])
        .await
        .unwrap_err()
        .to_string();
    assert!(error.contains("audio_input_unsupported"));
    assert!(server.requests.lock().unwrap().is_empty());
}
