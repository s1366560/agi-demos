//! Receipt, revision-CAS, blackboard write, and durable outbox transaction.

use std::ops::Range;

use bcs_db_api::{
    DbCountExpectation, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStep,
};
use serde_json::json;
use sha2::{Digest, Sha256};

use crate::blackboard::{required_json_object, required_string};
use crate::{
    WorkspaceBlackboardDomainWrite, WorkspaceBlackboardMutation,
    WorkspaceBlackboardMutationOutcome, WorkspaceBlackboardPostRecord,
    WorkspaceBlackboardReplyRecord, WorkspaceBlackboardScope, WorkspaceBlackboardStoreError,
};

pub(super) fn mutation_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceBlackboardMutation,
) -> Result<(Vec<DbTransactionStep>, Range<usize>), WorkspaceBlackboardStoreError> {
    let committed_revision = mutation
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceBlackboardStoreError::Conflict)?;
    let receipt_id = deterministic_id("blackboard-receipt", mutation);
    let outbox_id = deterministic_id("blackboard-outbox", mutation);
    let domain = domain_step(flavor, mutation);
    let domain_range = 3..4;
    let steps = vec![
        DbTransactionStep::query_checked(
            access_check(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            receipt_insert(flavor, mutation, receipt_id.as_str()),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            revision_check(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(domain, DbCountExpectation::exactly(1)),
        DbTransactionStep::execute_checked(
            authority_cas(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            outbox_insert(
                flavor,
                mutation,
                outbox_id.as_str(),
                committed_revision,
                receipt_id.as_str(),
            ),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            receipt_finalize(flavor, mutation, receipt_id.as_str(), committed_revision),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            receipt_lookup(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
    ];
    Ok((steps, domain_range))
}

fn access_check(flavor: DbSqlFlavor, mutation: &WorkspaceBlackboardMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT p.workspace_id FROM workspace_profiles p JOIN workspace_members m \
             ON m.tenant_id = p.tenant_id AND m.project_id = p.project_id \
             AND m.workspace_id = p.workspace_id WHERE p.tenant_id = ",
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

pub(super) fn receipt_lookup(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceBlackboardMutation,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT request_hash, committed_revision, response_json FROM \
             workspace_mutation_receipts WHERE tenant_id = ",
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
    mutation: &WorkspaceBlackboardMutation,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, surface, action) = mutation.receipt_authority.as_ref().map_or(
        ("v1", "blackboard", mutation.action.as_str()),
        |authority| {
            (
                authority.contract_version().as_str(),
                authority.surface().as_str(),
                authority.action().as_str(),
            )
        },
    );
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_mutation_receipts (receipt_id, tenant_id, project_id, \
             workspace_id, actor_id, contract_version, surface, action, idempotency_key, \
             request_hash, expected_revision) VALUES (",
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
        .bind(contract_version)
        .push_static(", ")
        .bind(surface)
        .push_static(", ")
        .bind(action)
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

fn revision_check(flavor: DbSqlFlavor, mutation: &WorkspaceBlackboardMutation) -> DbStatement {
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

fn authority_cas(flavor: DbSqlFlavor, mutation: &WorkspaceBlackboardMutation) -> DbStatement {
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

fn domain_step(flavor: DbSqlFlavor, mutation: &WorkspaceBlackboardMutation) -> DbStatement {
    match &mutation.domain_write {
        WorkspaceBlackboardDomainWrite::CreatePost(post) => insert_post(flavor, post),
        WorkspaceBlackboardDomainWrite::UpdatePost(post) => update_post(flavor, post),
        WorkspaceBlackboardDomainWrite::DeletePost { post_id } => scoped_delete(
            flavor,
            "workspace_blackboard_posts",
            "post_id",
            &mutation.scope,
            post_id,
        ),
        WorkspaceBlackboardDomainWrite::CreateReply(reply) => insert_reply(flavor, reply),
        WorkspaceBlackboardDomainWrite::UpdateReply(reply) => update_reply(flavor, reply),
        WorkspaceBlackboardDomainWrite::DeleteReply { post_id, reply_id } => {
            delete_reply(flavor, &mutation.scope, post_id, reply_id)
        }
    }
}

fn insert_post(flavor: DbSqlFlavor, post: &WorkspaceBlackboardPostRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_blackboard_posts (post_id, tenant_id, project_id, workspace_id, \
             author_actor_id, title, content, status, is_pinned, metadata_json, created_at, \
             updated_at) VALUES (",
        )
        .bind(post.post_id.as_str())
        .push_static(", ")
        .bind(post.tenant_id.as_str())
        .push_static(", ")
        .bind(post.project_id.as_str())
        .push_static(", ")
        .bind(post.workspace_id.as_str())
        .push_static(", ")
        .bind(post.author_actor_id.as_str())
        .push_static(", ")
        .bind(post.title.as_str())
        .push_static(", ")
        .bind(post.content.as_str())
        .push_static(", ")
        .bind(post.status.as_str())
        .push_static(", ")
        .bind(post.is_pinned)
        .push_static(", ")
        .bind(post.metadata.to_string())
        .push_static(", ")
        .bind(post.created_at.as_str())
        .push_static(", ")
        .bind(post.updated_at.clone())
        .push_static(")")
        .build()
}

fn update_post(flavor: DbSqlFlavor, post: &WorkspaceBlackboardPostRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_blackboard_posts SET title = ")
        .bind(post.title.as_str())
        .push_static(", content = ")
        .bind(post.content.as_str())
        .push_static(", status = ")
        .bind(post.status.as_str())
        .push_static(", is_pinned = ")
        .bind(post.is_pinned)
        .push_static(", metadata_json = ")
        .bind(post.metadata.to_string())
        .push_static(", updated_at = ")
        .bind(post.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(post.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(post.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(post.workspace_id.as_str())
        .push_static(" AND post_id = ")
        .bind(post.post_id.as_str())
        .build()
}

fn insert_reply(flavor: DbSqlFlavor, reply: &WorkspaceBlackboardReplyRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_blackboard_replies (reply_id, tenant_id, project_id, \
             workspace_id, post_id, author_actor_id, content, metadata_json, created_at, \
             updated_at) VALUES (",
        )
        .bind(reply.reply_id.as_str())
        .push_static(", ")
        .bind(reply.tenant_id.as_str())
        .push_static(", ")
        .bind(reply.project_id.as_str())
        .push_static(", ")
        .bind(reply.workspace_id.as_str())
        .push_static(", ")
        .bind(reply.post_id.as_str())
        .push_static(", ")
        .bind(reply.author_actor_id.as_str())
        .push_static(", ")
        .bind(reply.content.as_str())
        .push_static(", ")
        .bind(reply.metadata.to_string())
        .push_static(", ")
        .bind(reply.created_at.as_str())
        .push_static(", ")
        .bind(reply.updated_at.clone())
        .push_static(")")
        .build()
}

fn update_reply(flavor: DbSqlFlavor, reply: &WorkspaceBlackboardReplyRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_blackboard_replies SET content = ")
        .bind(reply.content.as_str())
        .push_static(", metadata_json = ")
        .bind(reply.metadata.to_string())
        .push_static(", updated_at = ")
        .bind(reply.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(reply.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(reply.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(reply.workspace_id.as_str())
        .push_static(" AND post_id = ")
        .bind(reply.post_id.as_str())
        .push_static(" AND reply_id = ")
        .bind(reply.reply_id.as_str())
        .build()
}

fn delete_reply(
    flavor: DbSqlFlavor,
    scope: &WorkspaceBlackboardScope,
    post_id: &str,
    reply_id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("DELETE FROM workspace_blackboard_replies WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND post_id = ")
        .bind(post_id)
        .push_static(" AND reply_id = ")
        .bind(reply_id)
        .build()
}

fn scoped_delete(
    flavor: DbSqlFlavor,
    table: &'static str,
    id_column: &'static str,
    scope: &WorkspaceBlackboardScope,
    id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("DELETE FROM ")
        .push_static(table)
        .push_static(" WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND ")
        .push_static(id_column)
        .push_static(" = ")
        .bind(id)
        .build()
}

fn outbox_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceBlackboardMutation,
    outbox_id: &str,
    committed_revision: u64,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, action, surface_owner) = mutation.receipt_authority.as_ref().map_or(
        ("v1", mutation.action.as_str(), "blackboard"),
        |authority| {
            (
                authority.contract_version().as_str(),
                authority.action().as_str(),
                authority.surface().as_str(),
            )
        },
    );
    let metadata = json!({
        "action": action,
        "authority_class": "authoritative",
        "contract_version": contract_version,
        "receipt_id": receipt_id,
        "request_hash": &mutation.payload_hash,
        "signal_role": "sensing-capable",
        "surface_boundary": "owned",
        "surface_owner": surface_owner,
    });
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
             aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, \
             metadata_json, correlation_id, idempotency_key) VALUES (",
        )
        .bind(outbox_id)
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", 'blackboard', ")
        .bind(mutation.aggregate_id.as_str())
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
    mutation: &WorkspaceBlackboardMutation,
    receipt_id: &str,
    committed_revision: u64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_mutation_receipts SET committed_revision = ")
        .bind(committed_revision)
        .push_static(", response_json = ")
        .bind(mutation.response.to_string())
        .push_static(", committed_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE receipt_id = ")
        .bind(receipt_id)
        .push_static(" AND request_hash = ")
        .bind(mutation.payload_hash.as_str())
        .push_static(" AND committed_revision IS NULL")
        .build()
}

pub(super) fn receipt_outcome(
    mutation: &WorkspaceBlackboardMutation,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceBlackboardMutationOutcome>, WorkspaceBlackboardStoreError> {
    let request_hash = required_string(row, "request_hash")?;
    if request_hash != mutation.payload_hash {
        return Err(WorkspaceBlackboardStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Err(WorkspaceBlackboardStoreError::IncompleteReceipt);
    };
    let committed_revision = u64::try_from(committed_revision)
        .map_err(|_| WorkspaceBlackboardStoreError::InvalidRecord("committed_revision"))?;
    Ok(Some(WorkspaceBlackboardMutationOutcome {
        committed_revision,
        response: required_json_object(row, "response_json")?,
        outbox_id: deterministic_id("blackboard-outbox", mutation),
        replayed,
    }))
}

fn deterministic_id(namespace: &str, mutation: &WorkspaceBlackboardMutation) -> String {
    let mut digest = Sha256::new();
    let (surface, action) = mutation
        .receipt_authority
        .as_ref()
        .map_or(("blackboard", mutation.action.as_str()), |authority| {
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
