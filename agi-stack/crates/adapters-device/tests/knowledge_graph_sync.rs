use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::processing::*;
use agistack_core::knowledge::sync::graph::*;
use agistack_core::knowledge::sync::graph_resolution::*;
use agistack_core::knowledge::sync::push::KnowledgeSyncTarget;
use agistack_core::knowledge::sync::{KnowledgeSyncLink, KnowledgeSyncRepository, KnowledgeUnbindPolicy};
use agistack_core::knowledge::KnowledgeMemory as Memory;
use agistack_core::knowledge::{
    KnowledgeError, KnowledgeScope, MemoryMutation, ScopedMemoryRepository,
};
use agistack_core::Entity;
use futures::executor::block_on;
use serde_json::{json, Value};
use uuid::Uuid;

struct Database(std::path::PathBuf);
impl Database {
    fn new() -> Self {
        Self(std::env::temp_dir().join(format!("knowledge-graph-sync-{}.db", Uuid::new_v4())))
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
fn memory(id: &str) -> MemoryMutation {
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
fn projection(name: &str) -> ProcessingProjection {
    ProcessingProjection {
        entities: vec![
            Entity {
                name: name.into(),
                kind: "Person".into(),
            },
            Entity {
                name: "Acme".into(),
                kind: "Organization".into(),
            },
        ],
        relationships: vec![ProcessingRelationship {
            source_index: 0,
            target_index: 1,
            relation_type: "WORKS_AT".into(),
            fact: format!("{name} works at Acme"),
            score: 0.8,
        }],
    }
}
async fn link(repo: &SqliteKnowledgeRepository) {
    repo.configure_sync_link(&scope(), target().link)
        .await
        .unwrap();
}
async fn extract(repo: &SqliteKnowledgeRepository, id: &str, name: &str) {
    repo.mutate(&scope(), "local-author", &format!("create-{id}-{name}"), memory(id))
        .await
        .unwrap();
    let lease = repo
        .claim(&scope(), "worker", 0, 100)
        .await
        .unwrap()
        .unwrap();
    repo.complete(&scope(), &lease, projection(name), 1)
        .await
        .unwrap();
}
fn remote_version(object_id: &str, revision: u32, name: &str) -> Value {
    version_with_content(
        object_id,
        revision,
        json!({
            "source_revision": 1,
            "change_sequence": 42,
            "audit_attempt": 1,
            "entities": [
                {"name": name, "kind": "Person"},
                {"name": "Acme", "kind": "Organization"}
            ],
            "relationships": [{
                "source_index": 0,
                "target_index": 1,
                "relation_type": "WORKS_AT",
                "fact": format!("{name} works at Acme"),
                "score": 0.8
            }]
        }),
    )
}
fn version_with_content(object_id: &str, revision: u32, content: Value) -> Value {
    json!({
        "object_id": object_id,
        "revision": revision,
        "deleted": false,
        "author_id": "remote-actor",
        "created_at_ms": 100,
        "content": content,
    })
}
fn page(events: Vec<(u64, &str, Value)>, has_more: bool) -> Value {
    json!({
        "changes": events
            .iter()
            .map(|(sequence, change_id, version)| json!({
                "sequence": sequence,
                "change_id": change_id,
                "version": version,
            }))
            .collect::<Vec<_>>(),
        "next_cursor": events.last().map_or(0, |(sequence, _, _)| *sequence),
        "has_more": has_more,
    })
}

#[test]
fn extraction_publish_enqueues_graph_outbox_and_status_counts() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let status = repo.sync_status(&scope()).await.unwrap();
        assert_eq!(status.pending_graph_changes, 1);
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        assert_eq!(request["operation"], "create");
        assert_eq!(request["object_id"], "memory");
        assert_eq!(request["expected_revision"], 0);
        assert_eq!(request["content"]["source_revision"], 1);
        assert_eq!(request["content"]["audit_attempt"], 1);
        assert_eq!(request["content"]["entities"][0]["name"], "Alice");
        assert_eq!(request["content"]["relationships"][0]["score"], 0.8);
        Uuid::parse_str(prepared.change_id.as_str()).unwrap();
    });
}

#[test]
fn push_receipt_applied_advances_baseline_and_update_uses_remote_revision() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        let response = json!({
            "replayed": false,
            "receipt": {
                "status": "applied",
                "change_id": prepared.change_id,
                "sequence": 7,
                "version": version_with_content("memory", 1, request["content"].clone()),
            }
        });
        let receipt = repo
            .accept_graph_push_receipt(&scope(), &target(), prepared.local_sequence, response, None)
            .await
            .unwrap();
        assert!(!receipt.replayed);
        assert!(repo
            .remote_graph_baseline(&scope(), "memory")
            .await
            .unwrap()
            .is_some());
        assert_eq!(
            repo.sync_status(&scope()).await.unwrap().pending_graph_changes,
            0
        );
        // Re-extraction enqueues an update carrying the remote base revision.
        let current = repo.get(&scope(), "memory").await.unwrap().unwrap();
        repo.update(&scope(), current, 1).await.unwrap();
        let lease = repo
            .claim(&scope(), "worker", 10, 100)
            .await
            .unwrap()
            .unwrap();
        repo.complete(&scope(), &lease, projection("Alice"), 11)
            .await
            .unwrap();
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        assert_eq!(request["operation"], "update");
        assert_eq!(request["expected_revision"], 1);
        assert_eq!(request["content"]["source_revision"], 2);
    });
}

#[test]
fn push_conflict_pauses_object_and_stores_cloud_versions() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        let mut proposed = request.clone();
        proposed.as_object_mut().unwrap().remove("change_id");
        let conflict = json!({
            "id": Uuid::new_v4().to_string(),
            "object_id": "memory",
            "proposed": proposed,
            "current": remote_version("memory", 1, "Cloud"),
            "resolved_change_id": Value::Null,
        });
        let response = json!({
            "replayed": false,
            "receipt": {
                "status": "conflict",
                "change_id": prepared.change_id,
                "conflict_id": conflict["id"],
            }
        });
        repo.accept_graph_push_receipt(
            &scope(),
            &target(),
            prepared.local_sequence,
            response,
            Some(conflict.clone()),
        )
        .await
        .unwrap();
        let conflicts = repo.graph_push_conflicts(&scope(), 10).await.unwrap();
        assert_eq!(conflicts, vec![conflict]);
        // The paused object is not prepared again while the conflict is open.
        assert!(repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
    });
}

#[test]
fn pull_applies_remote_record_and_serves_it_before_and_after_source_arrival() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        let event = remote_version("cloud-memory", 1, "Cloud");
        let response = page(
            vec![(1, &Uuid::new_v4().to_string(), event)],
            false,
        );
        let receipt = repo
            .accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        assert_eq!((receipt.applied, receipt.conflicts, receipt.next_cursor), (1, 0, 1));
        // The source memory has not arrived: durable but source-unavailable.
        let synced = repo
            .synced_graph_projection(&scope(), "cloud-memory")
            .await
            .unwrap()
            .unwrap();
        assert!(!synced.source_available);
        assert!(!synced.source_current);
        assert_eq!(synced.content.entities[0].name, "Cloud");
        assert_eq!(synced.content.change_sequence, 42);
        // Once memory sync delivers the source at the provenance revision, the
        // record becomes source-available and current.
        repo.mutate(
            &scope(),
            "local-author",
            "create-cloud-memory",
            memory("cloud-memory"),
        )
        .await
        .unwrap();
        let synced = repo
            .synced_graph_projection(&scope(), "cloud-memory")
            .await
            .unwrap()
            .unwrap();
        assert!(synced.source_available);
        assert!(synced.source_current);
    });
}

#[test]
fn pull_conflict_pauses_object_and_other_objects_continue() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let response = page(
            vec![
                (1, &Uuid::new_v4().to_string(), remote_version("memory", 1, "Cloud")),
                (2, &Uuid::new_v4().to_string(), remote_version("other", 1, "Other")),
            ],
            false,
        );
        let receipt = repo
            .accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        assert_eq!((receipt.applied, receipt.conflicts), (1, 1));
        let conflicts = repo.graph_pull_conflicts(&scope(), 10).await.unwrap();
        assert_eq!(conflicts.len(), 1);
        assert_eq!(conflicts[0]["object_id"], "memory");
        // The conflict materialized the pending local extraction for comparison.
        assert_eq!(conflicts[0]["local"]["content"]["entities"][0]["name"], "Alice");
        let other = repo
            .synced_graph_projection(&scope(), "other")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(other.content.entities[0].name, "Other");
        // The paused object blocks further pushes until explicit resolution.
        assert!(repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
    });
}

#[test]
fn own_journal_echo_settles_push_without_conflict() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        // The HTTP response was lost; the journal echo recovers the receipt.
        let response = page(
            vec![(
                1,
                &prepared.change_id,
                version_with_content("memory", 1, request["content"].clone()),
            )],
            false,
        );
        let receipt = repo
            .accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        // The echo settles the push and baseline without re-applying our own
        // record: the origin already serves it from its audited projection.
        assert_eq!((receipt.applied, receipt.conflicts), (0, 0));
        assert_eq!(
            repo.sync_status(&scope()).await.unwrap().pending_graph_changes,
            0
        );
        assert!(repo
            .remote_graph_baseline(&scope(), "memory")
            .await
            .unwrap()
            .is_some());
    });
}

#[test]
fn stale_cursor_and_malformed_events_fail_closed() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        let event = remote_version("cloud-memory", 1, "Cloud");
        let response = page(vec![(1, &Uuid::new_v4().to_string(), event.clone())], false);
        assert!(matches!(
            repo.accept_graph_pull_page(&scope(), &target(), 5, response.clone())
                .await,
            Err(KnowledgeError::Conflict)
        ));
        repo.accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        // Replaying the same event is rejected; the cursor stays durable.
        let replay = page(vec![(1, &Uuid::new_v4().to_string(), event)], false);
        assert!(matches!(
            repo.accept_graph_pull_page(&scope(), &target(), 1, replay)
                .await,
            Err(KnowledgeError::InvalidInput)
        ));
        assert_eq!(repo.graph_pull_cursor(&scope(), &target()).await.unwrap(), 1);
    });
}

#[test]
fn use_remote_resolution_applies_remote_and_supersedes_pending_push() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let response = page(
            vec![(1, &Uuid::new_v4().to_string(), remote_version("memory", 1, "Cloud"))],
            false,
        );
        repo.accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        let outcome = repo
            .resolve_graph_pull_conflicts(
                &scope(),
                &target(),
                "local-author",
                "resolve-1",
                GraphPullConflictResolution {
                    object_id: "memory".into(),
                    conflict_sequences: vec![1],
                    expected_local_revision: 1,
                    expected_remote_revision: 1,
                    expected_baseline_revision: 0,
                    choice: GraphConflictChoice::UseRemote {},
                },
            )
            .await
            .unwrap();
        assert!(!outcome.replayed);
        assert_eq!(outcome.receipt.local_revision, 2);
        assert_eq!(outcome.receipt.superseded_sequences.len(), 1);
        let synced = repo
            .synced_graph_projection(&scope(), "memory")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(synced.content.entities[0].name, "Cloud");
        assert!(repo.graph_pull_conflicts(&scope(), 10).await.unwrap().is_empty());
        // Replay returns the original receipt.
        let replayed = repo
            .resolve_graph_pull_conflicts(
                &scope(),
                &target(),
                "local-author",
                "resolve-1",
                GraphPullConflictResolution {
                    object_id: "memory".into(),
                    conflict_sequences: vec![1],
                    expected_local_revision: 1,
                    expected_remote_revision: 1,
                    expected_baseline_revision: 0,
                    choice: GraphConflictChoice::UseRemote {},
                },
            )
            .await
            .unwrap();
        assert!(replayed.replayed);
    });
}

#[test]
fn use_local_resolution_rebases_and_repushes_local_content() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let response = page(
            vec![(1, &Uuid::new_v4().to_string(), remote_version("memory", 1, "Cloud"))],
            false,
        );
        repo.accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        // Stale expectations are rejected with no state change.
        assert!(matches!(
            repo.resolve_graph_pull_conflicts(
                &scope(),
                &target(),
                "local-author",
                "stale",
                GraphPullConflictResolution {
                    object_id: "memory".into(),
                    conflict_sequences: vec![1],
                    expected_local_revision: 7,
                    expected_remote_revision: 1,
                    expected_baseline_revision: 0,
                    choice: GraphConflictChoice::UseLocal {},
                },
            )
            .await,
            Err(KnowledgeError::Conflict)
        ));
        let outcome = repo
            .resolve_graph_pull_conflicts(
                &scope(),
                &target(),
                "local-author",
                "resolve-1",
                GraphPullConflictResolution {
                    object_id: "memory".into(),
                    conflict_sequences: vec![1],
                    expected_local_revision: 1,
                    expected_remote_revision: 1,
                    expected_baseline_revision: 0,
                    choice: GraphConflictChoice::UseLocal {},
                },
            )
            .await
            .unwrap();
        assert_eq!(outcome.receipt.remote_baseline_revision, 1);
        let synced = repo
            .synced_graph_projection(&scope(), "memory")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(synced.content.entities[0].name, "Alice");
        // The pending push now updates from the acknowledged remote revision.
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        assert_eq!(request["operation"], "update");
        assert_eq!(request["expected_revision"], 1);
    });
}

#[test]
fn keep_both_resolution_preserves_local_as_deterministic_detached_copy() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let response = page(
            vec![(1, &Uuid::new_v4().to_string(), remote_version("memory", 1, "Cloud"))],
            false,
        );
        repo.accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        let outcome = repo
            .resolve_graph_pull_conflicts(
                &scope(),
                &target(),
                "local-author",
                "resolve-1",
                GraphPullConflictResolution {
                    object_id: "memory".into(),
                    conflict_sequences: vec![1],
                    expected_local_revision: 1,
                    expected_remote_revision: 1,
                    expected_baseline_revision: 0,
                    choice: GraphConflictChoice::KeepBoth {},
                },
            )
            .await
            .unwrap();
        let copy_id = outcome.receipt.copy_object_id.clone().unwrap();
        Uuid::parse_str(&copy_id).unwrap();
        let original = repo
            .synced_graph_projection(&scope(), "memory")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(original.content.entities[0].name, "Cloud");
        let copy = repo
            .synced_graph_projection(&scope(), &copy_id)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(copy.content.entities[0].name, "Alice");
        // The copy is pushed as a create so every replica converges to both.
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        assert_eq!(request["operation"], "create");
        assert_eq!(request["object_id"], Value::String(copy_id));
    });
}

#[test]
fn merged_resolution_applies_and_pushes_merged_content() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let response = page(
            vec![(1, &Uuid::new_v4().to_string(), remote_version("memory", 1, "Cloud"))],
            false,
        );
        repo.accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        let merged: RemoteGraphContent =
            serde_json::from_value(remote_version("memory", 1, "Merged")["content"].clone())
                .unwrap();
        let outcome = repo
            .resolve_graph_pull_conflicts(
                &scope(),
                &target(),
                "local-author",
                "resolve-1",
                GraphPullConflictResolution {
                    object_id: "memory".into(),
                    conflict_sequences: vec![1],
                    expected_local_revision: 1,
                    expected_remote_revision: 1,
                    expected_baseline_revision: 0,
                    choice: GraphConflictChoice::Merged {
                        content: merged,
                    },
                },
            )
            .await
            .unwrap();
        assert_eq!(outcome.receipt.local_revision, 2);
        let synced = repo
            .synced_graph_projection(&scope(), "memory")
            .await
            .unwrap()
            .unwrap();
        assert_eq!(synced.content.entities[0].name, "Merged");
        let prepared = repo
            .prepare_graph_push(&scope(), &target())
            .await
            .unwrap()
            .unwrap();
        let request: Value = serde_json::from_str(&prepared.request_json).unwrap();
        assert_eq!(request["content"]["entities"][0]["name"], "Merged");
    });
}

#[test]
fn unbind_fences_graph_outbox_and_delete_policy_tombstones_cloud_records() {
    block_on(async {
        let db = Database::new();
        let repo = db.open();
        link(&repo).await;
        extract(&repo, "memory", "Alice").await;
        let event = remote_version("cloud-memory", 1, "Cloud");
        let response = page(vec![(1, &Uuid::new_v4().to_string(), event)], false);
        repo.accept_graph_pull_page(&scope(), &target(), 0, response)
            .await
            .unwrap();
        let receipt = repo
            .unbind_sync_target_durable(&scope(), KnowledgeUnbindPolicy::Delete, 5)
            .unwrap();
        assert_eq!(receipt.fenced_graph_outbox, 1);
        // Cloud-origin graph records are tombstoned; local work is fenced.
        let cloud = repo
            .synced_graph_projection(&scope(), "cloud-memory")
            .await
            .unwrap()
            .unwrap();
        assert!(cloud.deleted);
        assert_eq!(
            repo.sync_status(&scope()).await.unwrap().pending_graph_changes,
            0
        );
        assert!(matches!(
            repo.graph_pull_cursor(&scope(), &target()).await,
            Err(KnowledgeError::Conflict)
        ));
    });
}
