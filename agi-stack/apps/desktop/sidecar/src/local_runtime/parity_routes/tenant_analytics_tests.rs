use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
};
use serde_json::Value;
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;

const ACTIVE_TENANT_ID: &str = "northstar";

struct AnalyticsTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for AnalyticsTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(launch_credential: &str) -> AnalyticsTestRuntime {
    let root = std::env::temp_dir().join(format!("agistack-tenant-analytics-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create analytics workspace");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            LocalToolHost::new(&root).expect("tool host"),
            Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints")),
            launch_credential.to_string(),
            DesktopSessionStore::in_memory().expect("session store"),
        )
        .expect("local runtime state"),
    );
    AnalyticsTestRuntime { root, state }
}

fn create_session(state: &super::super::LocalRuntimeState) -> String {
    state
        .session_store
        .create_local_session(
            format!("parity-session-{}", uuid::Uuid::new_v4()),
            false,
            chrono::Utc::now().timestamp_millis(),
        )
        .expect("create session")
        .access_token
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("response body");
    serde_json::from_slice(&body).expect("response JSON")
}

fn request(
    uri: &str,
    launch_credential: Option<&str>,
    session_credential: Option<&str>,
) -> Request<Body> {
    let mut builder = Request::builder().uri(uri);
    if let Some(credential) = launch_credential {
        builder = builder.header("x-agistack-launch", credential);
    }
    if let Some(credential) = session_credential {
        builder = builder.header("authorization", format!("Bearer {credential}"));
    }
    builder.body(Body::empty()).expect("analytics request")
}

#[tokio::test]
async fn tenant_analytics_returns_project_totals_and_structured_memory_unavailability() {
    let launch = "tenant-analytics-launch";
    let runtime = test_runtime(launch);
    let app = local_router(Arc::clone(&runtime.state));
    let session = create_session(&runtime.state);
    let uri = format!("/api/v1/tenants/{ACTIVE_TENANT_ID}/analytics?period=30d");

    let missing_launch = app
        .clone()
        .oneshot(request(&uri, None, Some(&session)))
        .await
        .expect("missing launch response");
    assert_eq!(missing_launch.status(), StatusCode::UNAUTHORIZED);

    let response = app
        .clone()
        .oneshot(request(&uri, Some(launch), Some(&session)))
        .await
        .expect("analytics response");
    assert_eq!(response.status(), StatusCode::OK);
    let payload = response_json(response).await;
    assert_eq!(payload["capability"], "tenant_analytics");
    assert_eq!(payload["availability"], "degraded");
    assert_eq!(payload["scope"]["tenant_id"], ACTIVE_TENANT_ID);
    assert_eq!(payload["summary"]["period_days"], 30);
    assert!(payload["summary"]["total_projects"]["value"]
        .as_u64()
        .is_some_and(|count| count >= 1));
    assert_eq!(
        payload["summary"]["total_memories"]["reason_code"],
        "local_tenant_memory_projection_unavailable"
    );
    assert_eq!(
        payload["summary"]["total_storage_bytes"]["reason_code"],
        "local_tenant_storage_projection_unavailable"
    );
    assert_eq!(
        payload["projectStorage"]["value"][0]["storage_bytes"]["reason_code"],
        "local_project_storage_projection_unavailable"
    );

    let short_period = app
        .clone()
        .oneshot(request(
            &format!("/api/v1/tenants/{ACTIVE_TENANT_ID}/analytics?period=7d"),
            Some(launch),
            Some(&session),
        ))
        .await
        .expect("short period response");
    assert_eq!(
        response_json(short_period).await["summary"]["period_days"],
        7
    );

    let invalid_query = app
        .oneshot(request(
            &format!("/api/v1/tenants/{ACTIVE_TENANT_ID}/analytics?period=14d"),
            Some(launch),
            Some(&session),
        ))
        .await
        .expect("invalid query response");
    assert_eq!(invalid_query.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        response_json(invalid_query).await["reason_code"],
        "local_tenant_analytics_query_invalid"
    );
}
