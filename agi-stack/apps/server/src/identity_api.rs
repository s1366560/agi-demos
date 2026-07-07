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
use serde_json::{json, Value};

use agistack_adapters_postgres::{ProjectUpdatePatch, TenantUpdatePatch};

use crate::auth::Identity;
use crate::identity::{
    CurrentUserView, DeviceApproveView, DeviceCodeView, DeviceTokenView, IdentityError,
    InvitationListView, InvitationVerifyView, InvitationView, ProjectCreateInput, ProjectListInput,
    ProjectMemberMutationView, ProjectMembersView, ProjectPage, ProjectStatsView, ProjectView,
    TenantMemberMutationView, TenantPage, TenantView,
};
use crate::AppState;

#[cfg(test)]
mod tests;
mod views;

use views::*;

/// Render [`IdentityError`] as FastAPI's `{"detail": ...}` envelope, adding
/// `WWW-Authenticate: Bearer` only when the originating Python `HTTPException`
/// does (the login 401 — not the inactive 401).
impl IntoResponse for IdentityError {
    fn into_response(self) -> Response {
        let detail = self
            .detail_value
            .unwrap_or(serde_json::Value::String(self.detail));
        let body = Json(json!({ "detail": detail }));
        if self.www_authenticate {
            (self.status, [("WWW-Authenticate", "Bearer")], body).into_response()
        } else {
            (self.status, body).into_response()
        }
    }
}

// ---- POST /auth/token (login) ---------------------------------------------

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

// ---- GET /auth/me + /users/me --------------------------------------------

async fn current_user(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
) -> Result<Json<CurrentUserView>, IdentityError> {
    Ok(Json(app.identity.current_user(&identity.user_id).await?))
}

// ---- device-code login ----------------------------------------------------

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
            ProjectListInput {
                tenant_id: q.tenant_id.as_deref(),
                search: q.search.as_deref(),
                visibility: &q.visibility,
                owner_id: q.owner_id.as_deref(),
                page: q.page,
                page_size: q.page_size,
            },
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
        .route("/api/v1/auth/me", get(current_user))
        .route("/api/v1/auth/me/", get(current_user))
        .route("/api/v1/users/me", get(current_user))
        .route("/api/v1/users/me/", get(current_user))
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
