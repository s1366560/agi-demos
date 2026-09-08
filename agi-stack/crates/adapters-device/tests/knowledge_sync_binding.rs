use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::sync::push::{KnowledgePushRepository, KnowledgeSyncTarget};
use agistack_core::knowledge::sync::{KnowledgeSyncLink, KnowledgeSyncRepository};
use agistack_core::knowledge::{KnowledgeError, KnowledgeScope};
use futures::executor::block_on;
use std::cell::Cell;
use uuid::Uuid;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-binding-{}.db", Uuid::new_v4())))
    }
    fn open(&self) -> SqliteKnowledgeRepository {
        SqliteKnowledgeRepository::open(self.0.to_str().unwrap()).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}
fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "local-tenant".into(),
        project_id: "local-project".into(),
    }
}
fn target() -> KnowledgeSyncTarget {
    KnowledgeSyncTarget {
        authority: "https://cloud.example/api/v1".into(),
        link: KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into(),
        },
    }
}

#[test]
fn verified_binding_survives_restart_and_rejects_origin_or_identity_rebinding() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        let original = repo
            .bind_verified_sync_target_durable(&scope(), &target(), &|| Ok(()))
            .unwrap();
        assert_eq!(original.link, Some(target().link));
        assert_eq!(
            repo.bind_verified_sync_target_durable(&scope(), &target(), &|| Ok(()))
                .unwrap()
                .replica_id,
            original.replica_id
        );
        // Preparing no changes succeeds because the origin is already bound.
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        drop(repo);
        let reopened = db.open();
        assert_eq!(
            reopened
                .bind_verified_sync_target_durable(&scope(), &target(), &|| Ok(()))
                .unwrap()
                .replica_id,
            original.replica_id
        );
        for field in ["authority", "tenant", "project", "actor"] {
            let mut other = target();
            match field {
                "authority" => other.authority = "https://other.example/api/v1".into(),
                "tenant" => other.link.remote_tenant_id = "other".into(),
                "project" => other.link.remote_project_id = "other".into(),
                _ => other.link.remote_actor_id = "other".into(),
            }
            assert!(matches!(
                reopened.bind_verified_sync_target_durable(&scope(), &other, &|| Ok(())),
                Err(KnowledgeError::Conflict)
            ));
        }
        assert_eq!(
            reopened.sync_status(&scope()).await.unwrap().link,
            original.link
        );
    });
}

#[test]
fn origin_insert_failure_or_final_identity_expiry_rolls_back_both_binding_tables() {
    block_on(async {
        for fail_at_commit in [false, true] {
            let db = Database::new();
            let repo = db.open();
            let connection = rusqlite::Connection::open(&db.0).unwrap();
            if !fail_at_commit {
                connection.execute_batch("CREATE TRIGGER fail_origin BEFORE INSERT ON knowledge_sync_targets BEGIN SELECT RAISE(ABORT,'fixture'); END;").unwrap();
            }
            let checks = Cell::new(0);
            let clock = || {
                checks.set(checks.get() + 1);
                if fail_at_commit && checks.get() == 2 {
                    return Err(KnowledgeError::Conflict);
                }
                Ok(())
            };
            assert!(repo
                .bind_verified_sync_target_durable(&scope(), &target(), &clock)
                .is_err());
            assert!(repo.sync_status(&scope()).await.unwrap().link.is_none());
            let origins: i64 = connection
                .query_row("SELECT count(*) FROM knowledge_sync_targets", [], |row| {
                    row.get(0)
                })
                .unwrap();
            assert_eq!(origins, 0);
        }
    });
}

#[test]
fn same_unverified_association_can_be_verified_but_foreign_association_cannot() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let mut other = target();
        other.link.remote_actor_id = "other".into();
        assert!(matches!(
            repo.bind_verified_sync_target_durable(&scope(), &other, &|| Ok(())),
            Err(KnowledgeError::Conflict)
        ));
        assert!(repo
            .bind_verified_sync_target_durable(&scope(), &target(), &|| Ok(()))
            .is_ok());
    });
}
