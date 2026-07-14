//! `agistack-server`: the native (server-tier) binary.
//!
//! It wires the runtime-agnostic [`MemoryService`] and [`ReActEngine`] to the
//! server-tier adapters (here the in-memory adapters for a zero-dependency demo;
//! swap in `agistack-adapters-device` or a future Postgres adapter without
//! touching the core) and the hot-pluggable [`HotPlugRegistry`], then exposes the
//! whole surface over HTTP.
//!
//! `tokio` lives **only** here. Everything it depends on — core, plugin-host,
//! adapters — is runtime-agnostic, which is exactly what lets the same code also
//! compile to wasm / iOS / Android behind a different shell.
//!
//! Routes:
//!   GET  /health
//!   POST /v1/episodes                  ingest an episode -> memory
//!   GET  /v1/memories/search           keyword (or ?semantic=true) search
//!   GET  /v1/memories/:id              fetch one memory
//!   POST /v1/agent/run                 run a ReAct session (may suspend on HITL)
//!   POST /v1/agent/resume              answer a HITL request -> resume to completion
//!   GET  /v1/plugins                   list registered tools + enabled plugins
//!   POST /v1/plugins/enable            enable a plugin manifest (hot)
//!   POST /v1/plugins/disable           disable a plugin by name (hot)
//!   POST /v1/tools/call               invoke one tool via the ToolHost (sandboxes wasm)
//!   POST /v1/control-plane/publish     CP publishes desired tools -> DP reconcile -> ACK/NACK

use std::{
    collections::HashMap,
    sync::{atomic::AtomicU64, Arc, Mutex},
};

const DEFAULT_SANDBOX_IMAGE: &str = "sandbox-mcp-server:latest";

mod admin_access;
mod admin_dlq_api;
mod agent_commands_api;
mod agent_conversations_api;
mod agent_events_api;
mod agent_ws;
mod artifacts_api;
mod attachments_api;
mod audit_api;
mod auth;
mod billing_api;
mod channel_api;
mod cron_api;
mod cron_automation_runtime;
mod cron_hitl_resume;
mod cron_schedule_fire;
mod cron_schedule_reconcile;
mod cron_scheduler;
mod cron_scheduler_ownership;
mod cron_tool_authority;
mod cron_worker;
mod data_api;
mod demo_api;
mod deploy_api;
mod engines_api;
mod enhanced_search_api;
mod events_api;
mod gene_api;
mod graph_api;
mod graph_stores_api;
mod hitl_api;
mod identity;
mod identity_api;
mod instance_api;
mod llm_providers_api;
mod maintenance_api;
mod notifications_api;
mod prod_api;
mod retrieval_stores_api;
mod sandbox_api;
mod schema_api;
mod shares_api;
mod skill_api;
mod skill_evolution_wiring;
mod subagents_api;
mod support_api;
mod system_api;
mod tenant_skill_config_api;
mod tenant_webhooks_api;
mod trust_api;
mod workspace_api;
mod workspace_outbox_worker;

use agistack_adapters_docker::{DockerContainerRuntime, ImagePullPolicy};
use agistack_adapters_http_llm::{HttpEmbedding, HttpLlm};
use agistack_adapters_mem::{
    HashEmbedding, InMemoryCheckpointStore, InMemoryContainerRuntime, InMemoryEmailSender,
    InMemoryEventStream, InMemoryGraphStore, InMemoryMemoryRepository, InMemoryObjectStore,
    InMemoryVectorIndex, StubLlm, SystemClock,
};
use agistack_adapters_neo4j::{connect as connect_neo4j, Neo4jGraphStore};
use agistack_adapters_postgres::{
    connect, ensure_aux_schema, PgAgentConversationRepository, PgAgentExecutionEventRepository,
    PgApiKeyStore, PgArtifactRepository, PgAttachmentRepository, PgAuditLogRepository,
    PgBillingRepository, PgChannelRepository, PgCheckpointStore, PgCronRepository,
    PgDataStatsRepository, PgDeployRepository, PgEventLogRepository, PgGeneRepository,
    PgGraphStoreRepository, PgHitlRequestRepository, PgInstanceRepository, PgInvitationRepository,
    PgLlmProviderRepository, PgMemoryRepository, PgNotificationRepository, PgPool,
    PgProjectReadRepository, PgProjectSandboxRepository, PgProjectStore,
    PgRetrievalStoreRepository, PgSchemaRepository, PgShareRepository, PgSkillEvolutionRepository,
    PgSkillRepository, PgSubagentTemplateRepository, PgSupportRepository, PgTenantRepository,
    PgTenantSkillConfigRepository, PgTenantWebhookRepository, PgTrustRepository, PgUserStore,
    PgVectorIndex, PgWorkspaceRepository,
};
use agistack_adapters_smtp::SmtpEmailSender;
use agistack_adapters_wasmtime::{WasmtimeTool, DEFAULT_FUEL, SCORE_V1_WAT};
use agistack_core::ports::{
    CheckpointStore, ContainerRuntime, EmailSender, EmbeddingPort, EventStream, GraphStore,
    LlmPort, ObjectStore, ToolHost,
};
use agistack_core::{MemoryService, ReActEngine};
use agistack_plugin_host::{
    ControlPlane, DataPlaneReconciler, HotPlugRegistry, LenTool, PluginHost, UpperTool,
};

use crate::admin_access::{build_admin_access, SharedAdminAccess};
use crate::admin_dlq_api::{build_admin_dlq_service, SharedAdminDlq};
use crate::agent_conversations_api::{
    DevAgentConversationService, PgAgentConversationService, SharedAgentConversations,
};
use crate::agent_events_api::{
    DevAgentEventReplayService, PgAgentEventReplayService, SharedAgentEvents,
};
use crate::artifacts_api::{DevArtifactService, PgArtifactService, SharedArtifacts};
use crate::attachments_api::{DevAttachmentService, PgAttachmentService, SharedAttachments};
use crate::audit_api::{DevAuditLogService, PgAuditLogService, SharedAuditLogs};
use crate::auth::{DevAuthenticator, PgAuthenticator, SharedAuthenticator};
use crate::billing_api::{DevBillingService, PgBillingService, SharedBilling};
use crate::channel_api::{
    ChannelOutboxDeliveryWorker, ChannelOutboxDeliveryWorkerConfig, DevChannelService,
    FeishuWebhookDeliverer, PgChannelService, SharedChannelOutboxDeliveryWorker, SharedChannels,
};
use crate::cron_api::{DevCronJobService, PgCronJobService, SharedCronJobs};
use crate::cron_scheduler::{build_pg_cron_scheduler, SharedCronScheduler};
use crate::data_api::{DevDataStatsScopeService, PgDataStatsScopeService, SharedDataStats};
use crate::deploy_api::{DevDeployService, PgDeployService, SharedDeploys};
use crate::events_api::{DevEventLogService, PgEventLogService, SharedEventLogs};
use crate::gene_api::{DevGeneService, PgGeneService, SharedGenes};
use crate::graph_stores_api::{
    DevGraphStoreCatalogService, PgGraphStoreCatalogService, SharedGraphStores,
};
use crate::hitl_api::{build_hitl_response_service, SharedHitlResponses};
use crate::identity::{
    DevIdentityService, InMemoryDeviceGrantStore, PgIdentityService, SharedDeviceGrantStore,
    SharedIdentity,
};
use crate::instance_api::{DevInstanceService, PgInstanceService, SharedInstances};
use crate::llm_providers_api::{
    DevLlmProviderAssignmentService, DevLlmProviderCatalogService, DevLlmProviderHealthService,
    DevLlmProviderUsageService, PgLlmProviderAssignmentService, PgLlmProviderCatalogService,
    PgLlmProviderHealthService, PgLlmProviderUsageService, SharedLlmProviderAssignments,
    SharedLlmProviderHealth, SharedLlmProviderUsage, SharedLlmProviders,
};
use crate::notifications_api::{
    DevNotificationService, PgNotificationService, SharedNotifications,
};
use crate::retrieval_stores_api::{
    DevRetrievalStoreCatalogService, PgRetrievalStoreCatalogService, SharedRetrievalStores,
};
use crate::sandbox_api::{
    in_memory_http_service_registry, PgProjectSandboxConfigSource, ProjectSandboxService,
    SharedHttpServiceRegistry, SharedProjectSandboxes,
};
use crate::schema_api::{DevProjectSchemaService, PgProjectSchemaService, SharedProjectSchema};
use crate::shares_api::{DevShareService, PgShareService, SharedShares};
use crate::skill_api::{
    DevSkillService, PgSkillEvolutionScheduler, PgSkillEvolutionWorker, PgSkillService,
    SharedSkillEvolutionWorker, SharedSkills,
};
use crate::skill_evolution_wiring::skill_evolution_executor_from_env;
use crate::subagents_api::{
    DevSubagentTemplateService, PgSubagentTemplateService, SharedSubagentTemplates,
};
use crate::support_api::{DevSupportService, PgSupportService, SharedSupport};
use crate::tenant_skill_config_api::{
    DevTenantSkillConfigService, PgTenantSkillConfigService, SharedTenantSkillConfigs,
};
use crate::tenant_webhooks_api::{
    DevTenantWebhookService, PgTenantWebhookService, SharedTenantWebhooks,
};
use crate::trust_api::{DevTrustService, PgTrustService, SharedTrust};
use crate::workspace_api::{
    DevWorkspaceService, PgWorkspaceService, SharedAutonomyCooldownStore, SharedWorkspaces,
};
use crate::workspace_outbox_worker::{
    worker_launch_event_stream_source, workspace_agent_mention_runtime_from_env,
    workspace_plan_outbox_handlers_with_runtime_state_and_streams, PgWorkspacePlanOutboxStore,
    ProjectSandboxPipelineStageRunner, SharedWorkspacePlanOutboxWorker,
    WorkerLaunchRuntimeStateStore, WorkspacePipelineStageRunner, WorkspacePlanOutboxWorker,
    WorkspacePlanOutboxWorkerConfig,
};

/// Shared, cheaply-cloneable application state. Every `Arc`/`HotPlugRegistry`
/// field is a shared handle, so all routes operate on the same registry, memory
/// store, and control/data planes.
#[derive(Clone)]
pub(crate) struct AppState {
    pub(crate) memory: Arc<MemoryService>,
    pub(crate) engine: Arc<ReActEngine>,
    pub(crate) events: Arc<dyn EventStream>,
    pub(crate) agent_event_writer: Option<PgAgentExecutionEventRepository>,
    pub(crate) event_counter: Arc<AtomicU64>,
    registry: HotPlugRegistry,
    plugins: Arc<PluginHost>,
    control: Arc<Mutex<ControlPlane>>,
    reconciler: Arc<Mutex<DataPlaneReconciler>>,
    /// Production authenticator backing the `/api/v1` strangled surface
    /// (Postgres in production, dev stub offline). See [`crate::auth`].
    pub(crate) auth: SharedAuthenticator,
    /// P2 identity service: login (`/auth/token`) + tenant reads. Postgres in
    /// production, dev stub offline. See [`crate::identity`].
    pub(crate) identity: SharedIdentity,
    /// P2 share service: authenticated share management plus public token access.
    pub(crate) shares: SharedShares,
    /// P2 trust governance service: policies, approval requests, and decisions.
    pub(crate) trust: SharedTrust,
    /// Shared global admin gate for exact admin-only Rust surfaces.
    pub(crate) admin_access: SharedAdminAccess,
    /// P5 skill store/versioning service over Python-owned `skills` tables.
    pub(crate) skills: SharedSkills,
    /// P5 skill evolution run worker foundation over Rust-owned
    /// `agistack_skill_evolution_runs`. It is wired but autostart-gated until
    /// full LLM evolution-engine parity is enabled.
    pub(crate) skill_evolution_worker: Option<SharedSkillEvolutionWorker>,
    /// P5 tenant skill disable/override config over Python-owned
    /// `tenant_skill_configs`.
    pub(crate) tenant_skill_configs: SharedTenantSkillConfigs,
    /// P6 workspace/task/topology/blackboard foundation over Python-owned
    /// workspace tables.
    pub(crate) workspaces: SharedWorkspaces,
    /// P5 channel configuration read/status, Feishu webhook EventStream fanout,
    /// and local lifecycle status markers over Python-owned channel tables. Live
    /// provider sessions and full workspace/session routing remain Python-owned.
    pub(crate) channels: SharedChannels,
    /// P5 channel outbox delivery worker foundation. It is wired for explicit
    /// one-shot/loop use but only autostarts when both channel delivery gates
    /// are enabled.
    pub(crate) channel_outbox_delivery_worker: Option<SharedChannelOutboxDeliveryWorker>,
    /// P3/F7 HITL response ingress over Python-owned `hitl_requests` plus the
    /// shared Redis/EventStream continuation channel.
    pub(crate) hitl: SharedHitlResponses,
    /// P3/F7 event replay over Python-owned `agent_execution_events` in
    /// production, with an in-process stream reader in offline/dev mode.
    pub(crate) agent_events: SharedAgentEvents,
    /// Desktop Agent conversation list/create/link plus normalized timeline
    /// replay over Python-owned conversation/event tables.
    pub(crate) agent_conversations: SharedAgentConversations,
    /// P7 tenant event-log read surface over Python-owned `tenant_event_logs`.
    /// Only exact list/type-discovery reads are routed to Rust.
    pub(crate) event_logs: SharedEventLogs,
    /// P7 tenant audit-log read/export surface over Python-owned `audit_logs`.
    /// Write-side logging remains Python-owned.
    pub(crate) audit_logs: SharedAuditLogs,
    /// P7 current-user notification API-v1 surface over Python-owned
    /// `notifications`.
    pub(crate) notifications: SharedNotifications,
    /// P7 billing invoice read surface over Python-owned `invoices`. Billing
    /// summaries and plan mutations remain Python-owned.
    pub(crate) billing: SharedBilling,
    /// P7 support ticket API-v1 and legacy surfaces over Python-owned
    /// `support_tickets`.
    pub(crate) support: SharedSupport,
    /// P7 artifact surface over Python-owned `artifacts`. Rust owns read
    /// metadata plus exact content save-back and soft-delete; download, URL
    /// refresh, upload, and multipart storage writes remain Python-owned.
    pub(crate) artifacts: SharedArtifacts,
    /// P7 attachment surface over Python-owned `attachments`. Rust owns
    /// metadata reads, exact simple upload, and hard-delete; multipart and
    /// download paths remain Python-owned.
    pub(crate) attachments: SharedAttachments,
    /// P7 admin DLQ surface over Python-owned Redis DLQ keys, including retry
    /// republish to the Python-compatible UnifiedEventBus stream.
    pub(crate) admin_dlq: SharedAdminDlq,
    /// P7 provider metadata list/detail/create/update/soft-delete over
    /// Python-owned `llm_providers`. Active connection tests and runtime
    /// provider resolution remain Python-owned.
    pub(crate) llm_providers: SharedLlmProviders,
    /// P7 latest provider health read surface over Python-owned
    /// `provider_health`. Active provider checks and writes remain Python-owned.
    pub(crate) llm_provider_health: SharedLlmProviderHealth,
    /// P7 tenant-provider assignment list surface over Python-owned
    /// `tenant_provider_mappings`. Assignment mutations remain Python-owned.
    pub(crate) llm_provider_assignments: SharedLlmProviderAssignments,
    /// P7 provider usage statistics read surface over Python-owned
    /// `llm_usage_logs`. Usage writes remain Python-owned.
    pub(crate) llm_provider_usage: SharedLlmProviderUsage,
    /// P7 tenant webhook CRUD surface over Python-owned `webhooks`. Provider
    /// delivery paths remain Python-owned.
    pub(crate) tenant_webhooks: SharedTenantWebhooks,
    /// P7 project schema CRUD surface over Python-owned schema tables.
    pub(crate) project_schema: SharedProjectSchema,
    /// P7 cron job read surface over Python-owned `cron_jobs` and
    /// `cron_job_runs`.
    pub(crate) cron_jobs: SharedCronJobs,
    /// Fenced Rust scheduler cutover runtime. It is composed only with
    /// PostgreSQL and remains double-gated at startup.
    pub(crate) cron_scheduler: Option<SharedCronScheduler>,
    /// P7 exact graph data stats/export read surface over the portable
    /// GraphStore. Cleanup stays Python-owned.
    pub(crate) data_stats: SharedDataStats,
    /// P7 deploy read surface over Python-owned `instances` and
    /// `deploy_records`. Deploy writes, lifecycle transitions, and SSE progress
    /// remain Python-owned.
    pub(crate) deploys: SharedDeploys,
    /// P3/F11 SubAgent template marketplace category discovery over
    /// Python-owned `subagent_templates`. Template CRUD/install/runtime remain
    /// Python-owned.
    pub(crate) subagent_templates: SharedSubagentTemplates,
    /// P7 instance read surface over Python-owned `instances`. Instance writes,
    /// runtime operations, config, members, files, and channels remain
    /// Python-owned.
    pub(crate) instances: SharedInstances,
    /// P7 gene marketplace read surface over Python-owned `gene_market`.
    /// Gene writes, genomes, installation, reviews, ratings, and evolution
    /// events remain Python-owned.
    pub(crate) genes: SharedGenes,
    /// P7 graph-store read surface over Python-owned `graph_stores`.
    /// Store writes and connection tests remain Python-owned.
    pub(crate) graph_stores: SharedGraphStores,
    /// P7 retrieval-store read surface over Python-owned `retrieval_stores`.
    /// Store writes and connection tests remain Python-owned.
    pub(crate) retrieval_stores: SharedRetrievalStores,
    /// P6 server-only outbox worker foundation. It is wired for explicit
    /// one-shot/loop use once handlers are migrated, but is not auto-started.
    pub(crate) workspace_plan_outbox_worker: Option<SharedWorkspacePlanOutboxWorker>,
    /// P4 knowledge-graph store. Server composition picks Neo4j when configured,
    /// otherwise an in-memory dev/test backend behind the same portable port.
    pub(crate) graph: Arc<dyn GraphStore>,
    /// P5 project sandbox lifecycle service over the portable ContainerRuntime
    /// port. Docker stays server-only; tests/dev can use the in-memory runtime.
    pub(crate) sandboxes: SharedProjectSandboxes,
}

type ServerResult<T> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Debug, Eq, PartialEq)]
enum PersistenceMode {
    Postgres(String),
    InMemoryDev,
}

pub(crate) fn env_flag_enabled(value: Option<&str>) -> bool {
    value.is_some_and(|value| matches!(value.trim().to_ascii_lowercase().as_str(), "1" | "true"))
}

fn select_persistence_mode(
    database_url: Option<String>,
    explicit_dev_mode: bool,
) -> ServerResult<PersistenceMode> {
    if let Some(url) = database_url.filter(|url| !url.trim().is_empty()) {
        return Ok(PersistenceMode::Postgres(url));
    }
    if explicit_dev_mode {
        return Ok(PersistenceMode::InMemoryDev);
    }
    Err(std::io::Error::other(
        "DATABASE_URL is required; set AGISTACK_DEV_MODE=1 only for an explicit local in-memory runtime",
    )
    .into())
}

type MemoryAndAuth = (
    Arc<MemoryService>,
    Arc<dyn CheckpointStore>,
    SharedAuthenticator,
    SharedIdentity,
    SharedShares,
    SharedTrust,
    SharedSkills,
    SharedTenantSkillConfigs,
    SharedWorkspaces,
    Option<PgPool>,
    Option<PgProjectSandboxRepository>,
    Option<PgProjectReadRepository>,
);

// ---- wiring ---------------------------------------------------------------

/// Resolve the LLM + embedding ports from the environment — the cloud↔local
/// seam. Default is the offline stub pair so `cargo run` and tests need no
/// network or keys; setting `AGISTACK_LLM_BASE_URL` swaps in the HTTP adapter
/// (optionally `AGISTACK_LLM_MODEL`, `AGISTACK_EMBED_MODEL`, `AGISTACK_LLM_API_KEY`).
fn select_llm_and_embedding() -> (Arc<dyn LlmPort>, Arc<dyn EmbeddingPort>) {
    match std::env::var("AGISTACK_LLM_BASE_URL") {
        Ok(base) if !base.is_empty() => {
            let chat_model =
                std::env::var("AGISTACK_LLM_MODEL").unwrap_or_else(|_| "gpt-4o-mini".into());
            let embed_model = std::env::var("AGISTACK_EMBED_MODEL")
                .unwrap_or_else(|_| "text-embedding-3-small".into());
            let key = std::env::var("AGISTACK_LLM_API_KEY").ok();
            let mut llm = HttpLlm::new(base.clone(), chat_model);
            let mut emb = HttpEmbedding::new(base, embed_model);
            if let Some(k) = key {
                llm = llm.with_api_key(k.clone());
                emb = emb.with_api_key(k);
            }
            eprintln!("[agistack] LLM port: HTTP (cloud) via AGISTACK_LLM_BASE_URL");
            (Arc::new(llm), Arc::new(emb))
        }
        _ => (Arc::new(StubLlm), Arc::new(HashEmbedding::new(64))),
    }
}

fn build_registry() -> HotPlugRegistry {
    // Shared hot-pluggable registry — the single data-plane tool set used by the
    // agent, the plugin lifecycle, and the CP/DP reconciler alike.
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(LenTool));
    registry.register_tool(Arc::new(UpperTool));
    // Native server tier hosts an untrusted tool in a Wasmtime sandbox (fuel +
    // epoch quotas). The same scorer `.wasm` runs under Wasmi on wasm/iOS — only
    // the host runtime differs (ADR-0002/0003). `wasmtime` is native-only and,
    // like `tokio`, never leaks back into the core or its port signatures.
    registry.register_tool(Arc::new(
        WasmtimeTool::from_wat("score", "1.0.0", SCORE_V1_WAT, DEFAULT_FUEL)
            .expect("BUG: built-in scorer WAT must compile"),
    ));
    registry
}

fn select_email_sender() -> Arc<dyn EmailSender> {
    match std::env::var("AGISTACK_SMTP_HOST") {
        Ok(host) if !host.is_empty() => {
            let sender = match (
                std::env::var("AGISTACK_SMTP_USERNAME").ok(),
                std::env::var("AGISTACK_SMTP_PASSWORD").ok(),
            ) {
                (Some(username), Some(password))
                    if !username.is_empty() && !password.is_empty() =>
                {
                    match SmtpEmailSender::relay(&host, username, password) {
                        Ok(sender) => sender,
                        Err(err) => {
                            eprintln!(
                                "[agistack] email sender: SMTP relay unavailable ({err}); falling back to in-memory"
                            );
                            return Arc::new(InMemoryEmailSender::new());
                        }
                    }
                }
                _ => {
                    let port = std::env::var("AGISTACK_SMTP_PORT")
                        .ok()
                        .and_then(|p| p.parse::<u16>().ok())
                        .unwrap_or(1025);
                    SmtpEmailSender::plaintext(&host, port)
                }
            };
            eprintln!("[agistack] email sender: SMTP via AGISTACK_SMTP_HOST");
            Arc::new(sender)
        }
        _ => {
            eprintln!("[agistack] email sender: in-memory (dev)");
            Arc::new(InMemoryEmailSender::new())
        }
    }
}

async fn build_device_grant_store() -> SharedDeviceGrantStore {
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => {
            match agistack_adapters_redis::RedisDeviceGrantStore::connect(&url).await {
                Ok(store) => {
                    eprintln!("[agistack] device-code grants: Redis TTL via REDIS_URL");
                    Arc::new(store)
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] device-code grants: Redis unavailable ({err}); falling back to in-memory"
                    );
                    Arc::new(InMemoryDeviceGrantStore::new())
                }
            }
        }
        _ => {
            eprintln!("[agistack] device-code grants: in-memory (dev)");
            Arc::new(InMemoryDeviceGrantStore::new())
        }
    }
}

async fn build_object_store() -> Arc<dyn ObjectStore> {
    let requested = std::env::var("AGISTACK_OBJECT_STORE")
        .map(|value| value.eq_ignore_ascii_case("s3"))
        .unwrap_or(false)
        || std::env::var("AGISTACK_S3_BUCKET")
            .map(|value| !value.is_empty())
            .unwrap_or(false);
    if requested {
        let endpoint = std::env::var("AGISTACK_S3_ENDPOINT")
            .ok()
            .or_else(|| std::env::var("S3_TEST_ENDPOINT").ok());
        let region = std::env::var("AGISTACK_S3_REGION").unwrap_or_else(|_| "us-east-1".into());
        let access_key = std::env::var("AGISTACK_S3_ACCESS_KEY")
            .ok()
            .or_else(|| std::env::var("S3_TEST_ACCESS_KEY").ok())
            .unwrap_or_else(|| "minioadmin".into());
        let secret_key = std::env::var("AGISTACK_S3_SECRET_KEY")
            .ok()
            .or_else(|| std::env::var("S3_TEST_SECRET_KEY").ok())
            .unwrap_or_else(|| "minioadmin".into());
        let bucket =
            std::env::var("AGISTACK_S3_BUCKET").unwrap_or_else(|_| "agistack-objects".into());
        match agistack_adapters_s3::connect(
            endpoint.as_deref(),
            &region,
            &access_key,
            &secret_key,
            &bucket,
        )
        .await
        {
            Ok(store) => {
                eprintln!("[agistack] object store: S3/MinIO bucket {bucket}");
                return Arc::new(store);
            }
            Err(err) => {
                eprintln!(
                    "[agistack] object store: S3/MinIO unavailable ({err}); falling back to in-memory"
                );
            }
        }
    }
    eprintln!("[agistack] object store: in-memory (dev)");
    Arc::new(InMemoryObjectStore::new())
}

/// Persistence + auth selection at the composition root — the strangler switch
/// (plan.md Section 14). When `DATABASE_URL` is set, bind the production Postgres
/// tier (**the same schema Python owns**, ADR-0001) and the SHA256 `api_keys`
/// authenticator. The zero-dependency in-memory adapters and dev authenticator
/// require the explicit `AGISTACK_DEV_MODE=1` capability; an accidental missing
/// database configuration fails closed. The heavy `sqlx`/`tokio` deps stay
/// inside `adapters-postgres`; the core only ever sees `Arc<dyn _>`.
async fn build_memory_and_auth(
    llm: Arc<dyn LlmPort>,
    embedding: Arc<dyn EmbeddingPort>,
    object_store: Arc<dyn ObjectStore>,
    autonomy_cooldown: Option<SharedAutonomyCooldownStore>,
) -> ServerResult<MemoryAndAuth> {
    let email = select_email_sender();
    let device_grants = build_device_grant_store().await;
    let invitation_base_url = std::env::var("AGISTACK_INVITATION_BASE_URL")
        .unwrap_or_else(|_| "http://localhost:8000".into());
    let mode = select_persistence_mode(
        std::env::var("DATABASE_URL").ok(),
        env_flag_enabled(std::env::var("AGISTACK_DEV_MODE").ok().as_deref()),
    )?;
    match mode {
        PersistenceMode::Postgres(url) => {
            let pool = connect(&url).await?;
            // Additive-only: create the Rust-owned aux tables; never alters a
            // Python-owned table (shared-DB invariant).
            ensure_aux_schema(&pool).await?;

            let memory = Arc::new(
                MemoryService::new(
                    Arc::new(PgMemoryRepository::new(pool.clone())),
                    llm,
                    embedding,
                    Arc::new(SystemClock),
                )
                .with_vectors(Arc::new(PgVectorIndex::new(pool.clone()))),
            );
            let checkpoint: Arc<dyn CheckpointStore> =
                Arc::new(PgCheckpointStore::new(pool.clone()));
            // P2 identity over the same shared schema (users/api_keys/tenants).
            let identity: SharedIdentity = Arc::new(PgIdentityService::new(
                PgUserStore::new(pool.clone()),
                PgTenantRepository::new(pool.clone()),
                PgProjectReadRepository::new(pool.clone()),
                PgInvitationRepository::new(pool.clone()),
                email,
                device_grants,
                invitation_base_url,
            ));
            let authenticator: SharedAuthenticator = Arc::new(PgAuthenticator::new(
                PgApiKeyStore::new(pool.clone()),
                PgProjectStore::new(pool.clone()),
            ));
            let shares: SharedShares =
                Arc::new(PgShareService::new(PgShareRepository::new(pool.clone())));
            let trust: SharedTrust =
                Arc::new(PgTrustService::new(PgTrustRepository::new(pool.clone())));
            let skill_evolution_repo = PgSkillEvolutionRepository::new(pool.clone());
            let skills: SharedSkills = Arc::new(
                PgSkillService::new(PgSkillRepository::new(pool.clone()))
                    .with_evolution_repo(skill_evolution_repo.clone())
                    .with_evolution_scheduler(PgSkillEvolutionScheduler::new(skill_evolution_repo)),
            );
            let tenant_skill_configs: SharedTenantSkillConfigs = Arc::new(
                PgTenantSkillConfigService::new(PgTenantSkillConfigRepository::new(pool.clone())),
            );
            let workspaces: SharedWorkspaces = Arc::new(PgWorkspaceService::new(
                PgWorkspaceRepository::new(pool.clone()),
                object_store,
                autonomy_cooldown,
            ));
            let sandbox_repo = Some(PgProjectSandboxRepository::new(pool.clone()));
            let project_sandbox_config_repo = Some(PgProjectReadRepository::new(pool.clone()));
            eprintln!("[agistack] persistence: PostgreSQL (production, shared Python schema)");
            Ok((
                memory,
                checkpoint,
                authenticator,
                identity,
                shares,
                trust,
                skills,
                tenant_skill_configs,
                workspaces,
                Some(pool),
                sandbox_repo,
                project_sandbox_config_repo,
            ))
        }
        PersistenceMode::InMemoryDev => {
            let memory = Arc::new(
                MemoryService::new(
                    Arc::new(InMemoryMemoryRepository::new()),
                    llm,
                    embedding,
                    Arc::new(SystemClock),
                )
                .with_vectors(Arc::new(InMemoryVectorIndex::new())),
            );
            let checkpoint: Arc<dyn CheckpointStore> = Arc::new(InMemoryCheckpointStore::new());
            let authenticator: SharedAuthenticator = Arc::new(DevAuthenticator::new("dev-user"));
            let identity: SharedIdentity = Arc::new(DevIdentityService::with_device_grants(
                "dev-user",
                device_grants,
            ));
            let shares: SharedShares = Arc::new(DevShareService::new("dev-user"));
            let trust: SharedTrust = Arc::new(DevTrustService::new("dev-user"));
            let skills: SharedSkills = Arc::new(DevSkillService::new("dev-tenant"));
            let tenant_skill_configs: SharedTenantSkillConfigs =
                Arc::new(DevTenantSkillConfigService::new("dev-tenant"));
            let workspaces: SharedWorkspaces = Arc::new(DevWorkspaceService::with_object_store(
                "dev-user",
                object_store,
            ));
            eprintln!("[agistack] persistence: in-memory (dev); auth: dev stub (any ms_sk_ key)");
            Ok((
                memory,
                checkpoint,
                authenticator,
                identity,
                shares,
                trust,
                skills,
                tenant_skill_configs,
                workspaces,
                None,
                None,
                None,
            ))
        }
    }
}

async fn build_event_stream() -> Arc<dyn EventStream> {
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => match agistack_adapters_redis::connect(&url).await {
            Ok(stream) => {
                eprintln!("[agistack] event stream: Redis Streams via REDIS_URL");
                Arc::new(stream)
            }
            Err(err) => {
                eprintln!(
                    "[agistack] event stream: Redis unavailable ({err}); falling back to in-memory"
                );
                Arc::new(InMemoryEventStream::new())
            }
        },
        _ => {
            eprintln!("[agistack] event stream: in-memory (dev)");
            Arc::new(InMemoryEventStream::new())
        }
    }
}

async fn build_workspace_autonomy_cooldown_store() -> Option<SharedAutonomyCooldownStore> {
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => {
            match agistack_adapters_redis::RedisWorkspaceAutonomyCooldownStore::connect(&url).await
            {
                Ok(store) => {
                    eprintln!("[agistack] workspace autonomy cooldown: Redis TTL via REDIS_URL");
                    Some(Arc::new(store))
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] workspace autonomy cooldown: Redis unavailable ({err}); skipping cooldown"
                    );
                    None
                }
            }
        }
        _ => {
            eprintln!("[agistack] workspace autonomy cooldown: disabled (no REDIS_URL)");
            None
        }
    }
}

async fn build_sandbox_http_service_registry() -> SharedHttpServiceRegistry {
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => {
            match agistack_adapters_redis::RedisSandboxHttpRegistry::connect(&url).await {
                Ok(registry) => {
                    eprintln!("[agistack] sandbox HTTP services: Redis registry via REDIS_URL");
                    Arc::new(registry)
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] sandbox HTTP services: Redis unavailable ({err}); falling back to in-memory"
                    );
                    in_memory_http_service_registry()
                }
            }
        }
        _ => {
            eprintln!("[agistack] sandbox HTTP services: in-memory (dev)");
            in_memory_http_service_registry()
        }
    }
}

async fn build_worker_launch_runtime_state_store() -> Option<Arc<dyn WorkerLaunchRuntimeStateStore>>
{
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => {
            match agistack_adapters_redis::RedisWorkerLaunchStateStore::connect(&url).await {
                Ok(store) => {
                    eprintln!("[agistack] worker launch state: Redis markers via REDIS_URL");
                    Some(Arc::new(store))
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] worker launch state: Redis unavailable ({err}); duplicate launch guard disabled"
                    );
                    None
                }
            }
        }
        _ => {
            eprintln!("[agistack] worker launch state: no Redis cooldown guard (dev)");
            None
        }
    }
}

async fn build_graph_store() -> Arc<dyn GraphStore> {
    match std::env::var("NEO4J_URI") {
        Ok(uri) if !uri.is_empty() => {
            let user = std::env::var("NEO4J_USER").unwrap_or_else(|_| "neo4j".into());
            let password = std::env::var("NEO4J_PASSWORD").unwrap_or_else(|_| "password".into());
            match connect_neo4j(&uri, &user, &password).await {
                Ok(graph) => {
                    eprintln!("[agistack] graph store: Neo4j via NEO4J_URI");
                    Arc::new(Neo4jGraphStore::new(graph))
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] graph store: Neo4j unavailable ({err}); falling back to in-memory"
                    );
                    Arc::new(InMemoryGraphStore::new())
                }
            }
        }
        _ => {
            eprintln!("[agistack] graph store: in-memory (dev)");
            Arc::new(InMemoryGraphStore::new())
        }
    }
}

async fn build_container_runtime() -> Arc<dyn ContainerRuntime> {
    let runtime = std::env::var("AGISTACK_CONTAINER_RUNTIME")
        .ok()
        .or_else(|| std::env::var("AGISTACK_SANDBOX_RUNTIME").ok())
        .unwrap_or_else(|| "memory".to_string());
    let wants_docker = runtime.eq_ignore_ascii_case("docker")
        || std::env::var("AGISTACK_DOCKER_SANDBOX")
            .map(|value| value == "1" || value.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

    if wants_docker {
        let raw_pull_policy = std::env::var("AGISTACK_SANDBOX_IMAGE_PULL").ok();
        let image_pull_policy = match raw_pull_policy.as_deref() {
            Some(raw) if !raw.trim().is_empty() => match ImagePullPolicy::parse(raw) {
                Some(policy) => policy,
                None => {
                    eprintln!(
                        "[agistack] invalid AGISTACK_SANDBOX_IMAGE_PULL={raw:?}; using if_missing"
                    );
                    ImagePullPolicy::IfMissing
                }
            },
            _ => ImagePullPolicy::IfMissing,
        };
        match DockerContainerRuntime::connect_with_image_pull_policy(image_pull_policy).await {
            Ok(runtime) => {
                eprintln!(
                    "[agistack] sandbox runtime: Docker via ContainerRuntime (image_pull={image_pull_policy})"
                );
                Arc::new(runtime)
            }
            Err(err) => {
                eprintln!(
                    "[agistack] sandbox runtime: Docker unavailable ({err}); falling back to in-memory"
                );
                Arc::new(InMemoryContainerRuntime::new())
            }
        }
    } else {
        eprintln!("[agistack] sandbox runtime: in-memory (dev)");
        Arc::new(InMemoryContainerRuntime::new())
    }
}

fn select_sandbox_auth_secret(
    dedicated: Option<String>,
    fallback: Option<String>,
) -> Option<String> {
    dedicated
        .filter(|secret| !secret.trim().is_empty())
        .or_else(|| fallback.filter(|secret| !secret.trim().is_empty()))
}

async fn build_state() -> ServerResult<AppState> {
    // Cloud↔local DI switch at the composition root (Phase 3, 03 §2): when
    // `AGISTACK_LLM_BASE_URL` is set, route the LLM/embedding ports to a real
    // OpenAI-/LiteLLM-compatible endpoint (`adapters-http-llm`); otherwise use
    // the deterministic offline stubs. The core never sees which — it only holds
    // `Arc<dyn LlmPort>` / `Arc<dyn EmbeddingPort>` (ADR-0001).
    let (llm, embedding) = select_llm_and_embedding();

    let registry = build_registry();
    let object_store = build_object_store().await;
    let autonomy_cooldown = build_workspace_autonomy_cooldown_store().await;

    // Persistence + auth: Postgres (production) or in-memory (dev), selected by
    // `DATABASE_URL`. This is the strangler cutover switch.
    let (
        memory,
        checkpoint,
        auth,
        identity,
        shares,
        trust,
        skills,
        tenant_skill_configs,
        workspaces,
        workspace_plan_pool,
        sandbox_repo,
        project_config_repo,
    ) = build_memory_and_auth(
        llm.clone(),
        embedding,
        Arc::clone(&object_store),
        autonomy_cooldown,
    )
    .await?;
    let events = build_event_stream().await;
    let agent_event_writer = workspace_plan_pool
        .clone()
        .map(PgAgentExecutionEventRepository::new);
    let hitl = build_hitl_response_service(workspace_plan_pool.clone(), Arc::clone(&events));
    let agent_events: SharedAgentEvents = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgAgentEventReplayService::new(
            PgAgentExecutionEventRepository::new(pool),
        )),
        None => Arc::new(DevAgentEventReplayService::new(Arc::clone(&events))),
    };
    let agent_conversations: SharedAgentConversations = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgAgentConversationService::new(
            PgAgentConversationRepository::new(pool.clone()),
            PgAgentExecutionEventRepository::new(pool.clone()),
            PgHitlRequestRepository::new(pool),
        )),
        None => Arc::new(DevAgentConversationService::new(Arc::clone(&events))),
    };
    let event_logs: SharedEventLogs = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgEventLogService::new(PgEventLogRepository::new(pool))),
        None => Arc::new(DevEventLogService::default()),
    };
    let audit_logs: SharedAuditLogs = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgAuditLogService::new(PgAuditLogRepository::new(pool))),
        None => Arc::new(DevAuditLogService::default()),
    };
    let notifications: SharedNotifications = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgNotificationService::new(PgNotificationRepository::new(
            pool,
        ))),
        None => Arc::new(DevNotificationService::default()),
    };
    let billing: SharedBilling = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgBillingService::new(PgBillingRepository::new(pool))),
        None => Arc::new(DevBillingService::default()),
    };
    let support: SharedSupport = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgSupportService::new(PgSupportRepository::new(pool))),
        None => Arc::new(DevSupportService::default()),
    };
    let artifacts: SharedArtifacts = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgArtifactService::new(
            PgArtifactRepository::new(pool),
            Arc::clone(&object_store),
        )),
        None => Arc::new(DevArtifactService::with_object_store(
            Vec::new(),
            Arc::clone(&object_store),
        )),
    };
    let attachments: SharedAttachments = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgAttachmentService::new(
            PgAttachmentRepository::new(pool),
            Arc::clone(&object_store),
        )),
        None => Arc::new(DevAttachmentService::with_object_store(
            Vec::new(),
            HashMap::new(),
            Arc::clone(&object_store),
        )),
    };
    let admin_access = build_admin_access(workspace_plan_pool.clone());
    let admin_dlq = build_admin_dlq_service(workspace_plan_pool.clone()).await;
    let llm_providers: SharedLlmProviders = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgLlmProviderCatalogService::new(
            PgLlmProviderRepository::new(pool),
        )),
        None => Arc::new(DevLlmProviderCatalogService::default()),
    };
    let llm_provider_health: SharedLlmProviderHealth = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgLlmProviderHealthService::new(
            PgLlmProviderRepository::new(pool),
        )),
        None => Arc::new(DevLlmProviderHealthService::default()),
    };
    let llm_provider_assignments: SharedLlmProviderAssignments = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgLlmProviderAssignmentService::new(
            PgLlmProviderRepository::new(pool),
        )),
        None => Arc::new(DevLlmProviderAssignmentService::default()),
    };
    let llm_provider_usage: SharedLlmProviderUsage = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgLlmProviderUsageService::new(
            PgLlmProviderRepository::new(pool),
        )),
        None => Arc::new(DevLlmProviderUsageService),
    };
    let tenant_webhooks: SharedTenantWebhooks = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgTenantWebhookService::new(PgTenantWebhookRepository::new(
            pool,
        ))),
        None => Arc::new(DevTenantWebhookService::default()),
    };
    let project_schema: SharedProjectSchema = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgProjectSchemaService::new(PgSchemaRepository::new(pool))),
        None => Arc::new(DevProjectSchemaService::default()),
    };
    let cron_jobs: SharedCronJobs = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgCronJobService::new(PgCronRepository::new(pool))),
        None => Arc::new(DevCronJobService::default()),
    };
    let data_stats: SharedDataStats = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgDataStatsScopeService::new(PgDataStatsRepository::new(
            pool,
        ))),
        None => Arc::new(DevDataStatsScopeService::default()),
    };
    let deploys: SharedDeploys = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgDeployService::new(PgDeployRepository::new(pool))),
        None => Arc::new(DevDeployService::default()),
    };
    let subagent_templates: SharedSubagentTemplates = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgSubagentTemplateService::new(
            PgSubagentTemplateRepository::new(pool),
        )),
        None => Arc::new(DevSubagentTemplateService::default()),
    };
    let instances: SharedInstances = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgInstanceService::new(PgInstanceRepository::new(pool))),
        None => Arc::new(DevInstanceService::default()),
    };
    let genes: SharedGenes = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgGeneService::new(PgGeneRepository::new(pool))),
        None => Arc::new(DevGeneService::default()),
    };
    let graph_stores: SharedGraphStores = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgGraphStoreCatalogService::new(
            PgGraphStoreRepository::new(pool),
        )),
        None => Arc::new(DevGraphStoreCatalogService::new("dev-tenant")),
    };
    let retrieval_stores: SharedRetrievalStores = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgRetrievalStoreCatalogService::new(
            PgRetrievalStoreRepository::new(pool),
        )),
        None => Arc::new(DevRetrievalStoreCatalogService::new("dev-tenant")),
    };
    let channels: SharedChannels = match workspace_plan_pool.clone() {
        Some(pool) => Arc::new(PgChannelService::new(PgChannelRepository::new(pool))),
        None => Arc::new(DevChannelService::new()),
    };
    let channel_outbox_delivery_worker = workspace_plan_pool.clone().map(|pool| {
        Arc::new(ChannelOutboxDeliveryWorker::new(
            PgChannelRepository::new(pool),
            FeishuWebhookDeliverer::default(),
            ChannelOutboxDeliveryWorkerConfig::from_env(),
        ))
    });
    let skill_evolution_worker = workspace_plan_pool.clone().map(|pool| {
        let executor = skill_evolution_executor_from_env(
            PgSkillEvolutionRepository::new(pool.clone()),
            PgSkillRepository::new(pool.clone()),
        );
        Arc::new(PgSkillEvolutionWorker::new(
            PgSkillEvolutionRepository::new(pool),
            executor,
        ))
    });
    let graph = build_graph_store().await;
    let sandbox_runtime = build_container_runtime().await;
    let sandbox_http_registry = build_sandbox_http_service_registry().await;
    let worker_launch_runtime_state = build_worker_launch_runtime_state_store().await;
    let workspace_mention_runtime = workspace_agent_mention_runtime_from_env(Arc::clone(&llm));
    let sandbox_image = std::env::var("AGISTACK_SANDBOX_IMAGE")
        .unwrap_or_else(|_| DEFAULT_SANDBOX_IMAGE.to_string());
    let tool_host: Arc<dyn ToolHost> = Arc::new(registry.clone());
    let mut sandbox_service = match sandbox_repo {
        Some(repo) => ProjectSandboxService::with_postgres(sandbox_runtime, sandbox_image, repo),
        None => ProjectSandboxService::new(sandbox_runtime, sandbox_image),
    };
    let sandbox_auth_secret = select_sandbox_auth_secret(
        std::env::var("AGISTACK_SANDBOX_AUTH_SECRET").ok(),
        std::env::var("SECRET_KEY").ok(),
    );
    if let Some(secret) = sandbox_auth_secret {
        sandbox_service = sandbox_service
            .with_runtime_auth_secret(secret)
            .map_err(std::io::Error::other)?;
    } else {
        eprintln!(
            "[agistack] sandbox runtime auth: not configured; cloud sandbox creation will fail closed"
        );
    }
    if let Some(repo) = project_config_repo {
        sandbox_service = sandbox_service
            .with_project_config_source(Arc::new(PgProjectSandboxConfigSource::new(repo)));
    }
    let sandboxes = Arc::new(
        sandbox_service
            .with_http_service_registry(sandbox_http_registry)
            .with_tool_host(Arc::clone(&tool_host))
            .with_ws_mcp_connector(),
    );
    let workspace_plan_outbox_worker = workspace_plan_pool.clone().map(|pool| {
        let stage_runner: Arc<dyn WorkspacePipelineStageRunner> = Arc::new(
            ProjectSandboxPipelineStageRunner::new(Arc::clone(&sandboxes)),
        );
        let worker_stream_events = worker_launch_event_stream_source(Arc::clone(&events));
        let handlers = match worker_launch_runtime_state.clone() {
            Some(runtime_state) => workspace_plan_outbox_handlers_with_runtime_state_and_streams(
                Arc::new(PgWorkspaceRepository::new(pool.clone())),
                Some(Arc::clone(&stage_runner)),
                Some(runtime_state),
                Some(Arc::clone(&worker_stream_events)),
                workspace_mention_runtime.clone(),
                Some(Arc::clone(&events)),
            ),
            None => workspace_plan_outbox_handlers_with_runtime_state_and_streams(
                Arc::new(PgWorkspaceRepository::new(pool.clone())),
                Some(Arc::clone(&stage_runner)),
                None,
                Some(worker_stream_events),
                workspace_mention_runtime.clone(),
                Some(Arc::clone(&events)),
            ),
        };
        Arc::new(WorkspacePlanOutboxWorker::new(
            Arc::new(PgWorkspacePlanOutboxStore::new(PgWorkspaceRepository::new(
                pool.clone(),
            ))),
            WorkspacePlanOutboxWorkerConfig::from_env(),
            handlers,
        ))
    });
    let engine = Arc::new(ReActEngine::new(
        llm,
        Arc::clone(&tool_host),
        checkpoint,
        Arc::new(SystemClock),
    ));
    let cron_scheduler = workspace_plan_pool
        .map(|pool| build_pg_cron_scheduler(pool, Arc::clone(&engine), registry.clone()));

    let plugins = Arc::new(PluginHost::new(registry.clone()));
    let control = Arc::new(Mutex::new(ControlPlane::new()));
    let reconciler = Arc::new(Mutex::new(DataPlaneReconciler::new(registry.clone())));

    Ok(AppState {
        memory,
        engine,
        events,
        agent_event_writer,
        event_counter: Arc::new(AtomicU64::new(0)),
        registry,
        plugins,
        control,
        reconciler,
        auth,
        identity,
        shares,
        trust,
        admin_access,
        skills,
        skill_evolution_worker,
        tenant_skill_configs,
        workspaces,
        channels,
        channel_outbox_delivery_worker,
        hitl,
        agent_events,
        agent_conversations,
        event_logs,
        audit_logs,
        notifications,
        billing,
        support,
        artifacts,
        attachments,
        admin_dlq,
        llm_providers,
        llm_provider_health,
        llm_provider_assignments,
        llm_provider_usage,
        tenant_webhooks,
        project_schema,
        cron_jobs,
        cron_scheduler,
        data_stats,
        deploys,
        subagent_templates,
        instances,
        genes,
        graph_stores,
        retrieval_stores,
        workspace_plan_outbox_worker,
        graph,
        sandboxes,
    })
}

#[tokio::main]
async fn main() -> ServerResult<()> {
    let addr = std::env::var("AGISTACK_ADDR").unwrap_or_else(|_| "127.0.0.1:8088".to_string());
    let state = build_state().await?;
    let _workspace_plan_outbox_runtime = state
        .workspace_plan_outbox_worker
        .as_ref()
        .and_then(|worker| Arc::clone(worker).spawn_if_enabled());
    let _skill_evolution_runtime = state
        .skill_evolution_worker
        .as_ref()
        .and_then(|worker| Arc::clone(worker).spawn_if_enabled());
    let _channel_outbox_delivery_runtime = state
        .channel_outbox_delivery_worker
        .as_ref()
        .and_then(|worker| Arc::clone(worker).spawn_if_enabled());
    let cron_scheduler_runtime = state
        .cron_scheduler
        .as_ref()
        .and_then(|scheduler| Arc::clone(scheduler).spawn_if_enabled());
    let app = demo_api::router(state);
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    println!("agistack-server listening on http://{addr}");
    let serve_result = axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await;
    if let Some(runtime) = cron_scheduler_runtime {
        runtime.shutdown().await;
    }
    serve_result?;
    Ok(())
}

async fn shutdown_signal() {
    if let Err(error) = tokio::signal::ctrl_c().await {
        eprintln!("[agistack] failed to install shutdown signal handler: {error}");
    }
}

#[cfg(test)]
mod runtime_mode_tests {
    use super::*;

    #[test]
    fn missing_database_requires_explicit_dev_mode() {
        let error = select_persistence_mode(None, false).expect_err("must fail closed");
        assert!(error.to_string().contains("DATABASE_URL"));
    }

    #[test]
    fn explicit_dev_mode_preserves_offline_runtime() {
        assert_eq!(
            select_persistence_mode(None, true).expect("explicit dev mode"),
            PersistenceMode::InMemoryDev
        );
    }

    #[test]
    fn configured_database_always_selects_postgres() {
        assert_eq!(
            select_persistence_mode(Some("postgresql://db/memstack".into()), false)
                .expect("database mode"),
            PersistenceMode::Postgres("postgresql://db/memstack".into())
        );
    }

    #[test]
    fn default_sandbox_image_provides_the_sandbox_runtime() {
        assert_eq!(DEFAULT_SANDBOX_IMAGE, "sandbox-mcp-server:latest");
        assert_ne!(DEFAULT_SANDBOX_IMAGE, "redis:7-alpine");
    }

    #[test]
    fn blank_dedicated_sandbox_secret_uses_server_secret() {
        assert_eq!(
            select_sandbox_auth_secret(Some("  ".into()), Some("server-secret".into())),
            Some("server-secret".into())
        );
        assert_eq!(select_sandbox_auth_secret(Some("  ".into()), None), None);
    }
}
