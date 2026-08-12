use std::collections::BTreeMap;
use std::error::Error;

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use memstack_workspace_service::{
    PublicPatchWorkspacePolicyInput, PublicPolicyRouteTarget, PublicPutWorkspacePolicyInput,
    PublicWorkspacePolicyContext, PublicWorkspacePolicyErrorKind, PublicWorkspacePolicyService,
};
use memstack_workspace_service_api::{
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
    TenantId,
};

const WORKSPACE_ID: &str = "workspace-policy-pg-contract";
const TENANT_ID: &str = "tenant-policy-contract";
const PROJECT_ID: &str = "project-policy-contract";
const ACTOR_ID: &str = "actor-policy-pg-contract";

struct StaticProviderRegistry;

#[async_trait]
impl ProviderRegistryPort for StaticProviderRegistry {
    async fn resolve(
        &self,
        lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        let allowed = matches!(
            (lookup.provider_id().as_str(), lookup.model_id().as_str()),
            ("provider-1", "model-1") | ("provider-2", "model-2")
        );
        if !allowed {
            return Ok(None);
        }
        ProviderRegistryRoute::parse(lookup.provider_id().as_str(), lookup.model_id().as_str())
            .map(Some)
            .map_err(|_| ProviderRegistryPortError::Unavailable)
    }

    async fn tenant_default(
        &self,
        _tenant_id: &TenantId,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        ProviderRegistryRoute::parse("provider-1", "model-1")
            .map(Some)
            .map_err(|_| ProviderRegistryPortError::Unavailable)
    }
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_policy_jsonb_cas_replay_receipt_and_outbox_are_atomic()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_scope(&db).await?;
    let registry = StaticProviderRegistry;
    let service = PublicWorkspacePolicyService::new(&db, DbSqlFlavor::Postgres, &registry);

    let default = service.get(&context()).await?;
    assert_eq!(default["revision"], 0);
    assert_eq!(default["roles"]["default"]["provider_id"], "provider-1");

    let patch = PublicPatchWorkspacePolicyInput {
        context: context(),
        expected_revision: 0,
        capability_mode: "code".to_string(),
        route: route("provider-1", "model-1"),
        reasoning_effort: "high".to_string(),
        permission_mode: "automatic".to_string(),
    };
    let patched = service.patch(&patch).await?;
    let replayed = service.patch(&patch).await?;
    assert_eq!(patched, replayed);
    assert_eq!(patched["revision"], 1);

    let replaced = service
        .put_legacy(&PublicPutWorkspacePolicyInput {
            project_id: PROJECT_ID.to_string(),
            workspace_id: WORKSPACE_ID.to_string(),
            actor_id: ACTOR_ID.to_string(),
            expected_revision: 1,
            roles: BTreeMap::from([
                ("default".to_string(), Some(route("provider-2", "model-2"))),
                ("fast".to_string(), None),
                ("coding".to_string(), None),
                ("vision".to_string(), None),
            ]),
            fallbacks: vec![route("provider-1", "model-1")],
        })
        .await?;
    assert_eq!(replaced["revision"], 2);
    assert_eq!(replaced["roles"]["default"]["provider_id"], "provider-2");

    assert_eq!(policy_i64(&db, "revision").await?, 2);
    assert_eq!(authority_revision(&db).await?, 7);
    assert_eq!(
        workspace_count(&db, "workspace_mutation_receipts").await?,
        2
    );
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 2);
    assert_eq!(policy_string(&db, "roles_json_type").await?, "jsonb");
    assert_eq!(policy_string(&db, "default_provider").await?, "provider-2");

    let stale = match service
        .patch(&PublicPatchWorkspacePolicyInput {
            context: context(),
            expected_revision: 1,
            capability_mode: "work".to_string(),
            route: route("provider-1", "model-1"),
            reasoning_effort: "low".to_string(),
            permission_mode: "ask".to_string(),
        })
        .await
    {
        Ok(_) => return Err("stale PostgreSQL policy revision must fail".into()),
        Err(error) => error,
    };
    assert_eq!(stale.kind(), PublicWorkspacePolicyErrorKind::Conflict);
    assert_eq!(policy_i64(&db, "revision").await?, 2);
    assert_eq!(authority_revision(&db).await?, 7);
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 2);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create a fault-injection trigger"]
async fn postgres_policy_outbox_failure_rolls_back_policy_receipt_and_authority()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_scope(&db).await?;
    drop_fault_trigger(&db).await?;
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_workspace_policy_outbox() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-policy-pg-contract' AND NEW.event_type = 'workspace_agent_policy_updated' THEN RAISE EXCEPTION 'injected policy outbox failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_workspace_policy_outbox BEFORE INSERT ON workspace_outbox FOR EACH ROW EXECUTE FUNCTION avernet.reject_workspace_policy_outbox()",
    ))
    .await?;

    let registry = StaticProviderRegistry;
    let error = match PublicWorkspacePolicyService::new(&db, DbSqlFlavor::Postgres, &registry)
        .patch(&PublicPatchWorkspacePolicyInput {
            context: context(),
            expected_revision: 0,
            capability_mode: "work".to_string(),
            route: route("provider-1", "model-1"),
            reasoning_effort: "medium".to_string(),
            permission_mode: "ask".to_string(),
        })
        .await
    {
        Ok(_) => return Err("fault-injected PostgreSQL policy mutation must fail".into()),
        Err(error) => error,
    };
    drop_fault_trigger(&db).await?;

    assert_eq!(error.kind(), PublicWorkspacePolicyErrorKind::Unavailable);
    assert_eq!(authority_revision(&db).await?, 5);
    assert_eq!(workspace_count(&db, "workspace_agent_policies").await?, 0);
    assert_eq!(
        workspace_count(&db, "workspace_mutation_receipts").await?,
        0
    );
    assert_eq!(workspace_count(&db, "workspace_outbox").await?, 0);
    cleanup(&db).await?;
    Ok(())
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

fn context() -> PublicWorkspacePolicyContext {
    PublicWorkspacePolicyContext {
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        actor_id: ACTOR_ID.to_string(),
    }
}

fn route(provider_id: &str, model_id: &str) -> PublicPolicyRouteTarget {
    PublicPolicyRouteTarget {
        provider_id: provider_id.to_string(),
        model_id: model_id.to_string(),
    }
}

async fn seed_scope(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-policy-contract', 'project-policy-contract', 'actor-policy-pg-contract', 'actor-policy-pg-contract', 'membership-policy-pg-contract', 'owner', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by) VALUES ('workspace-policy-pg-contract', 'tenant-policy-contract', 'project-policy-contract', 'group-policy-pg-contract', 'PostgreSQL Policy Contract', 'actor-policy-pg-contract')",
    ))
    .await?;
    db.execute(DbStatement::new(
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('workspace-policy-pg-contract', 'tenant-policy-contract', 'project-policy-contract', 5)",
    ))
    .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    drop_fault_trigger(db).await?;
    db.execute(
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
    )
    .await?;
    db.execute(DbStatement::new(
        "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-policy-pg-contract'",
    ))
    .await?;
    Ok(())
}

async fn drop_fault_trigger(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_workspace_policy_outbox ON workspace_outbox",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_workspace_policy_outbox()",
    ))
    .await?;
    Ok(())
}

async fn workspace_count(db: &dyn DbPlugin, table: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match table {
        "workspace_agent_policies" => {
            "SELECT COUNT(*) AS value FROM workspace_agent_policies WHERE workspace_id = $1"
        }
        "workspace_mutation_receipts" => {
            "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1"
        }
        "workspace_outbox" => {
            "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1"
        }
        _ => return Err("unsupported table".into()),
    };
    query_i64(db, sql).await
}

async fn authority_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
    )
    .await
}

async fn policy_i64(db: &dyn DbPlugin, field: &str) -> Result<i64, Box<dyn Error>> {
    let sql = match field {
        "revision" => {
            "SELECT revision AS value FROM workspace_agent_policies WHERE workspace_id = $1"
        }
        _ => return Err("unsupported field".into()),
    };
    query_i64(db, sql).await
}

async fn policy_string(db: &dyn DbPlugin, field: &str) -> Result<String, Box<dyn Error>> {
    let sql = match field {
        "roles_json_type" => {
            "SELECT pg_typeof(roles_json)::text AS value FROM workspace_agent_policies WHERE workspace_id = $1"
        }
        "default_provider" => {
            "SELECT roles_json -> 'default' ->> 'provider_id' AS value FROM workspace_agent_policies WHERE workspace_id = $1"
        }
        _ => return Err("unsupported field".into()),
    };
    let rows = db
        .query(DbStatement::with_params(sql, vec![WORKSPACE_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}

async fn query_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![WORKSPACE_ID.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}
