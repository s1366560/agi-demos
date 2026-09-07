use super::*;
use agistack_adapters_postgres::PgMemoryRepository;
use agistack_core::model::{GraphExport, GraphStats, GraphStatsScope, Relationship, Subgraph};
use agistack_core::ports::{CoreError, CoreResult, GraphStore};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;
use tokio::sync::Notify;

mod support {
    include!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../crates/adapters-postgres/tests/memory_legacy_admission/mod.rs"
    ));
}

#[derive(Default)]
struct PausedGraph {
    inner: InMemoryGraphStore,
    entered: Notify,
    release: Notify,
    fail: AtomicBool,
    tenant: Mutex<Option<String>>,
}
#[async_trait::async_trait]
impl GraphStore for PausedGraph {
    async fn upsert_entity(&self, entity: GraphEntity) -> CoreResult<()> {
        *self.tenant.lock().unwrap() = entity.tenant_id.clone();
        self.entered.notify_one();
        self.release.notified().await;
        if self.fail.load(Ordering::SeqCst) {
            return Err(CoreError::Graph("injected graph failure".into()));
        }
        self.inner.upsert_entity(entity).await
    }
    async fn upsert_relationship(&self, rel: Relationship) -> CoreResult<()> {
        self.inner.upsert_relationship(rel).await
    }
    async fn delete_entity(&self, p: &str, id: &str) -> CoreResult<()> {
        self.inner.delete_entity(p, id).await
    }
    async fn delete_relationship(&self, p: &str, id: &str) -> CoreResult<()> {
        self.inner.delete_relationship(p, id).await
    }
    async fn get_entity(&self, p: &str, id: &str) -> CoreResult<Option<GraphEntity>> {
        self.inner.get_entity(p, id).await
    }
    async fn neighbors(&self, p: &str, id: &str) -> CoreResult<Vec<GraphEntity>> {
        self.inner.neighbors(p, id).await
    }
    async fn subgraph(&self, p: &str, id: &str, depth: usize) -> CoreResult<Subgraph> {
        self.inner.subgraph(p, id, depth).await
    }
    async fn project_slice(&self, p: &str) -> CoreResult<(Vec<GraphEntity>, Vec<Relationship>)> {
        self.inner.project_slice(p).await
    }
    async fn search_entities(
        &self,
        p: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<GraphEntity>> {
        self.inner.search_entities(p, query, limit).await
    }
    async fn stats(&self, scope: GraphStatsScope) -> CoreResult<GraphStats> {
        self.inner.stats(scope).await
    }
    async fn export(&self, scope: GraphStatsScope) -> CoreResult<GraphExport> {
        self.inner.export(scope).await
    }
    async fn count_episodes_older_than(
        &self,
        scope: GraphStatsScope,
        cutoff: i64,
    ) -> CoreResult<usize> {
        self.inner.count_episodes_older_than(scope, cutoff).await
    }
    async fn delete_episodes_older_than(
        &self,
        scope: GraphStatsScope,
        cutoff: i64,
    ) -> CoreResult<usize> {
        self.inner.delete_episodes_older_than(scope, cutoff).await
    }
}

async fn app_for(pool: &sqlx::PgPool, graph: Arc<PausedGraph>) -> AppState {
    let mut app = test_state();
    let probes = Arc::new(support::Probes::default());
    app.memory = Arc::new(MemoryService::new(
        Arc::new(PgMemoryRepository::new(pool.clone()).await.unwrap()),
        probes.clone(),
        probes,
        Arc::new(support::FixedClock),
    ));
    app.graph = graph;
    app
}

fn identity() -> Identity {
    Identity {
        user_id: "actor".into(),
        _api_key_id: "qa".into(),
    }
}

#[tokio::test]
async fn bootstrap_waits_for_api_graph_and_uses_canonical_tenant() {
    let Some(pool) = support::test_pool().await else {
        return;
    };
    let project = support::seed_project(&pool, "api-graph").await;
    let graph = Arc::new(PausedGraph::default());
    let app = app_for(&pool, graph.clone()).await;
    let admission = app.memory.clone();
    let writing_project = project.clone();
    let writer = tokio::spawn(async move {
        create_episode(
            State(app),
            Extension(identity()),
            Json(EpisodeCreate {
                name: Some("QA".into()),
                content: "content".into(),
                project_id: Some(writing_project),
            }),
        )
        .await
    });
    tokio::time::timeout(Duration::from_secs(3), graph.entered.notified())
        .await
        .unwrap();
    assert_eq!(graph.tenant.lock().unwrap().as_deref(), Some("tenant"));
    let bootstrap = support::start_bootstrap(&project).await;
    tokio::time::sleep(Duration::from_secs(1)).await;
    let crossed = bootstrap.is_finished();
    graph.release.notify_one();
    assert_eq!(
        writer
            .await
            .unwrap()
            .map_err(|error| error.detail)
            .unwrap()
            .status(),
        StatusCode::ACCEPTED
    );
    bootstrap.await.unwrap();
    assert!(!crossed, "bootstrap must wait through graph projection");
    admission.close_write_admission().await;
    pool.close().await;
}

#[tokio::test]
async fn graph_failure_keeps_saved_sql_and_releases_the_lease() {
    let Some(pool) = support::test_pool().await else {
        return;
    };
    let project = support::seed_project(&pool, "api-failure").await;
    let graph = Arc::new(PausedGraph::default());
    graph.fail.store(true, Ordering::SeqCst);
    graph.release.notify_one();
    let app = app_for(&pool, graph).await;
    let response = create_episode(
        State(app.clone()),
        Extension(identity()),
        Json(EpisodeCreate {
            name: None,
            content: "content".into(),
            project_id: Some(project.clone()),
        }),
    )
    .await
    .map_err(|error| error.detail)
    .unwrap();
    assert_eq!(response.status(), StatusCode::ACCEPTED);
    assert_eq!(app.memory.count(&project, None).await.unwrap(), 1);
    tokio::time::timeout(Duration::from_secs(5), async {
        support::start_bootstrap(&project).await.await.unwrap()
    })
    .await
    .unwrap();
    let rejection = create_episode(
        State(app.clone()),
        Extension(identity()),
        Json(EpisodeCreate {
            name: None,
            content: "content".into(),
            project_id: Some(project),
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(rejection.status, StatusCode::CONFLICT);
    assert_eq!(rejection.detail, "knowledge_sync_write_context_required");
    app.memory.close_write_admission().await;
    pool.close().await;
}

#[tokio::test]
async fn cancelling_api_graph_releases_admission_without_rolling_back_saved_sql() {
    let Some(pool) = support::test_pool().await else {
        return;
    };
    let project = support::seed_project(&pool, "api-cancel").await;
    let graph = Arc::new(PausedGraph::default());
    let app = app_for(&pool, graph.clone()).await;
    let admission = app.memory.clone();
    let writing_project = project.clone();
    let writer = tokio::spawn(async move {
        create_episode(
            State(app),
            Extension(identity()),
            Json(EpisodeCreate {
                name: None,
                content: "cancel".into(),
                project_id: Some(writing_project),
            }),
        )
        .await
    });
    tokio::time::timeout(Duration::from_secs(3), graph.entered.notified())
        .await
        .unwrap();
    let bootstrap = support::start_bootstrap(&project).await;
    tokio::time::sleep(Duration::from_secs(1)).await;
    assert!(!bootstrap.is_finished());
    writer.abort();
    assert!(matches!(writer.await, Err(error) if error.is_cancelled()));
    tokio::time::timeout(Duration::from_secs(5), bootstrap)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(admission.count(&project, None).await.unwrap(), 1);
    admission.close_write_admission().await;
    pool.close().await;
}

#[test]
fn admission_errors_have_stable_http_status_and_code() {
    use agistack_core::ports::legacy_memory::LegacyMemoryWriteError as E;
    for (reason, status) in [
        (E::ContextRequired, StatusCode::CONFLICT),
        (E::Conflict, StatusCode::CONFLICT),
        (E::Forbidden, StatusCode::FORBIDDEN),
        (E::NotFound, StatusCode::NOT_FOUND),
        (E::FenceMissing, StatusCode::SERVICE_UNAVAILABLE),
        (E::Unavailable, StatusCode::SERVICE_UNAVAILABLE),
    ] {
        let mapped = memory_write_error(reason.into());
        assert_eq!(mapped.status, status);
        assert_eq!(mapped.detail, reason.to_string());
    }
}
