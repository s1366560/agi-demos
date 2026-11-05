//! Read bounded chunks of the exact recording admitted by the active engine.
use super::*;

pub(super) fn read(
    state: &LocalRuntimeState,
    owner: &Owner,
    context: &CuaCallContext,
    engine: &str,
    input: &Value,
) -> Result<Value, String> {
    let id = input["recording_id"]
        .as_str()
        .ok_or("cua_recording_required")?;
    let record = recordings_store::get(state, id)?.ok_or("cua_recording_not_owned")?;
    if record.owner != *owner
        || record.context != *context
        || record.engine_session_id.as_deref() != Some(engine)
    {
        return Err("cua_recording_not_owned".into());
    }
    if record.receipt["status"] != "saved" {
        return Err("cua_recording_not_saved".into());
    }
    let artifacts = record.receipt["artifacts"]
        .as_array()
        .ok_or("cua_recording_invalid")?;
    let artifact = match input.get("artifact_id") {
        Some(id) => artifacts
            .iter()
            .find(|artifact| artifact["artifact_id"] == *id),
        None if artifacts.len() == 1 => artifacts.first(),
        _ => None,
    }
    .ok_or("cua_recording_artifact_required")?;
    if artifact["mime_type"] != "audio/wav" {
        return Err("cua_recording_artifact_invalid".into());
    }
    let artifact_id = artifact["artifact_id"]
        .as_str()
        .ok_or("cua_recording_invalid")?;
    let offset = input
        .get("offset")
        .map(Value::as_u64)
        .unwrap_or(Some(0))
        .ok_or("cua_recording_offset_invalid")?;
    // Includes the conversation check missing from a UI owner's general player.
    artifacts::attachment(state, owner, &context.conversation_id, artifact_id)?;
    let descriptor = artifacts::descriptor(state, owner, artifact_id)?;
    let mut chunk = artifacts::audio_chunk(state, owner, artifact_id, offset)?;
    chunk["recording_id"] = json!(id);
    chunk["size_bytes"] = descriptor["size_bytes"].clone();
    Ok(chunk)
}
