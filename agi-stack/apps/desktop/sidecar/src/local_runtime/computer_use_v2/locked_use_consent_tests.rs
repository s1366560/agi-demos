//! Exact native approval for each new locked-use execution, using private mock IPC only.
use super::*;
use crate::local_runtime::execution_authority;
use agistack_core::ports::{PermissionKind, ToolResult};
use std::time::Duration;

async fn locked_call(host: &dyn ToolHost, engine: &str, round: u64) -> ToolResult {
    locked_input(host, engine, round, json!({"enabled":true}))
        .await
        .unwrap()
}

async fn locked_input(
    host: &dyn ToolHost,
    engine: &str,
    round: u64,
    input: Value,
) -> CoreResult<ToolResult> {
    let context = ToolPolicyContext {
        session_id: engine,
        round,
        tool: "computer_locked_use",
    };
    call_identity::scope(
        &context,
        host.call_with_content(context.tool, &input.to_string()),
    )
    .await
}

async fn locked_fixture() -> Fixture {
    let fixture = Fixture::new().await;
    for request in [
        json!({"action":"locked_use_install","expected_revision":1}),
        json!({"action":"configure","capability":"locked_use","enabled":true,"expected_revision":1}),
    ] {
        api::operation(
            &fixture.state,
            &fixture.owner,
            serde_json::from_value(request).unwrap(),
        )
        .await
        .unwrap();
    }
    fixture
}

fn run_authorization(
    fixture: &Fixture,
    conversation: &LocalConversation,
    run: &DesktopRun,
) -> Arc<RunAuthorization> {
    let auth = fixture
        .state
        .session_store
        .validate_session_credential(
            "cua-native-consent-fixture",
            chrono::Utc::now().timestamp_millis(),
        )
        .unwrap()
        .unwrap();
    RunAuthorization::capture(
        auth,
        Some(cloud::factory_lease(&fixture.state, &fixture.owner).unwrap()),
        conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap()
}

async fn close(fixture: Fixture) {
    fixture
        .state
        .computer_use
        .stop_owner(&fixture.state, &fixture.owner, "test_complete")
        .await;
    fixture.helper.client.shutdown().await;
    std::fs::remove_dir_all(fixture.state.workspace_root.lock().unwrap().as_path()).unwrap();
}

#[tokio::test]
async fn locked_use_host_releases_same_cell_lease_without_another_consent() {
    let fixture = locked_fixture().await;
    let (conversation, run) =
        crate::local_runtime::tests::seed_controlled_run(&fixture.state, "locked-release");
    agent_access::scope(
        Some(run_authorization(&fixture, &conversation, &run)),
        async {
            let host = tool_host(&fixture.state, &conversation, Some(&run)).unwrap();
            let pending = locked_call(host.as_ref(), &run.id, 1).await;
            let request = &pending.permission_required.as_ref().unwrap().demand()["request"];
            fixture.grant(&request["request_id"], "once").await.unwrap();
            execution_authority::with_cell_lifetime(Arc::new(AtomicBool::new(true)), async {
                let enabled = locked_call(host.as_ref(), &run.id, 1).await;
                assert!(enabled.permission_required.is_none());
                let enable = fixture
                    .helper
                    .requests()
                    .into_iter()
                    .find(|r| r["method"] == "locked_use_enable")
                    .unwrap();
                let released = locked_input(host.as_ref(), &run.id, 2, json!({"enabled":false}))
                    .await
                    .unwrap();
                assert!(
                    released.permission_required.is_none(),
                    "current lease release must not suspend the cell"
                );
                assert_eq!(
                    serde_json::from_str::<Value>(&released.output_json).unwrap()["enabled"],
                    false
                );
                assert!(fixture
                    .state
                    .computer_use
                    .pending_for(&fixture.owner)
                    .is_empty());
                let disable = fixture
                    .helper
                    .requests()
                    .into_iter()
                    .find(|r| r["method"] == "locked_use_disable")
                    .unwrap();
                for field in ["session_id", "run_id", "generation"] {
                    assert_eq!(disable["params"][field], enable["params"][field]);
                }
                let repeated = locked_input(host.as_ref(), &run.id, 3, json!({"enabled":false}))
                    .await
                    .unwrap();
                assert!(
                    repeated.permission_required.is_none(),
                    "cleanup is idempotent within the current session"
                );
                let next = locked_call(host.as_ref(), &run.id, 4).await;
                let permission = next
                    .permission_required
                    .as_ref()
                    .expect("enabling still requires a new exact Once");
                assert_eq!(permission.demand()["scopes"], json!(["once"]));
                assert_ne!(
                    permission.demand()["request"]["request_id"],
                    request["request_id"]
                );
                assert_eq!(
                    fixture
                        .helper
                        .requests()
                        .iter()
                        .filter(|r| r["method"] == "locked_use_enable")
                        .count(),
                    1
                );
            })
            .await;
        },
    )
    .await;
    close(fixture).await;
}

#[tokio::test]
async fn locked_use_host_release_retains_params_execution_and_session_boundaries() {
    let fixture = locked_fixture().await;
    let (conversation, run) =
        crate::local_runtime::tests::seed_controlled_run(&fixture.state, "locked-boundary");
    let (other_conversation, other_run) =
        crate::local_runtime::tests::seed_controlled_run(&fixture.state, "locked-other");
    let authorization = run_authorization(&fixture, &conversation, &run);
    let other_authorization = run_authorization(&fixture, &other_conversation, &other_run);
    agent_access::scope(Some(authorization), async {
        let host = tool_host(&fixture.state, &conversation, Some(&run)).unwrap();
        let pending = locked_call(host.as_ref(), &run.id, 1).await;
        let request = &pending.permission_required.as_ref().unwrap().demand()["request"];
        fixture.grant(&request["request_id"], "once").await.unwrap();
        execution_authority::with_cell_lifetime(Arc::new(AtomicBool::new(true)), async {
            assert!(locked_call(host.as_ref(), &run.id, 1)
                .await
                .permission_required
                .is_none());
            let enabled = fixture
                .helper
                .requests()
                .into_iter()
                .find(|r| r["method"] == "locked_use_enable")
                .unwrap();
            for input in [
                json!({"enabled":"false"}),
                json!({"enabled":false,"generation":"foreign"}),
                json!({"enabled":false,"session_id":"foreign"}),
            ] {
                assert!(locked_input(host.as_ref(), &run.id, 2, input)
                    .await
                    .is_err());
            }
            assert!(!fixture
                .helper
                .requests()
                .iter()
                .any(|r| r["method"] == "locked_use_disable"));
            agent_access::scope(Some(other_authorization), async {
                assert!(
                    locked_input(host.as_ref(), &run.id, 3, json!({"enabled":false}))
                        .await
                        .is_err()
                );
                let other =
                    tool_host(&fixture.state, &other_conversation, Some(&other_run)).unwrap();
                let cleaned =
                    locked_input(other.as_ref(), &other_run.id, 1, json!({"enabled":false}))
                        .await
                        .unwrap();
                assert!(cleaned.permission_required.is_none());
                let disabled = fixture
                    .helper
                    .requests()
                    .into_iter()
                    .find(|r| r["method"] == "locked_use_disable")
                    .unwrap();
                assert_ne!(
                    disabled["params"]["session_id"],
                    enabled["params"]["session_id"]
                );
                assert_eq!(disabled["params"]["run_id"], other_run.id);
                assert!(disabled["params"].get("generation").is_none());
            })
            .await;
            fixture
                .state
                .session_store
                .transition_run(
                    &run.id,
                    run.revision,
                    crate::local_runtime::authority_store::DesktopRunStatus::Cancelled,
                    None,
                    &crate::local_runtime::now_iso(),
                )
                .unwrap();
            let before = fixture.helper.requests().len();
            assert!(
                locked_input(host.as_ref(), &run.id, 4, json!({"enabled":false}))
                    .await
                    .is_err()
            );
            assert_eq!(fixture.helper.requests().len(), before);
        })
        .await;
    })
    .await;
    close(fixture).await;
}

#[tokio::test]
async fn locked_use_host_release_does_not_bypass_disabled_runtime_capability() {
    let fixture = Fixture::new().await;
    let (conversation, run) =
        crate::local_runtime::tests::seed_controlled_run(&fixture.state, "locked-disabled");
    agent_access::scope(
        Some(run_authorization(&fixture, &conversation, &run)),
        async {
            let host = tool_host(&fixture.state, &conversation, Some(&run)).unwrap();
            let error = locked_input(host.as_ref(), &run.id, 1, json!({"enabled":false}))
                .await
                .unwrap_err();
            assert!(error.to_string().contains("cua_locked_use_disabled"));
            assert!(fixture
                .state
                .computer_use
                .pending_for(&fixture.owner)
                .is_empty());
            assert!(!fixture.helper.root.join("requests").exists());
        },
    )
    .await;
    close(fixture).await;
}

#[tokio::test]
async fn locked_use_host_release_rejects_revoked_native_session_before_dispatch() {
    let fixture = locked_fixture().await;
    let (conversation, run) =
        crate::local_runtime::tests::seed_controlled_run(&fixture.state, "locked-revoked");
    agent_access::scope(
        Some(run_authorization(&fixture, &conversation, &run)),
        async {
            let host = tool_host(&fixture.state, &conversation, Some(&run)).unwrap();
            fixture
                .state
                .session_store
                .revoke_session(
                    "cua-native-consent-fixture",
                    chrono::Utc::now().timestamp_millis(),
                )
                .unwrap();
            let before = fixture.helper.requests().len();
            let error = locked_input(host.as_ref(), &run.id, 1, json!({"enabled":false}))
                .await
                .unwrap_err();
            assert!(error.to_string().contains("cua_authorization_revoked"));
            assert_eq!(fixture.helper.requests().len(), before);
            assert!(fixture
                .state
                .computer_use
                .pending_for(&fixture.owner)
                .is_empty());
        },
    )
    .await;
    close(fixture).await;
}

#[tokio::test]
async fn locked_use_exact_once_is_consumed_and_each_run_requires_fresh_consent() {
    let fixture = Fixture::new().await;
    for request in [
        json!({"action":"locked_use_install","expected_revision":1}),
        json!({"action":"configure","capability":"locked_use","enabled":true,"expected_revision":1}),
    ] {
        api::operation(
            &fixture.state,
            &fixture.owner,
            serde_json::from_value(request).unwrap(),
        )
        .await
        .unwrap();
    }
    let mut previous_session = None;
    let mut previous_request = None;
    for index in 0..2 {
        let (conversation, run) = crate::local_runtime::tests::seed_controlled_run(
            &fixture.state,
            &format!("locked-consent-{index}"),
        );
        let auth = fixture
            .state
            .session_store
            .validate_session_credential(
                "cua-native-consent-fixture",
                chrono::Utc::now().timestamp_millis(),
            )
            .unwrap()
            .unwrap();
        let authorization = RunAuthorization::capture(
            auth,
            Some(cloud::factory_lease(&fixture.state, &fixture.owner).unwrap()),
            &conversation,
            &run.message_id,
            Some(&run.id),
        )
        .unwrap();
        agent_access::scope(Some(authorization), async {
            let host = tool_host(&fixture.state, &conversation, Some(&run)).unwrap();
            let pending = locked_call(host.as_ref(), &run.id, 1).await;
            let permission = pending
                .permission_required
                .as_ref()
                .expect("fresh native consent");
            assert_eq!(permission.kind(), PermissionKind::NativeConsent);
            assert_eq!(permission.demand()["scopes"], json!(["once"]));
            let request = &permission.demand()["request"];
            let request_id = request["request_id"].clone();
            let session_id = request["session_id"].clone();
            assert_ne!(previous_request.as_ref(), Some(&request_id));
            assert_ne!(previous_session.as_ref(), Some(&session_id));
            previous_request = Some(request_id.clone());
            previous_session = Some(session_id);
            for scope in ["session", "always"] {
                assert_eq!(
                    fixture.grant(&request_id, scope).await.unwrap_err(),
                    "cua_action_requires_once"
                );
            }
            let enable_count = || {
                fixture
                    .helper
                    .requests()
                    .iter()
                    .filter(|request| request["method"] == "locked_use_enable")
                    .count()
            };
            assert_eq!(enable_count(), index);
            fixture.grant(&request_id, "once").await.unwrap();
            let cell = Arc::new(AtomicBool::new(true));
            let completed = execution_authority::with_cell_lifetime(
                cell.clone(),
                locked_call(host.as_ref(), &run.id, 1),
            )
            .await;
            assert!(completed.permission_required.is_none());
            assert_eq!(
                serde_json::from_str::<Value>(&completed.output_json).unwrap()["enabled"],
                true
            );
            assert_eq!(enable_count(), index + 1);
            assert!(store::grants(
                &fixture.state.session_store.connection().unwrap(),
                &fixture.owner
            )
            .unwrap()
            .iter()
            .all(|grant| grant.capability != "locked_use"));
            let replay = locked_call(host.as_ref(), &run.id, 1).await;
            assert!(replay.permission_required.is_none());
            assert_eq!(replay.output_json, completed.output_json);
            assert_eq!(enable_count(), index + 1, "retry must not execute twice");

            cell.store(false, Ordering::SeqCst);
            assert_eq!(
                fixture.state.computer_use.locked_use.status().unwrap()["enabled"],
                true,
                "the live run retains its lease after the cell returns"
            );
            fixture
                .state
                .computer_use
                .release_locked_run(&fixture.state, &run.id, "awaiting_human")
                .await;
            tokio::time::timeout(Duration::from_secs(4), async {
                while !fixture
                    .state
                    .computer_use
                    .locked_use
                    .status()
                    .is_some_and(|status| status["enabled"] == false)
                {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            })
            .await
            .unwrap();
            let next = locked_call(host.as_ref(), &run.id, 2).await;
            let next = next
                .permission_required
                .as_ref()
                .expect("next execution needs a new approval");
            assert_eq!(next.demand()["scopes"], json!(["once"]));
            assert_ne!(next.demand()["request"]["request_id"], request_id);
            assert_eq!(enable_count(), index + 1);
        })
        .await;
    }
    fixture
        .state
        .computer_use
        .stop_owner(&fixture.state, &fixture.owner, "test_complete")
        .await;
    fixture.helper.client.shutdown().await;
    std::fs::remove_dir_all(fixture.state.workspace_root.lock().unwrap().as_path()).unwrap();
}
