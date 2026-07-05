use super::*;

pub(super) fn drone_provider_unavailable_stage_metadata(
    contract: &PipelineContractFoundation,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("plugin_unavailable".to_string(), json!(true));
    metadata.insert("provider".to_string(), json!(contract.provider));
    metadata
}

pub(super) fn drone_provider_unavailable_run_metadata(
    contract: &PipelineContractFoundation,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
    message: &str,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("stage_count".to_string(), json!(1));
    metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("plugin_unavailable".to_string(), json!(true));
    metadata.insert("provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("provider_error".to_string(), json!(message));
    metadata.insert("pipeline_failed_stage".to_string(), json!("drone_plugin"));
    metadata.insert("pipeline_failure_summary".to_string(), json!(message));
    metadata.insert("pipeline_last_summary".to_string(), json!(message));
    if let Some(outcome) = source_publish_outcome {
        metadata.extend(outcome.metadata().clone());
    }
    metadata
}

pub(super) fn source_publish_stage_metadata(
    failure: &DroneSourcePublishFailure,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.extend(failure.metadata.clone());
    metadata
}

pub(super) fn drone_source_publish_run_metadata(
    contract: &PipelineContractFoundation,
    failure: &DroneSourcePublishFailure,
    completed_at: DateTime<Utc>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("stage_count".to_string(), json!(1));
    metadata.insert(
        "service_count".to_string(),
        json!(contract.services_json.as_array().map_or(0, Vec::len)),
    );
    metadata.insert("external_provider".to_string(), json!(DRONE_PROVIDER));
    metadata.insert("pipeline_failed_stage".to_string(), json!("source_publish"));
    metadata.insert(
        "pipeline_failure_summary".to_string(),
        json!(failure.reason),
    );
    metadata.insert("pipeline_last_summary".to_string(), json!(failure.reason));
    metadata.insert(
        "pipeline_finished_at".to_string(),
        json!(completed_at.to_rfc3339()),
    );
    metadata.extend(failure.metadata.clone());
    metadata
}

pub(in crate::workspace_outbox_worker) fn pipeline_contract_metadata(
    contract: &PipelineContractFoundation,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Value {
    source_publish_outcome.map_or_else(
        || contract.metadata_json.clone(),
        |outcome| {
            let mut metadata = object_or_empty(contract.metadata_json.clone());
            metadata.extend(outcome.metadata().clone());
            Value::Object(metadata)
        },
    )
}

pub(in crate::workspace_outbox_worker) fn pipeline_run_metadata(
    reason: &str,
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Value {
    let mut metadata = Map::new();
    metadata.insert("reason".to_string(), json!(reason));
    if let Some(outcome) = source_publish_outcome {
        metadata.extend(outcome.metadata().clone());
    }
    Value::Object(metadata)
}

pub(in crate::workspace_outbox_worker) fn source_publish_source_commit_ref(
    source_publish_outcome: Option<&DroneSourcePublishOutcome>,
) -> Option<String> {
    source_publish_outcome.and_then(|outcome| {
        outcome
            .metadata()
            .get("source_publish_source_commit_ref")
            .and_then(Value::as_str)
            .and_then(commit_ref_token)
    })
}

pub(super) fn source_publish_metadata(
    status: &str,
    reason: Option<&str>,
    commit_ref: Option<&str>,
    branch: Option<&str>,
    source_commit_ref: Option<&str>,
    token_env: Option<&str>,
) -> Map<String, Value> {
    let mut metadata = Map::new();
    metadata.insert("source_publish_status".to_string(), json!(status));
    metadata.insert("source_publish_provider".to_string(), json!("git"));
    if let Some(reason) = reason {
        metadata.insert("source_publish_reason".to_string(), json!(reason));
    }
    if let Some(commit_ref) = commit_ref {
        metadata.insert("source_publish_commit_ref".to_string(), json!(commit_ref));
    }
    if let Some(branch) = branch {
        metadata.insert("source_publish_branch".to_string(), json!(branch));
    }
    if let Some(source_commit_ref) = source_commit_ref {
        metadata.insert(
            "source_publish_source_commit_ref".to_string(),
            json!(source_commit_ref),
        );
    }
    if let Some(token_env) = token_env {
        metadata.insert("source_publish_token_env".to_string(), json!(token_env));
    }
    metadata
}
