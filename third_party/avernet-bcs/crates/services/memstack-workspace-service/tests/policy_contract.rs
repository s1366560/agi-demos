use std::error::Error;

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement};
use bcs_db_local::LocalSqliteDbPlugin;
use memstack_workspace_service::{
    PublicPatchWorkspacePolicyInput, PublicPolicyRouteTarget, PublicWorkspacePolicyContext,
    PublicWorkspacePolicyErrorKind, PublicWorkspacePolicyService,
};
use memstack_workspace_service_api::{
    ProviderRegistryLookup, ProviderRegistryPort, ProviderRegistryPortError, ProviderRegistryRoute,
    TenantId,
};

struct FakeProviderRegistry;

#[async_trait]
impl ProviderRegistryPort for FakeProviderRegistry {
    async fn resolve(
        &self,
        lookup: &ProviderRegistryLookup,
    ) -> Result<Option<ProviderRegistryRoute>, ProviderRegistryPortError> {
        if lookup.provider_id().as_str() == "provider-1" && lookup.model_id().as_str() == "model-1"
        {
            return ProviderRegistryRoute::parse("provider-1", "model-1")
                .map(Some)
                .map_err(|_| ProviderRegistryPortError::Unavailable);
        }
        Ok(None)
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
async fn policy_default_patch_replay_cas_and_outbox_are_atomic() -> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let registry = FakeProviderRegistry;
    let service = PublicWorkspacePolicyService::new(&db, DbSqlFlavor::Sqlite, &registry);
    let context = policy_context("project-owner");

    let default = service.get(&context).await?;
    assert_eq!(default["revision"], 0);
    assert_eq!(default["roles"]["default"]["provider_id"], "provider-1");
    assert_eq!(default["roles"]["coding"]["model_id"], "model-1");

    let input = PublicPatchWorkspacePolicyInput {
        context,
        expected_revision: 0,
        capability_mode: "code".to_string(),
        route: PublicPolicyRouteTarget {
            provider_id: "provider-1".to_string(),
            model_id: "model-1".to_string(),
        },
        reasoning_effort: "high".to_string(),
        permission_mode: "automatic".to_string(),
    };
    let committed = service.patch(&input).await?;
    let replayed = service.patch(&input).await?;

    assert_eq!(committed, replayed);
    assert_eq!(committed["revision"], 1);
    assert_eq!(committed["roles"]["coding"]["model_id"], "model-1");
    assert_eq!(committed["reasoning_effort"], "high");
    assert_eq!(
        scalar_i64(&db, "SELECT revision AS value FROM workspace_authorities").await?,
        8
    );
    assert_eq!(
        scalar_i64(
            &db,
            "SELECT revision AS value FROM workspace_agent_policies"
        )
        .await?,
        1
    );
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    assert_eq!(
        scalar_string(&db, "SELECT event_type AS value FROM workspace_outbox").await?,
        "workspace_agent_policy_updated"
    );
    assert_eq!(
        scalar_string(
            &db,
            "SELECT action AS value FROM workspace_mutation_receipts"
        )
        .await?,
        "update_agent_policy"
    );

    let stale = match service
        .patch(&PublicPatchWorkspacePolicyInput {
            reasoning_effort: "low".to_string(),
            ..input
        })
        .await
    {
        Ok(_) => return Err("stale policy revision must fail".into()),
        Err(error) => error,
    };
    assert_eq!(stale.kind(), PublicWorkspacePolicyErrorKind::Conflict);
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        1
    );
    Ok(())
}

#[tokio::test]
async fn policy_rejects_unregistered_routes_and_non_manager_access() -> Result<(), Box<dyn Error>> {
    let db = seeded_db().await?;
    let registry = FakeProviderRegistry;
    let service = PublicWorkspacePolicyService::new(&db, DbSqlFlavor::Sqlite, &registry);

    let invalid = match service
        .patch(&PublicPatchWorkspacePolicyInput {
            context: policy_context("project-owner"),
            expected_revision: 0,
            capability_mode: "work".to_string(),
            route: PublicPolicyRouteTarget {
                provider_id: "missing-provider".to_string(),
                model_id: "missing-model".to_string(),
            },
            reasoning_effort: "medium".to_string(),
            permission_mode: "ask".to_string(),
        })
        .await
    {
        Ok(_) => return Err("unregistered Provider route must fail".into()),
        Err(error) => error,
    };
    assert_eq!(invalid.kind(), PublicWorkspacePolicyErrorKind::Validation);

    let forbidden = match service
        .patch(&PublicPatchWorkspacePolicyInput {
            context: policy_context("project-viewer"),
            expected_revision: 0,
            capability_mode: "work".to_string(),
            route: PublicPolicyRouteTarget {
                provider_id: "provider-1".to_string(),
                model_id: "model-1".to_string(),
            },
            reasoning_effort: "medium".to_string(),
            permission_mode: "ask".to_string(),
        })
        .await
    {
        Ok(_) => return Err("project viewer policy mutation must fail".into()),
        Err(error) => error,
    };
    assert_eq!(forbidden.kind(), PublicWorkspacePolicyErrorKind::Forbidden);
    assert_eq!(
        scalar_i64(&db, "SELECT COUNT(*) AS value FROM workspace_outbox").await?,
        0
    );
    Ok(())
}

fn policy_context(actor_id: &str) -> PublicWorkspacePolicyContext {
    PublicWorkspacePolicyContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: "workspace-1".to_string(),
        actor_id: actor_id.to_string(),
    }
}

async fn seeded_db() -> Result<LocalSqliteDbPlugin, Box<dyn Error>> {
    let db = LocalSqliteDbPlugin::new()?;
    for ddl in [
        "CREATE TABLE project_principal_memberships (tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, is_active INTEGER NOT NULL, PRIMARY KEY (tenant_id, project_id, user_id))",
        "CREATE TABLE workspace_profiles (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, group_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, deleted_at TEXT, UNIQUE(tenant_id, project_id, workspace_id))",
        "CREATE TABLE workspace_members (member_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, participant_actor_id TEXT NOT NULL, role TEXT NOT NULL, UNIQUE(workspace_id, user_id))",
        "CREATE TABLE workspace_agent_policies (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, roles_json TEXT NOT NULL DEFAULT '{}', fallbacks_json TEXT NOT NULL DEFAULT '[]', reasoning_effort TEXT NOT NULL DEFAULT 'medium', permission_mode TEXT NOT NULL DEFAULT 'ask', updated_by TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_authorities (workspace_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, revision INTEGER NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)",
        "CREATE TABLE workspace_mutation_receipts (receipt_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, actor_id TEXT NOT NULL, contract_version TEXT NOT NULL, surface TEXT NOT NULL, action TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, expected_revision INTEGER NOT NULL, committed_revision INTEGER, response_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, committed_at TEXT, UNIQUE(workspace_id, actor_id, idempotency_key))",
        "CREATE TABLE workspace_outbox (outbox_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, workspace_id TEXT NOT NULL, aggregate_type TEXT NOT NULL, aggregate_id TEXT NOT NULL, event_type TEXT NOT NULL, stream_name TEXT NOT NULL, event_sequence INTEGER NOT NULL, payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, correlation_id TEXT, idempotency_key TEXT NOT NULL, UNIQUE(workspace_id, idempotency_key), UNIQUE(workspace_id, stream_name, event_sequence))",
    ] {
        db.execute(DbStatement::new(ddl)).await?;
    }
    for statement in [
        "INSERT INTO workspace_profiles (workspace_id, tenant_id, project_id, group_id, name, created_by) VALUES ('workspace-1', 'tenant-1', 'project-1', 'group-1', 'Policy Space', 'workspace-owner')",
        "INSERT INTO workspace_authorities (workspace_id, tenant_id, project_id, revision) VALUES ('workspace-1', 'tenant-1', 'project-1', 7)",
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, role, is_active) VALUES ('tenant-1', 'project-1', 'project-owner', 'project-owner', 'owner', 1)",
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, role, is_active) VALUES ('tenant-1', 'project-1', 'project-viewer', 'project-viewer', 'viewer', 1)",
    ] {
        db.execute(DbStatement::new(statement)).await?;
    }
    Ok(db)
}

async fn scalar_i64(db: &dyn DbPlugin, sql: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn scalar_string(db: &dyn DbPlugin, sql: &str) -> Result<String, Box<dyn Error>> {
    let rows = db.query(DbStatement::new(sql)).await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}
