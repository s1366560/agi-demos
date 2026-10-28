//! Pending iframe identities cannot revive a cancelled mount or grant operations.
use super::*;

#[tokio::test]
async fn pending_mount_cancellation_precedes_prepare_and_old_cleanup_cannot_cancel_replacement() {
    let fixture = FormalFixture::with_attachment(false).await;
    generic_permission(&fixture).await;
    let registry = &fixture.state.mcp_app_automation;
    registry.cancel_mount(&fixture.renderer_id, "old").unwrap();
    assert!(registry.tabs.lock().unwrap()[&fixture.renderer_id].mount_cancelled);
    assert!(registry
        .attach_mount(&fixture.state, &fixture.renderer_id, "old")
        .is_err());
    let new = registry
        .attach_mount(&fixture.state, &fixture.renderer_id, "new")
        .unwrap();
    assert_eq!(new["pending"], true);
    registry.cancel_mount(&fixture.renderer_id, "old").unwrap();
    assert!(registry
        .attach_mount(&fixture.state, &fixture.renderer_id, "old")
        .is_err());
    assert_eq!(
        registry
            .attach_mount(&fixture.state, &fixture.renderer_id, "new")
            .unwrap()["pending"],
        true
    );
    assert!(registry
        .attach_mount(&fixture.state, &fixture.renderer_id, "unrelated")
        .is_err());
    let tab = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    assert_eq!(tab.mount_nonce.as_deref(), Some("new"));
    assert!(!tab.mount_cancelled);
    assert!(!tab.attached);
    assert!(tab.registration.is_none());
    assert_eq!(tab.scope, fixture.original_scope);
    assert!(registry
        .renderer_operation(
            &fixture.state,
            json!({
                "tabId":fixture.renderer_id,"operation":"resources/list","mountNonce":"new",
            })
        )
        .await
        .is_err());
    fixture.finish(None).await;
}

#[tokio::test]
async fn formal_generic_approval_never_revives_closed_reset_denied_or_revoked_pending_mounts() {
    for revoked in [
        "closed-created",
        "closed-pending",
        "reset",
        "denied",
        "generation",
    ] {
        let fixture = FormalFixture::with_attachment(false).await;
        let request = generic_permission(&fixture).await;
        let registry = &fixture.state.mcp_app_automation;
        expire_waiting_authority(&fixture);
        if revoked != "closed-created" {
            assert_eq!(
                registry
                    .attach_mount(&fixture.state, &fixture.renderer_id, "pending")
                    .unwrap()["pending"],
                true
            );
        }
        match revoked {
            "closed-created" | "closed-pending" => {
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
            _ => {}
        }
        let llm = fixture.llm(None);
        let (status, receipt) = post(
            &fixture.state,
            Some(&fixture.token),
            "/api/v1/agent/hitl/respond",
            command(&request, revoked != "denied"),
        )
        .await;
        if revoked == "generation" {
            assert_ne!(status, StatusCode::OK, "{receipt}");
        } else {
            assert_eq!(status, StatusCode::OK, "{receipt}");
            tokio::time::timeout(Duration::from_secs(10), llm.ready.notified())
                .await
                .unwrap();
        }
        let tab = registry
            .tabs
            .lock()
            .unwrap()
            .get(&fixture.renderer_id)
            .cloned();
        assert!(
            tab.is_none_or(|tab| tab.scope == fixture.original_scope
                && !tab.attached
                && tab.registration.is_none()),
            "{revoked}"
        );
        assert!(
            registry
                .attach_mount(&fixture.state, &fixture.renderer_id, "new-mount")
                .is_err(),
            "{revoked}"
        );
        assert_eq!(
            fixture.counts().await,
            json!({"main":0,"sibling":0,"hidden":0})
        );
        fixture
            .finish((revoked != "generation").then_some(llm.as_ref()))
            .await;
    }
}

#[tokio::test]
async fn pending_mount_strict_mode_replay_survives_expired_waiting_executor() {
    let fixture = FormalFixture::with_attachment(false).await;
    generic_permission(&fixture).await;
    let registry = &fixture.state.mcp_app_automation;
    // The real waiting engine releases its tool host. Model the registry's expired
    // Weak even though this fixture retains a separate host for inspection.
    expire_waiting_authority(&fixture);
    // React development StrictMode tears down its first setup before replaying.
    registry
        .cancel_mount(&fixture.renderer_id, "strict-old")
        .unwrap();
    assert!(registry.tabs.lock().unwrap()[&fixture.renderer_id].mount_cancelled);
    let replacement = registry.attach_mount(&fixture.state, &fixture.renderer_id, "strict-new");
    let tab = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    fixture.finish(None).await;
    assert_eq!(
        replacement.unwrap()["pending"],
        true,
        "the verified replacement may register identity while the old executor is gone"
    );
    assert_eq!(tab.mount_nonce.as_deref(), Some("strict-new"));
    assert!(!tab.mount_cancelled);
    assert!(!tab.attached);
    assert!(tab.registration.is_none());
    assert!(tab.cancelled_mounts.contains("strict-old"));
}

fn expire_waiting_authority(fixture: &FormalFixture) {
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

#[tokio::test]
async fn pending_mount_without_executor_rejects_foreign_origin_scope_and_catalog() {
    let fixture = FormalFixture::with_attachment(false).await;
    generic_permission(&fixture).await;
    expire_waiting_authority(&fixture);
    let registry = &fixture.state.mcp_app_automation;
    let original = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
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
        "child",
        "catalog",
        "server-revision",
    ] {
        let mut tab = original.clone();
        match changed {
            "cloud-origin" => tab.local_origin = false,
            "tenant" => tab.scope.tenant_id.push_str("-other"),
            "project" => tab.scope.project_id.push_str("-other"),
            "conversation" => tab.scope.conversation_id.push_str("-other"),
            "run" => tab.scope.run_id.push_str("-other"),
            "revision" => tab.scope.run_revision += 1,
            "engine" => tab.scope.engine_session_id.push_str("-other"),
            "device" => tab.scope.device_id = Some("device".into()),
            "epoch" => tab.scope.connection_epoch = Some(1),
            "generation" => tab.scope.generation += 1,
            "child" => {
                tab.child = Some(ChildIdentityV2 {
                    execution_id: "child".into(),
                    subagent_id: "child".into(),
                    run_id: fixture.run.id.clone(),
                    revision: fixture.run.revision,
                })
            }
            "catalog" => tab.binding.catalog_digest.push_str("-changed"),
            "server-revision" => tab.binding.server_revision += 1,
            _ => unreachable!(),
        }
        registry
            .tabs
            .lock()
            .unwrap()
            .insert(fixture.renderer_id.clone(), tab);
        assert!(
            registry
                .attach_mount(&fixture.state, &fixture.renderer_id, "untrusted")
                .is_err(),
            "{changed}"
        );
        let stored = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
        assert!(
            !stored.attached && stored.registration.is_none() && stored.mount_nonce.is_none(),
            "{changed}"
        );
    }
    assert_eq!(
        fixture.counts().await,
        json!({"main":0,"sibling":0,"hidden":0})
    );
    fixture.finish(None).await;
}

#[tokio::test]
async fn cloud_origin_with_local_scope_cannot_register_pending_or_gain_local_approval() {
    let mut fixture = FormalFixture::with_attachment(false).await;
    let registry = &fixture.state.mcp_app_automation;
    let local = registry
        .registered(
            &fixture.original_scope.run_id,
            &fixture.original_scope.engine_session_id,
        )
        .unwrap();
    let ExecutionAuthority::LocalRun(inner) = &*local else {
        panic!("fixture must start with genuine local authority");
    };
    // A cloud origin remains cloud even with identical local-shaped scope fields.
    registry.register_authority(Arc::new(ExecutionAuthority::CloudClaim(inner.clone())));
    let app = registry.tabs.lock().unwrap()[&fixture.renderer_id]
        .app
        .clone();
    let renderer_id = call_identity::scope(
        &ToolPolicyContext {
            session_id: &fixture.conversation.id,
            round: 2,
            tool: "render_main",
        },
        async {
            registry.open(
                &fixture.state,
                &fixture.run.id,
                &fixture.conversation.id,
                &app,
            )
        },
    )
    .await
    .unwrap();
    assert!(!registry.tabs.lock().unwrap()[&renderer_id].local_origin);
    fixture.renderer_id = renderer_id;
    let request = generic_permission(&fixture).await;
    expire_waiting_authority(&fixture);
    assert!(registry
        .attach_mount(&fixture.state, &fixture.renderer_id, "cloud")
        .is_err());
    let llm = fixture.llm(None);
    let (status, receipt) = post(
        &fixture.state,
        Some(&fixture.token),
        "/api/v1/agent/hitl/respond",
        command(&request, true),
    )
    .await;
    assert_eq!(status, StatusCode::OK, "{receipt}");
    tokio::time::timeout(Duration::from_secs(10), llm.ready.notified())
        .await
        .unwrap();
    let tab = registry.tabs.lock().unwrap()[&fixture.renderer_id].clone();
    assert_eq!(tab.scope, fixture.original_scope);
    assert!(registry
        .attach_mount(&fixture.state, &fixture.renderer_id, "cloud")
        .is_err());
    assert!(!tab.attached && tab.registration.is_none() && tab.mount_nonce.is_none());
    assert_eq!(
        fixture.counts().await,
        json!({"main":0,"sibling":0,"hidden":0})
    );
    fixture.finish(Some(&llm)).await;
}
