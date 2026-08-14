use std::error::Error;

use bcs_db_api::{DbPlugin, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;

use super::*;

#[tokio::test]
async fn judge_resolution_is_authorized_revision_guarded_and_replayable()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    seed_judge_resolution(&db).await?;
    let store = WorkspaceAutonomyAttentionStore::new(&db, DbSqlFlavor::Sqlite);
    let resolution = judge_resolution("owner-1", "attention-judge-1", 0, "resolve-key-0001", 'a');

    let denied = store
        .resolve_judge_attention(&judge_resolution(
            "viewer-1",
            "attention-judge-1",
            0,
            "viewer-resolve-key",
            'b',
        ))
        .await;
    assert!(matches!(
        denied,
        Err(WorkspaceAutonomyAttentionStoreError::EditorAccessRequired)
    ));

    let wrong_source = store
        .resolve_judge_attention(&judge_resolution(
            "owner-1",
            "attention-dead-letter-1",
            0,
            "wrong-source-key-1",
            'c',
        ))
        .await;
    assert!(matches!(
        wrong_source,
        Err(WorkspaceAutonomyAttentionStoreError::Conflict)
    ));
    assert_eq!(scalar(&db, "workspace_mutation_receipts").await?, 0);

    let committed = store.resolve_judge_attention(&resolution).await?;
    assert_eq!(committed.committed_revision, 1);
    assert!(!committed.replayed);
    assert!(!committed.outbox_id.is_empty());
    assert!(!committed.receipt_id.is_empty());
    assert_eq!(scalar(&db, "workspace_mutation_receipts").await?, 1);
    assert_eq!(scalar(&db, "workspace_outbox").await?, 1);
    assert_eq!(authority_revision(&db).await?, 1);
    assert_eq!(
        attention_status(&db, "attention-judge-1").await?,
        "resolved"
    );

    let mut replay_request = resolution.clone();
    replay_request.resolved_at_ms = 9_999;
    let replay = store.resolve_judge_attention(&replay_request).await?;
    assert_eq!(replay.committed_revision, 1);
    assert!(replay.replayed);
    assert_eq!(replay.outbox_id, committed.outbox_id);
    assert_eq!(replay.receipt_id, committed.receipt_id);
    assert_eq!(scalar(&db, "workspace_mutation_receipts").await?, 1);
    assert_eq!(scalar(&db, "workspace_outbox").await?, 1);
    assert_eq!(authority_revision(&db).await?, 1);

    let idempotency_conflict = store
        .resolve_judge_attention(&judge_resolution(
            "owner-1",
            "attention-judge-2",
            1,
            "resolve-key-0001",
            'd',
        ))
        .await;
    assert!(matches!(
        idempotency_conflict,
        Err(WorkspaceAutonomyAttentionStoreError::IdempotencyConflict)
    ));

    let stale = store
        .resolve_judge_attention(&judge_resolution(
            "owner-1",
            "attention-judge-2",
            0,
            "stale-revision-key",
            'e',
        ))
        .await;
    assert!(matches!(
        stale,
        Err(WorkspaceAutonomyAttentionStoreError::Conflict)
    ));
    assert_eq!(attention_status(&db, "attention-judge-2").await?, "open");
    assert_eq!(scalar(&db, "workspace_mutation_receipts").await?, 1);
    assert_eq!(authority_revision(&db).await?, 1);

    let mut wrong_scope =
        judge_resolution("owner-1", "attention-judge-2", 1, "wrong-scope-key-1", 'f');
    wrong_scope.scope.project_id = "project-other".to_string();
    let wrong_scope = store.resolve_judge_attention(&wrong_scope).await;
    assert!(matches!(
        wrong_scope,
        Err(WorkspaceAutonomyAttentionStoreError::EditorAccessRequired)
    ));
    Ok(())
}

#[tokio::test]
async fn task_dispatch_retry_is_editor_authorized_exact_and_idempotent()
-> Result<(), Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    seed_task_dispatch_attention(&db).await?;
    let scope = WorkspaceAutonomyScope {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
    };
    let store = WorkspaceAutonomyAttentionStore::new(&db, DbSqlFlavor::Sqlite);

    let attentions = store.list_open(&scope).await?;
    assert_eq!(attentions.len(), 1);
    assert_eq!(attentions[0].source_kind, "task_dispatch_dead_letter");
    assert_eq!(attentions[0].root_task_id.as_deref(), Some("root-1"));

    let denied = store
        .retry_task_dispatch_dead_letter(
            &scope,
            "viewer-1",
            false,
            "task-dispatch:dispatch-1",
            2_000,
        )
        .await;
    assert!(matches!(
        denied,
        Err(WorkspaceAutonomyAttentionStoreError::EditorAccessRequired)
    ));

    store
        .retry_task_dispatch_dead_letter(
            &scope,
            "owner-1",
            false,
            "task-dispatch:dispatch-1",
            2_000,
        )
        .await?;
    let dispatch = db
        .query(DbStatement::new(
            "SELECT dispatch_id, delivery_request_id, status, attempt_count, \
             next_attempt_at_ms, lease_owner, lease_expires_at_ms, lease_generation, \
             last_error, delivered_at_ms FROM workspace_task_dispatch_outbox \
             WHERE dispatch_id = 'dispatch-1'",
        ))
        .await?;
    let dispatch = dispatch.first().ok_or("missing task dispatch row")?;
    assert_eq!(
        dispatch.get_string("dispatch_id")?.as_deref(),
        Some("dispatch-1")
    );
    assert_eq!(
        dispatch.get_string("delivery_request_id")?.as_deref(),
        Some("delivery-1")
    );
    assert_eq!(dispatch.get_string("status")?.as_deref(), Some("pending"));
    assert_eq!(dispatch.get_i64("attempt_count")?, Some(0));
    assert_eq!(dispatch.get_i64("next_attempt_at_ms")?, Some(2_000));
    assert_eq!(dispatch.get_i64("lease_generation")?, Some(7));
    assert_eq!(dispatch.get_string("lease_owner")?, None);
    assert_eq!(dispatch.get_i64("lease_expires_at_ms")?, None);
    assert_eq!(dispatch.get_string("last_error")?, None);
    assert_eq!(dispatch.get_i64("delivered_at_ms")?, None);

    let attention = db
        .query(DbStatement::new(
            "SELECT status, resolved_at_ms, resolved_by_actor_id \
             FROM workspace_autonomy_attentions \
             WHERE attention_id = 'task-dispatch:dispatch-1'",
        ))
        .await?;
    let attention = attention.first().ok_or("missing autonomy attention row")?;
    assert_eq!(attention.get_string("status")?.as_deref(), Some("resolved"));
    assert_eq!(attention.get_i64("resolved_at_ms")?, Some(2_000));
    assert_eq!(
        attention.get_string("resolved_by_actor_id")?.as_deref(),
        Some("owner-1")
    );

    let duplicate = store
        .retry_task_dispatch_dead_letter(
            &scope,
            "owner-1",
            false,
            "task-dispatch:dispatch-1",
            3_000,
        )
        .await;
    assert!(matches!(
        duplicate,
        Err(WorkspaceAutonomyAttentionStoreError::Conflict)
    ));
    Ok(())
}

async fn seed_task_dispatch_attention(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        "CREATE TABLE workspace_profiles (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, \
         workspace_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, \
         workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_autonomy_attentions (attention_id TEXT PRIMARY KEY, \
         tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, \
         root_task_id TEXT, source_kind TEXT NOT NULL, source_id TEXT NOT NULL, reason TEXT NOT NULL, \
         status TEXT NOT NULL, created_at_ms INTEGER NOT NULL, resolved_at_ms INTEGER, \
         resolved_by_actor_id TEXT)",
        "CREATE TABLE workspace_task_dispatch_outbox (dispatch_id TEXT PRIMARY KEY, \
         tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, \
         delivery_request_id TEXT NOT NULL, status TEXT NOT NULL, attempt_count INTEGER NOT NULL, \
         next_attempt_at_ms INTEGER NOT NULL, lease_owner TEXT, lease_expires_at_ms INTEGER, \
         lease_generation INTEGER NOT NULL, last_error TEXT, delivered_at_ms INTEGER)",
        "INSERT INTO workspace_profiles VALUES \
         ('tenant-1', 'project-1', 'workspace-1', NULL)",
        "INSERT INTO workspace_members VALUES \
         ('tenant-1', 'project-1', 'workspace-1', 'owner-1', 'owner')",
        "INSERT INTO workspace_members VALUES \
         ('tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_task_dispatch_outbox VALUES \
         ('dispatch-1', 'tenant-1', 'project-1', 'workspace-1', 'delivery-1', 'dead_letter', \
         8, 1000, NULL, NULL, 7, 'provider unavailable', NULL)",
        "INSERT INTO workspace_autonomy_attentions VALUES \
         ('task-dispatch:dispatch-1', 'tenant-1', 'project-1', 'workspace-1', 'root-1', \
         'task_dispatch_dead_letter', 'dispatch-1', 'provider unavailable', 'open', 1000, \
         NULL, NULL)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(())
}

fn judge_resolution(
    actor_id: &str,
    attention_id: &str,
    expected_revision: u64,
    idempotency_key: &str,
    hash_character: char,
) -> WorkspaceAutonomyAttentionResolution {
    WorkspaceAutonomyAttentionResolution {
        scope: WorkspaceAutonomyScope {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
        },
        actor_id: actor_id.to_string(),
        actor_is_superuser: false,
        attention_id: attention_id.to_string(),
        expected_revision,
        idempotency_key: idempotency_key.to_string(),
        request_hash: hash_character.to_string().repeat(64),
        resolved_at_ms: 2_000,
    }
}

async fn seed_judge_resolution(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    for statement in [
        "CREATE TABLE workspace_profiles (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, \
         workspace_id TEXT NOT NULL, deleted_at TEXT)",
        "CREATE TABLE workspace_members (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, \
         workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT \
         NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL)",
        "CREATE TABLE workspace_autonomy_attentions (attention_id TEXT PRIMARY KEY, tenant_id \
         TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, root_task_id TEXT, \
         source_kind TEXT NOT NULL, source_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT \
         NULL, created_at_ms INTEGER NOT NULL, resolved_at_ms INTEGER, resolved_by_actor_id TEXT)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT \
         NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, \
         contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, \
         idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT \
         NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT DEFAULT \
         CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, \
         project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, \
         aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, \
         event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, \
         correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), \
         UNIQUE(workspace_id, stream_name, event_sequence))",
        "INSERT INTO workspace_profiles VALUES ('tenant-1', 'project-1', 'workspace-1', NULL)",
        "INSERT INTO workspace_members VALUES \
         ('tenant-1', 'project-1', 'workspace-1', 'owner-1', 'owner')",
        "INSERT INTO workspace_members VALUES \
         ('tenant-1', 'project-1', 'workspace-1', 'viewer-1', 'viewer')",
        "INSERT INTO workspace_authorities VALUES \
         ('workspace-1', 'tenant-1', 'project-1', 0, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_autonomy_attentions VALUES \
         ('attention-judge-1', 'tenant-1', 'project-1', 'workspace-1', 'root-1', 'judge_block', \
         'audit-1', 'editor review required', 'open', 1, NULL, NULL)",
        "INSERT INTO workspace_autonomy_attentions VALUES \
         ('attention-judge-2', 'tenant-1', 'project-1', 'workspace-1', 'root-2', 'judge_escalate', \
         'audit-2', 'editor escalation required', 'open', 2, NULL, NULL)",
        "INSERT INTO workspace_autonomy_attentions VALUES \
         ('attention-dead-letter-1', 'tenant-1', 'project-1', 'workspace-1', 'root-3', \
         'progression_dead_letter', 'progression-1', 'delivery failed', 'open', 3, NULL, NULL)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(())
}

async fn scalar(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let statement = match table {
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts"
        }
        "workspace_outbox" => "SELECT COUNT(*) AS value FROM workspace_outbox",
        _ => return Err("unsupported scalar table".into()),
    };
    Ok(db
        .query(DbStatement::new(statement))
        .await?
        .first()
        .ok_or("missing scalar row")?
        .get_i64("value")?
        .ok_or("missing scalar value")?)
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    Ok(db
        .query(DbStatement::new(
            "SELECT revision AS value FROM workspace_authorities \
             WHERE workspace_id = 'workspace-1'",
        ))
        .await?
        .first()
        .ok_or("missing authority row")?
        .get_i64("value")?
        .ok_or("missing authority revision")?)
}

async fn attention_status(db: &dyn DbPlugin, attention_id: &str) -> Result<String, Box<dyn Error>> {
    Ok(db
        .query(
            DbStatementBuilder::new(DbSqlFlavor::Sqlite)
                .push_static(
                    "SELECT status FROM workspace_autonomy_attentions WHERE attention_id = ",
                )
                .bind(attention_id)
                .build(),
        )
        .await?
        .first()
        .ok_or("missing attention row")?
        .get_string("status")?
        .ok_or("missing attention status")?)
}
