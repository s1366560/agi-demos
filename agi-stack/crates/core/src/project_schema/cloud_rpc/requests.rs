use serde::{Deserialize, Serialize};
use serde_json::{json, value::RawValue};

use super::{
    parse, uuid, CloudSchemaProtocolError, CloudSchemaReceipt, ProjectSchemaDocument, Result,
    MAX_CLOUD_SCHEMA_HISTORY_ITEMS,
};
use crate::project_schema::MAX_REVISION;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReplaceBody<'a> {
    #[serde(borrow)]
    document: &'a RawValue,
    expected_revision: u32,
    change_id: String,
}

/// Immutable wire intent. Persist these bytes before dispatch when adding a
/// coordinator; this value alone makes no durability or authorization claim.
#[derive(Debug, Clone)]
pub struct CloudSchemaReplaceRequest {
    raw: String,
    document: ProjectSchemaDocument,
    expected_revision: u32,
    change_id: String,
}

impl CloudSchemaReplaceRequest {
    /// Prepare one adjacent replacement against its exact accepted base.
    ///
    /// # Errors
    /// Rejects invalid IDs, nonadjacent revisions and illegal schema transitions.
    pub fn new(
        previous: &CloudSchemaReceipt,
        document: &ProjectSchemaDocument,
        change_id: &str,
    ) -> Result<Self> {
        let raw = json!({"document":document.to_value(),
            "expected_revision":previous.revision(),"change_id":change_id})
        .to_string();
        Self::from_json(&raw, previous)
    }

    /// Restore exact prepared bytes without replacing their captured CAS.
    ///
    /// # Errors
    /// Rejects malformed envelopes and requests inconsistent with the supplied base.
    pub fn from_json(raw: &str, previous: &CloudSchemaReceipt) -> Result<Self> {
        let body: ReplaceBody<'_> = parse(raw)?;
        uuid(&body.change_id)?;
        let document = ProjectSchemaDocument::from_json(body.document.get())?;
        document.validate_successor(Some(previous.document()), body.expected_revision)?;
        Ok(Self {
            raw: raw.into(),
            document,
            expected_revision: body.expected_revision,
            change_id: body.change_id,
        })
    }

    pub fn as_json(&self) -> &str {
        &self.raw
    }

    pub fn document(&self) -> &ProjectSchemaDocument {
        &self.document
    }

    pub fn expected_revision(&self) -> u32 {
        self.expected_revision
    }

    pub fn change_id(&self) -> &str {
        &self.change_id
    }

    /// Check the actual command acceptance; a newer head is never a substitute.
    ///
    /// # Errors
    /// Rejects another request's receipt or any change to accepted document content.
    pub fn require_receipt(&self, receipt: &CloudSchemaReceipt) -> Result<()> {
        if receipt.change_id() != self.change_id || !receipt.matches_document(&self.document) {
            return Err(CloudSchemaProtocolError::ReceiptMismatch);
        }
        Ok(())
    }
}

/// The server derives receipt ownership from its authenticated actor.
#[derive(Debug, Clone, Serialize)]
pub struct CloudSchemaReceiptQuery {
    schema_id: String,
    change_id: String,
}

impl CloudSchemaReceiptQuery {
    /// # Errors
    /// Rejects noncanonical or nil schema/change UUIDs.
    pub fn new(schema_id: &str, change_id: &str) -> Result<Self> {
        uuid(schema_id)?;
        uuid(change_id)?;
        Ok(Self {
            schema_id: schema_id.into(),
            change_id: change_id.into(),
        })
    }

    /// # Errors
    /// Rejects unknown fields, duplicate keys and invalid identifiers.
    pub fn from_json(raw: &str) -> Result<Self> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Body {
            schema_id: String,
            change_id: String,
        }
        let value: Body = parse(raw)?;
        Self::new(&value.schema_id, &value.change_id)
    }

    pub fn schema_id(&self) -> &str {
        &self.schema_id
    }
    pub fn change_id(&self) -> &str {
        &self.change_id
    }
}

/// A bounded history query. Decoding a noninitial page also requires its exact
/// preceding receipt, so an unverified numeric cursor cannot hide a history gap.
#[derive(Debug, Clone, Serialize)]
pub struct CloudSchemaHistoryQuery {
    schema_id: String,
    after_revision: u32,
    limit: u32,
}

impl CloudSchemaHistoryQuery {
    /// # Errors
    /// Rejects invalid UUIDs and out-of-range cursor/page limits.
    pub fn new(schema_id: &str, after_revision: u32, limit: u32) -> Result<Self> {
        uuid(schema_id)?;
        if after_revision > MAX_REVISION || !(1..=MAX_CLOUD_SCHEMA_HISTORY_ITEMS).contains(&limit) {
            return Err(CloudSchemaProtocolError::InvalidCommand);
        }
        Ok(Self {
            schema_id: schema_id.into(),
            after_revision,
            limit,
        })
    }

    /// # Errors
    /// Rejects malformed/duplicate fields and noninteger protocol tokens.
    pub fn from_json(raw: &str) -> Result<Self> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Body {
            schema_id: String,
            after_revision: u32,
            limit: u32,
        }
        let value: Body = parse(raw)?;
        Self::new(&value.schema_id, value.after_revision, value.limit)
    }

    pub fn schema_id(&self) -> &str {
        &self.schema_id
    }
    pub fn after_revision(&self) -> u32 {
        self.after_revision
    }
    pub fn limit(&self) -> u32 {
        self.limit
    }
}
