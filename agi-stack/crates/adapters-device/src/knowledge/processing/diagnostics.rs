use super::super::diagnostics::Cursor;
use super::*;
use agistack_core::knowledge::diagnostics::*;
use agistack_core::knowledge::processing::audit::*;

impl SqliteKnowledgeRepository {
    pub fn processing_task_durable(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<ProcessingTaskSnapshot> {
        validate_source(scope, source)?;
        transact_timed(self, clock, |tx, _| {
            let current = current_source(tx, source)?;
            let task = if current {
                let (state, attempt, failure): (String, u32, Option<String>) = tx
                    .query_row(
                        "SELECT state,attempt,failure_json FROM knowledge_processing_jobs
                     WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3
                       AND revision=?4 AND change_sequence=?5",
                        params![
                            scope.tenant_id,
                            scope.project_id,
                            source.memory_id,
                            source.revision,
                            source.change_sequence
                        ],
                        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                    )
                    .map_err(storage)?;
                Some(ProcessingTask {
                    state: serde_json::from_value(serde_json::Value::String(state))
                        .map_err(storage)?,
                    attempt,
                    failure: failure
                        .map(|value| serde_json::from_str(&value).map_err(storage))
                        .transpose()?,
                })
            } else {
                None
            };
            Ok((
                ProcessingTaskSnapshot {
                    source: source.clone(),
                    current,
                    task,
                },
                None,
            ))
        })
    }
    pub fn failed_processing_durable(
        &self,
        scope: &KnowledgeScope,
        request: &DiagnosticRequest,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<DiagnosticPage<ProcessingFailureDetail>> {
        validate(scope, "processing-diagnostics")?;
        transact_timed(self, clock, |tx, _| {
            let upper:u64=tx.query_row("SELECT COALESCE(MAX(sequence),0) FROM knowledge_processing_changes WHERE tenant_id=?1 AND project_id=?2",params![scope.tenant_id,scope.project_id],|r|r.get(0)).map_err(storage)?;
            let binding =
                serde_json::to_string(&("failed_processing", &scope.tenant_id, &scope.project_id))
                    .map_err(storage)?;
            let cursor = Cursor::read(request, binding, upper)?;
            let mut statement=tx.prepare("SELECT j.memory_id,j.revision,j.change_sequence,j.attempt,j.failure_json FROM knowledge_processing_jobs j
                JOIN knowledge_processing_changes c ON c.sequence=j.change_sequence AND c.tenant_id=j.tenant_id AND c.project_id=j.project_id AND c.memory_id=j.memory_id AND c.revision=j.revision AND c.operation='upsert'
                JOIN knowledge_memories m ON m.tenant_id=j.tenant_id AND m.project_id=j.project_id AND m.id=j.memory_id AND m.revision=j.revision AND m.payload=c.payload AND m.deleted=0
                WHERE j.tenant_id=?1 AND j.project_id=?2 AND j.state='failed' AND j.change_sequence>?3 AND j.change_sequence<=?4 ORDER BY j.change_sequence LIMIT ?5").map_err(storage)?;
            let rows = statement
                .query_map(
                    params![
                        scope.tenant_id,
                        scope.project_id,
                        cursor.after,
                        cursor.upper,
                        request.limit + 1
                    ],
                    |r| {
                        Ok((
                            r.get::<_, String>(0)?,
                            r.get::<_, u32>(1)?,
                            r.get::<_, u64>(2)?,
                            r.get::<_, u32>(3)?,
                            r.get::<_, String>(4)?,
                        ))
                    },
                )
                .map_err(storage)?;
            let items = rows
                .map(|row| {
                    let (memory_id, revision, change_sequence, attempt, failure) =
                        row.map_err(storage)?;
                    Ok(ProcessingFailureDetail {
                        source: ProcessingSource {
                            tenant_id: scope.tenant_id.clone(),
                            project_id: scope.project_id.clone(),
                            memory_id,
                            revision,
                            change_sequence,
                        },
                        attempt,
                        failure: serde_json::from_str(&failure).map_err(storage)?,
                    })
                })
                .collect::<KnowledgeResult<Vec<_>>>()?;
            Ok((
                cursor.page(items, request.limit, |item| item.source.change_sequence)?,
                None,
            ))
        })
    }
    pub fn processing_audit_summaries_durable(
        &self,
        scope: &KnowledgeScope,
        source: &ProcessingSource,
        request: &DiagnosticRequest,
        clock: &dyn Fn() -> KnowledgeResult<i64>,
    ) -> KnowledgeResult<DiagnosticPage<AuditSummary>> {
        validate_source(scope, source)?;
        transact_timed(self, clock, |tx, _| {
            if !current_source(tx, source)? {
                return Err(KnowledgeError::Conflict);
            }
            let upper:u64=tx.query_row("SELECT COALESCE(MAX(attempt),0) FROM knowledge_processing_audits WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND revision=?4 AND change_sequence=?5",params![scope.tenant_id,scope.project_id,source.memory_id,source.revision,source.change_sequence],|r|r.get(0)).map_err(storage)?;
            let binding = serde_json::to_string(&("processing_audits", source)).map_err(storage)?;
            let cursor = Cursor::read(request, binding, upper)?;
            let mut statement=tx.prepare("SELECT attempt,invocation_json,started_at_ms,finished_at_ms,latency_ms,outcome_json FROM knowledge_processing_audits WHERE tenant_id=?1 AND project_id=?2 AND memory_id=?3 AND revision=?4 AND change_sequence=?5 AND attempt>?6 AND attempt<=?7 ORDER BY attempt LIMIT ?8").map_err(storage)?;
            let rows = statement
                .query_map(
                    params![
                        scope.tenant_id,
                        scope.project_id,
                        source.memory_id,
                        source.revision,
                        source.change_sequence,
                        cursor.after,
                        cursor.upper,
                        request.limit + 1
                    ],
                    |r| {
                        Ok((
                            r.get::<_, u32>(0)?,
                            r.get::<_, String>(1)?,
                            r.get::<_, i64>(2)?,
                            r.get::<_, Option<i64>>(3)?,
                            r.get::<_, Option<u64>>(4)?,
                            r.get::<_, Option<String>>(5)?,
                        ))
                    },
                )
                .map_err(storage)?;
            let items = rows
                .map(|row| {
                    let (attempt, invocation, started_at_ms, finished_at_ms, latency_ms, outcome) =
                        row.map_err(storage)?;
                    let invocation: ProcessingInvocation =
                        serde_json::from_str(&invocation).map_err(storage)?;
                    let outcome: Option<ProcessingAuditOutcome> = outcome
                        .map(|text| serde_json::from_str(&text).map_err(storage))
                        .transpose()?;
                    let (status, failure) = match outcome {
                        None => (AuditStatus::Running, None),
                        Some(ProcessingAuditOutcome::Applied { .. }) => {
                            (AuditStatus::Applied, None)
                        }
                        Some(ProcessingAuditOutcome::Failed { code, .. }) => {
                            (AuditStatus::Failed, Some(code))
                        }
                    };
                    Ok(AuditSummary {
                        source: source.clone(),
                        attempt,
                        agent_id: invocation.agent_id,
                        provider_id: invocation.provider_id,
                        model_id: invocation.model_id,
                        tool_name: invocation.tool_name,
                        contract_version: invocation.contract_version,
                        started_at_ms,
                        finished_at_ms,
                        latency_ms,
                        status,
                        failure,
                    })
                })
                .collect::<KnowledgeResult<Vec<_>>>()?;
            Ok((
                cursor.page(items, request.limit, |item| u64::from(item.attempt))?,
                None,
            ))
        })
    }
}
