use super::*;
use std::{sync::mpsc, time::Duration};

#[tokio::test]
async fn generation_replacement_during_read_discards_the_old_snapshot() {
    let f = Fixture::new().await;
    f.operation
        .bootstrap(&f.state, &f.auth, &f.command(1))
        .unwrap();
    let (snapshot, generation) = stage(&f.directory, 2, true).await;
    let (entered, ready) = mpsc::channel();
    let (release, resume) = mpsc::channel();
    let operation = Arc::clone(&f.operation);
    let state = Arc::clone(&f.state);
    let auth = f.auth.clone();
    let worker = tokio::task::spawn_blocking(move || {
        operation.with_current_for_test(&state, &auth, false, |repo, current| {
            let calls = std::cell::Cell::new(0);
            repo.read_project_schema_durable(
                &KnowledgeScope {
                    tenant_id: auth.workspace.tenant_id.clone(),
                    project_id: auth.workspace.project_id.clone(),
                },
                &|| {
                    calls.set(calls.get() + 1);
                    if calls.get() == 2 {
                        entered.send(()).unwrap();
                        resume.recv_timeout(Duration::from_secs(3)).unwrap();
                    }
                    current()
                },
            )
        })
    });
    ready.recv_timeout(Duration::from_secs(3)).unwrap();
    let retirement = f.state.platform_plugin_authority_v2.replace_local_baseline(
        &snapshot,
        &serde_json::to_value(&snapshot).unwrap(),
        generation,
    );
    release.send(()).unwrap();
    assert!(matches!(
        worker.await.unwrap(),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::GenerationMismatch
        ))
    ));
    assert_eq!(f.counts(), (1, 1, 0));
    drop(f.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn write_holds_generation_until_commit_and_old_operation_fails_after_replacement() {
    let f = Fixture::new().await;
    let first = f.command(1);
    let (snapshot, generation) = stage(&f.directory, 2, true).await;
    let (entered, ready) = mpsc::channel();
    let (release, resume) = mpsc::channel();
    let operation = Arc::clone(&f.operation);
    let state = Arc::clone(&f.state);
    let auth = f.auth.clone();
    let worker = tokio::task::spawn_blocking(move || {
        operation.with_current_for_test(&state, &auth, true, |repo, current| {
            let calls = std::cell::Cell::new(0);
            repo.bootstrap_project_schema_durable(
                &KnowledgeScope {
                    tenant_id: auth.workspace.tenant_id.clone(),
                    project_id: auth.workspace.project_id.clone(),
                },
                &auth.user.user_id,
                &first,
                &|| {
                    calls.set(calls.get() + 1);
                    if calls.get() == 2 {
                        entered.send(()).unwrap();
                        resume.recv_timeout(Duration::from_secs(3)).unwrap();
                    }
                    current()
                },
            )
        })
    });
    ready.recv_timeout(Duration::from_secs(3)).unwrap();
    let (attempted, attempt) = mpsc::channel();
    let (published, publication) = mpsc::channel();
    let state = Arc::clone(&f.state);
    let replacement = tokio::task::spawn_blocking(move || {
        attempted.send(()).unwrap();
        let retirement = state.platform_plugin_authority_v2.replace_local_baseline(
            &snapshot,
            &serde_json::to_value(&snapshot).unwrap(),
            generation,
        );
        published.send(()).unwrap();
        retirement
    });
    attempt.recv_timeout(Duration::from_secs(3)).unwrap();
    assert!(matches!(
        publication.try_recv(),
        Err(mpsc::TryRecvError::Empty)
    ));
    release.send(()).unwrap();
    let accepted = worker.await.unwrap().unwrap();
    let retirement = replacement.await.unwrap();
    publication.recv_timeout(Duration::from_secs(3)).unwrap();
    assert!(matches!(
        f.operation.read(&f.state, &f.auth),
        Err(ProjectSchemaOperationError::Authority(
            KnowledgeAuthorityErrorV2::GenerationMismatch
        ))
    ));
    let current = admit(&f.state, &f.auth).unwrap();
    assert_eq!(
        current.read(&f.state, &f.auth).unwrap().as_ref(),
        Some(accepted.document())
    );
    assert_eq!(f.counts(), (1, 1, 0));
    drop(f.operation);
    retirement.dispose().await;
}
