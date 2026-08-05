use std::{path::PathBuf, sync::Arc};

use axum::{
    body::Body,
    http::{Request, StatusCode},
    response::Response,
    Router,
};
use serde_json::{json, Value};
use tower::ServiceExt;
use uuid::Uuid;

use super::super::*;
use super::activity_read_state::{
    initialize_schema, read_state, update_state, ActivityReadEntry, ActivityReadStateError,
    UpdateActivityReadStateRequest,
};

const PROJECT_ID: &str = "local-project";
const TENANT_ID: &str = "local";

struct ActivityReadStateTestRuntime {
    root: PathBuf,
    state: Arc<LocalRuntimeState>,
}

impl Drop for ActivityReadStateTestRuntime {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

fn test_runtime(credential: &str) -> ActivityReadStateTestRuntime {
    let root =
        std::env::temp_dir().join(format!("agistack-activity-read-state-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create activity read-state workspace");
    let tool_host = LocalToolHost::new(&root).expect("tool host");
    let checkpoints = Arc::new(SqliteCheckpointStore::in_memory().expect("checkpoints"));
    let session_store = DesktopSessionStore::in_memory().expect("session store");
    let state = Arc::new(
        LocalRuntimeState::new(
            root.clone(),
            tool_host,
            checkpoints,
            credential.to_string(),
            session_store,
        )
        .expect("local runtime state"),
    );
    state
        .session_store
        .seed_test_session(credential)
        .expect("authenticated test session");
    ActivityReadStateTestRuntime { root, state }
}

fn seed_attention_run(store: &DesktopSessionStore, conversation_id: &str) -> DesktopRun {
    let now = now_iso();
    store
        .insert_conversation(&LocalConversation {
            id: conversation_id.to_string(),
            project_id: PROJECT_ID.to_string(),
            tenant_id: TENANT_ID.to_string(),
            title: "Activity authority fixture".to_string(),
            workspace_id: Some("local-workspace".to_string()),
            capability_mode: ConversationCapabilityMode::Code,
            current_mode: ConversationRunMode::Plan,
            created_at: now.clone(),
            updated_at: now.clone(),
        })
        .expect("insert activity conversation");
    store
        .replace_agent_plan_tasks(
            conversation_id,
            &[json!({
                "id": format!("task-{conversation_id}"),
                "conversation_id": conversation_id,
                "content": "Verify local Activity read receipts",
                "status": "pending",
                "priority": "high",
                "order_index": 0,
                "created_at": now,
                "updated_at": now,
            })],
        )
        .expect("store activity plan");
    let approved = store
        .approve_plan_and_start(
            conversation_id,
            PROJECT_ID,
            &format!("approval-{conversation_id}"),
            &format!("message-{conversation_id}"),
            "Execute the reviewed plan",
            &now_iso(),
        )
        .expect("approve activity run");
    let running = store
        .prepare_run_for_execution(&approved.run.id, &now_iso())
        .expect("prepare activity run")
        .expect("running activity run");
    store
        .transition_run(
            &running.id,
            running.revision,
            DesktopRunStatus::NeedsApproval,
            None,
            &now_iso(),
        )
        .expect("transition activity run")
}

fn activity_request(
    method: &str,
    project_id: &str,
    credential: &str,
    body: Option<Value>,
) -> Request<Body> {
    let mut builder = Request::builder()
        .method(method)
        .uri(format!("/api/v1/projects/{project_id}/activity/read-state"))
        .header("authorization", format!("Bearer {credential}"))
        .header("x-agistack-launch", credential);
    if body.is_some() {
        builder = builder.header("content-type", "application/json");
    }
    builder
        .body(body.map_or_else(Body::empty, |value| Body::from(value.to_string())))
        .expect("activity read-state request")
}

async fn response_json(response: Response) -> Value {
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("activity read-state response body");
    serde_json::from_slice(&body).expect("activity read-state response JSON")
}

#[tokio::test]
async fn first_get_initializes_an_empty_project_scoped_read_state() {
    // Arrange
    let credential = "activity-empty-secret";
    let runtime = test_runtime(credential);
    let app = local_router(Arc::clone(&runtime.state));

    // Act
    let response = app
        .oneshot(activity_request("GET", PROJECT_ID, credential, None))
        .await
        .expect("empty activity read-state response");

    // Assert
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(
        response_json(response).await,
        json!({
            "project_id": PROJECT_ID,
            "authority_revision": 0,
            "entries": [],
        })
    );
}

#[tokio::test]
async fn put_persists_a_known_my_work_entry_and_replays_the_same_shape() {
    // Arrange
    let credential = "activity-put-secret";
    let runtime = test_runtime(credential);
    let run = seed_attention_run(&runtime.state.session_store, "activity-put-conversation");
    let entry_id = format!("desktop_run:{}", run.id);
    let app = local_router(Arc::clone(&runtime.state));

    // Act
    let put_response = app
        .clone()
        .oneshot(activity_request(
            "PUT",
            PROJECT_ID,
            credential,
            Some(json!({
                "expected_authority_revision": 0,
                "entries": [{
                    "entry_id": entry_id,
                    "entry_revision": run.revision,
                    "read_at": "2026-08-05T01:00:00Z",
                }],
            })),
        ))
        .await
        .expect("put activity read-state response");
    let put_status = put_response.status();
    let put_payload = response_json(put_response).await;
    let get_response = app
        .oneshot(activity_request("GET", PROJECT_ID, credential, None))
        .await
        .expect("replayed activity read-state response");
    let get_status = get_response.status();
    let get_payload = response_json(get_response).await;

    // Assert
    assert_eq!(put_status, StatusCode::OK);
    assert_eq!(put_payload["project_id"], PROJECT_ID);
    assert_eq!(put_payload["authority_revision"], 1);
    assert_eq!(put_payload["entries"][0]["entry_id"], entry_id);
    assert_eq!(get_status, StatusCode::OK);
    assert_eq!(get_payload, put_payload);
}

#[tokio::test]
async fn put_rejects_stale_authority_revision_and_unknown_or_duplicate_entries() {
    // Arrange
    let credential = "activity-conflict-secret";
    let runtime = test_runtime(credential);
    let run = seed_attention_run(
        &runtime.state.session_store,
        "activity-conflict-conversation",
    );
    let entry_id = format!("desktop_run:{}", run.id);
    let app = local_router(Arc::clone(&runtime.state));
    let first = app
        .clone()
        .oneshot(activity_request(
            "PUT",
            PROJECT_ID,
            credential,
            Some(json!({
                "expected_authority_revision": 0,
                "entries": [{
                    "entry_id": entry_id,
                    "entry_revision": run.revision,
                    "read_at": "2026-08-05T01:00:00Z",
                }],
            })),
        ))
        .await
        .expect("initial activity receipt");
    assert_eq!(first.status(), StatusCode::OK);

    // Act
    let stale = app
        .clone()
        .oneshot(activity_request(
            "PUT",
            PROJECT_ID,
            credential,
            Some(json!({
                "expected_authority_revision": 0,
                "entries": [{
                    "entry_id": entry_id,
                    "entry_revision": run.revision,
                    "read_at": "2026-08-05T02:00:00Z",
                }],
            })),
        ))
        .await
        .expect("stale activity receipt");
    let unknown = app
        .clone()
        .oneshot(activity_request(
            "PUT",
            PROJECT_ID,
            credential,
            Some(json!({
                "expected_authority_revision": 1,
                "entries": [{
                    "entry_id": "desktop_run:unknown",
                    "entry_revision": 1,
                    "read_at": "2026-08-05T02:00:00Z",
                }],
            })),
        ))
        .await
        .expect("unknown activity receipt");
    let duplicate = app
        .oneshot(activity_request(
            "PUT",
            PROJECT_ID,
            credential,
            Some(json!({
                "expected_authority_revision": 1,
                "entries": [
                    {
                        "entry_id": entry_id,
                        "entry_revision": run.revision,
                        "read_at": "2026-08-05T02:00:00Z",
                    },
                    {
                        "entry_id": entry_id,
                        "entry_revision": run.revision,
                        "read_at": "2026-08-05T03:00:00Z",
                    },
                ],
            })),
        ))
        .await
        .expect("duplicate activity receipt");

    // Assert
    assert_eq!(stale.status(), StatusCode::CONFLICT);
    assert_eq!(unknown.status(), StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(duplicate.status(), StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn activity_read_state_rejects_a_project_outside_the_authenticated_scope() {
    // Arrange
    let credential = "activity-scope-secret";
    let runtime = test_runtime(credential);
    let app: Router = local_router(Arc::clone(&runtime.state));

    // Act
    let response = app
        .oneshot(activity_request("GET", "project-b", credential, None))
        .await
        .expect("out-of-scope activity read-state response");

    // Assert
    assert_eq!(response.status(), StatusCode::FORBIDDEN);
}

#[test]
fn update_merges_entry_revision_and_read_time_independently() {
    // Arrange
    let store = DesktopSessionStore::in_memory().expect("activity receipt store");
    let run = seed_attention_run(&store, "activity-merge-conversation");
    let entry_id = format!("desktop_run:{}", run.id);
    let first = UpdateActivityReadStateRequest {
        expected_authority_revision: 0,
        entries: vec![ActivityReadEntry::try_from_parts(
            entry_id.clone(),
            5,
            "2026-08-05T03:00:00Z".to_string(),
        )
        .expect("first activity receipt")],
    };
    update_state(&store, TENANT_ID, PROJECT_ID, "user-1", first)
        .expect("persist first activity receipt");

    // Act
    let newer_read_time = update_state(
        &store,
        TENANT_ID,
        PROJECT_ID,
        "user-1",
        UpdateActivityReadStateRequest {
            expected_authority_revision: 1,
            entries: vec![ActivityReadEntry::try_from_parts(
                entry_id.clone(),
                4,
                "2026-08-05T04:00:00Z".to_string(),
            )
            .expect("newer read-time receipt")],
        },
    )
    .expect("merge newer read time");
    let newer_entry_revision = update_state(
        &store,
        TENANT_ID,
        PROJECT_ID,
        "user-1",
        UpdateActivityReadStateRequest {
            expected_authority_revision: 2,
            entries: vec![ActivityReadEntry::try_from_parts(
                entry_id,
                6,
                "2026-08-05T02:00:00Z".to_string(),
            )
            .expect("newer entry-revision receipt")],
        },
    )
    .expect("merge newer entry revision");

    // Assert
    assert_eq!(newer_read_time.authority_revision, 2);
    assert_eq!(newer_read_time.entries[0].entry_revision, 5);
    assert_eq!(newer_read_time.entries[0].read_at, "2026-08-05T04:00:00Z");
    assert_eq!(newer_entry_revision.authority_revision, 3);
    assert_eq!(newer_entry_revision.entries[0].entry_revision, 6);
    assert_eq!(
        newer_entry_revision.entries[0].read_at,
        "2026-08-05T04:00:00Z"
    );
}

#[test]
fn update_rejects_an_entry_that_left_the_current_my_work_projection() {
    // Arrange
    let store = DesktopSessionStore::in_memory().expect("activity receipt store");
    let run = seed_attention_run(&store, "activity-terminal-conversation");
    let resumed = store
        .transition_run(
            &run.id,
            run.revision,
            DesktopRunStatus::Running,
            None,
            &now_iso(),
        )
        .expect("resume activity run");
    let ready_review = store
        .transition_run(
            &resumed.id,
            resumed.revision,
            DesktopRunStatus::ReadyReview,
            None,
            &now_iso(),
        )
        .expect("prepare activity run review");
    store
        .transition_review_run(
            &ready_review.id,
            ready_review.revision,
            DesktopRunStatus::Completed,
            "approve",
            None,
            &now_iso(),
        )
        .expect("complete activity run review");

    // Act
    let result = update_state(
        &store,
        TENANT_ID,
        PROJECT_ID,
        "user-1",
        UpdateActivityReadStateRequest {
            expected_authority_revision: 0,
            entries: vec![ActivityReadEntry::try_from_parts(
                format!("desktop_run:{}", run.id),
                run.revision,
                "2026-08-05T04:30:00Z".to_string(),
            )
            .expect("terminal activity receipt")],
        },
    );

    // Assert
    assert!(matches!(
        result,
        Err(ActivityReadStateError::InvalidRequest(
            "activity entry_id is absent from the current My Work projection"
        ))
    ));
}

#[test]
fn receipts_are_isolated_by_tenant_project_and_user() {
    // Arrange
    let store = DesktopSessionStore::in_memory().expect("activity receipt store");
    let run = seed_attention_run(&store, "activity-scope-conversation");
    update_state(
        &store,
        TENANT_ID,
        PROJECT_ID,
        "user-1",
        UpdateActivityReadStateRequest {
            expected_authority_revision: 0,
            entries: vec![ActivityReadEntry::try_from_parts(
                format!("desktop_run:{}", run.id),
                1,
                "2026-08-05T01:00:00Z".to_string(),
            )
            .expect("scoped activity receipt")],
        },
    )
    .expect("persist scoped activity receipt");

    // Act
    let cross_tenant_write = update_state(
        &store,
        "tenant-b",
        PROJECT_ID,
        "user-1",
        UpdateActivityReadStateRequest {
            expected_authority_revision: 0,
            entries: vec![ActivityReadEntry::try_from_parts(
                format!("desktop_run:{}", run.id),
                1,
                "2026-08-05T01:30:00Z".to_string(),
            )
            .expect("cross-tenant activity receipt")],
        },
    );
    let same_scope =
        read_state(&store, TENANT_ID, PROJECT_ID, "user-1").expect("read same activity scope");
    let other_tenant = read_state(&store, "tenant-b", PROJECT_ID, "user-1")
        .expect("read other tenant activity scope");
    let other_project = read_state(&store, TENANT_ID, "project-b", "user-1")
        .expect("read other project activity scope");
    let other_user = read_state(&store, TENANT_ID, PROJECT_ID, "user-2")
        .expect("read other user activity scope");

    // Assert
    assert!(matches!(
        cross_tenant_write,
        Err(ActivityReadStateError::InvalidRequest(
            "activity entry_id is absent from the current My Work projection"
        ))
    ));
    assert_eq!(same_scope.entries.len(), 1);
    for isolated in [other_tenant, other_project, other_user] {
        assert_eq!(isolated.authority_revision, 0);
        assert!(isolated.entries.is_empty());
    }
}

#[test]
fn schema_initialization_is_idempotent_and_receipts_survive_store_reopen() {
    // Arrange
    let root = std::env::temp_dir().join(format!("agistack-activity-reopen-{}", Uuid::new_v4()));
    std::fs::create_dir_all(&root).expect("create activity reopen directory");
    let database_path = root.join("session.sqlite3");
    {
        let store = DesktopSessionStore::open(&database_path).expect("open activity receipt store");
        let run = seed_attention_run(&store, "activity-reopen-conversation");
        store
            .with_local_mcp_connection(|connection| {
                initialize_schema(connection)?;
                initialize_schema(connection)
            })
            .expect("initialize activity schema twice");
        update_state(
            &store,
            TENANT_ID,
            PROJECT_ID,
            "user-1",
            UpdateActivityReadStateRequest {
                expected_authority_revision: 0,
                entries: vec![ActivityReadEntry::try_from_parts(
                    format!("desktop_run:{}", run.id),
                    9,
                    "2026-08-05T05:00:00Z".to_string(),
                )
                .expect("persistent activity receipt")],
            },
        )
        .expect("persist activity receipt before reopen");
    }

    // Act
    let reopened =
        DesktopSessionStore::open(&database_path).expect("reopen activity receipt store");
    let state = read_state(&reopened, TENANT_ID, PROJECT_ID, "user-1")
        .expect("read activity receipt after reopen");

    // Assert
    assert_eq!(state.authority_revision, 1);
    assert_eq!(state.entries.len(), 1);
    assert_eq!(state.entries[0].entry_revision, 9);
    assert_eq!(state.entries[0].read_at, "2026-08-05T05:00:00Z");
    drop(reopened);
    std::fs::remove_dir_all(root).expect("remove activity reopen directory");
}
