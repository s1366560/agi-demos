//! Device-tier integration: durable SQLite memory repo, vector index, and the
//! checkpoint store driving real ReAct crash recovery across a simulated restart.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use async_trait::async_trait;
use agistack_adapters_device::{SqliteCheckpointStore, SqliteMemoryRepository, SqliteVectorIndex};
use agistack_adapters_mem::{FixedClock, HashEmbedding, ScriptedLlm, StubLlm};
use agistack_core::agent::types::{CompletedCall, Role, TranscriptEntry};
use agistack_core::ports::{CheckpointStore, CoreResult, ToolHost};
use agistack_core::{
    AgentAction, Episode, MemoryService, ReActEngine, SessionState, SessionStatus, SourceType,
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
