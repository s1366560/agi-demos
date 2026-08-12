//! Legacy-compatible blackboard File authority over external object storage.

use std::sync::Arc;

use async_trait::async_trait;
use bcs_db_api::{DbPlugin, DbSqlFlavor};
use bcs_storage_api::ByteStream;
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use memstack_workspace_store::{
    WorkspaceFileDomainWrite, WorkspaceFileMutation, WorkspaceFileMutationOutcome,
    WorkspaceFileOperationRecord, WorkspaceFileRecord, WorkspaceFileScope, WorkspaceFileStore,
    WorkspaceFileStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

const MAX_FILE_SIZE: u64 = 100 * 1024 * 1024;
const MAX_COPY_ENTRIES: usize = 500;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;
const FILE_NAMESPACE: Uuid = Uuid::from_u128(0x173a_9bd8_68f0_49d7_8481_92dc_a99a_3268);
const BLOCKED_SEGMENTS: &[&str] = &[
    "credentials",
    "node_modules",
    ".env",
    "__pycache__",
    ".git",
    ".svn",
    ".hg",
];

/// Authenticated Workspace scope and mutation preconditions.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceFileContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub user_name: String,
    pub uploader_type: String,
    pub uploader_id: String,
    pub uploader_actor_id: String,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Legacy response projection. Object handles never cross the public API.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PublicWorkspaceFile {
    pub id: String,
    pub workspace_id: String,
    pub parent_path: String,
    pub name: String,
    pub is_directory: bool,
    pub file_size: u64,
    pub content_type: String,
    pub uploader_type: String,
    pub uploader_id: String,
    pub uploader_name: String,
    pub created_at: String,
}

/// Mutation metadata retained for collaboration-command composition.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceFileOutcome {
    pub file: PublicWorkspaceFile,
    pub receipt_id: String,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Delete response plus its atomic receipt/revision/outbox authority.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceFileDeleteOutcome {
    pub response: Value,
    pub receipt_id: String,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// External object staging request. Bytes are supplied as a stream, never DB values.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectStageRequest {
    pub key: String,
    pub file_name: String,
    pub content_type: String,
    pub size_bytes: u64,
    pub checksum_sha256: String,
}

/// Opaque durable staging reference.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StagedObjectReference {
    pub backend: String,
    pub key: String,
    pub handle: Value,
    pub size_bytes: u64,
    pub checksum_sha256: String,
}

/// Opaque ready-object or Desktop vault reference.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReadyObjectReference {
    pub backend: String,
    pub key: String,
    pub handle: Value,
    pub size_bytes: u64,
    pub checksum_sha256: Option<String>,
}

/// Object-store failures remain separate from database/authority failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum ObjectStoreError {
    #[error("invalid object-store request: {0}")]
    Invalid(String),
    #[error("object not found")]
    NotFound,
    #[error("object-store conflict: {0}")]
    Conflict(String),
    #[error("object store unavailable: {0}")]
    Unavailable(String),
}

/// Narrow Workspace object authority used by Cloud storage and Desktop vault adapters.
#[async_trait]
pub trait ObjectStorePort: Send + Sync + 'static {
    fn backend_name(&self) -> &str;
    fn max_object_size(&self) -> u64;

    async fn stage(
        &self,
        request: &ObjectStageRequest,
        body: ByteStream,
    ) -> Result<StagedObjectReference, ObjectStoreError>;
    async fn finalize(
        &self,
        staged: &StagedObjectReference,
    ) -> Result<ReadyObjectReference, ObjectStoreError>;
    async fn abort(&self, staged: &StagedObjectReference) -> Result<(), ObjectStoreError>;
    async fn open(&self, object: &ReadyObjectReference) -> Result<ByteStream, ObjectStoreError>;
    async fn delete(&self, object: &ReadyObjectReference) -> Result<(), ObjectStoreError>;
    async fn copy(
        &self,
        source: &ReadyObjectReference,
        request: &ObjectStageRequest,
    ) -> Result<ReadyObjectReference, ObjectStoreError>;
}

pub struct PublicWorkspaceFileDownload {
    pub file: PublicWorkspaceFile,
    pub checksum_sha256: Option<String>,
    pub body: ByteStream,
}

/// Stable File failure categories consumed by HTTP adapters.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceFileErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Stable File application errors.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceFileError {
    #[error("invalid Workspace File request: {0}")]
    InvalidRequest(String),
    #[error("Workspace File not found")]
    FileNotFound,
    #[error("Workspace File access denied")]
    Forbidden,
    #[error("Workspace File authority conflict")]
    Conflict,
    #[error(transparent)]
    ObjectStore(#[from] ObjectStoreError),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Store(#[from] WorkspaceFileStoreError),
}

impl PublicWorkspaceFileError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceFileErrorKind {
        match self {
            Self::InvalidRequest(_) => PublicWorkspaceFileErrorKind::InvalidRequest,
            Self::FileNotFound | Self::ObjectStore(ObjectStoreError::NotFound) => {
                PublicWorkspaceFileErrorKind::NotFound
            }
            Self::Forbidden => PublicWorkspaceFileErrorKind::Forbidden,
            Self::Conflict | Self::ObjectStore(ObjectStoreError::Conflict(_)) => {
                PublicWorkspaceFileErrorKind::Conflict
            }
            Self::ObjectStore(ObjectStoreError::Invalid(_)) => {
                PublicWorkspaceFileErrorKind::InvalidRequest
            }
            Self::ObjectStore(ObjectStoreError::Unavailable(_)) | Self::Json(_) => {
                PublicWorkspaceFileErrorKind::Unavailable
            }
            Self::Store(error) => match error {
                WorkspaceFileStoreError::NotFound | WorkspaceFileStoreError::FileNotFound => {
                    PublicWorkspaceFileErrorKind::NotFound
                }
                WorkspaceFileStoreError::AccessRequired
                | WorkspaceFileStoreError::EditorAccessRequired => {
                    PublicWorkspaceFileErrorKind::Forbidden
                }
                WorkspaceFileStoreError::Conflict
                | WorkspaceFileStoreError::IdempotencyConflict
                | WorkspaceFileStoreError::IncompleteReceipt => {
                    PublicWorkspaceFileErrorKind::Conflict
                }
                _ => PublicWorkspaceFileErrorKind::Unavailable,
            },
        }
    }
}

pub struct PublicWorkspaceFileService<'a> {
    store: WorkspaceFileStore<'a>,
    object_store: Arc<dyn ObjectStorePort>,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceFileService<'a> {
    #[must_use]
    pub fn new(
        db: &'a dyn DbPlugin,
        flavor: DbSqlFlavor,
        object_store: Arc<dyn ObjectStorePort>,
    ) -> Self {
        Self {
            store: WorkspaceFileStore::new(db, flavor),
            object_store,
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the File domain write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    pub async fn list(
        &self,
        context: &PublicWorkspaceFileContext,
        parent_path: &str,
    ) -> Result<Vec<PublicWorkspaceFile>, PublicWorkspaceFileError> {
        let scope = scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), false)
            .await?;
        let parent_path = validate_path(parent_path)?;
        self.store
            .list(&scope, parent_path.as_str())
            .await?
            .iter()
            .map(public_file)
            .collect()
    }

    pub async fn create_directory(
        &self,
        context: &PublicWorkspaceFileContext,
        parent_path: &str,
        name: &str,
    ) -> Result<PublicWorkspaceFileOutcome, PublicWorkspaceFileError> {
        let context = prepared_context(context, "create_directory");
        let scope = scope(&context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true)
            .await?;
        let parent_path = validate_path(parent_path)?;
        let name = validate_filename(name)?;
        self.require_parent(&scope, parent_path.as_str()).await?;
        self.require_name_available(&scope, parent_path.as_str(), name.as_str())
            .await?;
        let now = timestamp();
        let record = WorkspaceFileRecord {
            file_id: deterministic_file_id(&context, "directory", name.as_str()),
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            parent_path,
            name,
            is_directory: true,
            file_size: 0,
            content_type: String::new(),
            storage_backend: "none".to_string(),
            object_handle: String::new(),
            object_state: "ready".to_string(),
            uploader_type: "user".to_string(),
            uploader_id: context.user_id.clone(),
            uploader_actor_id: context.user_id.clone(),
            uploader_name: context.user_name.clone(),
            checksum_sha256: None,
            detected_mime_type: None,
            revision: 1,
            created_at: now.clone(),
            updated_at: now,
        };
        let response = public_file(&record)?;
        let aggregate_id = record.file_id.clone();
        let outcome = self
            .commit(
                &context,
                "create_directory",
                &aggregate_id,
                WorkspaceFileDomainWrite::Insert(record),
                serde_json::to_value(&response)?,
                "blackboard_file_created",
                created_event(&response, None),
            )
            .await?;
        Ok(file_outcome(response, outcome))
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn upload(
        &self,
        context: &PublicWorkspaceFileContext,
        parent_path: &str,
        filename: &str,
        content_type: &str,
        size_bytes: u64,
        checksum_sha256: &str,
        body: ByteStream,
    ) -> Result<PublicWorkspaceFileOutcome, PublicWorkspaceFileError> {
        let context = prepared_context(context, "upload_file");
        let scope = scope(&context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true)
            .await?;
        validate_upload(
            size_bytes,
            checksum_sha256,
            self.object_store.max_object_size(),
        )?;
        let parent_path = validate_path(parent_path)?;
        let filename = validate_filename(filename)?;
        self.require_parent(&scope, parent_path.as_str()).await?;
        let file_id = deterministic_file_id(&context, "file", filename.as_str());
        let domain_hash = upload_request_hash(
            &context,
            parent_path.as_str(),
            filename.as_str(),
            content_type,
            size_bytes,
            checksum_sha256,
        )?;
        let request_hash = self
            .receipt_authority
            .as_ref()
            .map_or(domain_hash, |authority| {
                authority.request_hash().as_str().to_string()
            });
        let placeholder = placeholder_upload_record(
            &context,
            &file_id,
            &parent_path,
            &filename,
            content_type,
            size_bytes,
            checksum_sha256,
        );
        let mutation = file_mutation(
            &context,
            "upload_file",
            &file_id,
            request_hash.clone(),
            WorkspaceFileDomainWrite::Update(placeholder.clone()),
            serde_json::to_value(public_file(&placeholder)?)?,
            "blackboard_file_created",
            created_event(&public_file(&placeholder)?, None),
            self.receipt_authority.clone(),
        );
        if let Some(replay) = self.store.replay(&mutation).await? {
            let file = serde_json::from_value(replay.response.clone())?;
            return Ok(file_outcome(file, replay));
        }
        self.require_name_available(&scope, parent_path.as_str(), filename.as_str())
            .await?;

        if let Some(operation) = self
            .store
            .operation(
                &scope,
                context.user_id.as_str(),
                required_idempotency(&context)?,
            )
            .await?
        {
            if operation.request_hash != request_hash {
                return Err(PublicWorkspaceFileError::Conflict);
            }
            return self.resume_upload(&context, operation).await;
        }

        let request = ObjectStageRequest {
            key: object_key(&context, &file_id, filename.as_str()),
            file_name: filename.clone(),
            content_type: normalized_content_type(content_type),
            size_bytes,
            checksum_sha256: checksum_sha256.to_string(),
        };
        let staged = self.object_store.stage(&request, body).await?;
        let operation_id = deterministic_operation_id(&context, &file_id);
        let now = timestamp();
        let staged_record = WorkspaceFileRecord {
            file_id: file_id.clone(),
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            parent_path,
            name: filename,
            is_directory: false,
            file_size: size_bytes,
            content_type: request.content_type,
            storage_backend: staged.backend.clone(),
            object_handle: serde_json::to_string(&staged)?,
            object_state: "staging".to_string(),
            uploader_type: context.uploader_type.clone(),
            uploader_id: context.uploader_id.clone(),
            uploader_actor_id: context.uploader_actor_id.clone(),
            uploader_name: context.user_name.clone(),
            checksum_sha256: Some(checksum_sha256.to_string()),
            detected_mime_type: None,
            revision: 1,
            created_at: now.clone(),
            updated_at: now,
        };
        let requested_operation = WorkspaceFileOperationRecord {
            operation_id: operation_id.clone(),
            file_id: file_id.clone(),
            actor_id: context.user_id.clone(),
            idempotency_key: required_idempotency(&context)?.to_string(),
            request_hash,
            state: "staged".to_string(),
            staged_handle: Some(serde_json::to_value(&staged)?),
            ready_handle: None,
            checksum_sha256: Some(checksum_sha256.to_string()),
            size_bytes: Some(size_bytes),
        };
        let operation = match self
            .store
            .reserve_upload(&requested_operation, &scope, &staged_record)
            .await
        {
            Ok(operation) => operation,
            Err(error) => {
                self.compensate_abort(&scope, &operation_id, &file_id, &staged, &error.to_string())
                    .await;
                return Err(error.into());
            }
        };
        if operation.operation_id != operation_id {
            self.compensate_abort(
                &scope,
                &operation_id,
                &file_id,
                &staged,
                "concurrent idempotent upload won",
            )
            .await;
        }
        self.resume_upload(&context, operation).await
    }

    pub async fn download(
        &self,
        context: &PublicWorkspaceFileContext,
        file_id: &str,
    ) -> Result<PublicWorkspaceFileDownload, PublicWorkspaceFileError> {
        let scope = scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), false)
            .await?;
        let record = self
            .store
            .get(&scope, file_id, false)
            .await?
            .ok_or(PublicWorkspaceFileError::FileNotFound)?;
        if record.is_directory {
            return Err(PublicWorkspaceFileError::InvalidRequest(
                "Cannot read directory content".to_string(),
            ));
        }
        let reference: ReadyObjectReference = serde_json::from_str(record.object_handle.as_str())?;
        let body = self.object_store.open(&reference).await?;
        Ok(PublicWorkspaceFileDownload {
            file: public_file(&record)?,
            checksum_sha256: record.checksum_sha256,
            body,
        })
    }

    pub async fn patch(
        &self,
        context: &PublicWorkspaceFileContext,
        file_id: &str,
        name: Option<&str>,
        parent_path: Option<&str>,
    ) -> Result<PublicWorkspaceFileOutcome, PublicWorkspaceFileError> {
        if name.is_none() && parent_path.is_none() {
            return Err(PublicWorkspaceFileError::InvalidRequest(
                "Provide at least one of 'name' or 'parent_path'".to_string(),
            ));
        }
        let context = prepared_context(context, "update_file");
        let scope = scope(&context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true)
            .await?;
        let mut record = self
            .store
            .get(&scope, file_id, false)
            .await?
            .ok_or(PublicWorkspaceFileError::FileNotFound)?;
        let old_descendant_path = record
            .is_directory
            .then(|| join_child(&record.parent_path, &record.name));
        if let Some(parent_path) = parent_path {
            let target = validate_path(parent_path)?;
            self.require_parent(&scope, target.as_str()).await?;
            if let Some(prefix) = &old_descendant_path
                && (target == *prefix || target.starts_with(prefix))
            {
                return Err(PublicWorkspaceFileError::InvalidRequest(
                    "Cannot move a directory into itself".to_string(),
                ));
            }
            record.parent_path = target;
        }
        if let Some(name) = name {
            record.name = validate_filename(name)?;
        }
        self.require_name_available_except(&scope, &record.parent_path, &record.name, file_id)
            .await?;
        let new_descendant_path = record
            .is_directory
            .then(|| join_child(&record.parent_path, &record.name));
        let response = public_file(&record)?;
        let outcome = self
            .commit(
                &context,
                "update_file",
                file_id,
                WorkspaceFileDomainWrite::RenameMove {
                    record,
                    old_descendant_path,
                    new_descendant_path,
                },
                serde_json::to_value(&response)?,
                "blackboard_file_updated",
                json!({"file": &response, "file_id": file_id}),
            )
            .await?;
        Ok(file_outcome(response, outcome))
    }

    pub async fn copy(
        &self,
        context: &PublicWorkspaceFileContext,
        file_id: &str,
        target_parent_path: &str,
        name: Option<&str>,
    ) -> Result<PublicWorkspaceFileOutcome, PublicWorkspaceFileError> {
        let context = prepared_context(context, "copy_file");
        let scope = scope(&context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true)
            .await?;
        let source = self
            .store
            .get(&scope, file_id, false)
            .await?
            .ok_or(PublicWorkspaceFileError::FileNotFound)?;
        let target_parent = validate_path(target_parent_path)?;
        self.require_parent(&scope, target_parent.as_str()).await?;
        let copy_name = validate_filename(name.unwrap_or(source.name.as_str()))?;
        self.require_name_available(&scope, target_parent.as_str(), copy_name.as_str())
            .await?;
        let descendants = if source.is_directory {
            self.store
                .descendants(
                    &scope,
                    join_child(&source.parent_path, &source.name).as_str(),
                )
                .await?
        } else {
            Vec::new()
        };
        if descendants.len().saturating_add(1) > MAX_COPY_ENTRIES {
            return Err(PublicWorkspaceFileError::InvalidRequest(
                "Directory copy exceeds maximum entry count".to_string(),
            ));
        }
        let mut records = Vec::with_capacity(descendants.len().saturating_add(1));
        let mut created_objects: Vec<(String, ReadyObjectReference)> = Vec::new();
        let root = self
            .copy_record(
                &context,
                &source,
                &target_parent,
                &copy_name,
                &mut created_objects,
            )
            .await?;
        let source_prefix = join_child(&source.parent_path, &source.name);
        let target_prefix = join_child(&target_parent, &copy_name);
        records.push(root.clone());
        for descendant in descendants {
            let mapped_parent =
                descendant
                    .parent_path
                    .replacen(source_prefix.as_str(), target_prefix.as_str(), 1);
            let copied = self
                .copy_record(
                    &context,
                    &descendant,
                    &mapped_parent,
                    &descendant.name,
                    &mut created_objects,
                )
                .await?;
            records.push(copied);
        }
        let response = public_file(&root)?;
        let result = self
            .commit(
                &context,
                "copy_file",
                &root.file_id,
                WorkspaceFileDomainWrite::InsertMany(records),
                serde_json::to_value(&response)?,
                "blackboard_file_created",
                created_event(&response, Some(file_id)),
            )
            .await;
        if let Err(error) = result {
            self.compensate_ready_objects(&scope, &created_objects, error.to_string().as_str())
                .await;
            return Err(error);
        }
        let outcome = result?;
        Ok(file_outcome(response, outcome))
    }

    pub async fn delete(
        &self,
        context: &PublicWorkspaceFileContext,
        file_id: &str,
        recursive: bool,
    ) -> Result<PublicWorkspaceFileDeleteOutcome, PublicWorkspaceFileError> {
        let context = prepared_context(context, "delete_file");
        let scope = scope(&context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true)
            .await?;
        let record = self
            .store
            .get(&scope, file_id, false)
            .await?
            .ok_or(PublicWorkspaceFileError::FileNotFound)?;
        let descendant_path = record
            .is_directory
            .then(|| join_child(&record.parent_path, &record.name));
        let descendants = if let Some(prefix) = &descendant_path {
            self.store.descendants(&scope, prefix).await?
        } else {
            Vec::new()
        };
        if !recursive && !descendants.is_empty() {
            return Err(PublicWorkspaceFileError::InvalidRequest(
                "Directory is not empty".to_string(),
            ));
        }
        let response = json!({"deleted": true});
        let event_type = if record.is_directory {
            "blackboard_directory_deleted"
        } else {
            "blackboard_file_deleted"
        };
        let outcome = self.commit(&context, "delete_file", file_id, WorkspaceFileDomainWrite::Delete { file_id: file_id.to_string(), descendant_path: recursive.then_some(descendant_path).flatten() }, response.clone(), event_type, json!({"workspace_id": context.workspace_id, "file_id": file_id, "deleted": true, "recursive": recursive, "is_directory": record.is_directory})).await?;
        let mut objects = descendants;
        objects.push(record);
        for object in objects
            .into_iter()
            .filter(|item| !item.is_directory && !item.object_handle.is_empty())
        {
            let reference: ReadyObjectReference = serde_json::from_str(&object.object_handle)?;
            if let Err(error) = self.object_store.delete(&reference).await {
                let operation_id = format!("delete-file:{}", object.file_id);
                let _ = self
                    .store
                    .record_compensation(
                        &scope,
                        &operation_id,
                        &object.file_id,
                        "delete_ready",
                        &serde_json::to_value(&reference)?,
                        error.to_string().as_str(),
                    )
                    .await;
            }
        }
        Ok(PublicWorkspaceFileDeleteOutcome {
            response,
            receipt_id: outcome.receipt_id,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    async fn resume_upload(
        &self,
        context: &PublicWorkspaceFileContext,
        operation: WorkspaceFileOperationRecord,
    ) -> Result<PublicWorkspaceFileOutcome, PublicWorkspaceFileError> {
        let scope = scope(context);
        let mut record = self
            .store
            .get(&scope, operation.file_id.as_str(), true)
            .await?
            .ok_or(PublicWorkspaceFileError::FileNotFound)?;
        let ready = if operation.state == "finalized" || operation.state == "completed" {
            serde_json::from_value(
                operation
                    .ready_handle
                    .ok_or(PublicWorkspaceFileError::Conflict)?,
            )?
        } else {
            let staged: StagedObjectReference = serde_json::from_value(
                operation
                    .staged_handle
                    .clone()
                    .ok_or(PublicWorkspaceFileError::Conflict)?,
            )?;
            let ready = match self.object_store.finalize(&staged).await {
                Ok(ready) => ready,
                Err(error) => {
                    let _ = self
                        .store
                        .record_compensation(
                            &scope,
                            &operation.operation_id,
                            &operation.file_id,
                            "persist_finalize",
                            &serde_json::to_value(&staged)?,
                            error.to_string().as_str(),
                        )
                        .await;
                    return Err(error.into());
                }
            };
            if let Err(error) = self
                .store
                .mark_finalized(
                    &scope,
                    &operation.operation_id,
                    &serde_json::to_value(&ready)?,
                )
                .await
            {
                let _ = self
                    .store
                    .record_compensation(
                        &scope,
                        &operation.operation_id,
                        &operation.file_id,
                        "activate_metadata",
                        &serde_json::to_value(&ready)?,
                        error.to_string().as_str(),
                    )
                    .await;
                return Err(error.into());
            }
            ready
        };
        if ready.size_bytes != record.file_size {
            return Err(PublicWorkspaceFileError::Conflict);
        }
        if ready
            .checksum_sha256
            .as_deref()
            .is_some_and(|value| Some(value) != record.checksum_sha256.as_deref())
        {
            return Err(PublicWorkspaceFileError::Conflict);
        }
        record.storage_backend.clone_from(&ready.backend);
        record.object_handle = serde_json::to_string(&ready)?;
        record.object_state = "ready".to_string();
        let response = public_file(&record)?;
        let aggregate_id = record.file_id.clone();
        let expected_revision = context
            .expected_revision
            .unwrap_or(self.store.revision(&scope).await?);
        let mutation = WorkspaceFileMutation {
            scope: scope.clone(),
            actor_id: context.user_id.clone(),
            action: "upload_file".to_string(),
            idempotency_key: required_idempotency(context)?.to_string(),
            request_hash: operation.request_hash.clone(),
            expected_revision,
            aggregate_id,
            domain_write: WorkspaceFileDomainWrite::ActivateUpload {
                record,
                operation_id: operation.operation_id.clone(),
            },
            response: serde_json::to_value(&response)?,
            event_type: "blackboard_file_created".to_string(),
            event_payload: created_event(&response, None),
            receipt_authority: self.receipt_authority.clone(),
        };
        let outcome = self
            .store
            .mutate(&mutation)
            .await
            .map_err(PublicWorkspaceFileError::from);
        if let Err(error) = &outcome {
            let _ = self
                .store
                .record_compensation(
                    &scope,
                    &operation.operation_id,
                    &operation.file_id,
                    "activate_metadata",
                    &serde_json::to_value(&ready)?,
                    error.to_string().as_str(),
                )
                .await;
        }
        outcome.map(|outcome| file_outcome(response, outcome))
    }

    async fn copy_record(
        &self,
        context: &PublicWorkspaceFileContext,
        source: &WorkspaceFileRecord,
        parent_path: &str,
        name: &str,
        created_objects: &mut Vec<(String, ReadyObjectReference)>,
    ) -> Result<WorkspaceFileRecord, PublicWorkspaceFileError> {
        let file_id = deterministic_file_id(
            context,
            "copy",
            format!("{}\0{}\0{}", source.file_id, parent_path, name).as_str(),
        );
        let mut record = source.clone();
        record.file_id.clone_from(&file_id);
        record.parent_path = parent_path.to_string();
        record.name = name.to_string();
        record.uploader_type = "user".to_string();
        record.uploader_id = context.user_id.clone();
        record.uploader_actor_id = context.user_id.clone();
        record.uploader_name = context.user_name.clone();
        record.revision = 1;
        record.created_at = timestamp();
        record.updated_at.clone_from(&record.created_at);
        if !source.is_directory {
            let source_reference: ReadyObjectReference =
                serde_json::from_str(source.object_handle.as_str())?;
            let request = ObjectStageRequest {
                key: object_key(context, &file_id, name),
                file_name: name.to_string(),
                content_type: record.content_type.clone(),
                size_bytes: record.file_size,
                checksum_sha256: record
                    .checksum_sha256
                    .clone()
                    .ok_or(PublicWorkspaceFileError::Conflict)?,
            };
            let ready = self.object_store.copy(&source_reference, &request).await?;
            record.storage_backend.clone_from(&ready.backend);
            record.object_handle = serde_json::to_string(&ready)?;
            record.object_state = "ready".to_string();
            created_objects.push((file_id, ready));
        }
        Ok(record)
    }

    async fn compensate_abort(
        &self,
        scope: &WorkspaceFileScope,
        operation_id: &str,
        file_id: &str,
        staged: &StagedObjectReference,
        reason: &str,
    ) {
        if let Err(error) = self.object_store.abort(staged).await {
            let _ = self
                .store
                .record_compensation(
                    scope,
                    operation_id,
                    file_id,
                    "abort_stage",
                    &serde_json::to_value(staged).unwrap_or(Value::Null),
                    format!("{reason}; abort: {error}").as_str(),
                )
                .await;
        }
    }

    async fn compensate_ready_objects(
        &self,
        scope: &WorkspaceFileScope,
        objects: &[(String, ReadyObjectReference)],
        reason: &str,
    ) {
        for (file_id, object) in objects {
            if let Err(error) = self.object_store.delete(object).await {
                let operation_id = format!("copy-file:{file_id}");
                let _ = self
                    .store
                    .record_compensation(
                        scope,
                        &operation_id,
                        file_id,
                        "delete_ready",
                        &serde_json::to_value(object).unwrap_or(Value::Null),
                        format!("{reason}; delete: {error}").as_str(),
                    )
                    .await;
            }
        }
    }

    async fn require_parent(
        &self,
        scope: &WorkspaceFileScope,
        parent_path: &str,
    ) -> Result<(), PublicWorkspaceFileError> {
        if parent_path == "/" {
            return Ok(());
        }
        let (grandparent, name) = split_directory_path(parent_path)?;
        if self
            .store
            .list(scope, grandparent.as_str())
            .await?
            .iter()
            .any(|item| item.is_directory && item.name == name)
        {
            Ok(())
        } else {
            Err(PublicWorkspaceFileError::FileNotFound)
        }
    }
    async fn require_name_available(
        &self,
        scope: &WorkspaceFileScope,
        parent: &str,
        name: &str,
    ) -> Result<(), PublicWorkspaceFileError> {
        self.require_name_available_except(scope, parent, name, "")
            .await
    }
    async fn require_name_available_except(
        &self,
        scope: &WorkspaceFileScope,
        parent: &str,
        name: &str,
        file_id: &str,
    ) -> Result<(), PublicWorkspaceFileError> {
        if self
            .store
            .list(scope, parent)
            .await?
            .iter()
            .any(|item| item.name == name && item.file_id != file_id)
        {
            Err(PublicWorkspaceFileError::Conflict)
        } else {
            Ok(())
        }
    }

    #[allow(clippy::too_many_arguments)]
    async fn commit(
        &self,
        context: &PublicWorkspaceFileContext,
        action: &str,
        aggregate_id: &str,
        domain_write: WorkspaceFileDomainWrite,
        response: Value,
        event_type: &str,
        event_payload: Value,
    ) -> Result<WorkspaceFileMutationOutcome, PublicWorkspaceFileError> {
        let domain_hash = request_hash(
            json!({"action": action, "scope": {"tenant_id": context.tenant_id, "project_id": context.project_id, "workspace_id": context.workspace_id}, "actor_id": context.user_id, "aggregate_id": aggregate_id, "response": stable_payload(&response), "event_payload": stable_payload(&event_payload)}),
        )?;
        let request_hash = self
            .receipt_authority
            .as_ref()
            .map_or(domain_hash, |authority| {
                authority.request_hash().as_str().to_string()
            });
        let mut prepared = context.clone();
        prepared.expected_revision = Some(
            context
                .expected_revision
                .unwrap_or(self.store.revision(&scope(context)).await?),
        );
        let mutation = file_mutation(
            &prepared,
            action,
            aggregate_id,
            request_hash,
            domain_write,
            response,
            event_type,
            event_payload,
            self.receipt_authority.clone(),
        );
        Ok(self.store.mutate(&mutation).await?)
    }
}

#[allow(clippy::too_many_arguments)]
fn file_mutation(
    context: &PublicWorkspaceFileContext,
    action: &str,
    aggregate_id: &str,
    request_hash: String,
    domain_write: WorkspaceFileDomainWrite,
    response: Value,
    event_type: &str,
    event_payload: Value,
    receipt_authority: Option<WorkspaceMutationAuthority>,
) -> WorkspaceFileMutation {
    WorkspaceFileMutation {
        scope: scope(context),
        actor_id: context.user_id.clone(),
        action: action.to_string(),
        idempotency_key: context.idempotency_key.clone().unwrap_or_default(),
        request_hash,
        expected_revision: context.expected_revision.unwrap_or(0),
        aggregate_id: aggregate_id.to_string(),
        domain_write,
        response,
        event_type: event_type.to_string(),
        event_payload,
        receipt_authority,
    }
}
fn scope(context: &PublicWorkspaceFileContext) -> WorkspaceFileScope {
    WorkspaceFileScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}
fn prepared_context(
    context: &PublicWorkspaceFileContext,
    action: &str,
) -> PublicWorkspaceFileContext {
    let mut context = context.clone();
    if context.idempotency_key.is_none() {
        context.idempotency_key = Some(format!("legacy-{action}:{}", Uuid::new_v4()));
    }
    context
}
fn required_idempotency(
    context: &PublicWorkspaceFileContext,
) -> Result<&str, PublicWorkspaceFileError> {
    let value = context
        .idempotency_key
        .as_deref()
        .ok_or(PublicWorkspaceFileError::Conflict)?;
    if value.is_empty() || value.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS {
        return Err(PublicWorkspaceFileError::InvalidRequest(
            "Invalid idempotency key".to_string(),
        ));
    }
    Ok(value)
}
fn public_file(
    record: &WorkspaceFileRecord,
) -> Result<PublicWorkspaceFile, PublicWorkspaceFileError> {
    Ok(PublicWorkspaceFile {
        id: record.file_id.clone(),
        workspace_id: record.workspace_id.clone(),
        parent_path: record.parent_path.clone(),
        name: record.name.clone(),
        is_directory: record.is_directory,
        file_size: record.file_size,
        content_type: record.content_type.clone(),
        uploader_type: record.uploader_type.clone(),
        uploader_id: record.uploader_id.clone(),
        uploader_name: record.uploader_name.clone(),
        created_at: record.created_at.clone(),
    })
}
fn file_outcome(
    file: PublicWorkspaceFile,
    outcome: WorkspaceFileMutationOutcome,
) -> PublicWorkspaceFileOutcome {
    PublicWorkspaceFileOutcome {
        file,
        receipt_id: outcome.receipt_id,
        committed_revision: outcome.committed_revision,
        outbox_id: outcome.outbox_id,
        replayed: outcome.replayed,
    }
}
fn created_event(response: &PublicWorkspaceFile, copied_from: Option<&str>) -> Value {
    let mut value = json!({"file": response, "file_id": response.id, "parent_path": response.parent_path, "name": response.name, "is_directory": response.is_directory, "authority_class": "authoritative", "surface_boundary": "owned"});
    if let Some(source) = copied_from {
        value["copied_from"] = Value::String(source.to_string());
    }
    value
}
fn timestamp() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}
fn deterministic_file_id(
    context: &PublicWorkspaceFileContext,
    kind: &str,
    discriminator: &str,
) -> String {
    Uuid::new_v5(
        &FILE_NAMESPACE,
        format!(
            "{kind}\0{}\0{}\0{}\0{}\0{}\0{discriminator}",
            context.tenant_id,
            context.project_id,
            context.workspace_id,
            context.user_id,
            context.idempotency_key.as_deref().unwrap_or_default()
        )
        .as_bytes(),
    )
    .to_string()
}
fn deterministic_operation_id(context: &PublicWorkspaceFileContext, file_id: &str) -> String {
    format!(
        "file-operation-{}",
        deterministic_file_id(context, "operation", file_id)
    )
}
fn object_key(context: &PublicWorkspaceFileContext, file_id: &str, filename: &str) -> String {
    format!(
        "workspace-files/{}/{}/{}/{file_id}/{filename}",
        context.tenant_id, context.project_id, context.workspace_id
    )
}
#[allow(clippy::possible_missing_else)]
fn validate_upload(
    size: u64,
    checksum: &str,
    backend_max: u64,
) -> Result<(), PublicWorkspaceFileError> {
    let max = MAX_FILE_SIZE.min(backend_max);
    if size > max {
        return Err(PublicWorkspaceFileError::InvalidRequest(format!(
            "File exceeds maximum size of {max} bytes"
        )));
    }
    if checksum.len() != 64
        || !checksum
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(PublicWorkspaceFileError::InvalidRequest(
            "Invalid staged upload checksum".to_string(),
        ));
    }
    Ok(())
}
fn validate_filename(value: &str) -> Result<String, PublicWorkspaceFileError> {
    let value = value.trim();
    if value.is_empty()
        || value.chars().count() > 255
        || value.contains(['/', '\\', '\0'])
        || matches!(value, "." | "..")
        || is_blocked(value)
    {
        return Err(PublicWorkspaceFileError::InvalidRequest(
            "Invalid filename".to_string(),
        ));
    }
    Ok(value.to_string())
}
#[allow(clippy::possible_missing_else)]
fn validate_path(value: &str) -> Result<String, PublicWorkspaceFileError> {
    let normalized = value.trim().replace('\\', "/");
    let mut parts = Vec::new();
    for part in normalized.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." || is_blocked(part) || part.contains('\0') {
            return Err(PublicWorkspaceFileError::InvalidRequest(
                "Path traversal detected".to_string(),
            ));
        }
        parts.push(part);
    }
    if parts.is_empty() {
        Ok("/".to_string())
    } else {
        Ok(format!("/{}/", parts.join("/")))
    }
}
fn is_blocked(value: &str) -> bool {
    BLOCKED_SEGMENTS
        .iter()
        .any(|blocked| value.eq_ignore_ascii_case(blocked))
}
fn join_child(parent: &str, name: &str) -> String {
    format!("{}{name}/", parent.trim_end_matches('/').to_string() + "/")
}
fn split_directory_path(path: &str) -> Result<(String, String), PublicWorkspaceFileError> {
    let trimmed = path.trim_matches('/');
    let mut parts: Vec<&str> = trimmed.split('/').collect();
    let name = parts
        .pop()
        .ok_or(PublicWorkspaceFileError::FileNotFound)?
        .to_string();
    let parent = if parts.is_empty() {
        "/".to_string()
    } else {
        format!("/{}/", parts.join("/"))
    };
    Ok((parent, name))
}
fn normalized_content_type(value: &str) -> String {
    if value.trim().is_empty() {
        "application/octet-stream".to_string()
    } else {
        value.trim().to_string()
    }
}
fn request_hash(value: Value) -> Result<String, PublicWorkspaceFileError> {
    Ok(hex::encode(Sha256::digest(serde_json::to_vec(
        &super::canonical_json(&value),
    )?)))
}
fn upload_request_hash(
    context: &PublicWorkspaceFileContext,
    parent: &str,
    filename: &str,
    content_type: &str,
    size: u64,
    checksum: &str,
) -> Result<String, PublicWorkspaceFileError> {
    request_hash(
        json!({"action": "upload_file", "scope": {"tenant_id": context.tenant_id, "project_id": context.project_id, "workspace_id": context.workspace_id}, "actor_id": context.user_id, "parent_path": parent, "filename": filename, "content_type": normalized_content_type(content_type), "size_bytes": size, "checksum_sha256": checksum}),
    )
}
fn stable_payload(value: &Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .iter()
                .filter(|(key, _)| !matches!(key.as_str(), "created_at" | "updated_at"))
                .map(|(key, value)| (key.clone(), stable_payload(value)))
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(stable_payload).collect()),
        _ => value.clone(),
    }
}
fn placeholder_upload_record(
    context: &PublicWorkspaceFileContext,
    file_id: &str,
    parent: &str,
    filename: &str,
    content_type: &str,
    size: u64,
    checksum: &str,
) -> WorkspaceFileRecord {
    let now = timestamp();
    WorkspaceFileRecord {
        file_id: file_id.to_string(),
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
        parent_path: parent.to_string(),
        name: filename.to_string(),
        is_directory: false,
        file_size: size,
        content_type: normalized_content_type(content_type),
        storage_backend: String::new(),
        object_handle: String::new(),
        object_state: "staging".to_string(),
        uploader_type: context.uploader_type.clone(),
        uploader_id: context.uploader_id.clone(),
        uploader_actor_id: context.uploader_actor_id.clone(),
        uploader_name: context.user_name.clone(),
        checksum_sha256: Some(checksum.to_string()),
        detected_mime_type: None,
        revision: 1,
        created_at: now.clone(),
        updated_at: now,
    }
}
