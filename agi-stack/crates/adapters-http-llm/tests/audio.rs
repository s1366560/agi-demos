use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Mutex,
};

use agistack_adapters_http_llm::{with_model_request_log, AnthropicLlm, HttpLlm, RequestLoggedLlm};
use agistack_core::{
    agent::types::{MediaAttachment, Role, TranscriptEntry},
    model_request::{ModelRequestLog, ModelRequestStatus},
    ports::{CoreResult, LlmPort},
};
use base64::{engine::general_purpose::STANDARD, Engine as _};
use serde_json::{json, Value};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpListener,
};

static NEXT: AtomicU64 = AtomicU64::new(0);
const PNG: &str =
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/a9sAAAAASUVORK5CYII=";

struct File(std::path::PathBuf);
impl File {
    fn new(bytes: &[u8]) -> Self {
        let path = std::env::temp_dir().join(format!(
            "memstack-audio-http-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::write(&path, bytes).unwrap();
        Self(path)
    }
    fn attachment(&self, mime: &str) -> MediaAttachment {
        MediaAttachment {
            artifact_path: self.0.to_string_lossy().into(),
            mime_type: mime.into(),
        }
    }
}
impl Drop for File {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn wav() -> Vec<u8> {
    let mut bytes = b"RIFF".to_vec();
    bytes.extend_from_slice(&38u32.to_le_bytes());
    bytes.extend_from_slice(b"WAVEfmt ");
    bytes.extend_from_slice(&16u32.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&1u16.to_le_bytes());
    bytes.extend_from_slice(&8_000u32.to_le_bytes());
    bytes.extend_from_slice(&16_000u32.to_le_bytes());
    bytes.extend_from_slice(&2u16.to_le_bytes());
    bytes.extend_from_slice(&16u16.to_le_bytes());
    bytes.extend_from_slice(b"data");
    bytes.extend_from_slice(&2u32.to_le_bytes());
    bytes.extend_from_slice(&[0, 0]);
    bytes
}

fn mp3() -> Vec<u8> {
    let mut bytes = vec![0; 417];
    bytes[..4].copy_from_slice(&[0xff, 0xfb, 0x90, 0x64]);
    bytes
}

struct Server {
    url: String,
    captured: Arc<Mutex<Vec<Value>>>,
    task: tokio::task::JoinHandle<()>,
}
impl Server {
    async fn new(stream: bool) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let captured = Arc::new(Mutex::new(Vec::new()));
        let sink = captured.clone();
        let task = tokio::spawn(async move {
            while let Ok((mut socket, _)) = listener.accept().await {
                let mut bytes = Vec::new();
                let header_end = loop {
                    let mut buffer = [0; 1024];
                    let count = socket.read(&mut buffer).await.unwrap();
                    if count == 0 {
                        return;
                    }
                    bytes.extend_from_slice(&buffer[..count]);
                    if let Some(index) = bytes.windows(4).position(|part| part == b"\r\n\r\n") {
                        break index + 4;
                    }
                };
                let length = String::from_utf8_lossy(&bytes[..header_end])
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
                let answer = r#"{"kind":"finish","answer":"heard"}"#;
                let body = if stream {
                    format!(
                        "data: {}\n\ndata: [DONE]\n\n",
                        json!({"choices":[{"delta":{"content":answer}}]})
                    )
                } else {
                    json!({"choices":[{"message":{"content":answer}}]}).to_string()
                };
                let content_type = if stream {
                    "text/event-stream"
                } else {
                    "application/json"
                };
                let response = format!(
                    "HTTP/1.1 200 OK\r\ncontent-type: {content_type}\r\ncontent-length: {}\r\nconnection: close\r\n\r\n{body}",
                    body.len()
                );
                socket.write_all(response.as_bytes()).await.unwrap();
            }
        });
        Self {
            url,
            captured,
            task,
        }
    }
}
impl Drop for Server {
    fn drop(&mut self) {
        self.task.abort();
    }
}

#[derive(Default)]
struct Log(Mutex<Vec<Value>>);
#[async_trait::async_trait]
impl ModelRequestLog for Log {
    async fn prepare_request(&self, _: &str, body: Value) -> CoreResult<String> {
        self.0.lock().unwrap().push(body);
        Ok("audio-request".into())
    }
    async fn settle_request(&self, _: &str, _: ModelRequestStatus) -> CoreResult<()> {
        Ok(())
    }
    fn cancel_request(&self, _: &str) {}
}

#[test]
fn declared_audio_capability_is_preserved_by_request_logging() {
    for supported in [false, true] {
        let target =
            HttpLlm::new("http://127.0.0.1:1", "opaque").with_audio_input_support(supported);
        assert_eq!(target.supports_audio_input(), supported);
        let logged = RequestLoggedLlm::new(Arc::new(target), Arc::new(Log::default()));
        assert_eq!(logged.supports_audio_input(), supported);
    }
    assert!(!HttpLlm::new("http://127.0.0.1:1", "audio-model").supports_audio_input());
}

#[tokio::test]
async fn audio_requires_explicit_capability_before_read_or_http_for_every_model_name() {
    let server = Server::new(false).await;
    let missing = MediaAttachment {
        artifact_path: "/missing/audio.wav".into(),
        mime_type: "audio/wav".into(),
    };
    for model in ["audio-model", "opaque-model"] {
        let error = HttpLlm::new(&server.url, model)
            .complete_with_media("s", "u", &[missing.clone()])
            .await
            .unwrap_err();
        assert!(error.to_string().contains("audio_input_unsupported"));
    }
    let error = AnthropicLlm::new(&server.url, "opaque-model")
        .with_vision_support(false)
        .complete_with_media_stream("s", "u", &[missing], |_| {})
        .await
        .unwrap_err();
    assert!(error.to_string().contains("audio_input_unsupported"));
    assert!(server.captured.lock().unwrap().is_empty());
}

#[tokio::test]
async fn openai_audio_encodes_wav_and_mp3_in_normal_and_streaming_requests_without_log_bytes() {
    for (mime, format, bytes) in [("audio/wav", "wav", wav()), ("audio/mpeg", "mp3", mp3())] {
        for stream in [false, true] {
            let file = File::new(&bytes);
            let server = Server::new(stream).await;
            let model = HttpLlm::new(&server.url, "opaque-model")
                .with_audio_input_support(true)
                .with_vision_support(false);
            let transcript = [
                TranscriptEntry::new(0, Role::Human, "Describe the attachment")
                    .with_media(vec![file.attachment(mime)]),
            ];
            let log = Arc::new(Log::default());
            if stream {
                with_model_request_log(
                    log.clone(),
                    model.decide_with_tools_stream("hear", 1, &transcript, &[], &|_| {}),
                )
                .await
                .unwrap();
            } else {
                with_model_request_log(log.clone(), model.decide("hear", 1, &transcript, &[]))
                    .await
                    .unwrap();
            }
            let wire = server.captured.lock().unwrap();
            assert_eq!(wire.len(), 1);
            let input = &wire[0]["messages"][1]["content"][1];
            assert_eq!(input["type"], "input_audio");
            assert_eq!(input["input_audio"]["format"], format);
            assert_eq!(input["input_audio"]["data"], STANDARD.encode(&bytes));
            let recorded = log.0.lock().unwrap();
            assert!(!recorded[0].to_string().contains(&STANDARD.encode(&bytes)));
            assert_eq!(
                recorded[0]["messages"][1]["content"][1]["input_audio"]["data"],
                "[audio payload withheld]"
            );
        }
    }
}

#[tokio::test]
async fn image_and_audio_keep_distinct_blocks_and_independent_capabilities() {
    let audio = File::new(&wav());
    let image = File::new(&STANDARD.decode(PNG).unwrap());
    let media = [audio.attachment("audio/wav"), image.attachment("image/png")];
    let server = Server::new(false).await;
    HttpLlm::new(&server.url, "opaque")
        .with_audio_input_support(true)
        .complete_with_media("s", "u", &media)
        .await
        .unwrap();
    let captured = server.captured.lock().unwrap();
    let content = &captured[0]["messages"][1]["content"];
    assert_eq!(content[1]["type"], "input_audio");
    assert_eq!(content[2]["type"], "image_url");
    drop(captured);
    let error = HttpLlm::new(&server.url, "opaque")
        .with_audio_input_support(true)
        .with_vision_support(false)
        .complete_with_media("s", "u", &media)
        .await
        .unwrap_err();
    assert!(error.to_string().contains("vision_unsupported"));
    assert_eq!(server.captured.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn invalid_audio_paths_types_and_limits_fail_before_dispatch() {
    let server = Server::new(false).await;
    let model = HttpLlm::new(&server.url, "opaque").with_audio_input_support(true);
    let valid = File::new(&wav());
    let invalid = File::new(b"RIFF not really a wave");
    let oversized = File::new(&wav());
    std::fs::OpenOptions::new()
        .write(true)
        .open(&oversized.0)
        .unwrap()
        .set_len(32 * 1024 * 1024 + 1)
        .unwrap();
    for attachment in [
        MediaAttachment {
            artifact_path: "relative.wav".into(),
            mime_type: "audio/wav".into(),
        },
        invalid.attachment("audio/wav"),
        valid.attachment("audio/mpeg"),
        oversized.attachment("audio/wav"),
    ] {
        let error = model
            .complete_with_media("s", "u", &[attachment])
            .await
            .unwrap_err();
        assert!(
            error.to_string().contains("audio_input_invalid_artifact"),
            "{error}"
        );
    }
    let error = model
        .complete_with_media("s", "u", &[valid.attachment("audio/ogg")])
        .await
        .unwrap_err();
    assert!(error.to_string().contains("audio_input_format_unsupported"));
    let error = model
        .complete_with_media("s", "u", &vec![valid.attachment("audio/wav"); 5])
        .await
        .unwrap_err();
    assert!(error.to_string().contains("audio_input_limit_exceeded"));
    #[cfg(unix)]
    {
        let link = File::new(&[]);
        std::fs::remove_file(&link.0).unwrap();
        std::os::unix::fs::symlink(&valid.0, &link.0).unwrap();
        let error = model
            .complete_with_media("s", "u", &[link.attachment("audio/wav")])
            .await
            .unwrap_err();
        assert!(error.to_string().contains("audio_input_invalid_artifact"));
    }
    assert!(server.captured.lock().unwrap().is_empty());
}
