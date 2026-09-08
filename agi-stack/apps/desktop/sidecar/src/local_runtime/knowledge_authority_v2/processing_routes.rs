//! Generated wire DTOs, live admission, and server-owned profile resolution.
use agistack_core::knowledge::index::*;

use super::super::{contracts::*, processing_context};
use super::*;

#[path = "processing_commands.rs"]
mod commands;
#[path = "community_routes.rs"]
mod community;
#[path = "graph_source_routes.rs"]
mod graph_source;
pub(super) use commands::command;

const MAX_WIRE_INTEGER: u64 = 9_007_199_254_740_991;

pub(super) async fn query(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(lease): Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Json(body): Json<ProcessingQueryRequest>,
) -> RouteResult {
    let operation = KnowledgeOperationV2::admit(lease, &auth, &body.scope)
        .map_err(IntoResponse::into_response)?;
    let operation = operation
        .admit_capability(&state, &auth, body.query.capability_action())
        .map_err(IntoResponse::into_response)?;
    let result = match body.query {
        ProcessingQuery::GraphSource {
            source,
            expected_audit_attempt,
        } => {
            return graph_source::query(
                &operation,
                &state,
                &auth,
                &body.scope,
                &source,
                expected_audit_attempt,
            )
            .await;
        }
        query @ (ProcessingQuery::CommunityActive {}
        | ProcessingQuery::CommunityBuilds { .. }
        | ProcessingQuery::CommunityBuild { .. }
        | ProcessingQuery::CommunityAudit { .. }) => {
            community::query(&operation, &state, &auth, query)
                .map_err(IntoResponse::into_response)?
        }
        ProcessingQuery::Configuration {} => {
            let status =
                processing_context::with_read_current(&operation, &state, &auth, |clock| {
                    operation
                        .authority
                        .repository()
                        .map_err(|_| KnowledgeError::Conflict)?
                        .index_configuration_status_durable(&operation.scope, clock)
                })
                .map_err(IntoResponse::into_response)?;
            let configuration = status
                .configuration
                .as_ref()
                .map(summary)
                .transpose()
                .map_err(IntoResponse::into_response)?;
            json!({"configuration":configuration,"active_build_id":status.active_build_id,
                "processing":processing_coverage(&status.processing),"index":status.index.as_ref().map(index_coverage)})
        }
        ProcessingQuery::ProcessingTask { source } => {
            validate_retry_source(&source).map_err(IntoResponse::into_response)?;
            let result =
                processing_context::with_read_current(&operation, &state, &auth, |clock| {
                    operation
                        .authority
                        .repository()
                        .map_err(|_| KnowledgeError::Conflict)?
                        .processing_task_durable(&operation.scope, &source, clock)
                })
                .map_err(IntoResponse::into_response)?;
            serde_json::to_value(result).map_err(serialization_error)?
        }
        ProcessingQuery::FailedProcessing { request } => {
            let result =
                processing_context::with_read_current(&operation, &state, &auth, |clock| {
                    operation
                        .authority
                        .repository()
                        .map_err(|_| KnowledgeError::Conflict)?
                        .failed_processing_durable(&operation.scope, &request, clock)
                })
                .map_err(IntoResponse::into_response)?;
            serde_json::to_value(result).map_err(serialization_error)?
        }
        ProcessingQuery::ProcessingAudits { source, request } => {
            let result =
                processing_context::with_read_current(&operation, &state, &auth, |clock| {
                    operation
                        .authority
                        .repository()
                        .map_err(|_| KnowledgeError::Conflict)?
                        .processing_audit_summaries_durable(
                            &operation.scope,
                            &source,
                            &request,
                            clock,
                        )
                })
                .map_err(IntoResponse::into_response)?;
            serde_json::to_value(result).map_err(serialization_error)?
        }
        ProcessingQuery::FailedIndex {
            build_id,
            config_revision,
            request,
        } => {
            let config = current_config(&operation, &state, &auth, &build_id, config_revision)
                .map_err(IntoResponse::into_response)?;
            let result =
                processing_context::with_read_current(&operation, &state, &auth, |clock| {
                    operation
                        .authority
                        .repository()
                        .map_err(|_| KnowledgeError::Conflict)?
                        .failed_index_durable(&config, &request, clock)
                })
                .map_err(IntoResponse::into_response)?;
            serde_json::to_value(result).map_err(serialization_error)?
        }
        ProcessingQuery::Entities { request } => serde_json::to_value(
            operation
                .entities(&state, &auth, &request)
                .map_err(IntoResponse::into_response)?,
        )
        .map_err(serialization_error)?,
        ProcessingQuery::Relationships { request } => serde_json::to_value(
            operation
                .relationships(&state, &auth, &request)
                .map_err(IntoResponse::into_response)?,
        )
        .map_err(serialization_error)?,
        ProcessingQuery::Text { literal, request } => serde_json::to_value(
            operation
                .search_text(&state, &auth, &literal, &request)
                .map_err(IntoResponse::into_response)?,
        )
        .map_err(serialization_error)?,
        ProcessingQuery::Semantic {
            build_id,
            config_revision,
            query,
            limit,
        } => {
            let config = current_config(&operation, &state, &auth, &build_id, config_revision)
                .map_err(IntoResponse::into_response)?;
            let result = operation
                .semantic_query(&state, &auth, &config, &query, limit)
                .await
                .map_err(IntoResponse::into_response)?;
            let hits: Vec<_> = result
                .hits
                .into_iter()
                .map(|hit| json!({"input":hit.input,"score":hit.score}))
                .collect();
            json!({"configuration":summary(&DesiredEmbeddingConfig {revision:result.config_revision,build:result.build})
                .map_err(IntoResponse::into_response)?,"processing":processing_coverage(&result.processing),
                "index":index_coverage(&result.index),"hits":hits})
        }
    };
    Ok(Json(
        json!({"contract_version":VERSION,"scope":body.scope,"result":result}),
    ))
}

fn current_config(
    operation: &KnowledgeOperationV2,
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    build_id: &str,
    config_revision: u64,
) -> Result<DesiredEmbeddingConfig, KnowledgeAuthorityErrorV2> {
    if build_id.trim().is_empty() || config_revision == 0 || config_revision > MAX_WIRE_INTEGER {
        return Err(KnowledgeError::InvalidInput.into());
    }
    processing_context::with_read_current(operation, state, auth, |clock| {
        let config = operation
            .authority
            .repository()
            .map_err(|_| KnowledgeError::Conflict)?
            .desired_index_config_durable(&operation.scope, clock)?
            .ok_or(KnowledgeError::Conflict)?;
        if config.revision != config_revision || config.build.build_id != build_id {
            return Err(KnowledgeError::Conflict);
        }
        Ok(config)
    })
}

fn summary(config: &DesiredEmbeddingConfig) -> Result<Value, KnowledgeAuthorityErrorV2> {
    let p = &config.build.profile;
    if config.revision > MAX_WIRE_INTEGER || p.provider_revision > MAX_WIRE_INTEGER {
        return Err(KnowledgeError::InvalidInput.into());
    }
    Ok(
        json!({"revision":config.revision,"build_id":config.build.build_id,
        "provider_id":p.provider_id,"provider_revision":p.provider_revision,"model_id":p.model_id,
        "dimensions":p.dimensions.get(),"input_contract_version":p.input_contract_version,
        "normalization_version":p.normalization_version}),
    )
}
fn processing_coverage(value: &ProcessingCoverage) -> Value {
    json!({"current_sources":value.current_sources,"applied_sources":value.applied_sources,
        "pending_sources":value.pending_sources,"failed_sources":value.failed_sources})
}
fn index_coverage(value: &IndexCoverage) -> Value {
    json!({"current_sources":value.current_sources,"completed_sources":value.completed_sources,
        "failed_sources":value.failed_sources})
}
fn serialization_error(_: serde_json::Error) -> Response {
    KnowledgeAuthorityErrorV2::Knowledge(KnowledgeError::InvalidInput).into_response()
}

fn validate_retry_source(
    source: &agistack_core::knowledge::processing::ProcessingSource,
) -> Result<(), KnowledgeAuthorityErrorV2> {
    if source.revision == 0
        || source.change_sequence == 0
        || source.change_sequence > MAX_WIRE_INTEGER
    {
        return Err(KnowledgeError::InvalidInput.into());
    }
    Ok(())
}
