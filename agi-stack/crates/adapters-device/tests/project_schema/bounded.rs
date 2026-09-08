use super::support::*;
use agistack_adapters_device::knowledge::project_schema::ProjectSchemaStorageError;
use std::{cell::Cell, time::Duration};

#[test]
fn byte_budget_returns_whole_contiguous_receipts_and_never_skips_an_oversized_first_item() {
    let db = Database::new();
    let repo = db.open();
    let first = changed(&command(&scope(), 1), |v| {
        v["entity_types"][0]["name"] = serde_json::json!("汉字")
    });
    let receipt = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
        .unwrap();
    repo.replace_project_schema_durable(&scope(), "actor", &command(&scope(), 2), &current)
        .unwrap();
    let page = repo
        .project_schema_history_bounded_durable(
            &scope(),
            0,
            100,
            &|_| Ok(receipt.as_json().len()),
            &current,
        )
        .unwrap();
    assert_eq!(page.schema_id.as_deref(), Some(SCHEMA_ID));
    assert_eq!(
        (
            page.after_revision,
            page.upper_revision,
            page.next_after_revision,
            page.has_more
        ),
        (0, 2, 1, true)
    );
    assert_eq!(page.items, vec![receipt.clone()]);
    assert!(matches!(
        repo.project_schema_history_bounded_durable(
            &scope(),
            0,
            100,
            &|_| Ok(receipt.as_json().len() - 1),
            &current
        ),
        Err(ProjectSchemaStorageError::ResponseTooLarge)
    ));
    let next = repo
        .project_schema_history_bounded_durable(&scope(), 1, 100, &|_| Ok(2_097_152), &current)
        .unwrap();
    assert_eq!(
        (next.next_after_revision, next.has_more, next.items.len()),
        (2, false, 1)
    );
    let empty = repo
        .project_schema_history_bounded_durable(&scope(), 2, 100, &|_| Ok(0), &current)
        .unwrap();
    assert_eq!(
        (empty.next_after_revision, empty.has_more, empty.items.len()),
        (2, false, 0)
    );
}

#[test]
fn page_identity_upper_and_items_share_one_snapshot_even_when_another_writer_advances() {
    let db = Database::new();
    db.sql().execute_batch("PRAGMA journal_mode=WAL").unwrap();
    let repo = db.open();
    repo.bootstrap_project_schema_durable(&scope(), "actor", &command(&scope(), 1), &current)
        .unwrap();
    let other = db.open();
    let invoked = Cell::new(false);
    let page = repo
        .project_schema_history_bounded_durable(
            &scope(),
            0,
            100,
            &|header| {
                assert!(!invoked.replace(true));
                assert_eq!(header.schema_id.as_deref(), Some(SCHEMA_ID));
                assert_eq!(header.upper_revision, 1);
                other.replace_project_schema_durable(
                    &scope(),
                    "actor",
                    &command(&scope(), 2),
                    &current,
                )?;
                Ok(2_097_152)
            },
            &current,
        )
        .unwrap();
    assert_eq!(
        (
            page.upper_revision,
            page.next_after_revision,
            page.items.len()
        ),
        (1, 1, 1)
    );
    assert!(!page.has_more);
    assert_eq!(
        repo.read_project_schema_durable(&scope(), &current)
            .unwrap()
            .unwrap()
            .revision(),
        2
    );
}

#[test]
fn response_preflight_runs_inside_transaction_and_rolls_back_the_whole_acceptance() {
    let db = Database::new();
    let repo = db.open();
    let first = command(&scope(), 1);
    let observed = Cell::new(false);
    let error = repo.bootstrap_project_schema_checked_durable(
        &scope(),
        "actor",
        &first,
        &current,
        &|receipt| {
            observed.set(true);
            assert_eq!(receipt.document().revision(), 1);
            let writer = db.sql();
            writer.busy_timeout(Duration::ZERO).unwrap();
            assert!(writer.execute_batch("BEGIN IMMEDIATE").is_err());
            assert_eq!(db.counts(), (0, 0));
            Err(ProjectSchemaStorageError::ResponseTooLarge)
        },
    );
    assert!(observed.get());
    assert!(matches!(
        error,
        Err(ProjectSchemaStorageError::ResponseTooLarge)
    ));
    assert_eq!(db.counts(), (0, 0));
}

#[test]
fn preflight_replay_uses_exact_original_receipt_without_reading_the_new_head() {
    let db = Database::new();
    let repo = db.open();
    let first = command(&scope(), 1);
    let receipt = repo
        .bootstrap_project_schema_durable(&scope(), "actor", &first, &current)
        .unwrap();
    repo.replace_project_schema_durable(&scope(), "actor", &command(&scope(), 2), &current)
        .unwrap();
    let replay = repo
        .bootstrap_project_schema_checked_durable(&scope(), "actor", &first, &current, &|actual| {
            assert_eq!(actual.as_json(), receipt.as_json());
            Ok(())
        })
        .unwrap();
    assert_eq!(replay, receipt);
    assert_eq!(db.counts(), (1, 2));
}
