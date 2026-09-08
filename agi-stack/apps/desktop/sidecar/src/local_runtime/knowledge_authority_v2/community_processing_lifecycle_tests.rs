use super::*;

#[tokio::test]
async fn revoked_session_membership_and_changed_context_reject_late_output() {
    for sql in [
        "UPDATE desktop_user_sessions SET status='revoked'",
        "UPDATE desktop_user_sessions SET expires_at_ms=0",
        "UPDATE desktop_tenant_memberships SET role='viewer'",
        "UPDATE desktop_workspace_contexts SET revision=revision+1",
    ] {
        let f = CommunityFixture::new().await;
        let endpoint = CommunityEndpoint::new(&f, f.output(true)).await;
        let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
        endpoint.wait().await;
        f.base
            .state
            .session_store
            .connection()
            .unwrap()
            .execute_batch(sql)
            .unwrap();
        endpoint.release.notify_one();
        let record = run.await.unwrap().unwrap().unwrap();
        assert!(matches!(
            record.outcome,
            Some(CommunityAuditOutcome::Failed {
                code: CommunityAuditFailure::AdmissionChanged,
                ..
            })
        ));
        f.no_result();
    }
}

#[tokio::test]
async fn retired_generation_rejects_publication_but_keeps_storage_until_attempt_drains() {
    let f = CommunityFixture::new().await;
    let endpoint = CommunityEndpoint::new(&f, f.output(true)).await;
    let run = f.spawn(endpoint.provider(), ProcessingRunOptions::default());
    endpoint.wait().await;
    let (snapshot, generation) = stage(&f.base.directory, 2, false).await;
    let retirement = f
        .base
        .state
        .platform_plugin_authority_v2
        .replace_local_baseline(
            &snapshot,
            &serde_json::to_value(&snapshot).unwrap(),
            generation,
        );
    assert!(f.base.operation.authority.repository().is_ok());
    endpoint.release.notify_one();
    let record = run.await.unwrap().unwrap().unwrap();
    assert!(matches!(
        record.outcome,
        Some(CommunityAuditOutcome::Failed {
            code: CommunityAuditFailure::AdmissionChanged,
            ..
        })
    ));
    f.no_result();
    drop(f.base.operation);
    retirement.dispose().await;
}

#[tokio::test]
async fn renewal_keeps_slow_attempt_owned_beyond_original_deadline() {
    let f = CommunityFixture::new().await;
    let endpoint = CommunityEndpoint::new(&f, f.output(true)).await;
    let run = f.spawn(
        endpoint.provider(),
        ProcessingRunOptions {
            lease_ms: 500,
            renew_every_ms: 25,
        },
    );
    endpoint.wait().await;
    tokio::time::sleep(std::time::Duration::from_millis(650)).await;
    assert!(f
        .base
        .repo()
        .claim_community_job_durable(
            &f.base.operation.scope,
            &f.input.build_id,
            "competing",
            500,
            &|| Ok(chrono::Utc::now().timestamp_millis()),
        )
        .unwrap()
        .is_none());
    endpoint.release.notify_one();
    assert!(matches!(
        run.await.unwrap().unwrap().unwrap().outcome,
        Some(CommunityAuditOutcome::Applied { .. })
    ));
}

#[tokio::test]
async fn unavailable_provider_does_not_claim_a_community_job() {
    let f = CommunityFixture::new().await;
    assert!(f
        .base
        .operation
        .process_community_one(
            f.base.state.clone(),
            f.base.auth.clone(),
            "missing-workspace",
            &f.input.build_id,
            ProcessingRunOptions::default(),
        )
        .await
        .is_err());
    let status = f
        .base
        .repo()
        .community_job_status_durable(
            &f.base.operation.scope,
            &f.input.build_id,
            &f.input.candidate.membership_digest,
        )
        .unwrap()
        .unwrap();
    assert_eq!(status.attempt, 0);
    assert_eq!(status.state, CommunityJobState::Pending);
}

#[tokio::test]
async fn audit_begin_failure_releases_job_without_sending_provider_request() {
    let f = CommunityFixture::new().await;
    let endpoint = CommunityEndpoint::new(&f, f.output(true)).await;
    let db = rusqlite::Connection::open(f.base.directory.0.join("knowledge/memories.db")).unwrap();
    db.execute_batch("CREATE TRIGGER fail_community_audit BEFORE INSERT ON knowledge_community_audits BEGIN SELECT RAISE(ABORT,'injected'); END;").unwrap();
    assert!(f
        .spawn(endpoint.provider(), ProcessingRunOptions::default())
        .await
        .unwrap()
        .is_err());
    let status = f
        .base
        .repo()
        .community_job_status_durable(
            &f.base.operation.scope,
            &f.input.build_id,
            &f.input.candidate.membership_digest,
        )
        .unwrap()
        .unwrap();
    assert_eq!(status.state, CommunityJobState::Failed);
    assert!(f
        .base
        .repo()
        .community_audit_durable(
            &f.base.operation.scope,
            &f.input.build_id,
            &f.input.candidate.membership_digest,
            1,
        )
        .unwrap()
        .is_none());
    f.no_result();
}
