use super::*;

#[tokio::test]
async fn closed_release_never_opens_storage_for_internal_schema_admission() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, false).await;
    assert!(matches!(
        admit(&state, &authenticated(&state)),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::ReleaseClosed
        ))
    ));
    assert!(!directory.0.exists());
}

#[tokio::test]
async fn forged_scope_generation_or_revoked_session_fail_before_storage_is_opened() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let auth = authenticated(&state);
    for field in [
        "tenant",
        "project",
        "context",
        "profile",
        "generation",
        "digest",
    ] {
        let lease = Arc::new(
            state
                .platform_plugin_authority_v2
                .acquire_generation()
                .unwrap(),
        );
        let mut scope = operation_scope(&auth, &lease);
        match field {
            "tenant" => scope.tenant_id = "foreign-tenant".into(),
            "project" => scope.project_id = "foreign-project".into(),
            "context" => scope.context_revision += 1,
            "profile" => scope.profile_id = "foreign-profile".into(),
            "generation" => scope.generation += 1,
            _ => scope.digest = "0".repeat(64),
        }
        assert!(ProjectSchemaOperationV2::admit(&state, lease, &auth, &scope).is_err());
        assert!(!directory.0.exists(), "{field}");
    }
    state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_user_sessions SET status='revoked'")
        .unwrap();
    assert!(matches!(
        admit(&state, &auth),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::Forbidden
        ))
    ));
    assert!(!directory.0.exists());
}

#[tokio::test]
async fn live_auth_and_context_revocation_fence_every_read_write_and_receipt_replay() {
    for revoke in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_user_sessions SET expires_at_ms=0",
        "UPDATE desktop_users SET status='disabled'",
        "UPDATE desktop_tenants SET status='archived'",
        "UPDATE desktop_projects SET status='archived'",
        "UPDATE desktop_tenant_memberships SET status='suspended'",
        "UPDATE desktop_workspace_contexts SET revision=revision+1",
        "UPDATE desktop_workspace_contexts SET updated_at_ms=updated_at_ms+1",
    ] {
        let f = Fixture::new().await;
        let first = f.command(1);
        f.operation.bootstrap(&f.state, &f.auth, &first).unwrap();
        f.state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(revoke)
            .unwrap();
        f.reject_all(&first);
    }
}

#[tokio::test]
async fn pinned_old_lease_cannot_admit_or_execute_after_generation_replacement() {
    let f = Fixture::new().await;
    let first = f.command(1);
    f.operation.bootstrap(&f.state, &f.auth, &first).unwrap();
    let old_lease = Arc::new(
        f.state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let old_scope = operation_scope(&f.auth, &old_lease);
    let (snapshot, generation) = stage(&f.directory, 2, true).await;
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    f.reject_all(&first);
    assert!(matches!(
        ProjectSchemaOperationV2::admit(&f.state, old_lease.clone(), &f.auth, &old_scope),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::GenerationMismatch
        ))
    ));
    let current = admit(&f.state, &f.auth).unwrap();
    assert_eq!(
        current.read(&f.state, &f.auth).unwrap().unwrap().revision(),
        1
    );
    drop(old_lease);
    drop(f.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn stale_generation_preflight_never_opens_previous_or_current_storage() {
    let directory = TestDirectory::new();
    let state = test_state(TOKEN);
    publish(&state, &directory, 1, true).await;
    let auth = authenticated(&state);
    let old = Arc::new(
        state
            .platform_plugin_authority_v2
            .acquire_generation()
            .unwrap(),
    );
    let scope = operation_scope(&auth, &old);
    let (snapshot, generation) = stage(&directory, 2, true).await;
    let retirement = state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    assert!(matches!(
        ProjectSchemaOperationV2::admit(&state, old, &auth, &scope),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::GenerationMismatch
        ))
    ));
    assert!(!directory.0.exists());
    retirement.dispose().await;
}
