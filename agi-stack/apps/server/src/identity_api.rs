//! Production `/api/v1` identity endpoints — the **P2 strangled surface**
//! (plan.md Section 15.2). Transport + Python-shape (de)serialization over
//! [`crate::identity::IdentityService`]; mirrors [`crate::prod_api`] in style.
//!
//! Routes split by authentication:
//!   - [`router_public`] (unauthenticated — login must not sit behind the key
//!     middleware): `POST /api/v1/auth/token`,
//!     `POST /api/v1/auth/oauth/{provider}/callback`.
//!   - [`router_authed`] (behind [`crate::auth::require_api_key`]):
//!     `GET /api/v1/tenants/`, `GET /api/v1/tenants/{id}`.

use axum::{
    extract::{Form, Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use serde::Deserialize;
use serde_json::json;

use crate::auth::Identity;
use crate::identity::{IdentityError, TenantPage, TenantView};
use crate::AppState;

/// Render [`IdentityError`] as FastAPI's `{"detail": ...}` envelope, adding
/// `WWW-Authenticate: Bearer` only when the originating Python `HTTPException`
/// does (the login 401 — not the inactive 401).
impl IntoResponse for IdentityError {
    fn into_response(self) -> Response {
        let body = Json(json!({ "detail": self.detail }));
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

// ---- routers --------------------------------------------------------------

/// Unauthenticated identity routes (login + oauth stub). These must **not** sit
/// behind the API-key middleware — you cannot present a key before you have one.
pub fn router_public() -> Router<AppState> {
    Router::new()
        .route("/api/v1/auth/token", post(login))
        .route(
            "/api/v1/auth/oauth/:provider/callback",
            post(oauth_callback),
        )
}

/// Authenticated identity routes (tenant reads). The caller layers
/// [`crate::auth::require_api_key`] so every handler runs with a verified
/// [`Identity`]. Both trailing-slash and bare forms are registered to avoid
/// FastAPI-style 307 redirects that strip the `Authorization` header.
pub fn router_authed() -> Router<AppState> {
    Router::new()
        .route("/api/v1/tenants/", get(list_tenants))
        .route("/api/v1/tenants", get(list_tenants))
        .route("/api/v1/tenants/:id", get(get_tenant))
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
    fn login_form_ignores_extra_grant_fields() {
        // OAuth2 form may carry grant_type/scope; only username+password bind.
        let f: LoginForm =
            serde_urlencoded::from_str("grant_type=password&username=a%40b.co&password=pw&scope=")
                .unwrap();
        assert_eq!(f.username, "a@b.co");
        assert_eq!(f.password, "pw");
    }
}
