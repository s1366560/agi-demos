use super::*;

#[test]
fn invalid_pages_are_atomic_and_do_not_reserve_change_ids_or_bind_an_origin() {
    block_on(async {
        let mut duplicate = event(2, 2, false, "second");
        duplicate["change_id"] = event(1, 1, false, "first")["change_id"].clone();
        let mut wrong_revision = event(2, 1, false, "non-increasing");
        wrong_revision["version"]["content"]["metadata"] = json!({"preserve":true});
        let mut cases = vec![
            page(vec![event(1, 1, false, "first"), duplicate], 2),
            page(vec![event(1, 1, false, "first"), wrong_revision], 2),
            page(
                vec![event(2, 1, false, "first"), event(1, 2, false, "second")],
                1,
            ),
            page(vec![event(0, 1, false, "zero")], 0),
            page(vec![event(1, 0, false, "zero revision")], 1),
            page(
                vec![event(1, i32::MAX as u32 + 1, false, "overflow revision")],
                1,
            ),
            page(vec![event(1, 1, false, "first")], 2),
            page(vec![], 1),
            json!({"changes":[],"next_cursor":0,"has_more":true}),
            json!({"changes":[],"next_cursor":i64::MAX as u64+1,"has_more":false}),
            page(vec![event(1, 1, false, "too many"); 501], 1),
        ];
        let mut noncanonical = event(1, 1, false, "invalid id");
        noncanonical["change_id"] = json!("no-uuid");
        cases.push(page(vec![noncanonical], 1));
        for response in cases {
            let repo = repository().await;
            assert!(repo
                .accept_pull_page(&scope(), &target(), 0, response)
                .await
                .is_err());
            assert!(repo.get(&scope(), "memory").await.unwrap().is_none());
            assert!(repo.changes(&scope(), 0, 10).await.unwrap().is_empty());
            assert!(repo.pull_conflicts(&scope(), 10).await.unwrap().is_empty());
            // Binding an origin is in the same rolled-back transaction.
            let mut another = target();
            another.authority = "https://another.test/api/v1".into();
            assert_eq!(repo.pull_cursor(&scope(), &another).await.unwrap(), 0);
            repo.accept_pull_page(
                &scope(),
                &another,
                0,
                page(vec![event(1, 1, false, "valid")], 1),
            )
            .await
            .unwrap();
        }
    });
}

#[test]
fn empty_page_and_has_more_pages_preserve_monotonic_cursor_without_reindexing() {
    block_on(async {
        let repo = repository().await;
        let mut first = page(vec![event(11, 1, false, "first")], 11);
        first["has_more"] = json!(true);
        assert!(
            repo.accept_pull_page(&scope(), &target(), 0, first)
                .await
                .unwrap()
                .has_more
        );
        let empty = repo
            .accept_pull_page(&scope(), &target(), 11, page(vec![], 11))
            .await
            .unwrap();
        assert_eq!(
            (
                empty.next_cursor,
                empty.applied,
                empty.conflicts,
                empty.has_more
            ),
            (11, 0, 0, false)
        );
        repo.accept_pull_page(
            &scope(),
            &target(),
            11,
            page(vec![event(19, 2, false, "second")], 19),
        )
        .await
        .unwrap();
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 2);
        assert_eq!(repo.pull_cursor(&scope(), &target()).await.unwrap(), 19);
    });
}
