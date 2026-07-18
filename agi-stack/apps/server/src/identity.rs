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

use std::sync::Arc;

use async_trait::async_trait;
use axum::http::StatusCode;
use serde_json::{json, Map, Value};

use agistack_adapters_postgres::{
    normalize_email, InvitationRecord, PgInvitationRepository, PgProjectReadRepository,
    PgTenantRepository, PgUserStore, PgWorkspaceContextRepository, ProjectActivityRecord,
    ProjectCreateRecord, ProjectListForUserQuery, ProjectLookup, ProjectMembersLookup,
    ProjectStatsLookup, ProjectUpdatePatch, TenantAdminStatus, TenantLookup, TenantUpdatePatch,
    WorkspaceContextRepositoryError,
};
use agistack_adapters_redis::DeviceGrant;
use agistack_adapters_secrets::{
    try_generate_api_key, try_generate_urlsafe_token, try_generate_uuid_v4, verify_password,
};
use agistack_core::ports::{EmailMessage, EmailSender};

mod dev_service;
mod device_grants;
mod pg_auth_service;
mod pg_invitation_service;
mod pg_project_service;
mod pg_service;
mod pg_tenant_service;
mod views;

pub use dev_service::DevIdentityService;
use device_grants::{
    create_device_code_with_store, normalize_device_user_code, poll_device_token_from_store,
};
pub use device_grants::{DeviceGrantStore, InMemoryDeviceGrantStore, SharedDeviceGrantStore};
pub use pg_service::{PgIdentityRepositories, PgIdentityService};
pub use views::{
    BackendStoreSummary, CurrentUserView, DeviceApproveView, DeviceCancelView, DeviceCodeView,
    DeviceTokenView, InvitationListView, InvitationVerifyView, InvitationView, LoginOutcome,
    ProjectCreateInput, ProjectListInput, ProjectMemberMutationView, ProjectMemberView,
    ProjectMembersView, ProjectPage, ProjectStatsView, ProjectView, TenantMemberMutationView,
    TenantPage, TenantView, WorkspaceContextResponseView, WorkspaceContextSwitchInput,
    WorkspaceContextSwitchOutcomeView, WorkspaceContextView,
};

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

    /// Fetch the authenticated user's Python `User` schema projection.
    async fn current_user(&self, user_id: &str) -> Result<CurrentUserView, IdentityError>;

    async fn workspace_context(
        &self,
        user_id: &str,
        now_ms: i64,
    ) -> Result<WorkspaceContextResponseView, IdentityError>;

    async fn switch_workspace_context(
        &self,
        user_id: &str,
        actor_api_key_id: Option<&str>,
        input: WorkspaceContextSwitchInput,
        now_ms: i64,
    ) -> Result<WorkspaceContextSwitchOutcomeView, IdentityError>;

    async fn create_device_code(&self) -> Result<DeviceCodeView, IdentityError>;

    async fn approve_device_code(
        &self,
        user_id: &str,
        user_code: &str,
        now_ms: i64,
    ) -> Result<DeviceApproveView, IdentityError>;

    async fn poll_device_token(&self, device_code: &str) -> Result<DeviceTokenView, IdentityError>;

    /// Cancel a device grant using only its opaque device code. Implementations
    /// must revoke any token stored in the grant and treat missing grants as an
    /// idempotent success.
    async fn cancel_device_code(
        &self,
        device_code: &str,
    ) -> Result<DeviceCancelView, IdentityError>;

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
        input: ProjectListInput<'_>,
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

fn workspace_context_error(error: WorkspaceContextRepositoryError) -> IdentityError {
    let (status, detail) = match error {
        WorkspaceContextRepositoryError::InvalidInput => (
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({"code": "workspace_context_invalid_input"}),
        ),
        WorkspaceContextRepositoryError::NoAccessibleProject => (
            StatusCode::NOT_FOUND,
            json!({"code": "workspace_context_unavailable"}),
        ),
        WorkspaceContextRepositoryError::TenantMembershipRequired => (
            StatusCode::FORBIDDEN,
            json!({"code": "workspace_context_membership_required"}),
        ),
        WorkspaceContextRepositoryError::ProjectUnavailable => (
            StatusCode::FORBIDDEN,
            json!({"code": "workspace_context_project_unavailable"}),
        ),
        WorkspaceContextRepositoryError::RevisionConflict { expected, actual } => (
            StatusCode::CONFLICT,
            json!({
                "code": "workspace_context_revision_conflict",
                "expected_revision": expected,
                "actual_revision": actual,
            }),
        ),
        WorkspaceContextRepositoryError::IdempotencyConflict => (
            StatusCode::CONFLICT,
            json!({"code": "workspace_context_idempotency_conflict"}),
        ),
        WorkspaceContextRepositoryError::RevisionExhausted => (
            StatusCode::CONFLICT,
            json!({"code": "workspace_context_revision_exhausted"}),
        ),
        error @ WorkspaceContextRepositoryError::Storage(_) => {
            return IdentityError::internal(error);
        }
    };
    IdentityError {
        status,
        detail: detail.to_string(),
        detail_value: Some(detail),
        www_authenticate: false,
    }
}

fn validate_workspace_context_input(
    input: &WorkspaceContextSwitchInput,
) -> Result<(), IdentityError> {
    let key = input.idempotency_key.trim();
    if input.tenant_id.trim().is_empty()
        || input.project_id.trim().is_empty()
        || input.expected_revision < 0
        || key.is_empty()
        || key.len() > 255
    {
        Err(workspace_context_error(
            WorkspaceContextRepositoryError::InvalidInput,
        ))
    } else {
        Ok(())
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
mod unit;
