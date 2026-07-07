use super::support::*;

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
    sqlx::query("DELETE FROM artifacts WHERE id LIKE 'artifact_%'")
        .execute(pool)
        .await
        .expect("clean artifacts");
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
