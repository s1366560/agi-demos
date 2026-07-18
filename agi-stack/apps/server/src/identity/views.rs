use serde::Serialize;
use serde_json::Value;

use agistack_adapters_postgres::{
    CurrentUserRecord, InvitationRecord, ProjectDashboardStatsRecord, ProjectMemberRecord,
    ProjectMembersRecord, ProjectReadRecord, TenantRecord, WorkspaceContextAccessRecord,
    WorkspaceContextSnapshotRecord, WorkspaceContextSwitchRecord,
};

use super::{
    activity_to_value, default_graph_config, default_memory_rules, ms_to_datetime, sandbox_config,
    with_defaults,
};

/// Login response - byte-identical to the Python `Token` schema
/// (`application/schemas/auth.py`): three flat fields, no timestamp.
#[derive(Debug, Serialize)]
pub struct LoginOutcome {
    pub access_token: String,
    pub token_type: String,
    pub must_change_password: bool,
}

/// Current-user response, byte-shaped like Python's `User` schema.
#[derive(Debug, Serialize)]
pub struct CurrentUserView {
    pub user_id: String,
    pub email: String,
    pub name: String,
    pub roles: Vec<String>,
    pub is_active: bool,
    pub created_at: String,
    pub profile: Value,
    pub preferred_language: Option<String>,
}

impl From<CurrentUserRecord> for CurrentUserView {
    fn from(record: CurrentUserRecord) -> Self {
        let profile = if record.profile.is_object() {
            record.profile
        } else {
            Value::Object(Default::default())
        };

        Self {
            user_id: record.id,
            email: record.email,
            name: record.full_name.unwrap_or_default(),
            roles: record.roles,
            is_active: record.is_active,
            created_at: iso8601(record.created_at),
            profile,
            preferred_language: record.preferred_language,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct WorkspaceContextView {
    pub tenant_id: String,
    pub project_id: String,
    pub revision: i64,
    pub updated_at: String,
}

impl From<WorkspaceContextSnapshotRecord> for WorkspaceContextView {
    fn from(record: WorkspaceContextSnapshotRecord) -> Self {
        Self {
            tenant_id: record.tenant_id,
            project_id: record.project_id,
            revision: record.revision,
            updated_at: iso8601(record.updated_at),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct WorkspaceContextResponseView {
    pub context: WorkspaceContextView,
    pub membership_role: String,
}

impl From<WorkspaceContextAccessRecord> for WorkspaceContextResponseView {
    fn from(record: WorkspaceContextAccessRecord) -> Self {
        Self {
            context: record.context.into(),
            membership_role: record.membership_role,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct WorkspaceContextSwitchOutcomeView {
    pub context: WorkspaceContextView,
    pub changed: bool,
}

impl From<WorkspaceContextSwitchRecord> for WorkspaceContextSwitchOutcomeView {
    fn from(record: WorkspaceContextSwitchRecord) -> Self {
        Self {
            context: record.context.into(),
            changed: record.changed,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextSwitchInput {
    pub tenant_id: String,
    pub project_id: String,
    pub expected_revision: i64,
    pub idempotency_key: String,
}

/// `POST /auth/device/code` response, byte-shaped like Python.
#[derive(Debug, Serialize)]
pub struct DeviceCodeView {
    pub device_code: String,
    pub user_code: String,
    pub verification_uri: String,
    pub verification_uri_complete: String,
    pub expires_in: u64,
    pub interval: u64,
}

/// `POST /auth/device/approve` response.
#[derive(Debug, Serialize)]
pub struct DeviceApproveView {
    pub status: String,
}

/// `POST /auth/device/cancel` response. Repeated cancellation is a successful
/// no-op, so callers can retry after a lost response.
#[derive(Debug, Serialize)]
pub struct DeviceCancelView {
    pub success: bool,
}

/// `POST /auth/device/token` successful response.
#[derive(Debug, Serialize)]
pub struct DeviceTokenView {
    pub access_token: String,
    pub token_type: String,
}

/// A tenant, column-for-column with the Python `TenantResponse`. Timestamps are
/// rendered with the same helper P1 uses for consistency across the strangled
/// surface.
#[derive(Debug, Serialize)]
pub struct TenantView {
    pub id: String,
    pub name: String,
    pub slug: String,
    pub description: Option<String>,
    pub owner_id: String,
    pub plan: String,
    pub max_projects: i32,
    pub max_users: i32,
    pub max_storage: i64,
    pub created_at: String,
    pub updated_at: Option<String>,
}

impl From<TenantRecord> for TenantView {
    fn from(r: TenantRecord) -> Self {
        Self {
            id: r.id,
            name: r.name,
            slug: r.slug,
            description: r.description,
            owner_id: r.owner_id,
            plan: r.plan,
            max_projects: r.max_projects,
            max_users: r.max_users,
            max_storage: r.max_storage,
            created_at: iso8601(r.created_at),
            updated_at: r.updated_at.map(iso8601),
        }
    }
}

/// Paginated tenant list - Python `TenantListResponse`
/// (`{tenants, total, page, page_size}`).
#[derive(Debug, Serialize)]
pub struct TenantPage {
    pub tenants: Vec<TenantView>,
    pub total: i64,
    pub page: i64,
    pub page_size: i64,
}

#[derive(Debug, Serialize)]
pub struct TenantMemberMutationView {
    pub message: String,
    pub user_id: String,
    pub role: String,
}

#[derive(Debug, Serialize)]
pub struct InvitationView {
    pub id: String,
    pub tenant_id: String,
    pub email: String,
    pub role: String,
    pub status: String,
    pub invited_by: String,
    pub expires_at: String,
    pub created_at: String,
}

impl From<InvitationRecord> for InvitationView {
    fn from(record: InvitationRecord) -> Self {
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            email: record.email,
            role: record.role,
            status: record.status,
            invited_by: record.invited_by,
            expires_at: iso8601(record.expires_at),
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct InvitationListView {
    pub items: Vec<InvitationView>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Debug, Serialize)]
pub struct InvitationVerifyView {
    pub valid: bool,
    pub email: Option<String>,
    pub tenant_id: Option<String>,
    pub role: Option<String>,
    pub expires_at: Option<String>,
}

impl InvitationVerifyView {
    pub(super) fn invalid() -> Self {
        Self {
            valid: false,
            email: None,
            tenant_id: None,
            role: None,
            expires_at: None,
        }
    }

    pub(super) fn valid(record: InvitationRecord) -> Self {
        Self {
            valid: true,
            email: Some(record.email),
            tenant_id: Some(record.tenant_id),
            role: Some(record.role),
            expires_at: Some(iso8601(record.expires_at)),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct BackendStoreSummary {
    pub id: String,
    pub name: String,
    pub engine_type: String,
    pub source: String,
    pub status: String,
}

impl BackendStoreSummary {
    fn graph(project: &ProjectReadRecord) -> Self {
        match &project.graph_store_id {
            Some(id) => Self::user_store(id),
            None => Self {
                id: "__env_neo4j__".to_string(),
                name: "neo4j (env)".to_string(),
                engine_type: "neo4j".to_string(),
                source: "env".to_string(),
                status: "connected".to_string(),
            },
        }
    }

    fn retrieval(project: &ProjectReadRecord) -> Self {
        match &project.retrieval_store_id {
            Some(id) => Self::user_store(id),
            None => Self {
                id: "__env_memstack_pgvector__".to_string(),
                name: "memstack_pgvector (env)".to_string(),
                engine_type: "memstack_pgvector".to_string(),
                source: "env".to_string(),
                status: "connected".to_string(),
            },
        }
    }

    fn user_store(id: &str) -> Self {
        Self {
            id: id.to_string(),
            name: id.to_string(),
            engine_type: "unknown".to_string(),
            source: "user".to_string(),
            status: "unknown".to_string(),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct SystemStatusView {
    pub status: String,
    pub indexing_active: bool,
    pub indexing_progress: i64,
}

#[derive(Debug, Serialize)]
pub struct ProjectStatsView {
    pub memory_count: i64,
    pub conversation_count: i64,
    pub storage_used: i64,
    pub storage_limit: i64,
    pub node_count: i64,
    pub member_count: i64,
    pub collaborators: i64,
    pub active_nodes: i64,
    pub last_active: Option<String>,
    pub system_status: Option<SystemStatusView>,
    pub recent_activity: Vec<Value>,
}

impl ProjectStatsView {
    pub(super) fn dashboard(record: ProjectDashboardStatsRecord, now_ms: i64) -> Self {
        Self {
            memory_count: record.memory_count,
            conversation_count: record.conversation_count,
            storage_used: record.storage_used,
            storage_limit: 1_073_741_824,
            node_count: 0,
            member_count: record.member_count,
            collaborators: record.member_count,
            active_nodes: 0,
            last_active: Some(iso8601(ms_to_datetime(now_ms))),
            system_status: Some(SystemStatusView {
                status: "operational".to_string(),
                indexing_active: true,
                indexing_progress: 100,
            }),
            recent_activity: record
                .recent_activity
                .into_iter()
                .map(|activity| activity_to_value(activity, now_ms))
                .collect(),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ProjectMemberView {
    pub user_id: String,
    pub email: String,
    pub name: Option<String>,
    pub role: String,
    pub permissions: Value,
    pub created_at: String,
}

impl From<ProjectMemberRecord> for ProjectMemberView {
    fn from(record: ProjectMemberRecord) -> Self {
        Self {
            user_id: record.user_id,
            email: record.email,
            name: record.name,
            role: record.role,
            permissions: record.permissions,
            created_at: iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ProjectMembersView {
    pub members: Vec<ProjectMemberView>,
    pub total: i64,
}

impl From<ProjectMembersRecord> for ProjectMembersView {
    fn from(record: ProjectMembersRecord) -> Self {
        Self {
            members: record
                .members
                .into_iter()
                .map(ProjectMemberView::from)
                .collect(),
            total: record.total,
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ProjectMemberMutationView {
    pub message: String,
    pub user_id: String,
    pub role: String,
}

#[derive(Debug, Serialize)]
pub struct ProjectView {
    pub id: String,
    pub tenant_id: String,
    pub name: String,
    pub description: Option<String>,
    pub owner_id: String,
    pub member_ids: Vec<String>,
    pub memory_rules: Value,
    pub graph_config: Value,
    pub graph_store_id: Option<String>,
    pub retrieval_store_id: Option<String>,
    pub graph_store: Option<BackendStoreSummary>,
    pub retrieval_store: Option<BackendStoreSummary>,
    pub sandbox_config: Value,
    pub is_public: bool,
    pub agent_conversation_mode: String,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub stats: Option<ProjectStatsView>,
}

impl From<ProjectReadRecord> for ProjectView {
    fn from(r: ProjectReadRecord) -> Self {
        let graph_store = BackendStoreSummary::graph(&r);
        let retrieval_store = BackendStoreSummary::retrieval(&r);
        let stats = ProjectStatsView {
            memory_count: r.stats.memory_count,
            conversation_count: 0,
            storage_used: r.stats.storage_used,
            storage_limit: 1_073_741_824,
            node_count: 0,
            member_count: r.stats.member_count,
            collaborators: 0,
            active_nodes: 0,
            last_active: r.stats.last_active.map(iso8601),
            system_status: None,
            recent_activity: Vec::new(),
        };
        Self {
            id: r.id,
            tenant_id: r.tenant_id.clone(),
            name: r.name,
            description: r.description,
            owner_id: r.owner_id,
            member_ids: r.member_ids,
            memory_rules: with_defaults(default_memory_rules(), r.memory_rules),
            graph_config: with_defaults(default_graph_config(), r.graph_config),
            graph_store_id: r.graph_store_id.clone(),
            retrieval_store_id: r.retrieval_store_id.clone(),
            graph_store: Some(graph_store),
            retrieval_store: Some(retrieval_store),
            sandbox_config: sandbox_config(&r.sandbox_type, r.sandbox_config),
            is_public: r.is_public,
            agent_conversation_mode: r.agent_conversation_mode,
            created_at: iso8601(r.created_at),
            updated_at: r.updated_at.map(iso8601),
            stats: Some(stats),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ProjectPage {
    pub projects: Vec<ProjectView>,
    pub total: i64,
    pub page: i64,
    pub page_size: i64,
    pub owner_ids: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct ProjectCreateInput {
    pub tenant_id: String,
    pub name: String,
    pub description: Option<String>,
    pub memory_rules: Option<Value>,
    pub graph_config: Option<Value>,
    pub graph_store_id: Option<String>,
    pub retrieval_store_id: Option<String>,
    pub is_public: bool,
    pub agent_conversation_mode: String,
}

#[derive(Debug, Clone, Copy)]
pub struct ProjectListInput<'a> {
    pub tenant_id: Option<&'a str>,
    pub search: Option<&'a str>,
    pub visibility: &'a str,
    pub owner_id: Option<&'a str>,
    pub page: i64,
    pub page_size: i64,
}

/// Format a UTC timestamp as ISO-8601 with a trailing `Z`, consistent with P1's
/// `prod_api::rfc3339`.
fn iso8601(dt: chrono::DateTime<chrono::Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}
