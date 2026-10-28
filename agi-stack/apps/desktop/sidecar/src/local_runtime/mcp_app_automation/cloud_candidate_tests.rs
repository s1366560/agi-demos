//! Consecutive Cloud approvals preserve only the captured callback's recorded lineage.
use super::super::callback_origin::CallbackOrigin;
use super::*;
use crate::local_runtime::execution_authority::{
    with_cell_lifetime, with_step_id, with_step_origin, StepOrigin,
};
use std::sync::atomic::AtomicBool;

#[tokio::test]
async fn cloud_callback_candidates_follow_only_prior_approved_lineage_and_never_dispatch_before_renewal(
) {
    let mut fixture = Fixture::new().await;
    let mut original = fixture.execution.scope.clone();
    original.connection_epoch = Some(7);
    original.device_id = Some("device".into());
    fixture.execution = execution(&fixture.state, original.clone(), &fixture.server_id);
    fixture._authority = Arc::new(ExecutionAuthority::CloudClaim(fixture.execution.clone()));
    fixture
        .state
        .mcp_app_automation
        .register_authority(fixture._authority.clone());
    let id = fixture.render("render_main").await;
    let handle = fixture.attach(&id).await;
    let registry = &fixture.state.mcp_app_automation;
    let captured = registry.tabs.lock().unwrap()[&id].clone();
    let binding = fixture
        .state
        .mcp_supervisor
        .resolve_tool(&fixture.scope, &fixture.server_id, "increment_main")
        .unwrap();
    let origin = CallbackOrigin::capture(&id, &captured, &binding).unwrap();
    let mut previous = original.clone();
    previous.run_revision = 3;
    let first_execution = execution(&fixture.state, previous.clone(), &fixture.server_id);
    let first = Arc::new(ExecutionAuthority::CloudClaim(first_execution));
    registry.register_authority(first.clone());
    registry
        .resume_cloud_permission(&original, &first, &handle)
        .unwrap();
    let mut next = previous.clone();
    next.run_revision = 5;
    let current = execution(&fixture.state, next.clone(), &fixture.server_id);
    let authority = Arc::new(ExecutionAuthority::CloudClaim(current.clone()));
    registry.register_authority(authority.clone());
    let tool = legacy_exposed_tool_name(&fixture.server_id, "increment_main");
    let step = StepOrigin {
        cell_id: "cell".into(),
        parent_request_id: Some("original-request".into()),
        continuation_scope: Some(previous.clone()),
    };
    captured
        .identity
        .for_tool(
            &tool,
            with_cell_lifetime(
                Arc::new(AtomicBool::new(true)),
                with_step_origin(
                    step,
                    with_step_id(
                        "step".into(),
                        origin.clone().scope(async {
                            let (actual, target) = registry
                                .cloud_callback_target(&fixture.state, &authority, &tool)
                                .unwrap()
                                .unwrap();
                            assert_eq!(actual, previous);
                            assert_eq!(target, handle);
                            assert!(registry
                                .validate_cloud_callback(&fixture.state, &authority)
                                .is_err());
                            assert_eq!(current.calls.load(Ordering::SeqCst), 0);
                            registry
                                .resume_cloud_permission(&actual, &authority, &target)
                                .unwrap();
                            registry
                                .validate_cloud_callback(&fixture.state, &authority)
                                .unwrap();
                            let arguments = json!({"operation_id":"second-approved-callback"});
                            *current.permit.lock().unwrap() =
                                Some((tool.clone(), arguments.clone()));
                            let output =
                                authority.call(&tool, &arguments.to_string()).await.unwrap();
                            let output: Value = serde_json::from_str(&output.output_json).unwrap();
                            assert_eq!(payload(&output)["counts"]["main"], 1);
                        }),
                    ),
                ),
            ),
        )
        .await;
    assert_eq!(fixture.events().len(), 1);
    assert_eq!(fixture.registration(&id), handle);
    assert!(registry
        .require_browser(&fixture.state, &handle, &original)
        .is_err());
    assert_eq!(registry.tabs.lock().unwrap()[&id].scope, next);
    assert_eq!(
        registry.tabs.lock().unwrap()[&id].continuation_revisions,
        BTreeSet::from([1, 3])
    );

    let mut untrusted = original.clone();
    untrusted.run_revision = 2;
    let fake_step = StepOrigin {
        cell_id: "cell".into(),
        parent_request_id: Some("other-request".into()),
        continuation_scope: Some(untrusted),
    };
    assert!(captured
        .identity
        .for_tool(
            &tool,
            with_cell_lifetime(
                Arc::new(AtomicBool::new(true)),
                with_step_origin(
                    fake_step,
                    with_step_id(
                        "other-step".into(),
                        origin.scope(async {
                            // The general old-scope path stays strict; no new lineage was approved.
                            let mut future = next.clone();
                            future.run_revision = 7;
                            let execution = execution(&fixture.state, future, &fixture.server_id);
                            let replacement = Arc::new(ExecutionAuthority::CloudClaim(execution));
                            registry.register_authority(replacement.clone());
                            registry.cloud_callback_target(&fixture.state, &replacement, &tool)
                        })
                    )
                )
            )
        )
        .await
        .is_err());
    assert_eq!(current.calls.load(Ordering::SeqCst), 1);
}
