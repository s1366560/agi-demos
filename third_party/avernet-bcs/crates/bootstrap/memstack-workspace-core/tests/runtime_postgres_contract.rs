use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result, anyhow};
use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_core::{WorkspaceCoreState, workspace_router};
use serde_json::{Value, json};
use tower::ServiceExt;

const TENANT_HEADER: &str = "x-memstack-tenant-id";
const SERVICE_TOKEN: &str = "postgres-contract-token";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn runtime_authority_passes_postgres_idempotency_and_rollback_contracts() -> Result<()> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")
        .context("BCS_TEST_POSTGRES_URL must be set for the runtime contract")?;
    let db: Arc<dyn DbPlugin> = Arc::new(
        PostgresDbPlugin::connect(&database_url, 4)
            .await
            .context("connect PostgreSQL runtime contract database")?,
    );
    seed_workspace(&db, "ws-plan", Some("plan-1")).await?;
    seed_workspace(&db, "ws-direct", None).await?;
    seed_workspace(&db, "ws-recovery", Some("plan-recovery")).await?;
    seed_workspace(&db, "ws-rollback", Some("plan-rollback")).await?;
    let state = Arc::new(
        WorkspaceCoreState::new(db.clone(), SERVICE_TOKEN.to_string())
            .map_err(|error| anyhow!(error))?,
    );

    public_read_surface_uses_the_postgres_authority(state.clone()).await?;
    internal_creation_uses_the_postgres_authority(state.clone(), &db).await?;
    public_creation_uses_the_postgres_authority(state.clone(), &db).await?;
    plan_terminal_is_idempotent(state.clone(), &db).await?;
    direct_terminal_has_no_plan_terminal_row(state.clone(), &db).await?;
    runtime_recovery_is_leased_audited_and_acknowledged(state.clone(), &db).await?;
    terminal_transaction_rolls_back_on_outbox_failure(state, &db).await?;
    Ok(())
}

async fn internal_creation_uses_the_postgres_authority(
    state: Arc<WorkspaceCoreState>,
    db: &Arc<dyn DbPlugin>,
) -> Result<()> {
    seed_project_membership(db).await?;
    let path = "/internal/v1/tenants/tenant-contract/projects/project-contract/workspaces";
    let payload = json!({
        "workspace_id": "ws-created",
        "group_id": "group-ws-created",
        "owner_member_id": "member-ws-created",
        "name": "Created Contract Workspace",
        "description": "PostgreSQL application service contract",
        "metadata": {"workspace_type": "general"}
    });

    let (status, first) = post_create_json(state.clone(), path, &payload).await?;
    let (replay_status, replay) = post_create_json(state, path, &payload).await?;

    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(replay_status, StatusCode::CREATED);
    assert_eq!(first["replayed"], false);
    assert_eq!(replay["replayed"], true);
    assert_eq!(replay["receipt_id"], first["receipt_id"]);
    assert_eq!(replay["workspace"], first["workspace"]);
    assert_eq!(workspace_revision(db, "ws-created").await?, 1);
    assert_eq!(
        scoped_count(db, "workspace_profiles", "ws-created").await?,
        1
    );
    assert_eq!(
        scoped_count(db, "workspace_members", "ws-created").await?,
        1
    );
    assert_eq!(scoped_count(db, "workspace_outbox", "ws-created").await?, 1);
    Ok(())
}

async fn public_creation_uses_the_postgres_authority(
    state: Arc<WorkspaceCoreState>,
    db: &Arc<dyn DbPlugin>,
) -> Result<()> {
    let path = "/api/v1/tenants/tenant-contract/projects/project-contract/workspaces";
    let payload = json!({
        "name": "Public Contract Workspace",
        "description": "PostgreSQL public compatibility contract",
        "use_case": "programming",
        "collaboration_mode": "autonomous",
        "sandbox_code_root": "public-contract",
        "metadata": {"source": "postgres-contract"}
    });

    let (status, first) =
        post_public_create_json(state.clone(), path, &payload, "public-contract-intent").await?;
    let (replay_status, replay) =
        post_public_create_json(state.clone(), path, &payload, "public-contract-intent").await?;

    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(replay_status, StatusCode::CREATED);
    assert_eq!(replay, first);
    assert_eq!(first["tenant_id"], "tenant-contract");
    assert_eq!(first["project_id"], "project-contract");
    assert_eq!(first["created_by"], "user-contract");
    assert_eq!(first["metadata"]["workspace_use_case"], "programming");
    assert_eq!(first["metadata"]["workspace_type"], "software_development");
    assert_eq!(
        first["metadata"]["sandbox_code_root"],
        "/workspace/public-contract"
    );
    assert!(
        first["created_at"]
            .as_str()
            .is_some_and(|value| value.ends_with('Z'))
    );
    let workspace_id = first["id"]
        .as_str()
        .ok_or_else(|| anyhow!("public creation response is missing its id"))?;
    assert_eq!(workspace_revision(db, workspace_id).await?, 1);
    assert_eq!(
        scoped_count(db, "workspace_profiles", workspace_id).await?,
        1
    );
    assert_eq!(
        scoped_count(db, "workspace_members", workspace_id).await?,
        1
    );
    assert_eq!(scoped_count(db, "workspace_outbox", workspace_id).await?, 1);

    let changed = json!({
        "name": "Changed Public Contract Workspace",
        "use_case": "general"
    });
    let (conflict_status, conflict) =
        post_public_create_json(state, path, &changed, "public-contract-intent").await?;
    assert_eq!(conflict_status, StatusCode::CONFLICT);
    assert_eq!(conflict, json!({"detail": "Workspace already exists"}));
    Ok(())
}

async fn public_read_surface_uses_the_postgres_authority(
    state: Arc<WorkspaceCoreState>,
) -> Result<()> {
    let workspace_path =
        "/api/v1/tenants/tenant-contract/projects/project-contract/workspaces/ws-plan";
    let (status, workspace) = get_public_json(state.clone(), workspace_path, false).await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(workspace["id"], "ws-plan");
    assert_eq!(workspace["metadata"], json!({}));
    assert_eq!(workspace["hex_layout_config"], json!({}));

    let (status, workspaces) = get_public_json(
        state.clone(),
        "/api/v1/tenants/tenant-contract/projects/project-contract/workspaces?limit=20&offset=0",
        false,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(workspaces.as_array().map(Vec::len), Some(4));

    let (status, agents) = get_public_json(
        state.clone(),
        &format!("{workspace_path}/agents?active_only=true&limit=20&offset=0"),
        false,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(agents[0]["agent_id"], "agent-ws-plan");
    assert_eq!(agents[0]["config"], json!({}));

    let (status, members) = get_public_json(
        state.clone(),
        &format!("{workspace_path}/members?limit=20&offset=0"),
        false,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(members[0]["id"], "member-ws-plan");
    assert_eq!(members[0]["user_id"], "user-contract");
    assert_eq!(members[0]["user_email"], "user-contract@example.invalid");
    assert_eq!(members[0]["role"], "owner");

    let (status, capabilities) = get_public_json(
        state.clone(),
        &format!("{workspace_path}/collaboration/capabilities"),
        false,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(capabilities["contract_version"], "2.0.0");
    assert_eq!(capabilities["mutations"]["idempotency_guarded"], true);

    let (status, authority) = get_public_json(
        state,
        &format!("{workspace_path}/collaboration/authority"),
        true,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(authority["revision"], 0);
    assert_eq!(authority["cursor"], "workspace:ws-plan:revision:0");
    Ok(())
}

async fn runtime_recovery_is_leased_audited_and_acknowledged(
    state: Arc<WorkspaceCoreState>,
    db: &Arc<dyn DbPlugin>,
) -> Result<()> {
    let correlation = correlation_payload(
        "correlation-recovery",
        "delivery-recovery",
        "ws-recovery",
        Some("plan-recovery"),
    );
    let (status, created) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations",
        &correlation,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(created["created"], true);
    let stored = db
        .query(DbStatement::new(
            "SELECT user_id, bcs_group_id, provider_id, provider_bot_ref FROM \
             workspace_agent_runtime_correlations WHERE correlation_id = \
             'correlation-recovery'",
        ))
        .await?
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("recovery correlation is missing"))?;
    assert_eq!(
        stored.get_string("user_id")?.as_deref(),
        Some("user-contract")
    );
    assert_eq!(
        stored.get_string("bcs_group_id")?.as_deref(),
        Some("group-ws-recovery")
    );
    assert_eq!(
        stored.get_string("provider_id")?.as_deref(),
        Some("memstack-agent-runtime")
    );
    assert_eq!(
        stored.get_string("provider_bot_ref")?.as_deref(),
        Some("provider-bot-contract")
    );

    wait_until_stale().await;
    let claim = recovery_claim_payload("recovery-worker-1");
    let (status, first_claim) = post_json(
        state.clone(),
        "/internal/v1/runtime-recoveries/claim",
        &claim,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    let recoveries = first_claim["recoveries"]
        .as_array()
        .ok_or_else(|| anyhow!("recovery claim payload is invalid"))?;
    let claimed = recoveries
        .iter()
        .find(|item| item["correlation_id"] == "correlation-recovery")
        .ok_or_else(|| anyhow!("stale running correlation was not claimed"))?;
    assert_eq!(claimed["recovery_attempt_count"], 1);

    let (status, competing_claim) = post_json(
        state.clone(),
        "/internal/v1/runtime-recoveries/claim",
        &recovery_claim_payload("recovery-worker-2"),
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(competing_claim["recoveries"], json!([]));

    let judgment = json!({
        "audit_id": "audit-recovery-contract",
        "project_id": "project-contract",
        "workspace_id": "ws-recovery",
        "lease_owner": "recovery-worker-1",
        "action": "continue",
        "agent_id": "judge-provider:model-contract",
        "tool_name": "decide_runtime_recovery",
        "input_json": {"correlation_id": "correlation-recovery", "status": "running"},
        "output_json": {"action": "continue", "evidence": ["stale correlation"]},
        "rationale": "the persisted evidence does not prove a terminal failure",
        "latency_ms": 9,
    });
    let judgment_path = "/internal/v1/runtime-correlations/correlation-recovery/recovery-judgments";
    let (status, recorded) = post_json(state.clone(), judgment_path, &judgment).await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(recorded["recorded"], true);
    assert_eq!(recorded["action"], "continue");
    let audit = db
        .query(DbStatement::new(
            "SELECT judgment_type, agent_id, tool_name, status FROM workspace_judge_audits \
             WHERE audit_id = 'audit-recovery-contract'",
        ))
        .await?;
    let audit = audit
        .first()
        .ok_or_else(|| anyhow!("runtime recovery audit is missing"))?;
    assert_eq!(
        audit.get_string("judgment_type")?.as_deref(),
        Some("runtime_recovery")
    );
    assert_eq!(
        audit.get_string("agent_id")?.as_deref(),
        Some("judge-provider:model-contract")
    );
    assert_eq!(
        audit.get_string("tool_name")?.as_deref(),
        Some("decide_runtime_recovery")
    );
    assert_eq!(audit.get_string("status")?.as_deref(), Some("continue"));

    wait_until_stale().await;
    let (_, reclaimed) = post_json(
        state.clone(),
        "/internal/v1/runtime-recoveries/claim",
        &recovery_claim_payload("terminal-worker"),
    )
    .await?;
    assert_eq!(reclaimed["recoveries"][0]["status"], "running");
    let (status, terminal) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations/correlation-recovery/terminal",
        &terminal_payload("ws-recovery", "complete", "legacy-terminal-recovery"),
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(terminal["status"], "completed");
    assert_recovery_state(db, "correlation-recovery", "terminal", 2, 0).await?;

    wait_until_stale().await;
    let (_, terminal_claim) = post_json(
        state.clone(),
        "/internal/v1/runtime-recoveries/claim",
        &recovery_claim_payload("callback-worker"),
    )
    .await?;
    assert_eq!(terminal_claim["recoveries"][0]["status"], "completed");
    let (status, callback_ack) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations/correlation-recovery/callback-ack",
        &json!({"project_id": "project-contract", "workspace_id": "ws-recovery"}),
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(callback_ack["acknowledged"], true);
    assert_recovery_state(db, "correlation-recovery", "terminal", 3, 1).await?;

    wait_until_stale().await;
    let (_, after_ack) = post_json(
        state,
        "/internal/v1/runtime-recoveries/claim",
        &recovery_claim_payload("after-ack-worker"),
    )
    .await?;
    assert_eq!(after_ack["recoveries"], json!([]));
    Ok(())
}

async fn plan_terminal_is_idempotent(
    state: Arc<WorkspaceCoreState>,
    db: &Arc<dyn DbPlugin>,
) -> Result<()> {
    let correlation = correlation_payload(
        "correlation-plan",
        "delivery-plan",
        "ws-plan",
        Some("plan-1"),
    );
    let (status, first) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations",
        &correlation,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(first["created"], true);

    let (_, duplicate) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations",
        &correlation,
    )
    .await?;
    assert_eq!(duplicate["created"], false);

    let mut conflicting = correlation;
    conflicting["conversation_id"] = json!("different-conversation");
    let (status, _) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations",
        &conflicting,
    )
    .await?;
    assert_eq!(status, StatusCode::CONFLICT);

    let terminal = terminal_payload("ws-plan", "complete", "legacy-terminal-plan");
    let terminal_path = "/internal/v1/runtime-correlations/correlation-plan/terminal";
    let (status, first) = post_json(state.clone(), terminal_path, &terminal).await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(first["created"], true);
    assert_eq!(first["status"], "completed");

    let (_, duplicate) = post_json(state.clone(), terminal_path, &terminal).await?;
    assert_eq!(duplicate["created"], false);
    let (status, replay) = get_json(
        state.clone(),
        "/internal/v1/runtime-correlations/correlation-plan/terminal\
         ?project_id=project-contract&workspace_id=ws-plan",
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(replay["persisted"], true);
    assert_eq!(replay["terminal_event_id"], "legacy-terminal-plan");
    assert_eq!(replay["report"], terminal["report"]);
    let (wrong_scope_status, _) = get_json(
        state,
        "/internal/v1/runtime-correlations/correlation-plan/terminal\
         ?project_id=project-contract&workspace_id=ws-direct",
    )
    .await?;
    assert_eq!(wrong_scope_status, StatusCode::NOT_FOUND);
    assert_eq!(scoped_count(db, "workspace_outbox", "ws-plan").await?, 1);
    assert_eq!(
        scoped_count(db, "workspace_execution_terminals", "ws-plan").await?,
        1
    );
    assert_eq!(workspace_revision(db, "ws-plan").await?, 1);
    let proof = db
        .query(DbStatement::new(
            "SELECT terminal_event_id, plan_event_id FROM workspace_execution_terminals \
             WHERE correlation_id = 'correlation-plan'",
        ))
        .await
        .context("read persisted terminal proof")?
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("persisted terminal proof is missing"))?;
    assert_eq!(
        proof.get_string("terminal_event_id")?,
        Some("legacy-terminal-plan".to_string())
    );
    assert_eq!(
        proof.get_string("plan_event_id")?,
        Some("runtime-plan-event-correlation-plan".to_string())
    );
    Ok(())
}

async fn direct_terminal_has_no_plan_terminal_row(
    state: Arc<WorkspaceCoreState>,
    db: &Arc<dyn DbPlugin>,
) -> Result<()> {
    let correlation =
        correlation_payload("correlation-direct", "delivery-direct", "ws-direct", None);
    let (status, _) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations",
        &correlation,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);

    let (status, terminal) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations/correlation-direct/terminal",
        &terminal_payload("ws-direct", "error", "legacy-terminal-direct"),
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(terminal["status"], "failed");
    assert!(terminal.get("terminal_id").is_none());
    let (status, replay) = get_json(
        state,
        "/internal/v1/runtime-correlations/correlation-direct/terminal\
         ?project_id=project-contract&workspace_id=ws-direct",
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    assert!(replay.get("terminal_id").is_none());
    assert_eq!(replay["status"], "failed");
    assert_eq!(replay["terminal_event_id"], "legacy-terminal-direct");
    assert_eq!(scoped_count(db, "workspace_outbox", "ws-direct").await?, 1);
    assert_eq!(
        scoped_count(db, "workspace_execution_terminals", "ws-direct").await?,
        0
    );
    assert_eq!(workspace_revision(db, "ws-direct").await?, 1);
    Ok(())
}

async fn terminal_transaction_rolls_back_on_outbox_failure(
    state: Arc<WorkspaceCoreState>,
    db: &Arc<dyn DbPlugin>,
) -> Result<()> {
    let correlation = correlation_payload(
        "correlation-rollback",
        "delivery-rollback",
        "ws-rollback",
        Some("plan-rollback"),
    );
    let (status, _) = post_json(
        state.clone(),
        "/internal/v1/runtime-correlations",
        &correlation,
    )
    .await?;
    assert_eq!(status, StatusCode::OK);
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_runtime_contract_outbox() RETURNS trigger \
         LANGUAGE plpgsql AS $$ BEGIN IF NEW.outbox_id = \
         'runtime-outbox-correlation-rollback' THEN RAISE EXCEPTION \
         'runtime contract rejection'; END IF; RETURN NEW; END $$",
    ))
    .await
    .context("create outbox rejection function")?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_runtime_contract_outbox BEFORE INSERT ON workspace_outbox \
         FOR EACH ROW EXECUTE FUNCTION avernet.reject_runtime_contract_outbox()",
    ))
    .await
    .context("create outbox rejection trigger")?;

    let (status, _) = post_json(
        state,
        "/internal/v1/runtime-correlations/correlation-rollback/terminal",
        &terminal_payload("ws-rollback", "complete", "legacy-terminal-rollback"),
    )
    .await?;
    assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(workspace_revision(db, "ws-rollback").await?, 0);
    assert_eq!(
        scoped_count(db, "workspace_plan_events", "ws-rollback").await?,
        0
    );
    assert_eq!(
        scoped_count(db, "workspace_outbox", "ws-rollback").await?,
        0
    );
    let status = db
        .query(DbStatement::new(
            "SELECT status FROM workspace_agent_runtime_correlations \
             WHERE correlation_id = 'correlation-rollback'",
        ))
        .await?
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("rollback correlation is missing"))?
        .get_string("status")?;
    assert_eq!(status, Some("running".to_string()));
    Ok(())
}

async fn seed_workspace(
    db: &Arc<dyn DbPlugin>,
    workspace_id: &str,
    plan_id: Option<&str>,
) -> Result<()> {
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, \
                 group_id, name, created_by) VALUES (",
            )
            .bind(workspace_id)
            .push_static(", 'tenant-contract', 'project-contract', ")
            .bind(format!("group-{workspace_id}"))
            .push_static(", ")
            .bind(format!("Contract {workspace_id}"))
            .push_static(", 'user-contract')")
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_agent_bindings (binding_id, tenant_id, project_id, \
                 workspace_id, agent_id, bot_uuid, participant_actor_id) VALUES (",
            )
            .bind(format!("binding-{workspace_id}"))
            .push_static(", 'tenant-contract', 'project-contract', ")
            .bind(workspace_id)
            .push_static(", ")
            .bind(format!("agent-{workspace_id}"))
            .push_static(", ")
            .bind(format!("bot-{workspace_id}"))
            .push_static(", ")
            .bind(format!("actor-agent-{workspace_id}"))
            .push_static(")")
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, \
                 user_id, participant_actor_id, role) VALUES (",
            )
            .bind(format!("member-{workspace_id}"))
            .push_static(", 'tenant-contract', 'project-contract', ")
            .bind(workspace_id)
            .push_static(", 'user-contract', ")
            .bind(format!("principal-user-contract-{workspace_id}"))
            .push_static(", 'owner')")
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_principal_identities (tenant_id, project_id, \
                 workspace_id, user_id, participant_actor_id, email, display_name, is_active, \
                 identity_authority, source_created_at, source_updated_at) VALUES \
                 ('tenant-contract', 'project-contract', ",
            )
            .bind(workspace_id)
            .push_static(", 'user-contract', ")
            .bind(format!("principal-user-contract-{workspace_id}"))
            .push_static(
                ", 'user-contract@example.invalid', 'Contract User', TRUE, 'memstack', \
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            )
            .build(),
    )
    .await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static(
                "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id) \
                 VALUES (",
            )
            .bind(workspace_id)
            .push_static(", 'tenant-contract', 'project-contract')")
            .build(),
    )
    .await?;
    if let Some(plan_id) = plan_id {
        db.execute(
            DbStatementBuilder::new(DbSqlFlavor::Postgres)
                .push_static(
                    "INSERT INTO workspace_plans (plan_id, tenant_id, project_id, workspace_id, \
                     collaboration_definition_id, collaboration_definition_version, goal) VALUES (",
                )
                .bind(plan_id)
                .push_static(", 'tenant-contract', 'project-contract', ")
                .bind(workspace_id)
                .push_static(", 'definition-contract', 1, 'Contract goal')")
                .build(),
        )
        .await?;
    }
    Ok(())
}

async fn seed_project_membership(db: &Arc<dyn DbPlugin>) -> Result<()> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, \
         participant_actor_id, source_membership_id, role, permissions_json, is_active, \
         identity_authority, source_created_at, source_updated_at) VALUES \
         ('tenant-contract', 'project-contract', 'user-contract', 'user-contract', \
         'project-member-contract', 'owner', '{}', TRUE, 'memstack', \
         CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    ))
    .await?;
    Ok(())
}

fn correlation_payload(
    correlation_id: &str,
    delivery_request_id: &str,
    workspace_id: &str,
    plan_id: Option<&str>,
) -> Value {
    json!({
        "correlation_id": correlation_id,
        "project_id": "project-contract",
        "workspace_id": workspace_id,
        "user_id": "user-contract",
        "plan_id": plan_id,
        "plan_node_id": plan_id.map(|_| "node-contract"),
        "conversation_id": format!("conversation-{correlation_id}"),
        "bcs_session_id": format!("session-{correlation_id}"),
        "bcs_group_id": format!("group-{workspace_id}"),
        "delivery_request_id": delivery_request_id,
        "provider_run_id": format!("provider-{delivery_request_id}"),
        "provider_id": "memstack-agent-runtime",
        "provider_bot_ref": "provider-bot-contract",
    })
}

fn recovery_claim_payload(lease_owner: &str) -> Value {
    json!({
        "lease_owner": lease_owner,
        "stale_after_seconds": 1,
        "lease_seconds": 60,
        "limit": 10,
    })
}

fn terminal_payload(workspace_id: &str, status: &str, terminal_event_id: &str) -> Value {
    json!({
        "project_id": "project-contract",
        "workspace_id": workspace_id,
        "execution_status": status,
        "terminal_message_id": format!("message-{terminal_event_id}"),
        "terminal_event_id": terminal_event_id,
        "report": {"content": "contract complete", "nested": {"b": 2, "a": 1}},
    })
}

async fn post_json(
    state: Arc<WorkspaceCoreState>,
    path: &str,
    payload: &Value,
) -> Result<(StatusCode, Value)> {
    let request = Request::builder()
        .method("POST")
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(TENANT_HEADER, "tenant-contract")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(payload.to_string()))?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    let payload = serde_json::from_slice(&body)?;
    Ok((status, payload))
}

async fn post_create_json(
    state: Arc<WorkspaceCoreState>,
    path: &str,
    payload: &Value,
) -> Result<(StatusCode, Value)> {
    let request = Request::builder()
        .method("POST")
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "user-contract")
        .header("x-memstack-user-is-superuser", "false")
        .header("x-idempotency-key", "create-contract-intent")
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(payload.to_string()))?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    let payload = serde_json::from_slice(&body)?;
    Ok((status, payload))
}

async fn post_public_create_json(
    state: Arc<WorkspaceCoreState>,
    path: &str,
    payload: &Value,
    idempotency_key: &str,
) -> Result<(StatusCode, Value)> {
    let request = Request::builder()
        .method("POST")
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "user-contract")
        .header("x-memstack-user-is-superuser", "false")
        .header("idempotency-key", idempotency_key)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(payload.to_string()))?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    let payload = serde_json::from_slice(&body)?;
    Ok((status, payload))
}

async fn get_json(state: Arc<WorkspaceCoreState>, path: &str) -> Result<(StatusCode, Value)> {
    let request = Request::builder()
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(TENANT_HEADER, "tenant-contract")
        .body(Body::empty())?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    let payload = serde_json::from_slice(&body)?;
    Ok((status, payload))
}

async fn get_public_json(
    state: Arc<WorkspaceCoreState>,
    path: &str,
    is_superuser: bool,
) -> Result<(StatusCode, Value)> {
    let request = Request::builder()
        .uri(path)
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header("x-memstack-user-id", "user-contract")
        .header("x-memstack-user-is-superuser", is_superuser.to_string())
        .body(Body::empty())?;
    let response = workspace_router(state).oneshot(request).await?;
    let status = response.status();
    let body = to_bytes(response.into_body(), usize::MAX).await?;
    let payload = serde_json::from_slice(&body)?;
    Ok((status, payload))
}

async fn workspace_revision(db: &Arc<dyn DbPlugin>, workspace_id: &str) -> Result<i64> {
    let rows = db
        .query(
            DbStatementBuilder::new(DbSqlFlavor::Postgres)
                .push_static("SELECT revision FROM workspace_authorities WHERE workspace_id = ")
                .bind(workspace_id)
                .build(),
        )
        .await?;
    rows.first()
        .ok_or_else(|| anyhow!("workspace authority is missing"))?
        .get_i64("revision")?
        .ok_or_else(|| anyhow!("workspace revision is missing"))
}

async fn wait_until_stale() {
    tokio::time::sleep(Duration::from_millis(1_100)).await;
}

async fn assert_recovery_state(
    db: &Arc<dyn DbPlugin>,
    correlation_id: &str,
    disposition: &str,
    recovery_attempt_count: i64,
    callback_attempt_count: i64,
) -> Result<()> {
    let row = db
        .query(
            DbStatementBuilder::new(DbSqlFlavor::Postgres)
                .push_static(
                    "SELECT recovery_lease_owner, recovery_disposition, \
                     recovery_attempt_count, callback_attempt_count, \
                     callback_completed_at IS NOT NULL AS callback_completed \
                     FROM workspace_agent_runtime_correlations WHERE correlation_id = ",
                )
                .bind(correlation_id)
                .build(),
        )
        .await?
        .into_iter()
        .next()
        .ok_or_else(|| anyhow!("runtime recovery state is missing"))?;
    assert_eq!(row.get_string("recovery_lease_owner")?, None);
    assert_eq!(
        row.get_string("recovery_disposition")?.as_deref(),
        Some(disposition)
    );
    assert_eq!(
        row.get_i64("recovery_attempt_count")?,
        Some(recovery_attempt_count)
    );
    assert_eq!(
        row.get_i64("callback_attempt_count")?,
        Some(callback_attempt_count)
    );
    assert_eq!(
        row.get_bool("callback_completed")?,
        Some(callback_attempt_count > 0)
    );
    Ok(())
}

async fn scoped_count(
    db: &Arc<dyn DbPlugin>,
    table: &'static str,
    workspace_id: &str,
) -> Result<i64> {
    let statement = DbStatementBuilder::new(DbSqlFlavor::Postgres)
        .push_static("SELECT COUNT(*) AS total FROM ")
        .push_identifier(bcs_db_api::DbIdentifier::new_static(table)?)
        .push_static(" WHERE workspace_id = ")
        .bind(workspace_id)
        .build();
    db.query(statement)
        .await?
        .first()
        .ok_or_else(|| anyhow!("count row is missing"))?
        .get_i64("total")?
        .ok_or_else(|| anyhow!("count is missing"))
}
