use std::collections::BTreeMap;
use std::error::Error;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder};
use bcs_db_postgres::PostgresDbPlugin;
use bcs_storage_api::{ByteStream, byte_stream_from_bytes};
use bytes::Bytes;
use futures::StreamExt;
use memstack_workspace_service::{
    CreateWorkspaceContentInput, CreateWorkspaceInput, CreateWorkspaceOwnerInput,
    CreateWorkspaceScopeInput, ObjectStageRequest, ObjectStoreError, ObjectStorePort,
    PublicWorkspaceFileContext, PublicWorkspaceFileErrorKind, PublicWorkspaceFileService,
    ReadyObjectReference, StagedObjectReference, WorkspaceCreationService,
};
use serde_json::json;
use sha2::{Digest, Sha256};

const TENANT_ID: &str = "tenant-file-pg-contract";
const PROJECT_ID: &str = "project-file-pg-contract";
const WORKSPACE_ID: &str = "workspace-file-pg-contract";
const GROUP_ID: &str = "group-file-pg-contract";
const USER_ID: &str = "actor-file-pg-contract";
const PAYLOAD: &[u8] = b"Avernet PostgreSQL File authority\n";

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and the Alembic-owned Avernet schema"]
async fn postgres_file_preserves_reservation_finalize_replay_cas_copy_delete_and_compensation()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    let objects = Arc::new(TestObjectStore::default());
    let service = PublicWorkspaceFileService::new(&db, DbSqlFlavor::Postgres, objects.clone());
    let checksum = checksum(PAYLOAD);

    let uploaded = service
        .upload(
            &file_context("file-upload", 1),
            "/",
            "authority.txt",
            "text/plain",
            u64::try_from(PAYLOAD.len())?,
            checksum.as_str(),
            byte_stream_from_bytes(Bytes::from_static(PAYLOAD)),
        )
        .await?;
    let replayed = service
        .upload(
            &file_context("file-upload", 1),
            "/",
            "authority.txt",
            "text/plain",
            u64::try_from(PAYLOAD.len())?,
            checksum.as_str(),
            byte_stream_from_bytes(Bytes::from_static(PAYLOAD)),
        )
        .await?;

    assert_eq!(uploaded.file, replayed.file);
    assert_eq!(uploaded.committed_revision, 2);
    assert!(!uploaded.replayed);
    assert!(replayed.replayed);
    assert_eq!(objects.stage_count.load(Ordering::Relaxed), 1);
    assert_eq!(objects.finalize_count.load(Ordering::Relaxed), 1);
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(file_state(&db, uploaded.file.id.as_str()).await?, "ready");
    assert_eq!(operation_state(&db, "file-upload").await?, "completed");

    let copied = service
        .copy(
            &file_context("file-copy", 2),
            uploaded.file.id.as_str(),
            "/",
            Some("copy.txt"),
        )
        .await?;
    assert_eq!(copied.committed_revision, 3);
    assert_eq!(objects.copy_count.load(Ordering::Relaxed), 1);

    let stale = require_error(
        service
            .delete(
                &file_context("file-delete-stale", 2),
                uploaded.file.id.as_str(),
                false,
            )
            .await,
        "stale File authority revision must fail",
    );
    assert_eq!(stale.kind(), PublicWorkspaceFileErrorKind::Conflict);
    assert_eq!(workspace_revision(&db).await?, 3);
    assert_eq!(file_count(&db).await?, 2);

    objects.fail_next_delete();
    let deleted = service
        .delete(
            &file_context("file-delete-object-failure", 3),
            uploaded.file.id.as_str(),
            false,
        )
        .await?;
    assert_eq!(deleted.committed_revision, 4);
    assert_eq!(compensation_count(&db, "delete_ready", "pending").await?, 1);

    service
        .delete(
            &file_context("file-delete-copy", 4),
            copied.file.id.as_str(),
            false,
        )
        .await?;
    assert_eq!(workspace_revision(&db).await?, 5);
    assert_eq!(file_count(&db).await?, 0);
    assert_eq!(receipt_count(&db).await?, 4);
    assert_eq!(outbox_count(&db).await?, 4);
    cleanup(&db).await?;
    Ok(())
}

#[tokio::test]
#[ignore = "requires BCS_TEST_POSTGRES_URL and permission to create fault-injection triggers"]
async fn postgres_file_faults_leave_recoverable_object_and_database_authority()
-> Result<(), Box<dyn Error>> {
    let db = postgres_db().await?;
    cleanup(&db).await?;
    seed_project_membership(&db).await?;
    create_workspace(&db).await?;
    let objects = Arc::new(TestObjectStore::default());
    let service = PublicWorkspaceFileService::new(&db, DbSqlFlavor::Postgres, objects.clone());
    let checksum = checksum(PAYLOAD);

    objects.fail_next_stage();
    let stage_error = require_error(
        upload(&service, "file-stage-fail", 1, "stage-fail.txt", &checksum).await,
        "injected object stage failure must fail",
    );
    assert_eq!(
        stage_error.kind(),
        PublicWorkspaceFileErrorKind::Unavailable
    );
    assert_eq!(workspace_revision(&db).await?, 1);
    assert_eq!(file_count(&db).await?, 0);
    assert_eq!(operation_count(&db).await?, 0);

    install_reserve_fault(&db).await?;
    objects.fail_next_abort();
    let reserve_error = require_error(
        upload(
            &service,
            "file-reserve-fail",
            1,
            "reserve-fail.txt",
            &checksum,
        )
        .await,
        "injected upload reservation failure must fail",
    );
    drop_reserve_fault(&db).await?;
    assert_eq!(
        reserve_error.kind(),
        PublicWorkspaceFileErrorKind::Unavailable
    );
    assert_eq!(objects.abort_count.load(Ordering::Relaxed), 1);
    assert_eq!(operation_count(&db).await?, 0);
    assert_eq!(file_count(&db).await?, 0);
    assert_eq!(compensation_count(&db, "abort_stage", "pending").await?, 1);

    objects.fail_next_finalize();
    let finalize_error = require_error(
        upload(
            &service,
            "file-finalize-retry",
            1,
            "finalize-retry.txt",
            &checksum,
        )
        .await,
        "injected object finalize failure must fail",
    );
    assert_eq!(
        finalize_error.kind(),
        PublicWorkspaceFileErrorKind::Unavailable
    );
    assert_eq!(operation_state(&db, "file-finalize-retry").await?, "staged");
    assert_eq!(workspace_revision(&db).await?, 1);
    assert_eq!(
        compensation_count(&db, "persist_finalize", "pending").await?,
        1
    );

    let recovered = upload(
        &service,
        "file-finalize-retry",
        1,
        "finalize-retry.txt",
        &checksum,
    )
    .await?;
    assert_eq!(recovered.committed_revision, 2);
    assert_eq!(
        operation_state(&db, "file-finalize-retry").await?,
        "completed"
    );

    install_activate_fault(&db).await?;
    let activate_error = require_error(
        upload(
            &service,
            "file-activate-fail",
            2,
            "activate-fail.txt",
            &checksum,
        )
        .await,
        "injected finalized-handle persistence failure must fail",
    );
    drop_activate_fault(&db).await?;
    assert_eq!(
        activate_error.kind(),
        PublicWorkspaceFileErrorKind::Unavailable
    );
    assert_eq!(workspace_revision(&db).await?, 2);
    assert_eq!(operation_state(&db, "file-activate-fail").await?, "staged");
    assert_eq!(
        compensation_count(&db, "activate_metadata", "pending").await?,
        1
    );

    let activated = upload(
        &service,
        "file-activate-fail",
        2,
        "activate-fail.txt",
        &checksum,
    )
    .await?;
    assert_eq!(activated.committed_revision, 3);

    install_copy_fault(&db).await?;
    let delete_count_before = objects.delete_count.load(Ordering::Relaxed);
    let copy_error = require_error(
        service
            .copy(
                &file_context("file-copy-db-fail", 3),
                recovered.file.id.as_str(),
                "/",
                Some("copy-db-fail.txt"),
            )
            .await,
        "injected copied metadata transaction failure must fail",
    );
    drop_copy_fault(&db).await?;
    assert_eq!(copy_error.kind(), PublicWorkspaceFileErrorKind::Unavailable);
    assert_eq!(workspace_revision(&db).await?, 3);
    assert_eq!(
        objects.delete_count.load(Ordering::Relaxed),
        delete_count_before + 1
    );
    assert_eq!(
        file_name_count(&db, "copy-db-fail.txt").await?,
        0,
        "failed copied metadata must roll back"
    );
    assert_eq!(receipt_count(&db).await?, 2);
    assert_eq!(outbox_count(&db).await?, 2);
    cleanup(&db).await?;
    Ok(())
}

async fn upload(
    service: &PublicWorkspaceFileService<'_>,
    idempotency_key: &str,
    expected_revision: u64,
    filename: &str,
    checksum: &str,
) -> Result<
    memstack_workspace_service::PublicWorkspaceFileOutcome,
    memstack_workspace_service::PublicWorkspaceFileError,
> {
    service
        .upload(
            &file_context(idempotency_key, expected_revision),
            "/",
            filename,
            "text/plain",
            u64::try_from(PAYLOAD.len()).unwrap_or(u64::MAX),
            checksum,
            byte_stream_from_bytes(Bytes::from_static(PAYLOAD)),
        )
        .await
}

fn require_error<T, E>(result: Result<T, E>, message: &str) -> E {
    match result {
        Ok(_) => panic!("{message}"),
        Err(error) => error,
    }
}

fn file_context(idempotency_key: &str, expected_revision: u64) -> PublicWorkspaceFileContext {
    PublicWorkspaceFileContext {
        tenant_id: TENANT_ID.to_string(),
        project_id: PROJECT_ID.to_string(),
        workspace_id: WORKSPACE_ID.to_string(),
        user_id: USER_ID.to_string(),
        user_name: "PostgreSQL File Contract".to_string(),
        uploader_type: "user".to_string(),
        uploader_id: USER_ID.to_string(),
        uploader_actor_id: USER_ID.to_string(),
        expected_revision: Some(expected_revision),
        idempotency_key: Some(idempotency_key.to_string()),
    }
}

fn checksum(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

#[derive(Default)]
struct TestObjectStore {
    state: Mutex<TestObjectState>,
    fail_stage: AtomicBool,
    fail_finalize: AtomicBool,
    fail_abort: AtomicBool,
    fail_delete: AtomicBool,
    stage_count: AtomicUsize,
    finalize_count: AtomicUsize,
    abort_count: AtomicUsize,
    copy_count: AtomicUsize,
    delete_count: AtomicUsize,
}

#[derive(Default)]
struct TestObjectState {
    staged: BTreeMap<String, Vec<u8>>,
    ready: BTreeMap<String, Vec<u8>>,
}

impl TestObjectStore {
    fn fail_next_stage(&self) {
        self.fail_stage.store(true, Ordering::Relaxed);
    }

    fn fail_next_finalize(&self) {
        self.fail_finalize.store(true, Ordering::Relaxed);
    }

    fn fail_next_abort(&self) {
        self.fail_abort.store(true, Ordering::Relaxed);
    }

    fn fail_next_delete(&self) {
        self.fail_delete.store(true, Ordering::Relaxed);
    }

    fn state(&self) -> Result<std::sync::MutexGuard<'_, TestObjectState>, ObjectStoreError> {
        self.state
            .lock()
            .map_err(|_| ObjectStoreError::Unavailable("test object state poisoned".to_string()))
    }
}

#[async_trait]
impl ObjectStorePort for TestObjectStore {
    fn backend_name(&self) -> &str {
        "postgres-contract"
    }

    fn max_object_size(&self) -> u64 {
        100 * 1024 * 1024
    }

    async fn stage(
        &self,
        request: &ObjectStageRequest,
        mut body: ByteStream,
    ) -> Result<StagedObjectReference, ObjectStoreError> {
        self.stage_count.fetch_add(1, Ordering::Relaxed);
        if self.fail_stage.swap(false, Ordering::Relaxed) {
            return Err(ObjectStoreError::Unavailable(
                "injected stage failure".to_string(),
            ));
        }
        let mut bytes = Vec::new();
        while let Some(chunk) = body.next().await {
            bytes.extend_from_slice(
                &chunk.map_err(|error| ObjectStoreError::Unavailable(error.to_string()))?,
            );
        }
        if u64::try_from(bytes.len()).ok() != Some(request.size_bytes) {
            return Err(ObjectStoreError::Conflict(
                "staged size differs from request".to_string(),
            ));
        }
        self.state()?.staged.insert(request.key.clone(), bytes);
        Ok(StagedObjectReference {
            backend: self.backend_name().to_string(),
            key: request.key.clone(),
            handle: json!({"key": request.key}),
            size_bytes: request.size_bytes,
            checksum_sha256: request.checksum_sha256.clone(),
        })
    }

    async fn finalize(
        &self,
        staged: &StagedObjectReference,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        self.finalize_count.fetch_add(1, Ordering::Relaxed);
        if self.fail_finalize.swap(false, Ordering::Relaxed) {
            return Err(ObjectStoreError::Unavailable(
                "injected finalize failure".to_string(),
            ));
        }
        let mut state = self.state()?;
        if let Some(bytes) = state.staged.remove(staged.key.as_str()) {
            state.ready.insert(staged.key.clone(), bytes);
        } else if !state.ready.contains_key(staged.key.as_str()) {
            return Err(ObjectStoreError::NotFound);
        }
        Ok(ReadyObjectReference {
            backend: self.backend_name().to_string(),
            key: staged.key.clone(),
            handle: json!({"key": staged.key}),
            size_bytes: staged.size_bytes,
            checksum_sha256: Some(staged.checksum_sha256.clone()),
        })
    }

    async fn abort(&self, staged: &StagedObjectReference) -> Result<(), ObjectStoreError> {
        self.abort_count.fetch_add(1, Ordering::Relaxed);
        if self.fail_abort.swap(false, Ordering::Relaxed) {
            return Err(ObjectStoreError::Unavailable(
                "injected abort failure".to_string(),
            ));
        }
        self.state()?.staged.remove(staged.key.as_str());
        Ok(())
    }

    async fn open(&self, object: &ReadyObjectReference) -> Result<ByteStream, ObjectStoreError> {
        let bytes = self
            .state()?
            .ready
            .get(object.key.as_str())
            .cloned()
            .ok_or(ObjectStoreError::NotFound)?;
        Ok(byte_stream_from_bytes(Bytes::from(bytes)))
    }

    async fn delete(&self, object: &ReadyObjectReference) -> Result<(), ObjectStoreError> {
        self.delete_count.fetch_add(1, Ordering::Relaxed);
        if self.fail_delete.swap(false, Ordering::Relaxed) {
            return Err(ObjectStoreError::Unavailable(
                "injected delete failure".to_string(),
            ));
        }
        self.state()?.ready.remove(object.key.as_str());
        Ok(())
    }

    async fn copy(
        &self,
        source: &ReadyObjectReference,
        request: &ObjectStageRequest,
    ) -> Result<ReadyObjectReference, ObjectStoreError> {
        self.copy_count.fetch_add(1, Ordering::Relaxed);
        let mut state = self.state()?;
        let bytes = state
            .ready
            .get(source.key.as_str())
            .cloned()
            .ok_or(ObjectStoreError::NotFound)?;
        state.ready.insert(request.key.clone(), bytes);
        Ok(ReadyObjectReference {
            backend: self.backend_name().to_string(),
            key: request.key.clone(),
            handle: json!({"key": request.key}),
            size_bytes: request.size_bytes,
            checksum_sha256: Some(request.checksum_sha256.clone()),
        })
    }
}

async fn postgres_db() -> Result<PostgresDbPlugin, Box<dyn Error>> {
    let database_url = std::env::var("BCS_TEST_POSTGRES_URL")?;
    Ok(PostgresDbPlugin::connect_no_tls(&database_url, 1).await?)
}

async fn seed_project_membership(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "INSERT INTO project_principal_memberships (tenant_id, project_id, user_id, participant_actor_id, source_membership_id, role, is_active, identity_authority, source_created_at, source_updated_at) VALUES ('tenant-file-pg-contract', 'project-file-pg-contract', 'actor-file-pg-contract', 'actor-file-pg-contract', 'membership-file-pg-contract', 'member', TRUE, 'memstack', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) ON CONFLICT (tenant_id, project_id, user_id) DO UPDATE SET participant_actor_id = excluded.participant_actor_id, is_active = TRUE, source_updated_at = CURRENT_TIMESTAMP",
    ))
    .await?;
    Ok(())
}

async fn create_workspace(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    WorkspaceCreationService::new(db, DbSqlFlavor::Postgres)
        .create(&CreateWorkspaceInput {
            scope: CreateWorkspaceScopeInput {
                tenant_id: TENANT_ID.to_string(),
                project_id: PROJECT_ID.to_string(),
                workspace_id: WORKSPACE_ID.to_string(),
                group_id: GROUP_ID.to_string(),
            },
            owner: CreateWorkspaceOwnerInput {
                member_id: "member-file-pg-contract".to_string(),
                user_id: USER_ID.to_string(),
                is_superuser: false,
            },
            content: CreateWorkspaceContentInput {
                name: "PostgreSQL File Workspace".to_string(),
                description: Some("File authority contract".to_string()),
                metadata: json!({"workspace_type": "general"}),
            },
            idempotency_key: "file-pg-workspace-create".to_string(),
        })
        .await?;
    Ok(())
}

async fn cleanup(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    drop_reserve_fault(db).await?;
    drop_activate_fault(db).await?;
    drop_copy_fault(db).await?;
    for statement in [
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_group_participants WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM workspace_profiles WHERE workspace_id = ")
            .bind(WORKSPACE_ID)
            .build(),
        DbStatementBuilder::new(DbSqlFlavor::Postgres)
            .push_static("DELETE FROM bcs_groups WHERE group_id = ")
            .bind(GROUP_ID)
            .build(),
        DbStatement::new(
            "DELETE FROM project_principal_memberships WHERE source_membership_id = 'membership-file-pg-contract'",
        ),
    ] {
        db.execute(statement).await?;
    }
    Ok(())
}

async fn install_reserve_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_file_reserve_contract() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-file-pg-contract' AND NEW.idempotency_key = 'file-reserve-fail' THEN RAISE EXCEPTION 'injected File reservation failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_file_reserve_contract BEFORE INSERT ON workspace_file_operations FOR EACH ROW EXECUTE FUNCTION avernet.reject_file_reserve_contract()",
    ))
    .await?;
    Ok(())
}

async fn drop_reserve_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_file_reserve_contract ON workspace_file_operations",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_file_reserve_contract()",
    ))
    .await?;
    Ok(())
}

async fn install_activate_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_file_activate_contract() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-file-pg-contract' AND NEW.idempotency_key = 'file-activate-fail' AND NEW.state = 'finalized' THEN RAISE EXCEPTION 'injected File activation failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_file_activate_contract BEFORE UPDATE ON workspace_file_operations FOR EACH ROW EXECUTE FUNCTION avernet.reject_file_activate_contract()",
    ))
    .await?;
    Ok(())
}

async fn drop_activate_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_file_activate_contract ON workspace_file_operations",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_file_activate_contract()",
    ))
    .await?;
    Ok(())
}

async fn install_copy_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "CREATE FUNCTION avernet.reject_file_copy_contract() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.workspace_id = 'workspace-file-pg-contract' AND NEW.name = 'copy-db-fail.txt' THEN RAISE EXCEPTION 'injected File copy metadata failure'; END IF; RETURN NEW; END $$",
    ))
    .await?;
    db.execute(DbStatement::new(
        "CREATE TRIGGER trg_reject_file_copy_contract BEFORE INSERT ON workspace_files FOR EACH ROW EXECUTE FUNCTION avernet.reject_file_copy_contract()",
    ))
    .await?;
    Ok(())
}

async fn drop_copy_fault(db: &dyn DbPlugin) -> Result<(), Box<dyn Error>> {
    db.execute(DbStatement::new(
        "DROP TRIGGER IF EXISTS trg_reject_file_copy_contract ON workspace_files",
    ))
    .await?;
    db.execute(DbStatement::new(
        "DROP FUNCTION IF EXISTS avernet.reject_file_copy_contract()",
    ))
    .await?;
    Ok(())
}

async fn workspace_revision(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT revision AS value FROM workspace_authorities WHERE workspace_id = $1",
        WORKSPACE_ID,
    )
    .await
}

async fn file_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_files WHERE workspace_id = $1",
        WORKSPACE_ID,
    )
    .await
}

async fn file_name_count(db: &dyn DbPlugin, name: &str) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT COUNT(*) AS value FROM workspace_files WHERE workspace_id = $1 AND name = $2",
            vec![WORKSPACE_ID.into(), name.into()],
        ))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn operation_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_file_operations WHERE workspace_id = $1",
        WORKSPACE_ID,
    )
    .await
}

async fn receipt_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_mutation_receipts WHERE workspace_id = $1 AND surface = 'blackboard_file'",
        WORKSPACE_ID,
    )
    .await
}

async fn outbox_count(db: &dyn DbPlugin) -> Result<i64, Box<dyn Error>> {
    query_i64(
        db,
        "SELECT COUNT(*) AS value FROM workspace_outbox WHERE workspace_id = $1 AND aggregate_type = 'blackboard_file'",
        WORKSPACE_ID,
    )
    .await
}

async fn compensation_count(
    db: &dyn DbPlugin,
    kind: &str,
    status: &str,
) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            "SELECT COUNT(*) AS value FROM workspace_file_compensations WHERE workspace_id = $1 AND compensation_kind = $2 AND status = $3",
            vec![WORKSPACE_ID.into(), kind.into(), status.into()],
        ))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn operation_state(
    db: &dyn DbPlugin,
    idempotency_key: &str,
) -> Result<String, Box<dyn Error>> {
    query_string(
        db,
        "SELECT state AS value FROM workspace_file_operations WHERE workspace_id = $1 AND idempotency_key = $2",
        idempotency_key,
    )
    .await
}

async fn file_state(db: &dyn DbPlugin, file_id: &str) -> Result<String, Box<dyn Error>> {
    query_string(
        db,
        "SELECT object_state AS value FROM workspace_files WHERE workspace_id = $1 AND file_id = $2",
        file_id,
    )
    .await
}

async fn query_i64(
    db: &dyn DbPlugin,
    sql: &str,
    workspace_id: &str,
) -> Result<i64, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(sql, vec![workspace_id.into()]))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_i64("value")?
        .ok_or("missing value")?)
}

async fn query_string(
    db: &dyn DbPlugin,
    sql: &str,
    second: &str,
) -> Result<String, Box<dyn Error>> {
    let rows = db
        .query(DbStatement::with_params(
            sql,
            vec![WORKSPACE_ID.into(), second.into()],
        ))
        .await?;
    Ok(rows
        .first()
        .ok_or("missing row")?
        .get_string("value")?
        .ok_or("missing value")?)
}
