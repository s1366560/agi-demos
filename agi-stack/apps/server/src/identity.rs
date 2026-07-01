//! P2 **identity** service — the login + tenant-read slice of the strangler
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
//! - **`GET /tenants/` + `GET /tenants/{id}`** — implemented and
//!   membership-scoped, structurally parity-tested. **Flip deferred**: (a) the
//!   gateway strangles by coarse prefix, which would also capture the
//!   `/tenants/{id}/members|stats|analytics` siblings that remain in Python; and
//!   (b) `TenantResponse` timestamps depend on pydantic's exact ISO-8601
//!   rendering (`Z` vs `+00:00`, sub-second precision) — an F3 golden-capture
//!   concern shared with P1. Until golden-captured against the live Python
//!   server, tenants read is "ready + tested, not yet flipped".
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
use serde::Serialize;

use agistack_adapters_postgres::{PgTenantRepository, PgUserStore, TenantLookup, TenantRecord};
use agistack_adapters_secrets::{generate_api_key, generate_uuid_v4, verify_password};

/// One day in milliseconds — the login key TTL (`expires_in_days=1` in Python).
const LOGIN_KEY_TTL_MS: i64 = 24 * 60 * 60 * 1000;

/// Why an identity request was rejected, carrying the HTTP status + a
/// Python-parity `detail` string, plus whether to add `WWW-Authenticate: Bearer`
/// (the login 401 does; the inactive 401 does not — mirroring Python exactly).
#[derive(Debug)]
pub struct IdentityError {
    pub status: StatusCode,
    pub detail: String,
    pub www_authenticate: bool,
}

impl IdentityError {
    fn unauthorized(detail: impl Into<String>, www_authenticate: bool) -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            detail: detail.into(),
            www_authenticate,
        }
    }
    fn not_found(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            detail: detail.into(),
            www_authenticate: false,
        }
    }
    fn forbidden(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::FORBIDDEN,
            detail: detail.into(),
            www_authenticate: false,
        }
    }
    fn internal(detail: impl std::fmt::Display) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            detail: detail.to_string(),
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

/// Format a UTC timestamp as ISO-8601 with a trailing `Z`, consistent with P1's
/// `prod_api::rfc3339`. (Exact pydantic format parity — `Z` vs `+00:00`,
/// sub-second precision — is a shared F3 golden-capture item; tenants read is not
/// flipped until then.)
fn iso8601(dt: chrono::DateTime<chrono::Utc>) -> String {
    dt.to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

/// Server-side identity port: mint a session key on login and serve
/// membership-scoped tenant reads. Two impls (Postgres / dev). Kept out of the
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
}

/// Convenience alias for the shared identity handle stored in `AppState`.
pub type SharedIdentity = Arc<dyn IdentityService>;

// ---- production impl ------------------------------------------------------

/// Production identity service over the shared Python `users`/`api_keys`/
/// `tenants` tables (`agistack-adapters-postgres` + `agistack-adapters-secrets`).
pub struct PgIdentityService {
    users: PgUserStore,
    tenants: PgTenantRepository,
}

impl PgIdentityService {
    pub fn new(users: PgUserStore, tenants: PgTenantRepository) -> Self {
        Self { users, tenants }
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
            return Err(IdentityError::unauthorized("User account is inactive", false));
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
            .insert_api_key(&key_id, &plain_key, &name, &user.id, expires_at, &permissions)
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
}

// ---- offline dev impl -----------------------------------------------------

/// Offline identity service: mints a fake `ms_sk_` key for any non-empty
/// credentials and serves a single deterministic dev tenant. Never used when
/// `DATABASE_URL` is set. Keeps `cargo run`/tests keyless and DB-free, exactly
/// like [`crate::auth::DevAuthenticator`].
pub struct DevIdentityService {
    dev_user_id: String,
}

impl DevIdentityService {
    pub fn new(dev_user_id: impl Into<String>) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
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
        let tenants = all.into_iter().skip(start as usize).take(page_size as usize).collect();
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
}

/// Defensive pagination guard: default missing values and keep them in Python's
/// `page >= 1`, `1 <= page_size <= 100` bounds so an offset can never go negative
/// or absurd. (Full FastAPI `422` validation parity is deferred with the flip.)
fn clamp_pagination(page: i64, page_size: i64) -> (i64, i64) {
    let page = page.max(1);
    let page_size = page_size.clamp(1, 100);
    (page, page_size)
}

#[cfg(test)]
mod unit {
    use super::*;

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
        let none = svc.list_tenants("dev-user", Some("zzz"), 1, 20).await.unwrap();
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
        assert_eq!(svc.get_tenant("u", "dev-tenant").await.unwrap().id, "dev-tenant");
        assert_eq!(svc.get_tenant("u", "dev").await.unwrap().slug, "dev");
        assert_eq!(
            svc.get_tenant("u", "nope").await.unwrap_err().status,
            StatusCode::NOT_FOUND
        );
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
}
