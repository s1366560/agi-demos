//! `agistack-adapters-postgres`: the **production persistence tier**.
//!
//! This is the server-only adapter that lets the Rust core read and write the
//! **same PostgreSQL database the Python backend already owns** — the enabling
//! move for the strangler-fig migration (plan.md Section 14): no data migration,
//! we just route a capability's read/write path from Python to Rust per cutover.
//!
//! ## Two table classes (the shared-DB invariant)
//! 1. **Python-owned tables, read/written verbatim** — [`PgMemoryRepository`]
//!    against `memories`, [`PgApiKeyStore`] against `api_keys`,
//!    [`PgProjectStore`] against `projects`. Column names/types mirror
//!    `src/infrastructure/adapters/secondary/persistence/models.py` exactly.
//! 2. **Rust-owned *additive* auxiliary tables** — created by
//!    [`ensure_aux_schema`], prefixed `agistack_`. The Python `memories` table has
//!    no embedding column (Python keeps vectors in Neo4j/graphiti), so the vector
//!    index lives in its own `agistack_memory_vectors` table; agent checkpoints in
//!    `agistack_checkpoints`. These are purely additive — they never alter a
//!    Python table, so the two backends coexist safely during cutover.
//!
//! ## Portability
//! `sqlx`/`tokio` live **only** in this crate (and the server binary). The core
//! holds the port traits; this adapter is selected at the composition root for
//! the server tier, just like `adapters-device` on device or the in-memory
//! adapters in the browser (ADR-0001). Nothing here leaks into a port signature.

use sha2::{Digest, Sha256};

pub use sqlx::postgres::PgPool;

mod admin_access_repo;
mod artifact_repo;
mod attachment_repo;
mod audit_repo;
mod auth_store;
mod backend_store_repo;
mod billing_repo;
mod channel_repo;
mod checkpoint;
mod conversation_events_repo;
mod conversation_repo;
mod cron_control_repo;
mod cron_operation_repo;
mod cron_repo;
mod cron_runtime_projection_support;
mod cron_runtime_repo;
mod cron_runtime_types;
mod cron_schedule_fire_repo;
mod cron_schedule_repo;
mod cron_scheduler_owner_repo;
mod data_stats_repo;
mod deploy_repo;
mod event_log_repo;
mod gene_repo;
mod hitl_repo;
mod instance_repo;
mod invitation_repo;
mod llm_provider_repo;
mod memory_repo;
mod notification_repo;
mod project_repo;
mod sandbox_repo;
mod schema_repo;
mod share_repo;
mod skill_evolution_repo;
mod skill_repo;
mod subagent_template_repo;
mod support_repo;
mod tenant_repo;
mod tenant_skill_config_repo;
mod tenant_webhook_repo;
mod trust_repo;
mod user_store;
mod vector_index;
mod workspace_context_repo;
mod workspace_repo;

pub use admin_access_repo::PgAdminAccessRepository;
pub use artifact_repo::{ArtifactListQuery, ArtifactRecord, PgArtifactRepository};
pub use attachment_repo::{
    AttachmentListQuery, AttachmentRecord, AttachmentUploadRecord, PgAttachmentRepository,
};
pub use audit_repo::{
    AuditLogListQuery, AuditLogRecord, PgAuditLogRepository, RuntimeHookAuditQuery,
    RuntimeHookAuditSummaryRecord,
};
pub use auth_store::{ApiKeyRecord, PgApiKeyStore, PgProjectStore, ProjectRecord};
pub use backend_store_repo::{
    BackendStoreAccessError, BackendStoreCreate, BackendStoreRecord, BackendStoreUpdate,
    PgGraphStoreRepository, PgRetrievalStoreRepository,
};
pub use billing_repo::{
    BillingTenantRecord, BillingUsageRecord, InvoiceRecord, PgBillingRepository,
};
pub use channel_repo::{
    ChannelConfigListQuery, ChannelConfigRecord, ChannelObservabilitySummaryRecord,
    ChannelOutboxListQuery, ChannelOutboxRecord, ChannelPageQuery, ChannelSessionBindingRecord,
    ChannelStatusRecord, ChannelWebhookEventInsertRecord, ChannelWebhookEventRecord,
    ChannelWebhookIngressRecord, ChannelWebhookRouteRecord, ChannelWebhookSecretRecord,
    ChannelWebhookSessionCreateRecord, PgChannelRepository,
};
pub use checkpoint::PgCheckpointStore;
pub use conversation_events_repo::{
    AgentExecutionEventInsertRecord, AgentExecutionEventListQuery, AgentExecutionEventRecord,
    AgentExecutionTimelineQuery, ConversationReplayAccess, PgAgentExecutionEventRepository,
    ToolExecutionRecord,
};
pub use conversation_repo::{
    AgentConversationRecord, ConversationCreateRecord, ConversationListQuery,
    ConversationModePatch, ConversationMutationAccess, PgAgentConversationRepository,
};
pub use cron_control_repo::{
    CronControlRepositoryError, CronControlScope, CronReconcileAdmission, PgCronControlRepository,
};
pub use cron_operation_repo::{
    CronOperationErrorCode, CronOperationFailure, CronOperationKind, CronOperationRecord,
    CronOperationScope, CronOperationStatus, NewCronOperation, PgCronOperationRepository,
};
pub use cron_repo::{CronJobListQuery, CronJobRecord, CronJobRunRecord, PgCronRepository};
pub use cron_runtime_repo::PgCronAutomationRuntimeRepository;
pub use cron_runtime_types::{
    AutomationPayload, AutomationRunContext, AutomationRunLease, AutomationRunStatus,
    AutomationRuntimeRepositoryError, AutomationRuntimeScope, AutomationTerminalOutcome,
    AutomationTerminalProjection,
};
pub use cron_schedule_fire_repo::{
    CronDueSchedule, CronScheduleFireError, CronScheduledFireResult, NewCronScheduledFire,
    PgCronScheduleFireRepository,
};
pub use cron_schedule_repo::{
    CronScheduleMaterializedState, CronScheduleProjection, CronScheduleRepositoryError,
    CronScheduleSnapshot, CronScheduleStatus, PgCronScheduleRepository,
};
pub use cron_scheduler_owner_repo::{
    CronSchedulerLease, CronSchedulerOwnerError, PgCronSchedulerOwnerRepository,
    GLOBAL_CRON_SCHEDULER_SCOPE,
};
pub use data_stats_repo::{
    DataStatsAccess, DataStatsScopeError, DataStatsScopeRecord, PgDataStatsRepository,
};
pub use deploy_repo::{DeployAccess, DeployListQuery, DeployRecord, PgDeployRepository};
pub use event_log_repo::{PgEventLogRepository, TenantEventLogListQuery, TenantEventLogRecord};
pub use gene_repo::{
    GeneListQuery, GeneRecord, GeneTenantAccess, GenomeListQuery, GenomeRecord, PgGeneRepository,
};
pub use hitl_repo::{
    AutomationHitlResumeCandidate, HitlRequestRecord, NewHitlRequestRecord, PgHitlRequestRepository,
};
pub use instance_repo::{
    InstanceChannelRecord, InstanceListQuery, InstanceMemberListQuery, InstanceMemberRecord,
    InstanceRecord, InstanceUserSearchRecord, PgInstanceRepository,
};
pub use invitation_repo::{
    normalize_email, InvitationRecord, PgInvitationRepository, TenantAdminStatus,
};
pub use llm_provider_repo::{
    decrypt_provider_api_key_for_mask, LlmProviderCreateRecord, LlmProviderRecord,
    LlmProviderUpdateRecord, PgLlmProviderRepository, ProviderHealthRecord,
    TenantProviderMappingRecord, UsageStatisticRecord, UsageStatisticsQuery,
};
pub use memory_repo::PgMemoryRepository;
pub use notification_repo::{
    CreateNotification, NotificationListQuery, NotificationRecord, PgNotificationRepository,
};
pub use project_repo::{
    PgProjectReadRepository, ProjectActivityRecord, ProjectCreateRecord,
    ProjectDashboardStatsRecord, ProjectListForUserQuery, ProjectListRecords, ProjectLookup,
    ProjectMemberMutationRecord, ProjectMemberRecord, ProjectMembersLookup, ProjectMembersRecord,
    ProjectReadRecord, ProjectStatsLookup, ProjectStatsRecord, ProjectUpdatePatch,
};
pub use sandbox_repo::{PgProjectSandboxRepository, ProjectSandboxRecord};
pub use schema_repo::{
    CreateSchemaEdgeMap, CreateSchemaType, PgSchemaRepository, SchemaEdgeMapRecord,
    SchemaTypeRecord, UpdateSchemaType,
};
pub use share_repo::{NewShareRecord, PgShareRepository, ShareMemoryRecord, ShareRecord};
pub use skill_evolution_repo::{
    PgSkillEvolutionRepository, SkillEvolutionJobAuditEventInsertRecord,
    SkillEvolutionJobAuditEventRecord, SkillEvolutionJobInsertRecord, SkillEvolutionJobRecord,
    SkillEvolutionOverviewStatsRecord, SkillEvolutionPipelineSessionRecord,
    SkillEvolutionRunRecord, SkillEvolutionSessionGroupRecord, SkillEvolutionSessionRecord,
    SkillEvolutionSkillSummaryRecord,
};
pub use skill_repo::{
    PgSkillRepository, PluginConfigRecord, SkillProjectAccess, SkillRecord, SkillUpdateRecord,
    SkillVersionRecord,
};
pub use subagent_template_repo::PgSubagentTemplateRepository;
pub use support_repo::{
    ClosedSupportTicketRecord, CreateSupportTicket, PgSupportRepository, SupportTicketListQuery,
    SupportTicketRecord, UpdateSupportTicket,
};
pub use tenant_repo::{PgTenantRepository, TenantLookup, TenantRecord, TenantUpdatePatch};
pub use tenant_skill_config_repo::{PgTenantSkillConfigRepository, TenantSkillConfigRecord};
pub use tenant_webhook_repo::{
    CreateTenantWebhook, PgTenantWebhookRepository, TenantWebhookRecord,
};
pub use trust_repo::{
    DecisionRecordRecord, NewDecisionRecordRecord, NewTrustPolicyRecord, PgTrustRepository,
    TenantAccessStatus, TrustDecisionResolution, TrustPolicyRecord,
};
pub use user_store::{CurrentUserRecord, PgUserStore, UserAuthRecord};
pub use vector_index::PgVectorIndex;
pub use workspace_context_repo::{
    PgWorkspaceContextRepository, WorkspaceContextAccessRecord, WorkspaceContextRepositoryError,
    WorkspaceContextSnapshotRecord, WorkspaceContextSwitchRecord, WorkspaceContextSwitchRequest,
};
pub use workspace_repo::{
    BlackboardFileRecord, BlackboardOutboxRecord, BlackboardPostRecord, BlackboardReplyRecord,
    PgWorkspaceRepository, TopologyEdgeRecord, TopologyNodeRecord, WorkspaceAccess,
    WorkspaceAgentDetailRecord, WorkspaceAgentRecord, WorkspaceMemberRecord,
    WorkspaceMessageRecord, WorkspacePipelineRunRecord, WorkspacePipelineStageRunRecord,
    WorkspacePlanBlackboardEntryRecord, WorkspacePlanEventRecord, WorkspacePlanNodeRecord,
    WorkspacePlanOutboxRecord, WorkspacePlanRecord, WorkspaceProjectAccess, WorkspaceRecord,
    WorkspaceTaskRecord, WorkspaceTaskSessionAttemptRecord,
};

use agistack_core::ports::{CoreError, CoreResult};

/// Open a pooled connection to `database_url` (e.g.
/// `postgres://user:pass@host:5432/db`). Mirrors the Python `POSTGRES_*` DSN; the
/// composition root supplies the URL from the environment.
pub async fn connect(database_url: &str) -> CoreResult<PgPool> {
    sqlx::postgres::PgPoolOptions::new()
        .max_connections(8)
        .connect(database_url)
        .await
        .map_err(|e| CoreError::Storage(format!("postgres connect: {e}")))
}

/// Create the **Rust-owned auxiliary** tables if absent. Strictly additive: it
/// only ever issues `CREATE EXTENSION IF NOT EXISTS` / `CREATE TABLE IF NOT
/// EXISTS` against `agistack_`-prefixed objects, so it can run against the live
/// shared database without disturbing any Python-owned table.
///
/// - `vector` extension + `agistack_memory_vectors` back [`PgVectorIndex`].
/// - `agistack_checkpoints` backs [`PgCheckpointStore`] (agent crash recovery).
/// - `agistack_skill_evolution_runs` backs Rust-side P5 evolution run admission.
/// - `agistack_skill_evolution_job_audit_events` records Rust-side P5 job review outcomes.
/// - `agistack_channel_outbox_leases` backs Rust-side P5 channel delivery ownership.
/// - `agistack_channel_webhook_events` backs Rust-side P5 channel webhook ingress idempotency
///   and binding route projections.
pub async fn ensure_aux_schema(pool: &PgPool) -> CoreResult<()> {
    // pgvector. On the `pgvector/pgvector` image the bootstrap superuser can
    // create it; if a managed instance pre-installs it, the IF NOT EXISTS is a
    // no-op. Vectors are kept unbounded-dim (no ANN index) so any embedding width
    // works for the brute-force P1 scan.
    sqlx::query("CREATE EXTENSION IF NOT EXISTS vector")
        .execute(pool)
        .await
        .map_err(|e| CoreError::Storage(format!("ensure vector extension: {e}")))?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_memory_vectors (\
            project_id text NOT NULL, \
            id text NOT NULL, \
            embedding vector NOT NULL, \
            PRIMARY KEY (project_id, id))",
    )
    .execute(pool)
    .await
    .map_err(|e| CoreError::Storage(format!("ensure agistack_memory_vectors: {e}")))?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_checkpoints (\
            session_id text PRIMARY KEY, \
            state jsonb NOT NULL, \
            updated_at timestamptz NOT NULL DEFAULT now())",
    )
    .execute(pool)
    .await
    .map_err(|e| CoreError::Storage(format!("ensure agistack_checkpoints: {e}")))?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_skill_evolution_runs (\
            id text PRIMARY KEY, \
            tenant_id text NOT NULL, \
            scope_key text NOT NULL, \
            project_id text, \
            skill_name text, \
            reason text NOT NULL, \
            status text NOT NULL, \
            attempts integer NOT NULL DEFAULT 0, \
            worker_id text, \
            started_at timestamptz, \
            completed_at timestamptz, \
            last_error text, \
            result_json jsonb, \
            created_at timestamptz NOT NULL DEFAULT now(), \
            updated_at timestamptz)",
    )
    .execute(pool)
    .await
    .map_err(|e| CoreError::Storage(format!("ensure agistack_skill_evolution_runs: {e}")))?;

    for (column, ty) in [
        ("attempts", "integer NOT NULL DEFAULT 0"),
        ("worker_id", "text"),
        ("started_at", "timestamptz"),
        ("completed_at", "timestamptz"),
        ("last_error", "text"),
        ("result_json", "jsonb"),
    ] {
        sqlx::query(&format!(
            "ALTER TABLE agistack_skill_evolution_runs ADD COLUMN IF NOT EXISTS {column} {ty}"
        ))
        .execute(pool)
        .await
        .map_err(|e| {
            CoreError::Storage(format!(
                "ensure agistack_skill_evolution_runs.{column}: {e}"
            ))
        })?;
    }

    sqlx::query(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agistack_skill_evolution_runs_active \
         ON agistack_skill_evolution_runs (tenant_id, scope_key) \
         WHERE status IN ('queued', 'running')",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure uq_agistack_skill_evolution_runs_active: {e}"
        ))
    })?;

    sqlx::query(
        "CREATE INDEX IF NOT EXISTS idx_agistack_skill_evolution_runs_claim \
         ON agistack_skill_evolution_runs (status, created_at)",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure idx_agistack_skill_evolution_runs_claim: {e}"
        ))
    })?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_skill_evolution_job_audit_events (\
            id text PRIMARY KEY, \
            tenant_id text NOT NULL, \
            project_id text, \
            skill_name text NOT NULL, \
            job_id text NOT NULL, \
            event_type text NOT NULL, \
            actor_user_id text, \
            skill_version_id text, \
            details_json jsonb NOT NULL DEFAULT '{}'::jsonb, \
            created_at timestamptz NOT NULL DEFAULT now())",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure agistack_skill_evolution_job_audit_events: {e}"
        ))
    })?;

    sqlx::query(
        "CREATE INDEX IF NOT EXISTS idx_agistack_skill_evolution_job_audit_job \
         ON agistack_skill_evolution_job_audit_events (tenant_id, job_id, created_at)",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure idx_agistack_skill_evolution_job_audit_job: {e}"
        ))
    })?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_channel_outbox_leases (\
            outbox_id text PRIMARY KEY, \
            lease_owner text NOT NULL, \
            lease_expires_at timestamptz NOT NULL, \
            created_at timestamptz NOT NULL DEFAULT now(), \
            updated_at timestamptz)",
    )
    .execute(pool)
    .await
    .map_err(|e| CoreError::Storage(format!("ensure agistack_channel_outbox_leases: {e}")))?;

    sqlx::query(
        "CREATE INDEX IF NOT EXISTS idx_agistack_channel_outbox_leases_expiry \
         ON agistack_channel_outbox_leases (lease_expires_at)",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure idx_agistack_channel_outbox_leases_expiry: {e}"
        ))
    })?;

    sqlx::query(
        "CREATE TABLE IF NOT EXISTS agistack_channel_webhook_events (\
            id text PRIMARY KEY, \
            project_id text NOT NULL, \
            channel_config_id text NOT NULL, \
            channel_type text NOT NULL, \
            idempotency_key text NOT NULL, \
            headers_json jsonb NOT NULL DEFAULT '{}'::jsonb, \
            raw_event_json jsonb NOT NULL, \
            normalized_event_json jsonb NOT NULL DEFAULT '{}'::jsonb, \
            status text NOT NULL DEFAULT 'received', \
            route_error text, \
            route_session_key text, \
            route_binding_id text, \
            route_conversation_id text, \
            received_at timestamptz NOT NULL DEFAULT now(), \
            routed_at timestamptz)",
    )
    .execute(pool)
    .await
    .map_err(|e| CoreError::Storage(format!("ensure agistack_channel_webhook_events: {e}")))?;

    sqlx::query(
        "ALTER TABLE agistack_channel_webhook_events \
         ADD COLUMN IF NOT EXISTS normalized_event_json jsonb NOT NULL DEFAULT '{}'::jsonb",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure agistack_channel_webhook_events.normalized_event_json: {e}"
        ))
    })?;

    for (column, ty) in [
        ("route_session_key", "text"),
        ("route_binding_id", "text"),
        ("route_conversation_id", "text"),
    ] {
        sqlx::query(&format!(
            "ALTER TABLE agistack_channel_webhook_events ADD COLUMN IF NOT EXISTS {column} {ty}"
        ))
        .execute(pool)
        .await
        .map_err(|e| {
            CoreError::Storage(format!(
                "ensure agistack_channel_webhook_events.{column}: {e}"
            ))
        })?;
    }

    sqlx::query(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agistack_channel_webhook_events_idempotency \
         ON agistack_channel_webhook_events (channel_config_id, idempotency_key)",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure uq_agistack_channel_webhook_events_idempotency: {e}"
        ))
    })?;

    sqlx::query(
        "CREATE INDEX IF NOT EXISTS idx_agistack_channel_webhook_events_project_received \
         ON agistack_channel_webhook_events (project_id, received_at)",
    )
    .execute(pool)
    .await
    .map_err(|e| {
        CoreError::Storage(format!(
            "ensure idx_agistack_channel_webhook_events_project_received: {e}"
        ))
    })?;

    Ok(())
}

/// SHA-256 hex digest — byte-identical to the Python auth path
/// (`AuthService.hash_api_key` = `hashlib.sha256(key.encode()).hexdigest()`), so
/// a `ms_sk_` key issued by Python verifies here against the same `key_hash`.
pub(crate) fn sha256_hex(input: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(input.as_bytes());
    let digest = hasher.finalize();
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

#[cfg(test)]
mod unit {
    use super::sha256_hex;

    #[test]
    fn sha256_matches_python_hexdigest() {
        // Reference vectors from Python `hashlib.sha256(x.encode()).hexdigest()`.
        assert_eq!(
            sha256_hex(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        // Shape of a real key prefix — just assert determinism + width here.
        let h = sha256_hex("ms_sk_0123456789abcdef");
        assert_eq!(h.len(), 64);
        assert!(h.chars().all(|c| c.is_ascii_hexdigit()));
    }
}
