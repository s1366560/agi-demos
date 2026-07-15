pub(super) use agistack_adapters_postgres::PgPool;
pub(super) use agistack_adapters_postgres::{
    connect, ensure_aux_schema, AgentExecutionEventListQuery, AgentExecutionTimelineQuery,
    ArtifactListQuery, AuditLogListQuery, BlackboardFileRecord, BlackboardOutboxRecord,
    BlackboardPostRecord, BlackboardReplyRecord, ChannelWebhookEventInsertRecord,
    ChannelWebhookSecretRecord, ChannelWebhookSessionCreateRecord, ConversationCreateRecord,
    ConversationListQuery, ConversationModePatch, ConversationMutationAccess,
    ConversationReplayAccess, CreateTenantWebhook, CronJobListQuery, DataStatsAccess,
    DataStatsScopeError, DeployAccess, DeployListQuery, GeneListQuery, GenomeListQuery,
    InstanceListQuery, InstanceMemberListQuery, InvitationRecord, LlmProviderCreateRecord,
    LlmProviderUpdateRecord, NewDecisionRecordRecord, NewHitlRequestRecord, NewShareRecord,
    NewTrustPolicyRecord, PgAdminAccessRepository, PgAgentConversationRepository,
    PgAgentExecutionEventRepository, PgApiKeyStore, PgArtifactRepository, PgAttachmentRepository,
    PgAuditLogRepository, PgBillingRepository, PgChannelRepository, PgCheckpointStore,
    PgCronRepository, PgDataStatsRepository, PgDeployRepository, PgEventLogRepository,
    PgGeneRepository, PgHitlRequestRepository, PgInstanceRepository, PgInvitationRepository,
    PgLlmProviderRepository, PgMemoryRepository, PgNotificationRepository, PgProjectReadRepository,
    PgProjectSandboxRepository, PgProjectStore, PgSchemaRepository, PgShareRepository,
    PgSkillEvolutionRepository, PgSkillRepository, PgSubagentTemplateRepository,
    PgSupportRepository, PgTenantRepository, PgTenantSkillConfigRepository,
    PgTenantWebhookRepository, PgTrustRepository, PgUserStore, PgVectorIndex,
    PgWorkspaceContextRepository, PgWorkspaceRepository, ProjectCreateRecord,
    ProjectListForUserQuery, ProjectLookup, ProjectMembersLookup, ProjectSandboxRecord,
    ProjectStatsLookup, ProjectUpdatePatch, RuntimeHookAuditQuery,
    SkillEvolutionJobAuditEventInsertRecord, SkillEvolutionJobInsertRecord, SkillProjectAccess,
    SkillRecord, SkillUpdateRecord, SkillVersionRecord, TenantAccessStatus, TenantAdminStatus,
    TenantEventLogListQuery, TenantLookup, TenantSkillConfigRecord, TenantUpdatePatch,
    TopologyEdgeRecord, TopologyNodeRecord, TrustDecisionResolution, UsageStatisticsQuery,
    WorkspaceAccess, WorkspaceContextRepositoryError, WorkspaceContextSwitchRequest,
    WorkspacePipelineRunRecord, WorkspacePipelineStageRunRecord,
    WorkspacePlanBlackboardEntryRecord, WorkspacePlanEventRecord, WorkspacePlanNodeRecord,
    WorkspacePlanOutboxRecord, WorkspacePlanRecord, WorkspaceProjectAccess, WorkspaceRecord,
    WorkspaceTaskRecord, WorkspaceTaskSessionAttemptRecord,
};
pub(super) use agistack_core::agent::types::{SessionState, SessionStatus};
pub(super) use agistack_core::model::{Entity, Memory};
pub(super) use agistack_core::ports::{CheckpointStore, MemoryRepository, VectorIndexPort};
pub(super) use serde_json::json;
pub(super) use sqlx::types::chrono::{DateTime, TimeZone, Utc};

/// Return a connected pool if `DATABASE_URL` is set, else `None` (skip).
pub(super) async fn pool_or_skip(test: &str) -> Option<PgPool> {
    match std::env::var("DATABASE_URL") {
        Ok(url) if !url.is_empty() => match connect(&url).await {
            Ok(pool) => Some(pool),
            Err(e) => panic!("DATABASE_URL set but connect failed for {test}: {e}"),
        },
        _ => {
            eprintln!("[skip] {test}: DATABASE_URL unset");
            None
        }
    }
}

pub(super) fn ts(year: i32, month: u32, day: u32, hour: u32, min: u32, sec: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(year, month, day, hour, min, sec)
        .unwrap()
}

/// Create the minimal Python-shaped tables the adapter reads/writes, plus the
/// Rust-owned auxiliary schema.
///
/// An Alembic-managed database already owns the Python schema. Avoid issuing
/// additive DDL against those tables because even an `IF NOT EXISTS` alteration
/// requires an exclusive relation lock and can block a running Python backend.
/// Empty integration databases still receive the minimal compatibility schema.
pub(super) async fn ensure_python_shaped_tables(pool: &PgPool) {
    let python_schema_is_migration_managed =
        sqlx::query_scalar::<_, bool>("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            .fetch_one(pool)
            .await
            .expect("inspect Python schema ownership");

    if python_schema_is_migration_managed {
        ensure_aux_schema(pool).await.expect("aux schema");
        return;
    }

    for ddl in [
        "CREATE TABLE IF NOT EXISTS users (id text PRIMARY KEY, email text)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superuser boolean DEFAULT false",
        "CREATE TABLE IF NOT EXISTS tenants (id text PRIMARY KEY, name text)",
        "CREATE TABLE IF NOT EXISTS user_tenants (\
            id text PRIMARY KEY, user_id text NOT NULL, tenant_id text NOT NULL, \
            role text DEFAULT 'member', permissions json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS projects (\
            id text PRIMARY KEY, tenant_id text NOT NULL, name text NOT NULL, \
            owner_id text NOT NULL, is_public boolean DEFAULT false)",
        "CREATE TABLE IF NOT EXISTS conversations (\
            id text PRIMARY KEY, user_id text NOT NULL, tenant_id text NOT NULL, \
            project_id text NOT NULL, workspace_id text, meta json DEFAULT '{}'::json)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title varchar(500) NOT NULL DEFAULT 'Untitled'",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS status varchar(20) DEFAULT 'active' NOT NULL",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent_config json DEFAULT '{}'::json",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS message_count integer DEFAULT 0 NOT NULL",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS current_mode varchar(20) DEFAULT 'build' NOT NULL",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS merge_strategy varchar(20) DEFAULT 'result_only' NOT NULL",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS parent_conversation_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS branch_point_message_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS conversation_mode varchar(32)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS linked_workspace_task_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS participant_agents json DEFAULT '[]'::json",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS coordinator_agent_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS focused_agent_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS updated_at timestamptz",
        "CREATE TABLE IF NOT EXISTS agent_execution_events (\
            id text PRIMARY KEY, conversation_id text NOT NULL, message_id text, \
            event_type varchar(80) NOT NULL, event_data json DEFAULT '{}'::json NOT NULL, \
            event_time_us bigint NOT NULL, event_counter integer NOT NULL, \
            correlation_id text, created_at timestamptz DEFAULT now())",
        "CREATE INDEX IF NOT EXISTS ix_agent_execution_events_conversation_cursor \
            ON agent_execution_events (conversation_id, event_time_us, event_counter)",
        "CREATE TABLE IF NOT EXISTS tool_execution_records (\
            id text PRIMARY KEY, conversation_id text NOT NULL, message_id text NOT NULL, \
            call_id text NOT NULL, tool_name varchar(100) NOT NULL, tool_input json DEFAULT '{}'::json, \
            tool_output text, status varchar(20) NOT NULL, error text, step_number integer, \
            sequence_number integer NOT NULL, started_at timestamptz DEFAULT now(), \
            completed_at timestamptz, duration_ms integer)",
        "CREATE INDEX IF NOT EXISTS ix_tool_execution_records_conversation \
            ON tool_execution_records (conversation_id)",
        "CREATE TABLE IF NOT EXISTS tenant_event_logs (\
            id text PRIMARY KEY, tenant_id text NOT NULL, event_type varchar(64) NOT NULL, \
            message text NOT NULL, source varchar(64) NOT NULL, metadata json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now())",
        "CREATE INDEX IF NOT EXISTS ix_tenant_event_logs_tenant_created \
            ON tenant_event_logs (tenant_id, created_at)",
        "CREATE TABLE IF NOT EXISTS llm_providers (\
            id uuid PRIMARY KEY, name varchar(255) UNIQUE NOT NULL, provider_type varchar(50) NOT NULL, \
            operation_type varchar(20) DEFAULT 'llm' NOT NULL, api_key_encrypted text NOT NULL, \
            base_url text, config json DEFAULT '{}'::json NOT NULL, is_active boolean DEFAULT true NOT NULL, \
            is_default boolean DEFAULT false NOT NULL, is_enabled boolean DEFAULT true NOT NULL, \
            pool_weight double precision DEFAULT 1.0 NOT NULL, pool_enabled boolean DEFAULT true NOT NULL, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS llm_model varchar(100)",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS llm_small_model varchar(100)",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS embedding_model varchar(100)",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS reranker_model varchar(100)",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS allowed_models text",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS blocked_models text",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS model_tier varchar(16)",
        "ALTER TABLE llm_providers ADD COLUMN IF NOT EXISTS secondary_models json",
        "CREATE TABLE IF NOT EXISTS provider_health (\
            provider_id uuid NOT NULL, last_check timestamptz DEFAULT now() NOT NULL, \
            status varchar(20) NOT NULL, error_message text, response_time_ms integer, \
            PRIMARY KEY (provider_id, last_check))",
        "CREATE INDEX IF NOT EXISTS idx_provider_health_status \
            ON provider_health (provider_id, last_check)",
        "CREATE TABLE IF NOT EXISTS tenant_provider_mappings (\
            id uuid PRIMARY KEY, tenant_id varchar(255) NOT NULL, \
            operation_type varchar(20) DEFAULT 'llm' NOT NULL, provider_id uuid NOT NULL, \
            priority integer DEFAULT 0 NOT NULL, created_at timestamptz DEFAULT now())",
        "CREATE INDEX IF NOT EXISTS idx_tenant_mappings_tenant \
            ON tenant_provider_mappings (tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_tenant_mappings_priority \
            ON tenant_provider_mappings (priority)",
        "CREATE TABLE IF NOT EXISTS llm_usage_logs (\
            id uuid PRIMARY KEY, provider_id uuid, tenant_id varchar(255), \
            operation_type varchar(50) NOT NULL, model_name varchar(100) NOT NULL, \
            prompt_tokens integer DEFAULT 0 NOT NULL, \
            completion_tokens integer DEFAULT 0 NOT NULL, cost_usd double precision, \
            created_at timestamptz DEFAULT now() NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_provider \
            ON llm_usage_logs (provider_id)",
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_logs_tenant \
            ON llm_usage_logs (tenant_id)",
        "CREATE TABLE IF NOT EXISTS audit_logs (\
            id text PRIMARY KEY, \"timestamp\" timestamptz DEFAULT now(), actor text, \
            action text NOT NULL, resource_type text NOT NULL, resource_id text, tenant_id text, \
            details json DEFAULT '{}'::json, ip_address text, user_agent text)",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action \
            ON audit_logs (tenant_id, action)",
        "CREATE TABLE IF NOT EXISTS roles (\
            id text PRIMARY KEY, name text UNIQUE NOT NULL, description text, \
            created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS user_roles (\
            id text PRIMARY KEY, user_id text NOT NULL, role_id text NOT NULL, \
            tenant_id text, project_id text, created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS notifications (\
            id text PRIMARY KEY, user_id text NOT NULL, type text NOT NULL, \
            title text NOT NULL, message text NOT NULL, data json, is_read boolean DEFAULT false, \
            action_url text, created_at timestamptz DEFAULT now(), expires_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS invoices (\
            id text PRIMARY KEY, tenant_id text NOT NULL, amount integer NOT NULL, \
            currency text NOT NULL, status text NOT NULL, period_start timestamptz NOT NULL, \
            period_end timestamptz NOT NULL, created_at timestamptz DEFAULT now(), \
            paid_at timestamptz, invoice_url text)",
        "CREATE TABLE IF NOT EXISTS support_tickets (\
            id text PRIMARY KEY, tenant_id text, user_id text NOT NULL, subject text NOT NULL, \
            message text NOT NULL, priority text NOT NULL, status text DEFAULT 'open', \
            created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(), \
            resolved_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS artifacts (\
            id text PRIMARY KEY, project_id text NOT NULL, tenant_id text NOT NULL, \
            sandbox_id text, tool_execution_id text, conversation_id text, workspace_id text, \
            filename text NOT NULL, mime_type text NOT NULL, category text NOT NULL, \
            size_bytes bigint DEFAULT 0 NOT NULL, object_key text NOT NULL, url text, \
            preview_url text, status text DEFAULT 'pending' NOT NULL, error_message text, \
            source_tool text, source_path text, artifact_metadata json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now())",
        "CREATE INDEX IF NOT EXISTS ix_artifacts_project_status \
            ON artifacts (project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_artifacts_tool_execution \
            ON artifacts (tool_execution_id)",
        "CREATE TABLE IF NOT EXISTS attachments (\
            id text PRIMARY KEY, conversation_id text NOT NULL, project_id text NOT NULL, \
            tenant_id text NOT NULL, filename text NOT NULL, mime_type text NOT NULL, \
            size_bytes bigint NOT NULL, object_key text NOT NULL, purpose text NOT NULL, \
            status text DEFAULT 'pending' NOT NULL, upload_id text, total_parts integer, \
            uploaded_parts integer DEFAULT 0 NOT NULL, sandbox_path text, file_metadata json, \
            error_message text, created_at timestamptz DEFAULT now() NOT NULL, expires_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_attachments_conv_status \
            ON attachments (conversation_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_attachments_status \
            ON attachments (status)",
        "CREATE TABLE IF NOT EXISTS entity_types (\
            id text PRIMARY KEY, project_id text NOT NULL, name text NOT NULL, \
            description text, schema json DEFAULT '{}'::json, status text DEFAULT 'ENABLED', \
            source text DEFAULT 'user', created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS edge_types (\
            id text PRIMARY KEY, project_id text NOT NULL, name text NOT NULL, \
            description text, schema json DEFAULT '{}'::json, status text DEFAULT 'ENABLED', \
            source text DEFAULT 'user', created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS edge_type_maps (\
            id text PRIMARY KEY, project_id text NOT NULL, source_type text NOT NULL, \
            target_type text NOT NULL, edge_type text NOT NULL, status text DEFAULT 'ENABLED', \
            source text DEFAULT 'user', created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS instances (\
            id text PRIMARY KEY, name varchar(100) DEFAULT '' NOT NULL, \
            slug varchar(100) DEFAULT '' NOT NULL, tenant_id text NOT NULL, \
            description text, cluster_id text, namespace varchar(100), \
            image_version varchar(100) DEFAULT 'latest', replicas integer DEFAULT 1, \
            cpu_request varchar(20) DEFAULT '100m', cpu_limit varchar(20) DEFAULT '500m', \
            mem_request varchar(20) DEFAULT '256Mi', mem_limit varchar(20) DEFAULT '512Mi', \
            service_type varchar(20) DEFAULT 'ClusterIP', ingress_domain text, proxy_token text, \
            env_vars json DEFAULT '{}'::json, quota_cpu varchar(20), quota_memory varchar(20), \
            quota_max_pods integer, storage_class varchar(50), storage_size varchar(20), \
            advanced_config json DEFAULT '{}'::json, llm_providers json DEFAULT '{}'::json, \
            pending_config json DEFAULT '{}'::json, available_replicas integer DEFAULT 0, \
            status varchar(20) DEFAULT 'creating', health_status varchar(20), \
            current_revision integer DEFAULT 0, compute_provider varchar(50), \
            runtime varchar(50) DEFAULT 'default', created_by text DEFAULT '', workspace_id text, \
            hex_position_q integer, hex_position_r integer, agent_display_name varchar(100), \
            agent_label varchar(100), theme_color varchar(20), \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_instances_tenant_status \
            ON instances (tenant_id, status)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS description text",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS cluster_id text",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS namespace varchar(100)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS image_version varchar(100) DEFAULT 'latest'",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS replicas integer DEFAULT 1",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS cpu_request varchar(20) DEFAULT '100m'",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS cpu_limit varchar(20) DEFAULT '500m'",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS mem_request varchar(20) DEFAULT '256Mi'",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS mem_limit varchar(20) DEFAULT '512Mi'",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS service_type varchar(20) DEFAULT 'ClusterIP'",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS ingress_domain text",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS proxy_token text",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS env_vars json DEFAULT '{}'::json",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS quota_cpu varchar(20)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS quota_memory varchar(20)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS quota_max_pods integer",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS storage_class varchar(50)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS storage_size varchar(20)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS advanced_config json DEFAULT '{}'::json",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS llm_providers json DEFAULT '{}'::json",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS pending_config json DEFAULT '{}'::json",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS available_replicas integer DEFAULT 0",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS health_status varchar(20)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS current_revision integer DEFAULT 0",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS compute_provider varchar(50)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS runtime varchar(50) DEFAULT 'default'",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS created_by text DEFAULT ''",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS workspace_id text",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS hex_position_q integer",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS hex_position_r integer",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS agent_display_name varchar(100)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS agent_label varchar(100)",
        "ALTER TABLE instances ADD COLUMN IF NOT EXISTS theme_color varchar(20)",
        "CREATE TABLE IF NOT EXISTS instance_channel_configs (\
            id text PRIMARY KEY, instance_id text NOT NULL, channel_type varchar(50) NOT NULL, \
            name varchar(200) NOT NULL, config json DEFAULT '{}'::json NOT NULL, \
            status varchar(20) DEFAULT 'pending' NOT NULL, last_connected_at timestamptz, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz, \
            deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_instance_channel_configs_instance \
            ON instance_channel_configs (instance_id)",
        "CREATE TABLE IF NOT EXISTS instance_members (\
            id text PRIMARY KEY, instance_id text NOT NULL, user_id text NOT NULL, \
            role varchar(20) DEFAULT 'viewer', created_at timestamptz DEFAULT now(), \
            deleted_at timestamptz)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_instance_members_instance_user \
            ON instance_members (instance_id, user_id)",
        "CREATE TABLE IF NOT EXISTS gene_market (\
            id text PRIMARY KEY, name varchar(100) NOT NULL, slug varchar(100) NOT NULL, \
            tenant_id text, description text, short_description varchar(300), category varchar(50), \
            tags json, source varchar(20) DEFAULT 'official', source_ref varchar(200), \
            icon varchar(200), version varchar(20) DEFAULT '1.0.0', manifest json DEFAULT '{}'::json, \
            dependencies json DEFAULT '[]'::json, synergies json DEFAULT '[]'::json, \
            parent_gene_id text, created_by_instance_id text, install_count integer DEFAULT 0, \
            avg_rating double precision DEFAULT 0, effectiveness_score double precision DEFAULT 0, \
            is_featured boolean DEFAULT false, review_status varchar(20) DEFAULT 'pending', \
            is_published boolean DEFAULT false, visibility varchar(20) DEFAULT 'public', \
            created_by text DEFAULT '', created_at timestamptz DEFAULT now(), \
            updated_at timestamptz, deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_gene_market_tenant_created \
            ON gene_market (tenant_id, created_at)",
        "CREATE TABLE IF NOT EXISTS genomes (\
            id text PRIMARY KEY, name varchar(100) NOT NULL, slug varchar(100) NOT NULL, \
            tenant_id text, description text, short_description varchar(300), icon varchar(200), \
            gene_slugs json DEFAULT '[]'::json, config_override json DEFAULT '{}'::json, \
            install_count integer DEFAULT 0, avg_rating double precision DEFAULT 0, \
            is_featured boolean DEFAULT false, is_published boolean DEFAULT false, \
            visibility varchar(20) DEFAULT 'public', created_by text DEFAULT '', \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_genomes_tenant_created \
            ON genomes (tenant_id, created_at)",
        "CREATE TABLE IF NOT EXISTS instance_genes (\
            id text PRIMARY KEY, instance_id text NOT NULL, gene_id text NOT NULL, \
            genome_id text, status varchar(20) DEFAULT 'installed', installed_version varchar(20), \
            config_snapshot json DEFAULT '{}'::json, usage_count integer DEFAULT 0, \
            installed_at timestamptz, created_at timestamptz DEFAULT now(), deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_instance_genes_instance \
            ON instance_genes (instance_id, gene_id)",
        "CREATE TABLE IF NOT EXISTS deploy_records (\
            id text PRIMARY KEY, instance_id text NOT NULL, revision integer NOT NULL, \
            action varchar(20) NOT NULL, image_version varchar(100), replicas integer, \
            config_snapshot json DEFAULT '{}'::json, status varchar(20) DEFAULT 'pending' NOT NULL, \
            message text, triggered_by text, started_at timestamptz, finished_at timestamptz, \
            created_at timestamptz DEFAULT now(), deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_deploy_records_instance_created \
            ON deploy_records (instance_id, created_at)",
        "CREATE TABLE IF NOT EXISTS cron_jobs (\
            id text PRIMARY KEY, project_id text NOT NULL, tenant_id text NOT NULL, \
            name varchar(255) NOT NULL, description text, enabled boolean DEFAULT true, \
            delete_after_run boolean DEFAULT false, revision bigint DEFAULT 1 NOT NULL, \
            schedule_revision bigint DEFAULT 1 NOT NULL, schedule_type varchar(50) NOT NULL, \
            schedule_config json DEFAULT '{}'::json, payload_type varchar(50) NOT NULL, \
            payload_config json DEFAULT '{}'::json, delivery_type varchar(50) DEFAULT 'none', \
            delivery_config json DEFAULT '{}'::json, conversation_mode varchar(50) DEFAULT 'reuse', \
            conversation_id text, timezone varchar(100) DEFAULT 'UTC', \
            stagger_seconds integer DEFAULT 0, timeout_seconds integer DEFAULT 300, \
            max_retries integer DEFAULT 3, state json DEFAULT '{}'::json, created_by text, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_cron_jobs_project_enabled \
            ON cron_jobs (project_id, enabled)",
        "CREATE TABLE IF NOT EXISTS cron_job_runs (\
            id text PRIMARY KEY, job_id text NOT NULL, project_id text NOT NULL, \
            status varchar(50) NOT NULL, trigger_type varchar(50) DEFAULT 'scheduled', \
            started_at timestamptz DEFAULT now(), finished_at timestamptz, \
            duration_ms integer, error_message text, result_summary json DEFAULT '{}'::json, \
            conversation_id text)",
        "CREATE INDEX IF NOT EXISTS ix_cron_job_runs_job_status \
            ON cron_job_runs (job_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_cron_job_runs_project_started \
            ON cron_job_runs (project_id, started_at)",
        "CREATE TABLE IF NOT EXISTS webhooks (\
            id text PRIMARY KEY, tenant_id text NOT NULL, name text NOT NULL, url text NOT NULL, \
            secret text, events json DEFAULT '[]'::json NOT NULL, is_active boolean DEFAULT true, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, deleted_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS graph_stores (\
            id text PRIMARY KEY, name varchar(255) NOT NULL, tenant_id text NOT NULL, \
            engine_type varchar(50) DEFAULT 'neo4j' NOT NULL, connection_config_encrypted text, \
            index_config json DEFAULT '{}'::json NOT NULL, status varchar(50) DEFAULT 'disconnected' NOT NULL, \
            health_status varchar(50), last_health_check timestamptz, detected_version varchar(100), \
            created_by text DEFAULT '' NOT NULL, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz, deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_graph_stores_tenant_status \
            ON graph_stores (tenant_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_graph_stores_tenant_engine \
            ON graph_stores (tenant_id, engine_type)",
        "CREATE TABLE IF NOT EXISTS retrieval_stores (\
            id text PRIMARY KEY, name varchar(255) NOT NULL, tenant_id text NOT NULL, \
            engine_type varchar(50) DEFAULT 'memstack_pgvector' NOT NULL, connection_config_encrypted text, \
            index_config json DEFAULT '{}'::json NOT NULL, status varchar(50) DEFAULT 'disconnected' NOT NULL, \
            health_status varchar(50), last_health_check timestamptz, detected_version varchar(100), \
            created_by text DEFAULT '' NOT NULL, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz, deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_retrieval_stores_tenant_status \
            ON retrieval_stores (tenant_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_retrieval_stores_tenant_engine \
            ON retrieval_stores (tenant_id, engine_type)",
        "CREATE TABLE IF NOT EXISTS project_sandboxes (\
            id text PRIMARY KEY, project_id text NOT NULL UNIQUE, tenant_id text NOT NULL, \
            sandbox_id text NOT NULL UNIQUE, sandbox_type varchar(20) DEFAULT 'cloud' NOT NULL, \
            status varchar(20) DEFAULT 'pending' NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, started_at timestamptz, \
            last_accessed_at timestamptz DEFAULT now() NOT NULL, \
            health_checked_at timestamptz, error_message text, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            local_config json DEFAULT '{}'::json NOT NULL)",
        "CREATE TABLE IF NOT EXISTS user_projects (\
            user_id text NOT NULL, project_id text NOT NULL, role text DEFAULT 'member', \
            PRIMARY KEY (user_id, project_id))",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS role text DEFAULT 'member'",
        "CREATE TABLE IF NOT EXISTS api_keys (\
            id text PRIMARY KEY, key_hash text, name text, user_id text, \
            created_at timestamptz DEFAULT now(), expires_at timestamptz, \
            is_active boolean DEFAULT true, permissions json DEFAULT '[]'::json, \
            last_used_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS memories (\
            id text PRIMARY KEY, project_id text NOT NULL, title varchar(500) NOT NULL, \
            content text NOT NULL, content_type varchar(20) DEFAULT 'text', \
            tags json DEFAULT '[]'::json, entities json DEFAULT '[]'::json, \
            relationships json DEFAULT '[]'::json, version integer DEFAULT 1, \
            author_id text NOT NULL, collaborators json DEFAULT '[]'::json, \
            is_public boolean DEFAULT false, status text DEFAULT 'ENABLED', \
            processing_status text DEFAULT 'PENDING', meta json DEFAULT '{}'::json, \
            task_id text, created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS memory_shares (\
            id text PRIMARY KEY, memory_id text NOT NULL, share_token text UNIQUE, \
            shared_with_user_id text, shared_with_project_id text, \
            permissions json DEFAULT '{}'::json, shared_by text NOT NULL, \
            created_at timestamptz DEFAULT now(), expires_at timestamptz, \
            access_count integer DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS skills (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text, \
            name varchar(200) NOT NULL, description text NOT NULL, \
            tools json DEFAULT '[]'::json NOT NULL, status varchar(20) DEFAULT 'active' NOT NULL, \
            metadata_json json, created_at timestamptz DEFAULT now(), updated_at timestamptz, \
            scope varchar(20) DEFAULT 'tenant' NOT NULL, is_system_skill boolean DEFAULT false NOT NULL, \
            full_content text, resource_files json, license varchar(200), compatibility varchar(500), \
            allowed_tools_raw text, spec_version varchar(32) DEFAULT '1.0' NOT NULL, \
            current_version integer DEFAULT 0 NOT NULL, version_label varchar(50))",
        "CREATE TABLE IF NOT EXISTS skill_versions (\
            id text PRIMARY KEY, skill_id text NOT NULL, version_number integer NOT NULL, \
            version_label varchar(50), skill_md_content text NOT NULL, resource_files json, \
            change_summary text, created_by varchar(20) DEFAULT 'agent' NOT NULL, \
            created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS tenant_skill_configs (\
            id text PRIMARY KEY, tenant_id text NOT NULL, system_skill_name varchar(200) NOT NULL, \
            action varchar(20) NOT NULL, override_skill_id text, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_skill_configs_tenant_skill \
            ON tenant_skill_configs (tenant_id, system_skill_name)",
        "CREATE TABLE IF NOT EXISTS plugin_configs (\
            id text PRIMARY KEY, tenant_id text NOT NULL, plugin_name varchar(255) NOT NULL, \
            config json NOT NULL DEFAULT '{}'::json, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_plugin_configs_tenant_plugin \
            ON plugin_configs (tenant_id, plugin_name)",
        "CREATE TABLE IF NOT EXISTS skill_evolution_sessions (\
            id text PRIMARY KEY, skill_name varchar(200) NOT NULL, tenant_id text NOT NULL, \
            project_id text, conversation_id text NOT NULL, user_query text NOT NULL, \
            trajectory json, summary text, judge_scores json, overall_score double precision, \
            success boolean DEFAULT false NOT NULL, execution_time_ms integer DEFAULT 0 NOT NULL, \
            tool_call_count integer DEFAULT 0 NOT NULL, processed boolean DEFAULT false NOT NULL, \
            created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS skill_evolution_jobs (\
            id text PRIMARY KEY, skill_name varchar(200) NOT NULL, tenant_id text NOT NULL, \
            project_id text, action varchar(30) NOT NULL, candidate_content text, rationale text, \
            session_ids json, status varchar(30) DEFAULT 'pending_review' NOT NULL, \
            skill_version_id text, created_at timestamptz DEFAULT now(), applied_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS subagent_templates (\
            id text PRIMARY KEY, tenant_id text NOT NULL, name varchar(200) NOT NULL, \
            version varchar(20) DEFAULT '1.0.0' NOT NULL, display_name varchar(200), \
            description text, category varchar(100) DEFAULT 'general' NOT NULL, \
            tags json, system_prompt text DEFAULT '' NOT NULL, trigger_description text, \
            trigger_keywords json, trigger_examples json, model varchar(50) DEFAULT 'inherit' NOT NULL, \
            max_tokens integer DEFAULT 4096 NOT NULL, temperature double precision DEFAULT 0.7 NOT NULL, \
            max_iterations integer DEFAULT 10 NOT NULL, allowed_tools json DEFAULT '[\"*\"]'::json NOT NULL, \
            author varchar(200), is_builtin boolean DEFAULT false NOT NULL, \
            is_published boolean DEFAULT true NOT NULL, install_count integer DEFAULT 0 NOT NULL, \
            rating double precision DEFAULT 0.0 NOT NULL, metadata_json json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_subagent_templates_tenant_id \
            ON subagent_templates (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_subagent_templates_category \
            ON subagent_templates (category)",
        "CREATE INDEX IF NOT EXISTS ix_subagent_templates_is_published \
            ON subagent_templates (is_published)",
        "CREATE TABLE IF NOT EXISTS channel_configs (\
            id text PRIMARY KEY, project_id text NOT NULL, channel_type text NOT NULL, \
            name text NOT NULL, enabled boolean DEFAULT true, connection_mode text DEFAULT 'websocket', \
            app_id text, app_secret text, encrypt_key text, verification_token text, \
            webhook_url text, webhook_port integer, webhook_path text, \
            dm_policy text DEFAULT 'open' NOT NULL, group_policy text DEFAULT 'open' NOT NULL, \
            allow_from json, group_allow_from json, rate_limit_per_minute integer DEFAULT 60 NOT NULL, \
            model_override varchar(255), domain text DEFAULT 'feishu', extra_settings json, \
            status text DEFAULT 'disconnected', last_error text, description text, created_by text, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_channel_configs_project_type \
            ON channel_configs (project_id, channel_type)",
        "CREATE INDEX IF NOT EXISTS ix_channel_configs_project_enabled \
            ON channel_configs (project_id, enabled)",
        "CREATE TABLE IF NOT EXISTS channel_session_bindings (\
            id text PRIMARY KEY, project_id text NOT NULL, channel_config_id text NOT NULL, \
            conversation_id text NOT NULL, channel_type text NOT NULL, chat_id text NOT NULL, \
            chat_type text NOT NULL, thread_id text, topic_id text, session_key varchar(512) NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_session_bindings_project_session_key \
            ON channel_session_bindings (project_id, session_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_session_bindings_conversation_id \
            ON channel_session_bindings (conversation_id)",
        "CREATE INDEX IF NOT EXISTS ix_channel_session_bindings_project_chat \
            ON channel_session_bindings (project_id, chat_id)",
        "CREATE INDEX IF NOT EXISTS ix_channel_session_bindings_config_chat \
            ON channel_session_bindings (channel_config_id, chat_id)",
        "CREATE TABLE IF NOT EXISTS channel_outbox (\
            id text PRIMARY KEY, project_id text NOT NULL, channel_config_id text NOT NULL, \
            conversation_id text NOT NULL, chat_id text NOT NULL, reply_to_channel_message_id text, \
            content_text text NOT NULL, status varchar(20) DEFAULT 'pending' NOT NULL, \
            attempt_count integer DEFAULT 0 NOT NULL, max_attempts integer DEFAULT 3 NOT NULL, \
            sent_channel_message_id text, last_error text, next_retry_at timestamptz, \
            metadata_json json, created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_channel_outbox_status_retry \
            ON channel_outbox (status, next_retry_at)",
        "CREATE INDEX IF NOT EXISTS ix_channel_outbox_project_created \
            ON channel_outbox (project_id, created_at)",
        "CREATE TABLE IF NOT EXISTS workspaces (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL, \
            name varchar(255) NOT NULL, description text, created_by text NOT NULL, \
            is_archived boolean DEFAULT false NOT NULL, metadata_json json DEFAULT '{}'::json, \
            office_status varchar(20) DEFAULT 'inactive' NOT NULL, \
            hex_layout_config_json json DEFAULT '{}'::json, \
            default_blocking_categories_json json DEFAULT '[]'::json NOT NULL, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS workspace_members (\
            id text PRIMARY KEY, workspace_id text NOT NULL, user_id text NOT NULL, \
            role varchar(20) DEFAULT 'viewer' NOT NULL, invited_by text, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS agent_definitions (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text, name varchar(100) NOT NULL, \
            display_name varchar(200) NOT NULL, system_prompt text NOT NULL, \
            trigger_examples json, trigger_keywords json, model varchar(50) NOT NULL, \
            persona_files json, allowed_tools json NOT NULL, allowed_skills json NOT NULL, \
            allowed_mcp_servers json NOT NULL, max_tokens integer NOT NULL, \
            temperature double precision NOT NULL, max_iterations integer NOT NULL, \
            can_spawn boolean NOT NULL, max_spawn_depth integer NOT NULL, \
            agent_to_agent_enabled boolean NOT NULL, discoverable boolean NOT NULL, \
            source varchar(20) NOT NULL, enabled boolean NOT NULL, max_retries integer NOT NULL, \
            fallback_models json, total_invocations integer NOT NULL, \
            avg_execution_time_ms double precision NOT NULL, success_rate double precision NOT NULL)",
        "CREATE TABLE IF NOT EXISTS workspace_agents (\
            id text PRIMARY KEY, workspace_id text NOT NULL, agent_id text NOT NULL, \
            display_name varchar(255), description text, config_json json DEFAULT '{}'::json, \
            is_active boolean DEFAULT true NOT NULL, hex_q integer, hex_r integer, \
            theme_color varchar(20), label varchar(100), status varchar(20) DEFAULT 'idle' NOT NULL, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS workspace_tasks (\
            id text PRIMARY KEY, workspace_id text NOT NULL, title varchar(255) NOT NULL, \
            description text, created_by text NOT NULL, assignee_user_id text, \
            assignee_agent_id text, status varchar(20) DEFAULT 'todo' NOT NULL, \
            priority integer DEFAULT 0 NOT NULL, estimated_effort varchar(50), \
            blocker_reason text, metadata_json json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, \
            completed_at timestamptz, archived_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS workspace_task_session_attempts (\
            id text PRIMARY KEY, workspace_task_id text NOT NULL, root_goal_task_id text NOT NULL, \
            workspace_id text NOT NULL, attempt_number integer NOT NULL, \
            status varchar(40) DEFAULT 'pending' NOT NULL, conversation_id text, \
            worker_agent_id text, leader_agent_id text, candidate_summary text, \
            candidate_artifacts_json json DEFAULT '[]'::json NOT NULL, \
            candidate_verifications_json json DEFAULT '[]'::json NOT NULL, \
            leader_feedback text, adjudication_reason text, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, \
            completed_at timestamptz)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_task_session_attempts_task_attempt \
            ON workspace_task_session_attempts (workspace_task_id, attempt_number)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_task_session_attempts_task_status \
            ON workspace_task_session_attempts (workspace_task_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_task_session_attempts_root_created \
            ON workspace_task_session_attempts (root_goal_task_id, created_at)",
        "CREATE TABLE IF NOT EXISTS workspace_plans (\
            id text PRIMARY KEY, workspace_id text NOT NULL, goal_id text NOT NULL, \
            status varchar(20) DEFAULT 'draft' NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plans_workspace \
            ON workspace_plans (workspace_id)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_nodes (\
            id text PRIMARY KEY, plan_id text NOT NULL, parent_id text, \
            kind varchar(20) DEFAULT 'task' NOT NULL, title varchar(500) NOT NULL, \
            description text DEFAULT '' NOT NULL, depends_on json DEFAULT '[]'::json NOT NULL, \
            inputs_schema json DEFAULT '{}'::json NOT NULL, \
            outputs_schema json DEFAULT '{}'::json NOT NULL, \
            acceptance_criteria json DEFAULT '[]'::json NOT NULL, \
            feature_checkpoint json, handoff_package json, \
            recommended_capabilities json DEFAULT '[]'::json NOT NULL, \
            preferred_agent_id text, estimated_effort json DEFAULT '{}'::json NOT NULL, \
            priority integer DEFAULT 0 NOT NULL, intent varchar(20) DEFAULT 'todo' NOT NULL, \
            execution varchar(20) DEFAULT 'idle' NOT NULL, progress json DEFAULT '{}'::json NOT NULL, \
            assignee_agent_id text, current_attempt_id text, workspace_task_id text, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz, \
            completed_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_nodes_plan \
            ON workspace_plan_nodes (plan_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_nodes_parent \
            ON workspace_plan_nodes (parent_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_nodes_workspace_task \
            ON workspace_plan_nodes (workspace_task_id)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_blackboard_entries (\
            id text PRIMARY KEY, plan_id text NOT NULL, key varchar(500) NOT NULL, \
            value_json json, published_by text NOT NULL, version integer NOT NULL, \
            schema_ref text, metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_plan_blackboard_plan_key_version \
            ON workspace_plan_blackboard_entries (plan_id, key, version)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_blackboard_plan \
            ON workspace_plan_blackboard_entries (plan_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_blackboard_plan_key \
            ON workspace_plan_blackboard_entries (plan_id, key)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_events (\
            id text PRIMARY KEY, plan_id text NOT NULL, workspace_id text NOT NULL, \
            node_id text, attempt_id text, event_type varchar(80) NOT NULL, \
            source varchar(80) DEFAULT 'system' NOT NULL, actor_id text, \
            payload_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_plan_created \
            ON workspace_plan_events (plan_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_workspace_created \
            ON workspace_plan_events (workspace_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_node \
            ON workspace_plan_events (plan_id, node_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_events_attempt \
            ON workspace_plan_events (attempt_id)",
        "CREATE TABLE IF NOT EXISTS workspace_plan_outbox (\
            id text PRIMARY KEY, plan_id text, workspace_id text NOT NULL, \
            event_type varchar(80) NOT NULL, payload_json json DEFAULT '{}'::json NOT NULL, \
            status varchar(20) DEFAULT 'pending' NOT NULL, attempt_count integer DEFAULT 0 NOT NULL, \
            max_attempts integer DEFAULT 5 NOT NULL, lease_owner varchar(255), \
            lease_expires_at timestamptz, last_error text, next_attempt_at timestamptz, \
            processed_at timestamptz, metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_plan \
            ON workspace_plan_outbox (plan_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_workspace_status \
            ON workspace_plan_outbox (workspace_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_status_next_attempt \
            ON workspace_plan_outbox (status, next_attempt_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_plan_outbox_lease \
            ON workspace_plan_outbox (lease_owner, lease_expires_at)",
        "CREATE TABLE IF NOT EXISTS workspace_pipeline_contracts (\
            id text PRIMARY KEY, workspace_id text NOT NULL, plan_id text, \
            provider varchar(40) DEFAULT 'sandbox_native' NOT NULL, code_root text, \
            commands_json json DEFAULT '[]'::json NOT NULL, \
            env_json json DEFAULT '{}'::json NOT NULL, \
            trigger_policy_json json DEFAULT '{}'::json NOT NULL, \
            timeout_seconds integer DEFAULT 600 NOT NULL, \
            auto_deploy boolean DEFAULT true NOT NULL, preview_port integer, health_url text, \
            status varchar(20) DEFAULT 'active' NOT NULL, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz, \
            CONSTRAINT uq_workspace_pipeline_contract_workspace_plan UNIQUE (workspace_id, plan_id))",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_contracts_workspace \
            ON workspace_pipeline_contracts (workspace_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_contracts_plan \
            ON workspace_pipeline_contracts (plan_id)",
        "CREATE TABLE IF NOT EXISTS workspace_pipeline_runs (\
            id text PRIMARY KEY, contract_id text NOT NULL, workspace_id text NOT NULL, \
            plan_id text, node_id text, attempt_id text, commit_ref text, \
            provider varchar(40) DEFAULT 'sandbox_native' NOT NULL, \
            status varchar(20) DEFAULT 'pending' NOT NULL, reason text, \
            started_at timestamptz, completed_at timestamptz, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_workspace_created \
            ON workspace_pipeline_runs (workspace_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_plan_node \
            ON workspace_pipeline_runs (plan_id, node_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_attempt \
            ON workspace_pipeline_runs (attempt_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_runs_status \
            ON workspace_pipeline_runs (status)",
        "CREATE TABLE IF NOT EXISTS workspace_pipeline_stage_runs (\
            id text PRIMARY KEY, run_id text NOT NULL, workspace_id text NOT NULL, \
            stage varchar(40) NOT NULL, status varchar(20) DEFAULT 'pending' NOT NULL, \
            command text, exit_code integer, stdout_preview text, stderr_preview text, \
            log_ref text, artifact_refs_json json DEFAULT '[]'::json NOT NULL, \
            started_at timestamptz, completed_at timestamptz, duration_ms integer, \
            metadata_json json DEFAULT '{}'::json NOT NULL, \
            created_at timestamptz DEFAULT now() NOT NULL, updated_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_stage_runs_run \
            ON workspace_pipeline_stage_runs (run_id)",
        "CREATE INDEX IF NOT EXISTS ix_workspace_pipeline_stage_runs_workspace_status \
            ON workspace_pipeline_stage_runs (workspace_id, status)",
        "CREATE TABLE IF NOT EXISTS topology_nodes (\
            id text PRIMARY KEY, workspace_id text NOT NULL, node_type varchar(20) NOT NULL, \
            ref_id text, title varchar(255) DEFAULT '' NOT NULL, \
            position_x double precision DEFAULT 0 NOT NULL, \
            position_y double precision DEFAULT 0 NOT NULL, hex_q integer, hex_r integer, \
            status varchar(20) DEFAULT 'active' NOT NULL, tags_json json DEFAULT '[]'::json, \
            data_json json DEFAULT '{}'::json, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS topology_edges (\
            id text PRIMARY KEY, workspace_id text NOT NULL, source_node_id text NOT NULL, \
            target_node_id text NOT NULL, label varchar(255), source_hex_q integer, \
            source_hex_r integer, target_hex_q integer, target_hex_r integer, \
            direction varchar(20), auto_created boolean DEFAULT false NOT NULL, \
            data_json json DEFAULT '{}'::json, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS blackboard_posts (\
            id text PRIMARY KEY, workspace_id text NOT NULL, author_id text NOT NULL, \
            title varchar(255) NOT NULL, content text NOT NULL, \
            status varchar(20) DEFAULT 'open' NOT NULL, is_pinned boolean DEFAULT false NOT NULL, \
            metadata_json json DEFAULT '{}'::json, created_at timestamptz DEFAULT now(), \
            updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS blackboard_replies (\
            id text PRIMARY KEY, post_id text NOT NULL, workspace_id text NOT NULL, \
            author_id text NOT NULL, content text NOT NULL, metadata_json json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS blackboard_files (\
            id text PRIMARY KEY, workspace_id text NOT NULL, parent_path varchar(1024) DEFAULT '/' NOT NULL, \
            name varchar(255) NOT NULL, is_directory boolean DEFAULT false NOT NULL, \
            file_size integer DEFAULT 0 NOT NULL, content_type varchar(128) DEFAULT '' NOT NULL, \
            storage_key varchar(512) DEFAULT '' NOT NULL, uploader_type varchar(10) NOT NULL, \
            uploader_id text NOT NULL, uploader_name varchar(128) NOT NULL, checksum_sha256 varchar(64), \
            mime_type_detected varchar(255), created_at timestamptz DEFAULT now())",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_blackboard_files_ws_path_name \
            ON blackboard_files (workspace_id, parent_path, name)",
        "CREATE TABLE IF NOT EXISTS workspace_blackboard_outbox (\
            id text PRIMARY KEY, workspace_id text NOT NULL, tenant_id text NOT NULL, \
            project_id text NOT NULL, event_type varchar(80) NOT NULL, \
            payload_json json DEFAULT '{}'::json NOT NULL, \
            metadata_json json DEFAULT '{}'::json NOT NULL, correlation_id text, \
            status varchar(20) DEFAULT 'pending' NOT NULL, attempt_count integer DEFAULT 0 NOT NULL, \
            max_attempts integer DEFAULT 10 NOT NULL, last_error text, next_attempt_at timestamptz, \
            dispatched_at timestamptz, created_at timestamptz DEFAULT now() NOT NULL, \
            updated_at timestamptz)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("ddl failed: {ddl}\n{e}"));
    }
    ensure_aux_schema(pool).await.expect("aux schema");
}

pub(super) fn sample_memory(id: &str, project_id: &str) -> Memory {
    Memory {
        id: id.to_string(),
        project_id: project_id.to_string(),
        title: "Portable core".to_string(),
        content: "Rust core compiles to wasm and native.".to_string(),
        author_id: "u_pg_it".to_string(),
        content_type: "text".to_string(),
        tags: vec!["rust".to_string(), "portable".to_string()],
        entities: vec![Entity {
            name: "Rust".to_string(),
            kind: "language".to_string(),
        }],
        version: 1,
        status: "ENABLED".to_string(),
        created_at_ms: 1_700_000_000_000,
        embedding: None,
    }
}

/// Additively extend the minimal `users`/`tenants` tables with the identity
/// columns the P2 adapters read, and create `user_tenants`. `ADD COLUMN IF NOT
/// EXISTS` keeps this idempotent and compatible with the memory/auth tests that
/// created the base tables — it never drops or rewrites existing columns.
pub(super) async fn ensure_identity_tables(pool: &PgPool) {
    for ddl in [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS hashed_password text",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name text",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_superuser boolean DEFAULT false",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password boolean DEFAULT false",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS slug text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS description text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS owner_id text",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan text DEFAULT 'free'",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_projects integer DEFAULT 10",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_users integer DEFAULT 5",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_storage bigint DEFAULT 1073741824",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS updated_at timestamptz",
        "CREATE TABLE IF NOT EXISTS user_tenants (\
            id text PRIMARY KEY, user_id text NOT NULL, tenant_id text NOT NULL, \
            role text DEFAULT 'member', created_at timestamptz DEFAULT now())",
        "ALTER TABLE user_tenants ADD COLUMN IF NOT EXISTS permissions json DEFAULT '{}'::json",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("identity ddl failed: {ddl}\n{e}"));
    }
}

pub(super) async fn ensure_project_read_tables(pool: &PgPool) {
    for ddl in [
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS description text",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS memory_rules json DEFAULT '{}'::json",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_config json DEFAULT '{}'::json",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS graph_store_id text",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS retrieval_store_id text",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS sandbox_type text DEFAULT 'cloud'",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS sandbox_config json DEFAULT '{}'::json",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS agent_conversation_mode text DEFAULT 'single_agent'",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS updated_at timestamptz",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS id text",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS permissions json DEFAULT '{}'::json",
        "ALTER TABLE user_projects ADD COLUMN IF NOT EXISTS created_at timestamptz DEFAULT now()",
        "CREATE TABLE IF NOT EXISTS conversations (\
            id text PRIMARY KEY, project_id text NOT NULL, tenant_id text NOT NULL, \
            user_id text NOT NULL, title varchar(500) NOT NULL, status varchar(20) DEFAULT 'active', \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS workspace_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS meta json DEFAULT '{}'::json",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent_config json DEFAULT '{}'::json",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS message_count integer DEFAULT 0 NOT NULL",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS current_mode varchar(20) DEFAULT 'build' NOT NULL",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS merge_strategy varchar(20) DEFAULT 'result_only' NOT NULL",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS summary text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS parent_conversation_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS branch_point_message_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS fork_source_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS conversation_mode varchar(32)",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS linked_workspace_task_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS participant_agents json DEFAULT '[]'::json",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS coordinator_agent_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS focused_agent_id text",
        "CREATE TABLE IF NOT EXISTS messages (\
            id text PRIMARY KEY, conversation_id text NOT NULL, reply_to_id text, \
            content text, created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS workspaces (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL, \
            name varchar(255) NOT NULL, description text, created_by text NOT NULL, \
            is_archived boolean DEFAULT false, metadata_json json DEFAULT '{}'::json, \
            office_status text DEFAULT 'inactive', hex_layout_config_json json DEFAULT '{}'::json, \
            default_blocking_categories_json json DEFAULT '[]'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS project_delete_audit_entries (\
            id text PRIMARY KEY, project_id text NOT NULL REFERENCES projects(id))",
        "CREATE TABLE IF NOT EXISTS project_delete_audit_children (\
            id text PRIMARY KEY, entry_id text NOT NULL REFERENCES project_delete_audit_entries(id))",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("project read ddl failed: {ddl}\n{e}"));
    }
}

pub(super) async fn ensure_hitl_tables(pool: &PgPool) {
    ensure_project_read_tables(pool).await;
    for ddl in [
        "CREATE TABLE IF NOT EXISTS hitl_requests (\
            id text PRIMARY KEY, request_type varchar(50) NOT NULL, \
            conversation_id text NOT NULL, message_id text, tenant_id text NOT NULL, \
            project_id text NOT NULL, user_id text, question text NOT NULL, options json, \
            context json, request_metadata json, status varchar(20) DEFAULT 'pending' NOT NULL, \
            response text, response_metadata json, created_at timestamptz DEFAULT now() NOT NULL, \
            expires_at timestamptz, answered_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_hitl_requests_conversation_status \
            ON hitl_requests (conversation_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_hitl_requests_tenant_project_status \
            ON hitl_requests (tenant_id, project_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_hitl_requests_expires_at \
            ON hitl_requests (expires_at)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("hitl ddl failed: {ddl}\n{e}"));
    }
}

pub(super) async fn ensure_tenant_delete_tables(pool: &PgPool) {
    ensure_project_read_tables(pool).await;
    for ddl in [
        "CREATE TABLE IF NOT EXISTS tenant_delete_audit_entries (\
            id text PRIMARY KEY, tenant_id text NOT NULL REFERENCES tenants(id))",
        "CREATE TABLE IF NOT EXISTS tenant_delete_audit_children (\
            id text PRIMARY KEY, entry_id text NOT NULL REFERENCES tenant_delete_audit_entries(id))",
        "CREATE TABLE IF NOT EXISTS tenant_delete_loose_notes (\
            id text PRIMARY KEY, tenant_id text NOT NULL, note text)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("tenant delete ddl failed: {ddl}\n{e}"));
    }
}

pub(super) async fn ensure_invitation_tables(pool: &PgPool) {
    for ddl in [
        "CREATE TABLE IF NOT EXISTS invitations (\
            id text PRIMARY KEY, tenant_id text NOT NULL, email text NOT NULL, role text DEFAULT 'member', \
            token text NOT NULL, status text DEFAULT 'pending', invited_by text NOT NULL, \
            accepted_by text, expires_at timestamptz NOT NULL, created_at timestamptz DEFAULT now(), \
            deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_invitations_tenant ON invitations (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_invitations_token ON invitations (token)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("invitation ddl failed: {ddl}\n{e}"));
    }
}

pub(super) async fn ensure_trust_tables(pool: &PgPool) {
    ensure_identity_tables(pool).await;
    for ddl in [
        "CREATE TABLE IF NOT EXISTS workspaces (\
            id text PRIMARY KEY, tenant_id text NOT NULL, project_id text NOT NULL, \
            name varchar(255) NOT NULL, description text, created_by text NOT NULL, \
            is_archived boolean DEFAULT false, metadata_json json DEFAULT '{}'::json, \
            office_status text DEFAULT 'inactive', hex_layout_config_json json DEFAULT '{}'::json, \
            default_blocking_categories_json json DEFAULT '[]'::json, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz)",
        "CREATE TABLE IF NOT EXISTS trust_policies (\
            id text PRIMARY KEY, tenant_id text NOT NULL, workspace_id text NOT NULL, \
            agent_instance_id text NOT NULL, action_type text NOT NULL, granted_by text NOT NULL, \
            grant_type text NOT NULL, created_at timestamptz DEFAULT now(), deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_trust_policies_tenant_ws \
            ON trust_policies (tenant_id, workspace_id)",
        "CREATE TABLE IF NOT EXISTS decision_records (\
            id text PRIMARY KEY, tenant_id text NOT NULL, workspace_id text NOT NULL, \
            agent_instance_id text NOT NULL, decision_type text NOT NULL, context_summary text, \
            proposal json DEFAULT '{}'::json, outcome text DEFAULT 'pending', reviewer_id text, \
            review_type text, review_comment text, resolved_at timestamptz, \
            created_at timestamptz DEFAULT now(), updated_at timestamptz, deleted_at timestamptz)",
        "CREATE INDEX IF NOT EXISTS ix_decision_records_tenant_ws \
            ON decision_records (tenant_id, workspace_id)",
    ] {
        sqlx::query(ddl)
            .execute(pool)
            .await
            .unwrap_or_else(|e| panic!("trust ddl failed: {ddl}\n{e}"));
    }
}
