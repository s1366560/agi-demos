use super::super::diagnostics::Cursor;
use super::*;
use agistack_core::knowledge::diagnostics::*;
impl SqliteKnowledgeRepository {
    pub fn failed_index_durable(
        &self,
        config: &DesiredEmbeddingConfig,
        request: &DiagnosticRequest,
        clock: Clock<'_>,
    ) -> KnowledgeResult<DiagnosticPage<IndexFailureDetail>> {
        timed(self, clock, |tx, _| {
            ensure_config(tx, config)?;
            let scope = &config.build.scope;
            let upper:u64=tx.query_row("SELECT COALESCE(MAX(sequence),0) FROM knowledge_processing_changes WHERE tenant_id=?1 AND project_id=?2",params![scope.tenant_id,scope.project_id],|r|r.get(0)).map_err(storage)?;
            let binding = serde_json::to_string(&(
                "failed_index",
                &scope.tenant_id,
                &scope.project_id,
                &config.build.build_id,
                config.revision,
            ))
            .map_err(storage)?;
            let cursor = Cursor::read(request, binding, upper)?;
            let mut current = current_inputs(tx, &config.build)?;
            current.sort_by_key(|input| input.identity.source.change_sequence);
            let mut items = Vec::new();
            for input in current {
                let sequence = input.identity.source.change_sequence;
                if sequence <= cursor.after || sequence > cursor.upper {
                    continue;
                }
                if let Some(status) = job(tx, &config.build, &input.identity)? {
                    if status.state == IndexJobState::Failed {
                        items.push(IndexFailureDetail {
                            input: status.input,
                            attempt: status.attempt,
                            failure: status.failure.ok_or(KnowledgeError::Conflict)?,
                        });
                        if items.len() > request.limit {
                            break;
                        }
                    }
                }
            }
            Ok((
                cursor.page(items, request.limit, |item| {
                    item.input.source.change_sequence
                })?,
                None,
            ))
        })
    }
}
