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

use std::collections::HashSet;
use std::sync::{Arc, Mutex};

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
use sha2::{Digest, Sha256};

use agistack_adapters_postgres::{PgApiKeyStore, PgProjectStore};

use crate::AppState;

/// The verified caller attached to a request after auth succeeds. Handlers read
/// it via `Extension<Identity>` and scope every query by it (multi-tenancy).
#[derive(Debug, Clone)]
pub struct Identity {
    pub user_id: String,
    /// Authenticated API-key id, retained for audit/event attribution as more
    /// strangled surfaces move into Rust.
    pub _api_key_id: String,
}

/// The raw `ms_sk_...` token accepted by the auth middleware. Most handlers only
/// need [`Identity`]; proxy bootstrap endpoints also need the legacy token value
/// because Python seeds it directly into a scoped HttpOnly cookie for iframe and
/// WebSocket subresources.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RawApiKey(pub String);

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

    /// Revoke exactly the API key represented by `raw_key`. Implementations
    /// must treat an absent/already-revoked key as success.
    async fn revoke_api_key(&self, raw_key: &str) -> Result<(), AuthRejection>;

    /// Whether `user_id` may read within `project_id` (owner / public / member).
    async fn can_access_project(&self, user_id: &str, project_id: &str) -> Result<bool, String>;

    /// Resolve the exact tenant for a project runtime-event subscription.
    /// Public visibility alone never grants access to tenant-private streams.
    async fn authorize_project_event_subscription(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<Option<String>, String>;

    /// Whether `user_id` may create memories/episodes within `project_id`.
    async fn can_write_project(&self, user_id: &str, project_id: &str) -> Result<bool, String>;

    /// Whether `user_id` may administer/delete memories within `project_id`.
    async fn can_admin_project(&self, user_id: &str, project_id: &str) -> Result<bool, String>;
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
            return Err(AuthRejection::unauthorized(
                "API key is inactive or expired",
            ));
        }

        // Best-effort audit touch, fired off the request path so the key SELECT
        // is the only round trip the request pays for. Still unconditional —
        // one UPDATE per authenticated request, mirroring the Python auth path —
        // and a failure must never fail the request, so the result stays
        // discarded inside the spawned task.
        let keys = self.keys.clone();
        let api_key_id = record.id.clone();
        tokio::spawn(async move {
            let _ = keys.touch_last_used(&api_key_id).await;
        });

        Ok(Identity {
            user_id: record.user_id,
            _api_key_id: record.id,
        })
    }

    async fn revoke_api_key(&self, raw_key: &str) -> Result<(), AuthRejection> {
        self.keys
            .revoke_by_raw_key(raw_key)
            .await
            .map(|_| ())
            .map_err(|error| AuthRejection {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                detail: error.to_string(),
            })
    }

    async fn can_access_project(&self, user_id: &str, project_id: &str) -> Result<bool, String> {
        match self
            .projects
            .find_by_id(project_id)
            .await
            .map_err(|e| e.to_string())?
        {
            Some(project) => self
                .projects
                .user_can_access(user_id, &project)
                .await
                .map_err(|e| e.to_string()),
            None => Ok(false),
        }
    }

    async fn authorize_project_event_subscription(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<Option<String>, String> {
        let Some(project) = self
            .projects
            .find_by_id(project_id)
            .await
            .map_err(|error| error.to_string())?
        else {
            return Ok(None);
        };
        if tenant_id
            .map(|requested_tenant_id| requested_tenant_id != project.tenant_id)
            .unwrap_or(false)
        {
            return Ok(None);
        }
        if self
            .projects
            .user_can_subscribe_project_events(user_id, &project)
            .await
            .map_err(|error| error.to_string())?
        {
            Ok(Some(project.tenant_id))
        } else {
            Ok(None)
        }
    }

    async fn can_write_project(&self, user_id: &str, project_id: &str) -> Result<bool, String> {
        match self
            .projects
            .find_by_id(project_id)
            .await
            .map_err(|e| e.to_string())?
        {
            Some(project) => self
                .projects
                .user_can_write(user_id, &project)
                .await
                .map_err(|e| e.to_string()),
            None => Ok(false),
        }
    }

    async fn can_admin_project(&self, user_id: &str, project_id: &str) -> Result<bool, String> {
        match self
            .projects
            .find_by_id(project_id)
            .await
            .map_err(|e| e.to_string())?
        {
            Some(project) => self
                .projects
                .user_can_admin(user_id, &project)
                .await
                .map_err(|e| e.to_string()),
            None => Ok(false),
        }
    }
}

/// Shared dev-mode revocation registry used by both device-grant cancellation
/// and request authentication.
#[derive(Clone, Default)]
pub(crate) struct DevApiKeyRevocations {
    revoked_key_hashes: Arc<Mutex<HashSet<[u8; 32]>>>,
}

impl DevApiKeyRevocations {
    pub(crate) fn new() -> Self {
        Self::default()
    }

    pub(crate) fn contains(&self, raw_key: &str) -> Result<bool, String> {
        self.revoked_key_hashes
            .lock()
            .map_err(|_| "API key revocation state unavailable".to_string())
            .map(|hashes| hashes.contains(&api_key_fingerprint(raw_key)))
    }

    pub(crate) fn revoke(&self, raw_key: &str) -> Result<(), String> {
        self.revoked_key_hashes
            .lock()
            .map_err(|_| "API key revocation state unavailable".to_string())?
            .insert(api_key_fingerprint(raw_key));
        Ok(())
    }
}

/// Isolated-test authenticator: accepts any well-formed `ms_sk_` key, maps it to
/// a fixed dev user, and permits every project unless the shared registry has
/// revoked it.
pub struct DevAuthenticator {
    dev_user_id: String,
    revocations: DevApiKeyRevocations,
}

impl DevAuthenticator {
    #[cfg(test)]
    pub fn new(dev_user_id: impl Into<String>) -> Self {
        Self::with_revocations(dev_user_id, DevApiKeyRevocations::new())
    }

    pub(crate) fn with_revocations(
        dev_user_id: impl Into<String>,
        revocations: DevApiKeyRevocations,
    ) -> Self {
        Self {
            dev_user_id: dev_user_id.into(),
            revocations,
        }
    }
}

fn api_key_fingerprint(raw_key: &str) -> [u8; 32] {
    Sha256::digest(raw_key.as_bytes()).into()
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
        let is_revoked = self
            .revocations
            .contains(raw_key)
            .map_err(|detail| AuthRejection {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                detail,
            })?;
        if is_revoked {
            return Err(AuthRejection::unauthorized("Invalid API key"));
        }
        Ok(Identity {
            user_id: self.dev_user_id.clone(),
            _api_key_id: format!("dev_{}", &raw_key[..raw_key.len().min(14)]),
        })
    }

    async fn revoke_api_key(&self, raw_key: &str) -> Result<(), AuthRejection> {
        self.revocations
            .revoke(raw_key)
            .map_err(|detail| AuthRejection {
                status: StatusCode::INTERNAL_SERVER_ERROR,
                detail,
            })
    }

    async fn can_access_project(&self, _user_id: &str, _project_id: &str) -> Result<bool, String> {
        Ok(true)
    }

    async fn authorize_project_event_subscription(
        &self,
        user_id: &str,
        project_id: &str,
        tenant_id: Option<&str>,
    ) -> Result<Option<String>, String> {
        if user_id != self.dev_user_id
            || project_id != "dev-project"
            || tenant_id
                .map(|requested_tenant_id| requested_tenant_id != "dev-tenant")
                .unwrap_or(false)
        {
            return Ok(None);
        }
        Ok(Some("dev-tenant".to_string()))
    }

    async fn can_write_project(&self, _user_id: &str, _project_id: &str) -> Result<bool, String> {
        Ok(true)
    }

    async fn can_admin_project(&self, _user_id: &str, _project_id: &str) -> Result<bool, String> {
        Ok(true)
    }
}

/// Extract the raw key from an `Authorization` header value, applying the same
/// prefix rules as the Python `get_api_key_from_header`.
pub(crate) fn extract_raw_key(authorization: Option<&str>) -> Result<String, AuthRejection> {
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

fn is_sandbox_proxy_path(path: &str) -> bool {
    path.starts_with("/api/v1/projects/") && path.contains("/sandbox/")
}

fn extract_protocol_key(value: &str) -> Option<&str> {
    value
        .split(',')
        .map(str::trim)
        .find(|part| part.starts_with("ms_sk_"))
}

fn extract_query_token(query: Option<&str>) -> Option<&str> {
    query?.split('&').find_map(|pair| {
        let (key, value) = pair.split_once('=')?;
        (key == "token" && value.starts_with("ms_sk_")).then_some(value)
    })
}

fn extract_cookie_token(cookie_header: &str) -> Option<&str> {
    cookie_header.split(';').find_map(|cookie| {
        let (key, value) = cookie.trim().split_once('=')?;
        ((key == "sandbox_proxy_token" || key == "desktop_token") && value.starts_with("ms_sk_"))
            .then_some(value)
    })
}

fn extract_sandbox_proxy_raw_key<T>(request: &Request<T>) -> Option<String> {
    if !is_sandbox_proxy_path(request.uri().path()) {
        return None;
    }

    if let Some(raw) = request
        .headers()
        .get(axum::http::header::SEC_WEBSOCKET_PROTOCOL)
        .and_then(|v| v.to_str().ok())
        .and_then(extract_protocol_key)
    {
        return Some(raw.to_string());
    }

    if let Some(raw) = extract_query_token(request.uri().query()) {
        return Some(raw.to_string());
    }

    request
        .headers()
        .get(axum::http::header::COOKIE)
        .and_then(|v| v.to_str().ok())
        .and_then(extract_cookie_token)
        .map(str::to_string)
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
        Err(rejection) => match extract_sandbox_proxy_raw_key(&request) {
            Some(key) => key,
            None => return rejection.into_response(),
        },
    };

    let now_ms = chrono::Utc::now().timestamp_millis();
    match app.auth.authenticate(&raw_key, now_ms).await {
        Ok(identity) => {
            request.extensions_mut().insert(identity);
            request.extensions_mut().insert(RawApiKey(raw_key));
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
        assert_eq!(
            extract_raw_key(Some("Bearer ms_sk_abc")).unwrap(),
            "ms_sk_abc"
        );
        assert_eq!(
            extract_raw_key(Some("Token ms_sk_abc")).unwrap(),
            "ms_sk_abc"
        );
        assert_eq!(extract_raw_key(Some("ms_sk_abc")).unwrap(), "ms_sk_abc");
    }

    #[test]
    fn extract_rejects_missing_and_malformed() {
        assert_eq!(
            extract_raw_key(None).unwrap_err().status,
            StatusCode::UNAUTHORIZED
        );
        assert_eq!(
            extract_raw_key(Some("Bearer sk-openai"))
                .unwrap_err()
                .status,
            StatusCode::UNAUTHORIZED
        );
    }

    #[tokio::test]
    async fn dev_revoke_is_idempotent_and_does_not_revoke_other_key() {
        let auth = DevAuthenticator::new("dev-user");
        let current_key = "ms_sk_dev_revoke_current";
        let other_key = "ms_sk_dev_revoke_other";

        assert!(auth.authenticate(current_key, 0).await.is_ok());
        assert!(auth.authenticate(other_key, 0).await.is_ok());

        auth.revoke_api_key(current_key).await.unwrap();
        auth.revoke_api_key(current_key).await.unwrap();

        assert!(auth.authenticate(current_key, 0).await.is_err());
        assert!(auth.authenticate(other_key, 0).await.is_ok());
    }

    #[test]
    fn sandbox_proxy_auth_accepts_query_protocol_and_cookies_only_on_sandbox_paths() {
        let request = Request::builder()
            .uri("/api/v1/projects/p1/sandbox/mcp/proxy?token=ms_sk_query")
            .body(())
            .unwrap();
        assert_eq!(
            extract_sandbox_proxy_raw_key(&request).as_deref(),
            Some("ms_sk_query")
        );

        let request = Request::builder()
            .uri("/api/v1/projects/p1/sandbox/mcp/proxy")
            .header("sec-websocket-protocol", "mcp, ms_sk_protocol")
            .body(())
            .unwrap();
        assert_eq!(
            extract_sandbox_proxy_raw_key(&request).as_deref(),
            Some("ms_sk_protocol")
        );

        let request = Request::builder()
            .uri("/api/v1/projects/p1/sandbox/desktop/proxy/app.js")
            .header(
                "cookie",
                "theme=dark; sandbox_proxy_token=ms_sk_cookie; other=1",
            )
            .body(())
            .unwrap();
        assert_eq!(
            extract_sandbox_proxy_raw_key(&request).as_deref(),
            Some("ms_sk_cookie")
        );

        let request = Request::builder()
            .uri("/api/v1/projects/p1")
            .header("cookie", "sandbox_proxy_token=ms_sk_cookie")
            .body(())
            .unwrap();
        assert_eq!(extract_sandbox_proxy_raw_key(&request), None);
    }

    #[tokio::test]
    async fn dev_authenticator_accepts_ms_sk_and_allows_projects() {
        let auth = DevAuthenticator::new("dev-user");
        let id = auth.authenticate("ms_sk_demo", 0).await.unwrap();
        assert_eq!(id.user_id, "dev-user");
        assert!(auth.can_access_project("dev-user", "p1").await.unwrap());
        assert!(auth.can_write_project("dev-user", "p1").await.unwrap());
        assert!(auth.can_admin_project("dev-user", "p1").await.unwrap());
        assert_eq!(
            auth.authorize_project_event_subscription(
                "dev-user",
                "dev-project",
                Some("dev-tenant")
            )
            .await
            .unwrap(),
            Some("dev-tenant".to_string())
        );
        assert_eq!(
            auth.authorize_project_event_subscription(
                "other-user",
                "dev-project",
                Some("dev-tenant")
            )
            .await
            .unwrap(),
            None
        );
        assert_eq!(
            auth.authorize_project_event_subscription(
                "dev-user",
                "dev-project",
                Some("other-tenant")
            )
            .await
            .unwrap(),
            None
        );
        assert!(auth.authenticate("nope", 0).await.is_err());
    }
}
