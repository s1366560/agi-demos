//! Existing knowledge authority transport for explicit community work.
use super::super::super::processing::ProcessingRunOptions;
use super::*;
use agistack_core::knowledge::community::build::CommunityBuildRequest;

fn identifier(value: &str) -> Result<(), KnowledgeAuthorityErrorV2> {
    if value.trim().is_empty() || value.len() > 256 || value.chars().any(char::is_control) {
        return Err(KnowledgeError::InvalidInput.into());
    }
    Ok(())
}
fn candidate(value: &str) -> Result<(), KnowledgeAuthorityErrorV2> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(KnowledgeError::InvalidInput.into());
    }
    Ok(())
}
fn write<T>(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    action: impl FnOnce(
        &dyn Fn() -> agistack_core::knowledge::KnowledgeResult<i64>,
    ) -> agistack_core::knowledge::KnowledgeResult<T>,
) -> Result<T, KnowledgeAuthorityErrorV2> {
    processing_context::with_read_current_checked(operation, state, auth, true, |_| Ok(()), action)
}

pub(super) fn query(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    query: ProcessingQuery,
) -> Result<Value, KnowledgeAuthorityErrorV2> {
    let repo = operation.authority.repository()?;
    match query {
        ProcessingQuery::CommunityActive {} => {
            let view = processing_context::with_read_current(operation, state, auth, |_| {
                repo.active_community_build_durable(&operation.scope)
            })?;
            Ok(
                json!({"selection":view.selection,"current_status":view.current.map(|b|b.status),"stale_build_id":view.stale_build_id}),
            )
        }
        ProcessingQuery::CommunityBuild {
            build_id,
            offset,
            limit,
        } => {
            identifier(&build_id)?;
            let page = processing_context::with_read_current(operation, state, auth, |clock| {
                repo.community_build_page_durable(&operation.scope, &build_id, offset, limit, clock)
            })?;
            Ok(json!({"page":page}))
        }
        ProcessingQuery::CommunityAudit {
            build_id,
            candidate_id,
            attempt,
        } => {
            identifier(&build_id)?;
            candidate(&candidate_id)?;
            let audit = processing_context::with_read_current(operation, state, auth, |_| {
                repo.community_audit_durable(&operation.scope, &build_id, &candidate_id, attempt)
            })?;
            Ok(json!({"audit":audit.map(|a|a.summary())}))
        }
        _ => Err(KnowledgeError::InvalidInput.into()),
    }
}

pub(super) async fn command(
    operation: &KnowledgeOperationV2,
    state: &Arc<LocalRuntimeState>,
    auth: &AuthenticatedContext,
    command: ProcessingCommand,
) -> Result<Value, KnowledgeAuthorityErrorV2> {
    let repo = operation.authority.repository()?;
    match command {
        ProcessingCommand::CreateCommunityBuild {
            idempotency_key,
            min_community_size,
        } => {
            identifier(&idempotency_key)?;
            if !(2..=4096).contains(&min_community_size) {
                return Err(KnowledgeError::InvalidInput.into());
            }
            let build = write(operation, state, auth, |clock| {
                repo.create_community_build_durable(
                    &operation.scope,
                    &CommunityBuildRequest {
                        actor_id: auth.user.user_id.clone(),
                        idempotency_key,
                        min_community_size,
                    },
                    clock,
                )
            })?;
            Ok(json!({"build":build}))
        }
        ProcessingCommand::SelectCommunityBuild {
            build_id,
            expected_selection_revision,
        } => {
            identifier(&build_id)?;
            if expected_selection_revision >= MAX_WIRE_INTEGER {
                return Err(KnowledgeError::InvalidInput.into());
            }
            let selection = write(operation, state, auth, |clock| {
                repo.select_community_build_durable(
                    &operation.scope,
                    &build_id,
                    expected_selection_revision,
                    clock,
                )
            })?;
            Ok(json!({"selection":selection}))
        }
        ProcessingCommand::ProcessCommunityOne {
            build_id,
            workspace_id,
        } => {
            identifier(&build_id)?;
            identifier(&workspace_id)?;
            let receipt = operation
                .process_community_one(
                    state.clone(),
                    auth.clone(),
                    &workspace_id,
                    &build_id,
                    ProcessingRunOptions::default(),
                )
                .await
                .map_err(|error| match error {
                    KnowledgeAuthorityErrorV2::TransportUnavailable => {
                        KnowledgeAuthorityErrorV2::ProcessingUnavailable
                    }
                    other => other,
                })?;
            // Avoid delivering any accepted result after the caller changed
            // context during the network wait, even when its durable audit exists.
            processing_context::with_read_current(operation, state, auth, |_| Ok(()))?;
            Ok(json!({"receipt":receipt.map(|r|r.summary())}))
        }
        ProcessingCommand::RetryCommunity {
            build_id,
            candidate_id,
            expected_attempt,
        } => {
            identifier(&build_id)?;
            candidate(&candidate_id)?;
            if expected_attempt == 0 {
                return Err(KnowledgeError::InvalidInput.into());
            }
            write(operation, state, auth, |clock| {
                repo.retry_community_job_durable(
                    &operation.scope,
                    &build_id,
                    &candidate_id,
                    expected_attempt,
                    clock,
                )
            })?;
            Ok(
                json!({"accepted":true,"build_id":build_id,"candidate_id":candidate_id,"attempt":expected_attempt}),
            )
        }
        ProcessingCommand::ActivateCommunityBuild {
            build_id,
            expected_selection_revision,
        } => {
            identifier(&build_id)?;
            if expected_selection_revision == 0 || expected_selection_revision > MAX_WIRE_INTEGER {
                return Err(KnowledgeError::InvalidInput.into());
            }
            let activated = write(operation, state, auth, |clock| {
                repo.activate_community_build_durable(
                    &operation.scope,
                    &build_id,
                    expected_selection_revision,
                    clock,
                )
            })?;
            Ok(
                json!({"activated":activated,"build_id":build_id,"selection_revision":expected_selection_revision}),
            )
        }
        _ => Err(KnowledgeError::InvalidInput.into()),
    }
}
