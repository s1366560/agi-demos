use super::support::*;

static WORKSPACE_INTEGRATION_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[path = "workspace/access.rs"]
mod access;
#[path = "workspace/outbox.rs"]
mod outbox;
#[path = "workspace/plan_pipeline.rs"]
mod plan_pipeline;
#[path = "workspace/seed.rs"]
mod seed;
#[path = "workspace/task_attempts.rs"]
mod task_attempts;
#[path = "workspace/topology_blackboard.rs"]
mod topology_blackboard;

#[tokio::test]
async fn workspace_repository_roundtrips_against_shared_schema() {
    let _guard = WORKSPACE_INTEGRATION_LOCK.lock().await;
    let Some(pool) = pool_or_skip("workspace_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;

    seed::reset_and_seed_workspace_rows(&pool).await;

    let repo = PgWorkspaceRepository::new(pool.clone());
    let created_at = ts(2026, 1, 2, 3, 4, 5);
    access::roundtrip_workspace_access(&pool, &repo, created_at).await;
    task_attempts::roundtrip_tasks_and_attempts(&repo, created_at).await;
    topology_blackboard::roundtrip_topology_blackboard(&pool, &repo, created_at).await;
    plan_pipeline::roundtrip_plan_pipeline(&repo, created_at).await;
    outbox::roundtrip_plan_outbox(&repo, created_at).await;
}

#[tokio::test]
async fn workspace_roster_repository_roundtrips_against_shared_schema() {
    let _guard = WORKSPACE_INTEGRATION_LOCK.lock().await;
    let Some(pool) =
        pool_or_skip("workspace_roster_repository_roundtrips_against_shared_schema").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    seed::reset_and_seed_workspace_rows(&pool).await;

    let repo = PgWorkspaceRepository::new(pool.clone());
    access::roundtrip_workspace_access(&pool, &repo, ts(2026, 1, 2, 3, 4, 5)).await;
}
