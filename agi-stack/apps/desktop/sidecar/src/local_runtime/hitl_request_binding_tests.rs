use super::*;
use agistack_core::agent::hitl_validation::HitlValidationContext;

fn bound_id(
    state: &Arc<LocalRuntimeState>,
    conversation: &LocalConversation,
    run: Option<&DesktopRun>,
    message: &str,
    child: Option<String>,
    context: &HitlValidationContext<'_>,
    raw: &str,
) -> String {
    computer_use_v2::hitl_validation::NativeHitlValidation::capture(
        state,
        conversation,
        run,
        message,
        child,
    )
    .bind_request_id(context, raw)
    .unwrap()
}

#[tokio::test]
async fn hitl_identity_binds_every_host_scope_field_without_trusting_agent_prefixes() {
    let state = test_state(TOKEN);
    let conversation = conversation(&state, "identity-scope");
    let run = running(&state, &conversation).await;
    let context = HitlValidationContext {
        session_id: "engine",
        round: 0,
    };
    let original = bound_id(
        &state,
        &conversation,
        Some(&run),
        "message",
        None,
        &context,
        RAW_ID,
    );
    assert!(original.starts_with("local-hitl-"));
    assert_eq!(
        original,
        bound_id(
            &state,
            &conversation,
            Some(&run),
            "message",
            None,
            &context,
            RAW_ID
        )
    );
    assert_ne!(
        original,
        bound_id(&state, &conversation, None, &run.id, None, &context, RAW_ID),
        "a message ID equal to a run ID remains a separate operation"
    );
    let mut ids = std::collections::HashSet::from([original.clone()]);
    for field in 0..3 {
        let mut changed = conversation.clone();
        match field {
            0 => changed.tenant_id.push('x'),
            1 => changed.project_id.push('x'),
            _ => changed.id.push('x'),
        }
        assert!(ids.insert(bound_id(
            &state,
            &changed,
            Some(&run),
            "message",
            None,
            &context,
            RAW_ID
        )));
    }
    let mut next_run = run.clone();
    next_run.id.push('x');
    assert!(ids.insert(bound_id(
        &state,
        &conversation,
        Some(&next_run),
        "message",
        None,
        &context,
        RAW_ID
    )));
    for message in ["message-a", "message-b"] {
        assert!(ids.insert(bound_id(
            &state,
            &conversation,
            None,
            message,
            None,
            &context,
            RAW_ID
        )));
    }
    assert!(ids.insert(bound_id(
        &state,
        &conversation,
        Some(&run),
        "message",
        Some("child".into()),
        &context,
        RAW_ID
    )));
    for context in [
        HitlValidationContext {
            session_id: "other-engine",
            round: 0,
        },
        HitlValidationContext {
            session_id: "engine",
            round: 1,
        },
    ] {
        assert!(ids.insert(bound_id(
            &state,
            &conversation,
            Some(&run),
            "message",
            None,
            &context,
            RAW_ID
        )));
    }
    assert!(ids.insert(bound_id(
        &state,
        &conversation,
        Some(&run),
        "message",
        None,
        &context,
        &original
    )));
    let left = bound_id(&state, &conversation, None, "a:b", None, &context, "c");
    let right = bound_id(&state, &conversation, None, "a", None, &context, "b:c");
    assert_ne!(left, right);
}

#[derive(Default)]
struct Capture {
    observed: Mutex<Vec<String>>,
    suspended: Mutex<Vec<SessionState>>,
}

#[async_trait]
impl ReActObserver for Capture {
    async fn on_human_request(&self, _: &str, _: u64, request: &HitlRequest) -> CoreResult<()> {
        self.observed.lock().unwrap().push(request.id.clone());
        Ok(())
    }
}

#[async_trait]
impl agistack_core::automation_permission::PermissionSuspensionPort for Capture {
    async fn suspend(&self, checkpoint: &SessionState) -> CoreResult<()> {
        self.suspended.lock().unwrap().push(checkpoint.clone());
        Ok(())
    }
}

#[tokio::test]
async fn hitl_identity_observer_and_atomic_suspension_receive_the_bound_checkpoint_id() {
    let state = test_state(TOKEN);
    let conversation = conversation(&state, "identity-observer");
    let observer = Arc::new(Capture::default());
    let engine = engine(&state, &conversation, None, vec![request()]);
    let pending = engine
        .run_observed(
            &conversation.id,
            "goal",
            Some("local-project"),
            observer.clone(),
        )
        .await
        .unwrap();
    assert_eq!(
        observer.observed.lock().unwrap().as_slice(),
        &[pending.pending_hitl.as_ref().unwrap().id.clone()]
    );
    assert_ne!(pending.pending_hitl.as_ref().unwrap().id, RAW_ID);

    let atomic_conversation = super::conversation(&state, "identity-atomic");
    let AgentAction::RequestHuman { mut request } = request() else {
        unreachable!()
    };
    request.permission_invocation = Some(Box::new(
        agistack_core::automation_permission::PermissionInvocationProposal {
            tool: request.decision.as_ref().unwrap().action.name.clone(),
            input: json!({"path":"a.rs"}),
        },
    ));
    let atomic = super::engine(
        &state,
        &atomic_conversation,
        None,
        vec![AgentAction::RequestHuman { request }],
    )
    .with_permission_suspension(observer.clone());
    let result = atomic
        .run(&atomic_conversation.id, "goal", Some("local-project"))
        .await
        .unwrap();
    assert_ne!(result.pending_hitl.as_ref().unwrap().id, RAW_ID);
    assert_eq!(
        observer.suspended.lock().unwrap().as_slice(),
        &[result.clone()]
    );
    assert!(
        state
            .checkpoints
            .load(&atomic_conversation.id)
            .await
            .unwrap()
            .is_none()
    );
    assert_eq!(observer.observed.lock().unwrap().len(), 1);
}
