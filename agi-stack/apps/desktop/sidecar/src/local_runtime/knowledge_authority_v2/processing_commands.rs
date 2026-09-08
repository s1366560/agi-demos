//! Explicit writes never accept caller profiles, vectors, or worker lease options.
use super::super::super::{
    embedding_provider::EmbeddingRoute,
    indexing::{IndexRunOptions, IndexRunOutcome},
    processing::ProcessingRunOptions,
};
use super::*;
use agistack_core::knowledge::processing::audit::ProcessingAuditOutcome;

pub(crate) async fn command(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<ProcessingCommandRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &body.scope)
        .map_err(IntoResponse::into_response)?;
    // Check live writer admission before any provider probe or worker dispatch.
    processing_context::with_current(&operation, &state, &auth, |_| Ok(()))
        .map_err(IntoResponse::into_response)?;
    let result = match body.command {
        ProcessingCommand::ConfigureEmbedding {
            build_id,
            provider_id,
            provider_revision,
            model_id,
            expected_config_revision,
        } => {
            expected_selection(&operation, &state, &auth, expected_config_revision)
                .map_err(IntoResponse::into_response)?;
            if provider_revision > MAX_WIRE_INTEGER {
                return Err(
                    KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::InvalidInput)
                        .into_response(),
                );
            }
            let route = EmbeddingRoute {
                provider_id,
                provider_revision,
                model_id,
            };
            let build = operation
                .prepare_index_build(&state, &auth, &route, &build_id)
                .await
                .map_err(IntoResponse::into_response)?;
            let selected = operation
                .select_index_build(&state, &auth, &build, expected_config_revision)
                .map_err(IntoResponse::into_response)?;
            json!({"configuration":summary(&selected).map_err(IntoResponse::into_response)?})
        }
        ProcessingCommand::SelectEmbedding {
            build_id,
            expected_config_revision,
        } => {
            expected_selection(&operation, &state, &auth, expected_config_revision)
                .map_err(IntoResponse::into_response)?;
            let build = processing_context::with_read_current(&operation, &state, &auth, |clock| {
                operation
                    .authority
                    .repository()
                    .map_err(|_| KnowledgeError::Conflict)?
                    .index_build_durable(&operation.scope, &build_id, clock)
            })
            .map_err(IntoResponse::into_response)?;
            let selected = operation
                .select_index_build(&state, &auth, &build, expected_config_revision)
                .map_err(IntoResponse::into_response)?;
            json!({"configuration":summary(&selected).map_err(IntoResponse::into_response)?})
        }
        ProcessingCommand::IndexOne {
            build_id,
            config_revision,
        } => {
            let config = current_config(&operation, &state, &auth, &build_id, config_revision)
                .map_err(IntoResponse::into_response)?;
            let receipt = operation
                .index_one(&state, &auth, &config, IndexRunOptions::default())
                .await
                .map_err(IntoResponse::into_response)?;
            let receipt = receipt.map(|r| {
                let (status, failure) = match r.outcome {
                    IndexRunOutcome::Indexed => ("indexed", None),
                    IndexRunOutcome::Failed(f) => ("failed", Some(f)),
                };
                json!({"input":r.input,"attempt":r.attempt,"status":status,"failure":failure})
            });
            json!({"receipt":receipt})
        }
        ProcessingCommand::PromoteIndex {
            build_id,
            config_revision,
            expected_active_build_id,
        } => {
            let config = current_config(&operation, &state, &auth, &build_id, config_revision)
                .map_err(IntoResponse::into_response)?;
            operation
                .promote_index_build(&state, &auth, &config, expected_active_build_id.as_deref())
                .map_err(IntoResponse::into_response)?;
            json!({"configuration":summary(&config).map_err(IntoResponse::into_response)?,"active_build_id":build_id})
        }
        ProcessingCommand::RetryIndex {
            build_id,
            config_revision,
            input,
            expected_attempt,
        } => {
            let config = current_config(&operation, &state, &auth, &build_id, config_revision)
                .map_err(IntoResponse::into_response)?;
            operation
                .retry_index(&state, &auth, &config, &input, expected_attempt)
                .map_err(IntoResponse::into_response)?;
            json!({"accepted":true,"input":input,"attempt":expected_attempt})
        }
        ProcessingCommand::ProcessOne { workspace_id } => {
            let receipt = operation
                .process_one(
                    state.clone(),
                    auth,
                    &workspace_id,
                    ProcessingRunOptions::default(),
                )
                .await
                .map_err(|error| match error {
                    KnowledgeAuthorityErrorV2::TransportUnavailable => {
                        KnowledgeAuthorityErrorV2::ProcessingUnavailable.into_response()
                    }
                    other => other.into_response(),
                })?;
            let receipt = receipt.map(|r| {
                let (status, failure) = match r.outcome {
                    ProcessingAuditOutcome::Applied { .. } => ("applied", None),
                    ProcessingAuditOutcome::Failed { code, .. } => ("failed", Some(code)),
                };
                json!({"source":r.source,"attempt":r.attempt,"status":status,"failure":failure})
            });
            json!({"receipt":receipt})
        }
    };
    Ok(Json(
        json!({"contract_version":VERSION,"scope":body.scope,"result":result}),
    ))
}

fn expected_selection(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    expected: Option<u64>,
) -> Result<(), KnowledgeAuthorityErrorV2> {
    if expected.is_some_and(|revision| revision == 0 || revision >= MAX_WIRE_INTEGER) {
        return Err(KnowledgeError::InvalidInput.into());
    }
    processing_context::with_current(operation, state, auth, |clock| {
        let config = operation
            .authority
            .repository()
            .map_err(|_| KnowledgeError::Conflict)?
            .desired_index_config_durable(&operation.scope, clock)?;
        if config.map(|c| c.revision) != expected {
            return Err(KnowledgeError::Conflict);
        }
        Ok(())
    })
}
