use super::*;
use crate::hitl_api::{HitlResponsePayload, HitlResponseService, PgHitlResponseService};
use agistack_adapters_mem::{
    FixedClock, InMemoryCheckpointStore, InMemoryEventStream, ScriptedLlm,
};
use agistack_adapters_postgres::{
    NewHitlRequestRecord, PgCheckpointStore, PgHitlRequestRepository,
};
use agistack_core::{
    agent::ReActObserver,
    ports::{CheckpointStore, CoreResult},
    AgentAction, HitlKind, HitlRequest, Role, SessionState, SessionStatus,
};
use agistack_plugin_host::HotPlugRegistry;
use futures_util::FutureExt;
use std::{
    panic::AssertUnwindSafe,
    sync::{Arc, Mutex},
};

mod fixture;

const RAW_ID: &str = "approve-render-main-once";

fn scope(conversation: &str) -> MessageScope {
    MessageScope {
        user_id: "actor".into(),
        tenant_id: "tenant".into(),
        project_id: "project".into(),
        conversation_id: conversation.into(),
        execution: MessageExecution::Message("message".into()),
    }
}

fn request() -> AgentAction {
    AgentAction::RequestHuman {
        request: HitlRequest::new(RAW_ID, HitlKind::Permission, "Allow the tool once?"),
    }
}

fn engine(
    checkpoints: Arc<dyn CheckpointStore>,
    scope: MessageScope,
    script: Vec<AgentAction>,
) -> ReActEngine {
    bind_engine(
        ReActEngine::new(
            Arc::new(ScriptedLlm::new(script)),
            Arc::new(HotPlugRegistry::new()),
            checkpoints,
            Arc::new(FixedClock(0)),
        ),
        scope,
    )
}

fn record(scope: &MessageScope, state: &SessionState) -> NewHitlRequestRecord {
    let request = state.pending_hitl.as_ref().unwrap();
    NewHitlRequestRecord {
        id: request.id.clone(),
        request_type: "permission".into(),
        conversation_id: scope.conversation_id.clone(),
        message_id: Some("message".into()),
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        user_id: Some(scope.user_id.clone()),
        question: request.prompt.clone(),
        options: None,
        context: None,
        request_metadata: None,
        expires_at: chrono::DateTime::from_timestamp(chrono::Utc::now().timestamp() + 1_800, 0)
            .unwrap(),
    }
}

#[tokio::test]
async fn cloud_hitl_identity_same_model_id_persists_in_two_conversations() {
    let Some(fixture) = fixture::Fixture::open().await else {
        return;
    };
    let outcome = AssertUnwindSafe(async {
        let checkpoints = Arc::new(PgCheckpointStore::new(fixture.pool.clone()));
        let repository = PgHitlRequestRepository::new(fixture.pool.clone());
        let mut ids = Vec::new();
        for conversation in ["conversation-a", "conversation-b"] {
            let scope = scope(conversation);
            let session = format!("{conversation}:message");
            let engine = engine(checkpoints.clone(), scope.clone(), vec![request()]);
            let pending = engine
                .run(&session, "Ask permission", Some("project"))
                .await
                .unwrap();
            assert_eq!(pending.status, SessionStatus::AwaitingInput);
            let stored = record(&scope, &pending);
            assert!(repository.insert_pending(&stored).await.unwrap());
            assert!(!repository.insert_pending(&stored).await.unwrap());
            let checkpoint = checkpoints.load(&session).await.unwrap().unwrap();
            assert_eq!(checkpoint.pending_hitl.as_ref().unwrap().id, stored.id);
            assert_eq!(
                repository
                    .get_by_id(&stored.id)
                    .await
                    .unwrap()
                    .unwrap()
                    .conversation_id,
                conversation
            );
            ids.push(stored.id);
        }
        assert_ne!(ids[0], ids[1]);
        assert!(repository.get_by_id(RAW_ID).await.unwrap().is_none());
    })
    .catch_unwind()
    .await;
    fixture.close().await;
    if let Err(error) = outcome {
        std::panic::resume_unwind(error);
    }
}

#[tokio::test]
async fn cloud_hitl_identity_same_run_new_round_waits_for_another_answer() {
    let Some(fixture) = fixture::Fixture::open().await else {
        return;
    };
    let outcome = AssertUnwindSafe(async {
        let checkpoints = Arc::new(PgCheckpointStore::new(fixture.pool.clone()));
        let repository = PgHitlRequestRepository::new(fixture.pool.clone());
        let scope = scope("conversation");
        let responses = PgHitlResponseService::new(
            PgHitlRequestRepository::new(fixture.pool.clone()),
            Arc::new(InMemoryEventStream::new()),
            None,
        );
        let engine = engine(
            checkpoints.clone(),
            scope.clone(),
            vec![
                request(),
                request(),
                AgentAction::Finish {
                    answer: "done".into(),
                },
            ],
        );
        let first = engine
            .run("conversation:message", "Ask twice", Some("project"))
            .await
            .unwrap();
        let first_record = record(&scope, &first);
        repository.insert_pending(&first_record).await.unwrap();
        let response = HitlResponsePayload {
            request_id: first_record.id.clone(),
            hitl_type: "permission".into(),
            response_data: serde_json::json!({"action":"allow", "granted":true, "scope":"once"}),
        };
        assert!(responses
            .respond("foreign-user", response.clone())
            .await
            .is_err());
        assert_eq!(
            repository
                .get_by_id(&first_record.id)
                .await
                .unwrap()
                .unwrap()
                .status,
            "pending"
        );
        let received = responses.respond("actor", response.clone()).await.unwrap();
        assert_eq!(received.request_id, first_record.id);
        let answer = response.response_data.to_string();
        let second = engine
            .resume("conversation:message", &received.request_id, &answer)
            .await
            .unwrap();
        assert_eq!(second.status, SessionStatus::AwaitingInput);
        let second_record = record(&scope, &second);
        assert_ne!(first_record.id, second_record.id);
        assert_eq!(second.hitl_answer(&first_record.id), Some(answer.as_str()));
        assert!(second.hitl_answer(&second_record.id).is_none());
        repository.insert_pending(&second_record).await.unwrap();
        assert!(responses.respond("actor", response.clone()).await.is_err());
        assert_eq!(
            repository
                .get_by_id(&second_record.id)
                .await
                .unwrap()
                .unwrap()
                .status,
            "pending"
        );
        assert!(engine
            .accept_human_response("conversation:message", &first_record.id, "stale")
            .await
            .is_err());
        let received = responses
            .respond(
                "actor",
                HitlResponsePayload {
                    request_id: second_record.id.clone(),
                    ..response
                },
            )
            .await
            .unwrap();
        let done = engine
            .resume("conversation:message", &received.request_id, &answer)
            .await
            .unwrap();
        assert_eq!(done.status, SessionStatus::Finished);
    })
    .catch_unwind()
    .await;
    fixture.close().await;
    if let Err(error) = outcome {
        std::panic::resume_unwind(error);
    }
}

#[derive(Default)]
struct Requests(Mutex<Vec<HitlRequest>>);

#[async_trait::async_trait]
impl ReActObserver for Requests {
    async fn on_human_request(&self, _: &str, _: u64, request: &HitlRequest) -> CoreResult<()> {
        self.0.lock().unwrap().push(request.clone());
        Ok(())
    }
}

async fn observe_request(scope: MessageScope, session: &str, round: u64, raw: &str) -> HitlRequest {
    let checkpoints = Arc::new(InMemoryCheckpointStore::new());
    let mut checkpoint = SessionState::new(session, "Ask permission", Some(&scope.project_id));
    checkpoint.round = round;
    checkpoints.save(&checkpoint).await.unwrap();
    let request = HitlRequest::new(raw, HitlKind::Permission, "Allow this native operation?")
        .with_decision(serde_json::from_value(serde_json::json!({
            "action": {"name":"computer_click", "label":"Click the button"},
            "target": {"kind":"computer_app", "id":"native-pending-consent-id"},
            "data": {"summary":"Click the observed local button", "redacted_fields":[]},
            "reason":"The user requested this action",
            "risk": {"level":"low", "rationale":"Changes only the local test interface"},
            "reversibility": {"mode":"reversible", "recovery":"Close the test interface"},
            "scope": {"kind":"once", "ids":["native-pending-consent-id"]},
            "evidence": [{"kind":"pending_request", "id":"native-evidence-id", "label":"Observed button"}]
        })).unwrap());
    let mut script = vec![
        AgentAction::Finish {
            answer: "unused".into()
        };
        usize::try_from(round).unwrap()
    ];
    script.push(AgentAction::RequestHuman {
        request: request.clone(),
    });
    let engine = engine(checkpoints.clone(), scope, script);
    let observer = Arc::new(Requests::default());
    let state = engine
        .run_observed(session, "Ask permission", Some("project"), observer.clone())
        .await
        .unwrap();
    assert_eq!(state.status, SessionStatus::AwaitingInput);
    let actual = state.pending_hitl.unwrap();
    assert_eq!(*observer.0.lock().unwrap(), vec![actual.clone()]);
    assert_eq!(
        checkpoints
            .load(session)
            .await
            .unwrap()
            .unwrap()
            .pending_hitl,
        Some(actual.clone())
    );
    let mut restored = actual.clone();
    restored.id = raw.into();
    assert_eq!(restored, request, "binding must change only the outer ID");
    actual
}

#[tokio::test]
async fn cloud_hitl_identity_scopes_are_distinct_and_retries_are_stable() {
    let base = scope("conversation");
    let first = observe_request(base.clone(), "engine", 0, RAW_ID).await;
    assert_ne!(first.id, RAW_ID);
    assert_eq!(
        observe_request(base.clone(), "engine", 0, RAW_ID).await.id,
        first.id
    );
    let mut variants = Vec::new();
    let mut changed = base.clone();
    changed.user_id = "other-user".into();
    variants.push(changed);
    let mut changed = base.clone();
    changed.tenant_id = "other-tenant".into();
    variants.push(changed);
    let mut changed = base.clone();
    changed.project_id = "other-project".into();
    variants.push(changed);
    let mut changed = base.clone();
    changed.conversation_id = "other-conversation".into();
    variants.push(changed);
    let mut changed = base.clone();
    changed.execution = MessageExecution::Message("other-message".into());
    variants.push(changed);
    let mut changed = base.clone();
    changed.execution = MessageExecution::Run("message".into());
    variants.push(changed);
    let mut ids = std::collections::HashSet::from([first.id.clone()]);
    for scope in variants {
        assert!(ids.insert(observe_request(scope, "engine", 0, RAW_ID).await.id));
    }
    for (session, round, raw) in [
        ("other-engine", 0, RAW_ID),
        ("engine", 1, RAW_ID),
        ("engine", 0, first.id.as_str()),
    ] {
        assert!(ids.insert(observe_request(base.clone(), session, round, raw).await.id));
    }
}

#[tokio::test]
async fn cloud_hitl_identity_restart_preserves_legacy_and_bound_pending_ids() {
    let Some(fixture) = fixture::Fixture::open().await else {
        return;
    };
    let outcome = AssertUnwindSafe(async {
        for legacy in [false, true] {
            let session = if legacy {
                "legacy-session"
            } else {
                "bound-session"
            };
            let checkpoints = Arc::new(PgCheckpointStore::new(fixture.pool.clone()));
            let scope = scope(session);
            let first = if legacy {
                ReActEngine::new(
                    Arc::new(ScriptedLlm::new(vec![request()])),
                    Arc::new(HotPlugRegistry::new()),
                    checkpoints.clone(),
                    Arc::new(FixedClock(0)),
                )
                .run(session, "Ask permission", Some("project"))
                .await
                .unwrap()
            } else {
                engine(checkpoints.clone(), scope.clone(), vec![request()])
                    .run(session, "Ask permission", Some("project"))
                    .await
                    .unwrap()
            };
            let id = first.pending_hitl.as_ref().unwrap().id.clone();
            if legacy {
                assert_eq!(id, RAW_ID);
            } else {
                assert_ne!(id, RAW_ID);
            }
            drop(checkpoints);
            let reopened = Arc::new(PgCheckpointStore::new(fixture.pool.clone()));
            let resumed = engine(
                reopened.clone(),
                scope,
                vec![
                    AgentAction::RequestHuman {
                        request: HitlRequest::new(
                            "must-not-reask",
                            HitlKind::Clarification,
                            "must not ask",
                        ),
                    },
                    AgentAction::Finish {
                        answer: "resumed".into(),
                    },
                ],
            );
            assert!(resumed
                .accept_human_response(session, "foreign-id", "wrong")
                .await
                .is_err());
            let accepted = resumed
                .accept_human_response(session, &id, "approved once")
                .await
                .unwrap();
            assert_eq!(accepted.pending_hitl.as_ref().unwrap().id, id);
            assert_eq!(accepted.hitl_answer(&id), Some("approved once"));
            let observer = Arc::new(Requests::default());
            let done = resumed
                .run_observed(session, "Ask permission", Some("project"), observer.clone())
                .await
                .unwrap();
            assert_eq!(done.status, SessionStatus::Finished);
            assert_eq!(done.answer.as_deref(), Some("resumed"));
            assert!(observer.0.lock().unwrap().is_empty());
            assert_eq!(
                done.transcript
                    .iter()
                    .filter(|entry| entry.role == Role::Human)
                    .count(),
                1
            );
        }
    })
    .catch_unwind()
    .await;
    fixture.close().await;
    if let Err(error) = outcome {
        std::panic::resume_unwind(error);
    }
}
