//! Sync storage orchestration over the projection layer. Every test uses the
//! real SQLite guards, triggers and journal; no production admission is opened.
use super::super::super::KNOWLEDGE_SCHEMA_VERSION;
use super::super::{
    ProjectSchemaDocument, ProjectSchemaMutation, ProjectSchemaStorageError,
    SqliteKnowledgeRepository,
};
use super::*;
use agistack_core::knowledge::sync::push::KnowledgeSyncTarget;
use agistack_core::knowledge::sync::KnowledgeSyncLink;
use agistack_core::knowledge::KnowledgeScope;
use agistack_core::project_schema::cloud_rpc::{CloudSchemaReceipt, CloudSchemaReplaceRequest};
use agistack_core::project_schema::{projection, ProjectSchemaError};
use serde_json::{json, Value};

const SCHEMA: &str = "00000000-0000-4000-8000-000000000001";
const MEMBER: &str = "00000000-0000-4000-8000-000000000002";
const SECOND: &str = "00000000-0000-4000-8000-000000000003";
const CHANGE: &str = "00000000-0000-4000-8000-999999999999";
const NEXT_CHANGE: &str = "00000000-0000-4000-8000-999999999998";
const THIRD_CHANGE: &str = "00000000-0000-4000-8000-999999999997";
const FOURTH_CHANGE: &str = "00000000-0000-4000-8000-999999999996";
const STEP: &str = "00000000-0000-4000-8000-999999999995";
const OTHER_STEP: &str = "00000000-0000-4000-8000-999999999994";
const SYNC_KEY: &str = "00000000-0000-4000-8000-999999999993";

fn scope() -> KnowledgeScope {
    KnowledgeScope {
        tenant_id: "local-tenant".into(),
        project_id: "local-project".into(),
    }
}

fn binding() -> ProjectSchemaSyncBinding {
    ProjectSchemaSyncBinding {
        sync_key: SYNC_KEY.into(),
        scope: scope(),
        authority: "https://cloud.example/api/v1".into(),
        remote_tenant_id: "remote-tenant".into(),
        remote_project_id: "remote-project".into(),
        remote_actor_id: "remote-actor".into(),
        schema_id: SCHEMA.into(),
    }
}

fn repository() -> SqliteKnowledgeRepository {
    SqliteKnowledgeRepository::in_memory().unwrap()
}

fn bind(repo: &SqliteKnowledgeRepository) {
    repo.bind_verified_sync_target_durable(
        &scope(),
        &KnowledgeSyncTarget {
            authority: "https://cloud.example/api/v1".into(),
            link: KnowledgeSyncLink {
                remote_tenant_id: "remote-tenant".into(),
                remote_project_id: "remote-project".into(),
                remote_actor_id: "remote-actor".into(),
            },
        },
        &|| Ok(()),
    )
    .unwrap();
}

fn begin(repo: &SqliteKnowledgeRepository) -> ProjectSchemaSyncState {
    repo.begin_project_schema_sync_durable(&binding(), &|| Ok(()))
        .unwrap()
}

fn member(id: &str, name: &str) -> Value {
    json!({"id":id,"name":name,"description":"","schema":{},"status":"ENABLED","source":"user"})
}

fn document(
    tenant: &str,
    project: &str,
    revision: u32,
    members: Value,
    tombstones: Value,
) -> Value {
    json!({"format_version":1,"tenant_id":tenant,"project_id":project,"schema_id":SCHEMA,
        "revision":revision,"deleted":false,
        "entity_types":members,"edge_types":[],"mappings":[],"tombstones":tombstones})
}

fn cloud_document(revision: u32, members: Value, tombstones: Value) -> Value {
    document(
        "remote-tenant",
        "remote-project",
        revision,
        members,
        tombstones,
    )
}

fn cloud_receipt(document: &Value, change: &str) -> CloudSchemaReceipt {
    let raw = json!({"schema_id":SCHEMA,"revision":document["revision"],
        "sequence":document["revision"],"change_id":change,"document":document})
    .to_string();
    CloudSchemaReceipt::from_json(&raw, "remote-tenant", "remote-project").unwrap()
}

fn native_bootstrap(repo: &SqliteKnowledgeRepository, document: Value, change: &str) {
    repo.bootstrap_project_schema_durable(
        &scope(),
        "local-actor",
        &ProjectSchemaMutation {
            document: ProjectSchemaDocument::from_json(&document.to_string()).unwrap(),
            expected_revision: 0,
            change_id: change.into(),
        },
        &|| Ok(()),
    )
    .unwrap();
}

fn native_replace(repo: &SqliteKnowledgeRepository, document: Value, expected: u32, change: &str) {
    repo.replace_project_schema_durable(
        &scope(),
        "local-actor",
        &ProjectSchemaMutation {
            document: ProjectSchemaDocument::from_json(&document.to_string()).unwrap(),
            expected_revision: expected,
            change_id: change.into(),
        },
        &|| Ok(()),
    )
    .unwrap();
}

fn native_head(repo: &SqliteKnowledgeRepository) -> ProjectSchemaDocument {
    repo.read_project_schema_durable(&scope(), &|| Ok(()))
        .unwrap()
        .unwrap()
}

#[test]
fn migration_is_additive_and_preserves_existing_knowledge_data() {
    let path = std::env::temp_dir().join(format!("schema-sync-{}.db", uuid::Uuid::new_v4()));
    {
        let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
        let conn = repo.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO knowledge_memories
             (tenant_id,project_id,id,revision,deleted,created_at_ms,payload)
             VALUES('local-tenant','local-project','memory-before-sync',1,0,1,'{}')",
            [],
        )
        .unwrap();
    }
    let repo = SqliteKnowledgeRepository::open(path.to_str().unwrap()).unwrap();
    {
        let conn = repo.conn.lock().unwrap();
        let version: i64 = conn
            .query_row("SELECT version FROM knowledge_schema", [], |row| row.get(0))
            .unwrap();
        assert_eq!(version, KNOWLEDGE_SCHEMA_VERSION);
        let objects: u32 = conn
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE name IN (
             'knowledge_project_schema_sync_cursors','knowledge_project_schema_prepared',
             'knowledge_project_schema_sync_anchors')",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(objects, 3);
        let kept: String = conn
            .query_row(
                "SELECT id FROM knowledge_memories WHERE id='memory-before-sync'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(kept, "memory-before-sync");
    }
    drop(repo);
    let _ = std::fs::remove_file(path);
}

#[test]
fn begin_requires_the_memory_binding_and_replays_identically() {
    let repo = repository();
    let binding = binding();
    assert!(matches!(
        repo.begin_project_schema_sync_durable(&binding, &|| Ok(())),
        Err(ProjectSchemaStorageError::SyncConflict)
    ));
    bind(&repo);
    let state = begin(&repo);
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (0, 0, 0)
    );
    assert!(state.head.is_none());
    let replayed = repo
        .begin_project_schema_sync_durable(&binding, &|| Ok(()))
        .unwrap();
    assert_eq!(replayed, state);
    let mut other = binding.clone();
    other.remote_actor_id = "another-actor".into();
    assert!(matches!(
        repo.begin_project_schema_sync_durable(&other, &|| Ok(())),
        Err(ProjectSchemaStorageError::SyncConflict)
    ));
    assert_eq!(
        repo.project_schema_sync_state_durable(&binding, &|| Ok(()))
            .unwrap(),
        Some(state)
    );
}

#[test]
fn initialize_projects_the_cloud_root_into_an_empty_native_scope() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        CHANGE,
    );
    let state = repo
        .initialize_project_schema_pull_durable(
            &binding(),
            &root,
            "local-actor",
            NEXT_CHANGE,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (1, 1, 1)
    );
    let anchor = state.head.unwrap();
    assert_eq!(anchor.kind, ProjectSchemaSyncAnchorKind::Pair);
    assert_eq!(anchor.imported_side, ProjectSchemaSyncImportedSide::Native);
    assert_eq!(anchor.cloud_receipt, root);
    let head = native_head(&repo);
    assert_eq!(head.revision(), 1);
    assert_eq!(head.tenant_id(), "local-tenant");
    assert_eq!(head.entity_types()[0].id, MEMBER);
    assert!(projection::equivalent_content(&head, root.document()));
    assert!(repo
        .project_schema_sync_pending_durable(&binding(), &|| Ok(()))
        .unwrap()
        .is_none());
    assert!(matches!(
        repo.initialize_project_schema_pull_durable(
            &binding(),
            &root,
            "local-actor",
            THIRD_CHANGE,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::SyncConflict)
    ));
}

#[test]
fn initialize_never_overwrites_divergent_native_content() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    native_bootstrap(
        &repo,
        document(
            "local-tenant",
            "local-project",
            1,
            json!([member(SECOND, "组织")]),
            json!([]),
        ),
        CHANGE,
    );
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        NEXT_CHANGE,
    );
    assert!(matches!(
        repo.initialize_project_schema_pull_durable(
            &binding(),
            &root,
            "local-actor",
            THIRD_CHANGE,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::Document(
            ProjectSchemaError::RevisionConflict
        ))
    ));
    let state = repo
        .project_schema_sync_state_durable(&binding(), &|| Ok(()))
        .unwrap()
        .unwrap();
    assert_eq!((state.epoch, state.head.is_none()), (0, true));
    let head = native_head(&repo);
    assert_eq!(head.entity_types()[0].id, SECOND);
}

#[test]
fn initialize_transfers_the_root_after_an_accepted_empty_native_seed() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    native_bootstrap(
        &repo,
        document("local-tenant", "local-project", 1, json!([]), json!([])),
        CHANGE,
    );
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        NEXT_CHANGE,
    );
    let state = repo
        .initialize_project_schema_pull_durable(
            &binding(),
            &root,
            "local-actor",
            THIRD_CHANGE,
            &|| Ok(()),
        )
        .unwrap();
    let anchor = state.head.unwrap();
    assert_eq!((anchor.native_revision(), anchor.cloud_revision()), (2, 1));
    assert_eq!(anchor.imported_side, ProjectSchemaSyncImportedSide::Native);
    let head = native_head(&repo);
    assert_eq!(head.revision(), 2);
    assert!(projection::equivalent_content(&head, root.document()));
}

#[test]
fn initialize_binds_independently_equivalent_heads_without_a_write() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    native_bootstrap(
        &repo,
        document(
            "local-tenant",
            "local-project",
            1,
            json!([member(MEMBER, "人物")]),
            json!([]),
        ),
        CHANGE,
    );
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        NEXT_CHANGE,
    );
    let state = repo
        .initialize_project_schema_pull_durable(
            &binding(),
            &root,
            "local-actor",
            THIRD_CHANGE,
            &|| Ok(()),
        )
        .unwrap();
    let anchor = state.head.unwrap();
    assert_eq!(anchor.imported_side, ProjectSchemaSyncImportedSide::Neither);
    assert_eq!((anchor.native_revision(), anchor.cloud_revision()), (1, 1));
    assert_eq!(native_head(&repo).revision(), 1);
    let journal = repo
        .project_schema_changes_durable(&scope(), 0, 100, &|| Ok(()))
        .unwrap();
    assert_eq!(journal.items.len(), 1);
}

#[test]
fn initialize_rejects_non_root_and_cross_scope_sources() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let later = cloud_receipt(
        &cloud_document(2, json!([member(MEMBER, "人物")]), json!([])),
        CHANGE,
    );
    assert!(matches!(
        repo.initialize_project_schema_pull_durable(
            &binding(),
            &later,
            "local-actor",
            NEXT_CHANGE,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::Document(
            ProjectSchemaError::InvalidTransition
        ))
    ));
    let foreign = document("other-tenant", "other-project", 1, json!([]), json!([]));
    let raw = json!({"schema_id":SCHEMA,"revision":1,"sequence":1,"change_id":CHANGE,
        "document":foreign})
    .to_string();
    let receipt = CloudSchemaReceipt::from_json(&raw, "other-tenant", "other-project").unwrap();
    assert!(matches!(
        repo.initialize_project_schema_pull_durable(
            &binding(),
            &receipt,
            "local-actor",
            NEXT_CHANGE,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::ScopeMismatch)
    ));
}

#[test]
fn apply_projects_the_adjacent_transition_and_preserves_tombstones() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let root = cloud_receipt(
        &cloud_document(
            1,
            json!([member(MEMBER, "人物"), member(SECOND, "组织")]),
            json!([]),
        ),
        CHANGE,
    );
    repo.initialize_project_schema_pull_durable(
        &binding(),
        &root,
        "local-actor",
        NEXT_CHANGE,
        &|| Ok(()),
    )
    .unwrap();
    let removed = cloud_document(
        2,
        json!([member(MEMBER, "人物")]),
        json!([{"id":SECOND,"kind":"entity_type","deleted_revision":2}]),
    );
    let source = cloud_receipt(&removed, NEXT_CHANGE);
    let state = repo
        .apply_project_schema_pull_durable(
            &binding(),
            &source,
            "local-actor",
            THIRD_CHANGE,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (2, 2, 2)
    );
    let anchor = state.head.unwrap();
    assert_eq!(anchor.imported_side, ProjectSchemaSyncImportedSide::Native);
    let head = native_head(&repo);
    assert_eq!(head.revision(), 2);
    assert_eq!(head.entity_types().len(), 1);
    assert_eq!(head.tombstones()[0].id, SECOND);
    assert_eq!(head.tombstones()[0].deleted_revision, 2);
}

#[test]
fn apply_rejects_non_adjacent_sources_and_consumed_replays() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        CHANGE,
    );
    repo.initialize_project_schema_pull_durable(
        &binding(),
        &root,
        "local-actor",
        NEXT_CHANGE,
        &|| Ok(()),
    )
    .unwrap();
    let gap = cloud_receipt(
        &cloud_document(3, json!([member(MEMBER, "人物")]), json!([])),
        NEXT_CHANGE,
    );
    assert!(matches!(
        repo.apply_project_schema_pull_durable(
            &binding(),
            &gap,
            "local-actor",
            THIRD_CHANGE,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::Document(
            ProjectSchemaError::RevisionConflict
        ))
    ));
    let second = cloud_receipt(
        &cloud_document(
            2,
            json!([member(MEMBER, "人物"), member(SECOND, "组织")]),
            json!([]),
        ),
        NEXT_CHANGE,
    );
    repo.apply_project_schema_pull_durable(
        &binding(),
        &second,
        "local-actor",
        THIRD_CHANGE,
        &|| Ok(()),
    )
    .unwrap();
    assert!(matches!(
        repo.apply_project_schema_pull_durable(
            &binding(),
            &second,
            "local-actor",
            FOURTH_CHANGE,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::Document(
            ProjectSchemaError::RevisionConflict
        ))
    ));
    let state = repo
        .project_schema_sync_state_durable(&binding(), &|| Ok(()))
        .unwrap()
        .unwrap();
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (2, 2, 2)
    );
}

#[test]
fn apply_fails_closed_when_the_local_head_moved() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        CHANGE,
    );
    repo.initialize_project_schema_pull_durable(
        &binding(),
        &root,
        "local-actor",
        NEXT_CHANGE,
        &|| Ok(()),
    )
    .unwrap();
    native_replace(
        &repo,
        document(
            "local-tenant",
            "local-project",
            2,
            json!([member(MEMBER, "人物"), member(SECOND, "组织")]),
            json!([]),
        ),
        1,
        THIRD_CHANGE,
    );
    let source = cloud_receipt(
        &cloud_document(2, json!([member(MEMBER, "人物")]), json!([])),
        NEXT_CHANGE,
    );
    assert!(matches!(
        repo.apply_project_schema_pull_durable(
            &binding(),
            &source,
            "local-actor",
            FOURTH_CHANGE,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::SyncConflict)
    ));
    let state = repo
        .project_schema_sync_state_durable(&binding(), &|| Ok(()))
        .unwrap()
        .unwrap();
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (1, 1, 1)
    );
}

fn prepared_cloud_step(
    repo: &SqliteKnowledgeRepository,
) -> (CloudSchemaReplaceRequest, CloudSchemaReceipt) {
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        CHANGE,
    );
    let state = repo
        .initialize_project_schema_pull_durable(
            &binding(),
            &root,
            "local-actor",
            NEXT_CHANGE,
            &|| Ok(()),
        )
        .unwrap();
    native_replace(
        repo,
        document(
            "local-tenant",
            "local-project",
            2,
            json!([member(MEMBER, "人物"), member(SECOND, "组织")]),
            json!([]),
        ),
        1,
        THIRD_CHANGE,
    );
    let anchor = state.head.unwrap();
    let head = native_head(repo);
    let projected = projection::project_successor(
        anchor.native_receipt.as_ref().unwrap().document(),
        &head,
        anchor.cloud_receipt.document(),
    )
    .unwrap();
    let request =
        CloudSchemaReplaceRequest::new(&anchor.cloud_receipt, &projected, NEXT_CHANGE).unwrap();
    (request, anchor.cloud_receipt)
}

#[test]
fn cloud_replace_prepare_replays_and_completes_with_the_actual_receipt() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let (request, _) = prepared_cloud_step(&repo);
    let prepared = repo
        .prepare_project_schema_cloud_replace_durable(
            &binding(),
            "local-actor",
            &request,
            STEP,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(prepared.kind, ProjectSchemaSyncStepKind::CloudReplace);
    assert_eq!(prepared.destination_change_id, NEXT_CHANGE);
    assert_eq!(prepared.request_json, request.as_json());
    assert_eq!(prepared.completed_anchor_id, None);
    let replayed = repo
        .prepare_project_schema_cloud_replace_durable(
            &binding(),
            "local-actor",
            &request,
            STEP,
            &|| Ok(()),
        )
        .unwrap();
    assert_eq!(replayed, prepared);
    assert!(matches!(
        repo.prepare_project_schema_cloud_replace_durable(
            &binding(),
            "local-actor",
            &request,
            OTHER_STEP,
            &|| Ok(())
        ),
        Err(ProjectSchemaStorageError::SyncConflict)
    ));
    let acceptance = cloud_receipt(&request.document().to_value(), NEXT_CHANGE);
    let state = repo
        .complete_project_schema_cloud_replace_durable(&binding(), STEP, &acceptance, &|| Ok(()))
        .unwrap();
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (2, 2, 2)
    );
    let anchor = state.head.unwrap();
    assert_eq!(anchor.imported_side, ProjectSchemaSyncImportedSide::Cloud);
    assert_eq!((anchor.native_revision(), anchor.cloud_revision()), (2, 2));
    assert!(repo
        .project_schema_sync_pending_durable(&binding(), &|| Ok(()))
        .unwrap()
        .is_none());
    assert!(matches!(
        repo.complete_project_schema_cloud_replace_durable(&binding(), STEP, &acceptance, &|| Ok(
            ()
        )),
        Err(ProjectSchemaStorageError::SyncConflict)
    ));
}

#[test]
fn cloud_replace_completion_accepts_only_the_actual_receipt() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let (request, _) = prepared_cloud_step(&repo);
    repo.prepare_project_schema_cloud_replace_durable(
        &binding(),
        "local-actor",
        &request,
        STEP,
        &|| Ok(()),
    )
    .unwrap();
    let wrong = cloud_receipt(&request.document().to_value(), CHANGE);
    assert!(matches!(
        repo.complete_project_schema_cloud_replace_durable(&binding(), STEP, &wrong, &|| Ok(())),
        Err(ProjectSchemaStorageError::SyncConflict)
    ));
    let pending = repo
        .project_schema_sync_pending_durable(&binding(), &|| Ok(()))
        .unwrap()
        .unwrap();
    assert_eq!(pending.step_id, STEP);
    let state = repo
        .project_schema_sync_state_durable(&binding(), &|| Ok(()))
        .unwrap()
        .unwrap();
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (1, 1, 1)
    );
}

#[test]
fn guards_reject_direct_cursor_prepared_and_anchor_mutation() {
    let repo = repository();
    bind(&repo);
    begin(&repo);
    let root = cloud_receipt(
        &cloud_document(1, json!([member(MEMBER, "人物")]), json!([])),
        CHANGE,
    );
    repo.initialize_project_schema_pull_durable(
        &binding(),
        &root,
        "local-actor",
        NEXT_CHANGE,
        &|| Ok(()),
    )
    .unwrap();
    let conn = repo.conn.lock().unwrap();
    for statement in [
        "DELETE FROM knowledge_project_schema_sync_cursors",
        "UPDATE knowledge_project_schema_sync_cursors SET epoch=epoch+2",
        "UPDATE knowledge_project_schema_sync_cursors SET schema_id='other'",
        "UPDATE knowledge_project_schema_sync_anchors SET kind='source_seed'",
        "DELETE FROM knowledge_project_schema_sync_anchors",
        "UPDATE knowledge_project_schema_prepared SET request_json='{}'",
        "DELETE FROM knowledge_project_schema_prepared",
        "INSERT INTO knowledge_project_schema_sync_anchors
         (anchor_id,sync_key,producing_step_id,kind,cloud_receipt,native_revision,cloud_revision,imported_side)
         VALUES('00000000-0000-4000-8000-999999999992','x','00000000-0000-4000-8000-999999999991',
                'source_seed','{}',0,1,'neither')",
    ] {
        assert!(conn.execute(statement, []).is_err(), "{statement}");
    }
    drop(conn);
    let state = repo
        .project_schema_sync_state_durable(&binding(), &|| Ok(()))
        .unwrap()
        .unwrap();
    assert_eq!(
        (state.epoch, state.native_after, state.cloud_after),
        (1, 1, 1)
    );
}
