use futures_util::StreamExt;
use reqwest::header::{HeaderMap, HeaderValue};
use serde::{Deserialize, Serialize};

use agistack_core::ports::{CoreError, CoreResult};

#[derive(Serialize)]
struct AnthropicMessage {
    role: &'static str,
    content: String,
}

#[derive(Serialize)]
struct AnthropicMessagesRequest {
    model: String,
    system: String,
    messages: Vec<AnthropicMessage>,
    max_tokens: u32,
    temperature: f32,
    stream: bool,
}

#[derive(Deserialize)]
struct AnthropicStreamEvent {
    #[serde(rename = "type")]
    kind: String,
    #[serde(default)]
    delta: Option<AnthropicDelta>,
    #[serde(default)]
    error: Option<AnthropicError>,
}

#[derive(Deserialize)]
struct AnthropicDelta {
    #[serde(rename = "type")]
    kind: String,
    #[serde(default)]
    text: Option<String>,
}

#[derive(Deserialize)]
struct AnthropicError {
    #[serde(rename = "type")]
    kind: String,
    message: String,
}

/// Anthropic Messages adapter for provider-native `/messages` streaming.
///
/// This stays separate from [`crate::HttpLlm`] because Anthropic's request path,
/// authentication headers, request body, and SSE event shapes are not
/// OpenAI-compatible. Like [`crate::HttpLlm::stream_complete`], it is an
/// adapter-level proof point so the portable core LLM port remains dependency-free.
pub struct AnthropicLlm {
    client: reqwest::Client,
    base_url: String,
    api_key: Option<String>,
    model: String,
    version: String,
    max_tokens: u32,
}

impl AnthropicLlm {
    /// Point at an Anthropic-compatible base URL, e.g. `https://api.anthropic.com/v1`.
    pub fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self {
            client: reqwest::Client::new(),
            base_url: base_url.into().trim_end_matches('/').to_string(),
            api_key: None,
            model: model.into(),
            version: "2023-06-01".to_string(),
            max_tokens: 1024,
        }
    }

    /// Attach an Anthropic API key. Direct Anthropic uses `x-api-key`.
    pub fn with_api_key(mut self, key: impl Into<String>) -> Self {
        self.api_key = Some(key.into());
        self
    }

    /// Override the Anthropic API version header for conformance tests or migrations.
    pub fn with_version(mut self, version: impl Into<String>) -> Self {
        self.version = version.into();
        self
    }

    /// Override the default streaming response budget.
    pub fn with_max_tokens(mut self, max_tokens: u32) -> Self {
        self.max_tokens = max_tokens;
        self
    }

    /// Stream a raw single-turn completion from Anthropic Messages SSE.
    ///
    /// `on_delta` is invoked for every `content_block_delta` / `text_delta` text
    /// fragment and the fully assembled content is returned when `message_stop`
    /// is observed or the stream closes.
    pub async fn stream_complete<F>(
        &self,
        system: &str,
        user: impl Into<String>,
        mut on_delta: F,
    ) -> CoreResult<String>
    where
        F: FnMut(&str),
    {
        let body = AnthropicMessagesRequest {
            model: self.model.clone(),
            system: system.to_string(),
            messages: vec![AnthropicMessage {
                role: "user",
                content: user.into(),
            }],
            max_tokens: self.max_tokens,
            temperature: 0.0,
            stream: true,
        };
        let url = format!("{}/messages", self.base_url);
        let mut headers = HeaderMap::new();
        let version = HeaderValue::from_str(&self.version)
            .map_err(|e| CoreError::Llm(format!("bad anthropic version header: {e}")))?;
        headers.insert("anthropic-version", version);
        if let Some(key) = &self.api_key {
            let value = HeaderValue::from_str(key)
                .map_err(|e| CoreError::Llm(format!("bad anthropic api key header: {e}")))?;
            headers.insert("x-api-key", value);
        }

        let resp = self
            .client
            .post(url)
            .headers(headers)
            .json(&body)
            .send()
            .await
            .map_err(|e| CoreError::Llm(e.to_string()))?;
        let resp = resp
            .error_for_status()
            .map_err(|e| CoreError::Llm(e.to_string()))?;
        let mut chunks = resp.bytes_stream();
        let mut line_buffer = Vec::new();
        let mut content = String::new();
        let mut done = false;

        while let Some(chunk) = chunks.next().await {
            let chunk = chunk.map_err(|e| CoreError::Llm(e.to_string()))?;
            line_buffer.extend_from_slice(&chunk);
            while let Some(newline_index) = line_buffer.iter().position(|b| *b == b'\n') {
                let line: Vec<u8> = line_buffer.drain(..=newline_index).collect();
                if handle_anthropic_stream_line(&line, &mut content, &mut on_delta)? {
                    done = true;
                    break;
                }
            }
            if done {
                break;
            }
        }

        if !done && !line_buffer.is_empty() {
            handle_anthropic_stream_line(&line_buffer, &mut content, &mut on_delta)?;
        }

        Ok(content)
    }
}

fn handle_anthropic_stream_line<F>(
    line: &[u8],
    content: &mut String,
    on_delta: &mut F,
) -> CoreResult<bool>
where
    F: FnMut(&str),
{
    let line = std::str::from_utf8(line)
        .map_err(|e| CoreError::Llm(format!("bad anthropic stream utf-8: {e}")))?
        .trim_end_matches(['\r', '\n']);
    let Some(payload) = line.strip_prefix("data:") else {
        return Ok(false);
    };
    let payload = payload.trim_start();
    if payload.is_empty() {
        return Ok(false);
    }

    let event: AnthropicStreamEvent = serde_json::from_str(payload)
        .map_err(|e| CoreError::Llm(format!("bad anthropic stream json: {e}")))?;
    if let Some(error) = event.error {
        return Err(CoreError::Llm(format!(
            "anthropic stream error {}: {}",
            error.kind, error.message
        )));
    }
    if event.kind == "message_stop" {
        return Ok(true);
    }
    if event.kind != "content_block_delta" {
        return Ok(false);
    }
    let Some(delta) = event.delta else {
        return Ok(false);
    };
    if delta.kind != "text_delta" {
        return Ok(false);
    }
    let Some(text) = delta.text.filter(|s| !s.is_empty()) else {
        return Ok(false);
    };
    on_delta(&text);
    content.push_str(&text);
    Ok(false)
}
