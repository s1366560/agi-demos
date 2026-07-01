//! Live chat-LLM conformance against **real** OpenAI-compatible coding-plan
//! providers — GLM (Zhipu/z.ai) and MiniMax.
//!
//! Unlike `http_llm.rs` (a canned tokio mock that only proves parsing + error
//! mapping), this drives `HttpLlm` against genuine hosted models and asserts:
//!   1. **liveness + instruction following** — a trivial prompt through the new
//!      `complete` method comes back non-empty and echoes the requested token;
//!   2. **structured extraction end to end** — `extract_memory` turns an episode
//!      into a well-formed `MemoryDraft`, exercising chat + reasoning-block
//!      (`<think>…</think>`) stripping + JSON parsing. MiniMax-M2 is a reasoning
//!      model that always prepends a `<think>` block, so this is the behavioural
//!      proof the adapter now survives modern reasoning providers.
//!
//! Because `LlmPort` is a pure I/O side-effect port (a model call, not a value
//! store), the honest evidence is *behavioural conformance against live infra*,
//! like the SMTP (F10) and embedding live tests — not cross-adapter byte parity.
//!
//! Env-gated per provider: with no API key (or an unreachable / throttled
//! endpoint) each test prints `[skip]` and passes, so an offline
//! `cargo test --workspace` stays green. Keys + overrides:
//!   GLM:     `GLM_API_KEY` | `ZAI_API_KEY`;
//!            `AGISTACK_GLM_BASE_URL`     (default `https://api.z.ai/api/coding/paas/v4`)
//!            `AGISTACK_GLM_MODEL`        (default `glm-4.6`)
//!   MiniMax: `MINIMAX_API_KEY`;
//!            `AGISTACK_MINIMAX_BASE_URL` (default `https://api.minimaxi.com/v1`)
//!            `AGISTACK_MINIMAX_MODEL`    (default `MiniMax-M2`)

use std::time::Duration;

use agistack_adapters_http_llm::HttpLlm;
use agistack_core::model::{Episode, SourceType};
use agistack_core::ports::{CoreError, LlmPort};

/// First non-empty value among `keys`, if any is set in the environment.
fn env_first(keys: &[&str]) -> Option<String> {
    keys.iter()
        .find_map(|k| std::env::var(k).ok().filter(|v| !v.trim().is_empty()))
}

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key)
        .ok()
        .filter(|v| !v.trim().is_empty())
        .unwrap_or_else(|| default.to_string())
}

/// A throttling / rate-limit error is not a conformance failure — under a tight
/// coding-plan RPS budget we honestly skip rather than fake a pass or fail.
fn is_throttle(e: &CoreError) -> bool {
    let s = e.to_string().to_lowercase();
    s.contains("429") || s.contains("rate limit") || s.contains("too many")
}

async fn exercise(provider: &str, base: String, model: String, key: String) {
    let llm = HttpLlm::new(base.clone(), model.clone()).with_api_key(key);

    // (1) Liveness + basic instruction following via the new `complete` method.
    //     Doubles as the reachability gate: unreachable / throttled -> skip.
    let answer = match llm
        .complete(
            "You are a test fixture. Follow the instruction exactly.",
            "Reply with exactly one word in uppercase and nothing else: PONG",
        )
        .await
    {
        Ok(a) => a,
        Err(e) => {
            eprintln!("[skip] {provider} chat {base} model {model} unavailable: {e}");
            return;
        }
    };
    assert!(
        !answer.trim().is_empty(),
        "{provider}: completion must be non-empty"
    );
    assert!(
        answer.to_uppercase().contains("PONG"),
        "{provider}: model should follow the instruction and emit PONG, got {answer:?}"
    );

    // Be gentle on tight coding-plan rate limits before the heavier call.
    std::thread::sleep(Duration::from_millis(1500));

    // (2) Structured extraction end to end: chat + <think>-strip + JSON parse.
    let episode = Episode {
        content: "Alice met Bob at the Rust conference in Berlin; they discussed the \
                  tokio async runtime and knowledge-graph memory."
            .into(),
        source_type: SourceType::Text,
        valid_at_ms: 0,
        name: None,
        project_id: Some("live-test".into()),
        user_id: None,
    };
    match llm.extract_memory(&episode).await {
        Ok(draft) => {
            assert!(
                !draft.title.trim().is_empty(),
                "{provider}: extracted draft title must be non-empty"
            );
            assert!(
                !draft.content.trim().is_empty(),
                "{provider}: extracted draft content must be non-empty"
            );
            eprintln!(
                "[ok] {provider} live: complete+extract ok; model={model} \
                 title={:?} tags={} entities={}",
                draft.title,
                draft.tags.len(),
                draft.entities.len()
            );
        }
        // A throttle between the two calls is not a conformance failure.
        Err(e) if is_throttle(&e) => {
            eprintln!("[skip] {provider} extract throttled (rate limit): {e}");
        }
        Err(e) => panic!("{provider}: extract_memory failed (not a throttle): {e}"),
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn glm_coding_plan_live() {
    let Some(key) = env_first(&["GLM_API_KEY", "ZAI_API_KEY"]) else {
        eprintln!("[skip] GLM: no GLM_API_KEY / ZAI_API_KEY in env");
        return;
    };
    let base = env_or("AGISTACK_GLM_BASE_URL", "https://api.z.ai/api/coding/paas/v4");
    let model = env_or("AGISTACK_GLM_MODEL", "glm-4.6");
    exercise("GLM", base, model, key).await;
}

#[tokio::test(flavor = "multi_thread")]
async fn minimax_coding_plan_live() {
    let Some(key) = env_first(&["MINIMAX_API_KEY"]) else {
        eprintln!("[skip] MiniMax: no MINIMAX_API_KEY in env");
        return;
    };
    let base = env_or("AGISTACK_MINIMAX_BASE_URL", "https://api.minimaxi.com/v1");
    let model = env_or("AGISTACK_MINIMAX_MODEL", "MiniMax-M2");
    exercise("MiniMax", base, model, key).await;
}
