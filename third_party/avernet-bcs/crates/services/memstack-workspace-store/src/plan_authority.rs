//! Consistent Workspace Plan snapshots and atomic Plan authority transitions.

use crate::plan_records::{
    WorkspacePlanStoreError, blackboard_from_row, classify_transition_error, event_from_row,
    node_from_row, outbox_from_row, pipeline_run_from_row, plan_from_row, replay_from_rows,
    required_json, revision_i64, rows_at,
};
use crate::plan_snapshot_sql::{
    access_check, blackboard, events, nodes, outbox, pipeline_runs, plan_history, selected_plan,
};
use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep,
};
use serde_json::Value;

/// Authenticated tenant, Project, Workspace, and actor scope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspacePlanScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub actor_is_superuser: bool,
}

/// Snapshot query controls matching the legacy route.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspacePlanSnapshotQuery {
    pub scope: WorkspacePlanScope,
    pub plan_id: Option<String>,
    pub include_details: bool,
    pub outbox_limit: u64,
    pub event_limit: u64,
}

/// Persisted Workspace Plan authority row.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanRecord {
    pub plan_id: String,
    pub workspace_id: String,
    pub source_task_id: Option<String>,
    pub goal: String,
    pub goal_json: Value,
    pub status: String,
    pub revision: u64,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: String,
    pub completed_at: Option<String>,
}

/// Persisted Plan node projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanNodeRecord {
    pub node_id: String,
    pub plan_id: String,
    pub workspace_task_id: Option<String>,
    pub parent_id: Option<String>,
    pub kind: String,
    pub title: String,
    pub description: Option<String>,
    pub intent: Option<String>,
    pub status: String,
    pub sequence_number: i64,
    pub dependencies: Value,
    pub acceptance_criteria: Value,
    pub feature_checkpoint: Option<Value>,
    pub handoff_package: Option<Value>,
    pub recommended_capabilities: Value,
    pub priority: i64,
    pub progress: Value,
    pub assignee_agent_id: Option<String>,
    pub current_attempt_id: Option<String>,
    pub timeout_deadline_at: Option<String>,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: String,
    pub completed_at: Option<String>,
}

/// Persisted Plan blackboard projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanBlackboardRecord {
    pub plan_id: String,
    pub key: String,
    pub value: Value,
    pub published_by: Option<String>,
    pub version: u64,
    pub schema_ref: Option<String>,
    pub metadata: Value,
}

/// Persisted durable outbox projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanOutboxRecord {
    pub outbox_id: String,
    pub aggregate_id: String,
    pub workspace_id: String,
    pub event_type: String,
    pub payload: Value,
    pub status: String,
    pub attempt_count: u64,
    pub max_attempts: u64,
    pub lease_owner: Option<String>,
    pub lease_expires_at: Option<String>,
    pub last_error: Option<String>,
    pub next_attempt_at: Option<String>,
    pub dispatched_at: Option<String>,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: String,
}

/// Persisted Plan event projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanEventRecord {
    pub event_id: String,
    pub plan_id: String,
    pub workspace_id: String,
    pub node_id: Option<String>,
    pub attempt_id: Option<String>,
    pub event_type: String,
    pub source: String,
    pub actor_id: Option<String>,
    pub payload: Value,
    pub created_at: String,
}

/// One pipeline run with its durable metadata.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePipelineRunRecord {
    pub run_id: String,
    pub provider: String,
    pub status: String,
    pub reason: Option<String>,
    pub node_id: Option<String>,
    pub attempt_id: Option<String>,
    pub commit_ref: Option<String>,
    pub metadata: Value,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub created_at: String,
}

/// One transactionally consistent read model for the public Plan route.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanSnapshot {
    pub selected: Option<WorkspacePlanRecord>,
    pub history: Vec<WorkspacePlanRecord>,
    pub nodes: Vec<WorkspacePlanNodeRecord>,
    pub blackboard: Vec<WorkspacePlanBlackboardRecord>,
    pub outbox: Vec<WorkspacePlanOutboxRecord>,
    pub events: Vec<WorkspacePlanEventRecord>,
    pub pipeline_runs: Vec<WorkspacePipelineRunRecord>,
}

/// Subjective Agent verdict audit persisted with a successful transition.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanJudgmentAudit {
    pub audit_id: String,
    pub plan_id: String,
    pub plan_node_id: Option<String>,
    pub judgment_type: String,
    pub agent_id: String,
    pub tool_name: String,
    pub input: Value,
    pub output: Value,
    pub rationale: String,
    pub latency_ms: u64,
    pub status: String,
    pub error_detail: Option<String>,
}

/// Deterministic Plan state transitions and externally judged actions.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum WorkspacePlanTransitionKind {
    RecoverStaleAttempts,
    RetryOutbox,
    PauseIteration,
    ResumeIteration,
    TriggerNextIteration,
    RunPipeline,
    RegenerateDeliveryContract,
    RequestNodeReplan,
    ReopenNode,
    AcceptNodeReview,
}

impl WorkspacePlanTransitionKind {
    #[must_use]
    pub const fn event_type(self) -> &'static str {
        match self {
            Self::RecoverStaleAttempts => "operator_stale_attempt_recovery_requested",
            Self::RetryOutbox => "operator_retry_outbox",
            Self::PauseIteration => "operator_iteration_loop_paused",
            Self::ResumeIteration => "operator_iteration_loop_resumed",
            Self::TriggerNextIteration => "operator_iteration_next_requested",
            Self::RunPipeline => "workspace_pipeline_run_requested",
            Self::RegenerateDeliveryContract => "delivery_contract_regeneration_requested",
            Self::RequestNodeReplan => "operator_replan_requested",
            Self::ReopenNode => "operator_node_reopened",
            Self::AcceptNodeReview => "operator_review_accepted",
        }
    }
}

/// Complete state transition prepared by the application service.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanTransition {
    pub scope: WorkspacePlanScope,
    pub kind: WorkspacePlanTransitionKind,
    pub plan_id: String,
    pub expected_revision: u64,
    pub node_id: Option<String>,
    pub target_outbox_id: Option<String>,
    pub stale_node_ids: Vec<String>,
    pub idempotency_key: String,
    pub request_hash: String,
    pub mutation_outbox_id: String,
    pub event_id: String,
    pub reason: Option<String>,
    pub evidence_refs: Vec<String>,
    pub node_metadata: Option<Value>,
    pub event_payload: Value,
    pub public_response: Value,
    pub judgment: Option<WorkspacePlanJudgmentAudit>,
    pub persisted_at: String,
}

/// Committed or replayed transition result.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanTransitionOutcome {
    pub response: Value,
    pub replayed: bool,
}

/// PostgreSQL/SQLite Plan authority store.
pub struct WorkspacePlanStore<'a> {
    pub(crate) db: &'a dyn DbPlugin,
    pub(crate) flavor: DbSqlFlavor,
}

impl<'a> WorkspacePlanStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Read one transactionally consistent Plan snapshot scoped by tenant and Project.
    ///
    /// # Errors
    ///
    /// Returns access, selected-plan, row-decoding, or database errors.
    pub async fn snapshot(
        &self,
        query: &WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshot, WorkspacePlanStoreError> {
        self.snapshot_with_access(query, false).await
    }

    /// Read the action projection only after editor access is proven.
    ///
    /// # Errors
    ///
    /// Returns editor-access, selected-plan, row-decoding, or database errors.
    pub async fn action_snapshot(
        &self,
        query: &WorkspacePlanSnapshotQuery,
    ) -> Result<WorkspacePlanSnapshot, WorkspacePlanStoreError> {
        self.snapshot_with_access(query, true).await
    }

    async fn snapshot_with_access(
        &self,
        query: &WorkspacePlanSnapshotQuery,
        editor_required: bool,
    ) -> Result<WorkspacePlanSnapshot, WorkspacePlanStoreError> {
        let mut steps = Vec::with_capacity(8);
        steps.push(DbTransactionStep::query_checked(
            access_check(self.flavor, &query.scope, editor_required),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::Query(plan_history(
            self.flavor,
            &query.scope,
        )));
        steps.push(DbTransactionStep::Query(selected_plan(
            self.flavor,
            &query.scope,
            query.plan_id.as_deref(),
        )));
        if query.include_details {
            steps.push(DbTransactionStep::Query(nodes(
                self.flavor,
                &query.scope,
                query.plan_id.as_deref(),
            )));
            steps.push(DbTransactionStep::Query(blackboard(
                self.flavor,
                &query.scope,
                query.plan_id.as_deref(),
            )));
            steps.push(DbTransactionStep::Query(outbox(
                self.flavor,
                &query.scope,
                query.plan_id.as_deref(),
                query.outbox_limit,
            )));
            steps.push(DbTransactionStep::Query(events(
                self.flavor,
                &query.scope,
                query.plan_id.as_deref(),
                query.event_limit,
            )));
            steps.push(DbTransactionStep::Query(pipeline_runs(
                self.flavor,
                &query.scope,
                query.plan_id.as_deref(),
            )));
        }
        let results = self.db.transaction(steps).await.map_err(|error| {
            if matches!(error, DbError::TransactionExpectation { step_index: 0, .. }) {
                if editor_required {
                    WorkspacePlanStoreError::EditorAccessRequired
                } else {
                    WorkspacePlanStoreError::AccessDenied
                }
            } else {
                WorkspacePlanStoreError::Database(error)
            }
        })?;
        let history = rows_at(&results, 1)?
            .iter()
            .map(plan_from_row)
            .collect::<Result<Vec<_>, _>>()?;
        let selected_rows = rows_at(&results, 2)?;
        let selected = selected_rows.first().map(plan_from_row).transpose()?;
        if query.plan_id.is_some() && selected.is_none() {
            return Err(WorkspacePlanStoreError::PlanNotFound);
        }
        if !query.include_details {
            return Ok(WorkspacePlanSnapshot {
                selected,
                history,
                nodes: Vec::new(),
                blackboard: Vec::new(),
                outbox: Vec::new(),
                events: Vec::new(),
                pipeline_runs: Vec::new(),
            });
        }
        Ok(WorkspacePlanSnapshot {
            selected,
            history,
            nodes: rows_at(&results, 3)?
                .iter()
                .map(node_from_row)
                .collect::<Result<Vec<_>, _>>()?,
            blackboard: rows_at(&results, 4)?
                .iter()
                .map(blackboard_from_row)
                .collect::<Result<Vec<_>, _>>()?,
            outbox: rows_at(&results, 5)?
                .iter()
                .map(outbox_from_row)
                .collect::<Result<Vec<_>, _>>()?,
            events: rows_at(&results, 6)?
                .iter()
                .map(event_from_row)
                .collect::<Result<Vec<_>, _>>()?,
            pipeline_runs: rows_at(&results, 7)?
                .iter()
                .map(pipeline_run_from_row)
                .collect::<Result<Vec<_>, _>>()?,
        })
    }

    /// Apply Plan state, event, Judge audit, and durable outbox atomically or replay it.
    ///
    /// # Errors
    ///
    /// Returns stable access, CAS, domain, idempotency, or database errors.
    pub async fn transition(
        &self,
        transition: &WorkspacePlanTransition,
    ) -> Result<WorkspacePlanTransitionOutcome, WorkspacePlanStoreError> {
        if let Some(replay) = self.read_replay(transition).await? {
            return Ok(replay);
        }
        let mut steps = Vec::with_capacity(10);
        let access_step = steps.len();
        steps.push(DbTransactionStep::query_checked(
            access_check(self.flavor, &transition.scope, true),
            DbCountExpectation::exactly(1),
        ));
        let revision_step = steps.len();
        steps.push(DbTransactionStep::query_checked(
            self.plan_revision_check(transition),
            DbCountExpectation::exactly(1),
        ));
        let domain_start = steps.len();
        self.push_domain_steps(transition, &mut steps)?;
        let domain_end = steps.len();
        let plan_cas_step = steps.len();
        steps.push(DbTransactionStep::execute_checked(
            self.plan_cas(transition),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::execute_checked(
            self.event_insert(transition),
            DbCountExpectation::exactly(1),
        ));
        if let Some(audit) = &transition.judgment {
            steps.push(DbTransactionStep::execute_checked(
                self.audit_insert(&transition.scope, audit, &transition.persisted_at),
                DbCountExpectation::exactly(1),
            ));
        }
        let outbox_step = steps.len();
        steps.push(DbTransactionStep::execute_checked(
            self.mutation_outbox_insert(transition),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::query_checked(
            self.replay_select(&transition.scope, &transition.idempotency_key),
            DbCountExpectation::exactly(1),
        ));

        let result = self.db.transaction(steps).await;
        let results = match result {
            Ok(results) => results,
            Err(error) => {
                if (error.is_duplicate_key()
                    || matches!(
                        error,
                        DbError::TransactionExpectation { step_index, .. }
                            if step_index == outbox_step
                    ))
                    && let Some(replay) = self.read_replay(transition).await?
                {
                    return Ok(replay);
                }
                return Err(classify_transition_error(
                    error,
                    access_step,
                    revision_step,
                    domain_start,
                    domain_end,
                    plan_cas_step,
                ));
            }
        };
        replay_from_rows(
            rows_at(&results, results.len().saturating_sub(1))?,
            false,
            transition.kind.event_type(),
            &transition.request_hash,
        )
    }

    /// Persist a failed Judge call for audit without mutating Plan authority.
    ///
    /// # Errors
    ///
    /// Returns a database or conflicting-audit error.
    pub async fn record_failed_judgment(
        &self,
        scope: &WorkspacePlanScope,
        audit: &WorkspacePlanJudgmentAudit,
        persisted_at: &str,
    ) -> Result<(), WorkspacePlanStoreError> {
        let result = self
            .db
            .execute(self.audit_insert(scope, audit, persisted_at))
            .await?;
        if result.affected_rows != 1 {
            return Err(WorkspacePlanStoreError::InvalidTransition);
        }
        Ok(())
    }

    fn plan_revision_check(&self, transition: &WorkspacePlanTransition) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("SELECT plan_id FROM workspace_plans WHERE tenant_id = ")
            .bind(transition.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(transition.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(" AND plan_id = ")
            .bind(transition.plan_id.as_str())
            .push_static(" AND revision = ")
            .bind(revision_i64(transition.expected_revision))
            .build()
    }

    fn push_domain_steps(
        &self,
        transition: &WorkspacePlanTransition,
        steps: &mut Vec<DbTransactionStep>,
    ) -> Result<(), WorkspacePlanStoreError> {
        match transition.kind {
            WorkspacePlanTransitionKind::RecoverStaleAttempts => {
                if transition.stale_node_ids.is_empty() {
                    return Err(WorkspacePlanStoreError::InvalidTransition);
                }
                steps.push(DbTransactionStep::execute_checked(
                    self.recover_stale_nodes(transition),
                    DbCountExpectation::exactly(
                        u64::try_from(transition.stale_node_ids.len())
                            .map_err(|_| WorkspacePlanStoreError::InvalidTransition)?,
                    ),
                ));
            }
            WorkspacePlanTransitionKind::RetryOutbox => {
                steps.push(DbTransactionStep::execute_checked(
                    self.retry_outbox(transition)?,
                    DbCountExpectation::exactly(1),
                ));
            }
            WorkspacePlanTransitionKind::RunPipeline
            | WorkspacePlanTransitionKind::RegenerateDeliveryContract
            | WorkspacePlanTransitionKind::PauseIteration
            | WorkspacePlanTransitionKind::ResumeIteration
            | WorkspacePlanTransitionKind::TriggerNextIteration => {}
            WorkspacePlanTransitionKind::RequestNodeReplan
            | WorkspacePlanTransitionKind::ReopenNode
            | WorkspacePlanTransitionKind::AcceptNodeReview => {
                steps.push(DbTransactionStep::execute_checked(
                    self.node_transition(transition)?,
                    DbCountExpectation::exactly(1),
                ));
            }
        }
        Ok(())
    }

    fn recover_stale_nodes(&self, transition: &WorkspacePlanTransition) -> DbStatement {
        let mut builder = DbStatementBuilder::new(self.flavor)
            .push_static(
                "UPDATE workspace_plan_nodes SET status = 'pending', current_attempt_id = NULL, assignee_agent_id = NULL, timeout_deadline_at = NULL, updated_at = ",
            )
            .bind(transition.persisted_at.as_str())
            .push_static(" WHERE tenant_id = ")
            .bind(transition.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(transition.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(" AND plan_id = ")
            .bind(transition.plan_id.as_str())
            .push_static(" AND status = 'running' AND timeout_deadline_at IS NOT NULL AND timeout_deadline_at <= ")
            .bind(transition.persisted_at.as_str())
            .push_static(" AND node_id IN (");
        for (index, node_id) in transition.stale_node_ids.iter().enumerate() {
            if index > 0 {
                builder = builder.push_static(", ");
            }
            builder = builder.bind(node_id.as_str());
        }
        builder.push_static(")").build()
    }

    fn retry_outbox(
        &self,
        transition: &WorkspacePlanTransition,
    ) -> Result<DbStatement, WorkspacePlanStoreError> {
        let outbox_id = transition
            .target_outbox_id
            .as_deref()
            .ok_or(WorkspacePlanStoreError::InvalidTransition)?;
        Ok(DbStatementBuilder::new(self.flavor)
            .push_static(
                "UPDATE workspace_outbox SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL, last_error = NULL, next_attempt_at = NULL, updated_at = ",
            )
            .bind(transition.persisted_at.as_str())
            .push_static(" WHERE tenant_id = ")
            .bind(transition.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(transition.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(" AND aggregate_type = 'workspace_plan' AND aggregate_id = ")
            .bind(transition.plan_id.as_str())
            .push_static(" AND outbox_id = ")
            .bind(outbox_id)
            .push_static(
                " AND (status IN ('failed', 'dead_letter') OR (status = 'pending' AND next_attempt_at IS NOT NULL))",
            )
            .build())
    }

    fn node_transition(
        &self,
        transition: &WorkspacePlanTransition,
    ) -> Result<DbStatement, WorkspacePlanStoreError> {
        let node_id = transition
            .node_id
            .as_deref()
            .ok_or(WorkspacePlanStoreError::InvalidTransition)?;
        let mut builder =
            DbStatementBuilder::new(self.flavor).push_static("UPDATE workspace_plan_nodes SET ");
        builder = match transition.kind {
            WorkspacePlanTransitionKind::RequestNodeReplan
            | WorkspacePlanTransitionKind::ReopenNode => builder
                .push_static("status = 'pending', progress_json = ")
                .bind("{\"percent\":0}")
                .push_static(", assignee_agent_id = NULL, current_attempt_id = NULL, timeout_deadline_at = NULL, completed_at = NULL, metadata_json = ")
                .bind(required_json(&transition.node_metadata, "node_metadata")?),
            WorkspacePlanTransitionKind::AcceptNodeReview => builder
                .push_static("status = 'done', progress_json = ")
                .bind("{\"percent\":100}")
                .push_static(", assignee_agent_id = NULL, current_attempt_id = NULL, timeout_deadline_at = NULL, completed_at = ")
                .bind(transition.persisted_at.as_str())
                .push_static(", metadata_json = ")
                .bind(required_json(&transition.node_metadata, "node_metadata")?),
            _ => return Err(WorkspacePlanStoreError::InvalidTransition),
        };
        builder = builder
            .push_static(", updated_at = ")
            .bind(transition.persisted_at.as_str())
            .push_static(" WHERE tenant_id = ")
            .bind(transition.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(transition.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(" AND plan_id = ")
            .bind(transition.plan_id.as_str())
            .push_static(" AND node_id = ")
            .bind(node_id);
        builder = match transition.kind {
            WorkspacePlanTransitionKind::ReopenNode => {
                builder.push_static(" AND status = 'blocked'")
            }
            WorkspacePlanTransitionKind::AcceptNodeReview => {
                builder.push_static(" AND status <> 'done'")
            }
            WorkspacePlanTransitionKind::RequestNodeReplan => {
                builder.push_static(" AND status <> 'done'")
            }
            _ => builder,
        };
        Ok(builder.build())
    }

    fn plan_cas(&self, transition: &WorkspacePlanTransition) -> DbStatement {
        let status = match transition.kind {
            WorkspacePlanTransitionKind::PauseIteration => Some("suspended"),
            WorkspacePlanTransitionKind::ResumeIteration
            | WorkspacePlanTransitionKind::TriggerNextIteration
            | WorkspacePlanTransitionKind::RequestNodeReplan
            | WorkspacePlanTransitionKind::ReopenNode
            | WorkspacePlanTransitionKind::RecoverStaleAttempts => Some("active"),
            WorkspacePlanTransitionKind::RetryOutbox
            | WorkspacePlanTransitionKind::RunPipeline
            | WorkspacePlanTransitionKind::RegenerateDeliveryContract
            | WorkspacePlanTransitionKind::AcceptNodeReview => None,
        };
        let mut builder = DbStatementBuilder::new(self.flavor)
            .push_static("UPDATE workspace_plans SET revision = revision + 1, updated_at = ")
            .bind(transition.persisted_at.as_str());
        if let Some(status) = status {
            builder = builder.push_static(", status = ").bind(status);
        }
        builder
            .push_static(" WHERE tenant_id = ")
            .bind(transition.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(transition.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(" AND plan_id = ")
            .bind(transition.plan_id.as_str())
            .push_static(" AND revision = ")
            .bind(revision_i64(transition.expected_revision))
            .build()
    }

    fn event_insert(&self, transition: &WorkspacePlanTransition) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("INSERT INTO workspace_plan_events (event_id, tenant_id, project_id, workspace_id, plan_id, event_sequence, node_id, attempt_id, event_type, source, actor_id, payload_json, created_at) VALUES (")
            .bind(transition.event_id.as_str())
            .push_static(", ")
            .bind(transition.scope.tenant_id.as_str())
            .push_static(", ")
            .bind(transition.scope.project_id.as_str())
            .push_static(", ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(", ")
            .bind(transition.plan_id.as_str())
            .push_static(", (SELECT COALESCE(MAX(event_sequence), -1) + 1 FROM workspace_plan_events WHERE plan_id = ")
            .bind(transition.plan_id.as_str())
            .push_static("), ")
            .bind(transition.node_id.as_deref())
            .push_static(", NULL, ")
            .bind(transition.kind.event_type())
            .push_static(", 'operator', ")
            .bind(transition.scope.actor_id.as_str())
            .push_static(", ")
            .bind(transition.event_payload.to_string())
            .push_static(", ")
            .bind(transition.persisted_at.as_str())
            .push_static(")")
            .build()
    }

    fn audit_insert(
        &self,
        scope: &WorkspacePlanScope,
        audit: &WorkspacePlanJudgmentAudit,
        persisted_at: &str,
    ) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("INSERT INTO workspace_judge_audits (audit_id, tenant_id, project_id, workspace_id, plan_id, plan_node_id, judgment_type, agent_id, tool_name, input_json, output_json, rationale, latency_ms, status, error_detail, created_at) VALUES (")
            .bind(audit.audit_id.as_str())
            .push_static(", ")
            .bind(scope.tenant_id.as_str())
            .push_static(", ")
            .bind(scope.project_id.as_str())
            .push_static(", ")
            .bind(scope.workspace_id.as_str())
            .push_static(", ")
            .bind(audit.plan_id.as_str())
            .push_static(", ")
            .bind(audit.plan_node_id.as_deref())
            .push_static(", ")
            .bind(audit.judgment_type.as_str())
            .push_static(", ")
            .bind(audit.agent_id.as_str())
            .push_static(", ")
            .bind(audit.tool_name.as_str())
            .push_static(", ")
            .bind(audit.input.to_string())
            .push_static(", ")
            .bind(audit.output.to_string())
            .push_static(", ")
            .bind(audit.rationale.as_str())
            .push_static(", ")
            .bind(i64::try_from(audit.latency_ms).unwrap_or(i64::MAX))
            .push_static(", ")
            .bind(audit.status.as_str())
            .push_static(", ")
            .bind(audit.error_detail.as_deref())
            .push_static(", ")
            .bind(persisted_at)
            .push_static(")")
            .build()
    }

    fn mutation_outbox_insert(&self, transition: &WorkspacePlanTransition) -> DbStatement {
        let metadata = serde_json::json!({
            "source": "memstack-workspace-core.plan",
            "public_response": &transition.public_response,
            "expected_plan_revision": transition.expected_revision,
            "request_hash": &transition.request_hash,
        });
        DbStatementBuilder::new(self.flavor)
            .push_static("INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, correlation_id, idempotency_key, status, attempt_count, max_attempts, created_at, updated_at) VALUES (")
            .bind(transition.mutation_outbox_id.as_str())
            .push_static(", ")
            .bind(transition.scope.tenant_id.as_str())
            .push_static(", ")
            .bind(transition.scope.project_id.as_str())
            .push_static(", ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(", 'workspace_plan', ")
            .bind(transition.plan_id.as_str())
            .push_static(", ")
            .bind(transition.kind.event_type())
            .push_static(", 'workspace.events', (SELECT COALESCE(MAX(event_sequence), -1) + 1 FROM workspace_outbox WHERE workspace_id = ")
            .bind(transition.scope.workspace_id.as_str())
            .push_static(" AND stream_name = 'workspace.events'), ")
            .bind(transition.event_payload.to_string())
            .push_static(", ")
            .bind(metadata.to_string())
            .push_static(", NULL, ")
            .bind(transition.idempotency_key.as_str())
            .push_static(", 'pending', 0, 10, ")
            .bind(transition.persisted_at.as_str())
            .push_static(", ")
            .bind(transition.persisted_at.as_str())
            .push_static(")")
            .build()
    }
}
