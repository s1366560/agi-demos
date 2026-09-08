use agistack_adapters_device::knowledge::{project_schema::*, SqliteKnowledgeRepository};
use agistack_core::{
    knowledge::KnowledgeScope,
    project_schema::{ProjectSchemaDocument, ProjectSchemaError},
};
use serde_json::json;

use super::support::*;

#[test]
fn fresh_reads_and_receipt_lookup_do_not_bootstrap_or_create_memory_changes() {
    let db = Database::new();
    let repo = db.open();
    assert!(repo
        .read_project_schema_durable(&scope(), &current)
        .unwrap()
        .is_none());
    let journal = repo
        .project_schema_changes_durable(&scope(), 0, 100, &current)
        .unwrap();
    assert_eq!(journal.upper_revision, 0);
    assert!(journal.items.is_empty());
    assert!(repo
        .project_schema_receipt_durable(
            &scope(),
            "actor",
            &uuid::Uuid::new_v4().to_string(),
            &current
        )
        .unwrap()
        .is_none());
    assert_eq!(db.counts(), (0, 0));
    let memory_changes: u32 = db
        .sql()
        .query_row(
            "SELECT count(*) FROM knowledge_processing_changes",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(memory_changes, 0);
}

#[test]
fn bootstrap_canonicalizes_member_order_but_preserves_ids_and_opaque_values() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let c = command(&scope(), 1);
    let receipt = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &c, &current)
        .unwrap();
    assert_eq!(receipt.sequence(), 1);
    assert_eq!(receipt.actor_id(), "actor");
    assert_eq!(receipt.change_id(), c.change_id);
    let doc = receipt.document();
    assert_eq!(doc.entity_types()[0].id, ENTITY_A);
    assert_eq!(doc.entity_types()[1].id, ENTITY_B);
    assert_eq!(
        doc.entity_types()[0].schema,
        c.document.entity_types()[1].schema
    );
    assert_eq!(doc.mappings(), c.document.mappings());
    assert_eq!(
        repo.read_project_schema_durable(&scope(), &current)
            .unwrap()
            .as_ref(),
        Some(doc)
    );
    let repeat = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &c, &current)
        .unwrap();
    assert_eq!(receipt.as_json(), repeat.as_json());
    let reordered = ProjectSchemaMutation {
        document: doc.clone(),
        ..c.clone()
    };
    assert!(matches!(
        repo.bootstrap_project_schema_durable(&scope(), "actor", &reordered, &current),
        Err(ProjectSchemaStorageError::ChangeIdReused)
    ));
}

#[test]
fn local_storage_accepts_distinct_ids_with_equal_names_without_semantic_deduplication() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let c = changed(&command(&scope(), 1), |d| {
        d["entity_types"][0]["name"] = d["entity_types"][1]["name"].clone()
    });
    let receipt = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &c, &current)
        .unwrap();
    assert_eq!(receipt.document().entity_types().len(), 2);
    assert_ne!(
        receipt.document().entity_types()[0].id,
        receipt.document().entity_types()[1].id
    );
}

#[test]
fn scope_actor_and_change_id_are_explicit_and_receipts_never_cross_them() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let c = command(&scope(), 1);
    repo.bootstrap_project_schema_durable(&scope(), "actor", &c, &current)
        .unwrap();
    for other in [
        KnowledgeScope {
            tenant_id: "other".into(),
            ..scope()
        },
        KnowledgeScope {
            project_id: "other".into(),
            ..scope()
        },
    ] {
        assert!(repo
            .read_project_schema_durable(&other, &current)
            .unwrap()
            .is_none());
        assert!(repo
            .project_schema_receipt_durable(&other, "actor", &c.change_id, &current)
            .unwrap()
            .is_none());
        assert!(matches!(
            repo.bootstrap_project_schema_durable(&other, "actor", &c, &current),
            Err(ProjectSchemaStorageError::ScopeMismatch)
        ));
        assert!(repo
            .project_schema_changes_durable(&other, 1, 1, &current)
            .is_err());
        repo.bootstrap_project_schema_durable(&other, "actor", &command(&other, 1), &current)
            .unwrap();
    }
    assert!(repo
        .project_schema_receipt_durable(&scope(), "other-actor", &c.change_id, &current)
        .unwrap()
        .is_none());
    for actor in ["", " actor", "actor\0", "\n"] {
        assert!(matches!(
            repo.bootstrap_project_schema_durable(&scope(), actor, &c, &current),
            Err(ProjectSchemaStorageError::InvalidInput)
        ));
    }
    for id in [
        "bad",
        "00000000-0000-0000-0000-000000000000",
        "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
    ] {
        let invalid = ProjectSchemaMutation {
            change_id: id.into(),
            ..c.clone()
        };
        assert!(matches!(
            repo.bootstrap_project_schema_durable(&scope(), "actor", &invalid, &current),
            Err(ProjectSchemaStorageError::InvalidInput)
        ));
    }
}

#[test]
fn stale_cas_rejects_whole_write_but_exact_old_receipt_replays_after_later_revision() {
    let db = Database::new();
    let repo = db.open();
    let first = command(&scope(), 1);
    let accepted = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
        .unwrap();
    let second = command(&scope(), 2);
    repo.replace_project_schema_durable(&scope(), "actor", &second, &current)
        .unwrap();
    let stale = ProjectSchemaMutation {
        change_id: uuid::Uuid::new_v4().to_string(),
        ..second.clone()
    };
    assert!(matches!(
        repo.replace_project_schema_durable(&scope(), "actor", &stale, &current),
        Err(ProjectSchemaStorageError::Document(
            ProjectSchemaError::RevisionConflict
        ))
    ));
    let old = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
        .unwrap();
    assert_eq!(old.as_json(), accepted.as_json());
    let reused = changed(&second, |d| {
        d["entity_types"][0]["description"] = json!("changed request")
    });
    assert!(matches!(
        repo.replace_project_schema_durable(&scope(), "actor", &reused, &current),
        Err(ProjectSchemaStorageError::ChangeIdReused)
    ));
    assert_eq!(db.counts(), (1, 2));
}

#[test]
fn schema_identity_and_tombstones_are_retained_until_terminal_deletion() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    let first = command(&scope(), 1);
    repo.bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
        .unwrap();
    let changed_identity = changed(&command(&scope(), 2), |d| {
        d["schema_id"] = json!(uuid::Uuid::new_v4().to_string())
    });
    assert!(matches!(
        repo.replace_project_schema_durable(&scope(), "actor", &changed_identity, &current),
        Err(ProjectSchemaStorageError::Document(
            ProjectSchemaError::InvalidTransition
        ))
    ));
    let missing_tombstone = changed(&command(&scope(), 2), |d| d["mappings"] = json!([]));
    assert!(repo
        .replace_project_schema_durable(&scope(), "actor", &missing_tombstone, &current)
        .is_err());
    let deleted_map = changed(&missing_tombstone, |d| {
        d["tombstones"] = json!([
            {"id":MAP_ID,"kind":"mapping","deleted_revision":2}
        ])
    });
    repo.replace_project_schema_durable(&scope(), "actor", &deleted_map, &current)
        .unwrap();
    assert!(repo
        .replace_project_schema_durable(&scope(), "actor", &command(&scope(), 3), &current)
        .is_err());
    let terminal = changed(&command(&scope(), 3), |d| {
        d["deleted"] = json!(true);
        d["entity_types"] = json!([]);
        d["edge_types"] = json!([]);
        d["mappings"] = json!([]);
        d["tombstones"] = json!([
            {"id":MAP_ID,"kind":"mapping","deleted_revision":2},
            {"id":ENTITY_A,"kind":"entity_type","deleted_revision":3},
            {"id":ENTITY_B,"kind":"entity_type","deleted_revision":3},
            {"id":EDGE_ID,"kind":"edge_type","deleted_revision":3},
        ]);
    });
    let accepted = repo
        .replace_project_schema_durable(&scope(), "actor", &terminal, &current)
        .unwrap();
    assert!(repo
        .read_project_schema_durable(&scope(), &current)
        .unwrap()
        .unwrap()
        .is_deleted());
    assert_eq!(
        repo.replace_project_schema_durable(&scope(), "actor", &terminal, &current)
            .unwrap(),
        accepted
    );
    assert!(repo
        .replace_project_schema_durable(&scope(), "actor", &command(&scope(), 4), &current)
        .is_err());
    assert!(repo
        .bootstrap_project_schema_durable(&scope(), "actor", &command(&scope(), 1), &current)
        .is_err());
    assert_eq!(
        repo.project_schema_changes_durable(&scope(), 0, 100, &current)
            .unwrap()
            .items
            .len(),
        3
    );
}

#[test]
fn journal_pages_are_scoped_contiguous_bounded_and_retain_the_observed_upper_revision() {
    let repo = SqliteKnowledgeRepository::in_memory().unwrap();
    repo.bootstrap_project_schema_durable(&scope(), "actor", &command(&scope(), 1), &current)
        .unwrap();
    for revision in 2..=4 {
        repo.replace_project_schema_durable(
            &scope(),
            "actor",
            &command(&scope(), revision),
            &current,
        )
        .unwrap();
    }
    let first = repo
        .project_schema_changes_durable(&scope(), 0, 2, &current)
        .unwrap();
    assert_eq!(first.upper_revision, 4);
    assert_eq!(
        first
            .items
            .iter()
            .map(ProjectSchemaReceipt::sequence)
            .collect::<Vec<_>>(),
        [1, 2]
    );
    let tail = repo
        .project_schema_changes_durable(&scope(), 2, 2, &current)
        .unwrap();
    assert_eq!(
        tail.items
            .iter()
            .map(ProjectSchemaReceipt::sequence)
            .collect::<Vec<_>>(),
        [3, 4]
    );
    assert!(repo
        .project_schema_changes_durable(&scope(), 4, 1, &current)
        .unwrap()
        .items
        .is_empty());
    assert!(repo
        .project_schema_changes_durable(&scope(), 5, 1, &current)
        .is_err());
    for limit in [0, 101, u32::MAX] {
        assert!(repo
            .project_schema_changes_durable(&scope(), 0, limit, &current)
            .is_err());
    }
}

#[test]
fn invalid_wire_documents_cannot_be_constructed_for_storage() {
    let db = Database::new();
    let repo = db.open();
    let valid = value(&scope(), 1);
    for edit in [
        ("revision", json!(0)),
        ("revision", json!(2147483648_u64)),
        ("extra", json!(true)),
        ("schema_id", json!("not-a-uuid")),
        ("project_id", json!(" project")),
    ] {
        let mut bad = valid.clone();
        bad[edit.0] = edit.1;
        assert!(ProjectSchemaDocument::from_json(&bad.to_string()).is_err());
    }
    let mut dangling = valid;
    dangling["mappings"][0]["source_type_id"] = json!(EDGE_ID);
    assert!(ProjectSchemaDocument::from_json(&dangling.to_string()).is_err());
    let duplicate = format!("{{\"revision\":1,{}", &value(&scope(), 1).to_string()[1..]);
    assert!(ProjectSchemaDocument::from_json(&duplicate).is_err());
    assert!(repo
        .read_project_schema_durable(&scope(), &current)
        .unwrap()
        .is_none());
    assert_eq!(db.counts(), (0, 0));
}
