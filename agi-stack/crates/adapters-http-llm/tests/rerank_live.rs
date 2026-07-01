//! Live rerank conformance against a **real** Cohere/Jina/BGE-compatible
//! reranker (e.g. the local `BAAI/bge-reranker-base` dev server on :8081).
//!
//! Drives `HttpRerank` (a cross-encoder second stage for hybrid search) and
//! asserts genuine reranking, not an echo:
//!   1. **complete ordering** — one hit per input document;
//!   2. **descending relevance** — hits are sorted most-relevant first;
//!   3. **semantic correctness** — the one document that actually answers the
//!      query ranks #1, markedly above the distractors.
//!
//! Scores from a cross-encoder are raw (logits, often negative), so we compare
//! *within* the response (relevant ≫ irrelevant) rather than assuming a `[0,1]`
//! range — the honest behavioural proof it is a real model, like the embedding
//! and SMTP live tests.
//!
//! Env-gated: if the endpoint is unreachable the first `rerank` returns `Err`
//! and the test prints `[skip]` and passes, so an offline `cargo test
//! --workspace` stays green. Overrides:
//!   `AGISTACK_RERANK_URL`   (default `http://localhost:8081`)
//!   `AGISTACK_RERANK_MODEL` (default `BAAI/bge-reranker-base`)

use agistack_adapters_http_llm::HttpRerank;
use agistack_core::ports::RerankPort;

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key)
        .ok()
        .filter(|v| !v.trim().is_empty())
        .unwrap_or_else(|| default.to_string())
}

#[tokio::test(flavor = "multi_thread")]
async fn reranks_against_real_cross_encoder() {
    let url = env_or("AGISTACK_RERANK_URL", "http://localhost:8081");
    let model = env_or("AGISTACK_RERANK_MODEL", "BAAI/bge-reranker-base");
    let reranker = HttpRerank::new(url.clone(), model.clone());

    let query = "How do I run asynchronous tasks in Rust?";
    let docs: Vec<String> = vec![
        // index 0 — the only document that actually answers the query.
        "Rust's async/await is powered by futures and executors such as the tokio runtime.".into(),
        // distractors.
        "Bananas are an excellent source of dietary potassium.".into(),
        "The Eiffel Tower is a wrought-iron lattice tower in Paris, France.".into(),
    ];

    // Gate: a real call is the reachability probe. Unreachable -> skip (green).
    let hits = match reranker.rerank(query, &docs).await {
        Ok(h) => h,
        Err(e) => {
            eprintln!("[skip] rerank endpoint {url} model {model} unavailable: {e}");
            return;
        }
    };

    // (1) complete ordering: one hit per document.
    assert_eq!(
        hits.len(),
        docs.len(),
        "reranker must return one hit per document"
    );

    // (2) descending relevance.
    for w in hits.windows(2) {
        assert!(
            w[0].score >= w[1].score,
            "hits must be sorted by descending relevance, got {} then {}",
            w[0].score,
            w[1].score
        );
    }

    // (3) semantic correctness: the async-Rust document (index 0) ranks first,
    //     markedly above the worst distractor (raw-logit margin, measured ~5).
    assert_eq!(
        hits[0].index, 0,
        "the async-Rust document must rank #1, got index {}",
        hits[0].index
    );
    let top = hits[0].score;
    let worst = hits.last().expect("non-empty hits").score;
    assert!(
        top > worst + 1.0,
        "the relevant document must score markedly higher than distractors: \
         top {top} vs worst {worst}"
    );

    eprintln!(
        "[ok] live rerank: model={model} top_index={} top_score={top:.4} worst_score={worst:.4}",
        hits[0].index
    );
}
