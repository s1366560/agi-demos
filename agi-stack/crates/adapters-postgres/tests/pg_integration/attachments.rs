use super::support::*;

#[tokio::test]
async fn attachments_are_conversation_scoped_visible_and_python_ordered() {
    let Some(pool) =
        pool_or_skip("attachments_are_conversation_scoped_visible_and_python_ordered").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_attachment_rows(&pool).await;
    seed_attachment_user(&pool, "attachment_user", false).await;
    seed_attachment_user(&pool, "attachment_superuser", true).await;
    seed_attachment_project(
        &pool,
        "attachment_project",
        "attachment_tenant",
        "attachment_owner",
    )
    .await;
    seed_attachment_project(
        &pool,
        "attachment_other_project",
        "attachment_other_tenant",
        "attachment_owner",
    )
    .await;
    seed_attachment_membership(&pool, "attachment_user", "attachment_project").await;

    seed_attachment(
        &pool,
        SeedAttachment {
            id: "attachment_old",
            conversation_id: "attachment_conversation",
            project_id: "attachment_project",
            tenant_id: "attachment_tenant",
            status: "ready",
            created_at: ts(2026, 2, 1, 0, 0, 0),
        },
    )
    .await;
    seed_attachment(
        &pool,
        SeedAttachment {
            id: "attachment_new",
            conversation_id: "attachment_conversation",
            project_id: "attachment_project",
            tenant_id: "attachment_tenant",
            status: "ready",
            created_at: ts(2026, 2, 2, 0, 0, 0),
        },
    )
    .await;
    seed_attachment(
        &pool,
        SeedAttachment {
            id: "attachment_pending",
            conversation_id: "attachment_conversation",
            project_id: "attachment_project",
            tenant_id: "attachment_tenant",
            status: "pending",
            created_at: ts(2026, 2, 3, 0, 0, 0),
        },
    )
    .await;
    seed_attachment(
        &pool,
        SeedAttachment {
            id: "attachment_other_conversation",
            conversation_id: "attachment_other_conversation",
            project_id: "attachment_project",
            tenant_id: "attachment_tenant",
            status: "ready",
            created_at: ts(2026, 2, 4, 0, 0, 0),
        },
    )
    .await;
    seed_attachment(
        &pool,
        SeedAttachment {
            id: "attachment_tenant_mismatch",
            conversation_id: "attachment_conversation",
            project_id: "attachment_project",
            tenant_id: "attachment_other_tenant",
            status: "ready",
            created_at: ts(2026, 2, 5, 0, 0, 0),
        },
    )
    .await;
    seed_attachment(
        &pool,
        SeedAttachment {
            id: "attachment_inaccessible",
            conversation_id: "attachment_conversation",
            project_id: "attachment_other_project",
            tenant_id: "attachment_other_tenant",
            status: "ready",
            created_at: ts(2026, 2, 6, 0, 0, 0),
        },
    )
    .await;

    let repo = PgAttachmentRepository::new(pool.clone());
    let ready = repo
        .list_visible(agistack_adapters_postgres::AttachmentListQuery {
            user_id: "attachment_user",
            conversation_id: "attachment_conversation",
            status: Some("ready"),
        })
        .await
        .expect("attachment list succeeds");

    assert_eq!(
        ready
            .iter()
            .map(|attachment| attachment.id.as_str())
            .collect::<Vec<_>>(),
        vec!["attachment_old", "attachment_new"]
    );

    let all_visible = repo
        .list_visible(agistack_adapters_postgres::AttachmentListQuery {
            user_id: "attachment_user",
            conversation_id: "attachment_conversation",
            status: None,
        })
        .await
        .expect("unfiltered attachment list succeeds");
    assert_eq!(all_visible.len(), 3);
    assert_eq!(all_visible[2].id, "attachment_pending");

    let detail = repo
        .get("attachment_new")
        .await
        .expect("attachment detail succeeds")
        .expect("attachment exists");
    assert_eq!(detail.project_id, "attachment_project");
    assert_eq!(detail.object_key.as_str(), "attachments/attachment_new.txt");
    assert_eq!(
        detail.sandbox_path.as_deref(),
        Some("/workspace/attachment_new.txt")
    );

    assert_eq!(
        repo.accessible_project_tenant("attachment_user", "attachment_project")
            .await
            .expect("project access succeeds")
            .as_deref(),
        Some("attachment_tenant")
    );
    assert!(repo
        .accessible_project_tenant("attachment_user", "attachment_other_project")
        .await
        .expect("project access succeeds")
        .is_none());
    assert_eq!(
        repo.accessible_project_tenant("attachment_superuser", "attachment_other_project")
            .await
            .expect("superuser project access succeeds")
            .as_deref(),
        Some("attachment_other_tenant")
    );
}

#[tokio::test]
async fn attachment_delete_hard_deletes_python_row() {
    let Some(pool) = pool_or_skip("attachment_delete_hard_deletes_python_row").await else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_attachment_rows(&pool).await;
    seed_attachment_user(&pool, "attachment_delete_user", false).await;
    seed_attachment_project(
        &pool,
        "attachment_delete_project",
        "attachment_delete_tenant",
        "attachment_delete_owner",
    )
    .await;
    seed_attachment_membership(&pool, "attachment_delete_user", "attachment_delete_project").await;
    seed_attachment(
        &pool,
        SeedAttachment {
            id: "attachment_delete_row",
            conversation_id: "attachment_delete_conversation",
            project_id: "attachment_delete_project",
            tenant_id: "attachment_delete_tenant",
            status: "ready",
            created_at: ts(2026, 2, 7, 0, 0, 0),
        },
    )
    .await;

    let repo = PgAttachmentRepository::new(pool.clone());
    assert_eq!(
        repo.get("attachment_delete_row")
            .await
            .expect("attachment detail")
            .expect("attachment exists")
            .object_key
            .as_str(),
        "attachments/attachment_delete_row.txt"
    );

    assert!(repo
        .delete("attachment_delete_row")
        .await
        .expect("delete attachment"));
    assert!(repo
        .get("attachment_delete_row")
        .await
        .expect("read deleted attachment")
        .is_none());
    assert!(!repo
        .delete("attachment_delete_row")
        .await
        .expect("delete missing attachment"));
}

#[tokio::test]
async fn attachment_insert_uploaded_matches_python_simple_upload_row() {
    let Some(pool) =
        pool_or_skip("attachment_insert_uploaded_matches_python_simple_upload_row").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_attachment_rows(&pool).await;
    seed_attachment_user(&pool, "attachment_upload_user", false).await;
    seed_attachment_project(
        &pool,
        "attachment_upload_project",
        "attachment_upload_tenant",
        "attachment_upload_owner",
    )
    .await;
    seed_attachment_membership(&pool, "attachment_upload_user", "attachment_upload_project").await;

    let repo = PgAttachmentRepository::new(pool.clone());
    let created_at = ts(2026, 2, 8, 0, 0, 0);
    let uploaded = repo
        .insert_uploaded(agistack_adapters_postgres::AttachmentUploadRecord {
            id: "attachment_upload_row".to_string(),
            conversation_id: "attachment_upload_conversation".to_string(),
            project_id: "attachment_upload_project".to_string(),
            tenant_id: "attachment_upload_tenant".to_string(),
            filename: "report.txt".to_string(),
            mime_type: "text/plain".to_string(),
            size_bytes: 5,
            object_key: "attachments/tenant/project/conversation/report.txt".to_string(),
            purpose: "both".to_string(),
            created_at,
        })
        .await
        .expect("insert uploaded attachment");

    assert_eq!(uploaded.status, "uploaded");
    assert_eq!(uploaded.sandbox_path, None);
    assert_eq!(uploaded.error_message, None);

    let row: (
        Option<String>,
        Option<i32>,
        i32,
        serde_json::Value,
        DateTime<Utc>,
    ) = sqlx::query_as(
        "SELECT upload_id, total_parts, uploaded_parts, file_metadata, expires_at \
             FROM attachments WHERE id = $1",
    )
    .bind("attachment_upload_row")
    .fetch_one(&pool)
    .await
    .expect("read uploaded row");
    assert_eq!(row.0, None);
    assert_eq!(row.1, None);
    assert_eq!(row.2, 0);
    assert_eq!(row.3, json!({}));
    assert_eq!(row.4.timestamp() - created_at.timestamp(), 24 * 60 * 60);
}

async fn clean_attachment_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM attachments WHERE id LIKE 'attachment_%'")
        .execute(pool)
        .await
        .expect("clean attachments");
    sqlx::query("DELETE FROM user_projects WHERE project_id LIKE 'attachment_%' OR user_id LIKE 'attachment_%'")
        .execute(pool)
        .await
        .expect("clean attachment memberships");
    sqlx::query("DELETE FROM projects WHERE id LIKE 'attachment_%'")
        .execute(pool)
        .await
        .expect("clean attachment projects");
    sqlx::query("DELETE FROM users WHERE id LIKE 'attachment_%'")
        .execute(pool)
        .await
        .expect("clean attachment users");
}

async fn seed_attachment_user(pool: &PgPool, user_id: &str, is_superuser: bool) {
    sqlx::query(
        "INSERT INTO users (id, email, is_superuser) VALUES ($1, $2, $3) \
         ON CONFLICT (id) DO UPDATE SET is_superuser = EXCLUDED.is_superuser",
    )
    .bind(user_id)
    .bind(format!("{user_id}@example.test"))
    .bind(is_superuser)
    .execute(pool)
    .await
    .expect("seed attachment user");
}

async fn seed_attachment_project(pool: &PgPool, project_id: &str, tenant_id: &str, owner_id: &str) {
    sqlx::query(
        "INSERT INTO projects (id, tenant_id, name, owner_id, is_public) \
         VALUES ($1, $2, $3, $4, false) \
         ON CONFLICT (id) DO UPDATE SET tenant_id = EXCLUDED.tenant_id",
    )
    .bind(project_id)
    .bind(tenant_id)
    .bind(format!("Project {project_id}"))
    .bind(owner_id)
    .execute(pool)
    .await
    .expect("seed attachment project");
}

async fn seed_attachment_membership(pool: &PgPool, user_id: &str, project_id: &str) {
    sqlx::query(
        "INSERT INTO user_projects (user_id, project_id, role) VALUES ($1, $2, 'member') \
         ON CONFLICT (user_id, project_id) DO UPDATE SET role = EXCLUDED.role",
    )
    .bind(user_id)
    .bind(project_id)
    .execute(pool)
    .await
    .expect("seed attachment membership");
}

struct SeedAttachment<'a> {
    id: &'a str,
    conversation_id: &'a str,
    project_id: &'a str,
    tenant_id: &'a str,
    status: &'a str,
    created_at: DateTime<Utc>,
}

async fn seed_attachment(pool: &PgPool, seed: SeedAttachment<'_>) {
    sqlx::query(
        "INSERT INTO attachments \
         (id, conversation_id, project_id, tenant_id, filename, mime_type, size_bytes, \
          object_key, purpose, status, uploaded_parts, sandbox_path, file_metadata, \
          error_message, created_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 0, $11, $12, $13, $14) \
         ON CONFLICT (id) DO UPDATE SET \
             conversation_id = EXCLUDED.conversation_id, \
             project_id = EXCLUDED.project_id, \
             tenant_id = EXCLUDED.tenant_id, \
             status = EXCLUDED.status, \
             created_at = EXCLUDED.created_at",
    )
    .bind(seed.id)
    .bind(seed.conversation_id)
    .bind(seed.project_id)
    .bind(seed.tenant_id)
    .bind(format!("{}.txt", seed.id))
    .bind("text/plain")
    .bind(42_i64)
    .bind(format!("attachments/{}.txt", seed.id))
    .bind("both")
    .bind(seed.status)
    .bind(format!("/workspace/{}.txt", seed.id))
    .bind(json!({"encoding": "utf-8"}))
    .bind(Option::<String>::None)
    .bind(seed.created_at)
    .execute(pool)
    .await
    .expect("seed attachment");
}
