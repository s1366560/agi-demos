use serde::{
    de::{Error, SeqAccess, Visitor},
    Deserialize, Deserializer,
};
use serde_json::value::RawValue;
use std::fmt;

use super::{
    parse, CloudSchemaHistoryQuery, CloudSchemaProtocolError, CloudSchemaReceipt, Result,
    MAX_CLOUD_SCHEMA_HISTORY_ITEMS,
};
use crate::project_schema::MAX_REVISION;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HistoryBody {
    schema_id: String,
    upper_revision: u32,
    next_after_revision: u32,
    has_more: bool,
    #[serde(deserialize_with = "bounded_receipts")]
    receipts: Vec<Box<RawValue>>,
}

fn bounded_receipts<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> std::result::Result<Vec<Box<RawValue>>, D::Error> {
    struct Receipts;
    impl<'de> Visitor<'de> for Receipts {
        type Value = Vec<Box<RawValue>>;
        fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
            formatter.write_str("at most 100 exact cloud receipts")
        }
        fn visit_seq<A: SeqAccess<'de>>(
            self,
            mut seq: A,
        ) -> std::result::Result<Self::Value, A::Error> {
            let mut result = Vec::new();
            while let Some(item) = seq.next_element::<Box<RawValue>>()? {
                if result.len() >= MAX_CLOUD_SCHEMA_HISTORY_ITEMS as usize {
                    return Err(A::Error::custom("too many cloud receipts"));
                }
                result.push(item);
            }
            Ok(result)
        }
    }
    deserializer.deserialize_seq(Receipts)
}

/// One complete bounded prefix from a single remote history observation.
#[derive(Debug)]
pub struct CloudSchemaHistoryPage {
    schema_id: String,
    upper_revision: u32,
    next_after_revision: u32,
    has_more: bool,
    receipts: Vec<CloudSchemaReceipt>,
}

impl CloudSchemaHistoryPage {
    /// # Errors
    /// Rejects wrong scope/identity, gaps, reordered receipts, changed tombstones
    /// and cursors or terminal states inconsistent with the observed history.
    pub fn from_json(
        raw: &str,
        tenant: &str,
        project: &str,
        query: &CloudSchemaHistoryQuery,
        previous: Option<&CloudSchemaReceipt>,
    ) -> Result<Self> {
        Self::require_previous(tenant, project, query, previous)?;
        let body: HistoryBody = parse(raw)?;
        let next = query
            .after_revision()
            .checked_add(body.receipts.len() as u32)
            .ok_or(CloudSchemaProtocolError::InvalidHistory)?;
        if body.schema_id != query.schema_id()
            || !(1..=MAX_REVISION).contains(&body.upper_revision)
            || next > body.upper_revision
            || body.next_after_revision != next
            || body.has_more != (next < body.upper_revision)
            || body.receipts.len() > query.limit() as usize
            || (body.has_more && body.receipts.is_empty())
            || previous.is_some_and(|receipt| {
                receipt.document().is_deleted() && next != body.upper_revision
            })
        {
            return Err(CloudSchemaProtocolError::InvalidHistory);
        }
        let mut receipts: Vec<CloudSchemaReceipt> = Vec::new();
        for raw in body.receipts {
            let receipt = CloudSchemaReceipt::from_json(raw.get(), tenant, project)?;
            let predecessor = receipts.last().or(previous);
            receipt.document().validate_successor(
                predecessor.map(CloudSchemaReceipt::document),
                predecessor.map_or(0, CloudSchemaReceipt::revision),
            )?;
            if receipt.document().schema_id() != query.schema_id()
                || (receipt.document().is_deleted() && receipt.revision() != body.upper_revision)
            {
                return Err(CloudSchemaProtocolError::InvalidHistory);
            }
            receipts.push(receipt);
        }
        Ok(Self {
            schema_id: body.schema_id,
            upper_revision: body.upper_revision,
            next_after_revision: next,
            has_more: body.has_more,
            receipts,
        })
    }

    /// Validate a requested cursor before any transport is attempted.
    ///
    /// # Errors
    /// Rejects missing or unrelated predecessor receipts.
    pub fn require_previous(
        tenant: &str,
        project: &str,
        query: &CloudSchemaHistoryQuery,
        previous: Option<&CloudSchemaReceipt>,
    ) -> Result<()> {
        match previous {
            None if query.after_revision() == 0 => Ok(()),
            Some(receipt)
                if receipt.revision() == query.after_revision()
                    && receipt.document().schema_id() == query.schema_id()
                    && receipt.document().tenant_id() == tenant
                    && receipt.document().project_id() == project =>
            {
                Ok(())
            }
            _ => Err(CloudSchemaProtocolError::InvalidHistory),
        }
    }

    pub fn schema_id(&self) -> &str {
        &self.schema_id
    }
    pub fn upper_revision(&self) -> u32 {
        self.upper_revision
    }
    pub fn next_after_revision(&self) -> u32 {
        self.next_after_revision
    }
    pub fn has_more(&self) -> bool {
        self.has_more
    }
    pub fn receipts(&self) -> &[CloudSchemaReceipt] {
        &self.receipts
    }
}
