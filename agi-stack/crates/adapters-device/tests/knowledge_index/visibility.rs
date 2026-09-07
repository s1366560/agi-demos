use super::*;

#[test]
fn scoped_identical_ids_and_forged_lease_provenance_never_cross_boundaries() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        for (tenant, project) in [("a", "p"), ("b", "p"), ("a", "q")] {
            let b = build(tenant, project, "same-build");
            create(&repo, &b.scope, "same-id").await;
            finish(&repo, &b.scope).await;
            repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
            let lease = claim(&repo, &b, 110);
            for field in 0..9 {
                let mut forged = lease.clone();
                match field {
                    0 => forged.build.scope.tenant_id.push('x'),
                    1 => forged.build.scope.project_id.push('x'),
                    2 => forged.input.source.memory_id.push('x'),
                    3 => forged.input.source.revision += 1,
                    4 => forged.input.audit_attempt += 1,
                    5 => forged.input.input_digest = "ff".repeat(32),
                    6 => forged.token.push('x'),
                    7 => forged.worker_id.push('x'),
                    _ => forged.input_text.push('x'),
                }
                assert!(repo
                    .complete_index_durable(&forged, &[1.0, 0.0], &|| Ok(111))
                    .is_err());
            }
            repo.complete_index_durable(&lease, &[1.0, 0.0], &|| Ok(111))
                .unwrap();
            repo.promote_index_build_durable(&b, None, &|| Ok(112))
                .unwrap();
            let read = repo.read_active_index_durable(&b, &|| Ok(113)).unwrap();
            assert_eq!(read.vectors.len(), 1);
            assert_eq!(read.vectors[0].input.source.tenant_id, tenant);
            assert_eq!(read.vectors[0].input.source.project_id, project);
        }
    });
}

#[test]
fn late_applied_audits_and_new_documents_make_active_coverage_partial_until_reconciled() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let b = build("t", "p", "b");
        create(&repo, &b.scope, "late").await;
        let late = repo
            .claim(&b.scope, "extractor", 100, 100)
            .await
            .unwrap()
            .unwrap();
        create(&repo, &b.scope, "ready").await;
        finish(&repo, &b.scope).await;
        repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
        let ready = claim(&repo, &b, 110);
        assert_eq!(ready.input.source.memory_id, "ready");
        repo.complete_index_durable(&ready, &[1.0, 0.0], &|| Ok(111))
            .unwrap();
        repo.promote_index_build_durable(&b, None, &|| Ok(112))
            .unwrap();
        apply(&repo, &b.scope, &late, 120).await;
        let partial = repo.read_active_index_durable(&b, &|| Ok(121)).unwrap();
        assert_eq!(partial.coverage.current_sources, 2);
        assert_eq!(partial.coverage.completed_sources, 1);
        assert!(repo
            .promote_index_build_durable(&b, Some("b"), &|| Ok(122))
            .is_err());
        let indexed_late = claim(&repo, &b, 123);
        assert_eq!(indexed_late.input.source, late.source);
        repo.complete_index_durable(&indexed_late, &[0.0, 1.0], &|| Ok(124))
            .unwrap();
        create(&repo, &b.scope, "new").await;
        finish(&repo, &b.scope).await;
        let new = claim(&repo, &b, 125);
        assert_eq!(new.input.source.memory_id, "new");
        repo.complete_index_durable(&new, &[1.0, 1.0], &|| Ok(126))
            .unwrap();
        assert!(repo
            .read_active_index_durable(&b, &|| Ok(127))
            .unwrap()
            .coverage
            .complete());
    });
}

#[test]
fn edited_deleted_and_invalid_audit_sources_disappear_even_without_cleanup_trigger() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let b = build("t", "p", "b");
        let mut memory = create(&repo, &b.scope, "one").await;
        finish(&repo, &b.scope).await;
        repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
        let lease = claim(&repo, &b, 110);
        repo.complete_index_durable(&lease, &[1.0, 0.0], &|| Ok(111))
            .unwrap();
        repo.promote_index_build_durable(&b, None, &|| Ok(112))
            .unwrap();
        db.sql()
            .execute_batch("DROP TRIGGER knowledge_processing_enqueue")
            .unwrap();
        memory.content = "edited".into();
        repo.update(&b.scope, memory, 1).await.unwrap();
        assert!(repo
            .read_active_index_durable(&b, &|| Ok(113))
            .unwrap()
            .vectors
            .is_empty());
        assert!(repo.renew_index_durable(&lease, 100, &|| Ok(113)).is_err());
        create(&repo, &b.scope, "other").await;
        // Lost enqueue trigger deliberately prevents extraction/indexing of new rows.
        assert!(repo
            .claim_index_durable(&b, "worker", 100, &|| Ok(114))
            .unwrap()
            .is_none());
    });
    block_on(async {
        for invalid in [
            "UPDATE knowledge_processing_jobs SET attempt=attempt+1",
            "UPDATE knowledge_memories SET deleted=1",
            "UPDATE knowledge_processing_audits SET outcome_json='{\"status\":\"failed\"}'",
        ] {
            let db = Database::new();
            let repo = db.open();
            let b = build("t", "p", "b");
            create(&repo, &b.scope, "one").await;
            finish(&repo, &b.scope).await;
            repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
            let lease = claim(&repo, &b, 110);
            repo.complete_index_durable(&lease, &[1.0, 0.0], &|| Ok(111))
                .unwrap();
            repo.promote_index_build_durable(&b, None, &|| Ok(112))
                .unwrap();
            db.sql().execute_batch(invalid).unwrap();
            assert!(repo
                .read_active_index_durable(&b, &|| Ok(113))
                .unwrap()
                .vectors
                .is_empty());
        }
    });
}

#[test]
fn active_lease_source_edit_or_audit_inconsistency_blocks_all_late_transitions() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let b = build("t", "p", "b");
        let mut memory = create(&repo, &b.scope, "one").await;
        finish(&repo, &b.scope).await;
        repo.begin_index_build_durable(&b, &|| Ok(110)).unwrap();
        let lease = claim(&repo, &b, 110);
        memory.content = "edited while embedding".into();
        repo.update(&b.scope, memory, 1).await.unwrap();
        assert!(repo
            .complete_index_durable(&lease, &[1.0, 0.0], &|| Ok(111))
            .is_err());
        assert!(repo
            .fail_index_durable(&lease, IndexFailure::Cancelled, &|| Ok(111))
            .is_err());
        assert!(repo.renew_index_durable(&lease, 100, &|| Ok(111)).is_err());
        finish(&repo, &b.scope).await;
        let current = claim(&repo, &b, 112);
        assert_ne!(current.input.input_digest, lease.input.input_digest);
        db.sql().execute_batch("UPDATE knowledge_derived_projections SET projection_json='{\"entities\":[{\"name\":\"tampered\",\"kind\":\"Other\"}],\"relationships\":[]}'").unwrap();
        assert!(repo
            .complete_index_durable(&current, &[1.0, 0.0], &|| Ok(113))
            .is_err());
        assert!(repo
            .promote_index_build_durable(&b, None, &|| Ok(113))
            .is_err());
    });
}
