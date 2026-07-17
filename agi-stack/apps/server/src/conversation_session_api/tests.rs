use chrono::{Duration, TimeZone};
use serde_json::json;
use sqlx::FromRow;

use super::pg::{project_pending_hitl_for_test, safe_options_for_test, safe_permission_request};
use super::*;

fn timestamp(seconds: i64) -> DateTime<Utc> {
    Utc.timestamp_opt(seconds, 0)
        .single()
        .expect("test timestamp must be valid")
}

fn conversation() -> SessionConversationResponse {
    SessionConversationResponse {
        id: "conversation-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: Some("workspace-1".to_string()),
        linked_workspace_task_id: Some("task-1".to_string()),
        workspace_name: Some("Workspace one".to_string()),
        user_id: "user-1".to_string(),
        title: "Scoped session".to_string(),
        summary: None,
        status: "active".to_string(),
        current_mode: "plan".to_string(),
        conversation_mode: Some("autonomous".to_string()),
        capability_mode: Some(SessionCapabilityMode::Code),
        message_count: 3,
        participant_agents: vec!["agent-1".to_string()],
        coordinator_agent_id: Some("agent-1".to_string()),
        focused_agent_id: None,
        created_at: timestamp(10),
        updated_at: Some(timestamp(20)),
    }
}

#[test]
fn schema_v2_projection_uses_persisted_authority_and_capabilities() {
    let hitl = SessionPendingHitlResponse {
        id: "hitl-1".to_string(),
        conversation_id: "conversation-1".to_string(),
        message_id: Some("message-1".to_string()),
        request_type: SessionHitlKind::Decision,
        question: "Choose one".to_string(),
        options: vec![Map::from_iter([
            ("id".to_string(), Value::String("safe".to_string())),
            ("label".to_string(), Value::String("Safe".to_string())),
        ])],
        context: Map::new(),
        metadata: Map::from_iter([(
            "hitl_type".to_string(),
            Value::String("decision".to_string()),
        )]),
        permission: None,
        status: "pending",
        created_at: timestamp(40),
        expires_at: Some(timestamp(40) + Duration::minutes(5)),
    };
    let projection = build_projection(ConversationSessionAuthoritySnapshot {
        conversation: conversation(),
        attempts: vec![SessionWorkspaceAttemptResponse {
            id: "attempt-2".to_string(),
            workspace_task_id: "task-1".to_string(),
            root_goal_task_id: "task-1".to_string(),
            workspace_id: "workspace-1".to_string(),
            conversation_id: "conversation-1".to_string(),
            attempt_number: 2,
            status: "running".to_string(),
            worker_agent_id: Some("agent-1".to_string()),
            leader_agent_id: None,
            candidate_summary: None,
            candidate_artifact_refs: vec!["artifact://one".to_string()],
            candidate_verification_refs: vec![
                "check://test".to_string(),
                "check://lint".to_string(),
            ],
            leader_feedback: None,
            adjudication_reason: None,
            created_at: timestamp(30),
            updated_at: None,
            completed_at: None,
        }],
        conversation_tasks: Vec::new(),
        workspace_plan_context: None,
        pending_hitl: vec![hitl],
        has_blocking_hitl: true,
        mutation_authority: SessionMutationAuthority {
            can_send_message: true,
            can_respond_to_hitl: true,
            can_control_execution: false,
        },
        artifact_records: vec![SessionArtifactAuthority {
            response: SessionArtifactRecordResponse {
                id: "artifact-1".to_string(),
            },
            created_at: timestamp(35),
        }],
        tool_executions: SessionToolExecutionAuthority {
            items: vec![SessionToolExecutionResponse {
                id: "tool-1".to_string(),
                message_id: "message-1".to_string(),
                call_id: "call-1".to_string(),
                tool_name: "read_file".to_string(),
                status: "failed".to_string(),
                error: None,
                step_number: None,
                sequence_number: 1,
                started_at: timestamp(50),
                completed_at: Some(timestamp(51)),
                duration_ms: Some(1_000),
            }],
            total: 3,
            failed_total: 1,
        },
    })
    .expect("projection must serialize");

    let payload = serde_json::to_value(projection).expect("projection must serialize");
    assert_eq!(payload["schema_version"], 2);
    assert_eq!(payload["projection_kind"], "workspace_session");
    assert_eq!(payload["authority_kind"], "workspace_attempt");
    assert_eq!(payload["authority_id"], "attempt-2");
    assert_eq!(payload["conversation"]["current_mode"], "plan");
    assert_eq!(payload["capabilities"]["can_send_message"], false);
    assert_eq!(payload["capabilities"]["can_respond_to_hitl"], true);
    assert_eq!(
        payload["capabilities"]["allowed_actions"],
        json!(["respond_to_hitl"])
    );
    assert_eq!(
        payload["evidence_summary"]["candidate_artifact_ref_count"],
        1
    );
    assert_eq!(
        payload["evidence_summary"]["candidate_verification_ref_count"],
        2
    );
    assert_eq!(payload["tool_execution_records"]["truncated"], true);
    assert_eq!(payload["updated_at"], "1970-01-01T00:00:51Z");
    assert_eq!(
        payload["snapshot_revision"]
            .as_str()
            .expect("revision must be a string")
            .len(),
        64
    );
    let serialized = payload.to_string();
    for unsupported in [
        "run_id",
        "permission_profile",
        "environment",
        "plan_version",
        "artifact_version",
    ] {
        assert!(!serialized.contains(unsupported));
    }
}

#[test]
fn read_only_projection_never_grants_mutation_capabilities() {
    let hitl = SessionPendingHitlResponse {
        id: "hitl-read-only".to_string(),
        conversation_id: "conversation-1".to_string(),
        message_id: None,
        request_type: SessionHitlKind::Clarification,
        question: "Confirm the next step".to_string(),
        options: Vec::new(),
        context: Map::new(),
        metadata: Map::from_iter([(
            "hitl_type".to_string(),
            Value::String("clarification".to_string()),
        )]),
        permission: None,
        status: "pending",
        created_at: timestamp(40),
        expires_at: None,
    };
    let projection = build_projection(ConversationSessionAuthoritySnapshot {
        conversation: conversation(),
        attempts: Vec::new(),
        conversation_tasks: Vec::new(),
        workspace_plan_context: None,
        pending_hitl: vec![hitl],
        has_blocking_hitl: true,
        mutation_authority: SessionMutationAuthority {
            can_send_message: false,
            can_respond_to_hitl: false,
            can_control_execution: false,
        },
        artifact_records: Vec::new(),
        tool_executions: SessionToolExecutionAuthority {
            items: Vec::new(),
            total: 0,
            failed_total: 0,
        },
    })
    .expect("read-only projection must serialize");

    let payload = serde_json::to_value(projection).expect("projection must serialize");
    assert_eq!(payload["capabilities"]["can_send_message"], false);
    assert_eq!(payload["capabilities"]["can_respond_to_hitl"], false);
    assert_eq!(payload["capabilities"]["can_control_execution"], false);
    assert_eq!(payload["capabilities"]["allowed_actions"], json!([]));
}

#[test]
fn pending_hitl_without_expiry_serializes_null_expiration() {
    let response = SessionPendingHitlResponse {
        id: "hitl-no-expiry".to_string(),
        conversation_id: "conversation-1".to_string(),
        message_id: None,
        request_type: SessionHitlKind::Decision,
        question: "Choose one".to_string(),
        options: Vec::new(),
        context: Map::new(),
        metadata: Map::from_iter([(
            "hitl_type".to_string(),
            Value::String("decision".to_string()),
        )]),
        permission: None,
        status: "pending",
        created_at: timestamp(40),
        expires_at: None,
    };

    let payload = serde_json::to_value(response).expect("HITL response must serialize");

    assert!(payload["expires_at"].is_null());
}

#[tokio::test]
async fn internal_error_response_hides_database_diagnostic() {
    let response = ConversationSessionApiError::internal(
        "database error: password authentication failed for private-host",
    )
    .into_response();

    assert_eq!(
        response.status(),
        axum::http::StatusCode::INTERNAL_SERVER_ERROR
    );
    let body = axum::body::to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("error response body must be readable");
    let payload: Value = serde_json::from_slice(&body).expect("error response must be JSON");
    assert_eq!(payload, json!({ "detail": "Internal server error" }));
}

#[test]
fn hitl_options_are_structurally_allowlisted_without_raw_runtime_values() {
    let options = safe_options_for_test(Some(&json!([
        {
            "id": "choice-1",
            "label": "<Reviewed>",
            "description": "Use the reviewed choice",
            "recommended": true,
            "value": "raw secret value",
            "runtime_payload": {"token": "must-not-leak"}
        }
    ])));

    assert_eq!(options.len(), 1);
    assert_eq!(options[0]["id"], "choice-1");
    assert_eq!(options[0]["label"], "&lt;Reviewed&gt;");
    assert_eq!(options[0]["recommended"], true);
    assert!(!options[0].contains_key("value"));
    assert!(!options[0].contains_key("runtime_payload"));
}

#[test]
fn permission_metadata_projects_only_the_structured_review_contract() {
    let metadata = json!({
        "hitl_type": "permission",
        "tool_name": "terminal.execute",
        "action": "run the reviewed test command",
        "risk_level": "medium",
        "description": "Run the focused test suite",
        "allow_remember": true,
        "details": {"command": "must-not-leak"},
        "runtime_payload": {"token": "must-not-leak"}
    });

    let permission = safe_permission_request(Some(&metadata))
        .expect("structured permission metadata must project");
    let payload = serde_json::to_value(permission).expect("permission must serialize");

    assert_eq!(payload["tool_name"], "terminal.execute");
    assert_eq!(payload["action"], "run the reviewed test command");
    assert_eq!(payload["risk_level"], "medium");
    assert_eq!(payload["description"], "Run the focused test suite");
    assert_eq!(payload["allow_remember"], true);
    assert!(payload.get("details").is_none());
    assert!(payload.get("runtime_payload").is_none());

    let incomplete = json!({
        "tool_name": "terminal.execute",
        "action": "run tests"
    });
    assert!(safe_permission_request(Some(&incomplete)).is_none());
}

#[test]
fn persisted_permission_without_question_projects_and_keeps_capabilities_consistent() {
    let metadata = json!({
        "hitl_type": "permission",
        "tool_name": "terminal.execute",
        "action": "run the reviewed test command",
        "risk_level": "medium",
        "description": null,
        "allow_remember": false,
        "details": {"command": "must-not-leak"}
    });

    let (items, has_blocking, can_respond) =
        project_pending_hitl_for_test("clarification", "", Some(metadata));

    assert_eq!(items.len(), 1);
    assert!(has_blocking);
    assert!(can_respond);
    assert_eq!(items[0].request_type, SessionHitlKind::Permission);
    assert_eq!(items[0].question, "run the reviewed test command");
    assert_eq!(
        items[0]
            .permission
            .as_ref()
            .expect("permission contract must project")
            .description,
        "run the reviewed test command"
    );

    let (items, has_blocking, can_respond) = project_pending_hitl_for_test(
        "clarification",
        "",
        Some(json!({
            "hitl_type": "permission",
            "tool_name": "terminal.execute"
        })),
    );
    assert!(items.is_empty());
    assert!(has_blocking);
    assert!(!can_respond);
}

#[test]
fn standalone_projection_keeps_current_mode_and_stable_revision() {
    let source = || StandaloneConversationSource {
        id: "conversation-standalone".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        workspace_id: None,
        linked_workspace_task_id: None,
        workspace_name: None,
        user_id: "user-1".to_string(),
        title: "Standalone".to_string(),
        summary: None,
        status: "active".to_string(),
        current_mode: "explore".to_string(),
        conversation_mode: Some("single_agent".to_string()),
        agent_config: Some(json!({"capability_mode": "work"})),
        message_count: 0,
        participant_agents: Vec::new(),
        coordinator_agent_id: None,
        focused_agent_id: None,
        created_at: timestamp(10),
        updated_at: None,
    };
    let first = standalone_projection(source()).expect("projection must serialize");
    let second = standalone_projection(source()).expect("projection must serialize");
    let first = serde_json::to_value(first).expect("projection must serialize");
    let second = serde_json::to_value(second).expect("projection must serialize");

    assert_eq!(first["authority_kind"], "conversation_record");
    assert_eq!(first["conversation"]["current_mode"], "explore");
    assert_eq!(first["conversation"]["capability_mode"], "work");
    assert_eq!(first["snapshot_revision"], second["snapshot_revision"]);
}

#[derive(FromRow)]
struct VisibleConversationScope {
    id: String,
    tenant_id: String,
    project_id: String,
    workspace_id: Option<String>,
    user_id: String,
    current_mode: String,
}

#[tokio::test]
async fn postgres_projection_uses_repository_env_and_fails_closed() {
    let Ok(database_url) = crate::startup_config::repository_database_url() else {
        return;
    };
    let Ok(pool) = agistack_adapters_postgres::connect(database_url.expose()).await else {
        return;
    };
    let visible = sqlx::query_as::<_, VisibleConversationScope>(
        "SELECT c.id, c.tenant_id, c.project_id, c.workspace_id, c.user_id, c.current_mode \
         FROM conversations AS c \
         WHERE EXISTS ( \
             SELECT 1 FROM projects AS p \
             WHERE p.id = c.project_id AND p.tenant_id = c.tenant_id \
         ) \
           AND EXISTS ( \
             SELECT 1 FROM user_projects AS up \
             WHERE up.project_id = c.project_id AND up.user_id = c.user_id \
         ) \
           AND EXISTS ( \
             SELECT 1 FROM user_tenants AS ut \
             WHERE ut.tenant_id = c.tenant_id AND ut.user_id = c.user_id \
         ) \
           AND ( \
             c.linked_workspace_task_id IS NULL \
             OR EXISTS ( \
                 SELECT 1 FROM workspace_tasks AS task \
                 WHERE task.id = c.linked_workspace_task_id \
                   AND task.workspace_id = c.workspace_id \
                   AND task.archived_at IS NULL \
             ) \
           ) \
           AND ( \
             c.workspace_id IS NULL \
             OR EXISTS ( \
                 SELECT 1 FROM workspaces AS workspace \
                 JOIN workspace_members AS member ON member.workspace_id = workspace.id \
                 WHERE workspace.id = c.workspace_id \
                   AND workspace.tenant_id = c.tenant_id \
                   AND workspace.project_id = c.project_id \
                   AND workspace.is_archived = FALSE \
                   AND member.user_id = c.user_id \
             ) \
           ) \
         ORDER BY c.updated_at DESC NULLS LAST, c.created_at DESC \
         LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .expect("visible conversation lookup must succeed");
    let Some(scope) = visible else {
        return;
    };
    let mut shared_readers = Vec::new();
    if let Some(workspace_id) = scope.workspace_id.as_deref() {
        if let Some((reader_id,)) = sqlx::query_as::<_, (String,)>(
            "SELECT member.user_id \
             FROM workspace_members AS member \
             JOIN user_projects AS project_member \
               ON project_member.project_id = $2 \
              AND project_member.user_id = member.user_id \
             JOIN user_tenants AS tenant_member \
               ON tenant_member.tenant_id = $3 \
              AND tenant_member.user_id = member.user_id \
             WHERE member.workspace_id = $1 AND member.user_id <> $4 \
             ORDER BY member.user_id LIMIT 1",
        )
        .bind(workspace_id)
        .bind(&scope.project_id)
        .bind(&scope.tenant_id)
        .bind(&scope.user_id)
        .fetch_optional(&pool)
        .await
        .expect("workspace reader lookup must succeed")
        {
            shared_readers.push(reader_id);
        }
    }
    if let Some((admin_id,)) = sqlx::query_as::<_, (String,)>(
        "SELECT user_id FROM user_tenants \
         WHERE tenant_id = $1 AND role IN ('admin', 'owner') AND user_id <> $2 \
         ORDER BY user_id LIMIT 1",
    )
    .bind(&scope.tenant_id)
    .bind(&scope.user_id)
    .fetch_optional(&pool)
    .await
    .expect("tenant administrator lookup must succeed")
    {
        if !shared_readers.contains(&admin_id) {
            shared_readers.push(admin_id);
        }
    }
    let service = PgConversationSessionProjectionService::new(pool);
    let query = ConversationSessionQuery {
        tenant_id: scope.tenant_id.clone(),
        project_id: scope.project_id.clone(),
        workspace_id: scope.workspace_id.clone(),
    };
    let projection = service
        .get_projection(&scope.user_id, &scope.id, &query)
        .await
        .expect("projection query must succeed")
        .expect("visible conversation must project");
    let payload = serde_json::to_value(projection).expect("projection must serialize");
    assert_eq!(payload["conversation"]["current_mode"], scope.current_mode);

    for reader_id in shared_readers {
        let shared_projection = service
            .get_projection(&reader_id, &scope.id, &query)
            .await
            .expect("authorized shared reader lookup must succeed")
            .expect("workspace members and tenant administrators must read the session");
        let shared_payload =
            serde_json::to_value(shared_projection).expect("shared projection must serialize");
        assert_eq!(shared_payload["capabilities"]["can_send_message"], false);
        assert_eq!(
            shared_payload["capabilities"]["can_control_execution"],
            false
        );
    }

    let mut denied_scopes = vec![
        ConversationSessionQuery {
            tenant_id: "not-the-visible-tenant".to_string(),
            ..query.clone()
        },
        ConversationSessionQuery {
            project_id: "not-the-visible-project".to_string(),
            ..query.clone()
        },
        ConversationSessionQuery {
            workspace_id: Some("not-the-visible-workspace".to_string()),
            ..query.clone()
        },
    ];
    if scope.workspace_id.is_some() {
        denied_scopes.push(ConversationSessionQuery {
            workspace_id: None,
            ..query
        });
    }
    for denied_scope in denied_scopes {
        let denied = service
            .get_projection(&scope.user_id, &scope.id, &denied_scope)
            .await
            .expect("wrong-scope query must not fail");
        assert!(denied.is_none());
    }
    let denied_user = service
        .get_projection(
            "not-the-visible-user",
            &scope.id,
            &ConversationSessionQuery {
                tenant_id: scope.tenant_id,
                project_id: scope.project_id,
                workspace_id: scope.workspace_id,
            },
        )
        .await
        .expect("wrong-user query must not fail");
    assert!(denied_user.is_none());
}
