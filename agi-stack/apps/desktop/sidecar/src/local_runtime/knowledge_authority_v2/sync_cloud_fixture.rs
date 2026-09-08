//! Shared strict mock-cloud enrollment and wire generation condition.
use super::*;
use crate::application_vault::ApplicationCredentialVault;
use crate::trusted_session::{
    TrustedSessionBroker, TrustedSessionCredentialKind, TrustedSessionRecord,
    TrustedSessionRuntimeMode,
};
use axum::{
    extract::Request,
    http::StatusCode,
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};

pub(super) fn generation() -> Value {
    json!({"contract_version":"1.0.0","descriptor":{"profile_id":"cloud-sync-fixture","generation":1,"digest":"ab".repeat(32)}})
}
pub(super) fn enrollment_value() -> Value {
    json!({"contract_version":"1.0.0","tenant_id":"remote-tenant","project_id":"remote-project","actor_id":"remote-actor","enabled":true,"can_enroll":true,"bootstrap_count":0,"next_cursor":0,"replayed":false,"generation":generation()})
}
pub(super) async fn enrollment() -> Json<Value> {
    Json(enrollment_value())
}

pub(super) async fn require_generation(request: Request, next: Next) -> Response {
    let required = request.uri().path().contains("/knowledge-sync/")
        && !request.uri().path().ends_with("/enrollment");
    let header = request
        .headers()
        .get_all(super::trusted_cloud_connection::GENERATION_HEADER);
    if required || header.iter().next().is_some() {
        let values: Vec<_> = header.iter().collect();
        let matches = values.len() == 1
            && serde_json::from_slice::<Value>(values[0].as_bytes())
                .ok()
                .as_ref()
                == Some(&generation());
        if !matches {
            return StatusCode::PRECONDITION_FAILED.into_response();
        }
    }
    next.run(request).await
}

/// Installs only vault authority; production binding tests must use sync-bind.
pub(super) fn install_unbound(
    state: &LocalRuntimeState,
    directory: &TestDirectory,
    base: String,
) -> TrustedSessionBroker {
    let broker = TrustedSessionBroker::native(
        ApplicationCredentialVault::open(&directory.0.join("test-vault")).unwrap(),
    );
    broker
        .save(TrustedSessionRecord {
            version: 1,
            api_base_url: base,
            runtime_mode: TrustedSessionRuntimeMode::Cloud,
            credential_kind: TrustedSessionCredentialKind::CloudBearer,
            credential: "cloud-test-credential".into(),
            expires_at: None,
        })
        .unwrap();
    state
        .platform_plugin_authority_v2
        .install_trusted_sessions(broker.clone());
    broker
}
