use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};

use agistack_adapters_postgres::PgPool;
use agistack_core::agent::types::{AgentAction, TranscriptEntry};
use agistack_core::model::{Episode, SourceType};
use agistack_core::ports::{
    Clock, CoreResult, EmbeddingPort, LlmPort, MemoryDraft, ScoredId, VectorIndexPort,
};
use async_trait::async_trait;
use tokio::sync::Notify;

pub async fn test_pool() -> Option<PgPool> {
    let url = std::env::var("AGISTACK_LEGACY_MEMORY_TEST_URL").ok()?;
    Some(
        sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&url)
            .await
            .unwrap(),
    )
}

pub async fn seed_project(pool: &PgPool, suffix: &str) -> String {
    let project = format!("rust-legacy-{suffix}");
    sqlx::query("INSERT INTO projects (id, tenant_id, owner_id, name, memory_rules, graph_config, sandbox_type, sandbox_config, is_public) VALUES ($1, 'tenant', 'actor', 'Rust legacy QA', '{}'::json, '{}'::json, 'cloud', '{}'::json, false)")
        .bind(&project).execute(pool).await.unwrap();
    sqlx::query("INSERT INTO user_projects (id, user_id, project_id, role, permissions) VALUES ($1, 'actor', $2, 'owner', '{}'::json)")
        .bind(format!("member-{project}")).bind(&project).execute(pool).await.unwrap();
    project
}

pub async fn start_bootstrap(project: &str) -> tokio::task::JoinHandle<()> {
    let project = project.to_string();
    let (ready_tx, ready_rx) = tokio::sync::oneshot::channel();
    let task = tokio::task::spawn_blocking(move || {
        let mut child = Command::new(std::env::var("AGISTACK_LEGACY_MEMORY_PYTHON").unwrap())
            .arg(std::env::var("AGISTACK_LEGACY_MEMORY_BOOTSTRAP").unwrap())
            .args(["--bootstrap", &project])
            .current_dir(std::env::var("AGISTACK_LEGACY_MEMORY_ROOT").unwrap())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let mut line = String::new();
        output.read_line(&mut line).unwrap();
        assert_eq!(line.trim(), "BOOTSTRAP_READY");
        let _ = ready_tx.send(());
        let result = child.wait_with_output().unwrap();
        assert!(
            result.status.success(),
            "bootstrap failed: {}",
            String::from_utf8_lossy(&result.stderr)
        );
    });
    ready_rx.await.unwrap();
    task
}

pub fn episode(project: &str) -> Episode {
    Episode {
        content: "Source".into(),
        source_type: SourceType::Text,
        valid_at_ms: 1,
        name: Some("QA".into()),
        project_id: Some(project.into()),
        user_id: Some("actor".into()),
    }
}

pub struct FixedClock;
impl Clock for FixedClock {
    fn now_ms(&self) -> i64 {
        1
    }
}

#[derive(Default)]
pub struct Probes {
    pub extractions: AtomicUsize,
    pub embeddings: AtomicUsize,
}
#[async_trait]
impl LlmPort for Probes {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        self.extractions.fetch_add(1, Ordering::SeqCst);
        Ok(MemoryDraft {
            title: "QA".into(),
            content: episode.content.clone(),
            tags: vec![],
            entities: vec![],
        })
    }
    async fn decide(
        &self,
        _: &str,
        _: u64,
        _: &[TranscriptEntry],
        _: &[String],
    ) -> CoreResult<AgentAction> {
        unreachable!("memory tests never run agent decisions")
    }
}
#[async_trait]
impl EmbeddingPort for Probes {
    async fn embed(&self, _: &str) -> CoreResult<Vec<f32>> {
        self.embeddings.fetch_add(1, Ordering::SeqCst);
        Ok(vec![1.0, 0.0])
    }
}

#[derive(Default)]
pub struct PausedVectors {
    pub entered: Notify,
    pub release: Notify,
}
#[async_trait]
impl VectorIndexPort for PausedVectors {
    async fn upsert(&self, _: &str, _: &str, _: &[f32]) -> CoreResult<()> {
        self.entered.notify_one();
        self.release.notified().await;
        Ok(())
    }
    async fn query(&self, _: &str, _: &[f32], _: usize) -> CoreResult<Vec<ScoredId>> {
        Ok(vec![])
    }
    async fn remove(&self, _: &str, _: &str) -> CoreResult<()> {
        Ok(())
    }
}
