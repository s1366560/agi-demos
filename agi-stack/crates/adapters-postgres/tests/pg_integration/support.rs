pub(super) use agistack_adapters_postgres::PgPool;
pub(super) use agistack_adapters_postgres::{
    connect, ensure_aux_schema, BlackboardFileRecord, BlackboardOutboxRecord, BlackboardPostRecord,
    BlackboardReplyRecord, InvitationRecord, NewDecisionRecordRecord, NewShareRecord,
    NewTrustPolicyRecord, PgApiKeyStore, PgCheckpointStore, PgHitlRequestRepository,
    PgInvitationRepository, PgMemoryRepository, PgProjectReadRepository,
    PgProjectSandboxRepository, PgProjectStore, PgShareRepository, PgSkillEvolutionRepository,
    PgSkillRepository, PgTenantRepository, PgTenantSkillConfigRepository, PgTrustRepository,
    PgUserStore, PgVectorIndex, PgWorkspaceRepository, ProjectCreateRecord,
    ProjectListForUserQuery, ProjectLookup, ProjectMembersLookup, ProjectSandboxRecord,
    ProjectStatsLookup, ProjectUpdatePatch, SkillEvolutionJobInsertRecord, SkillProjectAccess,
    SkillRecord, SkillUpdateRecord, SkillVersionRecord, TenantAccessStatus, TenantAdminStatus,
    TenantLookup, TenantSkillConfigRecord, TenantUpdatePatch, TopologyEdgeRecord,
    TopologyNodeRecord, TrustDecisionResolution, WorkspaceAccess, WorkspacePipelineRunRecord,
    WorkspacePipelineStageRunRecord, WorkspacePlanBlackboardEntryRecord, WorkspacePlanEventRecord,
    WorkspacePlanNodeRecord, WorkspacePlanOutboxRecord, WorkspacePlanRecord,
    WorkspaceProjectAccess, WorkspaceRecord, WorkspaceTaskRecord,
    WorkspaceTaskSessionAttemptRecord,
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
/// Rust-owned auxiliary schema. Idempotent (`IF NOT EXISTS`), so tests can share a
/// database. Uses a per-test id prefix to isolate rows.
pub(super) async fn ensure_python_shaped_tables(pool: &PgPool) {
    for ddl in [
        "CREATE TABLE IF NOT EXISTS users (id text PRIMARY KEY, email text)",
        "CREATE TABLE IF NOT EXISTS tenants (id text PRIMARY KEY, name text)",
        "CREATE TABLE IF NOT EXISTS user_tenants (\
            id text PRIMARY KEY, user_id text NOT NULL, tenant_id text NOT NULL, \
            role text DEFAULT 'member', permissions json DEFAULT '{}'::json, \
            created_at timestamptz DEFAULT now())",
        "CREATE TABLE IF NOT EXISTS projects (\
            id text PRIMARY KEY, tenant_id text NOT NULL, name text NOT NULL, \
            owner_id text NOT NULL, is_public boolean DEFAULT false)",
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
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS parent_conversation_id text",
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS fork_source_id text",
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
