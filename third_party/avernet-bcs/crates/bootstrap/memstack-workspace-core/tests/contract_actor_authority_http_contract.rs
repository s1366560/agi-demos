use std::error::Error;
use std::sync::Arc;

use axum::body::{Body, to_bytes};
use axum::http::{Request, StatusCode, header};
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbValue, db_get_column};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_core::{
    WorkspaceCoreState, desktop_schema::run_desktop_workspace_schema_migrations, workspace_router,
};
use serde_json::{Value, json};
use tower::ServiceExt;

const SERVICE_TOKEN: &str = "contract-actor-authority-token";
const SERVICE_PRINCIPAL_ID: &str = "memstack-agent-runtime";

#[tokio::test]
async fn contract_actor_resolver_prefers_the_still_eligible_workspace_creator()
-> Result<(), Box<dyn Error>> {
    let db = seeded_database().await?;
    let state = resolver_state(Arc::clone(&db))?;

    let response = workspace_router(state)
        .oneshot(resolve_request(
            "operation-prefer-creator",
            "planner_turn",
            "workspace-live",
        )?)
        .await?;

    assert_eq!(response.status(), StatusCode::OK);
    let body = response_json(response).await?;
    assert_eq!(body["contract_version"], "2.0.0");
    assert_eq!(body["actor_user_id"], "owner-created");
    assert_eq!(body["participant_actor_id"], "human:owner-created");
    assert_eq!(body["authority_revision"], 7);
    assert_eq!(body["policy_version"], "workspace-contract-actor-owner.v1");
    assert_eq!(body["duplicate"], false);

    let audit = db
        .query(DbStatement::with_params(
            "SELECT service_principal_id, purpose, outcome, reason, resolved_actor_user_id, \
             authority_revision, request_hash, policy_version \
             FROM workspace_contract_actor_resolution_audits WHERE operation_id = ?",
            vec![DbValue::from("operation-prefer-creator")],
        ))
        .await?;
    assert_eq!(audit.len(), 1);
    assert_eq!(
        db_get_column::<String>(&audit[0], "service_principal_id")?,
        SERVICE_PRINCIPAL_ID
    );
    assert_eq!(
        db_get_column::<String>(&audit[0], "purpose")?,
        "planner_turn"
    );
    assert_eq!(db_get_column::<String>(&audit[0], "outcome")?, "resolved");
    assert_eq!(db_get_column::<String>(&audit[0], "reason")?, "resolved");
    assert_eq!(
        db_get_column::<String>(&audit[0], "resolved_actor_user_id")?,
        "owner-created"
    );
    assert_eq!(db_get_column::<i64>(&audit[0], "authority_revision")?, 7);
    assert_eq!(
        db_get_column::<String>(&audit[0], "policy_version")?,
        "workspace-contract-actor-owner.v1"
    );
    let request_hash = db_get_column::<String>(&audit[0], "request_hash")?;
    assert_eq!(request_hash.len(), 64);
    assert!(request_hash.bytes().all(|byte| byte.is_ascii_hexdigit()));
    Ok(())
}

#[tokio::test]
async fn contract_actor_resolver_uses_the_only_eligible_owner_when_creator_is_inactive()
-> Result<(), Box<dyn Error>> {
    let db = seeded_database().await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_principal_identities SET is_active = 0 \
         WHERE workspace_id = 'workspace-live' AND user_id = 'owner-created'",
    ))
    .await?;
    let state = resolver_state(db)?;

    let response = workspace_router(state)
        .oneshot(resolve_request(
            "operation-unique-owner",
            "supervisor_turn",
            "workspace-live",
        )?)
        .await?;

    assert_eq!(response.status(), StatusCode::OK);
    let body = response_json(response).await?;
    assert_eq!(body["actor_user_id"], "owner-second");
    assert_eq!(body["participant_actor_id"], "human:owner-second");
    Ok(())
}

#[tokio::test]
async fn contract_actor_resolver_replays_audited_rejection_and_rejects_operation_drift()
-> Result<(), Box<dyn Error>> {
    let db = seeded_database().await?;
    db.execute(DbStatement::new(
        "UPDATE workspace_profiles SET created_by = 'former-owner' \
         WHERE workspace_id = 'workspace-live'",
    ))
    .await?;
    let state = resolver_state(Arc::clone(&db))?;

    let first = workspace_router(Arc::clone(&state))
        .oneshot(resolve_request(
            "operation-ambiguous",
            "verifier_turn",
            "workspace-live",
        )?)
        .await?;
    assert_eq!(first.status(), StatusCode::CONFLICT);
    let first = response_json(first).await?;
    assert_eq!(first["code"], "workspace_contract_actor_owner_ambiguous");

    db.execute(DbStatement::new(
        "UPDATE workspace_principal_identities SET is_active = 0 \
         WHERE workspace_id = 'workspace-live' AND user_id = 'owner-second'",
    ))
    .await?;
    let replay = workspace_router(Arc::clone(&state))
        .oneshot(resolve_request(
            "operation-ambiguous",
            "verifier_turn",
            "workspace-live",
        )?)
        .await?;
    assert_eq!(replay.status(), StatusCode::CONFLICT);
    let replay = response_json(replay).await?;
    assert_eq!(replay["code"], "workspace_contract_actor_owner_ambiguous");
    assert_eq!(replay["duplicate"], true);

    let drift = workspace_router(state)
        .oneshot(resolve_request(
            "operation-ambiguous",
            "worktree_turn",
            "workspace-live",
        )?)
        .await?;
    assert_eq!(drift.status(), StatusCode::CONFLICT);
    let drift = response_json(drift).await?;
    assert_eq!(
        drift["code"],
        "workspace_contract_actor_idempotency_conflict"
    );

    let rows = db
        .query(DbStatement::new(
            "SELECT COUNT(*) AS row_count FROM workspace_contract_actor_resolution_audits \
             WHERE service_principal_id = 'memstack-agent-runtime' \
               AND operation_id = 'operation-ambiguous'",
        ))
        .await?;
    assert_eq!(db_get_column::<i64>(&rows[0], "row_count")?, 1);
    Ok(())
}

#[tokio::test]
async fn contract_actor_resolver_rejects_inactive_scope_and_missing_owner_without_fallback()
-> Result<(), Box<dyn Error>> {
    let db = seeded_database().await?;
    let state = resolver_state(Arc::clone(&db))?;

    let archived = workspace_router(Arc::clone(&state))
        .oneshot(resolve_request(
            "operation-archived",
            "worktree_turn",
            "workspace-archived",
        )?)
        .await?;
    assert_eq!(archived.status(), StatusCode::CONFLICT);
    let archived = response_json(archived).await?;
    assert_eq!(
        archived["code"],
        "workspace_contract_actor_workspace_inactive"
    );

    db.execute(DbStatement::new(
        "UPDATE workspace_principal_identities SET is_active = 0 \
         WHERE workspace_id = 'workspace-live'",
    ))
    .await?;
    let unavailable = workspace_router(state)
        .oneshot(resolve_request(
            "operation-owner-unavailable",
            "iteration_review_turn",
            "workspace-live",
        )?)
        .await?;
    assert_eq!(unavailable.status(), StatusCode::CONFLICT);
    let unavailable = response_json(unavailable).await?;
    assert_eq!(
        unavailable["code"],
        "workspace_contract_actor_owner_unavailable"
    );
    Ok(())
}

#[tokio::test]
async fn contract_actor_resolver_requires_server_bound_capability_and_strict_payload()
-> Result<(), Box<dyn Error>> {
    let db = seeded_database().await?;
    let state_without_capability = Arc::new(WorkspaceCoreState::new_with_sql_flavor(
        db.clone(),
        SERVICE_TOKEN.to_string(),
        DbSqlFlavor::Sqlite,
    )?);

    let forbidden = workspace_router(state_without_capability)
        .oneshot(resolve_request(
            "operation-no-capability",
            "planner_turn",
            "workspace-live",
        )?)
        .await?;
    assert_eq!(forbidden.status(), StatusCode::FORBIDDEN);
    let forbidden = response_json(forbidden).await?;
    assert_eq!(
        forbidden["code"],
        "workspace_contract_actor_capability_denied"
    );

    let injected_actor = Request::builder()
        .method("POST")
        .uri("/internal/v2/workspace-authority/contract-actor:resolve")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "workspace_id": "workspace-live",
                "purpose": "planner_turn",
                "operation_id": "operation-injected-actor",
                "actor": {"user_id": "attacker", "is_superuser": true}
            })
            .to_string(),
        ))?;
    let invalid = workspace_router(resolver_state(db)?)
        .oneshot(injected_actor)
        .await?;
    assert_eq!(invalid.status(), StatusCode::UNPROCESSABLE_ENTITY);
    Ok(())
}

#[tokio::test]
async fn contract_actor_resolver_fails_closed_when_audit_cannot_be_persisted()
-> Result<(), Box<dyn Error>> {
    let db = seeded_database().await?;
    db.execute(DbStatement::new(
        "DROP TABLE workspace_contract_actor_resolution_audits",
    ))
    .await?;
    let state = resolver_state(db)?;

    let response = workspace_router(state)
        .oneshot(resolve_request(
            "operation-audit-failure",
            "planner_turn",
            "workspace-live",
        )?)
        .await?;

    assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
    let body = response_json(response).await?;
    assert_eq!(
        body["code"],
        "workspace_contract_actor_authority_unavailable"
    );
    Ok(())
}

fn resolver_state(db: Arc<LocalSqliteDbPlugin>) -> Result<Arc<WorkspaceCoreState>, &'static str> {
    WorkspaceCoreState::new_with_sql_flavor(db, SERVICE_TOKEN.to_string(), DbSqlFlavor::Sqlite)?
        .with_contract_actor_resolver_principal(SERVICE_PRINCIPAL_ID.to_string())
        .map(Arc::new)
}

fn resolve_request(
    operation_id: &str,
    purpose: &str,
    workspace_id: &str,
) -> Result<Request<Body>, Box<dyn Error>> {
    Ok(Request::builder()
        .method("POST")
        .uri("/internal/v2/workspace-authority/contract-actor:resolve")
        .header(header::AUTHORIZATION, format!("Bearer {SERVICE_TOKEN}"))
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            json!({
                "tenant_id": "tenant-1",
                "project_id": "project-1",
                "workspace_id": workspace_id,
                "purpose": purpose,
                "operation_id": operation_id
            })
            .to_string(),
        ))?)
}

async fn response_json(response: axum::response::Response) -> Result<Value, Box<dyn Error>> {
    Ok(serde_json::from_slice(
        &to_bytes(response.into_body(), usize::MAX).await?,
    )?)
}

async fn seeded_database() -> Result<Arc<LocalSqliteDbPlugin>, Box<dyn Error>> {
    let db = Arc::new(LocalSqliteDbPlugin::new()?);
    bcs::migrations::run_sqlite_migrations(db.as_ref()).await?;
    run_desktop_workspace_schema_migrations(db.as_ref()).await?;
    for statement in [
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, permissions_json, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-1', 'project-1', 'owner-created', 'human:owner-created', 'project-member-created', 'owner', '{}', 1, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, permissions_json, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-1', 'project-1', 'owner-second', 'human:owner-second', 'project-member-second', 'owner', '{}', 1, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by, is_archived, metadata_json) VALUES ('workspace-live', 'tenant-1', 'project-1', 'group-live', 'Live Workspace', 'owner-created', 0, '{}')",
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by, is_archived, metadata_json) VALUES ('workspace-archived', 'tenant-1', 'project-1', 'group-archived', 'Archived Workspace', 'owner-created', 1, '{}')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-created', 'tenant-1', 'project-1', 'workspace-live', 'owner-created', 'human:owner-created', 'owner')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-second', 'tenant-1', 'project-1', 'workspace-live', 'owner-second', 'human:owner-second', 'owner')",
        "INSERT INTO workspace_members (member_id, tenant_id, project_id, workspace_id, user_id, participant_actor_id, role) VALUES ('member-archived', 'tenant-1', 'project-1', 'workspace-archived', 'owner-created', 'human:owner-created', 'owner')",
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, participant_actor_id, email, display_name, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-1', 'project-1', 'workspace-live', 'owner-created', 'human:owner-created', 'created@example.invalid', 'Created owner', 1, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, participant_actor_id, email, display_name, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-1', 'project-1', 'workspace-live', 'owner-second', 'human:owner-second', 'second@example.invalid', 'Second owner', 1, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_principal_identities (tenant_id, project_id, workspace_id, user_id, participant_actor_id, email, display_name, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-1', 'project-1', 'workspace-archived', 'owner-created', 'human:owner-created', 'created@example.invalid', 'Created owner', 1, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('workspace-live', 'tenant-1', 'project-1', 7)",
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('workspace-archived', 'tenant-1', 'project-1', 3)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}
