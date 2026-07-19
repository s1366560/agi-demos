use super::*;

pub(super) fn validate_file_path(path: &str) -> Result<String, WorkspaceApiError> {
    let raw = if path.trim().is_empty() {
        "/".to_string()
    } else {
        path.replace('\\', "/").trim().to_string()
    };
    let mut parts = Vec::new();
    for part in raw.split('/') {
        if part.is_empty() || part == "." {
            continue;
        }
        if part == ".." {
            return Err(WorkspaceApiError::bad_request("Path traversal detected"));
        }
        if BLOCKED_FILE_SEGMENTS
            .iter()
            .any(|blocked| part.eq_ignore_ascii_case(blocked))
        {
            return Err(WorkspaceApiError::bad_request(format!(
                "Blocked path segment: {part}"
            )));
        }
        parts.push(part);
    }
    if parts.is_empty() {
        Ok("/".to_string())
    } else {
        Ok(format!("/{}/", parts.join("/")))
    }
}

pub(super) fn validate_filename(filename: &str) -> Result<String, WorkspaceApiError> {
    let normalized = filename.replace('\\', "/");
    if normalized.is_empty()
        || normalized.contains('/')
        || normalized == "."
        || normalized == ".."
        || normalized.contains('\0')
    {
        return Err(WorkspaceApiError::bad_request("Invalid filename"));
    }
    if BLOCKED_FILE_SEGMENTS
        .iter()
        .any(|blocked| normalized.eq_ignore_ascii_case(blocked))
    {
        return Err(WorkspaceApiError::bad_request(format!(
            "Blocked path segment: {normalized}"
        )));
    }
    Ok(normalized)
}

pub(super) fn join_child_path(parent_path: &str, name: &str) -> Result<String, WorkspaceApiError> {
    validate_file_path(&format!("{}/{}", parent_path.trim_end_matches('/'), name))
}

pub(super) fn split_directory_path(path: &str) -> Result<(String, String), WorkspaceApiError> {
    let normalized = validate_file_path(path)?;
    if normalized == "/" {
        return Err(WorkspaceApiError::bad_request(
            "Root directory has no file record",
        ));
    }
    let mut parts: Vec<&str> = normalized.trim_matches('/').split('/').collect();
    let name = parts
        .pop()
        .ok_or_else(|| WorkspaceApiError::bad_request("Invalid directory path"))?;
    let parent = if parts.is_empty() {
        "/".to_string()
    } else {
        format!("/{}/", parts.join("/"))
    };
    Ok((parent, name.to_string()))
}

pub(super) async fn require_directory_exists_pg(
    repo: &PgWorkspaceRepository,
    workspace_id: &str,
    path: &str,
) -> Result<(), WorkspaceApiError> {
    let (parent_path, name) = split_directory_path(path)?;
    let found = repo
        .find_file_by_path(workspace_id, &parent_path, &name)
        .await
        .map_err(WorkspaceApiError::internal)?;
    match found {
        Some(file) if file.is_directory => Ok(()),
        _ => Err(WorkspaceApiError::bad_request(
            "Destination directory not found",
        )),
    }
}

pub(super) async fn ensure_file_name_available_pg(
    repo: &PgWorkspaceRepository,
    workspace_id: &str,
    parent_path: &str,
    name: &str,
) -> Result<(), WorkspaceApiError> {
    if repo
        .find_file_by_path(workspace_id, parent_path, name)
        .await
        .map_err(WorkspaceApiError::internal)?
        .is_some()
    {
        Err(WorkspaceApiError::conflict("File already exists"))
    } else {
        Ok(())
    }
}

pub(super) fn map_file_storage_error(err: agistack_core::ports::CoreError) -> WorkspaceApiError {
    if err.to_string().contains("uq_blackboard_files_ws_path_name") {
        WorkspaceApiError::conflict("File already exists")
    } else {
        WorkspaceApiError::internal(err)
    }
}

pub(super) fn workspace_in_scope_dev(
    state: &DevWorkspaceState,
    service: &DevWorkspaceService,
    workspace_id: &str,
    tenant_id: &str,
    project_id: &str,
) -> bool {
    state
        .workspaces
        .get(workspace_id)
        .map(|workspace| service.workspace_matches(workspace, tenant_id, project_id))
        .unwrap_or(false)
}

pub(super) fn find_file_by_path_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    parent_path: &str,
    name: &str,
) -> Option<BlackboardFileRecord> {
    state
        .files
        .values()
        .find(|file| {
            file.workspace_id == workspace_id
                && file.parent_path == parent_path
                && file.name == name
        })
        .cloned()
}

pub(super) fn require_directory_exists_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    path: &str,
) -> Result<(), WorkspaceApiError> {
    let (parent_path, name) = split_directory_path(path)?;
    match find_file_by_path_dev(state, workspace_id, &parent_path, &name) {
        Some(file) if file.is_directory => Ok(()),
        _ => Err(WorkspaceApiError::bad_request(
            "Destination directory not found",
        )),
    }
}

pub(super) fn ensure_file_name_available_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    parent_path: &str,
    name: &str,
) -> Result<(), WorkspaceApiError> {
    if find_file_by_path_dev(state, workspace_id, parent_path, name).is_some() {
        Err(WorkspaceApiError::conflict("File already exists"))
    } else {
        Ok(())
    }
}

pub(super) fn list_files_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    parent_path: &str,
) -> Vec<BlackboardFileRecord> {
    let mut files: Vec<_> = state
        .files
        .values()
        .filter(|file| file.workspace_id == workspace_id && file.parent_path == parent_path)
        .cloned()
        .collect();
    sort_files(&mut files);
    files
}

pub(super) fn find_descendants_dev(
    state: &DevWorkspaceState,
    workspace_id: &str,
    path_prefix: &str,
) -> Vec<BlackboardFileRecord> {
    let mut files: Vec<_> = state
        .files
        .values()
        .filter(|file| {
            file.workspace_id == workspace_id && file.parent_path.starts_with(path_prefix)
        })
        .cloned()
        .collect();
    files.sort_by(|a, b| {
        a.parent_path
            .cmp(&b.parent_path)
            .then(b.is_directory.cmp(&a.is_directory))
            .then(a.name.cmp(&b.name))
    });
    files
}

pub(super) fn sort_files(files: &mut [BlackboardFileRecord]) {
    files.sort_by(|a, b| {
        b.is_directory
            .cmp(&a.is_directory)
            .then(a.name.cmp(&b.name))
    });
}

pub(super) fn bulk_update_parent_path_dev(
    state: &mut DevWorkspaceState,
    workspace_id: &str,
    old_prefix: &str,
    new_prefix: &str,
) {
    for file in state.files.values_mut() {
        if file.workspace_id == workspace_id {
            if file.parent_path == old_prefix {
                file.parent_path = new_prefix.to_string();
            } else if let Some(suffix) = file.parent_path.strip_prefix(old_prefix) {
                file.parent_path = format!("{new_prefix}{suffix}");
            }
        }
    }
}

pub(super) fn object_key(workspace_id: &str, storage_key: &str) -> String {
    format!(
        "workspace-files/{}/{}",
        workspace_id.trim_matches('/'),
        storage_key.trim_start_matches('/')
    )
}

pub(super) fn file_event_payload(workspace_id: &str, view: &BlackboardFileView) -> Value {
    json!({
        "file": view,
        "workspace_id": workspace_id,
        "file_id": view.id,
        "parent_path": view.parent_path,
        "name": view.name,
        "is_directory": view.is_directory,
    })
}

pub(super) fn guess_content_type(filename: &str) -> String {
    match filename
        .rsplit('.')
        .next()
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "txt" | "md" | "log" => "text/plain",
        "json" => "application/json",
        "csv" => "text/csv",
        "html" | "htm" => "text/html",
        "css" => "text/css",
        "js" | "mjs" => "text/javascript",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "pdf" => "application/pdf",
        _ => "application/octet-stream",
    }
    .to_string()
}

pub(super) fn content_disposition(filename: &str) -> String {
    let escaped = filename.replace('\\', "\\\\").replace('"', "\\\"");
    format!("attachment; filename=\"{escaped}\"")
}

pub(super) async fn copy_single_file_pg(
    repo: &PgWorkspaceRepository,
    object_store: Arc<dyn ObjectStore>,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let bytes = object_store
        .get(&object_key(workspace_id, &source.storage_key))
        .await
        .map_err(WorkspaceApiError::internal)?
        .ok_or_else(|| WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found"))?;
    let new_id = new_id();
    let storage_key = format!("{new_id}/{copy_name}");
    object_store
        .put(
            &object_key(workspace_id, &storage_key),
            bytes,
            Some(&source.content_type),
        )
        .await
        .map_err(WorkspaceApiError::internal)?;
    repo.create_file(BlackboardFileRecord {
        id: new_id,
        workspace_id: workspace_id.to_string(),
        parent_path: target_parent.to_string(),
        name: copy_name.to_string(),
        is_directory: false,
        file_size: source.file_size,
        content_type: source.content_type.clone(),
        storage_key,
        uploader_type: "user".to_string(),
        uploader_id: user_id.to_string(),
        uploader_name: user_id.to_string(),
        checksum_sha256: source.checksum_sha256.clone(),
        mime_type_detected: source.mime_type_detected.clone(),
        created_at: Utc::now(),
    })
    .await
    .map_err(map_file_storage_error)
}

pub(super) async fn copy_directory_pg(
    repo: &PgWorkspaceRepository,
    object_store: Arc<dyn ObjectStore>,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let old_prefix = join_child_path(&source.parent_path, &source.name)?;
    let descendants = repo
        .find_file_descendants(workspace_id, &old_prefix)
        .await
        .map_err(WorkspaceApiError::internal)?;
    if descendants.len() + 1 > MAX_COPY_ENTRIES {
        return Err(WorkspaceApiError::bad_request(
            "Directory copy is too large",
        ));
    }
    let root = repo
        .create_file(BlackboardFileRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            parent_path: target_parent.to_string(),
            name: copy_name.to_string(),
            is_directory: true,
            file_size: 0,
            content_type: String::new(),
            storage_key: String::new(),
            uploader_type: "user".to_string(),
            uploader_id: user_id.to_string(),
            uploader_name: user_id.to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at: Utc::now(),
        })
        .await
        .map_err(map_file_storage_error)?;
    let new_prefix = join_child_path(target_parent, copy_name)?;
    // Directory rows are cheap DB inserts — create them sequentially in
    // descendant order. File copies each pay an object-store get+put plus the
    // DB row, so run them in bounded concurrent chunks instead of strictly
    // serially (a large directory copy was user-visible latency). Chunk-local
    // first error still aborts; the copy was never atomic to begin with.
    let mut pending_files = Vec::new();
    for descendant in &descendants {
        let target_desc_parent =
            replace_parent_prefix(&descendant.parent_path, &old_prefix, &new_prefix);
        if descendant.is_directory {
            repo.create_file(BlackboardFileRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                parent_path: target_desc_parent,
                name: descendant.name.clone(),
                is_directory: true,
                file_size: 0,
                content_type: String::new(),
                storage_key: String::new(),
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            })
            .await
            .map_err(map_file_storage_error)?;
        } else {
            pending_files.push((descendant, target_desc_parent));
        }
    }
    for chunk in pending_files.chunks(COPY_FANOUT_CONCURRENCY) {
        let mut pending = Vec::with_capacity(chunk.len());
        for (descendant, target_desc_parent) in chunk {
            pending.push(copy_single_file_pg(
                repo,
                Arc::clone(&object_store),
                workspace_id,
                user_id,
                descendant,
                target_desc_parent,
                &descendant.name,
            ));
        }
        futures_util::future::join_all(pending)
            .await
            .into_iter()
            .collect::<Result<Vec<_>, _>>()?;
    }
    Ok(root)
}

pub(super) async fn copy_single_file_dev(
    service: &DevWorkspaceService,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let bytes = service
        .object_store
        .get(&service.object_key(workspace_id, &source.storage_key))
        .await
        .map_err(WorkspaceApiError::internal)?
        .ok_or_else(|| WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found"))?;
    let new_id = new_id();
    let storage_key = format!("{new_id}/{copy_name}");
    service
        .object_store
        .put(
            &service.object_key(workspace_id, &storage_key),
            bytes,
            Some(&source.content_type),
        )
        .await
        .map_err(WorkspaceApiError::internal)?;
    let clone = BlackboardFileRecord {
        id: new_id,
        workspace_id: workspace_id.to_string(),
        parent_path: target_parent.to_string(),
        name: copy_name.to_string(),
        is_directory: false,
        file_size: source.file_size,
        content_type: source.content_type.clone(),
        storage_key,
        uploader_type: "user".to_string(),
        uploader_id: user_id.to_string(),
        uploader_name: user_id.to_string(),
        checksum_sha256: source.checksum_sha256.clone(),
        mime_type_detected: source.mime_type_detected.clone(),
        created_at: Utc::now(),
    };
    service
        .lock_state()?
        .files
        .insert(clone.id.clone(), clone.clone());
    Ok(clone)
}

pub(super) async fn copy_directory_dev(
    service: &DevWorkspaceService,
    workspace_id: &str,
    user_id: &str,
    source: &BlackboardFileRecord,
    target_parent: &str,
    copy_name: &str,
) -> Result<BlackboardFileRecord, WorkspaceApiError> {
    let old_prefix = join_child_path(&source.parent_path, &source.name)?;
    let descendants = {
        let state = service.lock_state()?;
        find_descendants_dev(&state, workspace_id, &old_prefix)
    };
    if descendants.len() + 1 > MAX_COPY_ENTRIES {
        return Err(WorkspaceApiError::bad_request(
            "Directory copy is too large",
        ));
    }
    let root = BlackboardFileRecord {
        id: new_id(),
        workspace_id: workspace_id.to_string(),
        parent_path: target_parent.to_string(),
        name: copy_name.to_string(),
        is_directory: true,
        file_size: 0,
        content_type: String::new(),
        storage_key: String::new(),
        uploader_type: "user".to_string(),
        uploader_id: user_id.to_string(),
        uploader_name: user_id.to_string(),
        checksum_sha256: None,
        mime_type_detected: None,
        created_at: Utc::now(),
    };
    service
        .lock_state()?
        .files
        .insert(root.id.clone(), root.clone());
    let new_prefix = join_child_path(target_parent, copy_name)?;
    for descendant in descendants {
        let target_desc_parent =
            replace_parent_prefix(&descendant.parent_path, &old_prefix, &new_prefix);
        if descendant.is_directory {
            let clone = BlackboardFileRecord {
                id: new_id(),
                workspace_id: workspace_id.to_string(),
                parent_path: target_desc_parent,
                name: descendant.name,
                is_directory: true,
                file_size: 0,
                content_type: String::new(),
                storage_key: String::new(),
                uploader_type: "user".to_string(),
                uploader_id: user_id.to_string(),
                uploader_name: user_id.to_string(),
                checksum_sha256: None,
                mime_type_detected: None,
                created_at: Utc::now(),
            };
            service.lock_state()?.files.insert(clone.id.clone(), clone);
        } else {
            copy_single_file_dev(
                service,
                workspace_id,
                user_id,
                &descendant,
                &target_desc_parent,
                &descendant.name,
            )
            .await?;
        }
    }
    Ok(root)
}

pub(super) fn replace_parent_prefix(
    parent_path: &str,
    old_prefix: &str,
    new_prefix: &str,
) -> String {
    if parent_path == old_prefix {
        new_prefix.to_string()
    } else if let Some(suffix) = parent_path.strip_prefix(old_prefix) {
        format!("{new_prefix}{suffix}")
    } else {
        parent_path.to_string()
    }
}

pub(super) async fn parse_upload(
    mut multipart: Multipart,
) -> Result<BlackboardUpload, WorkspaceApiError> {
    let mut parent_path = "/".to_string();
    let mut filename = None;
    let mut content_type = None;
    let mut bytes = None;
    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|err| WorkspaceApiError::bad_request(format!("Invalid multipart upload: {err}")))?
    {
        let name = field.name().map(str::to_string);
        match name.as_deref() {
            Some("parent_path") => {
                parent_path = field.text().await.map_err(|err| {
                    WorkspaceApiError::bad_request(format!("Invalid multipart upload: {err}"))
                })?;
            }
            Some("file") => {
                filename = Some(field.file_name().unwrap_or("unnamed").to_string());
                content_type = field.content_type().map(str::to_string);
                bytes = Some(
                    field
                        .bytes()
                        .await
                        .map_err(|err| {
                            WorkspaceApiError::bad_request(format!(
                                "Invalid multipart upload: {err}"
                            ))
                        })?
                        .to_vec(),
                );
            }
            _ => {}
        }
    }
    Ok(BlackboardUpload {
        parent_path,
        filename: filename.unwrap_or_else(|| "unnamed".to_string()),
        content_type,
        bytes: bytes.ok_or_else(|| WorkspaceApiError::bad_request("Missing upload file"))?,
    })
}

pub(super) fn response_with_headers(
    status: StatusCode,
    download: &BlackboardFileDownload,
    bytes: Vec<u8>,
) -> Result<Response, WorkspaceApiError> {
    let mut response = Response::builder().status(status);
    let headers = response
        .headers_mut()
        .ok_or_else(|| WorkspaceApiError::internal("response headers unavailable"))?;
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_str(&download.content_type)
            .map_err(|err| WorkspaceApiError::internal(format!("content-type: {err}")))?,
    );
    headers.insert(
        CONTENT_DISPOSITION,
        HeaderValue::from_str(&content_disposition(&download.filename))
            .map_err(|err| WorkspaceApiError::internal(format!("content-disposition: {err}")))?,
    );
    headers.insert(
        CONTENT_LENGTH,
        HeaderValue::from_str(&download.file_size.max(0).to_string())
            .map_err(|err| WorkspaceApiError::internal(format!("content-length: {err}")))?,
    );
    headers.insert(CACHE_CONTROL, HeaderValue::from_static("private, no-cache"));
    headers.insert(ACCEPT_RANGES, HeaderValue::from_static("bytes"));
    headers.insert(
        ETAG,
        HeaderValue::from_str(&download.etag)
            .map_err(|err| WorkspaceApiError::internal(format!("etag: {err}")))?,
    );
    response
        .body(Body::from(bytes))
        .map_err(|err| WorkspaceApiError::internal(format!("response body: {err}")))
}
