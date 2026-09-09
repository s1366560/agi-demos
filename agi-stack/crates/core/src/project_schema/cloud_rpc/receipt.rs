use serde::Deserialize;
use serde_json::value::RawValue;

use super::{
    parse, scoped_document, uuid, CloudSchemaProtocolError, ProjectSchemaDocument, Result,
};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReceiptBody<'a> {
    schema_id: String,
    revision: u32,
    sequence: u32,
    change_id: String,
    #[serde(borrow)]
    document: &'a RawValue,
}

/// Validated cloud acceptance retaining its exact JSON, including opaque values.
/// Actor ownership is established by authenticated transport/receipt lookup, not
/// by inventing an actor field for a history receipt that has none on the wire.
#[derive(Debug, Clone, PartialEq)]
pub struct CloudSchemaReceipt {
    raw: String,
    change_id: String,
    document: ProjectSchemaDocument,
}

impl CloudSchemaReceipt {
    /// Decode a receipt for one already selected remote scope.
    ///
    /// # Errors
    /// Rejects malformed/oversize JSON, wrong scope and inconsistent receipt identity.
    pub fn from_json(raw: &str, tenant: &str, project: &str) -> Result<Self> {
        let body: ReceiptBody<'_> = parse(raw)?;
        uuid(&body.change_id)?;
        let document = scoped_document(body.document.get(), tenant, project)?;
        if body.schema_id != document.schema_id()
            || body.revision != document.revision()
            || body.sequence != body.revision
        {
            return Err(CloudSchemaProtocolError::ReceiptMismatch);
        }
        Ok(Self {
            raw: raw.into(),
            change_id: body.change_id,
            document,
        })
    }

    pub fn as_json(&self) -> &str {
        &self.raw
    }

    pub fn change_id(&self) -> &str {
        &self.change_id
    }

    pub fn document(&self) -> &ProjectSchemaDocument {
        &self.document
    }

    pub fn revision(&self) -> u32 {
        self.document.revision()
    }

    /// Cloud storage sorts member arrays by UUID when accepting a command.
    /// Compare that structural canonicalization without changing request bytes,
    /// coercing opaque schema values or interpreting their meaning.
    pub fn matches_document(&self, document: &ProjectSchemaDocument) -> bool {
        canonical(&self.document) == canonical(document)
    }
}

fn canonical(document: &ProjectSchemaDocument) -> ProjectSchemaDocument {
    let mut result = document.clone();
    result.raw.entity_types.sort_by(|a, b| a.id.cmp(&b.id));
    result.raw.edge_types.sort_by(|a, b| a.id.cmp(&b.id));
    result.raw.mappings.sort_by(|a, b| a.id.cmp(&b.id));
    result.raw.tombstones.sort_by(|a, b| a.id.cmp(&b.id));
    result
}
