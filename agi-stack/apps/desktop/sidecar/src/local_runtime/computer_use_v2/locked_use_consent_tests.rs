//! Exact native approval for each new locked-use execution, using private mock IPC only.
use super::*;
use crate::local_runtime::execution_authority;
use agistack_core::ports::{PermissionKind, ToolResult};
use std::time::Duration;

async fn locked_call(host: &dyn ToolHost, engine: &str, round: u64) -> ToolResult {
    let context = ToolPolicyContext {
        session_id: engine,
        round,
        tool: "computer_locked_use",
    };
    call_identity::scope(
        &context,
        host.call_with_content(context.tool, r#"{"enabled":true}"#),
    )
    .await
    .unwrap()
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
            assert!(
                store::grants(
                    &fixture.state.session_store.connection().unwrap(),
                    &fixture.owner
                )
                .unwrap()
                .iter()
                .all(|grant| grant.capability != "locked_use")
            );
            let replay = locked_call(host.as_ref(), &run.id, 1).await;
            assert!(replay.permission_required.is_none());
            assert_eq!(replay.output_json, completed.output_json);
            assert_eq!(enable_count(), index + 1, "retry must not execute twice");

            cell.store(false, Ordering::SeqCst);
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
