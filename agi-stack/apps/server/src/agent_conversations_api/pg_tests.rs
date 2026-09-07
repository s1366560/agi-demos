use super::*;
use crate::conversation_authority::test_support::{workspace_fixture, VisibleConversationScope};
use crate::workspace_authority::{test_support::FixedWorkspaceAuthority, WorkspaceAuthorityScope};
use agistack_adapters_postgres::PgPool;

struct WorkspaceProfiles(BTreeMap<String, WorkspaceAuthorityProfile>);

#[async_trait]
impl crate::workspace_authority::WorkspaceAuthority for WorkspaceProfiles {
    async fn authorize(
        &self,
        _user_id: &str,
        workspace_id: &str,
    ) -> Result<Option<WorkspaceAuthorityScope>, crate::workspace_authority::WorkspaceAuthorityError>
    {
        Ok(self
            .0
            .get(workspace_id)
            .map(|profile| profile.scope.clone()))
    }

    async fn read_profile(
        &self,
        _user_id: &str,
        workspace_id: &str,
        _task_id: Option<&str>,
    ) -> Result<
        Option<WorkspaceAuthorityProfile>,
        crate::workspace_authority::WorkspaceAuthorityError,
    > {
        Ok(self.0.get(workspace_id).cloned())
    }
}

fn service(pool: PgPool, authority: SharedWorkspaceAuthority) -> PgAgentConversationService {
    PgAgentConversationService::new(
        PgAgentConversationRepository::new(pool.clone()),
        PgAgentExecutionEventRepository::new(pool.clone()),
        PgHitlRequestRepository::new(pool.clone()),
        PgConversationSessionProjectionService::new(pool, authority.clone()),
        authority,
    )
}

fn profile(scope: &VisibleConversationScope) -> WorkspaceAuthorityProfile {
    WorkspaceAuthorityProfile {
        scope: WorkspaceAuthorityScope {
            tenant_id: scope.tenant_id.clone(),
            project_id: scope.project_id.clone(),
            workspace_id: scope.workspace_id.clone().unwrap(),
            is_archived: false,
        },
        name: "Authorized Core workspace".into(),
        task_linked: true,
    }
}

#[tokio::test]
async fn postgres_owner_send_and_stop_require_current_core_authority() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    for condition in ["revoked", "archived", "unavailable", "allowed"] {
        let mut authority = FixedWorkspaceAuthority::new(Some(profile(&scope)), &[&scope.user_id]);
        match condition {
            "revoked" => authority.users.clear(),
            "archived" => authority.profile.as_mut().unwrap().scope.is_archived = true,
            "unavailable" => authority.available = false,
            _ => {}
        }
        let api = service(pool.clone(), Arc::new(authority));
        for access in [
            api.authorize_message_send(&scope.user_id, &scope.id, &scope.project_id)
                .await,
            api.authorize_session_stop(&scope.user_id, &scope.id).await,
        ] {
            match condition {
                "unavailable" => {
                    assert_eq!(access.unwrap_err().status, StatusCode::SERVICE_UNAVAILABLE)
                }
                "allowed" => assert_eq!(access.unwrap(), ConversationSocketAccess::Allowed),
                _ => assert_eq!(access.unwrap(), ConversationSocketAccess::Denied),
            }
        }
    }
}

#[tokio::test]
async fn postgres_mode_rebind_requires_source_workspace_before_target() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    sqlx::query("UPDATE pg_temp.conversations SET linked_workspace_task_id = NULL")
        .execute(&pool)
        .await
        .unwrap();
    let mut target = profile(&scope);
    target.scope.workspace_id = "allowed-target-workspace".into();
    let authority = Arc::new(FixedWorkspaceAuthority::new(
        Some(target),
        &[&scope.user_id],
    ));
    let api = service(pool.clone(), authority.clone());
    let result = api
        .update_conversation_mode(
            &scope.user_id,
            &scope.id,
            &scope.project_id,
            UpdateConversationModeRequest {
                conversation_mode: None,
                workspace_id: Some(Some("allowed-target-workspace".into())),
                linked_workspace_task_id: None,
            },
        )
        .await;
    assert_eq!(result.unwrap_err().status, StatusCode::FORBIDDEN);
    let workspace: Option<String> =
        sqlx::query_scalar("SELECT workspace_id FROM pg_temp.conversations")
            .fetch_one(&pool)
            .await
            .unwrap();
    assert_eq!(workspace, scope.workspace_id);
    assert_eq!(
        authority.requests.lock().unwrap()[0].1,
        scope.workspace_id.unwrap()
    );
}

#[tokio::test]
async fn postgres_list_authorizes_legacy_metadata_and_identifier_workspace() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    for legacy in ["metadata", "identifier"] {
        sqlx::query("UPDATE pg_temp.conversations SET workspace_id = NULL, meta = $1, id = $2")
            .bind(if legacy == "metadata" {
                json!({"workspace_id": scope.workspace_id})
            } else {
                json!({})
            })
            .bind(if legacy == "identifier" {
                format!("workspace-chat:{}", scope.workspace_id.as_deref().unwrap())
            } else {
                scope.id.clone()
            })
            .execute(&pool)
            .await
            .unwrap();
        for condition in ["revoked", "archived", "unavailable", "allowed"] {
            let mut authority =
                FixedWorkspaceAuthority::new(Some(profile(&scope)), &[&scope.user_id]);
            match condition {
                "revoked" => authority.users.clear(),
                "archived" => authority.profile.as_mut().unwrap().scope.is_archived = true,
                "unavailable" => authority.available = false,
                _ => {}
            }
            let api = service(pool.clone(), Arc::new(authority));
            let result = api
                .list_conversations(
                    &scope.user_id,
                    ConversationListRequest {
                        project_id: scope.project_id.clone(),
                        status: None,
                        limit: None,
                        offset: None,
                        workspace_id: None,
                    },
                )
                .await;
            if condition == "allowed" {
                let result = result.unwrap();
                assert_eq!(result.items.len(), 1);
                assert_eq!(
                    result.items[0].workspace_name.as_deref(),
                    Some("Authorized Core workspace")
                );
            } else {
                assert_eq!(
                    result.unwrap_err().status,
                    if condition == "unavailable" {
                        StatusCode::SERVICE_UNAVAILABLE
                    } else {
                        StatusCode::FORBIDDEN
                    }
                );
            }
        }
    }
}

#[tokio::test]
async fn postgres_standalone_owner_send_stop_and_mode_do_not_require_core() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    sqlx::query("UPDATE pg_temp.conversations SET workspace_id = NULL, linked_workspace_task_id = NULL, meta = '{}'::json")
        .execute(&pool).await.unwrap();
    let mut authority = FixedWorkspaceAuthority::new(None, &[]);
    authority.available = false;
    let authority = Arc::new(authority);
    let api = service(pool, authority.clone());
    assert_eq!(
        api.authorize_message_send(&scope.user_id, &scope.id, &scope.project_id)
            .await
            .unwrap(),
        ConversationSocketAccess::Allowed
    );
    assert_eq!(
        api.authorize_session_stop(&scope.user_id, &scope.id)
            .await
            .unwrap(),
        ConversationSocketAccess::Allowed
    );
    api.update_conversation_mode(
        &scope.user_id,
        &scope.id,
        &scope.project_id,
        UpdateConversationModeRequest {
            conversation_mode: Some(Some("build".into())),
            workspace_id: None,
            linked_workspace_task_id: None,
        },
    )
    .await
    .unwrap();
    assert!(authority.requests.lock().unwrap().is_empty());
}

#[tokio::test]
async fn postgres_mode_rebind_checks_both_workspace_grants() {
    let Some((pool, scope)) = workspace_fixture().await else {
        return;
    };
    sqlx::query("UPDATE pg_temp.conversations SET linked_workspace_task_id = NULL")
        .execute(&pool)
        .await
        .unwrap();
    let source = profile(&scope);
    let mut target = source.clone();
    target.scope.workspace_id = "target-workspace".into();
    for grants in [
        vec![target.clone()],
        vec![source.clone()],
        vec![source.clone(), target.clone()],
    ] {
        let both = grants.len() == 2;
        let authority = WorkspaceProfiles(
            grants
                .into_iter()
                .map(|profile| (profile.scope.workspace_id.clone(), profile))
                .collect(),
        );
        let api = service(pool.clone(), Arc::new(authority));
        let result = api
            .update_conversation_mode(
                &scope.user_id,
                &scope.id,
                &scope.project_id,
                UpdateConversationModeRequest {
                    conversation_mode: None,
                    workspace_id: Some(Some(target.scope.workspace_id.clone())),
                    linked_workspace_task_id: None,
                },
            )
            .await;
        if both {
            assert_eq!(
                result.unwrap().workspace_id,
                Some(target.scope.workspace_id.clone())
            );
        } else {
            assert_eq!(result.unwrap_err().status, StatusCode::FORBIDDEN);
            let stored: Option<String> =
                sqlx::query_scalar("SELECT workspace_id FROM pg_temp.conversations")
                    .fetch_one(&pool)
                    .await
                    .unwrap();
            assert_eq!(stored, scope.workspace_id);
        }
    }
}
