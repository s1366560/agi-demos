use super::*;

#[test]
fn entity_keysets_are_stable_bound_and_exclude_new_source_changes() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        for id in ["one", "two", "three"] {
            create(&repo, &s, id, "Title", "needle").await;
            finish(&repo, &s, true).await;
        }
        let first = repo.entities(&s, &request(1)).await.unwrap();
        let cursor = first.next_cursor.clone().unwrap();
        create(&repo, &s, "four", "Title", "needle").await;
        finish(&repo, &s, true).await;
        let mut seen = vec![first.items[0].reference.clone()];
        let mut r = request(1);
        r.cursor = first.next_cursor;
        while r.cursor.is_some() {
            let page = repo.entities(&s, &r).await.unwrap();
            seen.extend(page.items.into_iter().map(|e| e.reference));
            r.cursor = page.next_cursor;
        }
        assert_eq!(seen.len(), 6);
        assert_eq!(
            seen.iter()
                .map(|x| format!("{}:{}", x.source.change_sequence, x.entity_index))
                .collect::<std::collections::BTreeSet<_>>()
                .len(),
            6
        );
        assert_eq!(
            repo.entities(&s, &request(100)).await.unwrap().items.len(),
            8
        );
        let mut r = request(1);
        r.cursor = Some(cursor);
        assert!(repo.entities(&scope("b", "p"), &r).await.is_err());
        assert!(repo.relationships(&s, &r).await.is_err());
        r.source = Some(seen[0].source.clone());
        assert!(repo.entities(&s, &r).await.is_err());
        let text = repo.search_text(&s, "needle", &request(1)).await.unwrap();
        let r = RetrievalRequest {
            cursor: text.next_cursor,
            ..request(1)
        };
        assert!(repo.search_text(&s, "Title", &r).await.is_err());
    });
}

#[test]
fn late_completed_audits_become_visible_on_fresh_traversal_and_deleted_rows_disappear_mid_page() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        create(&repo, &s, "late", "Title", "needle").await;
        let late = repo.claim(&s, "paused", 100, 100).await.unwrap().unwrap();
        for id in ["ready", "deleted"] {
            create(&repo, &s, id, "Title", "needle").await;
            finish(&repo, &s, true).await;
        }
        let first = repo.search_text(&s, "needle", &request(1)).await.unwrap();
        assert_eq!(first.items[0].source.memory_id, "ready");
        repo.delete(&s, "deleted", 1).await.unwrap();
        let next = repo
            .search_text(
                &s,
                "needle",
                &RetrievalRequest {
                    cursor: first.next_cursor,
                    ..request(1)
                },
            )
            .await
            .unwrap();
        assert!(next.items.is_empty());
        // Reclaiming the old attempt allows an audit to complete after the earlier traversal.
        let reclaimed = repo.claim(&s, "retry", 200, 100).await.unwrap().unwrap();
        assert_eq!(reclaimed.source, late.source);
        let invocation = ProcessingInvocation {
            agent_id: "extractor".into(),
            provider_id: "provider".into(),
            model_id: "model".into(),
            tool_name: SUBMIT_PROJECTION_TOOL.into(),
            contract_version: 1,
            input: ProcessingInput {
                source: late.source.clone(),
                title: "Title".into(),
                content: "needle".into(),
            },
        };
        repo.begin_processing_audit_durable(&s, &reclaimed, invocation, 200)
            .unwrap();
        repo.finish_processing_audit_durable(
            &s,
            &reclaimed,
            ProcessingAuditOutcome::Applied {
                submission: ProjectionSubmission {
                    source: late.source.clone(),
                    entities: vec![],
                    relationships: vec![],
                    rationale: "No facts".into(),
                },
            },
            201,
            1,
        )
        .unwrap();
        assert_eq!(
            repo.search_text(&s, "needle", &request(100))
                .await
                .unwrap()
                .items
                .iter()
                .map(|x| x.source.memory_id.as_str())
                .collect::<Vec<_>>(),
            vec!["late", "ready"]
        );
    });
}
