//! P2 **identity** service — the login + tenant/project-read slice of the strangler
//! migration (plan.md Section 15.2). Sibling to [`crate::auth`] (F2): where
//! `auth` *verifies* an existing `ms_sk_` key on every request, this module
//! *mints* one at `/auth/token` and serves the tenant read endpoints.
//!
//! ## What ships this wave (honest scope)
//! - **`POST /auth/token`** — full byte-parity with Python
//!   `routers/auth.py::login_for_access_token`. The response is the flat
//!   `Token` shape (`{access_token, token_type, must_change_password}`) with **no
//!   timestamp**, so it is exactly reproducible and **safe to flip at the
//!   gateway**.
//! - **`POST /auth/oauth/{provider}/callback`** — Python is a `501` stub; Rust
//!   owns the path and returns the same `501 {"detail": "OAuth login is not
//!   configured"}`. Also flippable.
//! - **`GET /tenants/` + `GET /tenants/{id}`** — membership-scoped, structurally
//!   parity-tested, and flipped through method-scoped gateway rules so write
//!   routes/siblings remain in Python.
//! - **`GET/POST /projects/` + `GET/PUT/DELETE /projects/{id}`** — project
//!   list/detail plus create/update/delete with Python-shaped defaults, stats,
//!   backend summaries, filtering and membership error ordering. Flipped through
//!   method-scoped gateway rules, excluding sandbox siblings.
//!
//! ## Two implementations, one port
//! Same shape as `auth`: [`PgIdentityService`] (production, shared Python tables)
//! and [`DevIdentityService`] (offline stub so `cargo run`/tests need no DB).
//!
//! ## Agent First
//! Nothing here is a judgment: password verification is a deterministic bcrypt
//! check, key minting is CSPRNG bytes, tenant scoping is set-membership + integer
//! pagination arithmetic. All explicitly outside the agent-decision boundary.

use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use async_trait::async_trait;
use axum::http::StatusCode;
use serde::Serialize;
use serde_json::{json, Map, Value};

use agistack_adapters_postgres::{
    normalize_email, InvitationRecord, PgInvitationRepository, PgProjectReadRepository,
    PgTenantRepository, PgUserStore, ProjectActivityRecord, ProjectCreateRecord,
    ProjectDashboardStatsRecord, ProjectLookup, ProjectMemberRecord, ProjectMembersLookup,
    ProjectMembersRecord, ProjectReadRecord, ProjectStatsLookup, ProjectUpdatePatch,
    TenantAdminStatus, TenantLookup, TenantRecord, TenantUpdatePatch,
};
use agistack_adapters_redis::{DeviceGrant, RedisDeviceGrantStore};
use agistack_adapters_secrets::{
    generate_api_key, generate_device_user_code, generate_urlsafe_token, generate_uuid_v4,
    verify_password,
};
use agistack_core::ports::{EmailMessage, EmailSender};

/// One day in milliseconds — the login key TTL (`expires_in_days=1` in Python).
const LOGIN_KEY_TTL_MS: i64 = 24 * 60 * 60 * 1000;
/// Thirty days in milliseconds — Python `create_api_key(..., expires_in_days=30)`.
const DEVICE_KEY_TTL_MS: i64 = 30 * 24 * 60 * 60 * 1000;
/// Device-code grant lifetime: Python `_DEVICE_CODE_TTL = 600`.
const DEVICE_CODE_TTL_SECS: u64 = 600;
/// Device-code polling interval: Python `_DEVICE_CODE_INTERVAL = 5`.
const DEVICE_CODE_INTERVAL_SECS: u64 = 5;
/// Python retries user-code allocation five times before returning 503.
const DEVICE_USER_CODE_ALLOC_ATTEMPTS: usize = 5;
/// Seven days in milliseconds — Python `INVITATION_EXPIRY_DAYS = 7`.
const INVITATION_EXPIRY_MS: i64 = 7 * 24 * 60 * 60 * 1000;

/// Why an identity request was rejected, carrying the HTTP status + a
/// Python-parity `detail` string, plus whether to add `WWW-Authenticate: Bearer`
/// (the login 401 does; the inactive 401 does not — mirroring Python exactly).
#[derive(Debug)]
pub struct IdentityError {
    pub status: StatusCode,
    pub detail: String,
    pub detail_value: Option<Value>,
    pub www_authenticate: bool,
}

impl IdentityError {
    fn unauthorized(detail: impl Into<String>, www_authenticate: bool) -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            detail: detail.into(),
            detail_value: None,
            www_authenticate,
        }
    }
    fn not_found(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            detail: detail.into(),
            detail_value: None,
            www_authenticate: false,
        }
    }
    fn forbidden(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::FORBIDDEN,
            detail: detail.into(),
            detail_value: None,
            www_authenticate: false,
        }
    }
    fn bad_request(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            detail: detail.into(),
            detail_value: None,
            www_authenticate: false,
        }
    }
    fn conflict(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::CONFLICT,
            detail: detail.into(),
            detail_value: None,
            www_authenticate: false,
        }
    }
    fn gone(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::GONE,
            detail: detail.into(),
            detail_value: None,
            www_authenticate: false,
        }
    }
    fn service_unavailable(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            detail: detail.into(),
            detail_value: None,
            www_authenticate: false,
        }
    }
    fn precondition_required(detail: Value) -> Self {
        Self {
            status: StatusCode::PRECONDITION_REQUIRED,
            detail: detail.to_string(),
            detail_value: Some(detail),
            www_authenticate: false,
        }
    }
    fn internal(detail: impl std::fmt::Display) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            detail: detail.to_string(),
            detail_value: None,
            www_authenticate: false,
        }
    }
}

/// Login response — byte-identical to the Python `Token` schema
/// (`application/schemas/auth.py`): three flat fields, no timestamp.
#[derive(Debug, Serialize)]
pub struct LoginOutcome {
    pub access_token: String,
    pub token_type: String,
    pub must_change_password: bool,
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

/// `POST /auth/device/token` successful response.
#[derive(Debug, Serialize)]
pub struct DeviceTokenView {
    pub access_token: String,
    pub token_type: String,
}

/// A tenant, column-for-column with the Python `TenantResponse`. Timestamps are
/// rendered with the same helper P1 uses for consistency across the strangled
/// surface (see the F3 note on exact pydantic format above).
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

/// Paginated tenant list — Python `TenantListResponse`
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
    fn invalid() -> Self {
        Self {
            valid: false,
            email: None,
            tenant_id: None,
            role: None,
            expires_at: None,
        }
    }

    fn valid(record: InvitationRecord) -> Self {
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
    fn dashboard(record: ProjectDashboardStatsRecord, now_ms: i64) -> Self {
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

/// Format a UTC timestamp as ISO-8601 with a trailing `Z`, consistent with P1's
/// `prod_api::rfc3339`. (Exact pydantic format parity — `Z` vs `+00:00`,
/// sub-second precision — is a shared F3 golden-capture item; tenants read is not
/// flipped until then.)
fn iso8601(dt: chrono::DateTime<chrono::Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

/// Server-only ephemeral grant store for CLI device-code login. It intentionally
/// lives outside `core`: Redis TTL grants are a transport/auth concern, not a
/// portable domain port.
#[async_trait]
pub trait DeviceGrantStore: Send + Sync {
    async fn user_code_exists(&self, user_code: &str) -> Result<bool, String>;
    async fn create_pending(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        ttl_seconds: u64,
    ) -> Result<(), String>;
    async fn device_code_for_user_code(&self, user_code: &str) -> Result<Option<String>, String>;
    async fn get(&self, device_code: &str) -> Result<Option<DeviceGrant>, String>;
    async fn save_preserving_ttl(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        fallback_ttl_seconds: u64,
    ) -> Result<(), String>;
    async fn delete_pair(&self, device_code: &str, user_code: &str) -> Result<(), String>;
}

pub type SharedDeviceGrantStore = Arc<dyn DeviceGrantStore>;

#[async_trait]
impl DeviceGrantStore for RedisDeviceGrantStore {
    async fn user_code_exists(&self, user_code: &str) -> Result<bool, String> {
        RedisDeviceGrantStore::user_code_exists(self, user_code)
            .await
            .map_err(|e| e.to_string())
    }

    async fn create_pending(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        ttl_seconds: u64,
    ) -> Result<(), String> {
        RedisDeviceGrantStore::create_pending(self, device_code, grant, ttl_seconds)
            .await
            .map_err(|e| e.to_string())
    }

    async fn device_code_for_user_code(&self, user_code: &str) -> Result<Option<String>, String> {
        RedisDeviceGrantStore::device_code_for_user_code(self, user_code)
            .await
            .map_err(|e| e.to_string())
    }

    async fn get(&self, device_code: &str) -> Result<Option<DeviceGrant>, String> {
        RedisDeviceGrantStore::get(self, device_code)
            .await
            .map_err(|e| e.to_string())
    }

    async fn save_preserving_ttl(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        fallback_ttl_seconds: u64,
    ) -> Result<(), String> {
        RedisDeviceGrantStore::save_preserving_ttl(self, device_code, grant, fallback_ttl_seconds)
            .await
            .map_err(|e| e.to_string())
    }

    async fn delete_pair(&self, device_code: &str, user_code: &str) -> Result<(), String> {
        RedisDeviceGrantStore::delete_pair(self, device_code, user_code)
            .await
            .map_err(|e| e.to_string())
    }
}

#[derive(Default)]
pub struct InMemoryDeviceGrantStore {
    inner: Mutex<InMemoryDeviceGrantState>,
}

#[derive(Default)]
struct InMemoryDeviceGrantState {
    device: HashMap<String, InMemoryDeviceGrantEntry>,
    user_code: HashMap<String, String>,
}

#[derive(Clone)]
struct InMemoryDeviceGrantEntry {
    grant: DeviceGrant,
    expires_at_ms: i64,
}

impl InMemoryDeviceGrantStore {
    pub fn new() -> Self {
        Self::default()
    }

    fn purge_expired(state: &mut InMemoryDeviceGrantState, now_ms: i64) {
        let expired: Vec<(String, String)> = state
            .device
            .iter()
            .filter_map(|(device_code, entry)| {
                (entry.expires_at_ms <= now_ms)
                    .then(|| (device_code.clone(), entry.grant.user_code.clone()))
            })
            .collect();
        for (device_code, user_code) in expired {
            state.device.remove(&device_code);
            state.user_code.remove(&user_code);
        }
    }
}

#[async_trait]
impl DeviceGrantStore for InMemoryDeviceGrantStore {
    async fn user_code_exists(&self, user_code: &str) -> Result<bool, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        Ok(state.user_code.contains_key(user_code))
    }

    async fn create_pending(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        ttl_seconds: u64,
    ) -> Result<(), String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        state
            .user_code
            .insert(grant.user_code.clone(), device_code.to_string());
        state.device.insert(
            device_code.to_string(),
            InMemoryDeviceGrantEntry {
                grant: grant.clone(),
                expires_at_ms: now_ms + (ttl_seconds as i64 * 1000),
            },
        );
        Ok(())
    }

    async fn device_code_for_user_code(&self, user_code: &str) -> Result<Option<String>, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        Ok(state.user_code.get(user_code).cloned())
    }

    async fn get(&self, device_code: &str) -> Result<Option<DeviceGrant>, String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        Ok(state
            .device
            .get(device_code)
            .map(|entry| entry.grant.clone()))
    }

    async fn save_preserving_ttl(
        &self,
        device_code: &str,
        grant: &DeviceGrant,
        fallback_ttl_seconds: u64,
    ) -> Result<(), String> {
        let now_ms = chrono::Utc::now().timestamp_millis();
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        Self::purge_expired(&mut state, now_ms);
        let expires_at_ms = state
            .device
            .get(device_code)
            .map(|entry| entry.expires_at_ms)
            .unwrap_or(now_ms + fallback_ttl_seconds as i64 * 1000);
        state.device.insert(
            device_code.to_string(),
            InMemoryDeviceGrantEntry {
                grant: grant.clone(),
                expires_at_ms,
            },
        );
        state
            .user_code
            .insert(grant.user_code.clone(), device_code.to_string());
        Ok(())
    }

    async fn delete_pair(&self, device_code: &str, user_code: &str) -> Result<(), String> {
        let mut state = self.inner.lock().map_err(|e| e.to_string())?;
        state.device.remove(device_code);
        state.user_code.remove(user_code);
        Ok(())
    }
}

/// Server-side identity port: mint a session key on login and serve
/// membership-scoped tenant/project reads. Two impls (Postgres / dev). Kept out of the
/// portable core — a server concern, like `auth`.
#[async_trait]
pub trait IdentityService: Send + Sync {
    /// Verify credentials and mint a short-lived `ms_sk_` session key. `now_ms` is
    /// injected (no ambient clock) so key expiry is deterministic/testable.
    async fn login(
        &self,
        username: &str,
        password: &str,
        now_ms: i64,
    ) -> Result<LoginOutcome, IdentityError>;

    async fn create_device_code(&self) -> Result<DeviceCodeView, IdentityError>;

    async fn approve_device_code(
        &self,
        user_id: &str,
        user_code: &str,
        now_ms: i64,
    ) -> Result<DeviceApproveView, IdentityError>;

    async fn poll_device_token(&self, device_code: &str) -> Result<DeviceTokenView, IdentityError>;

    /// List the tenants `user_id` belongs to (paginated, optional search).
    async fn list_tenants(
        &self,
        user_id: &str,
        search: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<TenantPage, IdentityError>;

    /// Fetch one tenant by id-or-slug, scoped to `user_id`'s membership.
    async fn get_tenant(
        &self,
        user_id: &str,
        tenant_id_or_slug: &str,
    ) -> Result<TenantView, IdentityError>;

    async fn create_tenant(
        &self,
        user_id: &str,
        name: &str,
        description: Option<&str>,
    ) -> Result<TenantView, IdentityError>;

    async fn update_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
        patch: TenantUpdatePatch,
    ) -> Result<TenantView, IdentityError>;

    async fn delete_tenant(&self, user_id: &str, tenant_id: &str) -> Result<(), IdentityError>;

    async fn add_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<TenantMemberMutationView, IdentityError>;

    async fn update_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<TenantMemberMutationView, IdentityError>;

    async fn remove_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError>;

    async fn list_projects(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        search: Option<&str>,
        visibility: &str,
        owner_id: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<ProjectPage, IdentityError>;

    async fn get_project(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<ProjectView, IdentityError>;

    async fn create_project(
        &self,
        user_id: &str,
        input: ProjectCreateInput,
    ) -> Result<ProjectView, IdentityError>;

    async fn update_project(
        &self,
        user_id: &str,
        project_id: &str,
        patch: ProjectUpdatePatch,
    ) -> Result<ProjectView, IdentityError>;

    async fn delete_project(&self, user_id: &str, project_id: &str) -> Result<(), IdentityError>;

    async fn get_project_stats(
        &self,
        user_id: &str,
        project_id: &str,
        now_ms: i64,
    ) -> Result<ProjectStatsView, IdentityError>;

    async fn list_project_members(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMembersView, IdentityError>;

    async fn add_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<ProjectMemberMutationView, IdentityError>;

    async fn update_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<ProjectMemberMutationView, IdentityError>;

    async fn remove_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError>;

    async fn create_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        email: &str,
        role: &str,
        message: Option<&str>,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError>;

    async fn list_invitations(
        &self,
        user_id: &str,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<InvitationListView, IdentityError>;

    async fn cancel_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        invitation_id: &str,
        now_ms: i64,
    ) -> Result<(), IdentityError>;

    async fn verify_invitation(
        &self,
        token: &str,
        now_ms: i64,
    ) -> Result<InvitationVerifyView, IdentityError>;

    async fn accept_invitation(
        &self,
        token: &str,
        user_id: &str,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError>;
}

/// Convenience alias for the shared identity handle stored in `AppState`.
pub type SharedIdentity = Arc<dyn IdentityService>;

// ---- production impl ------------------------------------------------------

/// Production identity service over the shared Python `users`/`api_keys`/
/// `tenants` tables (`agistack-adapters-postgres` + `agistack-adapters-secrets`).
pub struct PgIdentityService {
    users: PgUserStore,
    tenants: PgTenantRepository,
    projects: PgProjectReadRepository,
    invitations: PgInvitationRepository,
    email: Arc<dyn EmailSender>,
    device_grants: SharedDeviceGrantStore,
    invitation_base_url: String,
}

impl PgIdentityService {
    pub fn new(
        users: PgUserStore,
        tenants: PgTenantRepository,
        projects: PgProjectReadRepository,
        invitations: PgInvitationRepository,
        email: Arc<dyn EmailSender>,
        device_grants: SharedDeviceGrantStore,
        invitation_base_url: impl Into<String>,
    ) -> Self {
        Self {
            users,
            tenants,
            projects,
            invitations,
            email,
            device_grants,
            invitation_base_url: invitation_base_url.into(),
        }
    }

    async fn require_invitation_admin(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<(), IdentityError> {
        match self
            .invitations
            .tenant_admin_status(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            TenantAdminStatus::Authorized => Ok(()),
            TenantAdminStatus::TenantNotFound => Err(IdentityError::not_found("Tenant not found")),
            TenantAdminStatus::NotMember => Err(IdentityError::forbidden("Tenant access required")),
            TenantAdminStatus::NotAdmin => Err(IdentityError::forbidden("Admin access required")),
        }
    }

    async fn valid_invitation_at(
        &self,
        token: &str,
        now_ms: i64,
    ) -> Result<Option<InvitationRecord>, IdentityError> {
        let Some(record) = self
            .invitations
            .find_by_token(token)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Ok(None);
        };
        if record.status != "pending" || record.deleted_at.is_some() {
            return Ok(None);
        }
        if record.expires_at < ms_to_datetime(now_ms) {
            self.invitations
                .update_status(&record.id, "expired", None)
                .await
                .map_err(IdentityError::internal)?;
            return Ok(None);
        }
        Ok(Some(record))
    }

    async fn send_invitation_email(
        &self,
        record: &InvitationRecord,
        message: Option<&str>,
    ) -> Result<(), IdentityError> {
        let link = format!(
            "{}/api/v1/invitations/accept/{}",
            self.invitation_base_url.trim_end_matches('/'),
            record.token
        );
        let extra = message
            .map(str::trim)
            .filter(|m| !m.is_empty())
            .map(|m| format!("\n\nMessage from inviter:\n{m}"))
            .unwrap_or_default();
        let body_text = format!(
            "You have been invited to tenant {} as {}.\n\nAccept the invitation: {}{}",
            record.tenant_id, record.role, link, extra
        );
        let body_html = format!(
            "<p>You have been invited to tenant <b>{}</b> as <b>{}</b>.</p><p><a href=\"{}\">Accept the invitation</a></p>{}",
            escape_html(&record.tenant_id),
            escape_html(&record.role),
            escape_html(&link),
            message
                .map(str::trim)
                .filter(|m| !m.is_empty())
                .map(|m| format!("<p>{}</p>", escape_html(m)))
                .unwrap_or_default()
        );
        self.email
            .send(&EmailMessage {
                from: "MemStack <no-reply@memstack.ai>".to_string(),
                to: vec![record.email.clone()],
                subject: "You have been invited to MemStack".to_string(),
                body_text,
                body_html: Some(body_html),
            })
            .await
            .map_err(IdentityError::internal)
    }

    async fn normalize_graph_store_binding(
        &self,
        tenant_id: &str,
        store_id: Option<&str>,
    ) -> Result<Option<String>, IdentityError> {
        let Some(store_id) = normalize_backend_store_id(store_id) else {
            return Ok(None);
        };
        if !self
            .projects
            .graph_store_exists(tenant_id, &store_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::bad_request(
                "Graph store not found in tenant",
            ));
        }
        Ok(Some(store_id))
    }

    async fn normalize_retrieval_store_binding(
        &self,
        tenant_id: &str,
        store_id: Option<&str>,
    ) -> Result<Option<String>, IdentityError> {
        let Some(store_id) = normalize_backend_store_id(store_id) else {
            return Ok(None);
        };
        if !self
            .projects
            .retrieval_store_exists(tenant_id, &store_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::bad_request(
                "Retrieval store not found in tenant",
            ));
        }
        Ok(Some(store_id))
    }
}

#[async_trait]
impl IdentityService for PgIdentityService {
    async fn login(
        &self,
        username: &str,
        password: &str,
        now_ms: i64,
    ) -> Result<LoginOutcome, IdentityError> {
        // 1. Look up by email (the OAuth2 form `username`). Missing user and bad
        //    password both map to the SAME 401 (Python parity), and Python
        //    short-circuits on a missing user without calling verify — so do we.
        let user = self
            .users
            .find_auth_by_email(username)
            .await
            .map_err(IdentityError::internal)?;

        let user = match user {
            Some(u) if verify_password(password, &u.hashed_password) => u,
            _ => {
                return Err(IdentityError::unauthorized(
                    "Incorrect username or password",
                    true,
                ))
            }
        };

        // 2. Inactive accounts get a distinct 401 WITHOUT WWW-Authenticate.
        if !user.is_active {
            return Err(IdentityError::unauthorized(
                "User account is inactive",
                false,
            ));
        }

        // 3. Permissions on the minted key: read/write, plus admin for superusers.
        //    (Python detects admin via a roles join; `is_superuser` is a faithful
        //    proxy here and the field is not response-visible. Full role-join
        //    detection is a documented follow-up.)
        let mut permissions = vec!["read".to_string(), "write".to_string()];
        if user.is_superuser {
            permissions.push("admin".to_string());
        }

        // 4. Mint + persist the session key (name/TTL identical to Python).
        let plain_key = generate_api_key();
        let key_id = generate_uuid_v4();
        let name = format!("Login Session {username}");
        let expires_at = chrono::DateTime::from_timestamp_millis(now_ms + LOGIN_KEY_TTL_MS);
        self.users
            .insert_api_key(
                &key_id,
                &plain_key,
                &name,
                &user.id,
                expires_at,
                &permissions,
            )
            .await
            .map_err(IdentityError::internal)?;

        // NOTE: Python also runs `_ensure_default_project` (first-login only). It
        // does not affect the response bytes and the users the cutover serves
        // already have projects; skipping it avoids the `projects` table's
        // client-side-default landmine. Documented P2 follow-up.

        Ok(LoginOutcome {
            access_token: plain_key,
            token_type: "bearer".to_string(),
            must_change_password: user.must_change_password,
        })
    }

    async fn create_device_code(&self) -> Result<DeviceCodeView, IdentityError> {
        create_device_code_with_store(&*self.device_grants).await
    }

    async fn approve_device_code(
        &self,
        user_id: &str,
        user_code: &str,
        now_ms: i64,
    ) -> Result<DeviceApproveView, IdentityError> {
        let user_code = normalize_device_user_code(user_code);
        if user_code.is_empty() {
            return Err(IdentityError::bad_request("user_code required"));
        }

        let device_code = self
            .device_grants
            .device_code_for_user_code(&user_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::not_found("user_code expired or unknown"))?;
        let grant = self
            .device_grants
            .get(&device_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::gone("device code expired"))?;
        if grant.status != "pending" {
            return Err(IdentityError::conflict(
                "Device code has already been handled",
            ));
        }

        let user = self
            .users
            .find_auth_by_id(user_id)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::unauthorized("Invalid API key", true))?;
        if !user.is_active {
            return Err(IdentityError::unauthorized(
                "User account is inactive",
                false,
            ));
        }

        let mut permissions = vec!["read".to_string(), "write".to_string()];
        if user.is_superuser {
            permissions.push("admin".to_string());
        }

        let plain_key = generate_api_key();
        let key_id = generate_uuid_v4();
        let name = format!("CLI device login ({user_code})");
        let expires_at = chrono::DateTime::from_timestamp_millis(now_ms + DEVICE_KEY_TTL_MS);
        self.users
            .insert_api_key(
                &key_id,
                &plain_key,
                &name,
                &user.id,
                expires_at,
                &permissions,
            )
            .await
            .map_err(IdentityError::internal)?;

        let approved = DeviceGrant::approved(grant.user_code, user.id, plain_key);
        self.device_grants
            .save_preserving_ttl(&device_code, &approved, DEVICE_CODE_TTL_SECS)
            .await
            .map_err(IdentityError::internal)?;

        Ok(DeviceApproveView {
            status: "approved".to_string(),
        })
    }

    async fn poll_device_token(&self, device_code: &str) -> Result<DeviceTokenView, IdentityError> {
        poll_device_token_from_store(&*self.device_grants, device_code).await
    }

    async fn list_tenants(
        &self,
        user_id: &str,
        search: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<TenantPage, IdentityError> {
        let (page, page_size) = clamp_pagination(page, page_size);
        let total = self
            .tenants
            .count_for_user(user_id, search)
            .await
            .map_err(IdentityError::internal)?;
        let offset = (page - 1) * page_size;
        let records = self
            .tenants
            .list_for_user(user_id, search, offset, page_size)
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantPage {
            tenants: records.into_iter().map(TenantView::from).collect(),
            total,
            page,
            page_size,
        })
    }

    async fn get_tenant(
        &self,
        user_id: &str,
        tenant_id_or_slug: &str,
    ) -> Result<TenantView, IdentityError> {
        match self
            .tenants
            .get_for_user(user_id, tenant_id_or_slug)
            .await
            .map_err(IdentityError::internal)?
        {
            TenantLookup::Found(record) => Ok(TenantView::from(record)),
            TenantLookup::NotFound => Err(IdentityError::not_found("Tenant not found")),
            TenantLookup::Forbidden => Err(IdentityError::forbidden("Access denied to tenant")),
        }
    }

    async fn create_tenant(
        &self,
        user_id: &str,
        name: &str,
        description: Option<&str>,
    ) -> Result<TenantView, IdentityError> {
        let tenant_id = generate_uuid_v4();
        let membership_id = generate_uuid_v4();
        let record = self
            .tenants
            .create_tenant(
                &tenant_id,
                &membership_id,
                user_id,
                name,
                description,
                &tenant_owner_permissions(),
            )
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantView::from(record))
    }

    async fn update_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
        patch: TenantUpdatePatch,
    ) -> Result<TenantView, IdentityError> {
        self.tenants
            .update_owned_tenant(user_id, tenant_id, &patch)
            .await
            .map_err(IdentityError::internal)?
            .map(TenantView::from)
            .ok_or_else(|| IdentityError::forbidden("Only tenant owner can update tenant"))
    }

    async fn delete_tenant(&self, user_id: &str, tenant_id: &str) -> Result<(), IdentityError> {
        if !self
            .tenants
            .delete_owned_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can delete tenant",
            ));
        }
        Ok(())
    }

    async fn add_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        let role = default_tenant_member_role(role);
        if !is_valid_tenant_member_role(&role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if !self
            .tenants
            .tenant_exists(tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if !self
            .tenants
            .user_owns_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can add members",
            ));
        }
        if !self
            .tenants
            .user_exists(target_user_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("User not found"));
        }
        if self
            .tenants
            .tenant_member_role(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_some()
        {
            return Err(IdentityError::bad_request(
                "User is already a member of this tenant",
            ));
        }
        let membership_id = generate_uuid_v4();
        self.tenants
            .add_tenant_member(
                &membership_id,
                tenant_id,
                target_user_id,
                &role,
                &tenant_member_add_permissions(&role),
            )
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    async fn update_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        if !is_valid_tenant_member_role(role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if !self
            .tenants
            .tenant_exists(tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if !self
            .tenants
            .user_owns_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can update member roles",
            ));
        }
        if target_user_id == user_id && role != "owner" {
            return Err(IdentityError::bad_request(
                "Cannot change tenant owner role",
            ));
        }
        if self
            .tenants
            .tenant_member_role(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_none()
        {
            return Err(IdentityError::not_found("Tenant member not found"));
        }
        self.tenants
            .update_tenant_member(
                tenant_id,
                target_user_id,
                role,
                &tenant_member_update_permissions(role),
            )
            .await
            .map_err(IdentityError::internal)?;
        Ok(TenantMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    async fn remove_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if !self
            .tenants
            .tenant_exists(tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if !self
            .tenants
            .user_owns_tenant(user_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only tenant owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove tenant owner"));
        }
        if self
            .tenants
            .tenant_member_role(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_none()
        {
            return Err(IdentityError::not_found(
                "User is not a member of this tenant",
            ));
        }
        self.tenants
            .remove_tenant_member(tenant_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }

    async fn list_projects(
        &self,
        user_id: &str,
        tenant_id: Option<&str>,
        search: Option<&str>,
        visibility: &str,
        owner_id: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<ProjectPage, IdentityError> {
        let (page, page_size) = clamp_pagination(page, page_size);
        let offset = (page - 1) * page_size;
        let records = self
            .projects
            .list_for_user(
                user_id, tenant_id, search, visibility, owner_id, offset, page_size,
            )
            .await
            .map_err(IdentityError::internal)?;
        Ok(ProjectPage {
            projects: records
                .projects
                .into_iter()
                .map(ProjectView::from)
                .collect(),
            total: records.total,
            page,
            page_size,
            owner_ids: records.owner_ids,
        })
    }

    async fn get_project(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<ProjectView, IdentityError> {
        match self
            .projects
            .get_for_user(user_id, project_id, tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            ProjectLookup::Found(record) => Ok(ProjectView::from(record)),
            ProjectLookup::Forbidden => Err(IdentityError::forbidden("Access denied to project")),
            ProjectLookup::NotFound => Err(IdentityError::not_found("Project not found")),
            ProjectLookup::TenantMismatch => Err(IdentityError::not_found(
                "Project not found in requested tenant",
            )),
        }
    }

    async fn create_project(
        &self,
        user_id: &str,
        input: ProjectCreateInput,
    ) -> Result<ProjectView, IdentityError> {
        if !is_valid_agent_conversation_mode(&input.agent_conversation_mode) {
            return Err(unprocessable("Invalid agent_conversation_mode"));
        }
        if !self
            .projects
            .user_is_tenant_project_admin(user_id, &input.tenant_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "User does not have permission to create projects in this tenant",
            ));
        }

        let graph_store_id = self
            .normalize_graph_store_binding(&input.tenant_id, input.graph_store_id.as_deref())
            .await?;
        let retrieval_store_id = self
            .normalize_retrieval_store_binding(
                &input.tenant_id,
                input.retrieval_store_id.as_deref(),
            )
            .await?;
        let record = ProjectCreateRecord {
            id: generate_uuid_v4(),
            membership_id: generate_uuid_v4(),
            tenant_id: input.tenant_id,
            name: input.name,
            description: input.description,
            owner_id: user_id.to_string(),
            memory_rules: project_memory_rules_for_write(input.memory_rules),
            graph_config: project_graph_config_for_write(input.graph_config),
            graph_store_id,
            retrieval_store_id,
            sandbox_type: "cloud".to_string(),
            sandbox_config: json!({}),
            is_public: input.is_public,
            agent_conversation_mode: input.agent_conversation_mode,
            owner_permissions: project_owner_permissions(),
        };
        self.projects
            .create_project(&record)
            .await
            .map(ProjectView::from)
            .map_err(IdentityError::internal)
    }

    async fn update_project(
        &self,
        user_id: &str,
        project_id: &str,
        mut patch: ProjectUpdatePatch,
    ) -> Result<ProjectView, IdentityError> {
        if let Some(mode) = patch.agent_conversation_mode.as_deref() {
            if !is_valid_agent_conversation_mode(mode) {
                return Err(unprocessable("Invalid agent_conversation_mode"));
            }
        }
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update project",
            ));
        }
        let Some(current) = self
            .projects
            .get_by_id(project_id)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Err(IdentityError::not_found("Project not found"));
        };

        if let Some(store_id) = patch.graph_store_id.take() {
            patch.graph_store_id = Some(
                self.normalize_graph_store_binding(&current.tenant_id, store_id.as_deref())
                    .await?,
            );
        }
        if let Some(store_id) = patch.retrieval_store_id.take() {
            patch.retrieval_store_id = Some(
                self.normalize_retrieval_store_binding(&current.tenant_id, store_id.as_deref())
                    .await?,
            );
        }
        if let Some(memory_rules) = patch.memory_rules.take() {
            patch.memory_rules = Some(project_memory_rules_for_write(Some(memory_rules)));
        }
        if let Some(graph_config) = patch.graph_config.take() {
            patch.graph_config = Some(project_graph_config_for_write(Some(graph_config)));
        }

        self.projects
            .update_project(project_id, &patch)
            .await
            .map_err(IdentityError::internal)?
            .map(ProjectView::from)
            .ok_or_else(|| IdentityError::not_found("Project not found"))
    }

    async fn delete_project(&self, user_id: &str, project_id: &str) -> Result<(), IdentityError> {
        if !self
            .projects
            .user_is_project_owner(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner can delete project",
            ));
        }
        if !self
            .projects
            .project_exists(project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Project not found"));
        }
        self.projects
            .delete_project(project_id)
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }

    async fn get_project_stats(
        &self,
        user_id: &str,
        project_id: &str,
        now_ms: i64,
    ) -> Result<ProjectStatsView, IdentityError> {
        match self
            .projects
            .stats_for_user(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            ProjectStatsLookup::Found(record) => Ok(ProjectStatsView::dashboard(record, now_ms)),
            ProjectStatsLookup::Forbidden => {
                Err(IdentityError::forbidden("Access denied to project"))
            }
            ProjectStatsLookup::NotFound => Err(IdentityError::not_found("Project not found")),
        }
    }

    async fn list_project_members(
        &self,
        user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMembersView, IdentityError> {
        match self
            .projects
            .members_for_user(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            ProjectMembersLookup::Found(record) => Ok(ProjectMembersView::from(record)),
            ProjectMembersLookup::InvalidId => Err(IdentityError {
                status: StatusCode::UNPROCESSABLE_ENTITY,
                detail: "Invalid UUID".to_string(),
                detail_value: None,
                www_authenticate: false,
            }),
            ProjectMembersLookup::Forbidden => {
                Err(IdentityError::forbidden("Access denied to project"))
            }
            ProjectMembersLookup::NotFound => Err(IdentityError::not_found("Project not found")),
        }
    }

    async fn add_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        let role = default_project_member_role(role);
        if !is_valid_project_member_role(&role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can add members",
            ));
        }
        if !self
            .projects
            .project_exists(project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("Project not found"));
        }
        if !self
            .projects
            .user_exists(target_user_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::not_found("User not found"));
        }
        if self
            .projects
            .project_member_role(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_some()
        {
            return Err(IdentityError::bad_request(
                "User is already a member of this project",
            ));
        }

        let membership_id = generate_uuid_v4();
        self.projects
            .add_project_member(
                &membership_id,
                project_id,
                target_user_id,
                &role,
                &project_member_add_permissions(&role),
            )
            .await
            .map_err(IdentityError::internal)?;

        Ok(ProjectMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    async fn update_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update members",
            ));
        }

        let Some(existing) = self
            .projects
            .project_member_role(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Err(IdentityError::not_found(
                "User is not a member of this project",
            ));
        };
        if existing.role == "owner" {
            return Err(IdentityError::bad_request(
                "Cannot update project owner role",
            ));
        }

        self.projects
            .update_project_member(
                project_id,
                target_user_id,
                role,
                &project_member_update_permissions(role),
            )
            .await
            .map_err(IdentityError::internal)?;

        Ok(ProjectMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    async fn remove_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if !self
            .projects
            .user_is_project_admin(user_id, project_id)
            .await
            .map_err(IdentityError::internal)?
        {
            return Err(IdentityError::forbidden(
                "Only project owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove project owner"));
        }
        if self
            .projects
            .project_member_role(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?
            .is_none()
        {
            return Err(IdentityError::not_found(
                "User is not a member of this project",
            ));
        }
        self.projects
            .remove_project_member(project_id, target_user_id)
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }

    async fn create_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        email: &str,
        role: &str,
        message: Option<&str>,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        self.require_invitation_admin(user_id, tenant_id).await?;
        if self
            .invitations
            .find_pending_by_email_and_tenant(email, tenant_id)
            .await
            .map_err(IdentityError::internal)?
            .is_some()
        {
            return Err(IdentityError::conflict("Invitation already exists"));
        }

        let now = ms_to_datetime(now_ms);
        let invitation = InvitationRecord {
            id: generate_uuid_v4(),
            tenant_id: tenant_id.to_string(),
            email: normalize_email(email),
            role: if role.trim().is_empty() {
                "member".to_string()
            } else {
                role.to_string()
            },
            token: generate_urlsafe_token(32),
            status: "pending".to_string(),
            invited_by: user_id.to_string(),
            accepted_by: None,
            expires_at: ms_to_datetime(now_ms + INVITATION_EXPIRY_MS),
            created_at: now,
            deleted_at: None,
        };
        let saved = self
            .invitations
            .create(&invitation)
            .await
            .map_err(IdentityError::internal)?;
        self.send_invitation_email(&saved, message).await?;
        Ok(InvitationView::from(saved))
    }

    async fn list_invitations(
        &self,
        user_id: &str,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<InvitationListView, IdentityError> {
        self.require_invitation_admin(user_id, tenant_id).await?;
        let (limit, offset) = clamp_limit_offset(limit, offset);
        let total = self
            .invitations
            .count_pending_by_tenant(tenant_id)
            .await
            .map_err(IdentityError::internal)?;
        let items = self
            .invitations
            .list_pending_by_tenant(tenant_id, limit, offset)
            .await
            .map_err(IdentityError::internal)?
            .into_iter()
            .map(InvitationView::from)
            .collect();
        Ok(InvitationListView {
            items,
            total,
            limit,
            offset,
        })
    }

    async fn cancel_invitation(
        &self,
        user_id: &str,
        tenant_id: &str,
        invitation_id: &str,
        now_ms: i64,
    ) -> Result<(), IdentityError> {
        self.require_invitation_admin(user_id, tenant_id).await?;
        let Some(invitation) = self
            .invitations
            .find_by_id(invitation_id)
            .await
            .map_err(IdentityError::internal)?
        else {
            return Err(IdentityError::not_found("Invitation not found"));
        };
        if invitation.tenant_id != tenant_id {
            return Err(IdentityError::forbidden(
                "Not authorized to manage this invitation",
            ));
        }
        if invitation.status != "pending" {
            return Err(IdentityError::not_found("Invitation not found"));
        }
        self.invitations
            .soft_delete(invitation_id, ms_to_datetime(now_ms))
            .await
            .map_err(IdentityError::internal)?;
        Ok(())
    }

    async fn verify_invitation(
        &self,
        token: &str,
        now_ms: i64,
    ) -> Result<InvitationVerifyView, IdentityError> {
        match self.valid_invitation_at(token, now_ms).await? {
            Some(invitation) => Ok(InvitationVerifyView::valid(invitation)),
            None => Ok(InvitationVerifyView::invalid()),
        }
    }

    async fn accept_invitation(
        &self,
        token: &str,
        user_id: &str,
        now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        let Some(mut invitation) = self.valid_invitation_at(token, now_ms).await? else {
            return Err(IdentityError::bad_request("Invalid or expired invitation"));
        };
        self.invitations
            .update_status(&invitation.id, "accepted", Some(user_id))
            .await
            .map_err(IdentityError::internal)?;
        self.invitations
            .ensure_user_tenant_membership(
                &generate_uuid_v4(),
                user_id,
                &invitation.tenant_id,
                &invitation.role,
            )
            .await
            .map_err(IdentityError::internal)?;
        invitation.status = "accepted".to_string();
        invitation.accepted_by = Some(user_id.to_string());
        Ok(InvitationView::from(invitation))
    }
}

// ---- offline dev impl -----------------------------------------------------

/// Offline identity service: mints a fake `ms_sk_` key for any non-empty
/// credentials and serves a single deterministic dev tenant. Never used when
/// `DATABASE_URL` is set. Keeps `cargo run`/tests keyless and DB-free, exactly
/// like [`crate::auth::DevAuthenticator`].
pub struct DevIdentityService {
    dev_user_id: String,
    device_grants: SharedDeviceGrantStore,
}

impl DevIdentityService {
    #[cfg(test)]
    pub fn new(dev_user_id: impl Into<String>) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            device_grants: Arc::new(InMemoryDeviceGrantStore::new()),
        }
    }

    pub fn with_device_grants(
        dev_user_id: impl Into<String>,
        device_grants: SharedDeviceGrantStore,
    ) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            device_grants,
        }
    }

    /// The single deterministic tenant the dev service exposes.
    fn dev_tenant(&self) -> TenantView {
        TenantView {
            id: "dev-tenant".to_string(),
            name: "Dev Tenant".to_string(),
            slug: "dev".to_string(),
            description: None,
            owner_id: self.dev_user_id.clone(),
            plan: "free".to_string(),
            max_projects: 10,
            max_users: 5,
            max_storage: 1_073_741_824,
            created_at: "1970-01-01T00:00:00Z".to_string(),
            updated_at: None,
        }
    }

    fn dev_project(&self) -> ProjectView {
        ProjectView {
            id: "dev-project".to_string(),
            tenant_id: "dev-tenant".to_string(),
            name: "Default project".to_string(),
            description: None,
            owner_id: self.dev_user_id.clone(),
            member_ids: vec![self.dev_user_id.clone()],
            memory_rules: default_memory_rules(),
            graph_config: default_graph_config(),
            graph_store_id: None,
            retrieval_store_id: None,
            graph_store: Some(BackendStoreSummary {
                id: "__env_neo4j__".to_string(),
                name: "neo4j (env)".to_string(),
                engine_type: "neo4j".to_string(),
                source: "env".to_string(),
                status: "connected".to_string(),
            }),
            retrieval_store: Some(BackendStoreSummary {
                id: "__env_memstack_pgvector__".to_string(),
                name: "memstack_pgvector (env)".to_string(),
                engine_type: "memstack_pgvector".to_string(),
                source: "env".to_string(),
                status: "connected".to_string(),
            }),
            sandbox_config: json!({
                "sandbox_type": "cloud",
                "local_config": null
            }),
            is_public: false,
            agent_conversation_mode: "single_agent".to_string(),
            created_at: "1970-01-01T00:00:00Z".to_string(),
            updated_at: None,
            stats: Some(ProjectStatsView {
                memory_count: 0,
                conversation_count: 0,
                storage_used: 0,
                storage_limit: 1_073_741_824,
                node_count: 0,
                member_count: 1,
                collaborators: 0,
                active_nodes: 0,
                last_active: None,
                system_status: None,
                recent_activity: Vec::new(),
            }),
        }
    }

    fn dev_invitation(&self) -> InvitationView {
        InvitationView {
            id: "dev-invitation".to_string(),
            tenant_id: "dev-tenant".to_string(),
            email: "invitee@example.test".to_string(),
            role: "member".to_string(),
            status: "pending".to_string(),
            invited_by: self.dev_user_id.clone(),
            expires_at: "1970-01-08T00:00:00Z".to_string(),
            created_at: "1970-01-01T00:00:00Z".to_string(),
        }
    }
}

#[async_trait]
impl IdentityService for DevIdentityService {
    async fn login(
        &self,
        username: &str,
        password: &str,
        _now_ms: i64,
    ) -> Result<LoginOutcome, IdentityError> {
        // Offline: accept any non-empty credentials so the flow is exercisable
        // without a database; reject empties to keep the error path testable.
        if username.is_empty() || password.is_empty() {
            return Err(IdentityError::unauthorized(
                "Incorrect username or password",
                true,
            ));
        }
        Ok(LoginOutcome {
            access_token: generate_api_key(),
            token_type: "bearer".to_string(),
            must_change_password: false,
        })
    }

    async fn create_device_code(&self) -> Result<DeviceCodeView, IdentityError> {
        create_device_code_with_store(&*self.device_grants).await
    }

    async fn approve_device_code(
        &self,
        user_id: &str,
        user_code: &str,
        _now_ms: i64,
    ) -> Result<DeviceApproveView, IdentityError> {
        let user_code = normalize_device_user_code(user_code);
        if user_code.is_empty() {
            return Err(IdentityError::bad_request("user_code required"));
        }
        let device_code = self
            .device_grants
            .device_code_for_user_code(&user_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::not_found("user_code expired or unknown"))?;
        let grant = self
            .device_grants
            .get(&device_code)
            .await
            .map_err(IdentityError::internal)?
            .ok_or_else(|| IdentityError::gone("device code expired"))?;
        if grant.status != "pending" {
            return Err(IdentityError::conflict(
                "Device code has already been handled",
            ));
        }

        let approved = DeviceGrant::approved(grant.user_code, user_id, generate_api_key());
        self.device_grants
            .save_preserving_ttl(&device_code, &approved, DEVICE_CODE_TTL_SECS)
            .await
            .map_err(IdentityError::internal)?;
        Ok(DeviceApproveView {
            status: "approved".to_string(),
        })
    }

    async fn poll_device_token(&self, device_code: &str) -> Result<DeviceTokenView, IdentityError> {
        poll_device_token_from_store(&*self.device_grants, device_code).await
    }

    async fn list_tenants(
        &self,
        _user_id: &str,
        search: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<TenantPage, IdentityError> {
        let (page, page_size) = clamp_pagination(page, page_size);
        // The single dev tenant matches when unfiltered or when the term is a
        // substring of its name/slug.
        let matches = match search {
            None => true,
            Some(term) => {
                let t = term.to_lowercase();
                "dev tenant".contains(&t) || "dev".contains(&t)
            }
        };
        let all = if matches {
            vec![self.dev_tenant()]
        } else {
            vec![]
        };
        let total = all.len() as i64;
        let start = ((page - 1) * page_size).min(total);
        let tenants = all
            .into_iter()
            .skip(start as usize)
            .take(page_size as usize)
            .collect();
        Ok(TenantPage {
            tenants,
            total,
            page,
            page_size,
        })
    }

    async fn get_tenant(
        &self,
        _user_id: &str,
        tenant_id_or_slug: &str,
    ) -> Result<TenantView, IdentityError> {
        let dev = self.dev_tenant();
        if tenant_id_or_slug == dev.id || tenant_id_or_slug == dev.slug {
            Ok(dev)
        } else {
            Err(IdentityError::not_found("Tenant not found"))
        }
    }

    async fn create_tenant(
        &self,
        user_id: &str,
        name: &str,
        description: Option<&str>,
    ) -> Result<TenantView, IdentityError> {
        let mut tenant = self.dev_tenant();
        tenant.id = "dev-created-tenant".to_string();
        tenant.name = name.to_string();
        tenant.slug = name.to_lowercase().replace(' ', "-");
        tenant.description = description.map(str::to_string);
        tenant.owner_id = user_id.to_string();
        Ok(tenant)
    }

    async fn update_tenant(
        &self,
        user_id: &str,
        tenant_id: &str,
        patch: TenantUpdatePatch,
    ) -> Result<TenantView, IdentityError> {
        let mut tenant = self.dev_tenant();
        if tenant_id != tenant.id || user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can update tenant",
            ));
        }
        if let Some(name) = patch.name {
            tenant.name = name;
        }
        if let Some(description) = patch.description {
            tenant.description = description;
        }
        if let Some(plan) = patch.plan {
            tenant.plan = plan;
        }
        if let Some(max_projects) = patch.max_projects {
            tenant.max_projects = max_projects;
        }
        if let Some(max_users) = patch.max_users {
            tenant.max_users = max_users;
        }
        if let Some(max_storage) = patch.max_storage {
            tenant.max_storage = max_storage;
        }
        tenant.updated_at = Some("1970-01-01T00:00:00Z".to_string());
        Ok(tenant)
    }

    async fn delete_tenant(&self, user_id: &str, tenant_id: &str) -> Result<(), IdentityError> {
        if tenant_id != "dev-tenant" || user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can delete tenant",
            ));
        }
        Ok(())
    }

    async fn add_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        let role = default_tenant_member_role(role);
        if !is_valid_tenant_member_role(&role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can add members",
            ));
        }
        if target_user_id == self.dev_user_id {
            return Err(IdentityError::bad_request(
                "User is already a member of this tenant",
            ));
        }
        Ok(TenantMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    async fn update_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<TenantMemberMutationView, IdentityError> {
        if !is_valid_tenant_member_role(role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can update member roles",
            ));
        }
        if target_user_id == self.dev_user_id && role != "owner" {
            return Err(IdentityError::bad_request(
                "Cannot change tenant owner role",
            ));
        }
        Ok(TenantMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    async fn remove_tenant_member(
        &self,
        user_id: &str,
        tenant_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if user_id != self.dev_user_id {
            return Err(IdentityError::forbidden(
                "Only tenant owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove tenant owner"));
        }
        Ok(())
    }

    async fn list_projects(
        &self,
        _user_id: &str,
        tenant_id: Option<&str>,
        search: Option<&str>,
        visibility: &str,
        owner_id: Option<&str>,
        page: i64,
        page_size: i64,
    ) -> Result<ProjectPage, IdentityError> {
        let (page, page_size) = clamp_pagination(page, page_size);
        let project = self.dev_project();
        let search_matches = search
            .map(|term| {
                let term = term.to_lowercase();
                project.id.to_lowercase().contains(&term)
                    || project.name.to_lowercase().contains(&term)
                    || project.owner_id.to_lowercase().contains(&term)
            })
            .unwrap_or(true);
        let tenant_matches = tenant_id
            .map(|tenant| tenant == project.tenant_id)
            .unwrap_or(true);
        let owner_matches = owner_id
            .map(|owner| owner == project.owner_id)
            .unwrap_or(true);
        let visibility_matches = match visibility {
            "public" => project.is_public,
            "private" => !project.is_public,
            _ => true,
        };
        let all = if search_matches && tenant_matches && owner_matches && visibility_matches {
            vec![project]
        } else {
            vec![]
        };
        let total = all.len() as i64;
        let start = ((page - 1) * page_size).min(total);
        Ok(ProjectPage {
            projects: all
                .into_iter()
                .skip(start as usize)
                .take(page_size as usize)
                .collect(),
            total,
            page,
            page_size,
            owner_ids: if total == 0 {
                Vec::new()
            } else {
                vec![self.dev_user_id.clone()]
            },
        })
    }

    async fn get_project(
        &self,
        _user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<ProjectView, IdentityError> {
        let project = self.dev_project();
        if project_id != project.id {
            return Err(IdentityError::forbidden("Access denied to project"));
        }
        if tenant_id
            .map(|tenant| tenant != project.tenant_id)
            .unwrap_or(false)
        {
            return Err(IdentityError::not_found(
                "Project not found in requested tenant",
            ));
        }
        Ok(project)
    }

    async fn create_project(
        &self,
        user_id: &str,
        input: ProjectCreateInput,
    ) -> Result<ProjectView, IdentityError> {
        if user_id != self.dev_user_id || input.tenant_id != "dev-tenant" {
            return Err(IdentityError::forbidden(
                "User does not have permission to create projects in this tenant",
            ));
        }
        if !is_valid_agent_conversation_mode(&input.agent_conversation_mode) {
            return Err(unprocessable("Invalid agent_conversation_mode"));
        }
        let mut project = self.dev_project();
        project.id = "dev-created-project".to_string();
        project.name = input.name;
        project.description = input.description;
        project.memory_rules = project_memory_rules_for_write(input.memory_rules);
        project.graph_config = project_graph_config_for_write(input.graph_config);
        project.graph_store_id = normalize_backend_store_id(input.graph_store_id.as_deref());
        project.retrieval_store_id =
            normalize_backend_store_id(input.retrieval_store_id.as_deref());
        project.is_public = input.is_public;
        project.agent_conversation_mode = input.agent_conversation_mode;
        Ok(project)
    }

    async fn update_project(
        &self,
        user_id: &str,
        project_id: &str,
        patch: ProjectUpdatePatch,
    ) -> Result<ProjectView, IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update project",
            ));
        }
        if let Some(mode) = patch.agent_conversation_mode.as_deref() {
            if !is_valid_agent_conversation_mode(mode) {
                return Err(unprocessable("Invalid agent_conversation_mode"));
            }
        }
        let mut project = self.dev_project();
        if let Some(name) = patch.name {
            project.name = name;
        }
        if let Some(description) = patch.description {
            project.description = description;
        }
        if let Some(memory_rules) = patch.memory_rules {
            project.memory_rules = project_memory_rules_for_write(Some(memory_rules));
        }
        if let Some(graph_config) = patch.graph_config {
            project.graph_config = project_graph_config_for_write(Some(graph_config));
        }
        if let Some(graph_store_id) = patch.graph_store_id {
            project.graph_store_id = graph_store_id;
        }
        if let Some(retrieval_store_id) = patch.retrieval_store_id {
            project.retrieval_store_id = retrieval_store_id;
        }
        if let Some(raw_sandbox_config) = patch.sandbox_config {
            project.sandbox_config = sandbox_config("cloud", raw_sandbox_config);
        }
        if let Some(is_public) = patch.is_public {
            project.is_public = is_public;
        }
        if let Some(mode) = patch.agent_conversation_mode {
            project.agent_conversation_mode = mode;
        }
        project.updated_at = Some("1970-01-01T00:00:00Z".to_string());
        Ok(project)
    }

    async fn delete_project(&self, user_id: &str, project_id: &str) -> Result<(), IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner can delete project",
            ));
        }
        Ok(())
    }

    async fn get_project_stats(
        &self,
        _user_id: &str,
        project_id: &str,
        now_ms: i64,
    ) -> Result<ProjectStatsView, IdentityError> {
        if project_id != "dev-project" {
            return Err(IdentityError::forbidden("Access denied to project"));
        }
        Ok(ProjectStatsView::dashboard(
            ProjectDashboardStatsRecord {
                memory_count: 0,
                conversation_count: 0,
                storage_used: 0,
                member_count: 1,
                recent_activity: Vec::new(),
            },
            now_ms,
        ))
    }

    async fn list_project_members(
        &self,
        _user_id: &str,
        project_id: &str,
    ) -> Result<ProjectMembersView, IdentityError> {
        if project_id != "dev-project" {
            return Err(IdentityError {
                status: StatusCode::UNPROCESSABLE_ENTITY,
                detail: "Invalid UUID".to_string(),
                detail_value: None,
                www_authenticate: false,
            });
        }
        Ok(ProjectMembersView {
            members: vec![ProjectMemberView {
                user_id: self.dev_user_id.clone(),
                email: "dev@example.test".to_string(),
                name: Some("Dev User".to_string()),
                role: "owner".to_string(),
                permissions: json!({"admin": true, "read": true, "write": true, "delete": true}),
                created_at: "1970-01-01T00:00:00Z".to_string(),
            }],
            total: 1,
        })
    }

    async fn add_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: Option<&str>,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        let role = default_project_member_role(role);
        if !is_valid_project_member_role(&role) {
            return Err(IdentityError::bad_request("Invalid role"));
        }
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can add members",
            ));
        }
        if target_user_id == self.dev_user_id {
            return Err(IdentityError::bad_request(
                "User is already a member of this project",
            ));
        }
        Ok(ProjectMemberMutationView {
            message: "Member added successfully".to_string(),
            user_id: target_user_id.to_string(),
            role,
        })
    }

    async fn update_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
        role: &str,
    ) -> Result<ProjectMemberMutationView, IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner or admin can update members",
            ));
        }
        if target_user_id == self.dev_user_id {
            return Err(IdentityError::bad_request(
                "Cannot update project owner role",
            ));
        }
        Ok(ProjectMemberMutationView {
            message: "Member role updated successfully".to_string(),
            user_id: target_user_id.to_string(),
            role: role.to_string(),
        })
    }

    async fn remove_project_member(
        &self,
        user_id: &str,
        project_id: &str,
        target_user_id: &str,
    ) -> Result<(), IdentityError> {
        if user_id != self.dev_user_id || project_id != "dev-project" {
            return Err(IdentityError::forbidden(
                "Only project owner can remove members",
            ));
        }
        if target_user_id == user_id {
            return Err(IdentityError::bad_request("Cannot remove project owner"));
        }
        Ok(())
    }

    async fn create_invitation(
        &self,
        _user_id: &str,
        tenant_id: &str,
        email: &str,
        role: &str,
        _message: Option<&str>,
        _now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        let mut invitation = self.dev_invitation();
        invitation.email = normalize_email(email);
        invitation.role = if role.trim().is_empty() {
            "member".to_string()
        } else {
            role.to_string()
        };
        Ok(invitation)
    }

    async fn list_invitations(
        &self,
        _user_id: &str,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<InvitationListView, IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        let (limit, offset) = clamp_limit_offset(limit, offset);
        Ok(InvitationListView {
            items: if offset == 0 {
                vec![self.dev_invitation()]
            } else {
                Vec::new()
            },
            total: 1,
            limit,
            offset,
        })
    }

    async fn cancel_invitation(
        &self,
        _user_id: &str,
        tenant_id: &str,
        invitation_id: &str,
        _now_ms: i64,
    ) -> Result<(), IdentityError> {
        if tenant_id != "dev-tenant" {
            return Err(IdentityError::not_found("Tenant not found"));
        }
        if invitation_id == "dev-invitation" {
            Ok(())
        } else {
            Err(IdentityError::not_found("Invitation not found"))
        }
    }

    async fn verify_invitation(
        &self,
        token: &str,
        _now_ms: i64,
    ) -> Result<InvitationVerifyView, IdentityError> {
        if token == "dev-token" {
            Ok(InvitationVerifyView {
                valid: true,
                email: Some("invitee@example.test".to_string()),
                tenant_id: Some("dev-tenant".to_string()),
                role: Some("member".to_string()),
                expires_at: Some("1970-01-08T00:00:00Z".to_string()),
            })
        } else {
            Ok(InvitationVerifyView::invalid())
        }
    }

    async fn accept_invitation(
        &self,
        token: &str,
        _user_id: &str,
        _now_ms: i64,
    ) -> Result<InvitationView, IdentityError> {
        if token != "dev-token" {
            return Err(IdentityError::bad_request("Invalid or expired invitation"));
        }
        let mut invitation = self.dev_invitation();
        invitation.status = "accepted".to_string();
        Ok(invitation)
    }
}

/// Defensive pagination guard: default missing values and keep them in Python's
/// `page >= 1`, `1 <= page_size <= 100` bounds so an offset can never go negative
/// or absurd. (Full FastAPI `422` validation parity is deferred with the flip.)
fn clamp_pagination(page: i64, page_size: i64) -> (i64, i64) {
    let page = page.max(1);
    let page_size = page_size.clamp(1, 100);
    (page, page_size)
}

fn clamp_limit_offset(limit: i64, offset: i64) -> (i64, i64) {
    (limit.clamp(1, 200), offset.max(0))
}

fn tenant_owner_permissions() -> Value {
    json!({
        "admin": true,
        "create_projects": true,
        "manage_users": true
    })
}

fn project_owner_permissions() -> Value {
    json!({
        "admin": true,
        "read": true,
        "write": true,
        "delete": true
    })
}

fn default_tenant_member_role(role: Option<&str>) -> String {
    match role {
        Some(value) if !value.is_empty() => value.to_string(),
        _ => "member".to_string(),
    }
}

fn is_valid_tenant_member_role(role: &str) -> bool {
    matches!(role, "owner" | "admin" | "member" | "viewer" | "editor")
}

fn tenant_member_add_permissions(role: &str) -> Value {
    json!({
        "read": true,
        "write": matches!(role, "admin" | "member" | "editor")
    })
}

fn tenant_member_update_permissions(role: &str) -> Value {
    json!({
        "read": true,
        "write": matches!(role, "owner" | "admin" | "member" | "editor")
    })
}

fn default_project_member_role(role: Option<&str>) -> String {
    match role {
        Some(value) if !value.is_empty() => value.to_string(),
        _ => "member".to_string(),
    }
}

fn is_valid_project_member_role(role: &str) -> bool {
    matches!(role, "owner" | "admin" | "member" | "viewer" | "editor")
}

fn project_member_add_permissions(role: &str) -> Value {
    json!({
        "read": true,
        "write": matches!(role, "admin" | "member" | "editor")
    })
}

fn project_member_update_permissions(role: &str) -> Value {
    json!({
        "read": true,
        "write": matches!(role, "admin" | "member")
    })
}

fn is_valid_agent_conversation_mode(mode: &str) -> bool {
    matches!(
        mode,
        "single_agent" | "multi_agent_shared" | "multi_agent_isolated"
    )
}

fn normalize_backend_store_id(store_id: Option<&str>) -> Option<String> {
    store_id
        .map(str::trim)
        .filter(|id| !id.is_empty())
        .filter(|id| !id.starts_with("__env_"))
        .map(str::to_string)
}

fn project_memory_rules_for_write(raw: Option<Value>) -> Value {
    with_defaults(default_memory_rules(), raw.unwrap_or_else(|| json!({})))
}

fn project_graph_config_for_write(raw: Option<Value>) -> Value {
    with_defaults(default_graph_config(), raw.unwrap_or_else(|| json!({})))
}

fn unprocessable(detail: impl Into<String>) -> IdentityError {
    IdentityError {
        status: StatusCode::UNPROCESSABLE_ENTITY,
        detail: detail.into(),
        detail_value: None,
        www_authenticate: false,
    }
}

fn normalize_device_user_code(user_code: &str) -> String {
    user_code.trim().to_uppercase()
}

async fn create_device_code_with_store(
    store: &dyn DeviceGrantStore,
) -> Result<DeviceCodeView, IdentityError> {
    for _ in 0..DEVICE_USER_CODE_ALLOC_ATTEMPTS {
        let user_code = generate_device_user_code();
        if store
            .user_code_exists(&user_code)
            .await
            .map_err(IdentityError::internal)?
        {
            continue;
        }

        let device_code = generate_urlsafe_token(32);
        let grant = DeviceGrant::pending(user_code.clone());
        store
            .create_pending(&device_code, &grant, DEVICE_CODE_TTL_SECS)
            .await
            .map_err(IdentityError::internal)?;

        return Ok(DeviceCodeView {
            device_code,
            user_code: user_code.clone(),
            verification_uri: "/device".to_string(),
            verification_uri_complete: format!("/device?user_code={user_code}"),
            expires_in: DEVICE_CODE_TTL_SECS,
            interval: DEVICE_CODE_INTERVAL_SECS,
        });
    }

    Err(IdentityError::service_unavailable(
        "Could not allocate user code",
    ))
}

async fn poll_device_token_from_store(
    store: &dyn DeviceGrantStore,
    device_code: &str,
) -> Result<DeviceTokenView, IdentityError> {
    let device_code = device_code.trim();
    if device_code.is_empty() {
        return Err(IdentityError::bad_request("device_code required"));
    }
    let grant = store
        .get(device_code)
        .await
        .map_err(IdentityError::internal)?
        .ok_or_else(|| IdentityError::gone("expired_token"))?;

    match grant.status.as_str() {
        "pending" => Err(IdentityError::precondition_required(json!({
            "error": "authorization_pending",
            "interval": DEVICE_CODE_INTERVAL_SECS,
        }))),
        "approved" => {
            let access_token = grant
                .access_token
                .clone()
                .ok_or_else(|| IdentityError::internal("approved but no token stored"))?;
            store
                .delete_pair(device_code, &grant.user_code)
                .await
                .map_err(IdentityError::internal)?;
            Ok(DeviceTokenView {
                access_token,
                token_type: "bearer".to_string(),
            })
        }
        _ => Err(IdentityError::gone("device code was not approved")),
    }
}

fn default_memory_rules() -> Value {
    json!({
        "max_episodes": 1000,
        "retention_days": 30,
        "auto_refresh": true,
        "refresh_interval": 24
    })
}

fn default_graph_config() -> Value {
    json!({
        "layout_algorithm": "force-directed",
        "node_size": 20,
        "edge_width": 2,
        "colors": {},
        "animations": true,
        "max_nodes": 1000,
        "max_edges": 10000,
        "similarity_threshold": 0.7,
        "community_detection": true
    })
}

fn with_defaults(defaults: Value, raw: Value) -> Value {
    let Value::Object(mut out) = defaults else {
        return raw;
    };
    if let Value::Object(raw) = raw {
        for (k, v) in raw {
            out.insert(k, v);
        }
    }
    Value::Object(out)
}

fn activity_to_value(activity: ProjectActivityRecord, now_ms: i64) -> Value {
    json!({
        "id": activity.id,
        "user": activity.user,
        "action": "created a memory",
        "target": activity.target,
        "time": relative_time(activity.created_at, now_ms),
    })
}

fn relative_time(created_at: chrono::DateTime<chrono::Utc>, now_ms: i64) -> String {
    let now = ms_to_datetime(now_ms);
    let seconds = now.signed_duration_since(created_at).num_seconds().max(0);
    if seconds >= 86_400 {
        format!("{}d ago", seconds / 86_400)
    } else if seconds >= 3_600 {
        format!("{}h ago", seconds / 3_600)
    } else if seconds >= 60 {
        format!("{}m ago", seconds / 60)
    } else {
        "Just now".to_string()
    }
}

fn ms_to_datetime(now_ms: i64) -> chrono::DateTime<chrono::Utc> {
    chrono::DateTime::from_timestamp_millis(now_ms).unwrap_or(chrono::DateTime::UNIX_EPOCH)
}

fn escape_html(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    for ch in input.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(ch),
        }
    }
    out
}

fn sandbox_config(sandbox_type: &str, raw: Value) -> Value {
    let mut out = Map::new();
    out.insert(
        "sandbox_type".to_string(),
        Value::String(
            if sandbox_type.is_empty() {
                "cloud"
            } else {
                sandbox_type
            }
            .to_string(),
        ),
    );
    out.insert("local_config".to_string(), Value::Null);
    if let Value::Object(raw) = raw {
        for (k, v) in raw {
            out.insert(k, v);
        }
    }
    Value::Object(out)
}

#[cfg(test)]
mod unit {
    use super::*;

    #[test]
    fn html_escape_covers_text_and_attribute_metacharacters() {
        assert_eq!(
            escape_html("<tenant&role\"'>"),
            "&lt;tenant&amp;role&quot;&#39;&gt;"
        );
    }

    #[tokio::test]
    async fn dev_login_accepts_non_empty_and_rejects_empty() {
        let svc = DevIdentityService::new("dev-user");
        let ok = svc.login("admin@memstack.ai", "pw", 0).await.unwrap();
        assert!(ok.access_token.starts_with("ms_sk_"));
        assert_eq!(ok.token_type, "bearer");
        assert!(!ok.must_change_password);
        assert_eq!(
            svc.login("", "pw", 0).await.unwrap_err().status,
            StatusCode::UNAUTHORIZED
        );
        // The login 401 carries WWW-Authenticate (Python parity).
        assert!(svc.login("u", "", 0).await.unwrap_err().www_authenticate);
    }

    #[tokio::test]
    async fn dev_list_tenants_paginates_and_filters() {
        let svc = DevIdentityService::new("dev-user");
        let page = svc.list_tenants("dev-user", None, 1, 20).await.unwrap();
        assert_eq!(page.total, 1);
        assert_eq!(page.page, 1);
        assert_eq!(page.page_size, 20);
        assert_eq!(page.tenants.len(), 1);
        assert_eq!(page.tenants[0].slug, "dev");
        // Non-matching search -> empty, total 0.
        let none = svc
            .list_tenants("dev-user", Some("zzz"), 1, 20)
            .await
            .unwrap();
        assert_eq!(none.total, 0);
        assert!(none.tenants.is_empty());
        // Page 2 of a 1-item set is empty but echoes pagination.
        let p2 = svc.list_tenants("dev-user", None, 2, 20).await.unwrap();
        assert_eq!(p2.page, 2);
        assert!(p2.tenants.is_empty());
    }

    #[tokio::test]
    async fn dev_get_tenant_by_id_or_slug_else_404() {
        let svc = DevIdentityService::new("dev-user");
        assert_eq!(
            svc.get_tenant("u", "dev-tenant").await.unwrap().id,
            "dev-tenant"
        );
        assert_eq!(svc.get_tenant("u", "dev").await.unwrap().slug, "dev");
        assert_eq!(
            svc.get_tenant("u", "nope").await.unwrap_err().status,
            StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn dev_list_projects_filters_and_paginates() {
        let svc = DevIdentityService::new("dev-user");
        let page = svc
            .list_projects(
                "dev-user",
                Some("dev-tenant"),
                Some("Default"),
                "all",
                None,
                1,
                20,
            )
            .await
            .unwrap();
        assert_eq!(page.total, 1);
        assert_eq!(page.projects[0].id, "dev-project");
        assert_eq!(page.owner_ids, vec!["dev-user"]);

        let empty = svc
            .list_projects("dev-user", Some("other"), None, "all", None, 1, 20)
            .await
            .unwrap();
        assert_eq!(empty.total, 0);
        assert!(empty.projects.is_empty());
        assert!(empty.owner_ids.is_empty());

        let private = svc
            .list_projects("dev-user", None, None, "private", None, 2, 20)
            .await
            .unwrap();
        assert_eq!(private.total, 1);
        assert_eq!(private.page, 2);
        assert!(private.projects.is_empty());
    }

    #[tokio::test]
    async fn dev_get_project_matches_python_error_order() {
        let svc = DevIdentityService::new("dev-user");
        assert_eq!(
            svc.get_project("dev-user", "dev-project", None)
                .await
                .unwrap()
                .tenant_id,
            "dev-tenant"
        );
        assert_eq!(
            svc.get_project("dev-user", "missing", None)
                .await
                .unwrap_err()
                .status,
            StatusCode::FORBIDDEN
        );
        assert_eq!(
            svc.get_project("dev-user", "dev-project", Some("other"))
                .await
                .unwrap_err()
                .status,
            StatusCode::NOT_FOUND
        );
    }

    #[tokio::test]
    async fn dev_create_and_update_project_match_python_permissions() {
        let svc = DevIdentityService::new("dev-user");
        let created = svc
            .create_project(
                "dev-user",
                ProjectCreateInput {
                    tenant_id: "dev-tenant".to_string(),
                    name: "New Project".to_string(),
                    description: Some("created".to_string()),
                    memory_rules: Some(json!({"max_episodes": 2000})),
                    graph_config: Some(json!({"max_nodes": 5000})),
                    graph_store_id: Some("__env_neo4j__".to_string()),
                    retrieval_store_id: Some("__env_memstack_pgvector__".to_string()),
                    is_public: true,
                    agent_conversation_mode: "multi_agent_shared".to_string(),
                },
            )
            .await
            .unwrap();
        assert_eq!(created.id, "dev-created-project");
        assert_eq!(created.name, "New Project");
        assert_eq!(created.memory_rules["retention_days"], 30);
        assert_eq!(created.memory_rules["max_episodes"], 2000);
        assert!(created.graph_store_id.is_none());
        assert_eq!(created.agent_conversation_mode, "multi_agent_shared");

        let denied = svc
            .create_project(
                "other-user",
                ProjectCreateInput {
                    tenant_id: "dev-tenant".to_string(),
                    name: "Denied".to_string(),
                    description: None,
                    memory_rules: None,
                    graph_config: None,
                    graph_store_id: None,
                    retrieval_store_id: None,
                    is_public: false,
                    agent_conversation_mode: "single_agent".to_string(),
                },
            )
            .await
            .unwrap_err();
        assert_eq!(denied.status, StatusCode::FORBIDDEN);

        let updated = svc
            .update_project(
                "dev-user",
                "dev-project",
                ProjectUpdatePatch {
                    name: Some("Updated Project".to_string()),
                    description: Some(None),
                    memory_rules: Some(json!({"refresh_interval": 12})),
                    graph_config: None,
                    graph_store_id: Some(None),
                    retrieval_store_id: Some(None),
                    sandbox_config: Some(json!({"sandbox_type": "local"})),
                    is_public: Some(true),
                    agent_conversation_mode: Some("multi_agent_isolated".to_string()),
                },
            )
            .await
            .unwrap();
        assert_eq!(updated.name, "Updated Project");
        assert!(updated.description.is_none());
        assert_eq!(updated.memory_rules["max_episodes"], 1000);
        assert_eq!(updated.memory_rules["refresh_interval"], 12);
        assert_eq!(updated.sandbox_config["sandbox_type"], "local");
        assert_eq!(updated.agent_conversation_mode, "multi_agent_isolated");
    }

    #[test]
    fn pagination_is_clamped() {
        assert_eq!(clamp_pagination(0, 0), (1, 1));
        assert_eq!(clamp_pagination(-5, 500), (1, 100));
        assert_eq!(clamp_pagination(3, 50), (3, 50));
    }

    #[test]
    fn tenant_view_serializes_python_shape() {
        let view = TenantView {
            id: "t1".into(),
            name: "Acme".into(),
            slug: "acme".into(),
            description: None,
            owner_id: "u1".into(),
            plan: "free".into(),
            max_projects: 10,
            max_users: 5,
            max_storage: 1_073_741_824,
            created_at: "2023-11-14T22:13:20Z".into(),
            updated_at: None,
        };
        let v = serde_json::to_value(&view).unwrap();
        assert_eq!(v["id"], "t1");
        assert_eq!(v["slug"], "acme");
        assert_eq!(v["description"], serde_json::Value::Null);
        assert_eq!(v["max_storage"], 1_073_741_824i64);
        assert_eq!(v["updated_at"], serde_json::Value::Null);
        assert_eq!(v["created_at"], "2023-11-14T22:13:20Z");
    }

    #[test]
    fn login_outcome_is_flat_token_shape() {
        let out = LoginOutcome {
            access_token: "ms_sk_abc".into(),
            token_type: "bearer".into(),
            must_change_password: true,
        };
        let v = serde_json::to_value(&out).unwrap();
        // Exactly the three Python `Token` fields, no timestamp.
        assert_eq!(v.as_object().unwrap().len(), 3);
        assert_eq!(v["access_token"], "ms_sk_abc");
        assert_eq!(v["token_type"], "bearer");
        assert_eq!(v["must_change_password"], true);
    }

    #[test]
    fn project_defaults_expand_python_shapes() {
        let mut raw = Map::new();
        raw.insert("max_episodes".to_string(), json!(2000));
        let merged = with_defaults(default_memory_rules(), Value::Object(raw));
        assert_eq!(merged["max_episodes"], 2000);
        assert_eq!(merged["retention_days"], 30);

        let sandbox = sandbox_config(
            "local",
            json!({"local_config": {"workspace_path": "/tmp/w"}}),
        );
        assert_eq!(sandbox["sandbox_type"], "local");
        assert_eq!(sandbox["local_config"]["workspace_path"], "/tmp/w");
    }

    // ---- F3 parity gate: assert the wire shapes against contract-derived
    // goldens (plan.md §14.2 F3). The goldens live in `apps/server/tests/golden/`
    // and encode the Python schema contract; `agistack_parity::compare` checks
    // key-set + type + scalar-format parity so a strangler flip is safe.

    fn sample_tenant_record() -> TenantRecord {
        TenantRecord {
            id: "44444444-4444-4444-8444-444444444444".into(),
            name: "Acme".into(),
            slug: "acme".into(),
            description: None,
            owner_id: "33333333-3333-4333-8333-333333333333".into(),
            plan: "free".into(),
            max_projects: 10,
            max_users: 25,
            max_storage: 10_737_418_240,
            // 2023-11-14T22:13:20Z — deterministic so `created_at` is byte-stable.
            created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
            updated_at: None,
        }
    }

    fn sample_project_record() -> ProjectReadRecord {
        ProjectReadRecord {
            id: "55555555-5555-4555-8555-555555555555".into(),
            tenant_id: "44444444-4444-4444-8444-444444444444".into(),
            name: "Default project".into(),
            description: None,
            owner_id: "33333333-3333-4333-8333-333333333333".into(),
            member_ids: vec!["33333333-3333-4333-8333-333333333333".into()],
            memory_rules: json!({}),
            graph_config: json!({}),
            graph_store_id: None,
            retrieval_store_id: None,
            sandbox_type: "cloud".into(),
            sandbox_config: json!({}),
            is_public: false,
            agent_conversation_mode: "single_agent".into(),
            created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
            updated_at: None,
            stats: agistack_adapters_postgres::ProjectStatsRecord {
                memory_count: 0,
                storage_used: 0,
                member_count: 1,
                last_active: None,
            },
        }
    }

    fn sample_invitation_record() -> InvitationRecord {
        InvitationRecord {
            id: "66666666-6666-4666-8666-666666666666".into(),
            tenant_id: "44444444-4444-4444-8444-444444444444".into(),
            email: "invitee@example.test".into(),
            role: "member".into(),
            token: "token-hidden-from-response".into(),
            status: "pending".into(),
            invited_by: "33333333-3333-4333-8333-333333333333".into(),
            accepted_by: None,
            expires_at: chrono::DateTime::from_timestamp(1_700_604_800, 0).unwrap(),
            created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
            deleted_at: None,
        }
    }

    #[test]
    fn tenant_view_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/tenant_view.json")).unwrap();
        let actual = serde_json::to_value(TenantView::from(sample_tenant_record())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn tenant_page_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/tenant_page.json")).unwrap();
        let page = TenantPage {
            tenants: vec![TenantView::from(sample_tenant_record())],
            total: 1,
            page: 1,
            page_size: 20,
        };
        let actual = serde_json::to_value(&page).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn tenant_member_added_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/tenant_member_added.json")).unwrap();
        let view = TenantMemberMutationView {
            message: "Member added successfully".into(),
            user_id: "44444444-4444-4444-8444-444444444444".into(),
            role: "member".into(),
        };
        let actual = serde_json::to_value(&view).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn tenant_member_updated_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/tenant_member_updated.json"))
                .unwrap();
        let view = TenantMemberMutationView {
            message: "Member role updated successfully".into(),
            user_id: "44444444-4444-4444-8444-444444444444".into(),
            role: "viewer".into(),
        };
        let actual = serde_json::to_value(&view).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn tenant_member_role_and_permission_rules_match_python() {
        assert_eq!(default_tenant_member_role(None), "member");
        assert_eq!(default_tenant_member_role(Some("")), "member");
        assert_eq!(default_tenant_member_role(Some(" ")), " ");
        assert!(is_valid_tenant_member_role("editor"));
        assert!(!is_valid_tenant_member_role(" "));
        assert_eq!(tenant_member_add_permissions("viewer")["write"], false);
        assert_eq!(tenant_member_add_permissions("editor")["write"], true);
        assert_eq!(tenant_member_update_permissions("viewer")["write"], false);
        assert_eq!(tenant_member_update_permissions("owner")["write"], true);
    }

    #[test]
    fn project_view_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_view.json")).unwrap();
        let actual = serde_json::to_value(ProjectView::from(sample_project_record())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn project_page_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_page.json")).unwrap();
        let page = ProjectPage {
            projects: vec![ProjectView::from(sample_project_record())],
            total: 1,
            page: 1,
            page_size: 20,
            owner_ids: vec!["33333333-3333-4333-8333-333333333333".into()],
        };
        let actual = serde_json::to_value(&page).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn project_stats_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_stats.json")).unwrap();
        let stats = ProjectStatsView::dashboard(
            ProjectDashboardStatsRecord {
                memory_count: 2,
                conversation_count: 3,
                storage_used: 42,
                member_count: 4,
                recent_activity: vec![ProjectActivityRecord {
                    id: "mem-1".into(),
                    user: "Ada Lovelace".into(),
                    target: "Portable core".into(),
                    created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
                }],
            },
            1_700_000_600_000,
        );
        let actual = serde_json::to_value(&stats).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn project_members_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_members.json")).unwrap();
        let members = ProjectMembersView::from(ProjectMembersRecord {
            members: vec![ProjectMemberRecord {
                user_id: "33333333-3333-4333-8333-333333333333".into(),
                email: "ada@example.test".into(),
                name: Some("Ada Lovelace".into()),
                role: "owner".into(),
                permissions: json!({
                    "admin": true,
                    "read": true,
                    "write": true,
                    "delete": true
                }),
                created_at: chrono::DateTime::from_timestamp(1_700_000_000, 0).unwrap(),
            }],
            total: 1,
        });
        let actual = serde_json::to_value(&members).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn project_member_added_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_member_added.json"))
                .unwrap();
        let view = ProjectMemberMutationView {
            message: "Member added successfully".into(),
            user_id: "44444444-4444-4444-8444-444444444444".into(),
            role: "member".into(),
        };
        let actual = serde_json::to_value(&view).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn project_member_updated_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/project_member_updated.json"))
                .unwrap();
        let view = ProjectMemberMutationView {
            message: "Member role updated successfully".into(),
            user_id: "44444444-4444-4444-8444-444444444444".into(),
            role: "viewer".into(),
        };
        let actual = serde_json::to_value(&view).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn project_member_role_and_permission_rules_match_python() {
        assert_eq!(default_project_member_role(None), "member");
        assert_eq!(default_project_member_role(Some("")), "member");
        assert_eq!(default_project_member_role(Some(" ")), " ");
        assert!(is_valid_project_member_role("editor"));
        assert!(!is_valid_project_member_role(" "));
        assert_eq!(project_member_add_permissions("editor")["write"], true);
        assert_eq!(project_member_update_permissions("editor")["write"], false);
    }

    #[test]
    fn invitation_response_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/invitation_response.json")).unwrap();
        let actual =
            serde_json::to_value(InvitationView::from(sample_invitation_record())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn invitation_list_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/invitation_list.json")).unwrap();
        let list = InvitationListView {
            items: vec![InvitationView::from(sample_invitation_record())],
            total: 1,
            limit: 50,
            offset: 0,
        };
        let actual = serde_json::to_value(&list).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn invitation_verify_matches_golden_and_invalid_shape() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/invitation_verify.json")).unwrap();
        let actual =
            serde_json::to_value(InvitationVerifyView::valid(sample_invitation_record())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);

        let invalid = serde_json::to_value(InvitationVerifyView::invalid()).unwrap();
        assert_eq!(invalid["valid"], false);
        assert_eq!(invalid["email"], serde_json::Value::Null);
        assert_eq!(invalid["expires_at"], serde_json::Value::Null);
    }

    #[test]
    fn device_code_response_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/device_code_response.json"))
                .unwrap();
        let response = DeviceCodeView {
            device_code: agistack_adapters_secrets::generate_urlsafe_token(32),
            user_code: "ABCDEFGH".to_string(),
            verification_uri: "/device".to_string(),
            verification_uri_complete: "/device?user_code=ABCDEFGH".to_string(),
            expires_in: DEVICE_CODE_TTL_SECS,
            interval: DEVICE_CODE_INTERVAL_SECS,
        };
        let actual = serde_json::to_value(&response).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn device_approve_response_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/device_approve_response.json"))
                .unwrap();
        let actual = serde_json::to_value(DeviceApproveView {
            status: "approved".into(),
        })
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn device_token_response_matches_golden() {
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/device_token_response.json"))
                .unwrap();
        let actual = serde_json::to_value(DeviceTokenView {
            access_token: agistack_adapters_secrets::generate_api_key(),
            token_type: "bearer".into(),
        })
        .unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[tokio::test]
    async fn dev_device_code_flow_matches_python_states() {
        let svc = DevIdentityService::new("dev-user");
        let code = svc.create_device_code().await.unwrap();
        assert_eq!(code.verification_uri, "/device");
        assert_eq!(
            code.verification_uri_complete,
            format!("/device?user_code={}", code.user_code)
        );
        assert_eq!(code.expires_in, DEVICE_CODE_TTL_SECS);
        assert_eq!(code.interval, DEVICE_CODE_INTERVAL_SECS);
        assert!(agistack_parity::is_urlsafe_token_32(&code.device_code));
        assert!(agistack_parity::is_device_user_code(&code.user_code));

        let pending = svc.poll_device_token(&code.device_code).await.unwrap_err();
        assert_eq!(pending.status, StatusCode::PRECONDITION_REQUIRED);
        assert_eq!(
            pending.detail_value.unwrap(),
            json!({"error": "authorization_pending", "interval": DEVICE_CODE_INTERVAL_SECS})
        );

        let approved = svc
            .approve_device_code(
                "dev-user",
                &format!(" {} ", code.user_code.to_lowercase()),
                0,
            )
            .await
            .unwrap();
        assert_eq!(approved.status, "approved");
        let token = svc.poll_device_token(&code.device_code).await.unwrap();
        assert!(token.access_token.starts_with("ms_sk_"));
        assert_eq!(token.token_type, "bearer");

        let consumed = svc.poll_device_token(&code.device_code).await.unwrap_err();
        assert_eq!(consumed.status, StatusCode::GONE);
        assert_eq!(consumed.detail, "expired_token");
    }

    #[test]
    fn login_token_matches_golden_with_real_minted_key() {
        // A freshly minted `ms_sk_` key must satisfy the golden's `<ms_sk>`
        // matcher — proving the format the strangled login emits is contract-valid.
        let golden: serde_json::Value =
            serde_json::from_str(include_str!("../tests/golden/login_token.json")).unwrap();
        let out = LoginOutcome {
            access_token: agistack_adapters_secrets::generate_api_key(),
            token_type: "bearer".into(),
            must_change_password: false,
        };
        let actual = serde_json::to_value(&out).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }
}
