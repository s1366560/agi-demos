//! Reads the canonical run rows and the existing Workspace Core permission ceiling.
use super::*;
use crate::workspace_authority::SharedWorkspaceAuthority;
use sqlx::{FromRow, PgPool};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub(super) struct RunAuthority {
    pub run_id: String,
    pub run_kind: String,
    pub permission_profile: String,
    pub authorization_revision: i32,
    pub plan_version_id: String,
    pub allowed_mcp_servers: Vec<String>,
    pub agent_profile: agent_profile::AgentProfile,
}
#[derive(FromRow)]
struct RunRow {
    id: String,
    run_kind: String,
    permission_profile: String,
    revision: i32,
    plan_version_id: Option<String>,
    authorization_snapshot: Value,
    workspace_id: Option<String>,
    plan_profile: Option<String>,
    plan_status: Option<String>,
    plan_snapshot: Option<Value>,
    status: String,
}
pub(super) const RUN_SQL: &str = "SELECT r.id,r.run_kind,r.permission_profile,r.revision,r.plan_version_id,r.authorization_snapshot,c.workspace_id,r.status,p.permission_profile AS plan_profile,p.status AS plan_status,p.authorization_snapshot AS plan_snapshot
 FROM agent_run_authorities r JOIN conversations c ON c.id=r.conversation_id
 JOIN users u ON u.id=c.user_id AND u.is_active=true
 JOIN projects pr ON pr.id=r.project_id AND pr.tenant_id=r.tenant_id
 LEFT JOIN agent_plan_runs p ON p.id=r.plan_run_id AND p.id=r.id AND p.plan_version_id=r.plan_version_id AND p.project_id=r.project_id AND p.conversation_id=r.conversation_id
 WHERE c.user_id=$1 AND c.tenant_id=$2 AND c.project_id=$3 AND c.id=$4
 AND r.tenant_id=c.tenant_id AND r.project_id=c.project_id AND r.status IN ('queued','running')
 AND ($5::text IS NULL OR r.id=$5) AND ($6::text IS NULL OR r.message_id=$6)
 AND EXISTS(SELECT 1 FROM user_projects up WHERE up.user_id=c.user_id AND up.project_id=c.project_id)
 AND EXISTS(SELECT 1 FROM user_tenants ut WHERE ut.user_id=c.user_id AND ut.tenant_id=c.tenant_id)
 ORDER BY r.created_at DESC LIMIT 1";

#[async_trait]
pub(super) trait Authority: Send + Sync {
    async fn prepare(
        &self,
        owner: &Owner,
        conversation: &str,
        message_id: &str,
        message: &str,
    ) -> CoreResult<RunAuthority>;
    async fn recheck(
        &self,
        owner: &Owner,
        conversation: &str,
        expected: &RunAuthority,
    ) -> CoreResult<()>;
    async fn recheck_running(
        &self,
        owner: &Owner,
        conversation: &str,
        expected: &RunAuthority,
    ) -> CoreResult<()>;
    async fn finish(&self, _owner: &Owner, _run: &RunAuthority) {}
}
pub(super) struct PgAuthority {
    pub pool: Option<PgPool>,
    pub workspace: SharedWorkspaceAuthority,
}
fn denied() -> CoreError {
    CoreError::Tool("computer_use_run_authority_denied".into())
}
fn level(profile: &str) -> CoreResult<u8> {
    match profile {
        "read_only" => Ok(0),
        "workspace_write" => Ok(1),
        "full_access" => Ok(2),
        _ => Err(denied()),
    }
}
fn profile(policy: &Value) -> CoreResult<&str> {
    match policy["permission_mode"].as_str() {
        Some("ask") => Ok("read_only"),
        Some("automatic") => Ok("workspace_write"),
        Some("full_access") => Ok("full_access"),
        _ => Err(denied()),
    }
}
impl PgAuthority {
    async fn pin_agent(
        &self,
        owner: &Owner,
        conversation: &str,
        mut row: RunRow,
    ) -> CoreResult<RunRow> {
        let pool = self.pool.as_ref().ok_or_else(denied)?;
        let current = agent_profile::load(pool, owner, conversation).await?;
        if row
            .authorization_snapshot
            .get(agent_profile::SNAPSHOT_KEY)
            .is_none()
        {
            let updated:Option<Value>=sqlx::query_scalar("UPDATE agent_run_authorities SET authorization_snapshot=jsonb_set(authorization_snapshot::jsonb,'{computer_use_agent_profile}',$1::jsonb),updated_at=NOW() WHERE id=$2 AND tenant_id=$3 AND project_id=$4 AND conversation_id=$5 AND revision=$6 AND status IN ('queued','running') AND NOT(authorization_snapshot::jsonb ? 'computer_use_agent_profile') RETURNING authorization_snapshot")
                .bind(json!(current)).bind(&row.id).bind(&owner.tenant_id).bind(&owner.project_id).bind(conversation).bind(row.revision).fetch_optional(pool).await.map_err(|_|denied())?;
            row.authorization_snapshot = match updated {
                Some(snapshot) => snapshot,
                None => {
                    self.load(owner, conversation, Some(&row.id), None)
                        .await?
                        .ok_or_else(denied)?
                        .authorization_snapshot
                }
            };
        }
        agent_profile::pinned(&row.authorization_snapshot, &current)?;
        Ok(row)
    }
    async fn policy(&self, owner: &Owner, workspace: Option<&str>) -> CoreResult<Value> {
        if let Some(workspace) = workspace {
            self.workspace
                .read_agent_policy(
                    &owner.user_id,
                    &owner.tenant_id,
                    &owner.project_id,
                    workspace,
                )
                .await
                .map_err(|_| denied())
        } else {
            Ok(json!({"revision":0,"permission_mode":"ask","source":"unbound_chat_default"}))
        }
    }
    async fn load(
        &self,
        owner: &Owner,
        conversation: &str,
        run: Option<&str>,
        message: Option<&str>,
    ) -> CoreResult<Option<RunRow>> {
        sqlx::query_as::<_, RunRow>(RUN_SQL)
            .bind(&owner.user_id)
            .bind(&owner.tenant_id)
            .bind(&owner.project_id)
            .bind(conversation)
            .bind(run)
            .bind(message)
            .fetch_optional(self.pool.as_ref().ok_or_else(denied)?)
            .await
            .map_err(|_| denied())
    }
    async fn validate(
        &self,
        owner: &Owner,
        conversation: &str,
        row: RunRow,
    ) -> CoreResult<RunAuthority> {
        let policy = self.policy(owner, row.workspace_id.as_deref()).await?;
        if level(&row.permission_profile)? > level(profile(&policy)?)?
            || row
                .authorization_snapshot
                .get("cancellation_receipt")
                .is_some_and(|v| !v.is_null())
        {
            return Err(denied());
        }
        let snapshot = &row.authorization_snapshot;
        let selected = agent_profile::pinned(
            snapshot,
            &agent_profile::load(self.pool.as_ref().ok_or_else(denied)?, owner, conversation)
                .await?,
        )?;
        match row.run_kind.as_str() {
            "chat" => {
                if snapshot["source"] != "chat_admission"
                    || snapshot["schema_version"] != 1
                    || snapshot["workspace_id"] != json!(row.workspace_id)
                    || snapshot["conversation_id"] != conversation
                    || snapshot["project_id"] != owner.project_id
                    || snapshot["permission_profile"] != row.permission_profile
                {
                    return Err(denied());
                }
                if profile(&json!({"permission_mode":snapshot["effective_permission_mode"]}))?
                    != row.permission_profile
                {
                    return Err(denied());
                }
            }
            "plan" => {
                let approval = &snapshot["approval_request"];
                let request = &approval["request"];
                if row.plan_profile.as_deref() != Some(&row.permission_profile)
                    || row.plan_status.as_deref() != Some(&row.status)
                    || row
                        .plan_snapshot
                        .as_ref()
                        .map(|snapshot| &snapshot["approval_request"])
                        != Some(approval)
                    || approval["schema_version"] != 1
                    || approval["user_id"] != owner.user_id
                    || approval["tenant_id"] != owner.tenant_id
                    || request["permission_profile"] != row.permission_profile
                    || request["conversation_id"] != conversation
                    || request["project_id"] != owner.project_id
                    || request["plan_version_id"] != json!(row.plan_version_id)
                {
                    return Err(denied());
                }
            }
            _ => return Err(denied()),
        }
        Ok(RunAuthority {
            run_id: row.id,
            run_kind: row.run_kind,
            permission_profile: row.permission_profile,
            authorization_revision: row.revision,
            plan_version_id: row.plan_version_id.unwrap_or_default(),
            allowed_mcp_servers: selected.allowed_mcp_servers.clone(),
            agent_profile: selected,
        })
    }
}
#[async_trait]
impl Authority for PgAuthority {
    async fn prepare(
        &self,
        owner: &Owner,
        conversation: &str,
        message_id: &str,
        message: &str,
    ) -> CoreResult<RunAuthority> {
        if let Some(row) = self
            .load(owner, conversation, None, Some(message_id))
            .await?
        {
            let row = self.pin_agent(owner, conversation, row).await?;
            return self.validate(owner, conversation, row).await;
        }
        let pool = self.pool.as_ref().ok_or_else(denied)?;
        let workspace:Option<Option<String>>=sqlx::query_scalar("SELECT workspace_id FROM conversations WHERE id=$1 AND user_id=$2 AND tenant_id=$3 AND project_id=$4")
            .bind(conversation).bind(&owner.user_id).bind(&owner.tenant_id).bind(&owner.project_id).fetch_optional(pool).await.map_err(|_|denied())?;
        let workspace = workspace.ok_or_else(denied)?;
        let policy = self.policy(owner, workspace.as_deref()).await?;
        let permission_profile = profile(&policy)?.to_owned();
        let id = uuid::Uuid::new_v4().to_string();
        let snapshot = json!({"source":"chat_admission","schema_version":1,"conversation_id":conversation,"project_id":owner.project_id,"workspace_id":workspace,"effective_permission_mode":policy["permission_mode"],"permission_profile":permission_profile,"policy":policy});
        sqlx::query("INSERT INTO agent_run_authorities(id,tenant_id,project_id,conversation_id,run_kind,idempotency_key,message_id,request_message,status,revision,permission_profile,authorization_snapshot,created_at,updated_at,started_at) VALUES($1,$2,$3,$4,'chat',$5,$6,$7,'running',1,$8,$9,NOW(),NOW(),NOW()) ON CONFLICT(conversation_id,idempotency_key) DO NOTHING")
            .bind(&id).bind(&owner.tenant_id).bind(&owner.project_id).bind(conversation).bind(format!("rust-chat:{message_id}"))
            .bind(message_id).bind(message).bind(permission_profile).bind(snapshot).execute(pool).await.map_err(|_|denied())?;
        let row = self
            .load(owner, conversation, None, Some(message_id))
            .await?
            .ok_or_else(denied)?;
        let row = self.pin_agent(owner, conversation, row).await?;
        self.validate(owner, conversation, row).await
    }
    async fn recheck(
        &self,
        owner: &Owner,
        conversation: &str,
        expected: &RunAuthority,
    ) -> CoreResult<()> {
        let row = self
            .load(owner, conversation, Some(&expected.run_id), None)
            .await?
            .ok_or_else(denied)?;
        if self.validate(owner, conversation, row).await? != *expected {
            return Err(denied());
        }
        Ok(())
    }
    async fn finish(&self, owner: &Owner, run: &RunAuthority) {
        if run.run_kind != "chat" {
            return;
        }
        if let Some(pool) = &self.pool {
            let _=sqlx::query("UPDATE agent_run_authorities SET status='completed',completed_at=NOW(),updated_at=NOW() WHERE id=$1 AND tenant_id=$2 AND project_id=$3 AND revision=$4 AND run_kind='chat' AND status='running'")
            .bind(&run.run_id).bind(&owner.tenant_id).bind(&owner.project_id).bind(run.authorization_revision).execute(pool).await;
        }
    }
    async fn recheck_running(
        &self,
        owner: &Owner,
        conversation: &str,
        expected: &RunAuthority,
    ) -> CoreResult<()> {
        let row = self
            .load(owner, conversation, Some(&expected.run_id), None)
            .await?
            .filter(|row| row.status == "running")
            .ok_or_else(denied)?;
        if self.validate(owner, conversation, row).await? != *expected {
            return Err(denied());
        }
        Ok(())
    }
}
