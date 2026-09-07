use super::*;

#[test]
fn scoped_project_reads_preserve_source_positions_and_exclude_unaudited_work() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        for (tenant, project, audited) in [("a", "p", true), ("b", "p", true), ("a", "q", true)] {
            let scope = scope(tenant, project);
            create(&repo, &scope, "same-id", tenant, project).await;
            finish(&repo, &scope, audited).await;
        }
        let s = scope("a", "p");
        create(&repo, &s, "unaudited", "untrusted", "payload").await;
        finish(&repo, &s, false).await;
        let entities = repo.entities(&s, &request(100)).await.unwrap();
        assert_eq!(entities.items.len(), 2);
        let source = entities.items[0].reference.source.clone();
        assert_eq!(source.tenant_id, "a");
        assert_eq!(source.project_id, "p");
        assert_eq!(source.memory_id, "same-id");
        assert_eq!(entities.items[0].reference.entity_index, 0);
        assert_eq!(entities.items[1].reference.entity_index, 1);
        assert_eq!(entities.items[0].audit_attempt, 1);
        let relations = repo.relationships(&s, &request(100)).await.unwrap();
        assert_eq!(relations.items.len(), 1);
        assert_eq!(
            relations.items[0].source_entity,
            entities.items[0].reference
        );
        assert_eq!(
            relations.items[0].target_entity,
            entities.items[1].reference
        );
        let text = repo.search_text(&s, "a", &request(100)).await.unwrap();
        assert_eq!(text.items.len(), 1);
        assert_eq!(text.items[0].source, source);
        let mut r = request(100);
        r.source = Some(source.clone());
        assert_eq!(repo.entities(&s, &r).await.unwrap().items.len(), 2);
        r.source.as_mut().unwrap().tenant_id = "b".into();
        assert!(matches!(
            repo.entities(&s, &r).await,
            Err(KnowledgeError::InvalidInput)
        ));
    });
}

#[test]
fn updated_deleted_and_wrong_attempt_projections_are_invisible_even_without_cleanup_trigger() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let s = scope("a", "p");
        let mut memory = create(&repo, &s, "memory", "Title", "Old").await;
        let old = finish(&repo, &s, true).await;
        db.sql()
            .execute_batch("DROP TRIGGER knowledge_processing_enqueue")
            .unwrap();
        memory.content = "New".into();
        repo.update(&s, memory, 1).await.unwrap();
        assert!(repo
            .entities(&s, &request(100))
            .await
            .unwrap()
            .items
            .is_empty());
        let mut r = request(100);
        r.source = Some(old);
        assert!(repo.relationships(&s, &r).await.unwrap().items.is_empty());
        let other = scope("b", "p");
        // This fixture retains its original accepted revision while audit identity is damaged.
        let db2 = Database::new();
        let repo2 = db2.open();
        create(&repo2, &other, "memory", "Title", "Source").await;
        finish(&repo2, &other, true).await;
        db2.sql()
            .execute_batch("UPDATE knowledge_processing_jobs SET attempt=2")
            .unwrap();
        assert!(repo2
            .entities(&other, &request(100))
            .await
            .unwrap()
            .items
            .is_empty());
        db2.sql().execute_batch("UPDATE knowledge_processing_jobs SET attempt=1; UPDATE knowledge_processing_audits SET outcome_json='{\"status\":\"failed\",\"code\":\"cancelled\",\"response_digest\":null}'").unwrap();
        assert!(repo2
            .search_text(&other, "Source", &request(100))
            .await
            .unwrap()
            .items
            .is_empty());
        let repo3 = SqliteKnowledgeRepository::in_memory().unwrap();
        create(&repo3, &s, "deleted", "Title", "Source").await;
        finish(&repo3, &s, true).await;
        repo3.delete(&s, "deleted", 1).await.unwrap();
        assert!(repo3
            .entities(&s, &request(100))
            .await
            .unwrap()
            .items
            .is_empty());
    });
}

#[test]
fn literal_text_uses_no_wildcards_and_reads_survive_reopen() {
    block_on(async {
        let db = Database::new();
        let s = scope("a", "p");
        let repo = db.open();
        create(&repo, &s, "special", "100%_\\ exact", "你好 quoted ' text").await;
        let source = finish(&repo, &s, true).await;
        create(&repo, &s, "plain", "100XX exact", "plain").await;
        finish(&repo, &s, true).await;
        drop(repo);
        let repo = db.open();
        for literal in ["%", "_", "\\", "你好", "'"] {
            let page = repo.search_text(&s, literal, &request(100)).await.unwrap();
            assert_eq!(page.items.len(), 1);
            assert_eq!(page.items[0].source, source);
        }
        assert!(repo
            .search_text(&s, "EXACT", &request(100))
            .await
            .unwrap()
            .items
            .is_empty());
        assert!(repo.search_text(&s, "", &request(100)).await.is_err());
        assert!(repo.entities(&s, &request(0)).await.is_err());
        assert!(repo.entities(&s, &request(101)).await.is_err());
    });
}
