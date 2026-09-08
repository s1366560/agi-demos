use super::*;

#[test]
fn graph_source_preserves_exact_audit_and_rejects_changed_or_missing_sources() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let mut memory = create(&repo, &s, "memory", "Title", "Original").await;
        let source = finish(&repo, &s, true).await;
        let graph = repo
            .graph_source_durable(&s, &source, 1, &|| Ok(102))
            .unwrap();
        assert_eq!(graph.source, source);
        assert_eq!(graph.audit_attempt, 1);
        assert_eq!(graph.content, "Original");
        assert_eq!(graph.entities.len(), 2);
        assert_eq!(graph.relationships[0].target_index, 1);
        assert!(matches!(
            repo.graph_source_durable(&s, &source, 0, &|| Ok(102)),
            Err(KnowledgeError::InvalidInput)
        ));
        assert!(matches!(
            repo.graph_source_durable(&s, &source, 2, &|| Ok(102)),
            Err(KnowledgeError::Conflict)
        ));
        assert!(repo
            .graph_source_durable(&scope("b", "p"), &source, 1, &|| Ok(102))
            .is_err());
        let mut missing = source.clone();
        missing.memory_id = "absent".into();
        assert!(matches!(
            repo.graph_source_durable(&s, &missing, 1, &|| Ok(102)),
            Err(KnowledgeError::Conflict)
        ));
        memory.content = "Updated".into();
        repo.update(&s, memory, 1).await.unwrap();
        assert!(matches!(
            repo.graph_source_durable(&s, &source, 1, &|| Ok(102)),
            Err(KnowledgeError::Conflict)
        ));
    });
}

#[test]
fn graph_source_refuses_unaudited_deleted_failed_and_expired_reads() {
    block_on(async {
        for audited in [true, false] {
            let repo = SqliteKnowledgeRepository::in_memory().unwrap();
            let s = scope("a", "p");
            create(&repo, &s, "memory", "Title", "Original").await;
            let source = finish(&repo, &s, audited).await;
            if !audited {
                assert!(repo
                    .graph_source_durable(&s, &source, 1, &|| Ok(102))
                    .is_err());
            }
            assert!(repo
                .graph_source_durable(&s, &source, 1, &|| Err(KnowledgeError::Conflict))
                .is_err());
            repo.delete(&s, "memory", 1).await.unwrap();
            assert!(repo
                .graph_source_durable(&s, &source, 1, &|| Ok(102))
                .is_err());
        }
        let db = Database::new();
        let repo = db.open();
        let s = scope("a", "p");
        create(&repo, &s, "memory", "Title", "Original").await;
        let source = finish(&repo, &s, true).await;
        db.sql().execute_batch("UPDATE knowledge_processing_audits SET outcome_json='{\"status\":\"failed\",\"code\":\"cancelled\",\"response_digest\":null}'").unwrap();
        assert!(repo
            .graph_source_durable(&s, &source, 1, &|| Ok(102))
            .is_err());
    });
}

#[test]
fn graph_source_successful_empty_projection_is_not_a_missing_source() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let memory = create(&repo, &s, "empty", "Empty", "No facts").await;
        let lease = repo.claim(&s, "worker", 100, 100).await.unwrap().unwrap();
        repo.begin_processing_audit_durable(
            &s,
            &lease,
            ProcessingInvocation {
                agent_id: "extractor".into(),
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
            100,
        )
        .unwrap();
        repo.finish_processing_audit_durable(
            &s,
            &lease,
            ProcessingAuditOutcome::Applied {
                submission: ProjectionSubmission {
                    source: lease.source.clone(),
                    entities: vec![],
                    relationships: vec![],
                    rationale: "No entities are present.".into(),
                },
            },
            101,
            1,
        )
        .unwrap();
        let graph = repo
            .graph_source_durable(&s, &lease.source, 1, &|| Ok(102))
            .unwrap();
        assert!(graph.entities.is_empty());
        assert!(graph.relationships.is_empty());
        assert_eq!(graph.content, "No facts");
    });
}
