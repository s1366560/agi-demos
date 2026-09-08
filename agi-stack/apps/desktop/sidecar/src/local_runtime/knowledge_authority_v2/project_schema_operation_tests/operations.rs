use super::*;

#[tokio::test]
async fn reads_stay_absent_and_explicit_commands_preserve_typed_cas_and_exact_replay() {
    let f = Fixture::new().await;
    let first = f.command(1);
    assert!(f.operation.read(&f.state, &f.auth).unwrap().is_none());
    assert!(f
        .operation
        .receipt(&f.state, &f.auth, &first.change_id)
        .unwrap()
        .is_none());
    let empty = f.operation.history(&f.state, &f.auth, 0, 100).unwrap();
    assert_eq!(empty.upper_revision, 0);
    assert!(empty.items.is_empty());
    assert_eq!(f.counts(), (0, 0, 0));
    let accepted = f.operation.bootstrap(&f.state, &f.auth, &first).unwrap();
    assert_eq!(accepted.actor_id(), f.auth.user.user_id);
    let second = f.command(2);
    f.operation.replace(&f.state, &f.auth, &second).unwrap();
    assert_eq!(
        f.operation
            .bootstrap(&f.state, &f.auth, &first)
            .unwrap()
            .as_json(),
        accepted.as_json()
    );
    assert_eq!(
        f.operation
            .receipt(&f.state, &f.auth, &first.change_id)
            .unwrap(),
        Some(accepted)
    );
    assert!(matches!(
        f.operation.replace(&f.state, &f.auth, &f.command(2)),
        Err(ProjectSchemaOperationError::Storage(
            ProjectSchemaStorageError::Document(ProjectSchemaError::RevisionConflict)
        ))
    ));
    let mut reused = f.command(3);
    reused.change_id = second.change_id;
    assert!(matches!(
        f.operation.replace(&f.state, &f.auth, &reused),
        Err(ProjectSchemaOperationError::Storage(
            ProjectSchemaStorageError::ChangeIdReused
        ))
    ));
    assert!(matches!(
        f.operation.history(&f.state, &f.auth, 0, 0),
        Err(ProjectSchemaOperationError::Storage(
            ProjectSchemaStorageError::InvalidInput
        ))
    ));
    let page = f.operation.history(&f.state, &f.auth, 0, 1).unwrap();
    assert_eq!((page.upper_revision, page.items.len()), (2, 1));
    assert_eq!(
        f.operation
            .read(&f.state, &f.auth)
            .unwrap()
            .unwrap()
            .revision(),
        2
    );
    assert_eq!(f.counts(), (1, 2, 0));
}

#[tokio::test]
async fn caller_cannot_substitute_document_scope_or_authenticated_actor_context() {
    let f = Fixture::new().await;
    let mut foreign = f.auth.clone();
    foreign.workspace.project_id = "foreign-project".into();
    assert!(matches!(
        f.operation
            .bootstrap(&f.state, &f.auth, &command(&foreign, 1)),
        Err(ProjectSchemaOperationError::Storage(
            ProjectSchemaStorageError::ScopeMismatch
        ))
    ));
    for field in ["actor", "session", "context", "scope"] {
        let mut forged = f.auth.clone();
        match field {
            "actor" => forged.user.user_id = "foreign-user".into(),
            "session" => forged.session_id = "foreign-session".into(),
            "context" => forged.workspace.revision += 1,
            _ => forged.workspace.project_id = "foreign-project".into(),
        }
        assert!(matches!(
            f.operation.bootstrap(&f.state, &forged, &f.command(1)),
            Err(ProjectSchemaOperationError::Authority(_))
        ));
    }
    assert_eq!(f.counts(), (0, 0, 0));
}

#[tokio::test]
async fn live_viewer_can_read_but_cannot_write_or_replay_previously_authorized_writes() {
    let f = Fixture::new().await;
    let first = f.command(1);
    let receipt = f.operation.bootstrap(&f.state, &f.auth, &first).unwrap();
    f.state
        .session_store
        .connection()
        .unwrap()
        .execute_batch("UPDATE desktop_tenant_memberships SET role='viewer'")
        .unwrap();
    assert!(f.operation.read(&f.state, &f.auth).unwrap().is_some());
    assert_eq!(
        f.operation.history(&f.state, &f.auth, 0, 10).unwrap().items,
        vec![receipt.clone()]
    );
    assert_eq!(
        f.operation
            .receipt(&f.state, &f.auth, &first.change_id)
            .unwrap(),
        Some(receipt)
    );
    assert!(matches!(
        f.operation.bootstrap(&f.state, &f.auth, &first),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::Forbidden
        ))
    ));
    let auth = authenticated(&f.state);
    assert_eq!(auth.membership_role, "viewer");
    let viewer = admit(&f.state, &auth).unwrap();
    assert!(viewer.read(&f.state, &auth).unwrap().is_some());
    assert!(matches!(
        viewer.replace(&f.state, &auth, &f.command(2)),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::Forbidden
        ))
    ));
    assert_eq!(f.counts(), (1, 1, 0));
}
