//! Production authentication + multi-tenancy middleware — Foundation **F2** of the
//! strangler migration (plan.md Section 14.2).
//!
//! It replicates the Python `ms_sk_` bearer contract
//! (`src/.../dependencies/auth_dependencies.py`) so the frontend/SDK see the same
//! auth behavior whether a request is served by Python or by the strangled Rust
//! path:
//!   1. read `Authorization: Bearer <key>` (also `Token ` / bare);
//!   2. require the `ms_sk_` prefix;
//!   3. SHA-256 the key and match `api_keys.key_hash` (identical hash to Python);
//!   4. reject inactive/expired keys with `401`;
//!   5. attach a scoped [`Identity`] to the request for downstream handlers.
//!
//! ## Two authenticators, one middleware
//! The authenticator is a trait so the server runs with a real database in
//! production and a deterministic stub offline. Both are **server-side** concerns
//! and never touch the portable core.
//! - [`PgAuthenticator`]: verifies against the shared `api_keys`/`projects` tables
//!   (`agistack-adapters-postgres`). This is the production path.
//! - [`DevAuthenticator`]: accepts any well-formed `ms_sk_` key, maps it to a
//!   fixed dev user, and allows every project. Keeps `cargo run`/tests keyless and
//!   DB-free, exactly like the offline LLM stub.
//!
//! ## Agent First
//! Nothing here is a *judgment*: it is set-membership (prefix, roster) + a hash
//! lookup + arithmetic expiry — the deterministic protocol facts the top-level
//! rule explicitly keeps out of the agent. No semantics are inferred.

use std::sync::Arc;

use async_trait::async_trait;
use axum::{
    body::Body,
    extract::State,
    http::{Request, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde_json::json;

use agistack_adapters_postgres::{PgApiKeyStore, PgProjectStore};

use crate::AppState;

/// The verified caller attached to a request after auth succeeds. Handlers read
/// it via `Extension<Identity>` and scope every query by it (multi-tenancy).
#[derive(Debug, Clone)]
pub struct Identity {
    pub user_id: String,
    pub api_key_id: String,
}

/// Why a request was rejected. Carries the HTTP status + a Python-parity detail
/// string so the JSON error envelope matches the legacy backend.
#[derive(Debug)]
pub struct AuthRejection {
    pub status: StatusCode,
    pub detail: String,
}

impl AuthRejection {
    fn unauthorized(detail: impl Into<String>) -> Self {
        Self {
            status: StatusCode::UNAUTHORIZED,
            detail: detail.into(),
        }
    }
}

impl IntoResponse for AuthRejection {
    fn into_response(self) -> Response {
        // Mirror FastAPI's `{"detail": ...}` envelope + `WWW-Authenticate: Bearer`.
        (
            self.status,
            [("WWW-Authenticate", "Bearer")],
            Json(json!({ "detail": self.detail })),
        )
            .into_response()
    }
}

/// Server-side auth port: verify a raw key and check project access. Two impls
/// (Postgres / dev). Kept out of the portable core — it is a server concern.
#[async_trait]
pub trait Authenticator: Send + Sync {
    /// Resolve a raw `ms_sk_...` key to an [`Identity`], or reject. `now_ms` is
    /// injected (no ambient clock) so expiry is testable/deterministic.
    async fn authenticate(&self, raw_key: &str, now_ms: i64) -> Result<Identity, AuthRejection>;

    /// Whether `user_id` may act within `project_id` (owner / public / member).
    async fn can_access_project(&self, user_id: &str, project_id: &str) -> Result<bool, String>;
}

/// Production authenticator over the shared Python `api_keys`/`projects` tables.
pub struct PgAuthenticator {
    keys: PgApiKeyStore,
    projects: PgProjectStore,
}

impl PgAuthenticator {
    pub fn new(keys: PgApiKeyStore, projects: PgProjectStore) -> Self {
        Self { keys, projects }
    }
}

#[async_trait]
impl Authenticator for PgAuthenticator {
    async fn authenticate(&self, raw_key: &str, now_ms: i64) -> Result<Identity, AuthRejection> {
        let record = self
            .keys
            .find_by_raw_key(raw_key)
            .await
            .map_err(|e| AuthRejection {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                detail: e.to_string(),
            })?
            .ok_or_else(|| AuthRejection::unauthorized("Invalid API key"))?;

        if !record.is_usable_at(now_ms) {
            return Err(AuthRejection::unauthorized("API key is inactive or expired"));
        }

        // Best-effort audit touch; a failure here must never fail the request.
        let _ = self.keys.touch_last_used(&record.id).await;

        Ok(Identity {
            user_id: record.user_id,
            api_key_id: record.id,
        })
    }

    async fn can_access_project(&self, user_id: &str, project_id: &str) -> Result<bool, String> {
        match self.projects.find_by_id(project_id).await.map_err(|e| e.to_string())? {
            Some(project) => self
                .projects
                .user_can_access(user_id, &project)
                .await
                .map_err(|e| e.to_string()),
            None => Ok(false),
        }
    }
}

/// Offline authenticator: accepts any well-formed `ms_sk_` key, maps it to a
/// fixed dev user, and permits every project. Never used when `DATABASE_URL` is
/// set. Lets `cargo run` and the gateway end-to-end test run without a database.
pub struct DevAuthenticator {
    dev_user_id: String,
}

impl DevAuthenticator {
    pub fn new(dev_user_id: impl Into<String>) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
        }
    }
}

#[async_trait]
impl Authenticator for DevAuthenticator {
    async fn authenticate(&self, raw_key: &str, _now_ms: i64) -> Result<Identity, AuthRejection> {
        // Prefix is validated by the middleware before this is called; re-check so
        // the dev path can't be looser than production.
        if !raw_key.starts_with("ms_sk_") {
            return Err(AuthRejection::unauthorized(
                "Invalid API key format. API keys should start with 'ms_sk_'",
            ));
        }
        Ok(Identity {
            user_id: self.dev_user_id.clone(),
            api_key_id: format!("dev_{}", &raw_key[..raw_key.len().min(14)]),
        })
    }

    async fn can_access_project(&self, _user_id: &str, _project_id: &str) -> Result<bool, String> {
        Ok(true)
    }
}

/// Extract the raw key from an `Authorization` header value, applying the same
/// prefix rules as the Python `get_api_key_from_header`.
fn extract_raw_key(authorization: Option<&str>) -> Result<String, AuthRejection> {
    let Some(authorization) = authorization else {
        return Err(AuthRejection::unauthorized(
            "Missing API key. Please provide an API key in the Authorization header.",
        ));
    };
    let raw = if let Some(rest) = authorization.strip_prefix("Bearer ") {
        rest
    } else if let Some(rest) = authorization.strip_prefix("Token ") {
        rest
    } else {
        authorization
    };
    if !raw.starts_with("ms_sk_") {
        return Err(AuthRejection::unauthorized(
            "Invalid API key format. API keys should start with 'ms_sk_'",
        ));
    }
    Ok(raw.to_string())
}

/// Axum middleware guarding the production `/api/v1` surface. On success it
/// inserts an [`Identity`] into request extensions; on failure it short-circuits
/// with the Python-parity 401 envelope.
pub async fn require_api_key(
    State(app): State<AppState>,
    mut request: Request<Body>,
    next: Next,
) -> Response {
    let header = request
        .headers()
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .map(str::to_string);

    let raw_key = match extract_raw_key(header.as_deref()) {
        Ok(key) => key,
        Err(rejection) => return rejection.into_response(),
    };

    let now_ms = chrono::Utc::now().timestamp_millis();
    match app.auth.authenticate(&raw_key, now_ms).await {
        Ok(identity) => {
            request.extensions_mut().insert(identity);
            next.run(request).await
        }
        Err(rejection) => rejection.into_response(),
    }
}

/// Convenience alias for the shared authenticator handle stored in `AppState`.
pub type SharedAuthenticator = Arc<dyn Authenticator>;

#[cfg(test)]
mod unit {
    use super::*;

    #[test]
    fn extract_handles_bearer_token_and_bare() {
        assert_eq!(extract_raw_key(Some("Bearer ms_sk_abc")).unwrap(), "ms_sk_abc");
        assert_eq!(extract_raw_key(Some("Token ms_sk_abc")).unwrap(), "ms_sk_abc");
        assert_eq!(extract_raw_key(Some("ms_sk_abc")).unwrap(), "ms_sk_abc");
    }

    #[test]
    fn extract_rejects_missing_and_malformed() {
        assert_eq!(
            extract_raw_key(None).unwrap_err().status,
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            extract_raw_key(Some("Bearer sk-openai")).unwrap_err().status,
            StatusCode::UNAUTHORIZED
        );
    }

    #[tokio::test]
    async fn dev_authenticator_accepts_ms_sk_and_allows_projects() {
        let auth = DevAuthenticator::new("dev-user");
        let id = auth.authenticate("ms_sk_demo", 0).await.unwrap();
        assert_eq!(id.user_id, "dev-user");
        assert!(auth.can_access_project("dev-user", "p1").await.unwrap());
        assert!(auth.authenticate("nope", 0).await.is_err());
    }
}
