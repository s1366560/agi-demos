//! Formal owner revocation interrupts a live provider response without affecting another session.
use super::*;
use crate::local_runtime::knowledge_authority_v2::agent_access::{self, RunAuthorization};

const OWNER_TOKEN: &str = "http-control-session";

#[derive(Clone, Copy)]
enum OwnerChange {
    SignOut,
    WorkspaceSwitch,
}

async fn publish_generation(state: &Arc<LocalRuntimeState>) {
    let wire: Value = serde_json::from_str(include_str!(
        "../../../../../../shared/profiles/memstack-default-bootstrap.v2.json"
    ))
    .unwrap();
    let snapshot = agistack_plugin_host::parse_profile_snapshot_v2(&wire.to_string()).unwrap();
    let generation = crate::local_runtime::platform_plugin_sync_v2::desktop_loader(None, None)
        .stage(snapshot.clone())
        .await
        .unwrap();
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(&snapshot, &wire, generation)
        .await;
}

async fn owner_request(
    state: &Arc<LocalRuntimeState>,
    token: &str,
    path: &str,
    body: Value,
) -> Value {
    let request = Request::builder()
        .method("POST")
        .uri(path)
        .header("authorization", format!("Bearer {token}"))
        .header("x-agistack-launch", OWNER_TOKEN)
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let response = local_router_with_generation_required(state.clone())
        .oneshot(request)
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    response_json(response).await
}

async fn revoke_owner_while_http_is_held(stage: ResponseStage, change: OwnerChange) {
    let mut upstream = held_response(stage, false).await;
    let (state, conversation) = routed_state(&upstream.base).await;
    let run = registered_http_run(&state, &conversation).await;
    publish_generation(&state).await;
    let auth = state
        .session_store
        .validate_session_credential(OWNER_TOKEN, Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let authorization = RunAuthorization::capture(
        auth.clone(),
        Some(Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        )),
        &conversation,
        &run.message_id,
        Some(&run.id),
    )
    .unwrap();
    let control = agent_access::scope(Some(authorization.clone()), async {
        state
            .claim_agent_run(&conversation.id, Some(&run.id))
            .unwrap()
    })
    .await;
    let mut children = Vec::new();
    for id in ["owner-http-child-a", "owner-http-child-b"] {
        children.push(
            state
                .subagent_controls
                .register(
                    id,
                    &conversation.id,
                    &run,
                    "child-agent",
                    "builtin:all-access",
                    control.clone(),
                )
                .unwrap(),
        );
    }
    let mut first_child = Box::pin(children[0].wait_for_interrupt("owner-http-child-a", 0));
    let mut second_child = Box::pin(children[1].wait_for_interrupt("owner-http-child-b", 0));
    assert!(futures_util::poll!(first_child.as_mut()).is_pending());
    assert!(futures_util::poll!(second_child.as_mut()).is_pending());

    let llm = state
        .llm_for_role(&conversation, LlmWorkloadRole::Default)
        .await
        .unwrap();
    let tools = Arc::new(state.tool_host.lock().unwrap().clone());
    let engine = ReActEngine::new(llm, tools, state.checkpoints.clone(), state.clock.clone());
    let observer = Arc::new(ControlObserver::default());
    let mut task = tokio::spawn({
        let control = control.clone();
        let observer = observer.clone();
        let conversation = conversation.clone();
        agent_access::scope(Some(authorization), async move {
            engine
                .run_observed_controlled(
                    &conversation.id,
                    "Wait for the model",
                    Some(&conversation.project_id),
                    observer,
                    control,
                )
                .await
        })
    });
    let request = tokio::time::timeout(std::time::Duration::from_secs(5), &mut upstream.started)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(request["model"], "controlled-model");
    if matches!(stage, ResponseStage::SseBody) {
        tokio::time::timeout(std::time::Duration::from_secs(5), observer.delta.notified())
            .await
            .unwrap();
        assert_eq!(*observer.text.lock().unwrap(), "partial");
    }

    let unrelated =
        owner_request(&state, OWNER_TOKEN, "/api/v1/auth/local-session", json!({})).await;
    assert_ne!(unrelated["session"]["session_id"], auth.session_id);
    let unrelated_token = unrelated["access_token"].as_str().unwrap();
    let outcome = owner_request(&state, unrelated_token, "/api/v1/auth/signout", json!({})).await;
    assert_eq!(outcome["success"], true);
    assert_eq!(
        control.directive(&conversation.id, 0).await.unwrap(),
        RunDirective::Continue
    );
    assert!(futures_util::poll!(&mut task).is_pending());
    assert!(futures_util::poll!(&mut upstream.closed).is_pending());
    assert!(futures_util::poll!(first_child.as_mut()).is_pending());
    assert!(futures_util::poll!(second_child.as_mut()).is_pending());

    match change {
        OwnerChange::SignOut => {
            let outcome =
                owner_request(&state, OWNER_TOKEN, "/api/v1/auth/signout", json!({})).await;
            assert_eq!(outcome["success"], true);
        }
        OwnerChange::WorkspaceSwitch => {
            let outcome = owner_request(
                &state,
                OWNER_TOKEN,
                "/api/v1/workspace-context/switch",
                json!({
                    "tenant_id": "northstar",
                    "project_id": "desktop-client",
                    "expected_revision": auth.workspace.revision,
                    "idempotency_key": "owner-http-workspace-switch"
                }),
            )
            .await;
            assert_eq!(outcome["context"]["project_id"], "desktop-client");
        }
    }
    let result = tokio::time::timeout(std::time::Duration::from_secs(5), task)
        .await
        .expect("owner revocation must interrupt the held provider request")
        .unwrap()
        .unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(5), &mut upstream.closed)
        .await
        .expect("owner revocation must close the real HTTP response")
        .unwrap();
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        first_child.await.unwrap();
        second_child.await.unwrap();
    })
    .await
    .expect("owner revocation must wake both child controls");
    assert_eq!(result.status, SessionStatus::Cancelled);
    assert!(result.answer.is_none());
    assert!(result.completed_tool_calls.is_empty());
    assert_eq!(observer.finishes.load(Ordering::SeqCst), 0);
    for (child, id) in children
        .iter()
        .zip(["owner-http-child-a", "owner-http-child-b"])
    {
        assert_eq!(child.directive(id, 0).await.unwrap(), RunDirective::Cancel);
    }
    let saved = state
        .checkpoints
        .load(&conversation.id)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(saved.status, SessionStatus::Cancelled);
    assert!(saved.answer.is_none());
    state.release_agent_run(&conversation.id);
    state.platform_plugin_authority_v2.deactivate().await;
}

#[tokio::test]
async fn formal_owner_signout_interrupts_held_http_headers_and_child_controls() {
    revoke_owner_while_http_is_held(ResponseStage::Headers, OwnerChange::SignOut).await;
}

#[tokio::test]
async fn formal_owner_signout_interrupts_incomplete_http_json_and_child_controls() {
    revoke_owner_while_http_is_held(ResponseStage::JsonBody, OwnerChange::SignOut).await;
}

#[tokio::test]
async fn formal_workspace_switch_interrupts_partial_http_sse_and_child_controls() {
    revoke_owner_while_http_is_held(ResponseStage::SseBody, OwnerChange::WorkspaceSwitch).await;
}
