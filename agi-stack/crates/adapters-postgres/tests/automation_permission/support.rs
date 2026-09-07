use agistack_adapters_postgres::{
    AutomationPermissionAnswerCommand, AutomationPermissionIntentCommand,
    PgAutomationPermissionStore,
};
use agistack_core::automation_permission::{HostPermissionBinding, PermissionAnswer};
use chrono::Duration;
use serde_json::json;

pub use crate::admission_support::{now, Fixture};

pub async fn seed(f: &Fixture) {
    f.seed().await;
    sqlx::raw_sql(include_str!("schema.sql"))
        .execute(&f.pool)
        .await
        .unwrap();
    for sql in [
        "ALTER TABLE hitl_requests ADD COLUMN user_id text",
        "CREATE TABLE users (id text PRIMARY KEY, is_active boolean NOT NULL)",
        "CREATE TABLE projects (id text PRIMARY KEY, tenant_id text NOT NULL, owner_id text)",
        "CREATE TABLE user_tenants (user_id text, tenant_id text)",
        "CREATE TABLE user_projects (user_id text, project_id text, role text)",
        "CREATE TABLE api_keys (id text PRIMARY KEY, user_id text, is_active boolean, expires_at timestamptz, permissions json)",
        "CREATE TABLE conversations (id text PRIMARY KEY, tenant_id text, user_id text)",
        "INSERT INTO users VALUES ('responder',true),('actor',true)",
        "INSERT INTO projects VALUES ('project','tenant','project-owner')",
        "INSERT INTO api_keys VALUES ('actor-key','actor',true,NULL,'[]')",
        "INSERT INTO conversations VALUES ('conversation','tenant','responder')",
        "INSERT INTO user_tenants VALUES ('responder','tenant'),('actor','tenant')",
        "INSERT INTO user_projects VALUES ('responder','project','member'),('actor','project','member')",
        "UPDATE hitl_requests SET request_type='permission', status='pending', response_metadata=NULL, answered_at=NULL, user_id='responder'",
        "UPDATE agistack_checkpoints SET state=jsonb_set(state,'{pending_hitl,kind}','\"permission\"')",
    ] { sqlx::query(sql).execute(&f.pool).await.unwrap(); }
}

pub fn intent(f: &Fixture) -> AutomationPermissionIntentCommand {
    AutomationPermissionIntentCommand {
        id: "intent".into(), scope: f.command(),
        binding: HostPermissionBinding::from_host_observation("invocation".into(), "write".into(), "1.2.0".into(), "a".repeat(64)),
        decision: serde_json::from_value(json!({
            "action":{"name":"write","label":"Write file"},
            "target":{"kind":"file","id":"file-1","version_id":"v3"},
            "data":{"summary":"Update the requested document"},
            "reason":"User requested this edit", "risk":{"level":"low","rationale":"One scoped document"},
            "reversibility":{"mode":"reversible","recovery":"Restore prior version"},
            "scope":{"kind":"project","ids":["project"]},
            "evidence":[{"kind":"request","id":"request","label":"Requested edit"}]
        })).unwrap(), expires_at: now()+Duration::minutes(4),
    }
}

pub fn answer(f: &Fixture, outcome: PermissionAnswer) -> AutomationPermissionAnswerCommand {
    AutomationPermissionAnswerCommand {
        intent_id: "intent".into(),
        scope: f.command(),
        responder_user_id: "responder".into(),
        idempotency_key: "answer-key".into(),
        answer: outcome,
    }
}

pub async fn record(f: &Fixture) {
    assert_eq!(
        PgAutomationPermissionStore::new(f.pool.clone())
            .record_intent(&intent(f), now())
            .await
            .unwrap(),
        agistack_adapters_postgres::AutomationPermissionOutcome::Applied
    );
}

pub async fn count(f: &Fixture, table: &str) -> i64 {
    assert!([
        "agistack_automation_permission_intents",
        "agistack_automation_permission_receipts",
        "agistack_automation_permission_consumptions"
    ]
    .contains(&table));
    sqlx::query_scalar(&format!("SELECT count(*) FROM {table}"))
        .fetch_one(&f.pool)
        .await
        .unwrap()
}
