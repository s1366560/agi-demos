//! Owner-bound audio receipts and cleanup, independent of permission to start recording.
use super::*;
use recordings_store::Record;

pub(super) fn snapshot(state: &LocalRuntimeState, owner: &Owner) -> Result<Vec<Value>, String> {
    Ok(recordings_store::list(state, owner)?
        .into_iter()
        .map(|record| record.receipt)
        .collect())
}

fn public_receipt(context: &CuaCallContext, native: &Value) -> Result<Value, String> {
    let id = native["recording_id"]
        .as_str()
        .ok_or("cua_recording_invalid")?;
    Uuid::parse_str(id).map_err(|_| "cua_recording_invalid")?;
    if !matches!(
        native["source"].as_str(),
        Some("microphone" | "system" | "mixed")
    ) || !matches!(
        native["status"].as_str(),
        Some("recording" | "stopping" | "pending_export" | "failed" | "saved")
    ) || native["started_at"]
        .as_str()
        .and_then(|time| chrono::DateTime::parse_from_rfc3339(time).ok())
        .is_none()
        || native["artifacts"]
            .as_array()
            .is_some_and(|artifacts| artifacts.len() > 2)
    {
        return Err("cua_recording_invalid".into());
    }
    let mut receipt = json!({"recording_id":id,"session_id":context.session_id,
        "conversation_id":context.conversation_id,"run_id":context.run_id,
        "source":native["source"],"status":native["status"],"started_at":native["started_at"],"artifacts":[]});
    for field in [
        "ended_at",
        "elapsed_ms",
        "end_reason",
        "error_code",
        "partial",
        "sample_rate",
        "channels",
        "encoding",
        "max_duration_ms",
    ] {
        if let Some(value) = native.get(field) {
            receipt[field] = value.clone();
        }
    }
    Ok(receipt)
}

async fn acknowledge(state: &LocalRuntimeState, record: &Record) -> bool {
    if let Some(client) = state.computer_use.client.get() {
        if client
            .request_existing_session(
                &record.context,
                "audio_ack",
                json!({"recording_id":record.receipt["recording_id"]}),
            )
            .await
            .is_ok()
        {
            return true;
        }
    }
    tracing::warn!(
        code = "cua_recording_ack_deferred",
        "Saved recording cleanup will be retried"
    );
    false
}

async fn export_pending(state: &LocalRuntimeState, record: &mut Record) -> Result<(), String> {
    if record.receipt["status"] != "pending_export" && record.receipt["can_retry_export"] != true {
        return Ok(());
    }
    match recordings_export::export(state, record).await {
        Ok(artifacts) => {
            record.receipt["status"] = json!("saved");
            record.receipt["can_retry_export"] = json!(false);
            record.receipt["artifacts"] = json!(artifacts);
            if record.native.get("error_code").is_none() {
                record
                    .receipt
                    .as_object_mut()
                    .expect("receipt object")
                    .remove("error_code");
            }
            // The durable receipt is committed before native files may be removed.
            recordings_store::save(state, record)?;
            record.acknowledged = acknowledge(state, record).await;
            recordings_store::save(state, record)?;
        }
        Err(error) => {
            record.receipt["status"] = json!("failed");
            record.receipt["can_retry_export"] = json!(error != recordings_export::SOURCE_MISSING);
            record.receipt["error_code"] = json!(error);
            recordings_store::save(state, record)?;
        }
    }
    Ok(())
}

async fn ingest_inner(
    state: &LocalRuntimeState,
    owner: &Owner,
    context: &CuaCallContext,
    output: &Value,
) -> Result<Vec<Value>, String> {
    let Some(receipts) = output.get("recordings").and_then(Value::as_array) else {
        return Ok(vec![]);
    };
    if receipts.len() > 256 {
        return Err("cua_recording_invalid".into());
    }
    let mut accepted = Vec::new();
    for native in receipts {
        let receipt = public_receipt(context, native)?;
        let id = receipt["recording_id"]
            .as_str()
            .expect("validated recording id");
        let previous = recordings_store::get(state, id)?;
        if previous
            .as_ref()
            .is_some_and(|previous| previous.owner != *owner || previous.context != *context)
        {
            return Err("cua_recording_scope_mismatch".into());
        }
        if let Some(previous) = previous
            .as_ref()
            .filter(|previous| previous.receipt["status"] == "saved")
        {
            let mut previous = previous.clone();
            if !previous.acknowledged {
                previous.acknowledged =
                    receipt["status"] == "saved" || acknowledge(state, &previous).await;
                recordings_store::save(state, &previous)?;
            }
            accepted.push(previous.receipt.clone());
            continue;
        }
        if receipt["status"] == "saved" {
            return Err("cua_recording_export_receipt_missing".into());
        }
        if let Some(previous) = previous
            .as_ref()
            .filter(|previous| previous.receipt["can_retry_export"] == true)
        {
            accepted.push(previous.receipt.clone());
            continue;
        }
        // Status notifications can arrive ahead of a delayed audio_start reply.
        if let Some(previous) = previous.as_ref().filter(|previous| {
            matches!(
                previous.receipt["status"].as_str(),
                Some("pending_export" | "failed")
            ) && matches!(receipt["status"].as_str(), Some("recording" | "stopping"))
        }) {
            accepted.push(previous.receipt.clone());
            continue;
        }
        let root = if let Some(previous) = previous {
            previous.root
        } else {
            state
                .computer_use
                .client
                .get()
                .ok_or("cua_recording_owner_unavailable")?
                .existing_session_artifact_root(&context.session_id)
                .await
                .ok_or("cua_recording_owner_unavailable")?
        };
        let mut record = Record {
            owner: owner.clone(),
            context: context.clone(),
            root,
            native: native.clone(),
            receipt,
            acknowledged: false,
        };
        if record.native.get("artifacts").is_none() {
            record.native["artifacts"] = json!([]);
        }
        recordings_store::save(state, &record)?;
        export_pending(state, &mut record).await?;
        accepted.push(record.receipt);
    }
    Ok(accepted)
}

pub(super) async fn ingest(
    state: &LocalRuntimeState,
    owner: &Owner,
    context: &CuaCallContext,
    output: &Value,
) -> Result<Vec<Value>, String> {
    let _gate = state.computer_use.recordings_gate.lock().await;
    ingest_inner(state, owner, context, output).await
}

/// Rewrites native audio output to durable references; source paths stay private.
pub(super) async fn tool_result(
    state: &LocalRuntimeState,
    session: &Session,
    result: &mut ToolResult,
) -> CoreResult<()> {
    let mut output: Value = serde_json::from_str(&result.output_json)
        .map_err(|_| CoreError::Tool("cua_recording_invalid".into()))?;
    if output.get("recordings").is_none() {
        return Ok(());
    }
    let receipts = ingest(state, &session.owner, &session.context, &output)
        .await
        .map_err(CoreError::Tool)?;
    output["artifacts"] = json!(
        receipts
            .iter()
            .flat_map(|receipt| receipt["artifacts"]
                .as_array()
                .into_iter()
                .flatten()
                .cloned())
            .collect::<Vec<_>>()
    );
    output["recordings"] = json!(receipts);
    for artifact in output["artifacts"].as_array().into_iter().flatten() {
        if let Some(id) = artifact["artifact_id"].as_str() {
            let attachment =
                artifacts::attachment(state, &session.owner, &session.context.conversation_id, id)
                    .map_err(CoreError::Tool)?;
            if !result
                .media
                .iter()
                .any(|media| media.artifact_path == attachment.artifact_path)
            {
                result.media.push(attachment);
            }
        }
    }
    result.output_json = output.to_string();
    Ok(())
}

/// The native session has already released devices. Export its sealed receipts.
pub(super) async fn refresh_session(state: &LocalRuntimeState, session: &Session) {
    let Some(client) = state.computer_use.client.get() else {
        return;
    };
    if let Ok(output) = client
        .request_existing_session(&session.context, "audio_status", json!({}))
        .await
    {
        if ingest(state, &session.owner, &session.context, &output)
            .await
            .is_err()
        {
            tracing::warn!(
                code = "cua_recording_refresh_deferred",
                "Recording status could not be persisted"
            );
        }
    } else {
        tracing::warn!(
            code = "cua_recording_refresh_unavailable",
            "Recording resource status is unavailable"
        );
    }
}

pub(super) async fn stop(
    state: &LocalRuntimeState,
    owner: &Owner,
    session_id: &str,
    recording_id: &str,
) -> Result<(), String> {
    let record = recordings_store::get(state, recording_id)?
        .filter(|record| record.owner == *owner && record.context.session_id == session_id)
        .ok_or("cua_recording_not_found")?;
    if record.receipt["status"] == "pending_export" || record.receipt["can_retry_export"] == true {
        let _gate = state.computer_use.recordings_gate.lock().await;
        let mut record =
            recordings_store::get(state, recording_id)?.ok_or("cua_recording_not_found")?;
        return export_pending(state, &mut record).await;
    }
    if matches!(record.receipt["status"].as_str(), Some("saved" | "failed")) {
        return Ok(());
    }
    // Release the device before waiting behind any unrelated artifact export.
    let output = if let Some(client) = state.computer_use.client.get() {
        client
            .request_existing_session(
                &record.context,
                "audio_stop",
                json!({"recording_id":recording_id,"end_reason":"user_stopped"}),
            )
            .await
            .ok()
    } else {
        None
    };
    if let Some(output) = output {
        ingest(state, owner, &record.context, &output).await?;
    } else {
        resource_lost(state, owner, &record.context, Some(recording_id)).await;
    }
    Ok(())
}

async fn resource_lost(
    state: &LocalRuntimeState,
    owner: &Owner,
    context: &CuaCallContext,
    recording_id: Option<&str>,
) {
    let _gate = state.computer_use.recordings_gate.lock().await;
    if let Ok(records) = recordings_store::list(state, owner) {
        for mut record in records.into_iter().filter(|record| {
            record.context == *context
                && recording_id.is_none_or(|id| record.receipt["recording_id"] == id)
                && matches!(
                    record.receipt["status"].as_str(),
                    Some("recording" | "stopping")
                )
        }) {
            record.receipt["status"] = json!("failed");
            record.receipt["error_code"] = json!("cua_recording_resource_unavailable");
            record.receipt["end_reason"] = json!("process_ended");
            record.receipt["ended_at"] = json!(chrono::Utc::now().to_rfc3339());
            record.receipt["can_retry_export"] = json!(false);
            if recordings_store::save(state, &record).is_err() {
                tracing::warn!(
                    code = "cua_recording_status_save_failed",
                    "Lost recording state could not be persisted"
                );
            }
        }
    }
}

pub(super) async fn refresh_owner(state: &LocalRuntimeState, owner: &Owner) {
    let Ok(records) = recordings_store::list(state, owner) else {
        return;
    };
    let contexts: BTreeMap<_, _> = records
        .iter()
        .filter(|record| !matches!(record.receipt["status"].as_str(), Some("saved" | "failed")))
        .map(|record| (record.context.session_id.clone(), record.context.clone()))
        .collect();
    for context in contexts.values() {
        let output = if let Some(client) = state.computer_use.client.get() {
            client
                .request_existing_session(context, "audio_status", json!({}))
                .await
                .ok()
        } else {
            None
        };
        if let Some(output) = output {
            if ingest(state, owner, context, &output).await.is_err() {
                tracing::warn!(
                    code = "cua_recording_refresh_deferred",
                    "Recording status could not be persisted"
                );
            }
        } else {
            resource_lost(state, owner, context, None).await;
        }
    }
    let _gate = state.computer_use.recordings_gate.lock().await;
    if let Ok(records) = recordings_store::list(state, owner) {
        for mut record in records {
            if record.receipt["status"] == "pending_export" {
                if export_pending(state, &mut record).await.is_err() {
                    tracing::warn!(
                        code = "cua_recording_export_deferred",
                        "Recording export remains pending"
                    );
                }
            } else if record.receipt["status"] == "saved" && !record.acknowledged {
                record.acknowledged = acknowledge(state, &record).await;
                if recordings_store::save(state, &record).is_err() {
                    tracing::warn!(
                        code = "cua_recording_ack_save_failed",
                        "Recording cleanup receipt could not be persisted"
                    );
                }
            }
        }
    }
}

pub(super) fn has_pending(state: &LocalRuntimeState, owner: &Owner) -> bool {
    recordings_store::list(state, owner).is_ok_and(|records| {
        records.iter().any(|record| {
            record.receipt["status"] == "pending_export"
                || record.receipt["can_retry_export"] == true
        })
    })
}
