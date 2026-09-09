//! Sync cursor state and durable transfer intent values. None of these values
//! authenticates a remote receipt or authorizes a local acceptance.
use agistack_core::knowledge::KnowledgeScope;
use agistack_core::project_schema::cloud_rpc::CloudSchemaReceipt;

use super::super::ProjectSchemaReceipt;

/// Immutable identity of one schema synchronization association. The local
/// scope and remote origin must already be bound for Memory synchronization;
/// the SQLite cursor guard independently requires that association.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProjectSchemaSyncBinding {
    pub sync_key: String,
    pub scope: KnowledgeScope,
    pub authority: String,
    pub remote_tenant_id: String,
    pub remote_project_id: String,
    pub remote_actor_id: String,
    pub schema_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProjectSchemaSyncAnchorKind {
    SourceSeed,
    DestinationSeed,
    Pair,
}

impl ProjectSchemaSyncAnchorKind {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::SourceSeed => "source_seed",
            Self::DestinationSeed => "destination_seed",
            Self::Pair => "pair",
        }
    }

    pub(super) fn from_str(value: &str) -> Option<Self> {
        match value {
            "source_seed" => Some(Self::SourceSeed),
            "destination_seed" => Some(Self::DestinationSeed),
            "pair" => Some(Self::Pair),
            _ => None,
        }
    }
}

/// Which side received the content transfer recorded by an anchor. `Neither`
/// marks an observation or an equivalence bind without any new acceptance.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProjectSchemaSyncImportedSide {
    Native,
    Cloud,
    Neither,
}

impl ProjectSchemaSyncImportedSide {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::Native => "native",
            Self::Cloud => "cloud",
            Self::Neither => "neither",
        }
    }

    pub(super) fn from_str(value: &str) -> Option<Self> {
        match value {
            "native" => Some(Self::Native),
            "cloud" => Some(Self::Cloud),
            "neither" => Some(Self::Neither),
            _ => None,
        }
    }
}

/// One immutable accepted mapping between the two scopes' histories. Pair
/// anchors retain both exact receipts; seed anchors retain only the cloud one.
#[derive(Debug, Clone, PartialEq)]
pub struct ProjectSchemaSyncAnchor {
    pub anchor_id: String,
    pub predecessor_anchor_id: Option<String>,
    pub producing_step_id: String,
    pub kind: ProjectSchemaSyncAnchorKind,
    pub native_receipt: Option<ProjectSchemaReceipt>,
    pub cloud_receipt: CloudSchemaReceipt,
    pub imported_side: ProjectSchemaSyncImportedSide,
}

impl ProjectSchemaSyncAnchor {
    pub fn native_revision(&self) -> u32 {
        self.native_receipt
            .as_ref()
            .map_or(0, |receipt| receipt.document().revision())
    }

    pub fn cloud_revision(&self) -> u32 {
        self.cloud_receipt.revision()
    }
}

/// The durable position of one synchronization association. Cursors never move
/// backward and every epoch advance is chained to exactly one new anchor.
#[derive(Debug, Clone, PartialEq)]
pub struct ProjectSchemaSyncState {
    pub epoch: u64,
    pub native_after: u32,
    pub cloud_after: u32,
    pub head: Option<ProjectSchemaSyncAnchor>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProjectSchemaSyncStepKind {
    NativeBootstrap,
    NativeReplace,
    CloudReplace,
}

impl ProjectSchemaSyncStepKind {
    pub(super) fn as_str(self) -> &'static str {
        match self {
            Self::NativeBootstrap => "native_bootstrap",
            Self::NativeReplace => "native_replace",
            Self::CloudReplace => "cloud_replace",
        }
    }

    pub(super) fn from_str(value: &str) -> Option<Self> {
        match value {
            "native_bootstrap" => Some(Self::NativeBootstrap),
            "native_replace" => Some(Self::NativeReplace),
            "cloud_replace" => Some(Self::CloudReplace),
            _ => None,
        }
    }
}

/// Immutable prepared intent fenced to an exact cursor position. Native steps
/// complete inside their own transaction; a prepared cloud step survives
/// process restart so an uncertain remote outcome can be recovered explicitly.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProjectSchemaSyncPrepared {
    pub step_id: String,
    pub kind: ProjectSchemaSyncStepKind,
    pub local_actor_id: String,
    pub expected_anchor_id: Option<String>,
    pub expected_epoch: u64,
    pub source_receipt: String,
    pub destination_base: Option<String>,
    pub destination_change_id: String,
    pub request_json: String,
    pub completed_anchor_id: Option<String>,
}
