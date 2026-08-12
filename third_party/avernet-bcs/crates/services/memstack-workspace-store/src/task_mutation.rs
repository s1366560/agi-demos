//! Ordered receipt, revision-CAS, domain-write, and outbox Task transaction.

use bcs_db_api::{
    DbCountExpectation, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStep,
};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::task::{required_json_object, required_string};
use crate::{
    WorkspaceTaskAuxiliaryWrite, WorkspaceTaskDomainWrite, WorkspaceTaskMutation,
    WorkspaceTaskMutationOutcome, WorkspaceTaskRecord, WorkspaceTaskStoreError,
};

pub(super) fn mutation_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTaskMutation,
) -> Result<Vec<DbTransactionStep>, WorkspaceTaskStoreError> {
    let committed_revision = mutation
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceTaskStoreError::Conflict)?;
    let receipt_id = deterministic_id("task-receipt", mutation);
    let outbox_id = deterministic_id("task-outbox", mutation);
    let mut steps = Vec::with_capacity(8 + mutation.auxiliary_writes.len());
    steps.push(DbTransactionStep::query_checked(
        access_check(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        receipt_insert(flavor, mutation, &receipt_id),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::query_checked(
        revision_check(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        domain_statement(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    for auxiliary in &mutation.auxiliary_writes {
        steps.push(DbTransactionStep::execute_checked(
            auxiliary_statement(flavor, mutation, auxiliary),
            DbCountExpectation::exactly(1),
        ));
    }
    steps.push(DbTransactionStep::execute_checked(
        authority_cas(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        outbox_insert(flavor, mutation, &outbox_id, committed_revision),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        receipt_finalize(
            flavor,
            mutation,
            &receipt_id,
            &outbox_id,
            committed_revision,
        ),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::query_checked(
        receipt_lookup(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    Ok(steps)
}

fn access_check(flavor: DbSqlFlavor, mutation: &WorkspaceTaskMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT p.workspace_id FROM workspace_profiles p \
             JOIN workspace_members m ON m.tenant_id = p.tenant_id \
              AND m.project_id = p.project_id AND m.workspace_id = p.workspace_id \
             WHERE p.tenant_id = ",
        )
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND p.deleted_at IS NULL AND m.user_id = ")
        .bind(mutation.actor_id.as_str())
        .push_static(" AND m.role IN ('owner', 'editor', 'admin')")
        .build()
}

pub(super) fn receipt_lookup(flavor: DbSqlFlavor, mutation: &WorkspaceTaskMutation) -> DbStatement {
    if mutation.receipt_authority.is_some() {
        return DbStatementBuilder::new(flavor)
            .push_static(
                "SELECT request_hash AS payload_hash, committed_revision, response_json AS \
                 result_json FROM workspace_mutation_receipts WHERE tenant_id = ",
            )
            .bind(mutation.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(mutation.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(mutation.scope.workspace_id.as_str())
            .push_static(" AND actor_id = ")
            .bind(mutation.actor_id.as_str())
            .push_static(" AND idempotency_key = ")
            .bind(mutation.idempotency_key.as_str())
            .build();
    }
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT payload_hash, committed_revision, result_json FROM workspace_task_receipts \
             WHERE tenant_id = ",
        )
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND actor_id = ")
        .bind(mutation.actor_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(mutation.idempotency_key.as_str())
        .build()
}

fn receipt_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTaskMutation,
    receipt_id: &str,
) -> DbStatement {
    if let Some(authority) = &mutation.receipt_authority {
        let builder = DbStatementBuilder::new(flavor)
            .push_static(
                "INSERT INTO workspace_mutation_receipts \
                 (receipt_id, tenant_id, project_id, workspace_id, actor_id, contract_version, \
                  surface, action, idempotency_key, request_hash, expected_revision) VALUES (",
            )
            .bind(receipt_id)
            .push_static(", ")
            .bind(mutation.scope.tenant_id.as_str())
            .push_static(", ")
            .bind(mutation.scope.project_id.as_str())
            .push_static(", ")
            .bind(mutation.scope.workspace_id.as_str())
            .push_static(", ")
            .bind(mutation.actor_id.as_str())
            .push_static(", ")
            .bind(authority.contract_version().as_str())
            .push_static(", ")
            .bind(authority.surface().as_str())
            .push_static(", ")
            .bind(authority.action().as_str())
            .push_static(", ")
            .bind(mutation.idempotency_key.as_str())
            .push_static(", ")
            .bind(mutation.payload_hash.as_str())
            .push_static(", ")
            .bind(mutation.expected_revision)
            .push_static(")");
        return match flavor {
            DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
                .push_static(" ON CONFLICT(workspace_id, actor_id, idempotency_key) DO NOTHING")
                .build(),
            DbSqlFlavor::Mysql => builder.build(),
        };
    }
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_task_receipts \
             (receipt_id, tenant_id, project_id, workspace_id, task_id, actor_id, action, \
              idempotency_key, payload_hash, expected_revision) VALUES (",
        )
        .bind(receipt_id)
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(mutation.task_id.as_str())
        .push_static(", ")
        .bind(mutation.actor_id.as_str())
        .push_static(", ")
        .bind(mutation.action.as_str())
        .push_static(", ")
        .bind(mutation.idempotency_key.as_str())
        .push_static(", ")
        .bind(mutation.payload_hash.as_str())
        .push_static(", ")
        .bind(mutation.expected_revision)
        .push_static(")");
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(workspace_id, actor_id, idempotency_key) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn revision_check(flavor: DbSqlFlavor, mutation: &WorkspaceTaskMutation) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(mutation.expected_revision);
    if flavor == DbSqlFlavor::Postgres {
        builder.push_static(" FOR UPDATE").build()
    } else {
        builder.build()
    }
}

fn domain_statement(flavor: DbSqlFlavor, mutation: &WorkspaceTaskMutation) -> DbStatement {
    match &mutation.domain_write {
        WorkspaceTaskDomainWrite::Create(task) => insert_task(flavor, task),
        WorkspaceTaskDomainWrite::Update(task) => update_task(flavor, task),
        WorkspaceTaskDomainWrite::Delete { task_id } => DbStatementBuilder::new(flavor)
            .push_static("DELETE FROM workspace_tasks WHERE tenant_id = ")
            .bind(mutation.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(mutation.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(mutation.scope.workspace_id.as_str())
            .push_static(" AND task_id = ")
            .bind(task_id.as_str())
            .build(),
    }
}

fn insert_task(flavor: DbSqlFlavor, task: &WorkspaceTaskRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_tasks \
             (task_id, tenant_id, project_id, workspace_id, title, description, created_by, \
              assignee_user_id, assignee_agent_id, status, priority, estimated_effort, \
              blocker_reason, metadata_json, created_at, updated_at, completed_at, archived_at) \
             VALUES (",
        )
        .bind(task.task_id.as_str())
        .push_static(", ")
        .bind(task.tenant_id.as_str())
        .push_static(", ")
        .bind(task.project_id.as_str())
        .push_static(", ")
        .bind(task.workspace_id.as_str())
        .push_static(", ")
        .bind(task.title.as_str())
        .push_static(", ")
        .bind(task.description.clone())
        .push_static(", ")
        .bind(task.created_by.as_str())
        .push_static(", ")
        .bind(task.assignee_user_id.clone())
        .push_static(", ")
        .bind(task.assignee_agent_id.clone())
        .push_static(", ")
        .bind(task.status.as_str())
        .push_static(", ")
        .bind(task.priority)
        .push_static(", ")
        .bind(task.estimated_effort.clone())
        .push_static(", ")
        .bind(task.blocker_reason.clone())
        .push_static(", ")
        .bind(task.metadata.to_string())
        .push_static(", ")
        .bind(task.created_at.as_str())
        .push_static(", ")
        .bind(task.updated_at.clone())
        .push_static(", ")
        .bind(task.completed_at.clone())
        .push_static(", ")
        .bind(task.archived_at.clone())
        .push_static(")")
        .build()
}

fn update_task(flavor: DbSqlFlavor, task: &WorkspaceTaskRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_tasks SET title = ")
        .bind(task.title.as_str())
        .push_static(", description = ")
        .bind(task.description.clone())
        .push_static(", assignee_user_id = ")
        .bind(task.assignee_user_id.clone())
        .push_static(", assignee_agent_id = ")
        .bind(task.assignee_agent_id.clone())
        .push_static(", status = ")
        .bind(task.status.as_str())
        .push_static(", priority = ")
        .bind(task.priority)
        .push_static(", estimated_effort = ")
        .bind(task.estimated_effort.clone())
        .push_static(", blocker_reason = ")
        .bind(task.blocker_reason.clone())
        .push_static(", metadata_json = ")
        .bind(task.metadata.to_string())
        .push_static(", updated_at = ")
        .bind(task.updated_at.clone())
        .push_static(", completed_at = ")
        .bind(task.completed_at.clone())
        .push_static(", archived_at = ")
        .bind(task.archived_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(task.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(task.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(task.workspace_id.as_str())
        .push_static(" AND task_id = ")
        .bind(task.task_id.as_str())
        .build()
}

fn auxiliary_statement(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTaskMutation,
    auxiliary: &WorkspaceTaskAuxiliaryWrite,
) -> DbStatement {
    match auxiliary {
        WorkspaceTaskAuxiliaryWrite::CreateAttempt(attempt) => DbStatementBuilder::new(flavor)
            .push_static(
                "INSERT INTO workspace_task_attempts \
                     (attempt_id, tenant_id, project_id, workspace_id, task_id, \
                      root_goal_task_id, attempt_number, status, conversation_id, \
                      worker_agent_id, leader_agent_id, candidate_summary, \
                      candidate_artifacts_json, candidate_verifications_json, \
                      leader_feedback, adjudication_reason, created_at, updated_at, completed_at) \
                     SELECT ",
            )
            .bind(attempt.attempt_id.as_str())
            .push_static(", tenant_id, project_id, workspace_id, task_id, ")
            .bind(attempt.root_goal_task_id.as_str())
            .push_static(", ")
            .bind(attempt.attempt_number)
            .push_static(", ")
            .bind(attempt.status.as_str())
            .push_static(", ")
            .bind(attempt.conversation_id.clone())
            .push_static(", ")
            .bind(attempt.worker_agent_id.clone())
            .push_static(", ")
            .bind(attempt.leader_agent_id.clone())
            .push_static(", ")
            .bind(attempt.candidate_summary.clone())
            .push_static(", ")
            .bind(attempt.candidate_artifacts.to_string())
            .push_static(", ")
            .bind(attempt.candidate_verifications.to_string())
            .push_static(", ")
            .bind(attempt.leader_feedback.clone())
            .push_static(", ")
            .bind(attempt.adjudication_reason.clone())
            .push_static(", ")
            .bind(attempt.created_at.as_str())
            .push_static(", ")
            .bind(attempt.updated_at.clone())
            .push_static(", ")
            .bind(attempt.completed_at.clone())
            .push_static(" FROM workspace_tasks WHERE task_id = ")
            .bind(attempt.task_id.as_str())
            .build(),
        WorkspaceTaskAuxiliaryWrite::QueueDispatch(dispatch) => dispatch.insert_statement(flavor),
        WorkspaceTaskAuxiliaryWrite::CreateObjectiveProjection(projection) => {
            let committed_revision = mutation.expected_revision.saturating_add(1);
            let outbox_id = deterministic_id("task-outbox", mutation);
            DbStatementBuilder::new(flavor)
                .push_static(
                    "INSERT INTO workspace_objective_task_projections \
                     (projection_id, tenant_id, project_id, workspace_id, objective_id, \
                      task_id, created_by_actor_id, committed_revision, outbox_id, created_at) \
                     SELECT ",
                )
                .bind(projection.projection_id.as_str())
                .push_static(", tenant_id, project_id, workspace_id, ")
                .bind(projection.objective_id.as_str())
                .push_static(", ")
                .bind(projection.task_id.as_str())
                .push_static(", ")
                .bind(projection.actor_id.as_str())
                .push_static(", ")
                .bind(committed_revision)
                .push_static(", ")
                .bind(outbox_id)
                .push_static(", ")
                .bind(projection.created_at.as_str())
                .push_static(" FROM workspace_objectives WHERE tenant_id = ")
                .bind(mutation.scope.tenant_id.as_str())
                .push_static(" AND project_id = ")
                .bind(mutation.scope.project_id.as_str())
                .push_static(" AND workspace_id = ")
                .bind(mutation.scope.workspace_id.as_str())
                .push_static(" AND objective_id = ")
                .bind(projection.objective_id.as_str())
                .build()
        }
    }
}

fn authority_cas(flavor: DbSqlFlavor, mutation: &WorkspaceTaskMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_authorities SET revision = revision + 1, updated_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE tenant_id = ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(mutation.expected_revision)
        .build()
}

fn outbox_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTaskMutation,
    outbox_id: &str,
    committed_revision: u64,
) -> DbStatement {
    let (receipt_action, receipt_surface, contract_version) = mutation
        .receipt_authority
        .as_ref()
        .map_or((mutation.action.as_str(), "tasks", "v1"), |authority| {
            (
                authority.action().as_str(),
                authority.surface().as_str(),
                authority.contract_version().as_str(),
            )
        });
    let metadata = serde_json::json!({
        "action": receipt_action,
        "contract_version": contract_version,
        "request_hash": &mutation.payload_hash,
        "task_id": &mutation.task_id,
        "surface": receipt_surface,
    });
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_outbox \
             (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, \
              event_type, stream_name, event_sequence, payload_json, metadata_json, \
              correlation_id, idempotency_key) VALUES (",
        )
        .bind(outbox_id)
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", 'workspace_task', ")
        .bind(mutation.task_id.as_str())
        .push_static(", ")
        .bind(mutation.event_type.as_str())
        .push_static(", ")
        .bind(format!("workspace:{}", mutation.scope.workspace_id))
        .push_static(", ")
        .bind(committed_revision)
        .push_static(", ")
        .bind(mutation.event_payload.to_string())
        .push_static(", ")
        .bind(metadata.to_string())
        .push_static(", ")
        .bind(outbox_id)
        .push_static(", ")
        .bind(mutation.idempotency_key.as_str())
        .push_static(")")
        .build()
}

fn receipt_finalize(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceTaskMutation,
    receipt_id: &str,
    outbox_id: &str,
    committed_revision: u64,
) -> DbStatement {
    let result = serde_json::json!({
        "response": &mutation.response,
        "outbox_id": outbox_id,
    });
    let table = if mutation.receipt_authority.is_some() {
        "UPDATE workspace_mutation_receipts SET committed_revision = "
    } else {
        "UPDATE workspace_task_receipts SET committed_revision = "
    };
    let result_column = if mutation.receipt_authority.is_some() {
        ", response_json = "
    } else {
        ", result_json = "
    };
    let hash_column = if mutation.receipt_authority.is_some() {
        " AND request_hash = "
    } else {
        " AND payload_hash = "
    };
    DbStatementBuilder::new(flavor)
        .push_static(table)
        .bind(committed_revision)
        .push_static(result_column)
        .bind(result.to_string())
        .push_static(", committed_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE receipt_id = ")
        .bind(receipt_id)
        .push_static(hash_column)
        .bind(mutation.payload_hash.as_str())
        .push_static(" AND committed_revision IS NULL")
        .build()
}

pub(super) fn receipt_outcome(
    mutation: &WorkspaceTaskMutation,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceTaskMutationOutcome>, WorkspaceTaskStoreError> {
    let payload_hash = required_string(row, "payload_hash")?;
    if payload_hash != mutation.payload_hash {
        return Err(WorkspaceTaskStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Err(WorkspaceTaskStoreError::IncompleteReceipt);
    };
    let committed_revision = u64::try_from(committed_revision)
        .map_err(|_| WorkspaceTaskStoreError::InvalidRecord("committed_revision"))?;
    let result = required_json_object(row, "result_json")?;
    let response =
        result
            .get("response")
            .cloned()
            .ok_or(WorkspaceTaskStoreError::InvalidRecord(
                "result_json.response",
            ))?;
    let outbox_id = result
        .get("outbox_id")
        .and_then(Value::as_str)
        .ok_or(WorkspaceTaskStoreError::InvalidRecord(
            "result_json.outbox_id",
        ))?
        .to_string();
    Ok(Some(WorkspaceTaskMutationOutcome {
        committed_revision,
        response,
        outbox_id,
        replayed,
    }))
}

fn deterministic_id(namespace: &str, mutation: &WorkspaceTaskMutation) -> String {
    let mut digest = Sha256::new();
    let (surface, action) = mutation
        .receipt_authority
        .as_ref()
        .map_or(("tasks", mutation.action.as_str()), |authority| {
            (authority.surface().as_str(), authority.action().as_str())
        });
    for part in [
        namespace,
        mutation.scope.tenant_id.as_str(),
        mutation.scope.project_id.as_str(),
        mutation.scope.workspace_id.as_str(),
        mutation.actor_id.as_str(),
        surface,
        action,
        mutation.idempotency_key.as_str(),
        mutation.payload_hash.as_str(),
    ] {
        digest.update(u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{namespace}-{}", hex::encode(digest.finalize()))
}
