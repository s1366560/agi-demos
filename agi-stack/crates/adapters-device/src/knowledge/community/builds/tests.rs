use agistack_core::knowledge::processing::{audit::*, worker::*, *};
use agistack_core::Entity;
use futures::executor::block_on;

use super::*;

include!("../tests/fixtures.rs");

mod leases;
mod migration;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("community-build-{}.db", Uuid::new_v4())))
    }
    fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
    fn sql(&self) -> Connection {
        Connection::open(&self.0).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn request(key: &str) -> CommunityBuildRequest {
    CommunityBuildRequest {
        actor_id: "actor".into(),
        idempotency_key: key.into(),
        min_community_size: 2,
    }
}

async fn populated(repo: &SqliteKnowledgeRepository, s: &KnowledgeScope) -> CommunityBuildReceipt {
    create(repo, s, "one", "Title", "Content").await;
    finish(repo, s, true).await;
    repo.create_community_build(s, &request("build"), 10)
        .await
        .unwrap()
}

#[test]
fn fixed_input_replays_after_source_changes_and_reopen_without_rewriting() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let s = scope("a", "p");
        let receipt = populated(&repo, &s).await;
        assert_eq!(receipt.state, CommunityBuildState::Pending);
        assert_eq!(receipt.candidate_count, 1);
        let original = repo
            .community_build(&s, &receipt.build_id)
            .await
            .unwrap()
            .unwrap();
        let id = &original.candidates[0].membership_digest;
        let status = repo
            .community_job_status(&s, &receipt.build_id, id)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(status.state, CommunityJobState::Pending);
        assert_eq!(status.attempt, 0);
        let mut memory = repo.get(&s, "one").await.unwrap().unwrap();
        memory.metadata.insert("changed".into(), true.into());
        repo.update(&s, memory, 1).await.unwrap();
        assert_eq!(
            repo.create_community_build(&s, &request("build"), 20)
                .await
                .unwrap(),
            receipt
        );
        let mut conflicting = request("build");
        conflicting.min_community_size = 3;
        assert!(matches!(
            repo.create_community_build(&s, &conflicting, 21).await,
            Err(KnowledgeError::IdempotencyConflict)
        ));
        // Existing frozen input is protected even against accidental SQL updates.
        for sql in [
            "UPDATE knowledge_community_builds SET graph_digest='changed'",
            "UPDATE knowledge_community_candidates SET member_count=3",
            "UPDATE knowledge_community_members SET reference_json='{}'",
        ] {
            assert!(db.sql().execute_batch(sql).is_err());
        }
        drop(repo);
        let repo = db.open();
        assert_eq!(
            repo.community_build(&s, &receipt.build_id)
                .await
                .unwrap()
                .unwrap(),
            original
        );
        let new = repo
            .create_community_build(&s, &request("after-edit"), 30)
            .await
            .unwrap();
        assert_eq!(new.state, CommunityBuildState::CompletedEmpty);
        assert_ne!(new.graph_digest, receipt.graph_digest);
        assert_eq!(
            repo.create_community_build(&s, &request("build"), 40)
                .await
                .unwrap(),
            receipt
        );
    });
}

#[test]
fn empty_build_has_durable_completion_and_no_jobs_and_scopes_do_not_leak() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let receipt = repo
            .create_community_build(&s, &request("empty"), 10)
            .await
            .unwrap();
        assert_eq!(receipt.state, CommunityBuildState::CompletedEmpty);
        assert_eq!(receipt.candidate_count, 0);
        assert!(repo
            .claim_community_job(&s, &receipt.build_id, "worker", 20, 10)
            .await
            .unwrap()
            .is_none());
        for foreign in [scope("b", "p"), scope("a", "q")] {
            assert!(repo
                .community_build(&foreign, &receipt.build_id)
                .await
                .unwrap()
                .is_none());
            assert!(repo
                .claim_community_job(&foreign, &receipt.build_id, "worker", 20, 10)
                .await
                .unwrap()
                .is_none());
            let separate = repo
                .create_community_build(&foreign, &request("empty"), 10)
                .await
                .unwrap();
            assert_ne!(receipt.build_id, separate.build_id);
            assert_ne!(receipt.graph_digest, separate.graph_digest);
        }
        let mut another_actor = request("empty");
        another_actor.actor_id = "other".into();
        assert_ne!(
            receipt.build_id,
            repo.create_community_build(&s, &another_actor, 10)
                .await
                .unwrap()
                .build_id
        );
        assert!(repo
            .create_community_build(&scope("", "p"), &request("bad"), 10)
            .await
            .is_err());
        assert!(repo
            .create_community_build(&s, &request("bad-clock"), -1)
            .await
            .is_err());
    });
}

#[test]
fn candidate_insert_failure_rolls_back_entire_build_and_can_retry() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        create(&repo, &s, "one", "Title", "Content").await;
        finish(&repo, &s, true).await;
        repo.conn
            .lock()
            .unwrap()
            .execute_batch(
                "CREATE TRIGGER fail_job BEFORE INSERT ON knowledge_community_jobs
             BEGIN SELECT RAISE(ABORT,'test failure'); END;",
            )
            .unwrap();
        assert!(repo
            .create_community_build(&s, &request("atomic"), 10)
            .await
            .is_err());
        for table in [
            "knowledge_community_builds",
            "knowledge_community_candidates",
            "knowledge_community_members",
            "knowledge_community_jobs",
        ] {
            let count: u32 = repo
                .conn
                .lock()
                .unwrap()
                .query_row(&format!("SELECT count(*) FROM {table}"), [], |r| r.get(0))
                .unwrap();
            assert_eq!(count, 0);
        }
        repo.conn
            .lock()
            .unwrap()
            .execute_batch("DROP TRIGGER fail_job")
            .unwrap();
        assert_eq!(
            repo.create_community_build(&s, &request("atomic"), 10)
                .await
                .unwrap()
                .candidate_count,
            1
        );
    });
}

#[test]
fn prepared_snapshot_cas_rejects_edits_and_same_revision_late_completion() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let s = scope("a", "p");
        let mut memory = create(&repo, &s, "one", "Title", "Content").await;
        let pending = repo.community_snapshot_durable(&s, 2).unwrap();
        let candidates = SqliteKnowledgeRepository::community_candidates(&pending).unwrap();
        finish(&repo, &s, true).await;
        let result = transact(&repo, &|| Ok(10), |tx, now| {
            Ok((
                persist(tx, &s, &request("late"), &pending, &candidates, now)?,
                None,
            ))
        });
        assert!(matches!(result, Err(KnowledgeError::Conflict)));
        let complete = repo.community_snapshot_durable(&s, 2).unwrap();
        let candidates = SqliteKnowledgeRepository::community_candidates(&complete).unwrap();
        memory.metadata.insert("edit".into(), true.into());
        repo.update(&s, memory, 1).await.unwrap();
        let result = transact(&repo, &|| Ok(10), |tx, now| {
            Ok((
                persist(tx, &s, &request("edited"), &complete, &candidates, now)?,
                None,
            ))
        });
        assert!(matches!(result, Err(KnowledgeError::Conflict)));
        let count: u32 = repo
            .conn
            .lock()
            .unwrap()
            .query_row("SELECT count(*) FROM knowledge_community_builds", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(count, 0);
    });
}
