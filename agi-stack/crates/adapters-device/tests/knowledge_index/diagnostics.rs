use super::*;
use agistack_core::knowledge::diagnostics::DiagnosticRequest;
fn page(limit: usize) -> DiagnosticRequest {
    DiagnosticRequest {
        limit,
        cursor: None,
    }
}

#[test]
fn persisted_failure_pages_recover_and_retry_exact_current_input() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let b = build("tenant", "project", "build");
        for id in ["one", "two", "three"] {
            create(&repo, &b.scope, id).await;
            finish(&repo, &b.scope).await;
        }
        repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
        let config = repo
            .select_index_config_durable(&b, None, &|| Ok(110))
            .unwrap();
        for _ in 0..3 {
            let lease = repo
                .claim_index_durable(&config, "worker", 100, &|| Ok(110))
                .unwrap()
                .unwrap();
            repo.fail_index_durable(&lease, IndexFailure::ProviderUnavailable, &|| Ok(111))
                .unwrap();
        }
        drop(repo);
        let repo = db.open();
        let first = repo
            .failed_index_durable(&config, &page(1), &|| Ok(112))
            .unwrap();
        assert_eq!(first.items.len(), 1);
        let input = &first.items[0].input;
        let second = repo
            .failed_index_durable(
                &config,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: first.next_cursor.clone(),
                },
                &|| Ok(112),
            )
            .unwrap();
        assert_eq!(second.items.len(), 1);
        assert_ne!(input, &second.items[0].input);
        let third = repo
            .failed_index_durable(
                &config,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: second.next_cursor,
                },
                &|| Ok(112),
            )
            .unwrap();
        assert_eq!(third.items.len(), 1);
        assert!(third.next_cursor.is_none());
        assert!(repo
            .retry_index_durable(&config, input, first.items[0].attempt + 1, &|| Ok(112))
            .is_err());
        repo.retry_index_durable(&config, input, first.items[0].attempt, &|| Ok(112))
            .unwrap();
        assert_eq!(
            repo.failed_index_durable(&config, &page(100), &|| Ok(112))
                .unwrap()
                .items
                .len(),
            2
        );
        assert!(repo
            .retry_index_durable(&config, input, first.items[0].attempt, &|| Ok(112))
            .is_err());
        let mut replacement = repo
            .get(&b.scope, &second.items[0].input.source.memory_id)
            .await
            .unwrap()
            .unwrap();
        replacement.content = "Replaced".into();
        repo.update(&b.scope, replacement, 1).await.unwrap();
        assert_eq!(
            repo.failed_index_durable(&config, &page(100), &|| Ok(112))
                .unwrap()
                .items
                .len(),
            1
        );
        assert!(repo
            .retry_index_durable(
                &config,
                &second.items[0].input,
                second.items[0].attempt,
                &|| Ok(112)
            )
            .is_err());
        let reselected = repo
            .select_index_config_durable(&b, Some(1), &|| Ok(112))
            .unwrap();
        assert!(repo
            .failed_index_durable(&config, &page(1), &|| Ok(112))
            .is_err());
        assert!(repo
            .failed_index_durable(
                &reselected,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: first.next_cursor
                },
                &|| Ok(112)
            )
            .is_err());
        let mut wrong = reselected.clone();
        wrong.build.scope.tenant_id = "elsewhere".into();
        assert!(repo
            .failed_index_durable(&wrong, &page(1), &|| Ok(112))
            .is_err());
        for limit in [0, 101] {
            assert!(repo
                .failed_index_durable(&reselected, &page(limit), &|| Ok(112))
                .is_err());
        }
        let calls = std::cell::Cell::new(0);
        assert!(repo
            .failed_index_durable(&reselected, &page(1), &|| {
                calls.set(calls.get() + 1);
                if calls.get() == 1 {
                    Ok(112)
                } else {
                    Err(KnowledgeError::Conflict)
                }
            })
            .is_err());
        assert_eq!(calls.get(), 2);
    });
}

#[test]
fn extraction_failure_audits_are_scoped_current_paginated_and_metadata_only_after_reopen() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let scope = build("t", "p", "b").scope;
        for id in ["one", "two"] {
            create(&repo, &scope, id).await;
        }
        let mut source = None;
        for attempt in 1..=2 {
            let lease = repo
                .claim(&scope, "worker", 100, 100)
                .await
                .unwrap()
                .unwrap();
            if source.is_none() {
                source = Some(lease.source.clone());
            }
            let memory = repo
                .get(&scope, &lease.source.memory_id)
                .await
                .unwrap()
                .unwrap();
            repo.begin_processing_audit_durable(
                &scope,
                &lease,
                ProcessingInvocation {
                    agent_id: "agent".into(),
                    provider_id: "provider".into(),
                    model_id: "model".into(),
                    tool_name: SUBMIT_PROJECTION_TOOL.into(),
                    contract_version: 1,
                    input: ProcessingInput {
                        source: lease.source.clone(),
                        title: memory.title,
                        content: memory.content,
                    },
                },
                101,
            )
            .unwrap();
            repo.finish_processing_audit_durable(
                &scope,
                &lease,
                ProcessingAuditOutcome::Failed {
                    code: ProcessingAuditFailure::ProviderUnavailable,
                    response_digest: Some("ab".repeat(32)),
                },
                102,
                1,
            )
            .unwrap();
            if attempt == 1 {
                repo.retry(&scope, &lease.source, lease.attempt)
                    .await
                    .unwrap();
            }
        }
        let other = repo
            .claim(&scope, "worker", 100, 100)
            .await
            .unwrap()
            .unwrap();
        repo.fail(&scope, &other, ProcessingFailure::ModelUnconfigured, 101)
            .await
            .unwrap();
        drop(repo);
        let repo = db.open();
        let source = source.unwrap();
        let failed = repo
            .failed_processing_durable(&scope, &page(1), &|| Ok(103))
            .unwrap();
        assert_eq!(failed.items[0].source, source);
        assert_eq!(failed.items[0].attempt, 2);
        let second = repo
            .failed_processing_durable(
                &scope,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: failed.next_cursor.clone(),
                },
                &|| Ok(103),
            )
            .unwrap();
        assert_eq!(second.items.len(), 1);
        assert!(second.next_cursor.is_none());
        let audits = repo
            .processing_audit_summaries_durable(&scope, &source, &page(1), &|| Ok(103))
            .unwrap();
        assert_eq!(audits.items[0].attempt, 1);
        let output = serde_json::to_value(&audits).unwrap();
        assert!(output["items"][0].get("input").is_none());
        assert!(output["items"][0].get("response_digest").is_none());
        assert!(!serde_json::to_string(&audits).unwrap().contains("Content"));
        let last = repo
            .processing_audit_summaries_durable(
                &scope,
                &source,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: audits.next_cursor.clone(),
                },
                &|| Ok(103),
            )
            .unwrap();
        assert_eq!(last.items[0].attempt, 2);
        assert!(last.next_cursor.is_none());
        assert!(repo
            .processing_audit_summaries_durable(
                &scope,
                &other.source,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: audits.next_cursor
                },
                &|| Ok(103)
            )
            .is_err());
        let wrong = KnowledgeScope {
            tenant_id: "other".into(),
            project_id: scope.project_id.clone(),
        };
        assert!(repo
            .failed_processing_durable(&wrong, &page(1), &|| Ok(103))
            .unwrap()
            .items
            .is_empty());
        assert!(repo
            .failed_processing_durable(
                &wrong,
                &DiagnosticRequest {
                    limit: 1,
                    cursor: failed.next_cursor
                },
                &|| Ok(103)
            )
            .is_err());
        assert!(repo
            .processing_audit_summaries_durable(&wrong, &source, &page(1), &|| Ok(103))
            .is_err());
        let mut memory = repo.get(&scope, &source.memory_id).await.unwrap().unwrap();
        memory.content = "new content".into();
        repo.update(&scope, memory, 1).await.unwrap();
        assert!(repo
            .processing_audit_summaries_durable(&scope, &source, &page(1), &|| Ok(103))
            .is_err());
        assert_eq!(
            repo.failed_processing_durable(&scope, &page(10), &|| Ok(103))
                .unwrap()
                .items
                .len(),
            1
        );
    });
}
