use agistack_adapters_device::knowledge::SqliteKnowledgeRepository;
use agistack_core::knowledge::{KnowledgeError, KnowledgeScope, ScopedMemoryRepository};
use agistack_core::Memory;
use futures::executor::block_on;

fn scope(tenant: &str, project: &str) -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: tenant.into(),
        project_id: project.into(),
    }
}

fn memory(project: &str) -> Memory {
    Memory {
        id: "shared-id".into(),
        project_id: project.into(),
        title: "original".into(),
        content: "content".into(),
        author_id: "author".into(),
        content_type: "text".into(),
        tags: vec![],
        entities: vec![],
        version: 1,
        status: "ENABLED".into(),
        created_at_ms: 1,
        embedding: None,
    }
}

#[test]
fn scope_is_required_on_every_read_and_write() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let a = scope("a", "p");
        let b = scope("b", "p");
        let other_project = scope("a", "q");
        let saved = repo.create(&a, memory("p")).await.unwrap();
        for denied in [&b, &other_project] {
            assert!(repo.get(denied, &saved.id).await.unwrap().is_none());
            assert!(repo.list(denied, 10, 0).await.unwrap().is_empty());
            assert!(matches!(
                repo.delete(denied, &saved.id, 1).await,
                Err(KnowledgeError::NotFound)
            ));
        }
        assert!(matches!(
            repo.update(&b, saved.clone(), 1).await,
            Err(KnowledgeError::NotFound)
        ));
        assert!(matches!(
            repo.create(&other_project, saved).await,
            Err(KnowledgeError::InvalidInput)
        ));
        repo.create(&b, memory("p")).await.unwrap();
        repo.delete(&b, "shared-id", 1).await.unwrap();
        assert!(repo.get(&a, "shared-id").await.unwrap().is_some());
    });
}

#[test]
fn revisions_reject_lost_updates_and_resurrection() {
    block_on(async {
        let repo = SqliteKnowledgeRepository::in_memory().unwrap();
        let scope = scope("tenant", "project");
        let first = repo.create(&scope, memory("project")).await.unwrap();
        assert!(matches!(
            repo.create(&scope, first.clone()).await,
            Err(KnowledgeError::Conflict)
        ));
        let mut edited = first.clone();
        edited.title = "updated".into();
        let second = repo.update(&scope, edited, 1).await.unwrap();
        assert_eq!(second.version, 2);
        assert!(matches!(
            repo.update(&scope, first, 1).await,
            Err(KnowledgeError::Conflict)
        ));
        assert!(matches!(
            repo.delete(&scope, &second.id, 1).await,
            Err(KnowledgeError::Conflict)
        ));
        assert_eq!(
            repo.get(&scope, &second.id).await.unwrap().unwrap().title,
            "updated"
        );
        repo.delete(&scope, &second.id, 2).await.unwrap();
        assert!(repo.get(&scope, &second.id).await.unwrap().is_none());
        assert!(repo.list(&scope, usize::MAX, 0).await.unwrap().is_empty());
        assert!(matches!(
            repo.create(&scope, memory("project")).await,
            Err(KnowledgeError::Conflict)
        ));
    });
}

#[test]
fn durable_changes_are_atomic_and_legacy_rows_stay_unattributed() {
    block_on(async {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("knowledge-{}-{unique}.sqlite", std::process::id()));
        let connection = rusqlite::Connection::open(&path).unwrap();
        connection.execute_batch("CREATE TABLE memories(id TEXT PRIMARY KEY, project_id TEXT); INSERT INTO memories VALUES('legacy','project');").unwrap();
        let scope = scope("tenant", "project");
        {
            let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
            assert!(repo.get(&scope, "legacy").await.unwrap().is_none());
            let first = repo.create(&scope, memory("project")).await.unwrap();
            repo.update(&scope, first, 1).await.unwrap();
        }
        let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        let original = repo.get(&scope, "shared-id").await.unwrap().unwrap();
        assert_eq!(original.version, 2);
        connection.execute_batch("CREATE TRIGGER fail_change BEFORE INSERT ON knowledge_processing_changes BEGIN SELECT RAISE(ABORT,'injected failure'); END;").unwrap();
        let mut edited = original.clone();
        edited.content = "must not persist".into();
        assert!(matches!(
            repo.update(&scope, edited, 2).await,
            Err(KnowledgeError::Storage(_))
        ));
        assert!(matches!(
            repo.delete(&scope, &original.id, 2).await,
            Err(KnowledgeError::Storage(_))
        ));
        let mut new_memory = memory("project");
        new_memory.id = "new-id".into();
        assert!(matches!(
            repo.create(&scope, new_memory).await,
            Err(KnowledgeError::Storage(_))
        ));
        assert!(repo.get(&scope, "new-id").await.unwrap().is_none());
        let stored = repo.get(&scope, &original.id).await.unwrap().unwrap();
        assert_eq!(stored.content, original.content);
        assert_eq!(stored.version, 2);
        connection
            .execute_batch("DROP TRIGGER fail_change;")
            .unwrap();
        repo.delete(&scope, &original.id, 2).await.unwrap();
        drop(repo);
        let reopened = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        assert!(reopened.get(&scope, "shared-id").await.unwrap().is_none());
        let revisions: Vec<u32> = connection
            .prepare("SELECT revision FROM knowledge_processing_changes ORDER BY sequence")
            .unwrap()
            .query_map([], |row| row.get(0))
            .unwrap()
            .collect::<Result<_, _>>()
            .unwrap();
        assert_eq!(revisions, vec![1, 2, 3]);
        let legacy_count: usize = connection
            .query_row("SELECT count(*) FROM memories WHERE id='legacy'", [], |r| {
                r.get(0)
            })
            .unwrap();
        assert_eq!(legacy_count, 1);
        drop(reopened);
        drop(connection);
        std::fs::remove_file(path).unwrap();
    });
}

#[test]
fn concurrent_connections_allow_only_one_revision_winner() {
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!(
        "knowledge-cas-{}-{unique}.sqlite",
        std::process::id()
    ));
    let first = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
    let second = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
    let scope = scope("tenant", "project");
    block_on(first.create(&scope, memory("project"))).unwrap();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let workers: Vec<_> = [first, second]
        .into_iter()
        .map(|repo| {
            let barrier = barrier.clone();
            let scope = scope.clone();
            std::thread::spawn(move || {
                barrier.wait();
                block_on(repo.update(&scope, memory("project"), 1))
            })
        })
        .collect();
    let outcomes: Vec<_> = workers
        .into_iter()
        .map(|worker| worker.join().unwrap())
        .collect();
    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        outcomes
            .iter()
            .filter(|result| matches!(result, Err(KnowledgeError::Conflict)))
            .count(),
        1
    );
    let connection = rusqlite::Connection::open(&path).unwrap();
    let changes: usize = connection
        .query_row(
            "SELECT count(*) FROM knowledge_processing_changes",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(changes, 2);
    drop(connection);
    std::fs::remove_file(path).unwrap();
}
