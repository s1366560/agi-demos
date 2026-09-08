//! Serialize the complete actual reply within its byte limit, before mutation commit.
use super::{KnowledgeOperationScopeV2, SchemaAction, MAX_RESPONSE_BYTES};
use agistack_adapters_device::knowledge::project_schema::{
    ProjectSchemaHistoryPage, ProjectSchemaReceipt, ProjectSchemaStorageError,
    ProjectSchemaStorageResult,
};
use serde::Serialize;
use serde_json::value::RawValue;

#[derive(Serialize)]
struct Envelope<'a, T> {
    contract_version: &'static str,
    authority: &'static str,
    operation: &'static str,
    actor_id: &'a str,
    scope: &'a KnowledgeOperationScopeV2,
    result: T,
}

struct CappedWriter {
    bytes: Vec<u8>,
    limit: usize,
}
impl std::io::Write for CappedWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        if bytes.len() > self.limit.saturating_sub(self.bytes.len()) {
            return Err(std::io::Error::other("project_schema_response_too_large"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

pub(in crate::local_runtime::knowledge_authority_v2) fn encode<T: Serialize>(
    actor: &str,
    scope: &KnowledgeOperationScopeV2,
    action: SchemaAction,
    result: T,
) -> ProjectSchemaStorageResult<Vec<u8>> {
    let mut writer = CappedWriter {
        bytes: Vec::new(),
        limit: MAX_RESPONSE_BYTES,
    };
    serde_json::to_writer(
        &mut writer,
        &Envelope {
            contract_version: "1.0.0",
            authority: "native-project-schema",
            operation: action.as_str(),
            actor_id: actor,
            scope,
            result,
        },
    )
    .map_err(|_| ProjectSchemaStorageError::ResponseTooLarge)?;
    Ok(writer.bytes)
}

pub(in crate::local_runtime::knowledge_authority_v2) fn raw(
    receipt: &ProjectSchemaReceipt,
) -> ProjectSchemaStorageResult<&RawValue> {
    serde_json::from_str(receipt.as_json()).map_err(|_| ProjectSchemaStorageError::CorruptStorage)
}

pub(in crate::local_runtime::knowledge_authority_v2) fn receipt(
    actor: &str,
    scope: &KnowledgeOperationScopeV2,
    action: SchemaAction,
    value: Option<&ProjectSchemaReceipt>,
) -> ProjectSchemaStorageResult<Vec<u8>> {
    #[derive(Serialize)]
    struct Result<'a> {
        receipt: Option<&'a RawValue>,
    }
    encode(
        actor,
        scope,
        action,
        Result {
            receipt: value.map(raw).transpose()?,
        },
    )
}

#[derive(Serialize)]
struct History<'a> {
    schema_id: &'a Option<String>,
    after_revision: u32,
    upper_revision: u32,
    next_after_revision: u32,
    has_more: bool,
    items: Vec<&'a RawValue>,
}

pub(in crate::local_runtime::knowledge_authority_v2) fn history(
    actor: &str,
    scope: &KnowledgeOperationScopeV2,
    page: &ProjectSchemaHistoryPage,
) -> ProjectSchemaStorageResult<Vec<u8>> {
    encode(
        actor,
        scope,
        SchemaAction::History,
        History {
            schema_id: &page.schema_id,
            after_revision: page.after_revision,
            upper_revision: page.upper_revision,
            next_after_revision: page.next_after_revision,
            has_more: page.has_more,
            items: page
                .items
                .iter()
                .map(raw)
                .collect::<ProjectSchemaStorageResult<_>>()?,
        },
    )
}

pub(in crate::local_runtime::knowledge_authority_v2) fn item_budget(
    actor: &str,
    scope: &KnowledgeOperationScopeV2,
    page: &ProjectSchemaHistoryPage,
) -> ProjectSchemaStorageResult<usize> {
    // Reserve upper's digit width, and false (one byte longer than true).
    let empty = encode(
        actor,
        scope,
        SchemaAction::History,
        History {
            schema_id: &page.schema_id,
            after_revision: page.after_revision,
            upper_revision: page.upper_revision,
            next_after_revision: page.upper_revision,
            has_more: false,
            items: Vec::new(),
        },
    )?;
    Ok(MAX_RESPONSE_BYTES - empty.len())
}
