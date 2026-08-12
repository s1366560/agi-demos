//! Legacy-compatible Workspace topology use cases over the Avernet authority.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use memstack_workspace_store::{
    WorkspaceTopologyDomainWrite, WorkspaceTopologyEdgeRecord, WorkspaceTopologyNodeRecord,
    WorkspaceTopologyStore, WorkspaceTopologyStoreError,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use thiserror::Error;

#[path = "public_topology_commit.rs"]
mod commit;
#[path = "public_topology_projection.rs"]
mod projection;

use self::commit::outcome_value;
use projection::*;

const TOPOLOGY_NODE_TYPES: &[&str] = &[
    "user",
    "agent",
    "task",
    "note",
    "corridor",
    "human_seat",
    "objective",
];

/// Authenticated topology request scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceTopologyContext {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub user_id: String,
    pub expected_revision: Option<u64>,
    pub idempotency_key: Option<String>,
}

/// Public topology node response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublicWorkspaceTopologyNode {
    pub id: String,
    pub workspace_id: String,
    pub node_type: String,
    pub ref_id: Option<String>,
    pub title: String,
    pub position_x: f64,
    pub position_y: f64,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub status: String,
    pub tags: Value,
    pub data: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Public topology edge response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PublicWorkspaceTopologyEdge {
    pub id: String,
    pub workspace_id: String,
    pub source_node_id: String,
    pub target_node_id: String,
    pub label: Option<String>,
    pub source_hex_q: Option<i64>,
    pub source_hex_r: Option<i64>,
    pub target_hex_q: Option<i64>,
    pub target_hex_r: Option<i64>,
    pub direction: Option<String>,
    pub auto_created: bool,
    pub data: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Create-node input after HTTP decoding.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateTopologyNodeInput {
    pub context: PublicWorkspaceTopologyContext,
    pub node_type: String,
    pub ref_id: Option<String>,
    pub title: String,
    pub position_x: f64,
    pub position_y: f64,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub status: String,
    pub tags: Value,
    pub data: Value,
}

/// PATCH node fields where `None` preserves the persisted value.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PublicUpdateTopologyNodeFields {
    pub node_type: Option<String>,
    pub ref_id: Option<String>,
    pub title: Option<String>,
    pub position_x: Option<f64>,
    pub position_y: Option<f64>,
    pub hex_q: Option<i64>,
    pub hex_r: Option<i64>,
    pub status: Option<String>,
    pub tags: Option<Value>,
    pub data: Option<Value>,
}

/// Create-edge input after HTTP decoding.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicCreateTopologyEdgeInput {
    pub context: PublicWorkspaceTopologyContext,
    pub source_node_id: String,
    pub target_node_id: String,
    pub label: Option<String>,
    pub direction: Option<String>,
    pub auto_created: bool,
    pub data: Value,
}

/// PATCH edge fields where `None` preserves the persisted value.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct PublicUpdateTopologyEdgeFields {
    pub source_node_id: Option<String>,
    pub target_node_id: Option<String>,
    pub label: Option<String>,
    pub direction: Option<String>,
    pub auto_created: Option<bool>,
    pub data: Option<Value>,
}

/// Successful topology write with authority metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspaceTopologyOutcome<T> {
    pub value: T,
    pub committed_revision: u64,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable topology application failure categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PublicWorkspaceTopologyErrorKind {
    InvalidRequest,
    NotFound,
    Forbidden,
    Conflict,
    Unavailable,
}

/// Stable topology application failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceTopologyError {
    #[error("invalid Workspace topology request")]
    InvalidRequest,
    #[error("Workspace not found")]
    WorkspaceNotFound,
    #[error("User must be a workspace member")]
    MembershipRequired,
    #[error("Workspace topology access denied")]
    Forbidden,
    #[error("Topology node not found")]
    NodeNotFound,
    #[error("Topology edge not found")]
    EdgeNotFound,
    #[error("Edge endpoints must exist in same workspace")]
    EndpointScope,
    #[error("Workspace topology authority conflict")]
    Conflict,
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Store(#[from] WorkspaceTopologyStoreError),
}

impl PublicWorkspaceTopologyError {
    #[must_use]
    pub const fn kind(&self) -> PublicWorkspaceTopologyErrorKind {
        match self {
            Self::InvalidRequest | Self::EndpointScope => {
                PublicWorkspaceTopologyErrorKind::InvalidRequest
            }
            Self::WorkspaceNotFound | Self::NodeNotFound | Self::EdgeNotFound => {
                PublicWorkspaceTopologyErrorKind::NotFound
            }
            Self::MembershipRequired | Self::Forbidden => {
                PublicWorkspaceTopologyErrorKind::Forbidden
            }
            Self::Conflict => PublicWorkspaceTopologyErrorKind::Conflict,
            Self::Json(_) => PublicWorkspaceTopologyErrorKind::Unavailable,
            Self::Store(error) => match error {
                WorkspaceTopologyStoreError::NotFound
                | WorkspaceTopologyStoreError::NodeNotFound
                | WorkspaceTopologyStoreError::EdgeNotFound => {
                    PublicWorkspaceTopologyErrorKind::NotFound
                }
                WorkspaceTopologyStoreError::AccessRequired
                | WorkspaceTopologyStoreError::EditorAccessRequired => {
                    PublicWorkspaceTopologyErrorKind::Forbidden
                }
                WorkspaceTopologyStoreError::Conflict
                | WorkspaceTopologyStoreError::IdempotencyConflict
                | WorkspaceTopologyStoreError::IncompleteReceipt => {
                    PublicWorkspaceTopologyErrorKind::Conflict
                }
                WorkspaceTopologyStoreError::InvalidRecord(_)
                | WorkspaceTopologyStoreError::InvalidJson(_)
                | WorkspaceTopologyStoreError::Database(_) => {
                    PublicWorkspaceTopologyErrorKind::Unavailable
                }
                _ => PublicWorkspaceTopologyErrorKind::Unavailable,
            },
        }
    }
}

/// Workspace topology application service.
pub struct PublicWorkspaceTopologyService<'a> {
    store: WorkspaceTopologyStore<'a>,
    receipt_authority: Option<WorkspaceMutationAuthority>,
}

impl<'a> PublicWorkspaceTopologyService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceTopologyStore::new(db, flavor),
            receipt_authority: None,
        }
    }

    /// Persist a collaboration receipt envelope with the topology write.
    #[must_use]
    pub fn with_mutation_authority(mut self, authority: WorkspaceMutationAuthority) -> Self {
        self.receipt_authority = Some(authority);
        self
    }

    /// Create one topology node atomically with its outbox event.
    pub async fn create_node(
        &self,
        input: &PublicCreateTopologyNodeInput,
    ) -> Result<
        PublicWorkspaceTopologyOutcome<PublicWorkspaceTopologyNode>,
        PublicWorkspaceTopologyError,
    > {
        validate_node_input(input)?;
        let context = prepared_context(&input.context, "create_topology_node");
        self.require_access(&context, true).await?;
        let node_id = deterministic_id(&context, "node", "root");
        ensure_hex_available(
            &self.store,
            &context,
            input.hex_q,
            input.hex_r,
            Some(node_id.as_str()),
        )
        .await?;
        let now = timestamp();
        let record = WorkspaceTopologyNodeRecord {
            node_id,
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            node_type: input.node_type.clone(),
            ref_id: input.ref_id.clone(),
            title: input.title.clone(),
            position_x: input.position_x,
            position_y: input.position_y,
            hex_q: input.hex_q,
            hex_r: input.hex_r,
            status: input.status.clone(),
            tags: input.tags.clone(),
            data: input.data.clone(),
            created_at: now.clone(),
            updated_at: Some(now),
        };
        let response = public_node(&record)?;
        let event = json!({
            "workspace_id": &context.workspace_id,
            "operation": "node_created",
            "node_id": &response.id,
            "node": &response,
        });
        self.commit_node(
            &context,
            "create_topology_node",
            WorkspaceTopologyDomainWrite::CreateNode(record),
            response,
            event,
        )
        .await
    }

    /// List visible topology nodes.
    pub async fn list_nodes(
        &self,
        context: &PublicWorkspaceTopologyContext,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<PublicWorkspaceTopologyNode>, PublicWorkspaceTopologyError> {
        validate_page(limit, offset)?;
        self.require_access(context, false).await?;
        self.store
            .list_nodes(&topology_scope(context), limit, offset)
            .await?
            .iter()
            .map(public_node)
            .collect()
    }

    /// Read one visible topology node.
    pub async fn get_node(
        &self,
        context: &PublicWorkspaceTopologyContext,
        node_id: &str,
    ) -> Result<PublicWorkspaceTopologyNode, PublicWorkspaceTopologyError> {
        self.require_access(context, false).await?;
        let record = self
            .store
            .get_node(&topology_scope(context), node_id)
            .await?
            .ok_or(PublicWorkspaceTopologyError::NodeNotFound)?;
        public_node(&record)
    }

    /// Update one topology node and synchronize all connected edge coordinates atomically.
    pub async fn update_node(
        &self,
        context: &PublicWorkspaceTopologyContext,
        node_id: &str,
        fields: &PublicUpdateTopologyNodeFields,
    ) -> Result<
        PublicWorkspaceTopologyOutcome<PublicWorkspaceTopologyNode>,
        PublicWorkspaceTopologyError,
    > {
        let mut record = self.require_node_for_write(context, node_id).await?;
        apply_node_fields(&mut record, fields)?;
        ensure_hex_available(
            &self.store,
            context,
            record.hex_q,
            record.hex_r,
            Some(record.node_id.as_str()),
        )
        .await?;
        record.updated_at = Some(timestamp());
        let response = public_node(&record)?;
        let mut updated_edges: Vec<PublicWorkspaceTopologyEdge> = self
            .store
            .list_edges_for_node(&topology_scope(context), node_id)
            .await?
            .iter()
            .map(public_edge)
            .collect::<Result<_, _>>()?;
        for edge in &mut updated_edges {
            if edge.source_node_id == node_id {
                edge.source_hex_q = record.hex_q;
                edge.source_hex_r = record.hex_r;
            }
            if edge.target_node_id == node_id {
                edge.target_hex_q = record.hex_q;
                edge.target_hex_r = record.hex_r;
            }
            edge.updated_at.clone_from(&record.updated_at);
        }
        let event = json!({
            "workspace_id": &context.workspace_id,
            "operation": "node_updated",
            "node_id": node_id,
            "node": &response,
            "updated_edges": updated_edges,
        });
        self.commit_node(
            context,
            "update_topology_node",
            WorkspaceTopologyDomainWrite::UpdateNode(record),
            response,
            event,
        )
        .await
    }

    /// Delete one topology node and cascade its connected edges atomically.
    pub async fn delete_node(
        &self,
        context: &PublicWorkspaceTopologyContext,
        node_id: &str,
    ) -> Result<PublicWorkspaceTopologyOutcome<Value>, PublicWorkspaceTopologyError> {
        let _record = self.require_node_for_write(context, node_id).await?;
        self.commit_value(
            context,
            "delete_topology_node",
            node_id,
            WorkspaceTopologyDomainWrite::DeleteNode {
                node_id: node_id.to_string(),
            },
            json!({"success": true}),
            json!({
                "workspace_id": &context.workspace_id,
                "operation": "node_deleted",
                "node_id": node_id,
            }),
        )
        .await
        .map(outcome_value)
    }

    /// Create one edge after validating both scoped endpoint nodes.
    pub async fn create_edge(
        &self,
        input: &PublicCreateTopologyEdgeInput,
    ) -> Result<
        PublicWorkspaceTopologyOutcome<PublicWorkspaceTopologyEdge>,
        PublicWorkspaceTopologyError,
    > {
        validate_edge_input(input)?;
        let context = prepared_context(&input.context, "create_topology_edge");
        self.require_access(&context, true).await?;
        let (source, target) = self
            .edge_endpoints(&context, &input.source_node_id, &input.target_node_id)
            .await?;
        let now = timestamp();
        let record = WorkspaceTopologyEdgeRecord {
            edge_id: deterministic_id(&context, "edge", "root"),
            tenant_id: context.tenant_id.clone(),
            project_id: context.project_id.clone(),
            workspace_id: context.workspace_id.clone(),
            source_node_id: input.source_node_id.clone(),
            target_node_id: input.target_node_id.clone(),
            edge_type: "dependency".to_string(),
            label: input.label.clone(),
            source_hex_q: source.hex_q,
            source_hex_r: source.hex_r,
            target_hex_q: target.hex_q,
            target_hex_r: target.hex_r,
            direction: input.direction.clone(),
            auto_created: input.auto_created,
            data: input.data.clone(),
            created_at: now.clone(),
            updated_at: Some(now),
        };
        let response = public_edge(&record)?;
        let event = json!({
            "workspace_id": &context.workspace_id,
            "operation": "edge_created",
            "edge_id": &response.id,
            "edge": &response,
        });
        self.commit_edge(
            &context,
            "create_topology_edge",
            WorkspaceTopologyDomainWrite::CreateEdge(record),
            response,
            event,
        )
        .await
    }

    /// List visible topology edges.
    pub async fn list_edges(
        &self,
        context: &PublicWorkspaceTopologyContext,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<PublicWorkspaceTopologyEdge>, PublicWorkspaceTopologyError> {
        validate_page(limit, offset)?;
        self.require_access(context, false).await?;
        self.store
            .list_edges(&topology_scope(context), limit, offset)
            .await?
            .iter()
            .map(public_edge)
            .collect()
    }

    /// Read one visible topology edge.
    pub async fn get_edge(
        &self,
        context: &PublicWorkspaceTopologyContext,
        edge_id: &str,
    ) -> Result<PublicWorkspaceTopologyEdge, PublicWorkspaceTopologyError> {
        self.require_access(context, false).await?;
        let record = self
            .store
            .get_edge(&topology_scope(context), edge_id)
            .await?
            .ok_or(PublicWorkspaceTopologyError::EdgeNotFound)?;
        public_edge(&record)
    }

    /// Update one edge and refresh endpoint coordinates from node authority.
    pub async fn update_edge(
        &self,
        context: &PublicWorkspaceTopologyContext,
        edge_id: &str,
        fields: &PublicUpdateTopologyEdgeFields,
    ) -> Result<
        PublicWorkspaceTopologyOutcome<PublicWorkspaceTopologyEdge>,
        PublicWorkspaceTopologyError,
    > {
        let mut record = self.require_edge_for_write(context, edge_id).await?;
        apply_edge_fields(&mut record, fields)?;
        let (source, target) = self
            .edge_endpoints(context, &record.source_node_id, &record.target_node_id)
            .await?;
        record.source_hex_q = source.hex_q;
        record.source_hex_r = source.hex_r;
        record.target_hex_q = target.hex_q;
        record.target_hex_r = target.hex_r;
        record.updated_at = Some(timestamp());
        let response = public_edge(&record)?;
        let event = json!({
            "workspace_id": &context.workspace_id,
            "operation": "edge_updated",
            "edge_id": edge_id,
            "edge": &response,
        });
        self.commit_edge(
            context,
            "update_topology_edge",
            WorkspaceTopologyDomainWrite::UpdateEdge(record),
            response,
            event,
        )
        .await
    }

    /// Delete one topology edge atomically.
    pub async fn delete_edge(
        &self,
        context: &PublicWorkspaceTopologyContext,
        edge_id: &str,
    ) -> Result<PublicWorkspaceTopologyOutcome<Value>, PublicWorkspaceTopologyError> {
        let _record = self.require_edge_for_write(context, edge_id).await?;
        self.commit_value(
            context,
            "delete_topology_edge",
            edge_id,
            WorkspaceTopologyDomainWrite::DeleteEdge {
                edge_id: edge_id.to_string(),
            },
            json!({"success": true}),
            json!({
                "workspace_id": &context.workspace_id,
                "operation": "edge_deleted",
                "edge_id": edge_id,
            }),
        )
        .await
        .map(outcome_value)
    }

    async fn require_access(
        &self,
        context: &PublicWorkspaceTopologyContext,
        editor: bool,
    ) -> Result<(), PublicWorkspaceTopologyError> {
        self.store
            .require_access(&topology_scope(context), context.user_id.as_str(), editor)
            .await
            .map_err(|error| match error {
                WorkspaceTopologyStoreError::NotFound => {
                    PublicWorkspaceTopologyError::WorkspaceNotFound
                }
                WorkspaceTopologyStoreError::AccessRequired => {
                    PublicWorkspaceTopologyError::MembershipRequired
                }
                WorkspaceTopologyStoreError::EditorAccessRequired => {
                    PublicWorkspaceTopologyError::Forbidden
                }
                other => PublicWorkspaceTopologyError::Store(other),
            })
    }

    async fn require_node_for_write(
        &self,
        context: &PublicWorkspaceTopologyContext,
        node_id: &str,
    ) -> Result<WorkspaceTopologyNodeRecord, PublicWorkspaceTopologyError> {
        self.require_access(context, true).await?;
        self.store
            .get_node(&topology_scope(context), node_id)
            .await?
            .ok_or(PublicWorkspaceTopologyError::NodeNotFound)
    }

    async fn require_edge_for_write(
        &self,
        context: &PublicWorkspaceTopologyContext,
        edge_id: &str,
    ) -> Result<WorkspaceTopologyEdgeRecord, PublicWorkspaceTopologyError> {
        self.require_access(context, true).await?;
        self.store
            .get_edge(&topology_scope(context), edge_id)
            .await?
            .ok_or(PublicWorkspaceTopologyError::EdgeNotFound)
    }

    async fn edge_endpoints(
        &self,
        context: &PublicWorkspaceTopologyContext,
        source_node_id: &str,
        target_node_id: &str,
    ) -> Result<
        (WorkspaceTopologyNodeRecord, WorkspaceTopologyNodeRecord),
        PublicWorkspaceTopologyError,
    > {
        if source_node_id == target_node_id {
            return Err(PublicWorkspaceTopologyError::InvalidRequest);
        }
        let scope = topology_scope(context);
        let source = self.store.get_node(&scope, source_node_id).await?;
        let target = self.store.get_node(&scope, target_node_id).await?;
        source
            .zip(target)
            .ok_or(PublicWorkspaceTopologyError::EndpointScope)
    }
}
