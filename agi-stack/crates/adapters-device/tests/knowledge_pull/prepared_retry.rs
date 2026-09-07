use super::*;

struct Database(std::path::PathBuf);
impl Drop for Database {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

#[test]
fn prepared_retry_survives_pull_conflict_without_rebuilding_or_unblocking_new_payload() {
    block_on(async {
        let db = Database(
            std::env::temp_dir().join(format!("prepared-retry-{}.db", uuid::Uuid::new_v4())),
        );
        let repo = SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).unwrap();
        repo.configure_sync_link(&scope(), target().link)
            .await
            .unwrap();
        let original = edges::prepared(&repo).await;
        let mut local = repo.get(&scope(), "memory").await.unwrap().unwrap();
        local.content = "edit after preparation".into();
        repo.mutate(
            &scope(),
            "actor",
            "later edit",
            MemoryMutation::Update {
                memory: local,
                expected_revision: 1,
            },
        )
        .await
        .unwrap();
        let pulled = repo
            .accept_pull_page(
                &scope(),
                &target(),
                0,
                page(vec![event(1, 1, false, "other device")], 1),
            )
            .await
            .unwrap();
        assert_eq!(pulled.conflicts, 1);

        drop(repo);
        let repo = SqliteKnowledgeRepository::open(db.0.to_str().unwrap()).unwrap();

        let retry = repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .expect("prepared immutable request must remain recoverable behind a pull conflict");
        assert_eq!(retry.local_sequence, original.local_sequence);
        assert_eq!(retry.change_id, original.change_id);
        assert_eq!(retry.request_json, original.request_json);
        let mut wrong_target = target();
        wrong_target.authority = "https://other.test/api/v1".into();
        assert!(repo.prepare_push(&scope(), &wrong_target).await.is_err());
        let mut wrong_scope = scope();
        wrong_scope.project_id = "another-project".into();
        assert!(repo.prepare_push(&wrong_scope, &target()).await.is_err());

        let conflict_id = uuid::Uuid::new_v4().to_string();
        let mut proposed: Value = serde_json::from_str(&original.request_json).unwrap();
        proposed.as_object_mut().unwrap().remove("change_id");
        repo.accept_push_receipt(
            &scope(), &target(), original.local_sequence,
            json!({"replayed":false,"receipt":{"status":"conflict","change_id":original.change_id,"conflict_id":conflict_id}}),
            Some(json!({"id":conflict_id,"memory_id":"memory","proposed":proposed,"current":event(1,1,false,"other device")["version"],"resolved_change_id":null})),
        ).await.unwrap();
        assert!(repo
            .prepare_push(&scope(), &target())
            .await
            .unwrap()
            .is_none());
        assert_eq!(repo.pull_conflicts(&scope(), 10).await.unwrap().len(), 1);
        assert_eq!(
            repo.get(&scope(), "memory").await.unwrap().unwrap().content,
            "edit after preparation"
        );
        assert_eq!(repo.changes(&scope(), 0, 10).await.unwrap().len(), 2);
    });
}
