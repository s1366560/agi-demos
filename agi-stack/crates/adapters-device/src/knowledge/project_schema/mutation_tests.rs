//! A later failure must roll back both schema journal and materialized head.
use super::super::{ProjectSchemaDocument, SqliteKnowledgeRepository};
use super::*;
use rusqlite::TransactionBehavior;

fn command(scope: &KnowledgeScope, revision: u32) -> ProjectSchemaMutation {
    let document = json!({
        "format_version":1,"tenant_id":scope.tenant_id,"project_id":scope.project_id,
        "schema_id":"00000000-0000-4000-8000-000000000001",
        "revision":revision,"deleted":false,
        "entity_types":[],"edge_types":[],"mappings":[],"tombstones":[],
    });
    ProjectSchemaMutation {
        document: ProjectSchemaDocument::from_json(&document.to_string()).unwrap(),
        expected_revision: revision - 1,
        change_id: uuid::Uuid::new_v4().to_string(),
    }
}

#[test]
fn enclosing_transaction_failure_rolls_back_bootstrap_and_replace_acceptance() {
    let repo = SqliteKnowledgeRepository::open(":memory:").unwrap();
    let scope = KnowledgeScope {
        tenant_id: "tenant".into(),
        project_id: "project".into(),
    };
    for revision in [1, 2] {
        let command = command(&scope, revision);
        let operation = if revision == 1 {
            "bootstrap"
        } else {
            "replace"
        };
        {
            let mut conn = repo.conn.lock().unwrap();
            let tx = conn
                .transaction_with_behavior(TransactionBehavior::Immediate)
                .unwrap();
            let write = ValidatedMutation::new(&scope, "actor", &command, operation).unwrap();
            let receipt = write.apply_in_tx(&tx, None).unwrap();
            assert_eq!(
                read::head(&tx, &scope).unwrap().as_ref(),
                Some(receipt.document())
            );
            assert!(read::receipt(&tx, &scope, "actor", &command.change_id)
                .unwrap()
                .is_some());
            // Emulate a failed pair/cursor CAS after acceptance, before outer commit.
            tx.rollback().unwrap();
        }
        let head = repo
            .read_project_schema_durable(&scope, &|| Ok(()))
            .unwrap();
        assert_eq!(
            head.map(|document| document.revision()),
            (revision > 1).then_some(revision - 1)
        );
        assert!(repo
            .project_schema_receipt_durable(&scope, "actor", &command.change_id, &|| Ok(()))
            .unwrap()
            .is_none());
        // The same immutable command can still be accepted after the rolled-back attempt.
        let accepted = if revision == 1 {
            repo.bootstrap_project_schema_durable(&scope, "actor", &command, &|| Ok(()))
        } else {
            repo.replace_project_schema_durable(&scope, "actor", &command, &|| Ok(()))
        }
        .unwrap();
        let mut conn = repo.conn.lock().unwrap();
        let tx = conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .unwrap();
        let write = ValidatedMutation::new(&scope, "actor", &command, operation).unwrap();
        assert_eq!(write.apply_in_tx(&tx, None).unwrap(), accepted);
        tx.rollback().unwrap();
    }
}
