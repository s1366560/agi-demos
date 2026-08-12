//! Legacy-compatible Workspace Gene use cases over the Avernet authority.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{SecondsFormat, Utc};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use memstack_workspace_store::{
    WorkspaceGeneDomainWrite, WorkspaceGeneMutation, WorkspaceGeneRecord, WorkspaceGeneScope,
    WorkspaceGeneStore, WorkspaceGeneStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;
use uuid::Uuid;

use crate::canonical_json;

const GENE_NAMESPACE: Uuid = Uuid::from_u128(0xc5d9_1972_145b_4706_825a_9908_6237_6f64);
const CATEGORIES: &[&str] = &["skill", "knowledge", "tool", "workflow"];
const MAX_NAME_CHARS: usize = 200;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;

/// Authenticated public Gene request scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceGeneContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub is_superuser: bool,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Legacy-compatible Gene response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublicWorkspaceGene {
    pub id: String,
    pub workspace_id: String,
    pub name: String,
    pub category: String,
    pub description: Option<String>,
    pub config_json: Option<String>,
    pub version: String,
    pub is_active: bool,
    pub created_by: String,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Create-Gene input after HTTP decoding.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateWorkspaceGeneInput {
    pub context: PublicWorkspaceGeneContext,
    pub name: String,
    pub category: String,
    pub description: Option<String>,
    pub config_json: Option<String>,
    pub version: String,
    pub is_active: bool,
}

/// PATCH fields where `None` preserves persisted values.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PublicUpdateWorkspaceGeneFields {
    pub name: Option<String>,
    pub category: Option<String>,
    pub description: Option<String>,
    pub config_json: Option<String>,
    pub version: Option<String>,
    pub is_active: Option<bool>,
}

/// Successful Gene write with authority metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceGeneOutcome {
    pub gene: PublicWorkspaceGene,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Successful Gene deletion with retained authority metadata.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceGeneDeleteOutcome {
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable Gene application failure categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceGeneErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Stable Gene application failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceGeneError {
    #[error("invalid Workspace Gene request")]
    InvalidRequest,
    #[error("Gene not found")]
    GeneNotFound,
    #[error("Workspace Gene access denied")]
    Forbidden,
    #[error("Workspace Gene authority conflict")]
    Conflict,
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Store(#[from] WorkspaceGeneStoreError),
}

impl PublicWorkspaceGeneError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceGeneErrorKind {
        match self {
            Self::InvalidRequest => PublicWorkspaceGeneErrorKind::InvalidRequest,
            Self::GeneNotFound => PublicWorkspaceGeneErrorKind::NotFound,
            Self::Forbidden => PublicWorkspaceGeneErrorKind::Forbidden,
            Self::Conflict => PublicWorkspaceGeneErrorKind::Conflict,
            Self::Json(_) => PublicWorkspaceGeneErrorKind::Unavailable,
            Self::Store(error) => match error {
                WorkspaceGeneStoreError::NotFound | WorkspaceGeneStoreError::GeneNotFound => {
                    PublicWorkspaceGeneErrorKind::NotFound
                }
                WorkspaceGeneStoreError::AccessRequired
                | WorkspaceGeneStoreError::EditorAccessRequired => {
                    PublicWorkspaceGeneErrorKind::Forbidden
                }
                WorkspaceGeneStoreError::Conflict
                | WorkspaceGeneStoreError::IdempotencyConflict
                | WorkspaceGeneStoreError::IncompleteReceipt => {
                    PublicWorkspaceGeneErrorKind::Conflict
                }
                WorkspaceGeneStoreError::InvalidRecord(_)
                | WorkspaceGeneStoreError::InvalidJson(_)
                | WorkspaceGeneStoreError::Database(_) => PublicWorkspaceGeneErrorKind::Unavailable,
                _ => PublicWorkspaceGeneErrorKind::Unavailable,
            },
        }
    }
}

/// Workspace Gene application service.
pub struct PublicWorkspaceGeneService<'a> {
    store: WorkspaceGeneStore<'a>,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceGeneService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceGeneStore::new(db, flavor),
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the Gene domain write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    /// Create one Gene atomically with receipt, revision CAS, and durable outbox.
    pub async fn create(
        &self,
        input: &PublicCreateWorkspaceGeneInput,
    ) -> Result<PublicWorkspaceGeneOutcome, PublicWorkspaceGeneError> {
        validate_name(input.name.as_str())?;
        validate_category(input.category.as_str())?;
        validate_idempotency(input.context.idempotency_key.as_deref())?;
        let content = parse_config(input.config_json.as_deref())?;
        let context = prepared_context(&input.context, "create_gene");
        let scope = gene_scope(&context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true, context.is_superuser)
            .await?;
        let created_at = timestamp();
        let gene_id = deterministic_gene_id(&context);
        let record = WorkspaceGeneRecord {
            gene_id: gene_id.clone(),
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            name: input.name.clone(),
            description: input.description.clone(),
            category: input.category.clone(),
            status: active_status(input.is_active).to_string(),
            version: 1,
            source_version: input.version.clone(),
            is_active: input.is_active,
            config_text: input.config_json.clone(),
            content_hash: content_hash(&content)?,
            content,
            created_by_actor_id: context.user_id.clone(),
            created_at,
            updated_at: None,
        };
        let response = public_gene(&record);
        self.commit(
            &context,
            "create_gene",
            gene_id.as_str(),
            WorkspaceGeneDomainWrite::Create(record),
            response,
            "workspace_gene_created",
        )
        .await
    }

    /// List Genes visible to the current member.
    pub async fn list(
        &self,
        context: &PublicWorkspaceGeneContext,
        category: Option<&str>,
        is_active: Option<bool>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<PublicWorkspaceGene>, PublicWorkspaceGeneError> {
        validate_page(limit, offset)?;
        if let Some(category) = category {
            validate_category(category)?;
        }
        let scope = gene_scope(context);
        self.store
            .require_access(
                &scope,
                context.user_id.as_str(),
                false,
                context.is_superuser,
            )
            .await?;
        Ok(self
            .store
            .list(&scope, category, is_active, limit, offset)
            .await?
            .iter()
            .map(public_gene)
            .collect())
    }

    /// Read one scoped Gene.
    pub async fn get(
        &self,
        context: &PublicWorkspaceGeneContext,
        gene_id: &str,
    ) -> Result<PublicWorkspaceGene, PublicWorkspaceGeneError> {
        let scope = gene_scope(context);
        self.store
            .require_access(
                &scope,
                context.user_id.as_str(),
                false,
                context.is_superuser,
            )
            .await?;
        self.store
            .get(&scope, gene_id)
            .await?
            .as_ref()
            .map(public_gene)
            .ok_or(PublicWorkspaceGeneError::GeneNotFound)
    }

    /// Update one scoped Gene atomically. The internal integer version advances
    /// independently from the legacy semantic source version.
    pub async fn update(
        &self,
        context: &PublicWorkspaceGeneContext,
        gene_id: &str,
        fields: &PublicUpdateWorkspaceGeneFields,
    ) -> Result<PublicWorkspaceGeneOutcome, PublicWorkspaceGeneError> {
        let scope = gene_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true, context.is_superuser)
            .await?;
        let mut record = self
            .store
            .get(&scope, gene_id)
            .await?
            .ok_or(PublicWorkspaceGeneError::GeneNotFound)?;
        if let Some(name) = &fields.name {
            validate_name(name)?;
            record.name.clone_from(name);
        }
        if let Some(category) = &fields.category {
            validate_category(category)?;
            record.category.clone_from(category);
        }
        if let Some(description) = &fields.description {
            record.description = Some(description.clone());
        }
        if let Some(config_json) = &fields.config_json {
            record.content = parse_config(Some(config_json.as_str()))?;
            record.content_hash = content_hash(&record.content)?;
            record.config_text = Some(config_json.clone());
        }
        if let Some(version) = &fields.version {
            record.source_version.clone_from(version);
        }
        if let Some(is_active) = fields.is_active {
            record.is_active = is_active;
            record.status = active_status(is_active).to_string();
        }
        record.version = record
            .version
            .checked_add(1)
            .ok_or(PublicWorkspaceGeneError::Conflict)?;
        record.updated_at = Some(timestamp());
        let response = public_gene(&record);
        self.commit(
            context,
            "update_gene",
            gene_id,
            WorkspaceGeneDomainWrite::Update(record),
            response,
            "workspace_gene_updated",
        )
        .await
    }

    /// Delete one scoped Gene atomically.
    pub async fn delete(
        &self,
        context: &PublicWorkspaceGeneContext,
        gene_id: &str,
    ) -> Result<(), PublicWorkspaceGeneError> {
        self.delete_with_outcome(context, gene_id).await.map(drop)
    }

    /// Delete one scoped Gene and retain authority metadata for compatibility facades.
    pub async fn delete_with_outcome(
        &self,
        context: &PublicWorkspaceGeneContext,
        gene_id: &str,
    ) -> Result<PublicWorkspaceGeneDeleteOutcome, PublicWorkspaceGeneError> {
        let scope = gene_scope(context);
        self.store
            .require_access(&scope, context.user_id.as_str(), true, context.is_superuser)
            .await?;
        let response = json!({"success": true});
        let outcome = self
            .commit_value(
                context,
                "delete_gene",
                gene_id,
                WorkspaceGeneDomainWrite::Delete {
                    gene_id: gene_id.to_string(),
                },
                response,
                "workspace_gene_deleted",
            )
            .await?;
        Ok(PublicWorkspaceGeneDeleteOutcome {
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    async fn commit(
        &self,
        context: &PublicWorkspaceGeneContext,
        action: &str,
        gene_id: &str,
        domain_write: WorkspaceGeneDomainWrite,
        response: PublicWorkspaceGene,
        event_type: &str,
    ) -> Result<PublicWorkspaceGeneOutcome, PublicWorkspaceGeneError> {
        let response_value = serde_json::to_value(&response)?;
        let outcome = self
            .commit_value(
                context,
                action,
                gene_id,
                domain_write,
                response_value.clone(),
                event_type,
            )
            .await?;
        Ok(PublicWorkspaceGeneOutcome {
            gene: serde_json::from_value(outcome.response)?,
            committed_revision: outcome.committed_revision,
            outbox_id: outcome.outbox_id,
            replayed: outcome.replayed,
        })
    }

    #[allow(clippy::too_many_arguments)]
    async fn commit_value(
        &self,
        context: &PublicWorkspaceGeneContext,
        action: &str,
        gene_id: &str,
        domain_write: WorkspaceGeneDomainWrite,
        response: Value,
        event_type: &str,
    ) -> Result<memstack_workspace_store::WorkspaceGeneMutationOutcome, PublicWorkspaceGeneError>
    {
        let context = prepared_context(context, action);
        let scope = gene_scope(&context);
        let expected_revision = match context.expected_revision {
            Some(revision) => revision,
            None => self.store.revision(&scope).await?,
        };
        let idempotency_key = context
            .idempotency_key
            .clone()
            .ok_or(PublicWorkspaceGeneError::InvalidRequest)?;
        validate_idempotency(Some(idempotency_key.as_str()))?;
        let event_payload = json!({
            "gene": &response,
            "gene_id": gene_id,
            "workspace_id": &context.workspace_id,
        });
        let domain_hash = request_hash(json!({
            "action": action,
            "scope": {
                "tenant_id": &context.tenant_id,
                "project_id": &context.project_id,
                "workspace_id": &context.workspace_id,
            },
            "actor_id": &context.user_id,
            "gene_id": gene_id,
            "response": hash_payload(&response),
        }))?;
        let payload_hash = self
            .receipt_authority
            .as_ref()
            .map_or(domain_hash, |authority| {
                authority.request_hash().as_str().to_string()
            });
        self.store
            .mutate(&WorkspaceGeneMutation {
                scope,
                actor_id: context.user_id,
                actor_is_superuser: context.is_superuser,
                action: action.to_string(),
                idempotency_key,
                payload_hash,
                expected_revision,
                aggregate_id: gene_id.to_string(),
                domain_write,
                response,
                event_type: event_type.to_string(),
                event_payload,
                receipt_authority: self.receipt_authority.clone(),
            })
            .await
            .map_err(Into::into)
    }
}

fn gene_scope(context: &PublicWorkspaceGeneContext) -> WorkspaceGeneScope {
    WorkspaceGeneScope {
        tenant_id: context.tenant_id.clone(),
        project_id: context.project_id.clone(),
        workspace_id: context.workspace_id.clone(),
    }
}

fn prepared_context(
    context: &PublicWorkspaceGeneContext,
    action: &str,
) -> PublicWorkspaceGeneContext {
    let mut context = context.clone();
    if context.idempotency_key.is_none() {
        context.idempotency_key = Some(format!("legacy-{action}:{}", Uuid::new_v4()));
    }
    context
}

fn deterministic_gene_id(context: &PublicWorkspaceGeneContext) -> String {
    let identity = format!(
        "{}\0{}\0{}\0{}\0{}",
        context.tenant_id,
        context.project_id,
        context.workspace_id,
        context.user_id,
        context.idempotency_key.as_deref().unwrap_or_default(),
    );
    Uuid::new_v5(&GENE_NAMESPACE, identity.as_bytes()).to_string()
}

fn public_gene(record: &WorkspaceGeneRecord) -> PublicWorkspaceGene {
    PublicWorkspaceGene {
        id: record.gene_id.clone(),
        workspace_id: record.workspace_id.clone(),
        name: record.name.clone(),
        category: record.category.clone(),
        description: record.description.clone(),
        config_json: record.config_text.clone(),
        version: record.source_version.clone(),
        is_active: record.is_active,
        created_by: record.created_by_actor_id.clone(),
        created_at: record.created_at.clone(),
        updated_at: record.updated_at.clone(),
    }
}

fn validate_name(value: &str) -> Result<(), PublicWorkspaceGeneError> {
    let chars = value.chars().count();
    if chars == 0 || chars > MAX_NAME_CHARS {
        return Err(PublicWorkspaceGeneError::InvalidRequest);
    }
    Ok(())
}

fn validate_category(value: &str) -> Result<(), PublicWorkspaceGeneError> {
    if !CATEGORIES.contains(&value) {
        return Err(PublicWorkspaceGeneError::InvalidRequest);
    }
    Ok(())
}

fn validate_page(limit: i64, offset: i64) -> Result<(), PublicWorkspaceGeneError> {
    if !(1..=500).contains(&limit) || offset < 0 {
        return Err(PublicWorkspaceGeneError::InvalidRequest);
    }
    Ok(())
}

fn validate_idempotency(value: Option<&str>) -> Result<(), PublicWorkspaceGeneError> {
    if let Some(value) = value
        && (value.is_empty() || value.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS)
    {
        return Err(PublicWorkspaceGeneError::InvalidRequest);
    }
    Ok(())
}

fn parse_config(value: Option<&str>) -> Result<Value, PublicWorkspaceGeneError> {
    let Some(value) = value.filter(|value| !value.is_empty()) else {
        return Ok(json!({}));
    };
    let parsed: Value = serde_json::from_str(value)?;
    if !parsed.is_object() {
        return Err(PublicWorkspaceGeneError::InvalidRequest);
    }
    Ok(parsed)
}

fn content_hash(content: &Value) -> Result<String, PublicWorkspaceGeneError> {
    let encoded = serde_json::to_vec(&canonical_json(content))?;
    Ok(hex::encode(Sha256::digest(encoded)))
}

fn request_hash(value: Value) -> Result<String, PublicWorkspaceGeneError> {
    let encoded = serde_json::to_vec(&canonical_json(&value))?;
    Ok(hex::encode(Sha256::digest(encoded)))
}

fn hash_payload(value: &Value) -> Value {
    match value {
        Value::Object(fields) => Value::Object(
            fields
                .iter()
                .filter(|(key, _)| !matches!(key.as_str(), "created_at" | "updated_at"))
                .map(|(key, value)| (key.clone(), hash_payload(value)))
                .collect(),
        ),
        Value::Array(values) => Value::Array(values.iter().map(hash_payload).collect()),
        _ => value.clone(),
    }
}

fn timestamp() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Micros, true)
}

const fn active_status(is_active: bool) -> &'static str {
    if is_active { "active" } else { "inactive" }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_requires_an_object_and_hashes_canonically() -> Result<(), PublicWorkspaceGeneError> {
        assert!(matches!(
            parse_config(Some("[]")),
            Err(PublicWorkspaceGeneError::InvalidRequest)
        ));
        assert_eq!(
            content_hash(&parse_config(Some(r#"{"b":2,"a":1}"#))?)?,
            content_hash(&parse_config(Some(r#"{"a":1,"b":2}"#))?)?
        );
        Ok(())
    }

    #[test]
    fn public_version_uses_semantic_source_version() {
        let record = WorkspaceGeneRecord {
            gene_id: "gene-1".to_string(),
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
            name: "Gene".to_string(),
            description: None,
            category: "skill".to_string(),
            status: "active".to_string(),
            version: 7,
            source_version: "2.4.1".to_string(),
            is_active: true,
            config_text: None,
            content: json!({}),
            content_hash: "0".repeat(64),
            created_by_actor_id: "user-1".to_string(),
            created_at: "2026-08-11T00:00:00Z".to_string(),
            updated_at: None,
        };
        assert_eq!(public_gene(&record).version, "2.4.1");
    }
}
