use super::support::*;
use agistack_adapters_postgres::{
    ArtifactContentConflictRecord, ArtifactContentReceiptRecord, ArtifactContentSaveCommand,
    ArtifactContentSaveResult,
};

#[tokio::test]
async fn artifact_content_v2_save_is_conditional_and_idempotent() {
    let Some(pool) = pool_or_skip("artifact_content_v2_save_is_conditional_and_idempotent").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    ensure_artifact_content_v2_schema(&pool).await;
    clean_artifact_rows(&pool).await;
    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_v2",
            project_id: "artifact_project",
            status: "ready",
            category: "document",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 1, 0, 0, 0),
        },
    )
    .await;

    let repo = PgArtifactRepository::new(pool.clone());
    let initialized = repo
        .initialize_content_hash(
            "artifact_v2",
            1,
            "sha256:19b25856e1c150ca834cffc8b59b23adbd0ec0389e58eb22b3b64768098d002b",
        )
        .await
        .expect("initialize hash")
        .expect("artifact exists");
    assert_eq!(initialized.content_revision, 1);

    let command = ArtifactContentSaveCommand {
        artifact_id: "artifact_v2",
        project_id: "artifact_project",
        tenant_id: "artifact_tenant",
        expected_revision: 1,
        idempotency_key: "artifact-v2:save:0001",
        request_hash:
            "sha256:99009b05d03d76249c37a09ec4c3e7f9a3096173f094e0421736197525515a21",
        content_hash:
            "sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777",
        object_key:
            "artifacts/artifact_tenant/artifact_project/artifact_v2/versions/r2-27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777",
        size_bytes: 7,
    };
    let first = repo
        .save_content_v2(command)
        .await
        .expect("first save succeeds");
    let replay = repo
        .save_content_v2(command)
        .await
        .expect("same payload replays");

    assert_eq!(
        first,
        ArtifactContentSaveResult::Saved(ArtifactContentReceiptRecord {
            artifact_id: "artifact_v2".to_string(),
            revision: 2,
            content_hash: "sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777"
                .to_string(),
            duplicate: false,
        })
    );
    assert_eq!(
        replay,
        ArtifactContentSaveResult::Saved(ArtifactContentReceiptRecord {
            artifact_id: "artifact_v2".to_string(),
            revision: 2,
            content_hash: "sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777"
                .to_string(),
            duplicate: true,
        })
    );

    let key_conflict = repo
        .save_content_v2(ArtifactContentSaveCommand {
            request_hash: "sha256:ae1a1b87e7fc8dfaa620631e73c67257ff1288f515179dd6a2b1c1d319d9a8ff",
            content_hash: "sha256:9d6f965ac832e40a5df6c06afe983e3b449c07b843ff51ce76204de05c690d11",
            ..command
        })
        .await
        .expect("idempotency conflict is an authority result");
    assert_eq!(
        key_conflict,
        ArtifactContentSaveResult::Conflict(ArtifactContentConflictRecord {
            reason_code: "artifact_content_idempotency_conflict".to_string(),
            server_revision: 2,
            server_content_hash:
                "sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777"
                    .to_string(),
        })
    );

    let revision_conflict = repo
        .save_content_v2(ArtifactContentSaveCommand {
            idempotency_key: "artifact-v2:save:0002",
            request_hash: "sha256:99009b05d03d76249c37a09ec4c3e7f9a3096173f094e0421736197525515a21",
            ..command
        })
        .await
        .expect("revision conflict is an authority result");
    assert_eq!(
        revision_conflict,
        ArtifactContentSaveResult::Conflict(ArtifactContentConflictRecord {
            reason_code: "artifact_content_revision_conflict".to_string(),
            server_revision: 2,
            server_content_hash:
                "sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777"
                    .to_string(),
        })
    );

    let stored = repo
        .get("artifact_v2")
        .await
        .expect("get updated artifact")
        .expect("artifact exists");
    assert_eq!(stored.content_revision, 2);
    assert_eq!(
        stored.content_hash.as_deref(),
        Some("sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777")
    );
    assert_eq!(stored.object_key, command.object_key);
    assert_eq!(stored.url, None);
    assert_eq!(stored.preview_url, None);
}

#[tokio::test]
async fn artifacts_are_project_scoped_ready_filtered_and_ordered() {
    let Some(pool) = pool_or_skip("artifacts_are_project_scoped_ready_filtered_and_ordered").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_artifact_rows(&pool).await;

    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_old",
            project_id: "artifact_project",
            status: "ready",
            category: "document",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 1, 0, 0, 0),
        },
    )
    .await;
    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_new",
            project_id: "artifact_project",
            status: "ready",
            category: "document",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 2, 0, 0, 0),
        },
    )
    .await;
    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_image",
            project_id: "artifact_project",
            status: "ready",
            category: "image",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 3, 0, 0, 0),
        },
    )
    .await;
    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_pending",
            project_id: "artifact_project",
            status: "pending",
            category: "document",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 4, 0, 0, 0),
        },
    )
    .await;
    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_other_project",
            project_id: "artifact_other_project",
            status: "ready",
            category: "document",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 5, 0, 0, 0),
        },
    )
    .await;

    let repo = PgArtifactRepository::new(pool.clone());
    let records = repo
        .list(ArtifactListQuery {
            project_id: "artifact_project",
            category: Some("document"),
            tool_execution_id: Some("tool-1"),
            limit: 10,
        })
        .await
        .expect("artifact list query succeeds");

    assert_eq!(
        records
            .iter()
            .map(|artifact| artifact.id.as_str())
            .collect::<Vec<_>>(),
        vec!["artifact_new", "artifact_old"]
    );
    assert_eq!(records[0].metadata, json!({"line_count": 3}));

    let limited = repo
        .list(ArtifactListQuery {
            project_id: "artifact_project",
            category: None,
            tool_execution_id: Some("tool-1"),
            limit: 1,
        })
        .await
        .expect("limited artifact list query succeeds");
    assert_eq!(limited.len(), 1);
    assert_eq!(limited[0].id, "artifact_image");

    let pending = repo
        .get("artifact_pending")
        .await
        .expect("artifact detail query succeeds")
        .expect("pending artifact still has a detail row");
    assert_eq!(pending.status, "pending");
}

#[tokio::test]
async fn artifact_content_metadata_update_preserves_storage_reference() {
    let Some(pool) =
        pool_or_skip("artifact_content_metadata_update_preserves_storage_reference").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_artifact_rows(&pool).await;

    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_update",
            project_id: "artifact_project",
            status: "ready",
            category: "document",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 6, 0, 0, 0),
        },
    )
    .await;

    let repo = PgArtifactRepository::new(pool.clone());
    let updated = repo
        .update_content_metadata("artifact_update", 42)
        .await
        .expect("artifact update metadata succeeds")
        .expect("ready artifact is updated");

    assert_eq!(updated.size_bytes, 42);
    assert_eq!(updated.object_key, "artifacts/artifact_update.txt");
    assert_eq!(
        updated.url.as_deref(),
        Some("https://storage.example/artifact_update.txt")
    );
    assert_eq!(updated.status, "ready");

    let pending = repo
        .update_content_metadata("artifact_missing", 12)
        .await
        .expect("missing update is a non-error");
    assert!(pending.is_none());
}

#[tokio::test]
async fn artifact_mark_deleted_soft_deletes_python_row() {
    let Some(pool) = pool_or_skip("artifact_mark_deleted_soft_deletes_python_row").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_artifact_rows(&pool).await;

    seed_artifact(
        &pool,
        SeedArtifact {
            id: "artifact_delete",
            project_id: "artifact_project",
            status: "ready",
            category: "document",
            tool_execution_id: Some("tool-1"),
            created_at: ts(2026, 2, 7, 0, 0, 0),
        },
    )
    .await;

    let repo = PgArtifactRepository::new(pool.clone());
    let deleted = repo
        .mark_deleted("artifact_delete")
        .await
        .expect("artifact delete metadata succeeds")
        .expect("artifact exists");

    assert_eq!(deleted.status, "deleted");
    assert_eq!(deleted.error_message, None);
    assert_eq!(deleted.object_key, "artifacts/artifact_delete.txt");

    let listed = repo
        .list(ArtifactListQuery {
            project_id: "artifact_project",
            category: None,
            tool_execution_id: None,
            limit: 10,
        })
        .await
        .expect("list artifacts after delete");
    assert!(listed
        .iter()
        .all(|artifact| artifact.id != "artifact_delete"));

    let missing = repo
        .mark_deleted("artifact_missing")
        .await
        .expect("missing delete is a non-error");
    assert!(missing.is_none());
}

async fn clean_artifact_rows(pool: &PgPool) {
    ensure_artifact_content_v2_schema(pool).await;
    sqlx::query("DELETE FROM artifact_content_receipts WHERE artifact_id LIKE 'artifact_%'")
        .execute(pool)
        .await
        .expect("clean artifact content receipts");
    sqlx::query("DELETE FROM artifacts WHERE id LIKE 'artifact_%'")
        .execute(pool)
        .await
        .expect("clean artifacts");
}

async fn ensure_artifact_content_v2_schema(pool: &PgPool) {
    let migration_managed =
        sqlx::query_scalar::<_, bool>("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            .fetch_one(pool)
            .await
            .expect("inspect artifact schema ownership");
    if migration_managed {
        let schema_is_current = sqlx::query_scalar::<_, bool>(
            "SELECT EXISTS (\
                SELECT 1 FROM information_schema.columns \
                WHERE table_schema = 'public' AND table_name = 'artifacts' \
                  AND column_name = 'content_revision'\
             ) AND to_regclass('public.artifact_content_receipts') IS NOT NULL",
        )
        .fetch_one(pool)
        .await
        .expect("inspect artifact content v2 schema");
        assert!(
            schema_is_current,
            "migration-managed database must be upgraded to ArtifactContentContractV2"
        );
        return;
    }

    for statement in [
        "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS content_revision bigint DEFAULT 1 NOT NULL",
        "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS content_hash varchar(71)",
        "CREATE TABLE IF NOT EXISTS artifact_content_receipts (\
            artifact_id text NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE, \
            project_id text NOT NULL, tenant_id text NOT NULL, \
            idempotency_key varchar(128) NOT NULL, request_hash varchar(71) NOT NULL, \
            expected_revision bigint NOT NULL, resulting_revision bigint NOT NULL, \
            content_hash varchar(71) NOT NULL, object_key text NOT NULL, \
            size_bytes bigint NOT NULL, created_at timestamptz DEFAULT now() NOT NULL, \
            PRIMARY KEY (artifact_id, idempotency_key))",
    ] {
        sqlx::query(statement)
            .execute(pool)
            .await
            .expect("ensure artifact content v2 schema");
    }
}

struct SeedArtifact<'a> {
    id: &'a str,
    project_id: &'a str,
    status: &'a str,
    category: &'a str,
    tool_execution_id: Option<&'a str>,
    created_at: DateTime<Utc>,
}

async fn seed_artifact(pool: &PgPool, seed: SeedArtifact<'_>) {
    sqlx::query(
        "INSERT INTO artifacts \
         (id, project_id, tenant_id, sandbox_id, tool_execution_id, conversation_id, \
          filename, mime_type, category, size_bytes, object_key, url, preview_url, status, \
          error_message, source_tool, source_path, artifact_metadata, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19) \
         ON CONFLICT (id) DO UPDATE SET \
             project_id = EXCLUDED.project_id, \
             status = EXCLUDED.status, \
             category = EXCLUDED.category, \
             tool_execution_id = EXCLUDED.tool_execution_id, \
             created_at = EXCLUDED.created_at",
    )
    .bind(seed.id)
    .bind(seed.project_id)
    .bind("artifact_tenant")
    .bind("artifact_sandbox")
    .bind(seed.tool_execution_id)
    .bind("artifact_conversation")
    .bind(format!("{}.txt", seed.id))
    .bind("text/plain")
    .bind(seed.category)
    .bind(12_i64)
    .bind(format!("artifacts/{}.txt", seed.id))
    .bind(format!("https://storage.example/{}.txt", seed.id))
    .bind(Option::<String>::None)
    .bind(seed.status)
    .bind(Option::<String>::None)
    .bind("terminal")
    .bind(format!("/workspace/{}.txt", seed.id))
    .bind(json!({"line_count": 3}))
    .bind(seed.created_at)
    .execute(pool)
    .await
    .expect("seed artifact");
}
