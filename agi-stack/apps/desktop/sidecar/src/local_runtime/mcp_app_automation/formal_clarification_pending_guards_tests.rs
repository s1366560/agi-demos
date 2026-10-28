//! NeedsInput pending identity registration never revives revoked authority.
use super::*;

fn expire_authority(fixture: &FormalFixture) {
    fixture
        .state
        .mcp_app_automation
        .authorities
        .lock()
        .unwrap()
        .insert(
            (
                fixture.original_scope.run_id.clone(),
                fixture.original_scope.engine_session_id.clone(),
            ),
            Weak::new(),
        );
}

fn resumed_run(fixture: &FormalFixture, waiting: &DesktopRun) -> DesktopRun {
    fixture
        .state
        .session_store
        .transition_run(
            &waiting.id,
            waiting.revision,
            DesktopRunStatus::Running,
            None,
            &now_iso(),
        )
        .unwrap()
}

fn accepted_answer(request: &mut DesktopHitlRequest) {
    request.status = DesktopHitlStatus::Responded;
    request.response_data = Some(json!({"answer":"The original App is mounted."}));
}

#[tokio::test]
async fn formal_clarification_pending_mount_rejects_revocation_before_response() {
    for revoked in ["closed", "reset", "generation", "disabled", "reconfigured"] {
        let fixture = FormalFixture::with_attachment(false).await;
        let mut request = super::super::clarification_tests::clarification(&fixture).await;
        expire_authority(&fixture);
        let registry = &fixture.state.mcp_app_automation;
        assert_eq!(
            registry
                .attach_mount(&fixture.state, &fixture.renderer_id, "pending")
                .unwrap()["pending"],
            true
        );
        let waiting = fixture
            .state
            .session_store
            .run(&fixture.run.id)
            .unwrap()
            .unwrap();
        let generation = fixture
            .state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap();
        match revoked {
            "closed" => {
                registry
                    .cancel_mount(&fixture.renderer_id, "pending")
                    .unwrap();
            }
            "reset" => registry.reset_execution(&fixture.original_scope, &fixture.conversation.id),
            "generation" => {
                fixture
                    .state
                    .platform_plugin_authority_v2
                    .deactivate()
                    .await
            }
            "disabled" | "reconfigured" => {
                let scope = McpScope {
                    tenant_id: fixture.conversation.tenant_id.clone(),
                    project_id: fixture.conversation.project_id.clone(),
                };
                let server = fixture
                    .state
                    .mcp_supervisor
                    .server(&scope, &fixture.server_id)
                    .unwrap()
                    .unwrap();
                fixture
                    .state
                    .mcp_supervisor
                    .update_server(
                        &scope,
                        &server.id,
                        McpServerDefinitionInput {
                            name: server.name,
                            description: Some("changed before clarification response".into()),
                            transport: server.transport,
                            command: server.command,
                            cwd: server.cwd,
                            vault_env_refs: server.vault_env_refs,
                            enabled: revoked != "disabled",
                        },
                        server.revision,
                        "clarification-server-reconfigure",
                    )
                    .unwrap();
            }
            _ => unreachable!(),
        }
        let captured = registry
            .capture_local_human_response(
                &waiting,
                &request,
                &fixture.conversation.tenant_id,
                &fixture.conversation.id,
            )
            .unwrap();
        let resumed = resumed_run(&fixture, &waiting);
        accepted_answer(&mut request);
        registry.resume_local_human_response(
            &fixture.state,
            &waiting,
            &resumed,
            &request,
            &captured,
            &fixture.conversation.id,
            &generation,
        );
        let stored = registry
            .tabs
            .lock()
            .unwrap()
            .get(&fixture.renderer_id)
            .cloned();
        let replacement_denied = registry
            .attach_mount(&fixture.state, &fixture.renderer_id, "new-after-answer")
            .is_err();
        let visible = registry.list(&fixture.state, &fixture.original_scope);
        let permissions = fixture
            .state
            .run_once_tool_permissions
            .lock()
            .unwrap()
            .len();
        let original_scope = fixture.original_scope.clone();
        fixture.finish(None).await;
        assert!(
            stored.is_none_or(|tab| tab.scope == original_scope
                && !tab.attached
                && tab.registration.is_none()),
            "{revoked}"
        );
        assert!(replacement_denied, "{revoked}");
        assert_eq!(visible, json!([]), "{revoked}");
        assert_eq!(permissions, 0, "{revoked}");
    }
}

#[tokio::test]
async fn formal_clarification_capture_cannot_renew_a_replacement_mount() {
    for already_pending in [false, true] {
        let fixture = FormalFixture::with_attachment(false).await;
        let mut request = super::super::clarification_tests::clarification(&fixture).await;
        expire_authority(&fixture);
        let registry = &fixture.state.mcp_app_automation;
        if already_pending {
            assert_eq!(
                registry
                    .attach_mount(&fixture.state, &fixture.renderer_id, "captured")
                    .unwrap()["pending"],
                true
            );
        }
        let waiting = fixture
            .state
            .session_store
            .run(&fixture.run.id)
            .unwrap()
            .unwrap();
        let captured = registry
            .capture_local_human_response(
                &waiting,
                &request,
                &fixture.conversation.tenant_id,
                &fixture.conversation.id,
            )
            .unwrap();
        registry
            .cancel_mount(&fixture.renderer_id, "captured")
            .unwrap();
        assert_eq!(
            registry
                .attach_mount(&fixture.state, &fixture.renderer_id, "replacement")
                .unwrap()["pending"],
            true
        );
        let resumed = resumed_run(&fixture, &waiting);
        accepted_answer(&mut request);
        let generation = fixture
            .state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap();
        registry.resume_local_human_response(
            &fixture.state,
            &waiting,
            &resumed,
            &request,
            &captured,
            &fixture.conversation.id,
            &generation,
        );
        let stored = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
        let replacement_denied = registry
            .attach_mount(&fixture.state, &fixture.renderer_id, "replacement")
            .is_err();
        let counts = fixture.counts().await;
        let original_scope = fixture.original_scope.clone();
        fixture.finish(None).await;
        assert_eq!(
            stored.scope, original_scope,
            "already_pending={already_pending}"
        );
        assert_eq!(stored.mount_nonce.as_deref(), Some("replacement"));
        assert!(stored.cancelled_mounts.contains("captured"));
        assert!(!stored.attached && stored.registration.is_none());
        assert!(replacement_denied);
        assert_eq!(counts, json!({"main":0,"sibling":0,"hidden":0}));
    }
}
