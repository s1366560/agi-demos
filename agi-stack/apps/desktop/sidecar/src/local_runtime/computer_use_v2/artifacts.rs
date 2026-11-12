//! Persist authorized media before teardown; previews require the same device owner.
use super::Owner;
use crate::local_runtime::LocalRuntimeState;
use agistack_adapters_cua::CuaCallContext;
use agistack_core::ports::{CoreError, CoreResult, ToolResult};
use base64::{engine::general_purpose::STANDARD, Engine};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use uuid::Uuid;

pub(super) fn initialize(db: &Connection) -> Result<(), String> {
    db.execute_batch("CREATE TABLE IF NOT EXISTS desktop_cua_artifacts_v2 (
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,
        device_id TEXT NOT NULL,conversation_id TEXT NOT NULL,path TEXT NOT NULL,mime_type TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS desktop_cua_presentations_v2 (
        user_id TEXT NOT NULL,tenant_id TEXT NOT NULL,project_id TEXT NOT NULL,device_id TEXT NOT NULL,
        presentation_json TEXT NOT NULL,PRIMARY KEY(user_id,tenant_id,project_id,device_id));")
        .map_err(|error|error.to_string())
}

pub(super) async fn persist(
    state: &LocalRuntimeState,
    owner: &Owner,
    context: &CuaCallContext,
    result: &mut ToolResult,
) -> CoreResult<()> {
    let mut output: Value = serde_json::from_str(&result.output_json).unwrap_or(Value::Null);
    let has_audio = output
        .get("artifacts")
        .and_then(Value::as_array)
        .is_some_and(|artifacts| artifacts.iter().any(|artifact| artifact["kind"] == "audio"));
    if result.media.is_empty() && !has_audio && output.get("app_icon").is_none() {
        return Ok(());
    }
    let root = state
        .app_data_dir
        .as_ref()
        .ok_or_else(|| CoreError::Tool("cua_artifact_storage_unavailable".into()))?
        .join("computer-use-artifacts");
    tokio::fs::create_dir_all(&root)
        .await
        .map_err(|_| CoreError::Tool("cua_artifact_storage_unavailable".into()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        tokio::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700))
            .await
            .map_err(|_| CoreError::Tool("cua_artifact_permissions_failed".into()))?;
    }
    persist_icon(state, owner, context, &root, &mut output).await?;
    for media in &mut result.media {
        let (kind, extension) = match media.mime_type.as_str() {
            "image/png" => ("image", "png"),
            "image/jpeg" => ("image", "jpg"),
            "image/webp" => ("image", "webp"),
            "audio/wav" | "audio/x-wav" => ("audio", "wav"),
            "audio/mpeg" => ("audio", "mp3"),
            _ => return Err(CoreError::Tool("cua_media_type_invalid".into())),
        };
        let existing = state.session_store.connection().map_err(CoreError::Tool)?.query_row(
            "SELECT id FROM desktop_cua_artifacts_v2 WHERE path=?1 AND user_id=?2 AND tenant_id=?3 AND project_id=?4 AND device_id=?5 AND conversation_id=?6 AND mime_type=?7",
            params![media.artifact_path,owner.user_id,owner.tenant_id,owner.project_id,owner.device_id,context.conversation_id,media.mime_type],
            |row| row.get::<_,String>(0),
        ).optional().map_err(|_|CoreError::Tool("cua_artifact_lookup_failed".into()))?;
        if let Some(id) = existing {
            attachment(state, owner, &context.conversation_id, &id).map_err(CoreError::Tool)?;
            continue;
        }
        let metadata = tokio::fs::symlink_metadata(&media.artifact_path)
            .await
            .map_err(|_| CoreError::Tool("cua_artifact_not_found".into()))?;
        if !metadata.is_file()
            || metadata.file_type().is_symlink()
            || metadata.len() > (if kind == "audio" { 64 } else { 10 }) * 1024 * 1024
        {
            return Err(CoreError::Tool("cua_artifact_invalid".into()));
        }
        let id = format!("cua-{kind}-{}", Uuid::new_v4());
        let destination = root.join(format!("{id}.{extension}"));
        tokio::fs::copy(&media.artifact_path, &destination)
            .await
            .map_err(|_| CoreError::Tool("cua_artifact_copy_failed".into()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            tokio::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o600))
                .await
                .map_err(|_| CoreError::Tool("cua_artifact_permissions_failed".into()))?;
        }
        let db = state.session_store.connection().map_err(CoreError::Tool)?;
        db.execute(
            "INSERT INTO desktop_cua_artifacts_v2 VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
            params![
                id,
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id,
                context.conversation_id,
                destination.to_string_lossy(),
                media.mime_type
            ],
        )
        .map_err(|_| CoreError::Tool("cua_artifact_save_failed".into()))?;
        media.artifact_path = destination.to_string_lossy().into_owned();
        if output.get("screenshot").is_some() {
            output["screenshot"]["url"] = json!(format!("cua-artifact:{id}"));
            output["screenshot"]["artifact_id"] = json!(id);
        }
    }
    if let Some(artifacts) = output.get_mut("artifacts").and_then(Value::as_array_mut) {
        for artifact in artifacts
            .iter_mut()
            .filter(|artifact| artifact["kind"] == "audio")
        {
            // Recording finalization has already copied and scoped this artifact.
            if let Some(id) = artifact.get("artifact_id").and_then(Value::as_str) {
                if owned_path(
                    &*state.session_store.connection().map_err(CoreError::Tool)?,
                    owner,
                    id,
                )
                .map_err(CoreError::Tool)?
                .is_some()
                {
                    continue;
                }
                return Err(CoreError::Tool("cua_audio_artifact_not_owned".into()));
            }
            let url = artifact
                .get("url")
                .and_then(Value::as_str)
                .ok_or_else(|| CoreError::Tool("cua_audio_artifact_invalid".into()))?;
            let source = url::Url::parse(url)
                .ok()
                .and_then(|url| url.to_file_path().ok())
                .ok_or_else(|| CoreError::Tool("cua_audio_artifact_invalid".into()))?;
            let client = state.computer_use.client().map_err(CoreError::Tool)?;
            let helper_root = client
                .session_artifact_root(&context.session_id)
                .await
                .ok_or_else(|| CoreError::Tool("cua_artifact_owner_missing".into()))?;
            let helper_root = helper_root
                .canonicalize()
                .map_err(|_| CoreError::Tool("cua_artifact_root_missing".into()))?;
            let meta = tokio::fs::symlink_metadata(&source)
                .await
                .map_err(|_| CoreError::Tool("cua_audio_artifact_missing".into()))?;
            let source = source
                .canonicalize()
                .map_err(|_| CoreError::Tool("cua_audio_artifact_missing".into()))?;
            if !source.starts_with(helper_root)
                || meta.file_type().is_symlink()
                || !meta.is_file()
                || meta.len() > 64 * 1024 * 1024
                || artifact["mime_type"] != "audio/wav"
            {
                return Err(CoreError::Tool("cua_audio_artifact_not_owned".into()));
            }
            let id = format!("cua-audio-{}", Uuid::new_v4());
            let destination = root.join(format!("{id}.wav"));
            tokio::fs::copy(source, &destination)
                .await
                .map_err(|_| CoreError::Tool("cua_artifact_copy_failed".into()))?;
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                tokio::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o600))
                    .await
                    .map_err(|_| CoreError::Tool("cua_artifact_permissions_failed".into()))?;
            }
            let db = state.session_store.connection().map_err(CoreError::Tool)?;
            db.execute(
                "INSERT INTO desktop_cua_artifacts_v2 VALUES(?1,?2,?3,?4,?5,?6,?7,'audio/wav')",
                params![
                    id,
                    owner.user_id,
                    owner.tenant_id,
                    owner.project_id,
                    owner.device_id,
                    context.conversation_id,
                    destination.to_string_lossy()
                ],
            )
            .map_err(|_| CoreError::Tool("cua_artifact_save_failed".into()))?;
            artifact["url"] = json!(format!("cua-artifact:{id}"));
            artifact["artifact_id"] = json!(id);
        }
    }
    result.output_json = output.to_string();
    Ok(())
}

/// Application identity decoration is persisted without adding model media.
async fn persist_icon(
    state: &LocalRuntimeState,
    owner: &Owner,
    context: &CuaCallContext,
    root: &std::path::Path,
    output: &mut Value,
) -> CoreResult<()> {
    let Some(icon) = output.get("app_icon") else {
        return Ok(());
    };
    let source = icon
        .get("url")
        .and_then(Value::as_str)
        .and_then(|url| url::Url::parse(url).ok())
        .and_then(|url| url.to_file_path().ok())
        .ok_or_else(|| CoreError::Tool("cua_icon_invalid".into()))?;
    let helper_root = state
        .computer_use
        .client()
        .map_err(CoreError::Tool)?
        .session_artifact_root(&context.session_id)
        .await
        .ok_or_else(|| CoreError::Tool("cua_icon_owner_missing".into()))?;
    let helper_root = helper_root
        .canonicalize()
        .map_err(|_| CoreError::Tool("cua_icon_owner_missing".into()))?;
    let meta = tokio::fs::symlink_metadata(&source)
        .await
        .map_err(|_| CoreError::Tool("cua_icon_missing".into()))?;
    let canonical = source
        .canonicalize()
        .map_err(|_| CoreError::Tool("cua_icon_missing".into()))?;
    if !canonical.starts_with(helper_root)
        || meta.file_type().is_symlink()
        || !meta.is_file()
        || meta.len() > 1024 * 1024
        || icon["mime_type"] != "image/png"
        || icon["kind"] != "app_icon"
        || icon["width"] != 64
        || icon["height"] != 64
    {
        return Err(CoreError::Tool("cua_icon_not_owned".into()));
    }
    let dimension_path = canonical.clone();
    let dimensions = tokio::task::spawn_blocking(move || image::image_dimensions(dimension_path))
        .await
        .map_err(|_| CoreError::Tool("cua_icon_invalid".into()))?
        .map_err(|_| CoreError::Tool("cua_icon_invalid".into()))?;
    if dimensions != (64, 64) {
        return Err(CoreError::Tool("cua_icon_invalid".into()));
    }
    let id = format!("cua-image-{}", Uuid::new_v4());
    let destination = root.join(format!("{id}.png"));
    tokio::fs::copy(canonical, &destination)
        .await
        .map_err(|_| CoreError::Tool("cua_icon_copy_failed".into()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        tokio::fs::set_permissions(&destination, std::fs::Permissions::from_mode(0o600))
            .await
            .map_err(|_| CoreError::Tool("cua_icon_permissions_failed".into()))?;
    }
    state
        .session_store
        .connection()
        .map_err(CoreError::Tool)?
        .execute(
            "INSERT INTO desktop_cua_artifacts_v2 VALUES(?1,?2,?3,?4,?5,?6,?7,'image/png')",
            params![
                id,
                owner.user_id,
                owner.tenant_id,
                owner.project_id,
                owner.device_id,
                context.conversation_id,
                destination.to_string_lossy()
            ],
        )
        .map_err(|_| CoreError::Tool("cua_icon_save_failed".into()))?;
    output["app_icon"] = json!({"url":format!("cua-artifact:{id}"),"artifact_id":id,
        "mime_type":"image/png","width":64,"height":64,"kind":"app_icon"});
    Ok(())
}

pub(super) fn preview(state: &LocalRuntimeState, owner: &Owner, id: &str) -> Result<Value, String> {
    let (path, mime) = owned_path(&*state.session_store.connection()?, owner, id)?
        .ok_or("cua_artifact_not_found")?;
    let metadata = std::fs::symlink_metadata(&path).map_err(|_| "cua_artifact_not_found")?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 8 * 1024 * 1024
    {
        return Err("cua_artifact_invalid".into());
    }
    let root = state
        .app_data_dir
        .as_ref()
        .ok_or("cua_artifact_storage_unavailable")?
        .join("computer-use-artifacts")
        .canonicalize()
        .map_err(|_| "cua_artifact_storage_unavailable")?;
    let canonical = std::fs::canonicalize(&path).map_err(|_| "cua_artifact_not_found")?;
    if !canonical.starts_with(root) {
        return Err("cua_artifact_invalid".into());
    }
    let bytes = std::fs::read(canonical).map_err(|_| "cua_artifact_not_found")?;
    if !matches!(mime.as_str(), "image/png" | "image/jpeg" | "image/webp") {
        return Err("cua_preview_type_invalid".into());
    }
    Ok(
        json!({"artifact_id":id,"mime_type":mime,"data_url":format!("data:{mime};base64,{}",STANDARD.encode(bytes))}),
    )
}

pub(super) fn audio_chunk(
    state: &LocalRuntimeState,
    owner: &Owner,
    id: &str,
    offset: u64,
) -> Result<Value, String> {
    chunk(state, owner, id, offset, false)
}
pub(super) fn cloud_chunk(
    state: &LocalRuntimeState,
    owner: &Owner,
    id: &str,
    offset: u64,
) -> Result<Value, String> {
    let (_, mime) = owned_path(&*state.session_store.connection()?, owner, id)?
        .ok_or("cua_artifact_not_found")?;
    chunk(state, owner, id, offset, !mime.starts_with("audio/"))
}
pub(super) fn descriptor(
    state: &LocalRuntimeState,
    owner: &Owner,
    id: &str,
) -> Result<Value, String> {
    let (path, mime) = owned_path(&*state.session_store.connection()?, owner, id)?
        .ok_or("cua_artifact_not_found")?;
    let metadata = std::fs::symlink_metadata(path).map_err(|_| "cua_artifact_not_found")?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() > 64 * 1024 * 1024
    {
        return Err("cua_artifact_invalid".into());
    }
    Ok(json!({"artifact_id":id,"mime_type":mime,"size_bytes":metadata.len()}))
}
fn chunk(
    state: &LocalRuntimeState,
    owner: &Owner,
    id: &str,
    offset: u64,
    image: bool,
) -> Result<Value, String> {
    use std::io::{Read, Seek, SeekFrom};
    let (path, mime) = owned_path(&*state.session_store.connection()?, owner, id)?
        .ok_or("cua_artifact_not_found")?;
    let root = state
        .app_data_dir
        .as_ref()
        .ok_or("cua_artifact_storage_unavailable")?
        .join("computer-use-artifacts")
        .canonicalize()
        .map_err(|_| "cua_artifact_storage_unavailable")?;
    let metadata = std::fs::symlink_metadata(&path).map_err(|_| "cua_artifact_not_found")?;
    let canonical = std::fs::canonicalize(&path).map_err(|_| "cua_artifact_not_found")?;
    if (if image {
        !matches!(mime.as_str(), "image/png" | "image/jpeg" | "image/webp")
    } else {
        !matches!(mime.as_str(), "audio/wav" | "audio/x-wav" | "audio/mpeg")
    }) || metadata.file_type().is_symlink()
        || !metadata.is_file()
        || !canonical.starts_with(root)
        || metadata.len() > (if image { 10 } else { 64 }) * 1024 * 1024
        || offset > metadata.len()
    {
        return Err("cua_artifact_invalid".into());
    }
    let mut file = std::fs::File::open(canonical).map_err(|_| "cua_artifact_not_found")?;
    file.seek(SeekFrom::Start(offset))
        .map_err(|_| "cua_artifact_read_failed")?;
    let mut bytes = vec![0; 128 * 1024];
    let count = file
        .read(&mut bytes)
        .map_err(|_| "cua_artifact_read_failed")?;
    bytes.truncate(count);
    Ok(
        json!({"artifact_id":id,"mime_type":mime,"offset":offset,"next_offset":offset+count as u64,"eof":offset+count as u64==metadata.len(),"data_base64":STANDARD.encode(bytes)}),
    )
}
pub(super) fn media_descriptors(
    state: &LocalRuntimeState,
    owner: &Owner,
    media: &[agistack_core::agent::types::MediaAttachment],
) -> Result<Vec<Value>, String> {
    let db = state.session_store.connection()?;
    media.iter().map(|media| {
        let id:String=db.query_row("SELECT id FROM desktop_cua_artifacts_v2 WHERE path=?1 AND user_id=?2 AND tenant_id=?3 AND project_id=?4 AND device_id=?5 AND mime_type=?6",params![media.artifact_path,owner.user_id,owner.tenant_id,owner.project_id,owner.device_id,media.mime_type],|row|row.get(0)).map_err(|_|"cua_cloud_artifact_scope_invalid")?;
        let metadata=std::fs::symlink_metadata(&media.artifact_path).map_err(|_|"cua_artifact_not_found")?;
        if !metadata.is_file()||metadata.file_type().is_symlink()||metadata.len()>(if media.mime_type.starts_with("audio/"){64}else{10})*1024*1024{return Err("cua_artifact_invalid".into());}
        Ok(json!({"artifact_id":id,"mime_type":media.mime_type,"size_bytes":metadata.len()}))
    }).collect()
}

pub(super) fn attachment(
    state: &LocalRuntimeState,
    owner: &Owner,
    conversation: &str,
    id: &str,
) -> Result<agistack_core::agent::types::MediaAttachment, String> {
    let db = state.session_store.connection()?;
    let (path, mime): (String, String) = db.query_row(
        "SELECT path,mime_type FROM desktop_cua_artifacts_v2 WHERE id=?1 AND user_id=?2 AND tenant_id=?3 AND project_id=?4 AND device_id=?5 AND conversation_id=?6",
        params![id,owner.user_id,owner.tenant_id,owner.project_id,owner.device_id,conversation],
        |row|Ok((row.get(0)?,row.get(1)?)),
    ).map_err(|_|"cua_artifact_not_owned")?;
    let root = state
        .app_data_dir
        .as_ref()
        .ok_or("cua_artifact_storage_unavailable")?
        .join("computer-use-artifacts")
        .canonicalize()
        .map_err(|_| "cua_artifact_storage_unavailable")?;
    let metadata = std::fs::symlink_metadata(&path).map_err(|_| "cua_artifact_not_found")?;
    let canonical = std::fs::canonicalize(&path).map_err(|_| "cua_artifact_not_found")?;
    if !metadata.is_file()
        || metadata.file_type().is_symlink()
        || !canonical.starts_with(root)
        || metadata.len() > 64 * 1024 * 1024
    {
        return Err("cua_artifact_invalid".into());
    }
    Ok(agistack_core::agent::types::MediaAttachment {
        artifact_path: path,
        mime_type: mime,
    })
}

fn owned_path(
    db: &Connection,
    owner: &Owner,
    id: &str,
) -> Result<Option<(String, String)>, String> {
    db.query_row(
        "SELECT path,mime_type FROM desktop_cua_artifacts_v2 WHERE id=?1 AND user_id=?2
        AND tenant_id=?3 AND project_id=?4 AND device_id=?5",
        params![
            id,
            owner.user_id,
            owner.tenant_id,
            owner.project_id,
            owner.device_id
        ],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )
    .optional()
    .map_err(|error| error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn artifact_lookup_rejects_different_users_and_projects() {
        let db = Connection::open_in_memory().unwrap();
        initialize(&db).unwrap();
        db.execute("INSERT INTO desktop_cua_artifacts_v2 VALUES('id','user','tenant','project','device','conversation','/private/image.png','image/png')",[]).unwrap();
        let mut owner = Owner {
            user_id: "user".into(),
            tenant_id: "tenant".into(),
            project_id: "project".into(),
            device_id: "device".into(),
        };
        assert!(owned_path(&db, &owner, "id").unwrap().is_some());
        owner.project_id = "other".into();
        assert!(owned_path(&db, &owner, "id").unwrap().is_none());
        owner.project_id = "project".into();
        owner.user_id = "other".into();
        assert!(owned_path(&db, &owner, "id").unwrap().is_none());
    }
}
