//! Production `/api/v1` identity endpoints — the **P2 strangled surface**
//! (plan.md Section 15.2). Transport + Python-shape (de)serialization over
//! [`crate::identity::IdentityService`]; mirrors [`crate::prod_api`] in style.
//!
//! Routes split by authentication:
//!   - [`router_public`] (unauthenticated — login must not sit behind the key
//!     middleware): `POST /api/v1/auth/token`,
//!     `POST /api/v1/auth/oauth/{provider}/callback`.
//!   - [`router_authed`] (behind [`crate::auth::require_api_key`]):
//!     `GET/POST /api/v1/tenants/`, `GET/PUT /api/v1/tenants/{id}`,
//!     `GET/POST /api/v1/projects/`, `GET/PUT/DELETE /api/v1/projects/{id}`.

use axum::{
    extract::{Form, Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{delete, get, patch, post},
    Extension, Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

use agistack_adapters_postgres::{ProjectUpdatePatch, TenantUpdatePatch};

use crate::auth::Identity;
use crate::identity::{
    DeviceApproveView, DeviceCodeView, DeviceTokenView, IdentityError, InvitationListView,
    InvitationVerifyView, InvitationView, ProjectCreateInput, ProjectMemberMutationView,
    ProjectMembersView, ProjectPage, ProjectStatsView, ProjectView, TenantMemberMutationView,
    TenantPage, TenantView,
};
use crate::AppState;

/// Render [`IdentityError`] as FastAPI's `{"detail": ...}` envelope, adding
/// `WWW-Authenticate: Bearer` only when the originating Python `HTTPException`
/// does (the login 401 — not the inactive 401).
impl IntoResponse for IdentityError {
    fn into_response(self) -> Response {
        let detail = self
            .detail_value
            .unwrap_or_else(|| serde_json::Value::String(self.detail));
        let body = Json(json!({ "detail": detail }));
        if self.www_authenticate {
            (self.status, [("WWW-Authenticate", "Bearer")], body).into_response()
        } else {
            (self.status, body).into_response()
        }
    }
}

// ---- POST /auth/token (login) ---------------------------------------------

/// OAuth2 password-grant form. Mirrors FastAPI's `OAuth2PasswordRequestForm`:
/// `username` + `password` are required; other grant fields (grant_type, scope,
/// client_id/secret) are accepted and ignored.
#[derive(Deserialize)]
struct LoginForm {
    username: String,
    password: String,
}

/// `POST /api/v1/auth/token` — verify credentials, mint a short-lived `ms_sk_`
/// session key, and return the flat Python `Token` shape. Unauthenticated.
async fn login(
    State(app): State<AppState>,
    Form(form): Form<LoginForm>,
) -> Result<Json<crate::identity::LoginOutcome>, IdentityError> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    let outcome = app
        .identity
        .login(&form.username, &form.password, now_ms)
        .await?;
    Ok(Json(outcome))
}

// ---- POST /auth/oauth/{provider}/callback (501 stub) ----------------------

/// `POST /api/v1/auth/oauth/{provider}/callback` — Python returns an explicit
/// `501` until OAuth providers are configured; Rust owns the path with the same
/// status + detail so the strangler can flip it. (Real OAuth authorization-code /
/// PKCE flow is a documented future item.)
async fn oauth_callback(Path(_provider): Path<String>) -> Response {
    (
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({ "detail": "OAuth login is not configured" })),
    )
        .into_response()
}

// ---- device-code login ----------------------------------------------------

#[derive(Deserialize)]
struct DeviceCodeRequest {
    #[serde(default, rename = "client_id")]
    _client_id: Option<String>,
    #[serde(default, rename = "scope")]
    _scope: Option<String>,
}

#[derive(Deserialize)]
struct DeviceApproveRequest {
    #[serde(default)]
    user_code: String,
}

#[derive(Deserialize)]
struct DeviceTokenRequest {
    #[serde(default)]
    device_code: String,
}

async fn device_code(
    State(app): State<AppState>,
    _body: Option<Json<DeviceCodeRequest>>,
) -> Result<Json<DeviceCodeView>, IdentityError> {
    Ok(Json(app.identity.create_device_code().await?))
}

async fn approve_device_code(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(body): Json<DeviceApproveRequest>,
) -> Result<Json<DeviceApproveView>, IdentityError> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    let view = app
        .identity
        .approve_device_code(&identity.user_id, &body.user_code, now_ms)
        .await?;
    Ok(Json(view))
}

async fn device_token(
    State(app): State<AppState>,
    Json(body): Json<DeviceTokenRequest>,
) -> Result<Json<DeviceTokenView>, IdentityError> {
    Ok(Json(
        app.identity.poll_device_token(&body.device_code).await?,
    ))
}

// ---- GET /tenants (list) + /tenants/{id} (get) ----------------------------

/// Pagination + search query for the tenant list. Defaults mirror Python
/// (`page=1`, `page_size=20`).
#[derive(Deserialize)]
struct TenantListQuery {
    #[serde(default = "default_page")]
    page: i64,
    #[serde(default = "default_page_size")]
    page_size: i64,
    #[serde(default)]
    search: Option<String>,
}

fn default_page() -> i64 {
    1
}
fn default_page_size() -> i64 {
    20
}

/// `GET /api/v1/tenants/` — list the caller's tenants (membership-scoped,
/// paginated). Requires a verified [`Identity`].
async fn list_tenants(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<TenantListQuery>,
) -> Result<Json<TenantPage>, IdentityError> {
    let page = app
        .identity
        .list_tenants(&identity.user_id, q.search.as_deref(), q.page, q.page_size)
        .await?;
    Ok(Json(page))
}

/// `GET /api/v1/tenants/{id}` — fetch one tenant by id-or-slug, scoped to the
/// caller's membership (404 if absent, 403 if not a member — Python ordering).
async fn get_tenant(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
) -> Result<Json<TenantView>, IdentityError> {
    let view = app
        .identity
        .get_tenant(&identity.user_id, &tenant_id)
        .await?;
    Ok(Json(view))
}

#[derive(Deserialize)]
struct CreateTenantRequest {
    name: String,
    #[serde(default)]
    description: Option<String>,
}

#[derive(Deserialize)]
struct AddTenantMemberRequest {
    user_id: String,
    #[serde(default)]
    role: Option<String>,
}

#[derive(Deserialize)]
struct AddTenantMemberQuery {
    #[serde(default = "default_member_role")]
    role: String,
}

#[derive(Deserialize)]
struct UpdateTenantMemberRequest {
    role: String,
}

fn default_member_role() -> String {
    "member".to_string()
}

fn tenant_update_patch_from_value(value: Value) -> Result<TenantUpdatePatch, IdentityError> {
    let Value::Object(map) = value else {
        return Err(IdentityError {
            status: StatusCode::UNPROCESSABLE_ENTITY,
            detail: "Invalid request body".to_string(),
            detail_value: None,
            www_authenticate: false,
        });
    };

    let mut patch = TenantUpdatePatch::default();
    if let Some(value) = map.get("name") {
        if let Some(name) = value.as_str() {
            patch.name = Some(name.to_string());
        }
    }
    if let Some(value) = map.get("description") {
        patch.description = if value.is_null() {
            Some(None)
        } else {
            value
                .as_str()
                .map(|description| Some(description.to_string()))
        };
    }
    if let Some(value) = map.get("plan") {
        if let Some(plan) = value.as_str() {
            patch.plan = Some(plan.to_string());
        }
    }
    if let Some(value) = map.get("max_projects") {
        if let Some(max_projects) = value.as_i64() {
            patch.max_projects = Some(max_projects as i32);
        }
    }
    if let Some(value) = map.get("max_users") {
        if let Some(max_users) = value.as_i64() {
            patch.max_users = Some(max_users as i32);
        }
    }
    if let Some(value) = map.get("max_storage") {
        if let Some(max_storage) = value.as_i64() {
            patch.max_storage = Some(max_storage);
        }
    }
    Ok(patch)
}

async fn create_tenant(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(body): Json<CreateTenantRequest>,
) -> Result<impl IntoResponse, IdentityError> {
    let view = app
        .identity
        .create_tenant(&identity.user_id, &body.name, body.description.as_deref())
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn update_tenant(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Json(body): Json<Value>,
) -> Result<Json<TenantView>, IdentityError> {
    let patch = tenant_update_patch_from_value(body)?;
    let view = app
        .identity
        .update_tenant(&identity.user_id, &tenant_id, patch)
        .await?;
    Ok(Json(view))
}

async fn delete_tenant(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
) -> Result<impl IntoResponse, IdentityError> {
    app.identity
        .delete_tenant(&identity.user_id, &tenant_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn add_tenant_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Json(body): Json<AddTenantMemberRequest>,
) -> Result<impl IntoResponse, IdentityError> {
    let view = app
        .identity
        .add_tenant_member(
            &identity.user_id,
            &tenant_id,
            &body.user_id,
            body.role.as_deref(),
        )
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn add_tenant_member_by_path(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, user_id)): Path<(String, String)>,
    Query(query): Query<AddTenantMemberQuery>,
) -> Result<impl IntoResponse, IdentityError> {
    let view = app
        .identity
        .add_tenant_member(&identity.user_id, &tenant_id, &user_id, Some(&query.role))
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn update_tenant_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, user_id)): Path<(String, String)>,
    Json(body): Json<UpdateTenantMemberRequest>,
) -> Result<Json<TenantMemberMutationView>, IdentityError> {
    let view = app
        .identity
        .update_tenant_member(&identity.user_id, &tenant_id, &user_id, &body.role)
        .await?;
    Ok(Json(view))
}

async fn remove_tenant_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, user_id)): Path<(String, String)>,
) -> Result<impl IntoResponse, IdentityError> {
    app.identity
        .remove_tenant_member(&identity.user_id, &tenant_id, &user_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

// ---- GET /projects (list) + /projects/{id} (get) --------------------------

#[derive(Deserialize)]
struct ProjectListQuery {
    #[serde(default)]
    tenant_id: Option<String>,
    #[serde(default = "default_page")]
    page: i64,
    #[serde(default = "default_page_size")]
    page_size: i64,
    #[serde(default)]
    search: Option<String>,
    #[serde(default = "default_visibility")]
    visibility: String,
    #[serde(default)]
    owner_id: Option<String>,
}

fn default_visibility() -> String {
    "all".to_string()
}

#[derive(Deserialize)]
struct ProjectGetQuery {
    #[serde(default)]
    tenant_id: Option<String>,
}

#[derive(Deserialize)]
struct CreateProjectRequest {
    name: String,
    tenant_id: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    memory_rules: Option<Value>,
    #[serde(default)]
    graph_config: Option<Value>,
    #[serde(default)]
    graph_store_id: Option<String>,
    #[serde(default)]
    retrieval_store_id: Option<String>,
    #[serde(default, rename = "sandbox_config")]
    _sandbox_config: Option<Value>,
    #[serde(default)]
    is_public: bool,
    #[serde(default = "default_agent_conversation_mode")]
    agent_conversation_mode: String,
}

fn default_agent_conversation_mode() -> String {
    "single_agent".to_string()
}

fn invalid_request_body() -> IdentityError {
    IdentityError {
        status: StatusCode::UNPROCESSABLE_ENTITY,
        detail: "Invalid request body".to_string(),
        detail_value: None,
        www_authenticate: false,
    }
}

fn project_update_patch_from_value(value: Value) -> Result<ProjectUpdatePatch, IdentityError> {
    let Value::Object(map) = value else {
        return Err(invalid_request_body());
    };

    let mut patch = ProjectUpdatePatch::default();
    if let Some(value) = map.get("name") {
        if let Some(name) = value.as_str() {
            patch.name = Some(name.to_string());
        }
    }
    if let Some(value) = map.get("description") {
        patch.description = if value.is_null() {
            Some(None)
        } else {
            value
                .as_str()
                .map(|description| Some(description.to_string()))
        };
    }
    if let Some(value) = map.get("memory_rules") {
        patch.memory_rules = Some(value.clone());
    }
    if let Some(value) = map.get("graph_config") {
        patch.graph_config = Some(value.clone());
    }
    if let Some(value) = map.get("graph_store_id") {
        patch.graph_store_id = if value.is_null() {
            Some(None)
        } else {
            value.as_str().map(|store_id| Some(store_id.to_string()))
        };
    }
    if let Some(value) = map.get("retrieval_store_id") {
        patch.retrieval_store_id = if value.is_null() {
            Some(None)
        } else {
            value.as_str().map(|store_id| Some(store_id.to_string()))
        };
    }
    if let Some(value) = map.get("sandbox_config") {
        patch.sandbox_config = Some(value.clone());
    }
    if let Some(value) = map.get("is_public") {
        if let Some(is_public) = value.as_bool() {
            patch.is_public = Some(is_public);
        }
    }
    if let Some(value) = map.get("agent_conversation_mode") {
        if let Some(mode) = value.as_str() {
            patch.agent_conversation_mode = Some(mode.to_string());
        }
    }
    Ok(patch)
}

async fn list_projects(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<ProjectListQuery>,
) -> Result<Json<ProjectPage>, IdentityError> {
    let page = app
        .identity
        .list_projects(
            &identity.user_id,
            q.tenant_id.as_deref(),
            q.search.as_deref(),
            &q.visibility,
            q.owner_id.as_deref(),
            q.page,
            q.page_size,
        )
        .await?;
    Ok(Json(page))
}

async fn get_project(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(q): Query<ProjectGetQuery>,
) -> Result<Json<ProjectView>, IdentityError> {
    let view = app
        .identity
        .get_project(&identity.user_id, &project_id, q.tenant_id.as_deref())
        .await?;
    Ok(Json(view))
}

async fn create_project(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(body): Json<CreateProjectRequest>,
) -> Result<impl IntoResponse, IdentityError> {
    let view = app
        .identity
        .create_project(
            &identity.user_id,
            ProjectCreateInput {
                tenant_id: body.tenant_id,
                name: body.name,
                description: body.description,
                memory_rules: body.memory_rules,
                graph_config: body.graph_config,
                graph_store_id: body.graph_store_id,
                retrieval_store_id: body.retrieval_store_id,
                is_public: body.is_public,
                agent_conversation_mode: body.agent_conversation_mode,
            },
        )
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn update_project(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(body): Json<Value>,
) -> Result<Json<ProjectView>, IdentityError> {
    let patch = project_update_patch_from_value(body)?;
    let view = app
        .identity
        .update_project(&identity.user_id, &project_id, patch)
        .await?;
    Ok(Json(view))
}

async fn delete_project(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> Result<StatusCode, IdentityError> {
    app.identity
        .delete_project(&identity.user_id, &project_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn get_project_stats(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> Result<Json<ProjectStatsView>, IdentityError> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    let stats = app
        .identity
        .get_project_stats(&identity.user_id, &project_id, now_ms)
        .await?;
    Ok(Json(stats))
}

async fn list_project_members(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
) -> Result<Json<ProjectMembersView>, IdentityError> {
    let members = app
        .identity
        .list_project_members(&identity.user_id, &project_id)
        .await?;
    Ok(Json(members))
}

#[derive(Deserialize)]
struct AddProjectMemberRequest {
    user_id: String,
    #[serde(default)]
    role: Option<String>,
}

#[derive(Deserialize)]
struct UpdateProjectMemberRequest {
    role: String,
}

async fn add_project_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Json(body): Json<AddProjectMemberRequest>,
) -> Result<impl IntoResponse, IdentityError> {
    let view = app
        .identity
        .add_project_member(
            &identity.user_id,
            &project_id,
            &body.user_id,
            body.role.as_deref(),
        )
        .await?;
    Ok((StatusCode::CREATED, Json(view)))
}

async fn update_project_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, user_id)): Path<(String, String)>,
    Json(body): Json<UpdateProjectMemberRequest>,
) -> Result<Json<ProjectMemberMutationView>, IdentityError> {
    let view = app
        .identity
        .update_project_member(&identity.user_id, &project_id, &user_id, &body.role)
        .await?;
    Ok(Json(view))
}

async fn remove_project_member(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((project_id, user_id)): Path<(String, String)>,
) -> Result<impl IntoResponse, IdentityError> {
    app.identity
        .remove_project_member(&identity.user_id, &project_id, &user_id)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

// ---- invitations ----------------------------------------------------------

#[derive(Deserialize)]
struct CreateInvitationRequest {
    email: String,
    #[serde(default = "default_invitation_role")]
    role: String,
    #[serde(default)]
    message: Option<String>,
}

fn default_invitation_role() -> String {
    "member".to_string()
}

#[derive(Deserialize)]
struct InvitationListQuery {
    #[serde(default = "default_invitation_limit")]
    limit: i64,
    #[serde(default)]
    offset: i64,
}

fn default_invitation_limit() -> i64 {
    50
}

#[derive(Deserialize)]
struct AcceptInvitationRequest {
    #[serde(default)]
    _display_name: Option<String>,
}

async fn create_invitation(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Json(body): Json<CreateInvitationRequest>,
) -> Result<impl IntoResponse, IdentityError> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    let invitation = app
        .identity
        .create_invitation(
            &identity.user_id,
            &tenant_id,
            &body.email,
            &body.role,
            body.message.as_deref(),
            now_ms,
        )
        .await?;
    Ok((StatusCode::CREATED, Json(invitation)))
}

async fn list_invitations(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(tenant_id): Path<String>,
    Query(q): Query<InvitationListQuery>,
) -> Result<Json<InvitationListView>, IdentityError> {
    let items = app
        .identity
        .list_invitations(&identity.user_id, &tenant_id, q.limit, q.offset)
        .await?;
    Ok(Json(items))
}

async fn cancel_invitation(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((tenant_id, invitation_id)): Path<(String, String)>,
) -> Result<StatusCode, IdentityError> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    app.identity
        .cancel_invitation(&identity.user_id, &tenant_id, &invitation_id, now_ms)
        .await?;
    Ok(StatusCode::NO_CONTENT)
}

async fn verify_invitation(
    State(app): State<AppState>,
    Path(token): Path<String>,
) -> Result<Json<InvitationVerifyView>, IdentityError> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    let view = app.identity.verify_invitation(&token, now_ms).await?;
    Ok(Json(view))
}

async fn accept_invitation(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(token): Path<String>,
    Json(_body): Json<AcceptInvitationRequest>,
) -> Result<Json<InvitationView>, IdentityError> {
    let now_ms = chrono::Utc::now().timestamp_millis();
    let view = app
        .identity
        .accept_invitation(&token, &identity.user_id, now_ms)
        .await?;
    Ok(Json(view))
}

// ---- routers --------------------------------------------------------------

/// Unauthenticated identity routes (login + oauth stub). These must **not** sit
/// behind the API-key middleware — you cannot present a key before you have one.
pub fn router_public() -> Router<AppState> {
    Router::new()
        .route("/api/v1/auth/token", post(login))
        .route("/api/v1/auth/device/code", post(device_code))
        .route("/api/v1/auth/device/token", post(device_token))
        .route(
            "/api/v1/auth/oauth/:provider/callback",
            post(oauth_callback),
        )
        .route("/api/v1/invitations/verify/:token", get(verify_invitation))
}

/// Authenticated identity routes (tenant reads). The caller layers
/// [`crate::auth::require_api_key`] so every handler runs with a verified
/// [`Identity`]. Both trailing-slash and bare forms are registered to avoid
/// FastAPI-style 307 redirects that strip the `Authorization` header.
pub fn router_authed() -> Router<AppState> {
    Router::new()
        .route("/api/v1/tenants/", get(list_tenants).post(create_tenant))
        .route("/api/v1/tenants", get(list_tenants).post(create_tenant))
        .route(
            "/api/v1/tenants/:id",
            get(get_tenant).put(update_tenant).delete(delete_tenant),
        )
        .route(
            "/api/v1/tenants/:tenant_id/members",
            post(add_tenant_member),
        )
        .route(
            "/api/v1/tenants/:tenant_id/members/:user_id",
            post(add_tenant_member_by_path)
                .patch(update_tenant_member)
                .delete(remove_tenant_member),
        )
        .route("/api/v1/projects/", get(list_projects).post(create_project))
        .route("/api/v1/projects", get(list_projects).post(create_project))
        .route("/api/v1/projects/:id/stats", get(get_project_stats))
        .route(
            "/api/v1/projects/:id/members",
            get(list_project_members).post(add_project_member),
        )
        .route(
            "/api/v1/projects/:id/members/:user_id",
            patch(update_project_member).delete(remove_project_member),
        )
        .route(
            "/api/v1/projects/:id",
            get(get_project).put(update_project).delete(delete_project),
        )
        .route("/api/v1/auth/device/approve", post(approve_device_code))
        .route(
            "/api/v1/tenants/:tenant_id/invitations",
            get(list_invitations).post(create_invitation),
        )
        .route(
            "/api/v1/tenants/:tenant_id/invitations/:invitation_id",
            delete(cancel_invitation),
        )
        .route("/api/v1/invitations/accept/:token", post(accept_invitation))
}

#[cfg(test)]
mod unit {
    use super::*;

    #[test]
    fn query_defaults_match_python() {
        // serde defaults: page=1, page_size=20, search=None.
        let q: TenantListQuery = serde_urlencoded::from_str("").unwrap();
        assert_eq!(q.page, 1);
        assert_eq!(q.page_size, 20);
        assert!(q.search.is_none());
        let q2: TenantListQuery =
            serde_urlencoded::from_str("page=3&page_size=50&search=acme").unwrap();
        assert_eq!(q2.page, 3);
        assert_eq!(q2.page_size, 50);
        assert_eq!(q2.search.as_deref(), Some("acme"));
    }

    #[test]
    fn project_query_defaults_match_python() {
        let q: ProjectListQuery = serde_urlencoded::from_str("").unwrap();
        assert!(q.tenant_id.is_none());
        assert_eq!(q.page, 1);
        assert_eq!(q.page_size, 20);
        assert!(q.search.is_none());
        assert_eq!(q.visibility, "all");
        assert!(q.owner_id.is_none());

        let q2: ProjectListQuery = serde_urlencoded::from_str(
            "tenant_id=t1&page=2&page_size=10&search=ai&visibility=private&owner_id=u1",
        )
        .unwrap();
        assert_eq!(q2.tenant_id.as_deref(), Some("t1"));
        assert_eq!(q2.page, 2);
        assert_eq!(q2.page_size, 10);
        assert_eq!(q2.search.as_deref(), Some("ai"));
        assert_eq!(q2.visibility, "private");
        assert_eq!(q2.owner_id.as_deref(), Some("u1"));
    }

    #[test]
    fn login_form_ignores_extra_grant_fields() {
        // OAuth2 form may carry grant_type/scope; only username+password bind.
        let f: LoginForm =
            serde_urlencoded::from_str("grant_type=password&username=a%40b.co&password=pw&scope=")
                .unwrap();
        assert_eq!(f.username, "a@b.co");
        assert_eq!(f.password, "pw");
    }

    #[test]
    fn tenant_update_patch_preserves_explicit_null_and_known_fields() {
        let patch = tenant_update_patch_from_value(json!({
            "name": "Acme 2",
            "description": null,
            "plan": "enterprise",
            "max_projects": 20,
            "max_users": 50,
            "max_storage": 2147483648i64,
            "ignored": "kept out"
        }))
        .unwrap();
        assert_eq!(patch.name.as_deref(), Some("Acme 2"));
        assert_eq!(patch.description, Some(None));
        assert_eq!(patch.plan.as_deref(), Some("enterprise"));
        assert_eq!(patch.max_projects, Some(20));
        assert_eq!(patch.max_users, Some(50));
        assert_eq!(patch.max_storage, Some(2_147_483_648));
        assert!(!patch.is_empty());

        let invalid = tenant_update_patch_from_value(json!("not an object")).unwrap_err();
        assert_eq!(invalid.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[test]
    fn project_update_patch_preserves_explicit_null_and_known_fields() {
        let patch = project_update_patch_from_value(json!({
            "name": "Project 2",
            "description": null,
            "memory_rules": {"max_episodes": 2000},
            "graph_config": {"max_nodes": 5000},
            "graph_store_id": "__env_neo4j__",
            "retrieval_store_id": null,
            "sandbox_config": {"sandbox_type": "local", "local_config": {"host": "localhost"}},
            "is_public": true,
            "agent_conversation_mode": "multi_agent_shared",
            "ignored": "kept out"
        }))
        .unwrap();
        assert_eq!(patch.name.as_deref(), Some("Project 2"));
        assert_eq!(patch.description, Some(None));
        assert_eq!(patch.memory_rules.as_ref().unwrap()["max_episodes"], 2000);
        assert_eq!(patch.graph_config.as_ref().unwrap()["max_nodes"], 5000);
        assert_eq!(
            patch.graph_store_id.as_ref().and_then(|v| v.as_deref()),
            Some("__env_neo4j__")
        );
        assert_eq!(patch.retrieval_store_id, Some(None));
        assert_eq!(
            patch.sandbox_config.as_ref().unwrap()["sandbox_type"],
            "local"
        );
        assert_eq!(patch.is_public, Some(true));
        assert_eq!(
            patch.agent_conversation_mode.as_deref(),
            Some("multi_agent_shared")
        );
        assert!(!patch.is_empty());

        let invalid = project_update_patch_from_value(json!("not an object")).unwrap_err();
        assert_eq!(invalid.status, StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[test]
    fn device_requests_default_missing_fields_like_python_dict_get() {
        let approve: DeviceApproveRequest = serde_json::from_str("{}").unwrap();
        assert!(approve.user_code.is_empty());
        let token: DeviceTokenRequest = serde_json::from_str("{}").unwrap();
        assert!(token.device_code.is_empty());
        let code: DeviceCodeRequest =
            serde_json::from_str(r#"{"client_id":"cli","scope":"read"}"#).unwrap();
        assert_eq!(code._client_id.as_deref(), Some("cli"));
        assert_eq!(code._scope.as_deref(), Some("read"));
    }

    #[test]
    fn invitation_query_defaults_match_python() {
        let q: InvitationListQuery = serde_urlencoded::from_str("").unwrap();
        assert_eq!(q.limit, 50);
        assert_eq!(q.offset, 0);
        let q2: InvitationListQuery = serde_urlencoded::from_str("limit=25&offset=10").unwrap();
        assert_eq!(q2.limit, 25);
        assert_eq!(q2.offset, 10);
    }
}
