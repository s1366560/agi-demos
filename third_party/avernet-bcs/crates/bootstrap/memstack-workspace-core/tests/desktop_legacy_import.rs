use std::error::Error;

use bcs_db_api::{DbPlugin, DbStatement, db_get_column};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::desktop_legacy_import::import_legacy_workspace_snapshot;
use memstack_workspace_core::desktop_schema::run_desktop_workspace_schema_migrations;
use serde_json::{Value, json};
use sha2::{Digest as _, Sha256};
use tempfile::TempDir;

type TestResult = Result<(), Box<dyn Error>>;

#[tokio::test]
async fn imports_legacy_workspaces_and_messages_without_reemitting_history() -> TestResult {
    let fixture = Fixture::new().await?;

    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;

    assert_imported_contract(&fixture.db).await?;
    assert_eq!(count(&fixture.db, "workspace_outbox").await?, 0);
    assert_eq!(
        count(&fixture.db, "workspace_message_delivery_outbox").await?,
        0
    );
    Ok(())
}

#[tokio::test]
async fn repeated_import_is_idempotent_and_reverifies_every_target() -> TestResult {
    let fixture = Fixture::new().await?;

    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;
    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;

    assert_imported_contract(&fixture.db).await?;
    assert_eq!(count(&fixture.db, "workspace_migration_ledger").await?, 4);
    Ok(())
}

#[tokio::test]
async fn autonomous_import_ensures_and_repairs_one_bootstrap_without_history_outbox() -> TestResult
{
    let directory = TempDir::new()?;
    let snapshot_path = directory.path().join("autonomous-legacy.json");
    let (snapshot, snapshot_hash) = autonomous_snapshot();
    std::fs::write(&snapshot_path, snapshot)?;
    let db = LocalSqliteDbPlugin::new()?;
    bcs::migrations::run_sqlite_migrations(&db).await?;
    run_desktop_workspace_schema_migrations(&db).await?;

    import_legacy_workspace_snapshot(&db, &snapshot_path, &snapshot_hash).await?;
    assert_eq!(count(&db, "workspace_autonomy_bootstrap_outbox").await?, 1);
    assert_eq!(count(&db, "workspace_outbox").await?, 0);
    assert_eq!(
        scalar_string(
            &db,
            "SELECT actor_id AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        "local-user"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT objective_title AS value FROM workspace_autonomy_bootstrap_outbox"
        )
        .await?,
        "Autonomous Legacy Workspace"
    );

    db.execute(DbStatement::new(
        "DELETE FROM workspace_autonomy_bootstrap_outbox",
    ))
    .await?;
    import_legacy_workspace_snapshot(&db, &snapshot_path, &snapshot_hash).await?;
    assert_eq!(count(&db, "workspace_autonomy_bootstrap_outbox").await?, 1);
    Ok(())
}

#[tokio::test]
async fn repeated_import_allows_authoritative_project_membership_metadata_refresh() -> TestResult {
    let fixture = Fixture::new().await?;
    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;
    fixture
        .db
        .execute(DbStatement::new(
            "UPDATE project_principal_memberships SET \
             source_membership_id = 'desktop-sidecar:refreshed', \
             identity_authority = 'desktop-sidecar', \
             source_updated_at = '2026-08-12T09:44:46Z' \
             WHERE tenant_id = 'tenant-a' AND project_id = 'project-a' \
             AND user_id = 'local-user'",
        ))
        .await?;

    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;

    assert_imported_contract(&fixture.db).await?;
    assert_eq!(count(&fixture.db, "workspace_migration_ledger").await?, 4);
    Ok(())
}

#[tokio::test]
async fn repeated_import_preserves_workspace_core_changes_after_cutover() -> TestResult {
    let fixture = Fixture::new().await?;
    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;
    fixture
        .db
        .execute(DbStatement::new(
            "UPDATE workspace_profiles SET name = 'Workspace A renamed', \
             updated_at = '2026-08-13T09:00:00Z' WHERE workspace_id = 'workspace-a'",
        ))
        .await?;
    fixture
        .db
        .execute(DbStatement::new(
            "UPDATE workspace_authorities SET revision = 7 WHERE workspace_id = 'workspace-a'",
        ))
        .await?;
    fixture
        .db
        .execute(DbStatement::new(
            "UPDATE bcs_group_sessions SET current_msg_seq = 3 \
             WHERE group_id = 'group-workspace-a' AND env = 'memstack'",
        ))
        .await?;

    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;

    assert_eq!(
        scalar_string(
            &fixture.db,
            "SELECT name AS value FROM workspace_profiles WHERE workspace_id = 'workspace-a'",
        )
        .await?,
        "Workspace A renamed"
    );
    assert_eq!(
        scalar_i64(
            &fixture.db,
            "SELECT revision AS value FROM workspace_authorities \
             WHERE workspace_id = 'workspace-a'",
        )
        .await?,
        7
    );
    assert_eq!(
        scalar_i64(
            &fixture.db,
            "SELECT current_msg_seq AS value FROM bcs_group_sessions \
             WHERE group_id = 'group-workspace-a' AND env = 'memstack'",
        )
        .await?,
        3
    );
    Ok(())
}

#[tokio::test]
async fn target_content_conflict_fails_closed() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture
        .db
        .execute(DbStatement::new(
            "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, \
             name, created_by) VALUES ('workspace-a', 'tenant-a', 'project-a', \
             'group-workspace-a', 'conflicting', 'local-user')",
        ))
        .await?;

    let error = require_error(
        import_legacy_workspace_snapshot(
            &fixture.db,
            &fixture.snapshot_path,
            &fixture.snapshot_hash,
        )
        .await,
        "target collision must fail closed",
    )?;

    assert!(error.to_string().contains("target collision"));
    assert_eq!(count(&fixture.db, "workspace_migration_ledger").await?, 0);
    Ok(())
}

#[tokio::test]
async fn transaction_failure_rolls_back_all_workspace_rows() -> TestResult {
    let fixture = Fixture::new().await?;
    fixture
        .db
        .execute(DbStatement::new(
            "CREATE TRIGGER reject_legacy_message BEFORE INSERT ON bcs_messages \
             BEGIN SELECT RAISE(ABORT, 'injected message failure'); END",
        ))
        .await?;

    require_error(
        import_legacy_workspace_snapshot(
            &fixture.db,
            &fixture.snapshot_path,
            &fixture.snapshot_hash,
        )
        .await,
        "injected transaction failure must propagate",
    )?;

    assert_eq!(count(&fixture.db, "workspace_profiles").await?, 0);
    assert_eq!(count(&fixture.db, "bcs_groups").await?, 0);
    assert_eq!(count(&fixture.db, "workspace_migration_ledger").await?, 0);
    Ok(())
}

#[tokio::test]
async fn file_database_reopens_with_imported_authority_intact() -> TestResult {
    let directory = TempDir::new()?;
    let database_path = directory.path().join("avernet-workspace.db");
    let snapshot_path = directory.path().join("legacy.json");
    let (snapshot, snapshot_hash) = snapshot();
    std::fs::write(&snapshot_path, snapshot)?;
    {
        let db = LocalSqliteDbPlugin::new_file(&database_path)?;
        bcs::migrations::run_sqlite_migrations(&db).await?;
        run_desktop_workspace_schema_migrations(&db).await?;
        import_legacy_workspace_snapshot(&db, &snapshot_path, &snapshot_hash).await?;
    }

    let reopened = LocalSqliteDbPlugin::new_file(&database_path)?;
    assert_imported_contract(&reopened).await?;
    Ok(())
}

#[tokio::test]
async fn rejects_snapshot_and_record_hash_mismatches() -> TestResult {
    let fixture = Fixture::new().await?;
    let wrong_snapshot_hash = "0".repeat(64);
    let overall_error = require_error(
        import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &wrong_snapshot_hash)
            .await,
        "overall hash mismatch must fail closed",
    )?;
    assert!(
        overall_error
            .to_string()
            .contains("snapshot SHA-256 mismatch")
    );

    let mut value: Value = serde_json::from_slice(&std::fs::read(&fixture.snapshot_path)?)?;
    value["workspaces"][0]["sourceHash"] = Value::String("0".repeat(64));
    let encoded = serde_json::to_vec(&value)?;
    std::fs::write(&fixture.snapshot_path, &encoded)?;
    let record_error = require_error(
        import_legacy_workspace_snapshot(
            &fixture.db,
            &fixture.snapshot_path,
            &hex_sha256(&encoded),
        )
        .await,
        "record hash mismatch must fail closed",
    )?;
    assert!(
        record_error
            .to_string()
            .contains("record source hash mismatch")
    );
    Ok(())
}

#[tokio::test]
async fn completed_ledger_with_missing_target_fails_closed() -> TestResult {
    let fixture = Fixture::new().await?;
    import_legacy_workspace_snapshot(&fixture.db, &fixture.snapshot_path, &fixture.snapshot_hash)
        .await?;
    fixture
        .db
        .execute(DbStatement::new(
            "DELETE FROM workspace_message_correlations WHERE legacy_message_id = 'message-a1'",
        ))
        .await?;

    let error = require_error(
        import_legacy_workspace_snapshot(
            &fixture.db,
            &fixture.snapshot_path,
            &fixture.snapshot_hash,
        )
        .await,
        "missing target behind verified ledger must fail closed",
    )?;

    assert!(
        error
            .to_string()
            .contains("verified import target mismatch")
    );
    Ok(())
}

struct Fixture {
    _directory: TempDir,
    db: LocalSqliteDbPlugin,
    snapshot_path: std::path::PathBuf,
    snapshot_hash: String,
}

impl Fixture {
    async fn new() -> Result<Self, Box<dyn Error>> {
        let directory = TempDir::new()?;
        let snapshot_path = directory.path().join("legacy.json");
        let (snapshot, snapshot_hash) = snapshot();
        std::fs::write(&snapshot_path, snapshot)?;
        let db = LocalSqliteDbPlugin::new()?;
        bcs::migrations::run_sqlite_migrations(&db).await?;
        run_desktop_workspace_schema_migrations(&db).await?;
        Ok(Self {
            _directory: directory,
            db,
            snapshot_path,
            snapshot_hash,
        })
    }
}

fn snapshot() -> (Vec<u8>, String) {
    let mut workspaces = vec![workspace_record(
        "workspace-a",
        "tenant-a",
        "project-a",
        "Workspace A",
        "2026-07-13T06:14:23.455413+00:00",
    )];
    workspaces.push(workspace_record(
        "workspace-b",
        "tenant-a",
        "project-a",
        "Workspace B",
        "2026-07-14T06:14:23.455413+00:00",
    ));
    let messages = vec![
        message_record(
            "message-a1",
            "workspace-a",
            1,
            "first message",
            "2026-07-14T03:47:29.661319+00:00",
            Some("conversation-a"),
        ),
        message_record(
            "message-a2",
            "workspace-a",
            2,
            "second message",
            "2026-07-14T03:48:29.123456+00:00",
            None,
        ),
    ];
    let snapshot = json!({
        "schemaVersion": 1,
        "source": "desktop-session-store",
        "workspaceCount": workspaces.len(),
        "messageCount": messages.len(),
        "workspaces": workspaces,
        "messages": messages,
    });
    let encoded = serde_json::to_vec(&snapshot)
        .unwrap_or_else(|error| panic!("serialize test snapshot: {error}"));
    let hash = hex_sha256(&encoded);
    (encoded, hash)
}

fn autonomous_snapshot() -> (Vec<u8>, String) {
    let mut workspace = workspace_record(
        "workspace-autonomous",
        "tenant-a",
        "project-a",
        "Autonomous Legacy Workspace",
        "2026-07-14T06:14:23.455413+00:00",
    );
    workspace["value"]["collaboration_mode"] = Value::String("autonomous".to_string());
    let hash_value = json!({
        "id": "workspace-autonomous",
        "project_id": "project-a",
        "value": workspace["value"].clone(),
    });
    workspace["sourceHash"] = Value::String(source_hash(&hash_value));
    let snapshot = json!({
        "schemaVersion": 1,
        "source": "desktop-session-store",
        "workspaceCount": 1,
        "messageCount": 0,
        "workspaces": [workspace],
        "messages": [],
    });
    let encoded = serde_json::to_vec(&snapshot)
        .unwrap_or_else(|error| panic!("serialize autonomous test snapshot: {error}"));
    let hash = hex_sha256(&encoded);
    (encoded, hash)
}

fn workspace_record(
    id: &str,
    tenant_id: &str,
    project_id: &str,
    name: &str,
    created_at: &str,
) -> Value {
    let value = json!({
        "id": id,
        "tenant_id": tenant_id,
        "project_id": project_id,
        "name": name,
        "description": format!("{name} description"),
        "status": "open",
        "created_at": created_at,
        "updated_at": created_at,
        "is_archived": false,
        "collaboration_mode": "team",
        "use_case": "development",
        "metadata": {"preserved": true},
    });
    let hash_value = json!({"id": id, "project_id": project_id, "value": value});
    json!({
        "id": id,
        "projectId": project_id,
        "value": value,
        "sourceHash": source_hash(&hash_value),
    })
}

fn message_record(
    id: &str,
    workspace_id: &str,
    position: i64,
    content: &str,
    created_at: &str,
    conversation_id: Option<&str>,
) -> Value {
    let value = json!({
        "id": id,
        "workspace_id": workspace_id,
        "sender_id": "local-user",
        "sender_type": "human",
        "content": content,
        "created_at": created_at,
        "parent_message_id": null,
        "mentions": [],
        "metadata": conversation_id.map_or_else(
            || json!({"preserved": true}),
            |value| json!({"conversation_id": value, "preserved": true}),
        ),
    });
    let hash_value = json!({
        "id": id,
        "workspace_id": workspace_id,
        "position": position,
        "value": value,
    });
    json!({
        "id": id,
        "workspaceId": workspace_id,
        "position": position,
        "value": value,
        "sourceHash": source_hash(&hash_value),
    })
}

async fn assert_imported_contract(db: &dyn DbPlugin) -> TestResult {
    assert_eq!(count(db, "workspace_profiles").await?, 2);
    assert_eq!(count(db, "bcs_groups").await?, 2);
    assert_eq!(count(db, "workspace_members").await?, 2);
    assert_eq!(count(db, "workspace_principal_identities").await?, 2);
    assert_eq!(count(db, "project_principal_memberships").await?, 1);
    assert_eq!(count(db, "bcs_group_sessions").await?, 2);
    assert_eq!(count(db, "bcs_messages").await?, 2);
    assert_eq!(count(db, "workspace_message_correlations").await?, 2);

    let rows = db
        .query(DbStatement::new(
            "SELECT message_id, session_seq, content, created_at, metadata_json, source_hash \
             FROM bcs_messages WHERE workspace_id = 'workspace-a' ORDER BY session_seq",
        ))
        .await?;
    assert_eq!(
        db_get_column::<String>(&rows[0], "message_id")?,
        "message-a1"
    );
    assert_eq!(db_get_column::<i64>(&rows[0], "session_seq")?, 1);
    assert_eq!(
        db_get_column::<String>(&rows[0], "content")?,
        "\"first message\""
    );
    let expected_created_at =
        chrono::DateTime::parse_from_rfc3339("2026-07-14T03:47:29.661319+00:00")?
            .timestamp_millis();
    assert_eq!(
        db_get_column::<i64>(&rows[0], "created_at")?,
        expected_created_at
    );
    let metadata: Value =
        serde_json::from_str(&db_get_column::<String>(&rows[0], "metadata_json")?)?;
    assert_eq!(metadata["conversation_id"], "conversation-a");
    assert_eq!(
        metadata["legacy_desktop"]["created_at"],
        "2026-07-14T03:47:29.661319+00:00"
    );
    assert_eq!(metadata["legacy_desktop"]["position"], 1);
    assert_eq!(
        metadata["legacy_desktop"]["source_hash"],
        db_get_column::<String>(&rows[0], "source_hash")?
    );
    Ok(())
}

async fn count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::new(format!(
            "SELECT COUNT(*) AS count FROM {table}"
        )))
        .await?;
    Ok(db_get_column::<i64>(&rows[0], "count")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(db_get_column::<String>(&rows[0], "value")?)
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(db_get_column::<i64>(&rows[0], "value")?)
}

fn source_hash(value: &Value) -> String {
    let canonical = canonical_json(value);
    let encoded = serde_json::to_vec(&canonical)
        .unwrap_or_else(|error| panic!("serialize canonical record: {error}"));
    hex_sha256(&encoded)
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Object(object) => Value::Object(
            object
                .iter()
                .map(|(key, value)| (key.clone(), canonical_json(value)))
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(canonical_json).collect()),
        _ => value.clone(),
    }
}

fn hex_sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn require_error<T, E>(result: Result<T, E>, message: &str) -> Result<E, Box<dyn Error>>
where
    E: Error + 'static,
{
    match result {
        Err(error) => Ok(error),
        Ok(_) => Err(message.into()),
    }
}
