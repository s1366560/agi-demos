//! Cloud-authoritative protocol-v2 plugin marketplace routes.

use std::{sync::Arc, time::Duration};

use axum::{
    extract::{Extension, OriginalUri, Path, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use url::Url;

use super::{
    ensure_managed_resource_manager, ensure_tenant_scope,
    platform_plugin_sync_v2::{control_plane_url, load_cloud_authority, CloudAuthorityV2},
    AuthenticatedContext, LocalRuntimeState,
};

const REQUEST_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_MARKETPLACE_RESPONSE_BYTES: usize = 4 * 1024 * 1024;
const CLOUD_AUTHORITY_UNAVAILABLE: &str = "plugin_marketplace_v2_cloud_authority_unavailable";
const UPSTREAM_UNAVAILABLE: &str = "plugin_marketplace_v2_upstream_unavailable";
const UPSTREAM_INVALID_RESPONSE: &str = "plugin_marketplace_v2_upstream_invalid_response";

type MarketplaceResult = Result<Response, (StatusCode, Json<Value>)>;

#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct MarketplaceUninstallRequestV2 {
    tenant_id: String,
    version: String,
}

enum ExpectedResponse<'a> {
    PackageList,
    Uninstall {
        plugin_id: &'a str,
        version: &'a str,
    },
}

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/plugin-marketplace/packages", get(list_packages))
        .route(
            "/api/v1/plugin-marketplace/packages/:plugin_id/uninstall",
            post(uninstall_package),
        )
}

async fn list_packages(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(_authenticated): Extension<AuthenticatedContext>,
    OriginalUri(uri): OriginalUri,
) -> MarketplaceResult {
    let authority = cloud_authority(&state)?;
    let mut url = control_plane_url(&authority.base_url, "plugin-marketplace/packages");
    url.set_query(uri.query());
    let response = marketplace_client()?
        .get(url)
        .bearer_auth(authority.credential)
        .send()
        .await
        .map_err(|_| {
            marketplace_error(
                StatusCode::BAD_GATEWAY,
                UPSTREAM_UNAVAILABLE,
                "The protocol-v2 cloud marketplace is unavailable",
            )
        })?;
    cloud_json_response(response, ExpectedResponse::PackageList).await
}

async fn uninstall_package(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(plugin_id): Path<String>,
    Json(request): Json<MarketplaceUninstallRequestV2>,
) -> MarketplaceResult {
    ensure_tenant_scope(&authenticated, Some(&request.tenant_id))?;
    ensure_managed_resource_manager(&authenticated)?;
    validate_uninstall_request(&plugin_id, &request)?;
    let authority = cloud_authority(&state)?;
    let url = uninstall_url(&authority.base_url, &plugin_id)?;
    let response = marketplace_client()?
        .post(url)
        .bearer_auth(authority.credential)
        .json(&request)
        .send()
        .await
        .map_err(|_| {
            marketplace_error(
                StatusCode::BAD_GATEWAY,
                UPSTREAM_UNAVAILABLE,
                "The protocol-v2 cloud marketplace is unavailable",
            )
        })?;
    cloud_json_response(
        response,
        ExpectedResponse::Uninstall {
            plugin_id: &plugin_id,
            version: &request.version,
        },
    )
    .await
}

fn cloud_authority(
    state: &LocalRuntimeState,
) -> Result<CloudAuthorityV2, (StatusCode, Json<Value>)> {
    let trusted_sessions = state
        .platform_plugin_authority_v2
        .trusted_sessions()
        .ok_or_else(cloud_authority_unavailable)?;
    load_cloud_authority(&trusted_sessions)
        .map_err(|_| cloud_authority_unavailable())?
        .ok_or_else(cloud_authority_unavailable)
}

fn marketplace_client() -> Result<reqwest::Client, (StatusCode, Json<Value>)> {
    reqwest::Client::builder()
        .timeout(REQUEST_TIMEOUT)
        .build()
        .map_err(|_| {
            marketplace_error(
                StatusCode::SERVICE_UNAVAILABLE,
                CLOUD_AUTHORITY_UNAVAILABLE,
                "The protocol-v2 cloud marketplace authority is unavailable",
            )
        })
}

fn uninstall_url(base_url: &Url, plugin_id: &str) -> Result<Url, (StatusCode, Json<Value>)> {
    let mut url = control_plane_url(base_url, "plugin-marketplace/packages");
    url.path_segments_mut()
        .map_err(|_| {
            marketplace_error(
                StatusCode::SERVICE_UNAVAILABLE,
                CLOUD_AUTHORITY_UNAVAILABLE,
                "The protocol-v2 cloud marketplace authority is unavailable",
            )
        })?
        .push(plugin_id)
        .push("uninstall");
    Ok(url)
}

fn validate_uninstall_request(
    plugin_id: &str,
    request: &MarketplaceUninstallRequestV2,
) -> Result<(), (StatusCode, Json<Value>)> {
    if plugin_id.is_empty()
        || plugin_id.len() > 255
        || request.tenant_id.is_empty()
        || request.tenant_id.len() > 255
        || request.version.is_empty()
        || request.version.len() > 255
        || plugin_id != plugin_id.trim()
        || request.tenant_id != request.tenant_id.trim()
        || request.version != request.version.trim()
    {
        return Err(marketplace_error(
            StatusCode::UNPROCESSABLE_ENTITY,
            "plugin_marketplace_v2_uninstall_request_invalid",
            "Plugin ID, tenant ID, and exact version must be non-empty bounded values",
        ));
    }
    Ok(())
}

async fn cloud_json_response(
    response: reqwest::Response,
    expected: ExpectedResponse<'_>,
) -> MarketplaceResult {
    let status = StatusCode::from_u16(response.status().as_u16()).map_err(|_| {
        marketplace_error(
            StatusCode::BAD_GATEWAY,
            UPSTREAM_INVALID_RESPONSE,
            "The protocol-v2 cloud marketplace returned an invalid status",
        )
    })?;
    let bytes = bounded_response_bytes(response).await?;
    let payload: Value = serde_json::from_slice(&bytes).map_err(|_| {
        marketplace_error(
            StatusCode::BAD_GATEWAY,
            UPSTREAM_INVALID_RESPONSE,
            "The protocol-v2 cloud marketplace returned invalid JSON",
        )
    })?;
    if status.is_success() {
        validate_success_payload(&payload, expected)?;
    }
    Ok((status, Json(payload)).into_response())
}

async fn bounded_response_bytes(
    response: reqwest::Response,
) -> Result<Vec<u8>, (StatusCode, Json<Value>)> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_MARKETPLACE_RESPONSE_BYTES as u64)
    {
        return Err(response_too_large());
    }
    let mut stream = response.bytes_stream();
    let mut bytes = Vec::new();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| {
            marketplace_error(
                StatusCode::BAD_GATEWAY,
                UPSTREAM_INVALID_RESPONSE,
                "The protocol-v2 cloud marketplace response could not be read",
            )
        })?;
        if bytes.len().saturating_add(chunk.len()) > MAX_MARKETPLACE_RESPONSE_BYTES {
            return Err(response_too_large());
        }
        bytes.extend_from_slice(&chunk);
    }
    Ok(bytes)
}

fn validate_success_payload(
    payload: &Value,
    expected: ExpectedResponse<'_>,
) -> Result<(), (StatusCode, Json<Value>)> {
    let valid = match expected {
        ExpectedResponse::PackageList => payload.is_array(),
        ExpectedResponse::Uninstall { plugin_id, version } => {
            payload.get("plugin_id").and_then(Value::as_str) == Some(plugin_id)
                && payload.get("version").and_then(Value::as_str) == Some(version)
                && payload.get("status").and_then(Value::as_str) == Some("uninstalled")
                && payload
                    .get("desired_removed")
                    .and_then(Value::as_bool)
                    .is_some()
                && payload
                    .get("revoked_permissions")
                    .and_then(Value::as_u64)
                    .is_some()
        }
    };
    if valid {
        return Ok(());
    }
    Err(marketplace_error(
        StatusCode::BAD_GATEWAY,
        UPSTREAM_INVALID_RESPONSE,
        "The protocol-v2 cloud marketplace response violated its contract",
    ))
}

fn response_too_large() -> (StatusCode, Json<Value>) {
    marketplace_error(
        StatusCode::BAD_GATEWAY,
        UPSTREAM_INVALID_RESPONSE,
        "The protocol-v2 cloud marketplace response exceeded its size limit",
    )
}

fn cloud_authority_unavailable() -> (StatusCode, Json<Value>) {
    marketplace_error(
        StatusCode::SERVICE_UNAVAILABLE,
        CLOUD_AUTHORITY_UNAVAILABLE,
        "The protocol-v2 cloud marketplace authority is unavailable",
    )
}

fn marketplace_error(
    status: StatusCode,
    code: &'static str,
    message: &'static str,
) -> (StatusCode, Json<Value>) {
    (
        status,
        Json(json!({
            "detail": {
                "code": code,
                "message": message,
            },
        })),
    )
}

#[cfg(test)]
mod tests {
    use std::{
        path::PathBuf,
        sync::{Arc, Mutex},
    };

    use axum::{
        body::Body,
        extract::{OriginalUri, Path, State},
        http::{header::AUTHORIZATION, HeaderMap, Method, Request, StatusCode},
        routing::{get, post},
        Json, Router,
    };
    use serde_json::{json, Value};
    use tokio::{net::TcpListener, sync::oneshot, task::JoinHandle};
    use tower::ServiceExt;
    use uuid::Uuid;

    use crate::trusted_session::{
        TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
        TrustedSessionRuntimeMode, TrustedSessionStore, TrustedSessionStoreError,
    };

    use super::super::*;

    #[derive(Clone, Debug, Eq, PartialEq)]
    struct CloudRequest {
        method: Method,
        path: String,
        query: Option<String>,
        authorization: Option<String>,
        plugin_id: Option<String>,
        body: Option<Value>,
    }

    #[derive(Clone)]
    struct MockCloud {
        requests: Arc<Mutex<Vec<CloudRequest>>>,
        list_status: StatusCode,
        list_body: Value,
        uninstall_status: StatusCode,
        uninstall_body: Value,
    }

    impl MockCloud {
        fn requests(&self) -> Vec<CloudRequest> {
            self.requests
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone()
        }

        fn record(&self, request: CloudRequest) {
            self.requests
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .push(request);
        }
    }

    #[derive(Default)]
    struct InMemoryTrustedSessionStore {
        raw: Mutex<Option<String>>,
    }

    impl TrustedSessionStore for InMemoryTrustedSessionStore {
        fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
            *self
                .raw
                .lock()
                .map_err(|_| TrustedSessionStoreError::Unavailable)? = Some(value.to_string());
            Ok(())
        }

        fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
            self.raw
                .lock()
                .map(|raw| raw.clone())
                .map_err(|_| TrustedSessionStoreError::Unavailable)
        }

        fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
            self.raw
                .lock()
                .map(|mut raw| raw.take())
                .map(|_| ())
                .map_err(|_| TrustedSessionStoreError::Unavailable)
        }
    }

    async fn list_packages(
        State(cloud): State<MockCloud>,
        OriginalUri(uri): OriginalUri,
        headers: HeaderMap,
    ) -> (StatusCode, Json<Value>) {
        cloud.record(CloudRequest {
            method: Method::GET,
            path: uri.path().to_string(),
            query: uri.query().map(str::to_string),
            authorization: authorization(&headers),
            plugin_id: None,
            body: None,
        });
        (cloud.list_status, Json(cloud.list_body.clone()))
    }

    async fn uninstall_package(
        State(cloud): State<MockCloud>,
        OriginalUri(uri): OriginalUri,
        Path(plugin_id): Path<String>,
        headers: HeaderMap,
        Json(body): Json<Value>,
    ) -> (StatusCode, Json<Value>) {
        cloud.record(CloudRequest {
            method: Method::POST,
            path: uri.path().to_string(),
            query: uri.query().map(str::to_string),
            authorization: authorization(&headers),
            plugin_id: Some(plugin_id),
            body: Some(body),
        });
        (cloud.uninstall_status, Json(cloud.uninstall_body.clone()))
    }

    fn authorization(headers: &HeaderMap) -> Option<String> {
        headers
            .get(AUTHORIZATION)
            .and_then(|value| value.to_str().ok())
            .map(str::to_string)
    }

    async fn spawn_cloud(
        list_status: StatusCode,
        list_body: Value,
        uninstall_status: StatusCode,
        uninstall_body: Value,
    ) -> (String, MockCloud, oneshot::Sender<()>, JoinHandle<()>) {
        let cloud = MockCloud {
            requests: Arc::new(Mutex::new(Vec::new())),
            list_status,
            list_body,
            uninstall_status,
            uninstall_body,
        };
        let app = Router::new()
            .route(
                "/control/api/v1/plugin-marketplace/packages",
                get(list_packages),
            )
            .route(
                "/control/api/v1/plugin-marketplace/packages/:plugin_id/uninstall",
                post(uninstall_package),
            )
            .with_state(cloud.clone());
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("mock cloud listener");
        let address = listener.local_addr().expect("mock cloud address");
        let (shutdown, shutdown_rx) = oneshot::channel();
        let task = tokio::spawn(async move {
            axum::serve(listener, app)
                .with_graceful_shutdown(async {
                    let _ = shutdown_rx.await;
                })
                .await
                .expect("mock cloud server");
        });
        (format!("http://{address}/control"), cloud, shutdown, task)
    }

    fn test_state(local_credential: &str, cloud: Option<(&str, &str)>) -> Arc<LocalRuntimeState> {
        let root: PathBuf =
            std::env::temp_dir().join(format!("agistack-plugin-marketplace-v2-{}", Uuid::new_v4()));
        let tool_host = LocalToolHost::new(&root).expect("tool host");
        let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
        let session_store = DesktopSessionStore::in_memory().expect("session store");
        let state = Arc::new(
            LocalRuntimeState::new(
                root,
                tool_host,
                checkpoints,
                local_credential.to_string(),
                session_store,
            )
            .expect("local runtime state"),
        );
        state
            .session_store
            .seed_test_session(local_credential)
            .expect("authenticated local session");
        if let Some((base_url, cloud_credential)) = cloud {
            let broker =
                TrustedSessionBroker::new(Arc::new(InMemoryTrustedSessionStore::default()));
            broker
                .save(TrustedSessionRecord {
                    version: 1,
                    api_base_url: base_url.to_string(),
                    runtime_mode: TrustedSessionRuntimeMode::Cloud,
                    credential_kind: TrustedSessionCredentialKind::CloudBearer,
                    credential: cloud_credential.to_string(),
                    expires_at: None,
                })
                .expect("trusted cloud session");
            state
                .platform_plugin_authority_v2
                .install_trusted_sessions(broker);
        }
        state
    }

    fn request(
        method: Method,
        uri: &str,
        launch_credential: &str,
        local_bearer: Option<&str>,
        body: Option<Value>,
    ) -> Request<Body> {
        let mut builder = Request::builder()
            .method(method)
            .uri(uri)
            .header("x-agistack-launch", launch_credential);
        if let Some(local_bearer) = local_bearer {
            builder = builder.header(AUTHORIZATION, format!("Bearer {local_bearer}"));
        }
        if body.is_some() {
            builder = builder.header("content-type", "application/json");
        }
        builder
            .body(Body::from(
                body.map_or_else(String::new, |body| body.to_string()),
            ))
            .expect("marketplace request")
    }

    async fn response_json(response: axum::response::Response) -> Value {
        let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
            .await
            .expect("marketplace response body");
        serde_json::from_slice(&bytes).expect("marketplace response JSON")
    }

    fn seed_legacy_plugin_row(state: &LocalRuntimeState) -> String {
        let value = json!({
            "id": "legacy-marketplace-plugin",
            "enabled": true,
            "source": "sqlite-v1",
        })
        .to_string();
        state
            .session_store
            .connection()
            .expect("legacy registry connection")
            .execute(
                "INSERT INTO desktop_managed_resources(
                   kind, scope_kind, scope_id, id, status, revision,
                   created_at_ms, updated_at_ms, value_json, vault_refs_json
                 ) VALUES (
                   'plugin', 'tenant', 'local', 'legacy-marketplace-plugin', 'active', 0,
                   1752384000000, 1752384000000, ?1, '[]'
                 )",
                [value.as_str()],
            )
            .expect("seed inert legacy plugin row");
        value
    }

    fn legacy_plugin_row(state: &LocalRuntimeState) -> String {
        state
            .session_store
            .connection()
            .expect("legacy registry connection")
            .query_row(
                "SELECT value_json FROM desktop_managed_resources
                 WHERE kind = 'plugin' AND id = 'legacy-marketplace-plugin'",
                [],
                |row| row.get(0),
            )
            .expect("read inert legacy plugin row")
    }

    #[tokio::test]
    async fn list_is_authenticated_and_forwards_the_raw_query_and_cloud_array() {
        let local_credential = "local-marketplace-session";
        let cloud_credential = "trusted-cloud-bearer";
        let listing = json!([
            {
                "plugin_id": "local-workspace",
                "version": "2.4.1",
                "revoked": false,
            },
            {
                "plugin_id": "audit-export",
                "version": "3.0.0",
                "revoked": true,
            },
        ]);
        let (base_url, cloud, shutdown, task) =
            spawn_cloud(StatusCode::OK, listing.clone(), StatusCode::OK, json!({})).await;
        let state = test_state(
            local_credential,
            Some((base_url.as_str(), cloud_credential)),
        );
        let app = local_router(state);

        let unauthenticated = app
            .clone()
            .oneshot(request(
                Method::GET,
                "/api/v1/plugin-marketplace/packages?include_revoked=true",
                local_credential,
                None,
                None,
            ))
            .await
            .expect("unauthenticated marketplace response");
        assert_eq!(unauthenticated.status(), StatusCode::UNAUTHORIZED);

        let response = app
            .oneshot(request(
                Method::GET,
                "/api/v1/plugin-marketplace/packages?include_revoked=true&cursor=a%2Fb",
                local_credential,
                Some(local_credential),
                None,
            ))
            .await
            .expect("marketplace listing response");

        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response_json(response).await, listing);
        assert_eq!(
            cloud.requests(),
            vec![CloudRequest {
                method: Method::GET,
                path: "/control/api/v1/plugin-marketplace/packages".to_string(),
                query: Some("include_revoked=true&cursor=a%2Fb".to_string()),
                authorization: Some(format!("Bearer {cloud_credential}")),
                plugin_id: None,
                body: None,
            }]
        );
        let _ = shutdown.send(());
        task.await.expect("mock cloud task");
    }

    #[tokio::test]
    async fn uninstall_enforces_scope_and_manager_then_forwards_exact_path_and_body() {
        let local_credential = "local-marketplace-manager";
        let cloud_credential = "trusted-cloud-uninstall-bearer";
        let result = json!({
            "plugin_id": "local-workspace",
            "version": "2.4.1",
            "status": "uninstalled",
            "desired_removed": true,
            "revoked_permissions": 3,
        });
        let (base_url, cloud, shutdown, task) =
            spawn_cloud(StatusCode::OK, json!([]), StatusCode::OK, result.clone()).await;
        let state = test_state(
            local_credential,
            Some((base_url.as_str(), cloud_credential)),
        );
        let app = local_router(Arc::clone(&state));
        let path = "/api/v1/plugin-marketplace/packages/local-workspace/uninstall";

        let wrong_scope = app
            .clone()
            .oneshot(request(
                Method::POST,
                path,
                local_credential,
                Some(local_credential),
                Some(json!({"tenant_id": "northstar", "version": "2.4.1"})),
            ))
            .await
            .expect("wrong-scope uninstall response");
        assert_eq!(wrong_scope.status(), StatusCode::FORBIDDEN);
        assert!(cloud.requests().is_empty());

        let response = app
            .clone()
            .oneshot(request(
                Method::POST,
                path,
                local_credential,
                Some(local_credential),
                Some(json!({"tenant_id": "local", "version": "2.4.1"})),
            ))
            .await
            .expect("marketplace uninstall response");
        assert_eq!(response.status(), StatusCode::OK);
        assert_eq!(response_json(response).await, result);
        assert_eq!(
            cloud.requests(),
            vec![CloudRequest {
                method: Method::POST,
                path: "/control/api/v1/plugin-marketplace/packages/local-workspace/uninstall"
                    .to_string(),
                query: None,
                authorization: Some(format!("Bearer {cloud_credential}")),
                plugin_id: Some("local-workspace".to_string()),
                body: Some(json!({"tenant_id": "local", "version": "2.4.1"})),
            }]
        );

        state
            .session_store
            .connection()
            .expect("membership connection")
            .execute(
                "UPDATE desktop_tenant_memberships SET role = 'member'
                 WHERE tenant_id = 'local'",
                [],
            )
            .expect("downgrade local membership");
        let member = app
            .oneshot(request(
                Method::POST,
                path,
                local_credential,
                Some(local_credential),
                Some(json!({"tenant_id": "local", "version": "2.4.1"})),
            ))
            .await
            .expect("member uninstall response");
        assert_eq!(member.status(), StatusCode::FORBIDDEN);
        assert_eq!(cloud.requests().len(), 1);
        let _ = shutdown.send(());
        task.await.expect("mock cloud task");
    }

    #[tokio::test]
    async fn missing_cloud_authority_is_structured_unavailable_and_never_reads_v1_sqlite() {
        let credential = "local-marketplace-without-cloud";
        let state = test_state(credential, None);
        let legacy = seed_legacy_plugin_row(&state);
        let app = local_router(Arc::clone(&state));

        for (method, uri, body) in [
            (
                Method::GET,
                "/api/v1/plugin-marketplace/packages?include_revoked=true",
                None,
            ),
            (
                Method::POST,
                "/api/v1/plugin-marketplace/packages/legacy-marketplace-plugin/uninstall",
                Some(json!({"tenant_id": "local", "version": "1.0.0"})),
            ),
        ] {
            let response = app
                .clone()
                .oneshot(request(method, uri, credential, Some(credential), body))
                .await
                .expect("cloud-authority unavailable response");
            assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
            let payload = response_json(response).await;
            assert_eq!(
                payload["detail"]["code"],
                "plugin_marketplace_v2_cloud_authority_unavailable"
            );
            assert_eq!(payload.get("items"), None);
        }
        assert_eq!(legacy_plugin_row(&state), legacy);
    }

    #[tokio::test]
    async fn upstream_failure_is_forwarded_without_mutating_v1_sqlite() {
        let local_credential = "local-marketplace-upstream-failure";
        let upstream_failure = json!({"detail": "cloud control plane unavailable"});
        let (base_url, cloud, shutdown, task) = spawn_cloud(
            StatusCode::SERVICE_UNAVAILABLE,
            upstream_failure.clone(),
            StatusCode::BAD_GATEWAY,
            json!({"detail": "publication failed"}),
        )
        .await;
        let state = test_state(local_credential, Some((base_url.as_str(), "cloud-bearer")));
        let legacy = seed_legacy_plugin_row(&state);
        let app = local_router(Arc::clone(&state));

        let response = app
            .oneshot(request(
                Method::GET,
                "/api/v1/plugin-marketplace/packages?include_revoked=true",
                local_credential,
                Some(local_credential),
                None,
            ))
            .await
            .expect("upstream failure response");
        assert_eq!(response.status(), StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(response_json(response).await, upstream_failure);
        assert_eq!(legacy_plugin_row(&state), legacy);
        assert_eq!(cloud.requests().len(), 1);
        let _ = shutdown.send(());
        task.await.expect("mock cloud task");
    }

    #[tokio::test]
    async fn transport_failure_is_structured_and_never_falls_back_to_v1_sqlite() {
        let listener =
            std::net::TcpListener::bind("127.0.0.1:0").expect("reserve unavailable cloud port");
        let address = listener.local_addr().expect("unavailable cloud address");
        drop(listener);
        let local_credential = "local-marketplace-transport-failure";
        let base_url = format!("http://{address}/control");
        let state = test_state(
            local_credential,
            Some((base_url.as_str(), "cloud-transport-bearer")),
        );
        let legacy = seed_legacy_plugin_row(&state);

        let response = local_router(Arc::clone(&state))
            .oneshot(request(
                Method::POST,
                "/api/v1/plugin-marketplace/packages/legacy-marketplace-plugin/uninstall",
                local_credential,
                Some(local_credential),
                Some(json!({"tenant_id": "local", "version": "1.0.0"})),
            ))
            .await
            .expect("transport failure response");

        assert_eq!(response.status(), StatusCode::BAD_GATEWAY);
        let payload = response_json(response).await;
        assert_eq!(
            payload["detail"]["code"],
            "plugin_marketplace_v2_upstream_unavailable"
        );
        assert_eq!(legacy_plugin_row(&state), legacy);
    }
}
