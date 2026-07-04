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
    PgTenantRepository, PgUserStore, ProjectActivityRecord, ProjectCreateRecord,
    ProjectListForUserQuery, ProjectLookup, ProjectMembersLookup, ProjectStatsLookup,
    ProjectUpdatePatch, TenantAdminStatus, TenantLookup, TenantUpdatePatch,
};
use agistack_adapters_redis::DeviceGrant;
use agistack_adapters_secrets::{
    generate_api_key, generate_urlsafe_token, generate_uuid_v4, verify_password,
};
use agistack_core::ports::{EmailMessage, EmailSender};

mod dev_service;
mod device_grants;
mod views;

pub use dev_service::DevIdentityService;
use device_grants::{
    create_device_code_with_store, normalize_device_user_code, poll_device_token_from_store,
};
pub use device_grants::{DeviceGrantStore, InMemoryDeviceGrantStore, SharedDeviceGrantStore};
pub use views::{
    BackendStoreSummary, DeviceApproveView, DeviceCodeView, DeviceTokenView, InvitationListView,
    InvitationVerifyView, InvitationView, LoginOutcome, ProjectCreateInput, ProjectListInput,
    ProjectMemberMutationView, ProjectMemberView, ProjectMembersView, ProjectPage,
    ProjectStatsView, ProjectView, TenantMemberMutationView, TenantPage, TenantView,
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
        input: ProjectListInput<'_>,
    ) -> Result<ProjectPage, IdentityError> {
        let ProjectListInput {
            tenant_id,
            search,
            visibility,
            owner_id,
            page,
            page_size,
        } = input;
        let (page, page_size) = clamp_pagination(page, page_size);
        let offset = (page - 1) * page_size;
        let records = self
            .projects
            .list_for_user(ProjectListForUserQuery {
                user_id,
                tenant_id,
                search,
                visibility,
                owner_id,
                offset,
                limit: page_size,
            })
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
            ProjectLookup::Found(record) => Ok(ProjectView::from(*record)),
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
