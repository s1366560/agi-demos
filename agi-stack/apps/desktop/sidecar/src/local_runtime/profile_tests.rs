//! Launch both process compositions on isolated data and exercise their actual listeners.

use super::*;
use crate::local_runtime::platform_plugin_sync_v2::PlatformPluginAuthorityModeV2;
use crate::plugin_data_plane_credential_v2::PluginDataPlaneCredentialBrokerV2;
use crate::trusted_session::TrustedSessionBroker;

#[tokio::test]
async fn package_host_mounts_diagnostics_and_never_restores_local_business_authority() {
    let directory = std::env::temp_dir().join(format!("package-profile-{}", Uuid::new_v4()));
    let data = directory.join("application");
    let vault = ApplicationCredentialVault::open(&data).unwrap();
    let runtime = LocalRuntimeService::start(
        data,
        directory.join("workspace"),
        vault.clone(),
        None,
        SidecarProfile::default(),
    )
    .await
    .unwrap();
    let reconciler = runtime
        .start_platform_plugin_control_plane_v2(
            TrustedSessionBroker::native(vault.clone()),
            PluginDataPlaneCredentialBrokerV2::native(vault),
        )
        .await
        .unwrap();
    assert_eq!(
        reconciler.selection_snapshot().unwrap().0,
        PlatformPluginAuthorityModeV2::Cloud
    );
    assert!(reconciler
        .select(PlatformPluginAuthorityModeV2::Local)
        .await
        .is_err());
    assert!(runtime
        .state
        .platform_plugin_authority_v2
        .acquire_generation()
        .is_err());
    assert!(!runtime.state.automation_worker_running());
    let http = reqwest::Client::new();
    let status = runtime.status();
    let health = format!("{}/health", status.api_base_url);
    assert_eq!(
        http.get(&health).send().await.unwrap().status(),
        StatusCode::UNAUTHORIZED
    );
    assert_eq!(
        http.get(&health)
            .header("x-agistack-launch", &status.api_token)
            .send()
            .await
            .unwrap()
            .status(),
        StatusCode::NO_CONTENT
    );
    for path in [
        "/api/v1/projects/p/cron-jobs",
        "/api/v1/agent/ws",
        "/mcp/tools/call",
        "/api/v1/projects/p/sandbox/execute",
    ] {
        let response = http
            .post(format!("{}{path}", status.api_base_url))
            .header("x-agistack-launch", &status.api_token)
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::NOT_FOUND, "{path}");
    }
    assert!(runtime
        .configure(serde_json::from_value(json!({"browser_bridge": {}})).unwrap())
        .is_err());
    let working = directory.join("selected");
    assert!(runtime
        .configure(serde_json::from_value(json!({"workspace_root": working})).unwrap())
        .is_ok());
    reconciler.shutdown().await;
    runtime.shutdown().await;
    std::fs::remove_dir_all(directory).unwrap();
}

#[cfg(feature = "legacy-business")]
#[tokio::test]
async fn compat_profile_starts_existing_worker_and_mounts_authenticated_business_routes() {
    let directory = std::env::temp_dir().join(format!("full-profile-{}", Uuid::new_v4()));
    let data = directory.join("application");
    let vault = ApplicationCredentialVault::open(&data).unwrap();
    let runtime = LocalRuntimeService::start(
        data,
        directory.join("workspace"),
        vault,
        None,
        SidecarProfile::Compat,
    )
    .await
    .unwrap();
    assert!(runtime.state.automation_worker_running());
    let status = runtime.status();
    let response = reqwest::Client::new()
        .get(format!(
            "{}/api/v1/projects/p/cron-jobs",
            status.api_base_url
        ))
        .header("x-agistack-launch", status.api_token)
        .send()
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    runtime.shutdown().await;
    std::fs::remove_dir_all(directory).unwrap();
}

#[test]
fn default_control_plane_admits_device_and_cloud_history_only_for_supported_calls() {
    let profile = SidecarProfile::default();
    for command in [
        "device_plugin_manage_v2",
        "local_run_execute",
        "retire_local_workspace_history",
        "trusted_session_clear",
    ] {
        assert!(profile.allows_command(command));
    }
    for command in [
        "mcp_app_operation",
        "browser_bridge_dev_call",
        "computer_use_cloud_v2",
        "audio_sessions_manage_v2",
    ] {
        assert!(!profile.allows_command(command));
        assert!(SidecarProfile::Full.allows_command(command));
    }
}

#[tokio::test]
async fn full_profile_serves_signed_package_routes_and_workspace_core_callbacks() {
    let directory = std::env::temp_dir().join(format!("full-package-profile-{}", Uuid::new_v4()));
    let data = directory.join("application");
    let vault = ApplicationCredentialVault::open(&data).unwrap();
    let runtime = LocalRuntimeService::start(
        data,
        directory.join("workspace"),
        vault.clone(),
        None,
        serde_json::from_value(json!("full")).unwrap(),
    )
    .await
    .unwrap();
    assert!(!runtime.state.automation_worker_running());
    let status = runtime.status();
    let http = reqwest::Client::new();
    for path in [
        "/api/v1/local-plugins/v2/installations",
        "/api/v1/local-plugins/v2/instances",
    ] {
        let response = http
            .get(format!("{}{path}", status.api_base_url))
            .header("x-agistack-launch", &status.api_token)
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::UNAUTHORIZED);
    }
    let reconciler = runtime
        .start_platform_plugin_control_plane_v2(
            TrustedSessionBroker::native(vault.clone()),
            PluginDataPlaneCredentialBrokerV2::native(vault),
        )
        .await
        .unwrap();
    assert_eq!(
        reconciler.selection_snapshot().unwrap().0,
        PlatformPluginAuthorityModeV2::Cloud
    );
    reconciler
        .select(PlatformPluginAuthorityModeV2::Local)
        .await
        .unwrap();
    runtime
        .state
        .session_store
        .seed_test_session("profile-session")
        .unwrap();
    let auth = runtime
        .state
        .session_store
        .validate_session_credential("profile-session", Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let installed = http
        .get(format!(
            "{}/api/v1/local-plugins/v2/installations",
            status.api_base_url
        ))
        .header("x-agistack-launch", &status.api_token)
        .bearer_auth("profile-session")
        .query(&[
            ("tenant_id", auth.workspace.tenant_id),
            ("project_id", auth.workspace.project_id),
        ])
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json::<Value>()
        .await
        .unwrap();
    assert_eq!(installed["installations"], json!([]));
    let callback = http
        .post(format!(
            "{}/internal/v1/workspace-core/agent-registry/resolve",
            status.api_base_url
        ))
        .json(&json!({"tenant_id":"local","project_id":"sample","agent_id":"example"}))
        .send()
        .await
        .unwrap();
    assert_eq!(callback.status(), StatusCode::SERVICE_UNAVAILABLE);
    reconciler.shutdown().await;
    runtime.shutdown().await;
    std::fs::remove_dir_all(directory).unwrap();
}
