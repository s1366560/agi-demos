//! Live embedding conformance against a **real** OpenAI-/LiteLLM-compatible
//! embeddings endpoint (Ollama / LiteLLM / OpenAI).
//!
//! Unlike `http_llm.rs` (a canned tokio mock that only proves parsing + error
//! mapping), this test drives `HttpEmbedding` against a genuine embedding model
//! server and asserts the vectors are *real embeddings*, not noise:
//!   1. **stable dimensionality** across inputs,
//!   2. **near-determinism** — the same text embeds to a near-identical vector
//!      (cosine ~ 1.0; we tolerate tiny inference/FP jitter, we do NOT assert
//!      bit-equality),
//!   3. **semantic sanity** — a semantically related pair is markedly closer
//!      than an unrelated pair (the behavioural proof it is a real model).
//!
//! Because `EmbeddingPort` is a pure I/O side-effect port (a model call, not a
//! value store), the honest evidence is *behavioural conformance against live
//! infra*, exactly like the SMTP (F10) live test — not cross-adapter byte
//! parity (F5/F6/F8) and not a state-machine walk (F9).
//!
//! Env-gated: if the endpoint is unreachable or the model is missing, the first
//! `embed` returns `Err` and the test prints `[skip]` and passes, so an offline
//! `cargo test --workspace` stays green. Overrides:
//!   `AGISTACK_EMBED_URL`   (default `http://localhost:11434/v1`)
//!   `AGISTACK_EMBED_MODEL` (default `qwen3-embedding:0.6b`)

use agistack_adapters_http_llm::HttpEmbedding;
use agistack_core::ports::EmbeddingPort;

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let na: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let nb: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if na == 0.0 || nb == 0.0 {
        0.0
    } else {
        dot / (na * nb)
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn embeds_against_real_model_server() {
    let url = env_or("AGISTACK_EMBED_URL", "http://localhost:11434/v1");
    let model = env_or("AGISTACK_EMBED_MODEL", "qwen3-embedding:0.6b");
    let embedder = HttpEmbedding::new(url.clone(), model.clone());

    // Gate: a real call is the reachability probe. Unreachable endpoint or a
    // missing model -> Err -> skip (offline stays green).
    let base = match embedder.embed("reachability probe").await {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[skip] embeddings endpoint {url} model {model} unavailable: {e}");
            return;
        }
    };
    assert!(!base.is_empty(), "a real embedding must be non-empty");
    let dim = base.len();

    // (1) stable dimensionality across different inputs.
    let cat1 = embedder
        .embed("The cat sat on the warm mat.")
        .await
        .expect("embed cat1");
    assert_eq!(
        cat1.len(),
        dim,
        "dimensionality must be stable across inputs"
    );

    // (2) near-determinism: same text twice -> cosine ~ 1.0 (tolerate jitter).
    let cat2 = embedder
        .embed("The cat sat on the warm mat.")
        .await
        .expect("embed cat2");
    let self_sim = cosine(&cat1, &cat2);
    assert!(
        self_sim > 0.999,
        "same text should embed near-identically, got cosine {self_sim}"
    );

    // (3) semantic sanity: a related pair must be clearly closer than an
    // unrelated one. Measured margins are large (~0.72 vs ~0.28), so a 0.1
    // floor is a strong yet non-flaky claim.
    let kitten = embedder
        .embed("A kitten rested on the cozy rug.")
        .await
        .expect("embed kitten");
    let finance = embedder
        .embed("Quarterly derivatives settlement and tax report.")
        .await
        .expect("embed finance");
    let related = cosine(&cat1, &kitten);
    let unrelated = cosine(&cat1, &finance);
    assert!(
        related > unrelated + 0.1,
        "related texts must be markedly closer than unrelated: \
         related {related} vs unrelated {unrelated}"
    );

    eprintln!(
        "[ok] live embeddings: dim={dim} self_sim={self_sim:.4} \
         related={related:.4} unrelated={unrelated:.4}"
    );
}
