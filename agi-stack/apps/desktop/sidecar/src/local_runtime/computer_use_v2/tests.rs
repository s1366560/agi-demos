use super::*;
use api::ManagementRequest;

pub(super) fn owner(state: &LocalRuntimeState) -> Owner {
    Owner {
        user_id: "user".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        device_id: state.session_store.installation_id().into(),
    }
}
fn action(name: &str, revision: Option<u64>) -> ManagementRequest {
    ManagementRequest {
        action: name.into(),
        expected_revision: revision,
        capability: None,
        enabled: None,
        input_mode: None,
        request_id: None,
        scope: None,
        grant_id: None,
        session_id: None,
        recording_id: None,
        artifact_id: None,
        offset: None,
        provider: None,
        client_id: None,
        account_id: None,
    }
}

#[tokio::test]
async fn device_management_defaults_disabled_and_scope_isolated() {
    let state = super::super::tests::test_state("cua-management");
    let owner = owner(&state);
    let initial = api::snapshot(&state, &owner).unwrap();
    assert_eq!(initial["instance"]["installed"], true);
    assert_eq!(initial["instance"]["enabled"], false);
    api::operation(&state, &owner, action("uninstall", Some(0)))
        .await
        .unwrap();
    assert_eq!(
        api::snapshot(&state, &owner).unwrap()["instance"]["installed"],
        false
    );
    let mut other = owner.clone();
    other.user_id = "other-user".into();
    assert_eq!(
        api::snapshot(&state, &other).unwrap()["instance"]["installed"],
        true
    );
    assert!(api::operation(&state, &owner, action("install", Some(0)))
        .await
        .is_err());
}

#[tokio::test]
async fn renderer_cannot_create_grants_without_a_real_pending_request() {
    let state = super::super::tests::test_state("cua-grants");
    let owner = owner(&state);
    let mut input = action("grant", None);
    input.request_id = Some("invented".into());
    input.scope = Some(store::GrantScope::Always);
    assert!(api::operation(&state, &owner, input)
        .await
        .unwrap_err()
        .contains("expired"));
}

#[test]
fn audio_and_locked_capabilities_require_separate_explicit_configuration() {
    let instance = Instance::default();
    assert!(capability_for(
        "computer_audio_start",
        &json!({"source":"microphone"}),
        &instance
    )
    .is_err());
    assert!(capability_for("computer_locked_use", &json!({}), &instance).is_err());
    assert_eq!(
        capability_for("computer_get_app_state", &json!({}), &instance).unwrap(),
        "observe"
    );
}

#[test]
fn launch_binds_installed_identity_and_running_actions_freeze_the_resolved_pid() {
    let installed = json!({"app":"installed:fixture","identity_digest":"binary-fingerprint","app_path":"/managed/Fixture.app","status":"not_running"});
    assert_eq!(
        host::frozen_target("computer_launch_app", &installed, "installed:fixture").unwrap(),
        json!("/managed/Fixture.app")
    );
    assert!(host::frozen_target("computer_click", &installed, "installed:fixture").is_err());
    let running = json!({"app":"fixture","process_id":123,"app_path":"/managed/Fixture.app"});
    assert_eq!(
        host::frozen_target("computer_click", &running, "fixture").unwrap(),
        json!("pid:123")
    );
}
