//! Exercises the real compiled profile and host-qualified Loader, never internal_validation.
use super::*;
use crate::local_runtime::platform_plugin_sync_v2::PlatformPluginControlPlaneReconcilerV2;
use crate::{
    application_vault::ApplicationCredentialVault,
    local_knowledge_acceptance::{self, tests::AcceptanceDirectories},
    plugin_data_plane_credential_v2::PluginDataPlaneCredentialBrokerV2,
};
use axum::{
    body::{to_bytes, Body},
    http::{Request, StatusCode},
};
use tower::ServiceExt;

fn accepted_state(directories: &AcceptanceDirectories) -> Arc<LocalRuntimeState> {
    let mut state = test_state(TOKEN);
    let inner = Arc::get_mut(&mut state).unwrap();
    inner.app_data_dir = Some(directories.data.clone());
    inner.local_knowledge_acceptance = Some(directories.qualification());
    *inner.workspace_root.lock().unwrap() = directories.workspace.clone();
    state
}
async fn start(
    state: Arc<LocalRuntimeState>,
    directories: &AcceptanceDirectories,
) -> PlatformPluginControlPlaneReconcilerV2 {
    let vault = ApplicationCredentialVault::open(&directories.data).unwrap();
    PlatformPluginControlPlaneReconcilerV2::start(
        state,
        PluginDataPlaneCredentialBrokerV2::native(vault),
    )
    .await
    .unwrap()
}
async fn request(
    state: Arc<LocalRuntimeState>,
    path: &str,
    body: Option<Value>,
) -> (StatusCode, Value) {
    let request = Request::builder()
        .uri(path)
        .method(if body.is_some() { "POST" } else { "GET" })
        .header("x-agistack-launch", TOKEN)
        .header("authorization", format!("Bearer {TOKEN}"))
        .header("content-type", "application/json")
        .header("idempotency-key", "acceptance-create")
        .body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))
        .unwrap();
    let response = crate::local_runtime::local_router_with_generation_required(state)
        .oneshot(request)
        .await
        .unwrap();
    let status = response.status();
    let value = serde_json::from_slice(&to_bytes(response.into_body(), usize::MAX).await.unwrap())
        .unwrap_or(Value::Null);
    (status, value)
}
fn scope(state: &LocalRuntimeState) -> Value {
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    json!(operation_scope(&authenticated(state), &lease))
}

#[tokio::test]
async fn qualified_host_publishes_local_actions_and_durable_crud_through_real_loader() {
    let directories = AcceptanceDirectories::new();
    let state = accepted_state(&directories);
    let control = start(state.clone(), &directories).await;
    let observed = request(state.clone(), "/api/v1/knowledge/capabilities", None).await;
    assert_eq!(observed.0, StatusCode::OK);
    assert_eq!(
        observed.1["scope"]["profile_id"],
        local_knowledge_acceptance::PROFILE
    );
    assert_eq!(observed.1["result"]["availability"], "degraded");
    assert_eq!(
        observed.1["result"]["reason_code"],
        "knowledge_local_acceptance_only"
    );
    assert_eq!(observed.1["result"]["provenance"], "observed");
    assert_eq!(
        observed.1["result"]["allowed_actions"],
        json!(super::super::capabilities_generated::LOCAL_ACCEPTANCE_ACTIONS)
    );
    assert!(!directories.data.join("knowledge").exists());
    {
        let lease = state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap();
        let auth = authenticated(&state);
        let authority = lease
            .knowledge_authority(&ScopeV2 {
                kind: ScopeKindV2::Project,
                tenant_id: Some(auth.workspace.tenant_id),
                project_id: Some(auth.workspace.project_id),
                session_id: None,
            })
            .unwrap();
        assert!(
            authority
                .require_profile(
                    &lease.descriptor().profile_id,
                    &lease.descriptor().digest,
                    Some(1)
                )
                .is_err(),
            "a cloud publication cannot reuse host-local acceptance qualification"
        );
    }
    let body = json!({"scope":scope(&state),"mutation":mutation(&authenticated(&state))});
    let created = request(state.clone(), "/api/v1/knowledge/mutations", Some(body)).await;
    assert_eq!(created.0, StatusCode::OK, "{created:?}");
    assert_eq!(created.1["result"]["receipt"]["memory"]["version"], 1);
    assert!(directories.data.join("knowledge/memories.db").exists());
    let configuration = request(
        state.clone(),
        "/api/v1/knowledge/processing-query",
        Some(json!({"scope":scope(&state),"query":{"operation":"configuration"}})),
    )
    .await;
    assert_eq!(configuration.0, StatusCode::OK, "{configuration:?}");
    control.shutdown().await;
    let restarted = start(state.clone(), &directories).await;
    let read = request(
        state.clone(),
        "/api/v1/knowledge/query",
        Some(
            json!({"scope":scope(&state),"query":{"operation":"get","id":"knowledge-test-memory"}}),
        ),
    )
    .await;
    assert_eq!(read.0, StatusCode::OK, "{read:?}");
    assert_eq!(read.1["result"]["memory"]["version"], 1);
    restarted.shutdown().await;
}

#[tokio::test]
async fn local_acceptance_keeps_sync_and_workspace_escape_closed() {
    let directories = AcceptanceDirectories::new();
    let state = accepted_state(&directories);
    let control = start(state.clone(), &directories).await;
    for path in [
        "sync-link",
        "sync-push",
        "sync-pull",
        "sync-resolve-push",
        "sync-resume-resolution",
        "sync-reconcile-resolution",
        "sync-cloud-query",
        "sync-resolve-pull",
    ] {
        let response = request(
            state.clone(),
            &format!("/api/v1/knowledge/{path}"),
            Some(json!({})),
        )
        .await;
        assert_eq!(
            response.0,
            StatusCode::SERVICE_UNAVAILABLE,
            "{path}: {response:?}"
        );
        assert_eq!(response.1["error"]["code"], "knowledge_release_closed");
    }
    let response = request(
        state.clone(),
        "/api/v1/knowledge/query",
        Some(json!({"scope":scope(&state),"query":{"operation":"sync_status"}})),
    )
    .await;
    assert_eq!(response.0, StatusCode::SERVICE_UNAVAILABLE);
    let outside = directories.profile.join("not-the-workspace");
    let config = crate::local_runtime::LocalRuntimeConfig {
        workspace_root: outside.to_string_lossy().into_owned(),
        ..Default::default()
    };
    assert!(state.configure(config, "http://127.0.0.1:1234").is_err());
    assert!(!outside.exists());
    assert_eq!(*state.workspace_root.lock().unwrap(), directories.workspace);
    control.shutdown().await;
}

#[tokio::test]
async fn acceptance_profile_without_host_qualification_is_rejected_before_storage() {
    let directories = AcceptanceDirectories::new();
    let snapshot = parse_profile_snapshot_v2(local_knowledge_acceptance::SNAPSHOT).unwrap();
    let loader = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            definition(Some(directories.data.clone()), None).unwrap(),
        ],
    );
    assert!(loader.stage(snapshot).await.is_err());
    assert!(!directories.data.join("knowledge").exists());
}

#[tokio::test]
async fn late_directory_replacement_revokes_observation_and_storage_access() {
    let directories = AcceptanceDirectories::new();
    let state = accepted_state(&directories);
    let control = start(state.clone(), &directories).await;
    let original_scope = scope(&state);
    let old = directories.profile.join("retired-workspace");
    fs::rename(&directories.workspace, &old).unwrap();
    fs::create_dir(&directories.workspace).unwrap();
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&directories.workspace, fs::Permissions::from_mode(0o700)).unwrap();
    let capability = request(state.clone(), "/api/v1/knowledge/capabilities", None).await;
    assert_eq!(capability.0, StatusCode::CONFLICT);
    let created = request(
        state.clone(),
        "/api/v1/knowledge/mutations",
        Some(json!({"scope":original_scope,"mutation":mutation(&authenticated(&state))})),
    )
    .await;
    assert_eq!(created.0, StatusCode::CONFLICT);
    assert!(!directories.data.join("knowledge").exists());
    control.shutdown().await;
}

#[tokio::test]
async fn host_qualification_cannot_authorize_an_alternate_snapshot_digest() {
    let directories = AcceptanceDirectories::new();
    let state = accepted_state(&directories);
    let mut wire: Value = serde_json::from_str(local_knowledge_acceptance::SNAPSHOT).unwrap();
    wire["generation"] = json!(2);
    wire.as_object_mut().unwrap().remove("digest");
    wire["digest"] = json!(format!(
        "{:x}",
        Sha256::digest(serde_jcs::to_vec(&wire).unwrap())
    ));
    let snapshot = parse_profile_snapshot_v2(&wire.to_string()).unwrap();
    let loader = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            definition(
                Some(directories.data.clone()),
                Some(directories.qualification()),
            )
            .unwrap(),
        ],
    );
    let generation = loader.stage(snapshot.clone()).await.unwrap();
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(&snapshot, &wire, generation)
        .await;
    let capability = request(state.clone(), "/api/v1/knowledge/capabilities", None).await;
    assert_eq!(capability.0, StatusCode::CONFLICT);
    assert!(!directories.data.join("knowledge").exists());
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn ordinary_host_retains_disabled_default_profile_and_no_knowledge_storage() {
    let directories = AcceptanceDirectories::new();
    let mut state = test_state(TOKEN);
    Arc::get_mut(&mut state).unwrap().app_data_dir = Some(directories.data.clone());
    let control = start(state.clone(), &directories).await;
    assert_eq!(scope(&state)["profile_id"], "memstack-default-v2");
    let capability = request(state.clone(), "/api/v1/knowledge/capabilities", None).await;
    assert_eq!(capability.0, StatusCode::SERVICE_UNAVAILABLE);
    assert!(!directories.data.join("knowledge").exists());
    control.shutdown().await;
}

#[tokio::test]
async fn explicit_sync_host_uses_separate_profile_and_requires_exact_cloud_descriptor() {
    let directories = AcceptanceDirectories::new();
    let mut state = accepted_state(&directories);
    Arc::get_mut(&mut state).unwrap().local_knowledge_acceptance =
        Some(directories.sync_qualification());
    let control = start(state.clone(), &directories).await;
    let observed = request(state.clone(), "/api/v1/knowledge/capabilities", None).await;
    assert_eq!(observed.0, StatusCode::OK);
    assert_eq!(
        observed.1["scope"]["profile_id"],
        local_knowledge_acceptance::SYNC_PROFILE
    );
    assert_eq!(
        observed.1["result"]["reason_code"],
        "knowledge_sync_acceptance_only"
    );
    let actions = observed.1["result"]["allowed_actions"].as_array().unwrap();
    assert!(actions.contains(&json!("sync_push")));
    assert!(actions.contains(&json!("sync_pull")));
    let lease = state
        .platform_plugin_authority_v2
        .acquire_generation()
        .unwrap();
    let auth = authenticated(&state);
    let authority = lease
        .knowledge_authority(&ScopeV2 {
            kind: ScopeKindV2::Project,
            tenant_id: Some(auth.workspace.tenant_id),
            project_id: Some(auth.workspace.project_id),
            session_id: None,
        })
        .unwrap();
    authority.require_sync_release().unwrap();
    let cloud: Value =
        serde_json::from_str(local_knowledge_acceptance::CLOUD_SYNC_SNAPSHOT).unwrap();
    authority
        .require_sync_cloud_profile(
            local_knowledge_acceptance::CLOUD_SYNC_PROFILE,
            1,
            cloud["digest"].as_str().unwrap(),
        )
        .unwrap();
    for (profile, digest) in [
        (
            local_knowledge_acceptance::SYNC_PROFILE,
            cloud["digest"].as_str().unwrap(),
        ),
        (
            local_knowledge_acceptance::CLOUD_SYNC_PROFILE,
            "0000000000000000000000000000000000000000000000000000000000000000",
        ),
        (local_knowledge_acceptance::CLOUD_SYNC_PROFILE, "invalid"),
    ] {
        assert!(authority
            .require_sync_cloud_profile(profile, 1, digest)
            .is_err());
    }
    assert!(authority
        .require_profile(
            &lease.descriptor().profile_id,
            &lease.descriptor().digest,
            Some(1)
        )
        .is_err());
    let old = directories.profile.join("retired-workspace");
    fs::rename(&directories.workspace, &old).unwrap();
    fs::create_dir(&directories.workspace).unwrap();
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(&directories.workspace, fs::Permissions::from_mode(0o700)).unwrap();
    assert!(authority.require_sync_release().is_err());
    assert!(authority
        .require_sync_cloud_profile(
            local_knowledge_acceptance::CLOUD_SYNC_PROFILE,
            1,
            cloud["digest"].as_str().unwrap()
        )
        .is_err());
    drop(authority);
    drop(lease);
    control.shutdown().await;
}

#[tokio::test]
async fn sync_profile_requires_matching_host_purpose_before_storage() {
    let directories = AcceptanceDirectories::new();
    for qualification in [None, Some(directories.qualification())] {
        let loader = LoaderV2::for_target(
            DataPlaneTargetV2::DesktopSidecar,
            [
                desktop_sidecar_http_routes_definition_v2(),
                desktop_sidecar_host_definition_v2(),
                definition(Some(directories.data.clone()), qualification).unwrap(),
            ],
        );
        assert!(loader
            .stage(parse_profile_snapshot_v2(local_knowledge_acceptance::SYNC_SNAPSHOT).unwrap())
            .await
            .is_err());
        assert!(!directories.data.join("knowledge").exists());
    }
    let loader = LoaderV2::for_target(
        DataPlaneTargetV2::DesktopSidecar,
        [
            desktop_sidecar_http_routes_definition_v2(),
            desktop_sidecar_host_definition_v2(),
            definition(
                Some(directories.data.clone()),
                Some(directories.sync_qualification()),
            )
            .unwrap(),
        ],
    );
    assert!(loader
        .stage(parse_profile_snapshot_v2(local_knowledge_acceptance::SNAPSHOT).unwrap())
        .await
        .is_err());
}
