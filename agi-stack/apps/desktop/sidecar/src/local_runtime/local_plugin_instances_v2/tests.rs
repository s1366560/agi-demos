use super::*;
use agistack_plugin_host::protocol_v2::ProfileSnapshotV2;

async fn setup() -> (
    Arc<LocalRuntimeState>,
    AuthenticatedContext,
    ProfileSnapshotV2,
) {
    let state = super::super::tests::test_state("local-instance-test");
    let auth = state
        .session_store
        .validate_session_credential("local-instance-test", chrono::Utc::now().timestamp_millis())
        .unwrap()
        .unwrap();
    let snapshot = super::super::platform_plugin_sync_v2::local_base_snapshot(&state).unwrap();
    let generation = super::super::platform_plugin_sync_v2::desktop_loader(None, None)
        .stage(snapshot.clone())
        .await
        .unwrap();
    state
        .platform_plugin_authority_v2
        .publish_local_baseline(&snapshot, &json!(snapshot), generation)
        .await;
    (state, auth, snapshot)
}

fn scope_request(auth: &AuthenticatedContext) -> ScopeRequest {
    ScopeRequest {
        tenant_id: auth.workspace.tenant_id.clone(),
        project_id: Some(auth.workspace.project_id.clone()),
    }
}

#[tokio::test]
async fn baseline_ack_is_durable_and_repeated_view_does_not_renew_it() {
    let (state, auth, _) = setup().await;
    let request = scope_request(&auth);
    let scope = require_scope(&state, &auth, &request).unwrap();
    let identity = configuration::authority(&scope).unwrap();
    let view = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(request),
    )
    .await
    .unwrap()
    .0;
    let stored =
        snapshots::read_state(&state.session_store.connection().unwrap(), &identity).unwrap();
    assert!(
        stored.is_some(),
        "baseline must be an acknowledged publication"
    );
    let digest = view["snapshot"]["digest"].as_str().unwrap();
    let _ = renderer_receipt(
        State(state.clone()),
        Extension(auth.clone()),
        Json(
            serde_json::from_value(json!({
                "tenant_id": auth.workspace.tenant_id, "project_id": auth.workspace.project_id,
                "snapshot_digest": digest, "status": "ack"
            }))
            .unwrap(),
        ),
    )
    .await
    .unwrap();
    let before = snapshots::read_state(&state.session_store.connection().unwrap(), &identity)
        .unwrap()
        .unwrap();
    assert_eq!(before.last_good.as_ref().unwrap().snapshot.digest, digest);
    let _ = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(scope_request(&auth)),
    )
    .await
    .unwrap();
    let after = snapshots::read_state(&state.session_store.connection().unwrap(), &identity)
        .unwrap()
        .unwrap();
    assert_eq!(before, after);
}

fn store_accepted(state: &LocalRuntimeState, scope: &ScopeV2, snapshot: &ProfileSnapshotV2) {
    let identity = configuration::authority(scope).unwrap();
    let publication = distribution(snapshot, 1).unwrap();
    let mut connection = state.session_store.connection().unwrap();
    snapshots::initialize_schema(&connection).unwrap();
    snapshots::record_requested(&connection, &identity, &publication).unwrap();
    snapshots::record_receipt(
        &mut connection,
        &identity,
        &publication.envelope.nonce,
        &SnapshotApplyReceiptV2 {
            status: ApplyStatusV2::Ack,
            requested_version: 1,
            requested_digest: snapshot.digest.clone(),
            applied_version: Some(1),
            applied_digest: Some(snapshot.digest.clone()),
            error_code: None,
            error_message: None,
        },
    )
    .unwrap();
}

#[tokio::test]
async fn previous_base_ack_does_not_mark_changed_base_ready() {
    let (state, auth, mut previous_base) = setup().await;
    let scope = require_scope(&state, &auth, &scope_request(&auth)).unwrap();
    previous_base
        .entries
        .iter_mut()
        .find(|entry| entry.entry_id == "builtin-desktop-settings-general")
        .unwrap()
        .enabled = false;
    let previous = configuration::compose(
        &previous_base,
        &configuration::baseline(&previous_base, &scope).unwrap(),
        &scope,
    )
    .unwrap();
    store_accepted(&state, &scope, &previous);
    assert_eq!(
        instance_view(&state, &auth, &scope).unwrap().0["publication"]["status"],
        "reconciling"
    );
    let next = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(scope_request(&auth)),
    )
    .await
    .unwrap()
    .0;
    assert_ne!(next["snapshot"]["digest"], previous.digest);
    let stale = renderer_receipt(
        State(state.clone()),
        Extension(auth.clone()),
        Json(ReceiptRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: Some(auth.workspace.project_id.clone()),
            snapshot_digest: previous.digest.clone(),
            status: ApplyStatusV2::Ack,
            error_code: None,
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(stale.1 .0["code"], "instance_receipt_superseded");
    let identity = configuration::authority(&scope).unwrap();
    let retained = snapshots::read_state(&state.session_store.connection().unwrap(), &identity)
        .unwrap()
        .unwrap()
        .last_good
        .unwrap();
    assert_eq!(retained.snapshot.digest, previous.digest);
}

#[tokio::test]
async fn accepted_disabled_ancestor_blocks_child_business_admission() {
    let (state, auth, mut base) = setup().await;
    let scope = require_scope(&state, &auth, &scope_request(&auth)).unwrap();
    let key = "builtin-desktop-feature-tenant-tenant-providers";
    let parent_id = base
        .entries
        .iter()
        .find(|entry| entry.entry_id == key)
        .unwrap()
        .parent_entry_id
        .clone()
        .unwrap();
    base.entries
        .iter_mut()
        .find(|entry| entry.entry_id == parent_id)
        .unwrap()
        .enabled = false;
    // Older persisted receipts may predate the ancestor preflight validation.
    let mut wire = json!(base);
    wire.as_object_mut().unwrap().remove("digest");
    use sha2::{Digest, Sha256};
    base.digest = format!("{:x}", Sha256::digest(serde_jcs::to_vec(&wire).unwrap()));
    store_accepted(&state, &scope, &base);
    assert_eq!(
        super::super::local_feature_authority_v2::require_feature(&state, &auth, key),
        Err("feature_disabled")
    );
    assert!(
        agistack_plugin_host::protocol_v2::validate_snapshot_target_v2(
            &base,
            &agistack_plugin_host::protocol_v2::DataPlaneTargetV2::DesktopRenderer
        )
        .is_err()
    );
}

#[tokio::test]
async fn tenant_renderer_view_accepts_a_receipt_without_project_edit_authority() {
    let (state, auth, _) = setup().await;
    let view = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(ScopeRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: None,
        }),
    )
    .await
    .unwrap()
    .0;
    let request: ReceiptRequest = serde_json::from_value(json!({
        "tenant_id": auth.workspace.tenant_id, "project_id": null,
        "snapshot_digest": view["snapshot"]["digest"], "status": "ack"
    }))
    .expect("tenant renderer delivery must accept its matching receipt");
    let receipt = renderer_receipt(State(state.clone()), Extension(auth.clone()), Json(request))
        .await
        .unwrap()
        .0;
    assert_eq!(receipt["status"], "ready");
    assert!(
        list(
            State(state),
            Extension(auth.clone()),
            Query(ScopeRequest {
                tenant_id: auth.workspace.tenant_id.clone(),
                project_id: None,
            })
        )
        .await
        .is_err(),
        "tenant-wide editing remains unavailable"
    );
}

#[tokio::test]
async fn unaccepted_baseline_fallback_never_contains_another_projects_entries() {
    let (state, auth, mut base) = setup().await;
    let scope = require_scope(&state, &auth, &scope_request(&auth)).unwrap();
    let key = "builtin-desktop-settings-general";
    let foreign = base
        .entries
        .iter_mut()
        .find(|entry| entry.entry_id == key)
        .unwrap();
    foreign.scope = ScopeV2 {
        kind: ScopeKindV2::Project,
        tenant_id: scope.tenant_id.clone(),
        project_id: Some("other-project".into()),
        session_id: None,
    };
    let retained = accepted_snapshot(&base, &scope, None).unwrap();
    assert!(!retained.entries.iter().any(|entry| entry.entry_id == key));
    assert!(base.entries.iter().any(|entry| entry.entry_id == key));
}

#[tokio::test]
async fn configuration_waits_for_renderer_receipt_and_preserves_scope() {
    let (state, auth, _) = setup().await;
    let key = "builtin-desktop-settings-general";
    let response = apply(
        State(state.clone()),
        Extension(auth.clone()),
        Json(ApplyRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
            expected_revision: 1,
            changes: vec![serde_json::from_value(json!({"entry_id":key,"enabled":false})).unwrap()],
        }),
    )
    .await
    .unwrap()
    .0;
    assert_eq!(response["revision"], 2);
    assert_eq!(response["publication"]["status"], "reconciling");
    let view = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(scope_request(&auth)),
    )
    .await
    .unwrap()
    .0;
    assert!(view["snapshot"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .any(|entry| entry["entry_id"] == key && entry["enabled"] == false));
    let _ = renderer_receipt(
        State(state.clone()),
        Extension(auth.clone()),
        Json(ReceiptRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: Some(auth.workspace.project_id.clone()),
            snapshot_digest: view["snapshot"]["digest"].as_str().unwrap().into(),
            status: ApplyStatusV2::Ack,
            error_code: None,
        }),
    )
    .await
    .unwrap();
    let listed = list(
        State(state.clone()),
        Extension(auth.clone()),
        Query(scope_request(&auth)),
    )
    .await
    .unwrap()
    .0;
    assert_eq!(listed["publication"]["status"], "ready");
    let tenant = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(ScopeRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: None,
        }),
    )
    .await
    .unwrap()
    .0;
    assert!(tenant["snapshot"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .any(|entry| entry["entry_id"] == key && entry["enabled"] == true));
    let denied = list(
        State(state),
        Extension(auth.clone()),
        Query(ScopeRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: Some("different-project".into()),
        }),
    )
    .await;
    assert!(denied.is_err());
}

#[tokio::test]
async fn stale_revision_and_self_disable_are_rejected_without_saving() {
    let (state, auth, _) = setup().await;
    for (expected_revision, entry_id, reason) in [
        (
            2,
            "builtin-desktop-settings-general",
            "instance_revision_conflict",
        ),
        (
            1,
            "builtin-desktop-feature-tenant-tenant-plugins",
            "instance_not_editable",
        ),
    ] {
        let error = apply(
            State(state.clone()),
            Extension(auth.clone()),
            Json(ApplyRequest {
                tenant_id: auth.workspace.tenant_id.clone(),
                project_id: auth.workspace.project_id.clone(),
                expected_revision,
                changes: vec![
                    serde_json::from_value(json!({"entry_id":entry_id,"enabled":false})).unwrap(),
                ],
            }),
        )
        .await
        .unwrap_err();
        assert_eq!(error.1 .0["code"], reason);
    }
    assert_eq!(
        list(
            State(state),
            Extension(auth.clone()),
            Query(scope_request(&auth))
        )
        .await
        .unwrap()
        .0["revision"],
        1
    );
}

#[tokio::test]
async fn rejected_renderer_candidate_preserves_durable_last_good_and_fences_late_receipts() {
    let (state, auth, _) = setup().await;
    let key = "builtin-desktop-settings-general";
    let mut last_digest = String::new();
    for (revision, enabled, status) in [
        (1, false, ApplyStatusV2::Ack),
        (2, true, ApplyStatusV2::Nack),
    ] {
        let _ = apply(
            State(state.clone()),
            Extension(auth.clone()),
            Json(ApplyRequest {
                tenant_id: auth.workspace.tenant_id.clone(),
                project_id: auth.workspace.project_id.clone(),
                expected_revision: revision,
                changes: vec![
                    serde_json::from_value(json!({"entry_id":key,"enabled":enabled})).unwrap(),
                ],
            }),
        )
        .await
        .unwrap();
        let view = renderer_view(
            State(state.clone()),
            Extension(auth.clone()),
            Query(scope_request(&auth)),
        )
        .await
        .unwrap()
        .0;
        let current_digest = view["snapshot"]["digest"].as_str().unwrap().to_owned();
        if revision == 2 {
            let stale = renderer_receipt(
                State(state.clone()),
                Extension(auth.clone()),
                Json(ReceiptRequest {
                    tenant_id: auth.workspace.tenant_id.clone(),
                    project_id: Some(auth.workspace.project_id.clone()),
                    snapshot_digest: last_digest.clone(),
                    status: ApplyStatusV2::Ack,
                    error_code: None,
                }),
            )
            .await
            .unwrap_err();
            assert_eq!(stale.1 .0["code"], "instance_receipt_superseded");
        } else {
            last_digest = current_digest.clone();
        }
        let _ = renderer_receipt(
            State(state.clone()),
            Extension(auth.clone()),
            Json(ReceiptRequest {
                tenant_id: auth.workspace.tenant_id.clone(),
                project_id: Some(auth.workspace.project_id.clone()),
                snapshot_digest: current_digest,
                status,
                error_code: Some("renderer_test_failure".into()),
            }),
        )
        .await
        .unwrap();
    }
    let scope = require_scope(&state, &auth, &scope_request(&auth)).unwrap();
    let identity = configuration::authority(&scope).unwrap();
    let stored = snapshots::read_state(&state.session_store.connection().unwrap(), &identity)
        .unwrap()
        .unwrap();
    assert_eq!(stored.configuration.unwrap().desired.revision, 3);
    assert_eq!(stored.last_good.unwrap().snapshot.digest, last_digest);
    let retained = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(scope_request(&auth)),
    )
    .await
    .unwrap()
    .0;
    assert_eq!(retained["snapshot"]["digest"], last_digest);
    let listed = list(
        State(state),
        Extension(auth.clone()),
        Query(scope_request(&auth)),
    )
    .await
    .unwrap()
    .0;
    assert_eq!(listed["publication"]["status"], "degraded");
    assert_eq!(
        listed["instances"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["entry_id"] == key)
            .unwrap()["state"]["status"],
        "failed"
    );
}

#[tokio::test]
async fn invalid_member_of_batch_does_not_save_any_change() {
    let (state, auth, _) = setup().await;
    let invalid = apply(State(state.clone()),Extension(auth.clone()),Json(ApplyRequest {
        tenant_id:auth.workspace.tenant_id.clone(),project_id:auth.workspace.project_id.clone(),expected_revision:1,
        changes:vec![serde_json::from_value(json!({"entry_id":"builtin-desktop-settings-general","enabled":false})).unwrap(),
          serde_json::from_value(json!({"entry_id":"builtin-desktop-feature-tenant-tenant-providers","config":{"id":"invalid","order":1,"contributions":[{"id":"untrusted","kind":"route","order":1,"payload":{"schema_version":1,"artifact_refs":["arbitrary-executable-module"]}}]}})).unwrap()],
    })).await;
    assert!(invalid.is_err());
    assert_eq!(
        list(
            State(state),
            Extension(auth.clone()),
            Query(scope_request(&auth))
        )
        .await
        .unwrap()
        .0["revision"],
        1
    );
}

#[tokio::test]
async fn renderer_artifact_contract_mismatch_is_rejected_before_saving() {
    for (invalid, expected) in [
        ("wrong-kind", "renderer_artifact_kind_mismatch"),
        ("duplicate-artifact", "renderer_artifact_conflict"),
    ] {
        let (state, auth, base) = setup().await;
        let key = "builtin-desktop-settings-general";
        let original = base
            .entries
            .iter()
            .find(|entry| entry.entry_id == key)
            .unwrap();
        let mut config = json!(original.config);
        if invalid == "wrong-kind" {
            config["contributions"][0]["kind"] = json!("route");
        } else {
            let mut duplicate = config["contributions"][0].clone();
            duplicate["id"] = json!("duplicate-artifact-owner");
            config["contributions"]
                .as_array_mut()
                .unwrap()
                .push(duplicate);
        }
        let result = apply(
            State(state.clone()),
            Extension(auth.clone()),
            Json(ApplyRequest {
                tenant_id: auth.workspace.tenant_id.clone(),
                project_id: auth.workspace.project_id.clone(),
                expected_revision: 1,
                changes: vec![
                    serde_json::from_value(json!({"entry_id": key, "config": config})).unwrap(),
                ],
            }),
        )
        .await;
        let Err(error) = result else {
            panic!("invalid renderer artifact was saved: {invalid}");
        };
        assert_eq!(error.1 .0["code"], expected);
        assert_eq!(
            list(
                State(state),
                Extension(auth.clone()),
                Query(scope_request(&auth))
            )
            .await
            .unwrap()
            .0["revision"],
            1
        );
    }
}

#[tokio::test]
async fn accepted_business_disable_blocks_new_operations_and_keeps_recovery_access() {
    use tower::ServiceExt;
    let (state, auth, _) = setup().await;
    let key = "builtin-desktop-feature-tenant-tenant-providers";
    let _ = apply(
        State(state.clone()),
        Extension(auth.clone()),
        Json(ApplyRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: auth.workspace.project_id.clone(),
            expected_revision: 1,
            changes: vec![serde_json::from_value(json!({"entry_id":key,"enabled":false})).unwrap()],
        }),
    )
    .await
    .unwrap();
    assert!(super::super::local_feature_authority_v2::require_feature(&state, &auth, key).is_ok());
    let view = renderer_view(
        State(state.clone()),
        Extension(auth.clone()),
        Query(scope_request(&auth)),
    )
    .await
    .unwrap()
    .0;
    let _ = renderer_receipt(
        State(state.clone()),
        Extension(auth.clone()),
        Json(ReceiptRequest {
            tenant_id: auth.workspace.tenant_id.clone(),
            project_id: Some(auth.workspace.project_id.clone()),
            snapshot_digest: view["snapshot"]["digest"].as_str().unwrap().into(),
            status: ApplyStatusV2::Ack,
            error_code: None,
        }),
    )
    .await
    .unwrap();
    let app = super::super::local_router(state);
    for (path, expected) in [
        (
            "/api/v1/llm-providers/?project_id=forged",
            StatusCode::FORBIDDEN,
        ),
        ("/api/v1/auth/me", StatusCode::OK),
    ] {
        let response = app
            .clone()
            .oneshot(
                axum::http::Request::builder()
                    .uri(path)
                    .header("authorization", "Bearer local-instance-test")
                    .body(axum::body::Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), expected);
    }
}
