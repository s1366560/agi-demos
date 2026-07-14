use super::support::*;

#[tokio::test]
async fn cron_jobs_and_runs_are_project_scoped_and_python_ordered() {
    let Some(pool) = pool_or_skip("cron_jobs_and_runs_are_project_scoped_and_python_ordered").await
    else {
        return;
    };
    ensure_python_shaped_tables(&pool).await;
    clean_cron_rows(&pool).await;

    let scopes = sqlx::query_as::<_, (String, String, String)>(
        "SELECT project.id, project.tenant_id, project.owner_id \
         FROM projects AS project \
         WHERE NOT EXISTS (SELECT 1 FROM cron_jobs AS job WHERE job.project_id = project.id) \
         ORDER BY project.id LIMIT 2",
    )
    .fetch_all(&pool)
    .await
    .expect("load cron project scopes");
    let [target_scope, other_scope, ..] = scopes.as_slice() else {
        eprintln!("[skip] cron project scoping requires two projects");
        return;
    };
    let (project_id, tenant_id, user_id) = target_scope;
    let (other_project_id, other_tenant_id, other_user_id) = other_scope;

    seed_cron_job(
        &pool,
        "cron_job_old",
        project_id,
        tenant_id,
        user_id,
        true,
        ts(2026, 1, 1, 0, 0, 0),
    )
    .await;
    seed_cron_job(
        &pool,
        "cron_job_new",
        project_id,
        tenant_id,
        user_id,
        true,
        ts(2026, 1, 2, 0, 0, 0),
    )
    .await;
    seed_cron_job(
        &pool,
        "cron_job_disabled",
        project_id,
        tenant_id,
        user_id,
        false,
        ts(2026, 1, 3, 0, 0, 0),
    )
    .await;
    seed_cron_job(
        &pool,
        "cron_job_other",
        other_project_id,
        other_tenant_id,
        other_user_id,
        true,
        ts(2026, 1, 4, 0, 0, 0),
    )
    .await;
    seed_cron_run(
        &pool,
        "cron_run_old",
        "cron_job_new",
        project_id,
        "success",
        ts(2026, 1, 2, 1, 0, 0),
    )
    .await;
    seed_cron_run(
        &pool,
        "cron_run_new",
        "cron_job_new",
        project_id,
        "failed",
        ts(2026, 1, 2, 2, 0, 0),
    )
    .await;
    seed_cron_run(
        &pool,
        "cron_run_other_project",
        "cron_job_new",
        other_project_id,
        "success",
        ts(2026, 1, 2, 3, 0, 0),
    )
    .await;

    let repo = PgCronRepository::new(pool.clone());
    let (enabled_jobs, enabled_total) = repo
        .list_jobs(CronJobListQuery {
            project_id,
            include_disabled: false,
            limit: 10,
            offset: 0,
        })
        .await
        .expect("cron job list succeeds");
    assert_eq!(enabled_total, 2);
    assert_eq!(
        enabled_jobs
            .iter()
            .map(|job| job.id.as_str())
            .collect::<Vec<_>>(),
        vec!["cron_job_new", "cron_job_old"]
    );

    let (all_jobs, all_total) = repo
        .list_jobs(CronJobListQuery {
            project_id,
            include_disabled: true,
            limit: 2,
            offset: 0,
        })
        .await
        .expect("cron job list with disabled succeeds");
    assert_eq!(all_total, 3);
    assert_eq!(
        all_jobs
            .iter()
            .map(|job| job.id.as_str())
            .collect::<Vec<_>>(),
        vec!["cron_job_disabled", "cron_job_new"]
    );
    assert_eq!(all_jobs[0].schedule_config, json!({"expr": "0 * * * *"}));
    assert_eq!(
        all_jobs[0].payload_config,
        json!({"message": "Summarize status", "timeout_seconds": 300})
    );

    let job = repo
        .get_job(project_id, "cron_job_new")
        .await
        .expect("cron job detail query succeeds")
        .expect("cron job exists");
    assert_eq!(job.name, "Cron cron_job_new");
    assert!(repo
        .get_job(project_id, "cron_job_other")
        .await
        .expect("wrong-project cron job detail query succeeds")
        .is_none());

    let (runs, total) = repo
        .list_runs(project_id, "cron_job_new", 10, 0)
        .await
        .expect("cron run list succeeds");
    assert_eq!(total, 2);
    assert_eq!(
        runs.iter().map(|run| run.id.as_str()).collect::<Vec<_>>(),
        vec!["cron_run_new", "cron_run_old"]
    );
    assert_eq!(runs[0].status, "failed");
    assert_eq!(runs[0].result_summary, json!({"tokens": 42}));
}

async fn clean_cron_rows(pool: &PgPool) {
    sqlx::query("DELETE FROM cron_job_runs WHERE id LIKE 'cron_run_%'")
        .execute(pool)
        .await
        .expect("clean cron runs");
    sqlx::query("DELETE FROM cron_jobs WHERE id LIKE 'cron_job_%'")
        .execute(pool)
        .await
        .expect("clean cron jobs");
}

async fn seed_cron_job(
    pool: &PgPool,
    id: &str,
    project_id: &str,
    tenant_id: &str,
    user_id: &str,
    enabled: bool,
    created_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO cron_jobs \
         (id, project_id, tenant_id, name, description, enabled, delete_after_run, \
          schedule_type, schedule_config, payload_type, payload_config, delivery_type, \
          delivery_config, conversation_mode, conversation_id, timezone, stagger_seconds, \
          timeout_seconds, max_retries, state, created_by, created_at, updated_at) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, \
                 $15, $16, $17, $18, $19, $20, $21, $22, $23) \
         ON CONFLICT (id) DO UPDATE SET project_id = EXCLUDED.project_id, \
             enabled = EXCLUDED.enabled, created_at = EXCLUDED.created_at",
    )
    .bind(id)
    .bind(project_id)
    .bind(tenant_id)
    .bind(format!("Cron {id}"))
    .bind("Cron integration job")
    .bind(enabled)
    .bind(false)
    .bind("cron")
    .bind(json!({"expr": "0 * * * *"}))
    .bind("agent_turn")
    .bind(json!({"message": "Summarize status", "timeout_seconds": 300}))
    .bind("announce")
    .bind(json!({"conversation_id": "conversation-1"}))
    .bind("reuse")
    .bind("conversation-1")
    .bind("UTC")
    .bind(5_i32)
    .bind(300_i32)
    .bind(3_i32)
    .bind(json!({"last_run_status": "success"}))
    .bind(user_id)
    .bind(created_at)
    .bind(ts(2026, 1, 5, 0, 0, 0))
    .execute(pool)
    .await
    .expect("seed cron job");
}

async fn seed_cron_run(
    pool: &PgPool,
    id: &str,
    job_id: &str,
    project_id: &str,
    status: &str,
    started_at: DateTime<Utc>,
) {
    sqlx::query(
        "INSERT INTO cron_job_runs \
         (id, job_id, project_id, status, trigger_type, started_at, finished_at, \
          duration_ms, error_message, result_summary, conversation_id) \
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) \
         ON CONFLICT (id) DO UPDATE SET project_id = EXCLUDED.project_id, \
             started_at = EXCLUDED.started_at",
    )
    .bind(id)
    .bind(job_id)
    .bind(project_id)
    .bind(status)
    .bind("scheduled")
    .bind(started_at)
    .bind(started_at)
    .bind(1250_i32)
    .bind(Option::<String>::None)
    .bind(json!({"tokens": 42}))
    .bind("conversation-1")
    .execute(pool)
    .await
    .expect("seed cron run");
}
