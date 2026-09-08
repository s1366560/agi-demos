use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::sync::push::{
    KnowledgePushRepository, KnowledgeSyncTarget, PreparedKnowledgePush, MAX_REMOTE_REVISION,
};
use agistack_core::knowledge::sync::{KnowledgeSyncLink, KnowledgeSyncRepository};
use agistack_core::knowledge::KnowledgeMemory as Memory;
use agistack_core::knowledge::{
    KnowledgeError, KnowledgeScope, MemoryMutation, ScopedMemoryRepository,
};
use futures::executor::block_on;
use serde_json::{json, Value};
use uuid::Uuid;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-push-{}.db", Uuid::new_v4())))
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
        authority: "https://example.test/api/v1".into(),
        link: KnowledgeSyncLink {
            remote_tenant_id: "remote-tenant".into(),
            remote_project_id: "remote-project".into(),
            remote_actor_id: "remote-actor".into(),
        },
    }
}
fn create(id: &str) -> MemoryMutation {
    MemoryMutation::Create {
        memory: Memory {
            id: id.into(),
            project_id: "local-project".into(),
            title: "title".into(),
            content: "original".into(),
            content_type: "text".into(),
            author_id: "local-author".into(),
            tags: vec![],
            entities: vec![],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1,
            metadata: Default::default(),
            embedding: None,
        },
    }
}
async fn init(repo: &SqliteKnowledgeRepository) {
    repo.configure_sync_link(&scope(), target().link)
        .await
        .unwrap();
    repo.mutate(&scope(), "local-author", "create", create("memory"))
        .await
        .unwrap();
}
fn applied(push: &PreparedKnowledgePush) -> Value {
    let request: Value = serde_json::from_str(&push.request_json).unwrap();
    json!({"receipt":{"status":"applied","change_id":push.change_id,"sequence":push.local_sequence+10,"version":{"memory_id":request["memory_id"],"revision":request["expected_revision"].as_u64().unwrap()+1,"deleted":false,"author_id":"remote-actor","created_at_ms":100,"content":request["content"],"remote_extension":{"preserve":"all"}}},"replayed":false})
}

#[test]
fn local_delete_conflict_retains_remote_modified_copy_and_local_tombstone() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        init(&repo).await;
        let create = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        repo.accept_push_receipt(
            &scope(),
            &target(),
            create.local_sequence,
            applied(&create),
            None,
        )
        .await
        .unwrap();
        repo.mutate(
            &scope(),
            "local-author",
            "delete",
            MemoryMutation::Delete {
                id: "memory".into(),
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        let delete = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let mut proposed: Value = serde_json::from_str(&delete.request_json).unwrap();
        assert_eq!(proposed["operation"], "delete");
        assert_eq!(proposed["expected_revision"], 1);
        assert!(proposed["content"].is_null());
        proposed.as_object_mut().unwrap().remove("change_id");
        let id = Uuid::new_v4().to_string();
        let mut current = applied(&create)["receipt"]["version"].clone();
        current["revision"] = json!(2);
        current["content"]["content"] = json!("remote edit after local base");
        let conflict = json!({"id":id,"memory_id":"memory","proposed":proposed,"current":current,"resolved_change_id":null});
        repo.accept_push_receipt(&scope(),&target(),delete.local_sequence,json!({"receipt":{"change_id":delete.change_id,"status":"conflict","conflict_id":id},"replayed":false}),Some(conflict.clone())).await.unwrap();
        assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
        assert_eq!(
            repo.push_conflicts(&scope(), 20).await.unwrap(),
            vec![conflict]
        );
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.sync_outbox(&scope(), 0, 10).await.unwrap().len(), 1);
    });
}

#[test]
fn retries_preserve_exact_request_and_receipt_only_acks_its_sequence() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        init(&repo).await;
        let prepared = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        assert_eq!(request["expected_revision"], 0);
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "edited while sending".into();
        let second = repo
            .mutate(
                &scope(),
                "local-author",
                "update",
                MemoryMutation::Update {
                    memory,
                    expected_revision: 1,
                },
            )
            .await
            .unwrap();
        drop(repo);
        let repo = db.open();
        assert_eq!(
            repo.prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap(),
            prepared
        );
        let response = applied(&prepared);
        assert!(matches!(
            repo.accept_push_receipt(
                &scope(),
                &target(),
                second.receipt.sequence,
                response.clone(),
                None
            )
            .await,
            Err(KnowledgeError::NotFound)
        ));
        repo.accept_push_receipt(
            &scope(),
            &target(),
            prepared.local_sequence,
            response.clone(),
            None,
        )
        .await
        .unwrap();
        let local = repo.get(&scope(), "memory").await.unwrap().unwrap();
        assert_eq!(local.version, 2);
        assert_eq!(local.content, "edited while sending");
        assert_eq!(local.author_id, "local-author");
        assert_eq!(
            repo.remote_baseline(&scope(), "memory").await.unwrap(),
            Some(response["receipt"]["version"].clone())
        );
        let pending = repo.sync_outbox(&scope(), 0, 20).await.unwrap();
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0].local_change.sequence, second.receipt.sequence);
        let next = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&next.request_json).unwrap();
        assert_eq!(request["expected_revision"], 1);
        assert_eq!(request["operation"], "update");
        assert_eq!(request["content"]["content"], "edited while sending");
        let next_response = applied(&next);
        repo.accept_push_receipt(
            &scope(),
            &target(),
            next.local_sequence,
            next_response.clone(),
            None,
        )
        .await
        .unwrap();
        let mut replay_response = response.clone();
        replay_response["replayed"] = json!(true);
        assert!(
            repo.accept_push_receipt(
                &scope(),
                &target(),
                prepared.local_sequence,
                replay_response,
                None
            )
            .await
            .unwrap()
            .replayed
        );
        assert_eq!(
            repo.remote_baseline(&scope(), "memory").await.unwrap(),
            Some(next_response["receipt"]["version"].clone())
        );
        assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 0);
        let mut changed = response;
        changed["receipt"]["sequence"] = json!(999);
        assert!(matches!(
            repo.accept_push_receipt(&scope(), &target(), prepared.local_sequence, changed, None)
                .await,
            Err(KnowledgeError::IdempotencyConflict)
        ));
    });
}

#[test]
fn receipt_failure_rolls_back_baseline_and_rejects_wrong_identity_or_revision() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        init(&repo).await;
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let response = applied(&push);
        let mut wrong_target = target();
        wrong_target.authority = "https://other.test/api/v1".into();
        assert!(repo.prepare_push(&scope(), &wrong_target).await.is_err());
        assert!(repo
            .accept_push_receipt(
                &scope(),
                &wrong_target,
                push.local_sequence,
                response.clone(),
                None
            )
            .await
            .is_err());
        let mut foreign = scope();
        foreign.tenant_id = "foreign".into();
        assert!(repo
            .accept_push_receipt(
                &foreign,
                &target(),
                push.local_sequence,
                response.clone(),
                None
            )
            .await
            .is_err());
        for field in ["revision", "author_id", "memory_id"] {
            let mut invalid = response.clone();
            invalid["receipt"]["version"][field] = if field == "revision" {
                json!(2)
            } else {
                json!("forged")
            };
            assert!(repo
                .accept_push_receipt(&scope(), &target(), push.local_sequence, invalid, None)
                .await
                .is_err());
        }
        let conn = rusqlite::Connection::open(&db.0).unwrap();
        conn.execute_batch("CREATE TRIGGER fail_receipt BEFORE UPDATE ON knowledge_sync_pushes BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END;").unwrap();
        assert!(repo
            .accept_push_receipt(
                &scope(),
                &target(),
                push.local_sequence,
                response.clone(),
                None
            )
            .await
            .is_err());
        assert!(repo
            .remote_baseline(&scope(), "memory")
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.sync_status(&scope()).await.unwrap().pending_changes, 1);
        conn.execute_batch("DROP TRIGGER fail_receipt;").unwrap();
        repo.accept_push_receipt(&scope(), &target(), push.local_sequence, response, None)
            .await
            .unwrap();
    });
}

#[test]
fn conflict_preserves_both_versions_and_blocks_only_that_object() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        init(&repo).await;
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        memory.content = "later local".into();
        repo.mutate(
            &scope(),
            "local-author",
            "later",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        repo.mutate(&scope(), "local-author", "other", create("other"))
            .await
            .unwrap();
        let conflict_id = Uuid::new_v4().to_string();
        let receipt = json!({"receipt":{"status":"conflict","change_id":push.change_id,"conflict_id":conflict_id},"replayed":false});
        let mut proposed: Value = serde_json::from_str(&push.request_json).unwrap();
        proposed.as_object_mut().unwrap().remove("change_id");
        let mut current = applied(&push)["receipt"]["version"].clone();
        current["revision"] = json!(7);
        current["deleted"] = json!(true);
        current["content"]["metadata"] = json!({"nested":{"remote":[1,2,"preserved"]}});
        let conflict = json!({"id":conflict_id,"memory_id":"memory","proposed":proposed,"current":current,"resolved_change_id":null});
        assert!(repo
            .accept_push_receipt(
                &scope(),
                &target(),
                push.local_sequence,
                receipt.clone(),
                None
            )
            .await
            .is_err());
        repo.accept_push_receipt(
            &scope(),
            &target(),
            push.local_sequence,
            receipt.clone(),
            Some(conflict.clone()),
        )
        .await
        .unwrap();
        drop(repo);
        let repo = db.open();
        assert_eq!(
            repo.push_conflicts(&scope(), 20).await.unwrap(),
            vec![conflict]
        );
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "later local"
        );
        assert!(repo
            .remote_baseline(&scope(), "memory")
            .await
            .unwrap()
            .is_none());
        let next = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&next.request_json).unwrap();
        assert_eq!(request["memory_id"], "other");
        assert!(
            repo.accept_push_receipt(&scope(), &target(), push.local_sequence, receipt, None)
                .await
                .unwrap()
                .replayed
        );
    });
}

#[test]
fn remote_metadata_and_signed_revision_boundary_stay_independent_of_local_revision() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        init(&repo).await;
        let conn = rusqlite::Connection::open(&db.0).unwrap();
        let remote = json!({"memory_id":"memory","revision":MAX_REMOTE_REVISION-1,"deleted":false,"author_id":"remote-actor","created_at_ms":100,"content":{"title":"old","content":"remote old","content_type":"text","tags":[],"status":"ENABLED","metadata":{"nested":{"unicode":"知识","values":[null,true,42]}}},"remote_extension":["complete"]});
        conn.execute("INSERT INTO knowledge_sync_remote_versions(tenant_id,project_id,memory_id,version_json) VALUES(?1,?2,'memory',?3)",rusqlite::params![scope().tenant_id,scope().project_id,serde_json::to_string(&remote).unwrap()]).unwrap();
        // Exercise an actual v11 payload: metadata existed only in the trusted
        // remote baseline before the document upgrade.
        conn.execute_batch("UPDATE knowledge_memories SET payload=json_remove(payload,'$.metadata'); UPDATE knowledge_processing_changes SET payload=json_remove(payload,'$.metadata'); UPDATE knowledge_schema SET version=11;").unwrap();
        drop(repo);
        let repo = db.open();
        assert_eq!(
            serde_json::to_value(
                repo.get(&scope(), "memory")
                    .await
                    .unwrap()
                    .unwrap()
                    .metadata
            )
            .unwrap(),
            remote["content"]["metadata"]
        );
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&push.request_json).unwrap();
        assert_eq!(request["expected_revision"], MAX_REMOTE_REVISION - 1);
        assert_eq!(request["operation"], "update");
        assert_eq!(
            request["content"]["metadata"],
            remote["content"]["metadata"]
        );
        let response = applied(&push);
        repo.accept_push_receipt(
            &scope(),
            &target(),
            push.local_sequence,
            response.clone(),
            None,
        )
        .await
        .unwrap();
        assert_eq!(
            repo.remote_baseline(&scope(), "memory").await.unwrap(),
            Some(response["receipt"]["version"].clone())
        );
        let mut memory = repo.get(&scope(), "memory").await.unwrap().unwrap();
        assert_eq!(memory.version, 1);
        memory.content = "later".into();
        repo.mutate(
            &scope(),
            "local-author",
            "later",
            MemoryMutation::Update {
                memory,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        assert!(matches!(
            repo.prepare_push(&scope(), &target()).await,
            Err(KnowledgeError::Conflict)
        ));
    });
}

#[test]
fn local_metadata_create_edit_clear_and_uncertain_retry_keep_exact_snapshot() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let MemoryMutation::Create { mut memory } = create("memory") else {
            unreachable!()
        };
        memory.metadata = json!({"user":{"nested":[1,false,null,"中文"]}})
            .as_object()
            .unwrap()
            .clone();
        let original = memory.metadata.clone();
        repo.mutate(
            &scope(),
            "local-author",
            "create",
            MemoryMutation::Create { memory },
        )
        .await
        .unwrap();
        let push = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&push.request_json).unwrap();
        assert_eq!(request["content"]["metadata"], json!(original));
        let mut edited = repo.get(&scope(), "memory").await.unwrap().unwrap();
        edited.metadata = json!({"later":2}).as_object().unwrap().clone();
        repo.update(&scope(), edited, 1).await.unwrap();
        drop(repo);
        let repo = db.open();
        assert_eq!(
            repo.prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap()
                .request_json,
            push.request_json
        );
        repo.accept_push_receipt(
            &scope(),
            &target(),
            push.local_sequence,
            applied(&push),
            None,
        )
        .await
        .unwrap();
        let update = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&update.request_json).unwrap()["content"]["metadata"],
            json!({"later":2})
        );
        repo.accept_push_receipt(
            &scope(),
            &target(),
            update.local_sequence,
            applied(&update),
            None,
        )
        .await
        .unwrap();
        let mut cleared = repo.get(&scope(), "memory").await.unwrap().unwrap();
        cleared.metadata.clear();
        repo.update(&scope(), cleared, 2).await.unwrap();
        let clear = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&clear.request_json).unwrap()["content"]["metadata"],
            json!({})
        );
    });
}

#[test]
fn metadata_upgrade_preserves_prepared_bytes_and_recovers_explicit_pending_intent() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        init(&repo).await;
        let prepared = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let current = repo.get(&scope(), "memory").await.unwrap().unwrap();
        repo.update(&scope(), current, 1).await.unwrap();
        let changes = repo.changes(&scope(), 0, 10).await.unwrap();
        let pending = changes[1].sequence;
        drop(repo);
        let conn = rusqlite::Connection::open(&db.0).unwrap();
        let remote = json!({"memory_id":"memory","revision":1,"deleted":false,"author_id":"remote-actor","created_at_ms":100,"content":{"title":"title","content":"original","content_type":"text","tags":[],"status":"ENABLED","metadata":{"baseline":true}}});
        conn.execute(
            "INSERT INTO knowledge_sync_remote_versions VALUES(?1,?2,'memory',?3)",
            rusqlite::params![scope().tenant_id, scope().project_id, remote.to_string()],
        )
        .unwrap();
        conn.execute(
            "INSERT INTO knowledge_sync_outbox_metadata VALUES(?1,?2)",
            rusqlite::params![
                pending,
                json!({"explicit":{"retain":[false,4,"中文"]}}).to_string()
            ],
        )
        .unwrap();
        conn.execute_batch("UPDATE knowledge_memories SET payload=json_remove(payload,'$.metadata'); UPDATE knowledge_processing_changes SET payload=json_remove(payload,'$.metadata'); UPDATE knowledge_schema SET version=11;").unwrap();
        let before:(String,String)=conn.query_row("SELECT request_json,(SELECT request_json FROM knowledge_mutation_receipts LIMIT 1) FROM knowledge_sync_pushes",[],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();
        let repo = db.open();
        assert_eq!(
            repo.prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap()
                .request_json,
            prepared.request_json
        );
        assert_eq!(
            serde_json::to_value(
                repo.get(&scope(), "memory")
                    .await
                    .unwrap()
                    .unwrap()
                    .metadata
            )
            .unwrap(),
            json!({"explicit":{"retain":[false,4,"中文"]}})
        );
        assert_eq!(
            serde_json::to_value(
                repo.change(&scope(), pending)
                    .await
                    .unwrap()
                    .unwrap()
                    .memory
                    .metadata
            )
            .unwrap(),
            json!({"explicit":{"retain":[false,4,"中文"]}})
        );
        let after:(String,String)=conn.query_row("SELECT request_json,(SELECT request_json FROM knowledge_mutation_receipts LIMIT 1) FROM knowledge_sync_pushes",[],|r|Ok((r.get(0)?,r.get(1)?))).unwrap();
        assert_eq!(before, after);
        drop(repo);
        let repo = db.open();
        assert_eq!(
            repo.prepare_push(&scope(), &target())
                .await
                .unwrap()
                .unwrap()
                .request_json,
            prepared.request_json
        );
    });
}
