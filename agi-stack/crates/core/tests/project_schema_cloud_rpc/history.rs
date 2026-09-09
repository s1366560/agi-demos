use super::*;

fn history_raw(items: &[String], upper: u32, next: u32, more: bool) -> String {
    format!("{{\"schema_id\":\"{SCHEMA}\",\"upper_revision\":{upper},\"next_after_revision\":{next},\"has_more\":{more},\"receipts\":[{}]}}", items.join(","))
}

#[test]
fn root_prefix_and_resume_validate_adjacency_and_retain_receipt_bytes() {
    let first = receipt_raw(&document(1), CHANGE);
    let second = receipt_raw(&document(2), NEXT_CHANGE);
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 1).unwrap();
    let page = CloudSchemaHistoryPage::from_json(
        &history_raw(std::slice::from_ref(&first), 2, 1, true),
        "tenant-a",
        "project-a",
        &query,
        None,
    )
    .unwrap();
    assert_eq!(page.schema_id(), SCHEMA);
    assert_eq!(page.upper_revision(), 2);
    assert_eq!(page.next_after_revision(), 1);
    assert!(page.has_more());
    assert_eq!(page.receipts()[0].as_json(), first);
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 1, 1).unwrap();
    let page = CloudSchemaHistoryPage::from_json(
        &history_raw(std::slice::from_ref(&second), 2, 2, false),
        "tenant-a",
        "project-a",
        &query,
        page.receipts().first(),
    )
    .unwrap();
    assert_eq!(page.receipts()[0].as_json(), second);
    assert!(!page.has_more());
}

#[test]
fn cloud_history_does_not_assume_change_ids_are_global_across_actors() {
    let raw = history_raw(
        &[
            receipt_raw(&document(1), CHANGE),
            receipt_raw(&document(2), CHANGE),
        ],
        2,
        2,
        false,
    );
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 100).unwrap();
    assert!(CloudSchemaHistoryPage::from_json(&raw, "tenant-a", "project-a", &query, None).is_ok());
}

#[test]
fn unrelated_or_missing_predecessor_cannot_validate_a_noninitial_page() {
    let raw = history_raw(&[receipt_raw(&document(2), CHANGE)], 2, 2, false);
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 1, 1).unwrap();
    assert!(
        CloudSchemaHistoryPage::from_json(&raw, "tenant-a", "project-a", &query, None).is_err()
    );
    for prior in [receipt(&document(2)), {
        let mut doc = document(1);
        doc["tenant_id"] = json!("other");
        CloudSchemaReceipt::from_json(&receipt_raw(&doc, CHANGE), "other", "project-a").unwrap()
    }] {
        assert!(CloudSchemaHistoryPage::from_json(
            &raw,
            "tenant-a",
            "project-a",
            &query,
            Some(&prior)
        )
        .is_err());
    }
}

#[test]
fn history_rejects_every_inconsistent_cursor_and_page_relationship() {
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 1).unwrap();
    let root = receipt_raw(&document(1), CHANGE);
    for raw in [
        history_raw(std::slice::from_ref(&root), 0, 1, false),
        history_raw(std::slice::from_ref(&root), 2, 1, false),
        history_raw(std::slice::from_ref(&root), 1, 1, true),
        history_raw(std::slice::from_ref(&root), 1, 0, false),
        history_raw(&[], 1, 0, true),
        history_raw(
            &[root.clone(), receipt_raw(&document(2), CHANGE)],
            2,
            2,
            false,
        ),
        history_raw(&[receipt_raw(&document(2), CHANGE)], 2, 1, true),
        history_raw(&[receipt_raw(&document(3), CHANGE)], 3, 1, true),
    ] {
        assert!(
            CloudSchemaHistoryPage::from_json(&raw, "tenant-a", "project-a", &query, None).is_err(),
            "{raw}"
        );
    }
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 100).unwrap();
    for items in [
        vec![root.clone(), root],
        vec![
            receipt_raw(&document(2), CHANGE),
            receipt_raw(&document(1), CHANGE),
        ],
    ] {
        assert!(CloudSchemaHistoryPage::from_json(
            &history_raw(&items, 2, 2, false),
            "tenant-a",
            "project-a",
            &query,
            None
        )
        .is_err());
    }
}

#[test]
fn tombstones_are_retained_and_terminal_history_cannot_claim_later_revisions() {
    let root = document(1);
    let mut removed = document(2);
    removed["entity_types"] = json!([]);
    removed["tombstones"] = json!([{"id":MEMBER,"kind":"entity_type","deleted_revision":2}]);
    let mut terminal = removed.clone();
    terminal["revision"] = json!(3);
    terminal["deleted"] = json!(true);
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 100).unwrap();
    let items = [
        receipt_raw(&root, CHANGE),
        receipt_raw(&removed, CHANGE),
        receipt_raw(&terminal, CHANGE),
    ];
    let raw = history_raw(&items, 3, 3, false);
    assert!(CloudSchemaHistoryPage::from_json(&raw, "tenant-a", "project-a", &query, None).is_ok());
    assert!(CloudSchemaHistoryPage::from_json(
        &history_raw(&items, 4, 3, true),
        "tenant-a",
        "project-a",
        &query,
        None
    )
    .is_err());
    for bad in [
        {
            let mut d = terminal.clone();
            d["tombstones"][0]["deleted_revision"] = json!(3);
            d
        },
        {
            let mut d = terminal.clone();
            d["tombstones"] = json!([]);
            d
        },
        document(3),
    ] {
        let invalid = history_raw(
            &[
                items[0].clone(),
                items[1].clone(),
                receipt_raw(&bad, CHANGE),
            ],
            3,
            3,
            false,
        );
        assert!(
            CloudSchemaHistoryPage::from_json(&invalid, "tenant-a", "project-a", &query, None)
                .is_err()
        );
    }
    let prior = receipt(&terminal);
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 3, 1).unwrap();
    assert!(CloudSchemaHistoryPage::from_json(
        &history_raw(&[], 3, 3, false),
        "tenant-a",
        "project-a",
        &query,
        Some(&prior)
    )
    .is_ok());
    assert!(CloudSchemaHistoryPage::from_json(
        &history_raw(&[], 4, 3, true),
        "tenant-a",
        "project-a",
        &query,
        Some(&prior)
    )
    .is_err());
}

#[test]
fn nested_duplicate_keys_and_oversize_streams_never_become_history() {
    let query = CloudSchemaHistoryQuery::new(SCHEMA, 0, 100).unwrap();
    let good = history_raw(&[receipt_raw(&document(1), CHANGE)], 1, 1, false);
    for bad in [
        good.replace(
            "\"upper_revision\":1",
            "\"upper_revision\":1,\"upper_revision\":1",
        ),
        good.replace("\"sequence\" : 1", "\"sequence\" : 1,\"sequence\":1"),
        good.replace("\"number\":0.25", "\"number\":0.25,\"number\":1"),
        good.replace("\"upper_revision\":1", "\"upper_revision\":1.0"),
        good.replace("\"next_after_revision\":1", "\"next_after_revision\":1e0"),
        good.clone() + &" ".repeat(MAX_CLOUD_SCHEMA_BYTES),
    ] {
        assert!(
            CloudSchemaHistoryPage::from_json(&bad, "tenant-a", "project-a", &query, None).is_err()
        );
    }
    let over_count = history_raw(&vec!["null".into(); 101], 101, 101, false);
    assert!(
        CloudSchemaHistoryPage::from_json(&over_count, "tenant-a", "project-a", &query, None)
            .is_err()
    );
}
