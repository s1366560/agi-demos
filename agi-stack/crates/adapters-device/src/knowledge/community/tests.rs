use super::*;
use agistack_core::knowledge::processing::{worker::*, *};
use agistack_core::Entity;
use futures::executor::block_on;

include!("tests/fixtures.rs");

#[test]
fn metadata_only_edit_invalidates_old_projection_and_preserves_nested_evidence() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let mut memory = create(&repo, &s, "one", "Title", "Unchanged content").await;
        finish(&repo, &s, true).await;
        let original = repo.community_snapshot(&s, 2).await.unwrap();
        let metadata = serde_json::json!({
            "release": {"version": 2, "reviewed": true},
            "labels": ["one", "two"], "optional": null
        });
        memory.metadata = metadata.as_object().unwrap().clone();
        repo.update(&s, memory, 1).await.unwrap();
        let edited = repo.community_snapshot(&s, 2).await.unwrap();
        assert_eq!(edited.sources[0].source.revision, 2);
        assert_eq!(edited.sources[0].payload["metadata"], metadata);
        assert_eq!(
            edited.sources[0].payload["content"],
            original.sources[0].payload["content"]
        );
        assert!(edited.sources[0].audited_projection.is_none());
        assert_ne!(edited.graph_digest, original.graph_digest);
        assert!(SqliteKnowledgeRepository::community_candidates(&edited)
            .unwrap()
            .is_empty());
        finish(&repo, &s, true).await;
        let completed = repo.community_snapshot(&s, 2).await.unwrap();
        assert_eq!(completed.sources[0].payload["metadata"], metadata);
        assert_ne!(completed.graph_digest, edited.graph_digest);
        assert_eq!(
            SqliteKnowledgeRepository::community_candidates(&completed)
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            original.sources[0].payload["metadata"],
            serde_json::json!({})
        );
    });
}

#[test]
fn complete_coverage_and_source_local_members_survive_repeated_reads() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        for id in ["one", "two"] {
            create(&repo, &s, id, "Same title", "Same content").await;
            finish(&repo, &s, true).await;
        }
        create(&repo, &s, "legacy", "Title", "Content").await;
        finish(&repo, &s, false).await;
        create(&repo, &s, "pending", "Title", "Content").await;
        for foreign in [scope("b", "p"), scope("a", "q")] {
            create(&repo, &foreign, "one", "Foreign", "Foreign").await;
            finish(&repo, &foreign, true).await;
        }
        let snapshot = repo.community_snapshot(&s, 2).await.unwrap();
        assert_eq!(snapshot.sources.len(), 4);
        assert_eq!(
            snapshot
                .sources
                .iter()
                .filter(|s| s.audited_projection.is_some())
                .count(),
            2
        );
        assert_eq!(snapshot, repo.community_snapshot(&s, 2).await.unwrap());
        let candidates = SqliteKnowledgeRepository::community_candidates(&snapshot).unwrap();
        assert_eq!(candidates.len(), 2);
        assert_ne!(
            candidates[0].membership_digest,
            candidates[1].membership_digest
        );
        for candidate in candidates {
            assert_eq!(candidate.members.len(), 2);
            assert_eq!(candidate.members[0].source, candidate.members[1].source);
            assert_ne!(
                candidate.members[0].entity_index,
                candidate.members[1].entity_index
            );
            assert_eq!(candidate.members[0].source.tenant_id, "a");
        }
    });
}

#[test]
fn edits_deletes_and_late_audited_completion_change_snapshot_fingerprint() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let empty = repo.community_snapshot(&s, 2).await.unwrap();
        assert!(SqliteKnowledgeRepository::community_candidates(&empty)
            .unwrap()
            .is_empty());
        let mut memory = create(&repo, &s, "one", "Title", "Original").await;
        let pending = repo.community_snapshot(&s, 2).await.unwrap();
        finish(&repo, &s, true).await;
        let complete = repo.community_snapshot(&s, 2).await.unwrap();
        assert_eq!(pending.sources[0].source, complete.sources[0].source);
        assert_ne!(pending.graph_digest, complete.graph_digest);
        assert!(pending.sources[0].audited_projection.is_none());
        memory.content = "Edited".into();
        repo.update(&s, memory, 1).await.unwrap();
        let edited = repo.community_snapshot(&s, 2).await.unwrap();
        assert_eq!(edited.sources[0].source.revision, 2);
        assert!(edited.sources[0].audited_projection.is_none());
        assert_ne!(complete.graph_digest, edited.graph_digest);
        finish(&repo, &s, true).await;
        let reprocessed = repo.community_snapshot(&s, 2).await.unwrap();
        assert_ne!(edited.graph_digest, reprocessed.graph_digest);
        assert_ne!(
            SqliteKnowledgeRepository::community_candidates(&complete).unwrap(),
            SqliteKnowledgeRepository::community_candidates(&reprocessed).unwrap()
        );
        repo.delete(&s, "one", 2).await.unwrap();
        assert_eq!(empty, repo.community_snapshot(&s, 2).await.unwrap());
        // Captured evidence is immutable even when the live source disappears.
        assert_eq!(complete.sources[0].payload["content"], "Original");
    });
}

#[test]
fn failed_sources_and_algorithm_parameters_are_fingerprinted() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        create(&repo, &s, "one", "Title", "Content").await;
        let pending = repo.community_snapshot(&s, 2).await.unwrap();
        let lease = repo.claim(&s, "worker", 100, 100).await.unwrap().unwrap();
        repo.fail(&s, &lease, ProcessingFailure::ProviderUnavailable, 101)
            .await
            .unwrap();
        let failed = repo.community_snapshot(&s, 2).await.unwrap();
        assert_eq!(
            failed.sources[0].processing_state,
            Some(ProcessingState::Failed)
        );
        assert_ne!(pending.graph_digest, failed.graph_digest);
        assert_ne!(
            failed.graph_digest,
            repo.community_snapshot(&s, 3).await.unwrap().graph_digest
        );
        assert!(repo.community_snapshot(&s, 1).await.is_err());
        assert!(repo.community_snapshot(&scope("", "p"), 2).await.is_err());
        let mut tampered = failed;
        tampered.sources[0].payload["content"] = "tampered".into();
        assert!(SqliteKnowledgeRepository::community_candidates(&tampered).is_err());
    });
}

#[test]
fn read_transaction_keeps_one_revision_while_another_connection_commits() {
    block_on(async {
        let path =
            std::env::temp_dir().join(format!("community-snapshot-{}.db", uuid::Uuid::new_v4()));
        let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        repo.conn
            .lock()
            .unwrap()
            .execute_batch("PRAGMA journal_mode=WAL")
            .unwrap();
        let s = scope("a", "p");
        let mut memory = create(&repo, &s, "one", "Title", "Original").await;
        finish(&repo, &s, true).await;
        let other = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        let mut conn = repo.conn.lock().unwrap();
        let tx = conn.transaction().unwrap();
        let before = capture(&tx, &s, 2).unwrap();
        memory.content = "Concurrent edit".into();
        other.update(&s, memory, 1).await.unwrap();
        // Same transaction observes complete old source + old audit, never a
        // mix of new payload and earlier derived output.
        assert_eq!(before, capture(&tx, &s, 2).unwrap());
        tx.commit().unwrap();
        drop(conn);
        let after = repo.community_snapshot(&s, 2).await.unwrap();
        assert_eq!(after.sources[0].source.revision, 2);
        assert!(after.sources[0].audited_projection.is_none());
        drop(other);
        drop(repo);
        std::fs::remove_file(path).unwrap();
    });
}

#[test]
fn matching_success_receipt_is_required_and_inconsistent_audit_fails_closed() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        create(&repo, &s, "one", "Title", "Content").await;
        finish(&repo, &s, true).await;
        let original = repo.community_snapshot(&s, 2).await.unwrap();
        repo.conn
            .lock()
            .unwrap()
            .execute_batch("UPDATE knowledge_processing_jobs SET attempt=2")
            .unwrap();
        let mismatched = repo.community_snapshot(&s, 2).await.unwrap();
        assert!(mismatched.sources[0].audited_projection.is_none());
        assert_ne!(original.graph_digest, mismatched.graph_digest);
        repo.conn.lock().unwrap().execute_batch("UPDATE knowledge_processing_jobs SET attempt=1;
          UPDATE knowledge_processing_audits SET invocation_json=json_set(invocation_json,'$.input.content','Wrong source')").unwrap();
        assert!(repo.community_snapshot(&s, 2).await.is_err());
    });
}

#[test]
fn canonical_memberships_ignore_source_iteration_order_and_reject_bad_references() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        for id in ["one", "two"] {
            create(&repo, &s, id, "Title", "Content").await;
            finish(&repo, &s, true).await;
        }
        let mut snapshot = repo.community_snapshot(&s, 2).await.unwrap();
        let expected = partition_snapshot(&snapshot).unwrap();
        snapshot.sources.reverse();
        assert_eq!(expected, partition_snapshot(&snapshot).unwrap());
        snapshot.sources[0]
            .audited_projection
            .as_mut()
            .unwrap()
            .projection
            .relationships[0]
            .source_index = 99;
        assert!(partition_snapshot(&snapshot).is_err());
        let mut foreign = repo.community_snapshot(&s, 2).await.unwrap();
        foreign.sources[0].source.tenant_id = "foreign".into();
        assert!(partition_snapshot(&foreign).is_err());
    });
}
