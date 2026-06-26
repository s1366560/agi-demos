//! Device-tier integration: durable SQLite memory repo, vector index, and the
//! checkpoint store driving real ReAct crash recovery across a simulated restart.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use agistack_adapters_device::{
    HnswVectorIndex, SqliteCheckpointStore, SqliteMemoryRepository, SqliteVectorIndex,
};
use agistack_adapters_mem::{FixedClock, HashEmbedding, NgramHashEmbedding, ScriptedLlm, StubLlm};
use agistack_core::agent::types::{CompletedCall, Role, TranscriptEntry};
use agistack_core::ports::{CheckpointStore, CoreResult, EmbeddingPort, ToolHost, VectorIndexPort};
use agistack_core::{
    AgentAction, Episode, HitlKind, HitlRequest, MemoryService, ReActEngine, SessionState,
    SessionStatus, SourceType,
};
use futures::executor::block_on;

fn episode(content: &str) -> Episode {
    Episode {
        content: content.to_string(),
        source_type: SourceType::Text,
        valid_at_ms: 0,
        name: None,
        project_id: Some("p1".into()),
        user_id: None,
    }
}

#[test]
fn sqlite_repo_persists_and_searches_via_sql() {
    let repo = Arc::new(SqliteMemoryRepository::in_memory().unwrap());
    let service = MemoryService::new(
        repo,
        Arc::new(StubLlm),
        Arc::new(HashEmbedding::new(8)),
        Arc::new(FixedClock(1)),
    );

    let mem = block_on(service.ingest_episode(
        "p1",
        "u1",
        &episode("Local-first apps store data on device using sqlite"),
    ))
    .unwrap();

    let got = block_on(service.get(&mem.id)).unwrap().unwrap();
    assert_eq!(got.id, mem.id);
    assert_eq!(got.embedding.unwrap().len(), 8);

    let hits = block_on(service.search("p1", "sqlite", 10)).unwrap();
    assert_eq!(hits.len(), 1);
    let miss = block_on(service.search("p1", "postgres", 10)).unwrap();
    assert!(miss.is_empty());
}

#[test]
fn sqlite_vector_index_semantic_search_is_durable() {
    let vectors = Arc::new(SqliteVectorIndex::in_memory().unwrap());
    let service = MemoryService::new(
        Arc::new(SqliteMemoryRepository::in_memory().unwrap()),
        Arc::new(StubLlm),
        Arc::new(HashEmbedding::new(32)),
        Arc::new(FixedClock(1)),
    )
    .with_vectors(vectors);

    let target = block_on(service.ingest_episode(
        "p1",
        "u1",
        &episode("vector embeddings power semantic similarity search"),
    ))
    .unwrap();
    block_on(service.ingest_episode("p1", "u1", &episode("a recipe for garlic bread"))).unwrap();

    let hits =
        block_on(service.semantic_search("p1", "semantic similarity embeddings", 2)).unwrap();
    assert!(!hits.is_empty());
    assert_eq!(hits[0].id, target.id);
}

/// Cross-adapter parity: the HNSW ANN index must return the **same top-1** as the
/// exact brute-force [`SqliteVectorIndex`] for a realistic corpus embedded with
/// [`NgramHashEmbedding`]. This is the correctness gate behind the speed win the
/// `vector_bench` example measures — fast is only useful if it is also right.
#[test]
fn hnsw_matches_brute_force_top1_on_ngram_corpus() {
    let embed = NgramHashEmbedding::new(256, 3);
    let brute = SqliteVectorIndex::in_memory().unwrap();
    let ann = HnswVectorIndex::new();

    let corpus = [
        ("m1", "local-first apps sync data across devices"),
        ("m2", "vector embeddings drive semantic similarity search"),
        ("m3", "a recipe for sourdough bread and garlic butter"),
        ("m4", "rust compiles to webassembly for the browser"),
        ("m5", "approximate nearest neighbour graphs speed up retrieval"),
        ("m6", "quarterly revenue forecast and budget planning"),
    ];
    for (id, text) in corpus {
        let v = block_on(embed.embed(text)).unwrap();
        block_on(brute.upsert("p1", id, &v)).unwrap();
        block_on(ann.upsert("p1", id, &v)).unwrap();
    }

    for query in [
        "nearest neighbour search retrieval",
        "embeddings for semantic search",
        "bread recipe",
        "webassembly in the browser",
    ] {
        let q = block_on(embed.embed(query)).unwrap();
        let b = block_on(brute.query("p1", &q, 1)).unwrap();
        let a = block_on(ann.query("p1", &q, 1)).unwrap();
        assert_eq!(b[0].id, a[0].id, "top-1 mismatch for query {query:?}");
        // Both report cosine similarity in the same orientation (higher = closer).
        assert!((b[0].score - a[0].score).abs() < 1e-4);
    }
}

/// A `ToolHost` that counts invocations — to prove the resumed engine reuses the
/// saved tool output instead of re-running it.
struct CountingToolHost {
    calls: AtomicUsize,
}
#[async_trait]
impl ToolHost for CountingToolHost {
    fn list_tools(&self) -> Vec<String> {
        vec!["len".into()]
    }
    async fn call(&self, _tool: &str, _input: &str) -> CoreResult<String> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(r#"{"fresh":true}"#.into())
    }
}

const LEN_INPUT: &str = r#"{"text":"hello"}"#;

/// End-to-end durable recovery: persist a mid-round checkpoint to SQLite, drop
/// the engine (simulating a crash), then a fresh engine backed by the SAME
/// SQLite store resumes and reuses the completed tool call — counter stays 0.
#[test]
fn ckpt_survives_restart_and_engine_reuses_completed_call() {
    let store = Arc::new(SqliteCheckpointStore::in_memory().unwrap());

    // Mid-round crash state: round 0 tool already executed + persisted.
    let mut seeded = SessionState::new("s1", "len of hello", Some("p1"));
    seeded.push_unique(TranscriptEntry::new(0, Role::Action, format!("len {LEN_INPUT}")));
    seeded.completed_tool_calls.push(CompletedCall {
        round: 0,
        tool: "len".into(),
        input_json: LEN_INPUT.into(),
        output_json: r#"{"reused":true}"#.into(),
    });
    block_on(store.save(&seeded)).unwrap();

    // It is durably loadable (the restart boundary).
    let reloaded = block_on(store.load("s1")).unwrap().unwrap();
    assert_eq!(reloaded.round, 0);
    assert_eq!(reloaded.completed_tool_calls.len(), 1);

    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });
    let script = vec![
        AgentAction::CallTool {
            tool: "len".into(),
            input_json: LEN_INPUT.into(),
        },
        AgentAction::Finish {
            answer: "5".into(),
        },
    ];
    let engine = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script)),
        tools.clone(),
        store.clone(),
        Arc::new(FixedClock(0)),
    );

    let state = block_on(engine.run("s1", "len of hello", Some("p1"))).unwrap();
    assert_eq!(tools.calls.load(Ordering::SeqCst), 0, "must reuse saved output");
    assert_eq!(state.status, SessionStatus::Finished);
    assert_eq!(state.answer.as_deref(), Some("5"));

    // The final state was checkpointed durably.
    let final_state = block_on(store.load("s1")).unwrap().unwrap();
    assert_eq!(final_state.status, SessionStatus::Finished);
}

/// HITL suspend/resume survives a SQLite round-trip: a loop suspends on a human
/// request (status + pending request persisted to SQLite), a fresh engine backed
/// by the SAME store resumes with the answer and finishes — proving the HITL
/// fields serialize through the durable checkpoint, not just memory.
#[test]
fn hitl_suspend_and_resume_survive_sqlite_roundtrip() {
    let store = Arc::new(SqliteCheckpointStore::in_memory().unwrap());
    let tools = Arc::new(CountingToolHost {
        calls: AtomicUsize::new(0),
    });
    let script = || {
        vec![
            AgentAction::CallTool {
                tool: "len".into(),
                input_json: LEN_INPUT.into(),
            },
            AgentAction::RequestHuman {
                request: HitlRequest::new("approve-1", HitlKind::Decision, "ship it?"),
            },
            AgentAction::Finish {
                answer: "shipped".into(),
            },
        ]
    };

    // Engine #1 runs until it suspends on the HITL request.
    let engine1 = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script())),
        tools.clone(),
        store.clone(),
        Arc::new(FixedClock(0)),
    );
    let suspended = block_on(engine1.run("s-hitl", "ship the build", Some("p1"))).unwrap();
    assert_eq!(suspended.status, SessionStatus::AwaitingInput);
    assert_eq!(tools.calls.load(Ordering::SeqCst), 1);

    // The suspension is durably reloadable from SQLite (the restart boundary):
    // status and the pending request both survived JSON serialization.
    let reloaded = block_on(store.load("s-hitl")).unwrap().unwrap();
    assert_eq!(reloaded.status, SessionStatus::AwaitingInput);
    assert_eq!(reloaded.pending_hitl.as_ref().unwrap().id, "approve-1");
    assert_eq!(reloaded.pending_hitl.as_ref().unwrap().kind, HitlKind::Decision);

    // Engine #2 (fresh) resumes against the same store and completes.
    let engine2 = ReActEngine::new(
        Arc::new(ScriptedLlm::new(script())),
        tools.clone(),
        store.clone(),
        Arc::new(FixedClock(0)),
    );
    let done = block_on(engine2.resume("s-hitl", "approve-1", "yes")).unwrap();
    assert_eq!(done.status, SessionStatus::Finished);
    assert_eq!(done.answer.as_deref(), Some("shipped"));
    assert_eq!(
        tools.calls.load(Ordering::SeqCst),
        1,
        "round-0 tool must not be re-run across the SQLite resume"
    );
    assert_eq!(done.hitl_answer("approve-1"), Some("yes"));

    // Final state is durably finished.
    let final_state = block_on(store.load("s-hitl")).unwrap().unwrap();
    assert_eq!(final_state.status, SessionStatus::Finished);
}
