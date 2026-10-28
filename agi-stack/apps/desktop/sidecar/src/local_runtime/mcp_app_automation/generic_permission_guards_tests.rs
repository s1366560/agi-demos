//! Authority revocations between capture and commit must never renew a surface.
use super::*;
use crate::local_runtime::{
    mcp_app_automation::generic_permission::LocalHumanResponseSurfaces,
    platform_plugin_authority_v2::ActivePlatformPluginGenerationLeaseV2,
};

struct Transition {
    waiting: DesktopRun,
    resumed: DesktopRun,
    request: DesktopHitlRequest,
    captured: LocalHumanResponseSurfaces,
    generation: ActivePlatformPluginGenerationLeaseV2,
}

impl Transition {
    async fn prepare(fixture: &FormalFixture) -> Self {
        Self::prepare_with_mount_change(fixture, None).await
    }

    async fn prepare_with_mount_change(fixture: &FormalFixture, change: Option<&str>) -> Self {
        let mut request = generic_permission(fixture).await;
        let waiting = fixture
            .state
            .session_store
            .run(&fixture.run.id)
            .unwrap()
            .unwrap();
        let captured = fixture
            .state
            .mcp_app_automation
            .capture_local_human_response(
                &waiting,
                &request,
                &fixture.conversation.tenant_id,
                &fixture.conversation.id,
            )
            .unwrap();
        if let Some(change) = change {
            let registry = &fixture.state.mcp_app_automation;
            if change == "cancelled" {
                registry
                    .cancel_mount(&fixture.renderer_id, "closed-mount")
                    .unwrap();
            }
            let pending = registry
                .attach_mount(&fixture.state, &fixture.renderer_id, "racing-mount")
                .unwrap();
            assert_eq!(pending["pending"], true);
        }
        let resumed = fixture
            .state
            .session_store
            .transition_run(
                &waiting.id,
                waiting.revision,
                DesktopRunStatus::Running,
                None,
                &now_iso(),
            )
            .unwrap();
        request.status = DesktopHitlStatus::Responded;
        request.response_data = Some(json!({"action":"allow","granted":true,"scope":"once"}));
        let generation = fixture
            .state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap();
        Self {
            waiting,
            resumed,
            request,
            captured,
            generation,
        }
    }

    fn apply(&self, fixture: &FormalFixture) {
        fixture
            .state
            .mcp_app_automation
            .resume_local_human_response(
                &fixture.state,
                &self.waiting,
                &self.resumed,
                &self.request,
                &self.captured,
                &fixture.conversation.id,
                &self.generation,
            );
    }
}

#[tokio::test]
async fn generic_permission_rejects_changed_attachment_scope_and_approval() {
    let fixture = FormalFixture::new().await;
    let mut transition = Transition::prepare(&fixture).await;
    let registry = &fixture.state.mcp_app_automation;
    let original = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    let original_waiting = transition.waiting.clone();
    let original_resumed = transition.resumed.clone();
    let original_request = transition.request.clone();
    for changed in [
        "cloud-origin",
        "tenant",
        "project",
        "conversation",
        "run",
        "revision",
        "engine",
        "device",
        "epoch",
        "generation",
        "detached",
        "registration",
        "mount_nonce",
        "mount_cancelled",
        "child",
        "app",
        "catalog",
        "server_revision",
        "denied",
        "pending",
        "repl_step",
        "paused",
        "cancelled",
        "resume_revision",
        "plan",
        "authorization",
    ] {
        let mut tab = original.clone();
        transition.waiting = original_waiting.clone();
        transition.resumed = original_resumed.clone();
        transition.request = original_request.clone();
        match changed {
            "cloud-origin" => tab.local_origin = false,
            "tenant" => tab.scope.tenant_id.push_str("-other"),
            "project" => tab.scope.project_id.push_str("-other"),
            "conversation" => tab.scope.conversation_id.push_str("-other"),
            "run" => tab.scope.run_id.push_str("-other"),
            "revision" => tab.scope.run_revision += 1,
            "engine" => tab.scope.engine_session_id.push_str("-other"),
            "device" => tab.scope.device_id = Some("other-device".into()),
            "epoch" => tab.scope.connection_epoch = Some(1),
            "generation" => tab.scope.generation += 1,
            "detached" => {
                tab.attached = false;
                tab.registration = None;
            }
            "mount_nonce" => tab.mount_nonce = Some("replacement-mount".into()),
            "mount_cancelled" => tab.mount_cancelled = true,
            "registration" => tab.registration = Some("replacement-handle".into()),
            "child" => {
                tab.child = Some(ChildIdentityV2 {
                    execution_id: "child".into(),
                    subagent_id: "child".into(),
                    run_id: fixture.run.id.clone(),
                    revision: fixture.run.revision,
                })
            }
            "app" => tab.app.revision += 1,
            "catalog" => tab.binding.catalog_digest.push_str("-changed"),
            "server_revision" => tab.binding.server_revision += 1,
            "denied" => transition.request.response_data = Some(json!({"granted":false})),
            "pending" => transition.request.status = DesktopHitlStatus::Pending,
            "repl_step" => {
                transition.request.decision.as_mut().unwrap().target.kind = "repl_step".into()
            }
            "paused" => transition.waiting.status = DesktopRunStatus::Paused,
            "cancelled" => transition.resumed.status = DesktopRunStatus::Cancelled,
            "resume_revision" => transition.resumed.revision += 1,
            "plan" => transition.resumed.plan_version_id.push_str("-other"),
            "authorization" => transition.resumed.authorization_snapshot = json!({"changed":true}),
            _ => unreachable!(),
        }
        let expected_scope = tab.scope.clone();
        registry
            .tabs
            .lock()
            .unwrap()
            .insert(fixture.renderer_id.clone(), tab);
        transition.apply(&fixture);
        assert_eq!(
            registry.tabs.lock().unwrap()[&fixture.renderer_id].scope,
            expected_scope,
            "{changed}"
        );
    }
    registry
        .tabs
        .lock()
        .unwrap()
        .insert(fixture.renderer_id.clone(), original);
    transition.waiting = original_waiting;
    transition.resumed = original_resumed;
    transition.request = original_request;
    registry.resume_local_human_response(
        &fixture.state,
        &transition.waiting,
        &transition.resumed,
        &transition.request,
        &transition.captured,
        "different-checkpoint-engine",
        &transition.generation,
    );
    assert_eq!(
        registry.tabs.lock().unwrap()[&fixture.renderer_id].scope,
        fixture.original_scope
    );
    fixture.finish(None).await;
}

#[tokio::test]
async fn generic_permission_does_not_restore_reset_closed_or_cancelled_surfaces() {
    for revoked in ["reset", "closed", "cancelled", "generation"] {
        let fixture = FormalFixture::new().await;
        let transition = Transition::prepare(&fixture).await;
        let registry = &fixture.state.mcp_app_automation;
        match revoked {
            "reset" => registry.reset_execution(&fixture.original_scope, &fixture.conversation.id),
            "closed" => {
                registry
                    .renderer_operation(
                        &fixture.state,
                        json!({"tabId":fixture.renderer_id,"operation":"detach","mountNonce":"fixture-mount"}),
                    )
                    .await
                    .unwrap();
            }
            "cancelled" => {
                fixture
                    .state
                    .session_store
                    .transition_run(
                        &fixture.run.id,
                        transition.resumed.revision,
                        DesktopRunStatus::Cancelled,
                        None,
                        &now_iso(),
                    )
                    .unwrap();
            }
            "generation" => {
                fixture
                    .state
                    .platform_plugin_authority_v2
                    .deactivate()
                    .await
            }
            _ => unreachable!(),
        }
        transition.apply(&fixture);
        let stored = registry
            .tabs
            .lock()
            .unwrap()
            .get(&fixture.renderer_id)
            .cloned();
        assert!(
            stored.is_none_or(|tab| tab.scope == fixture.original_scope),
            "{revoked}"
        );
        fixture.finish(None).await;
    }
}

#[tokio::test]
async fn generic_permission_cannot_renew_disabled_or_reconfigured_server() {
    for disabled in [false, true] {
        let fixture = FormalFixture::new().await;
        let transition = Transition::prepare(&fixture).await;
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
                    description: Some("reconfigured after capture".into()),
                    transport: server.transport,
                    command: server.command,
                    cwd: server.cwd,
                    vault_env_refs: server.vault_env_refs,
                    enabled: !disabled,
                },
                server.revision,
                "generic-server-reconfigure",
            )
            .unwrap();
        transition.apply(&fixture);
        assert_eq!(
            fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].scope,
            fixture.original_scope
        );
        fixture.finish(None).await;
    }
}

#[tokio::test]
async fn generic_permission_first_pending_mount_race_preserves_only_uncancelled_created_surface() {
    for change in ["first-mount", "cancelled"] {
        let fixture = FormalFixture::with_attachment(false).await;
        let transition = Transition::prepare_with_mount_change(&fixture, Some(change)).await;
        transition.apply(&fixture);
        let tab =
            fixture.state.mcp_app_automation.tabs.lock().unwrap()[&fixture.renderer_id].clone();
        assert_eq!(
            tab.scope.run_revision,
            if change == "first-mount" {
                transition.resumed.revision
            } else {
                fixture.original_scope.run_revision
            },
            "{change}"
        );
        assert!(!tab.attached);
        assert!(tab.registration.is_none());
        assert_eq!(tab.mount_nonce.as_deref(), Some("racing-mount"));
        fixture.finish(None).await;
    }
}
