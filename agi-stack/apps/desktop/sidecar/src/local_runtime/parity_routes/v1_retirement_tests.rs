use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

const RETIRED_CODE: &str = "plugin_protocol_v1_retired";
const MIGRATION_TARGET: &str = "/api/v1/plugin-marketplace";

fn test_state(credential: &str) -> Arc<LocalRuntimeState> {
    let root: PathBuf =
        std::env::temp_dir().join(format!("agistack-v1-retirement-{}", Uuid::new_v4()));
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root,
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    state
}

fn seed_legacy_plugin_row(state: &LocalRuntimeState) {
    let connection = state
        .session_store
        .connection()
        .expect("legacy plugin registry connection");
    connection
        .execute(
            "INSERT INTO desktop_managed_resources(
               kind, scope_kind, scope_id, id, status, revision,
               created_at_ms, updated_at_ms, value_json, vault_refs_json
             ) VALUES (
               'plugin', 'tenant', 'local', 'custom-plugin', 'active', 0,
               1752384000000, 1752384000000, ?1, '[]'
             )",
            [json!({
                "id": "custom-plugin",
                "name": "Custom plugin",
                "source": "local",
                "enabled": true,
                "status": "active",
            })
            .to_string()],
        )
        .expect("seed retired managed plugin state");
}

fn legacy_plugin_row(state: &LocalRuntimeState) -> Value {
    let connection = state
        .session_store
        .connection()
        .expect("legacy plugin registry connection");
    let raw: String = connection
        .query_row(
            "SELECT value_json FROM desktop_managed_resources
             WHERE kind = 'plugin' AND scope_kind = 'tenant'
               AND scope_id = 'local' AND id = 'custom-plugin'",
            [],
            |row| row.get(0),
        )
        .expect("read retired managed plugin state");
    serde_json::from_str(&raw).expect("legacy plugin JSON")
}

fn request(
    method: Method,
    uri: &str,
    launch_credential: &str,
    bearer: Option<&str>,
) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("x-agistack-launch", launch_credential)
        .header("content-type", "application/json");
    if let Some(bearer) = bearer {
        builder = builder.header("authorization", format!("Bearer {bearer}"));
    }
    builder
        .body(Body::from("{}"))
        .expect("V1 retirement request")
}

async fn json_response(response: axum::response::Response) -> Value {
    let bytes = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response bytes");
    serde_json::from_slice(&bytes).expect("response JSON")
}

fn assert_retired_detail(payload: &Value, message: &str) {
    assert_eq!(
        payload["detail"],
        json!({
            "code": RETIRED_CODE,
            "message": message,
            "migration_target": MIGRATION_TARGET,
        })
    );
}

#[tokio::test]
async fn managed_plugin_v1_routes_are_authenticated_scoped_gone_and_stateless() {
    let credential = "managed-plugin-v1-retirement-secret";
    let state = test_state(credential);
    seed_legacy_plugin_row(&state);
    let before = legacy_plugin_row(&state);
    let app = local_router(Arc::clone(&state));

    let unauthenticated = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/channels/tenants/local/plugins",
            credential,
            None,
        ))
        .await
        .expect("unauthenticated retired plugin response");
    assert_eq!(unauthenticated.status(), StatusCode::UNAUTHORIZED);

    let wrong_scope = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/channels/tenants/orbital/plugins",
            credential,
            Some(credential),
        ))
        .await
        .expect("wrong-scope retired plugin response");
    assert_eq!(wrong_scope.status(), StatusCode::FORBIDDEN);

    for (method, uri) in [
        (Method::GET, "/api/v1/channels/tenants/local/plugins"),
        (
            Method::POST,
            "/api/v1/channels/tenants/local/plugins/install",
        ),
        (
            Method::POST,
            "/api/v1/channels/tenants/local/plugins/reload",
        ),
        (
            Method::POST,
            "/api/v1/channels/tenants/local/plugins/custom-plugin/enable",
        ),
        (
            Method::POST,
            "/api/v1/channels/tenants/local/plugins/custom-plugin/disable",
        ),
        (
            Method::POST,
            "/api/v1/channels/tenants/local/plugins/custom-plugin/uninstall",
        ),
        (
            Method::GET,
            "/api/v1/channels/tenants/local/plugins/custom-plugin/config-schema",
        ),
        (
            Method::GET,
            "/api/v1/channels/tenants/local/plugins/custom-plugin/config",
        ),
        (
            Method::PUT,
            "/api/v1/channels/tenants/local/plugins/custom-plugin/config",
        ),
    ] {
        let response = app
            .clone()
            .oneshot(request(method.clone(), uri, credential, Some(credential)))
            .await
            .expect("retired managed plugin response");
        assert_eq!(response.status(), StatusCode::GONE, "{method} {uri}");
        let payload = json_response(response).await;
        assert_retired_detail(
            &payload,
            "Plugin protocol V1 is retired; use the V2 plugin marketplace",
        );
        assert_eq!(payload.get("items"), None, "{method} {uri} leaked V1 state");
        assert_eq!(payload.get("item"), None, "{method} {uri} leaked V1 state");
    }

    let after = legacy_plugin_row(&state);
    assert_eq!(
        after, before,
        "retired routes must not mutate the V1 registry"
    );
}

#[tokio::test]
async fn channel_catalog_routes_are_not_retired_with_generic_plugin_v1() {
    let credential = "channel-catalog-v2-retention-secret";
    let app = local_router(test_state(credential));

    for uri in [
        "/api/v1/channels/tenants/local/plugins/channel-catalog",
        "/api/v1/channels/tenants/local/plugins/channel-catalog/feishu/schema",
    ] {
        let response = app
            .clone()
            .oneshot(request(Method::GET, uri, credential, Some(credential)))
            .await
            .expect("channel catalog response");
        assert_eq!(response.status(), StatusCode::NOT_IMPLEMENTED, "{uri}");
        let payload = json_response(response).await;
        assert_eq!(
            payload["reason_code"],
            "local_channel_runtime_not_applicable"
        );
        assert_ne!(payload["detail"]["code"], RETIRED_CODE);
    }
}

#[tokio::test]
async fn platform_plugin_v1_catch_all_is_authenticated_gone_and_excludes_v2() {
    let credential = "platform-plugin-v1-retirement-secret";
    let app = local_router(test_state(credential));

    let unauthenticated = app
        .clone()
        .oneshot(request(
            Method::GET,
            "/api/v1/platform-plugins/snapshot",
            credential,
            None,
        ))
        .await
        .expect("unauthenticated V1 control-plane response");
    assert_eq!(unauthenticated.status(), StatusCode::UNAUTHORIZED);

    for (method, uri) in [
        (Method::GET, "/api/v1/platform-plugins"),
        (Method::GET, "/api/v1/platform-plugins/snapshot"),
        (Method::POST, "/api/v1/platform-plugins/snapshot"),
        (Method::GET, "/api/v1/platform-plugins/apply-state"),
        (Method::POST, "/api/v1/platform-plugins/ack"),
        (Method::POST, "/api/v1/platform-plugins/nack"),
        (Method::POST, "/api/v1/platform-plugins/tools/invoke"),
        (
            Method::GET,
            "/api/v1/platform-plugins/frontend/example/module",
        ),
        (
            Method::PATCH,
            "/api/v1/platform-plugins/unknown/legacy/path",
        ),
    ] {
        let response = app
            .clone()
            .oneshot(request(method.clone(), uri, credential, Some(credential)))
            .await
            .expect("retired V1 control-plane response");
        assert_eq!(response.status(), StatusCode::GONE, "{method} {uri}");
        assert_retired_detail(
            &json_response(response).await,
            "Plugin protocol V1 is retired; use the V2 plugin control plane",
        );
    }

    for (method, uri) in [
        (Method::GET, "/api/v1/platform-plugins/v2/distribution"),
        (Method::POST, "/api/v1/platform-plugins/v2/data-plane-state"),
        (Method::GET, "/api/v1/platform-plugins/v2/unknown"),
    ] {
        let response = app
            .clone()
            .oneshot(request(method.clone(), uri, credential, Some(credential)))
            .await
            .expect("V2 control-plane exclusion response");
        assert_ne!(response.status(), StatusCode::GONE, "{method} {uri}");
    }
}
