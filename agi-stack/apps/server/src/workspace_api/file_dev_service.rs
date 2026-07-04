use super::*;

impl DevWorkspaceService {
    pub(super) async fn dev_list_files(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        query: BlackboardFileListQuery,
    ) -> Result<BlackboardFileListView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let parent_path = files::validate_file_path(query.parent_path.as_deref().unwrap_or("/"))?;
        let state = self.lock_state()?;
        if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut files: Vec<_> = state
            .files
            .values()
            .filter(|file| file.workspace_id == workspace_id && file.parent_path == parent_path)
            .cloned()
            .collect();
        files::sort_files(&mut files);
        Ok(BlackboardFileListView {
            items: files.into_iter().map(BlackboardFileView::from).collect(),
        })
    }

    pub(super) async fn dev_create_directory(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        body: MkdirPayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let parent_path = files::validate_file_path(&body.parent_path)?;
        let name = files::validate_filename(&body.name)?;
        let mut state = self.lock_state()?;
        if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        if parent_path != "/" {
            files::require_directory_exists_dev(&state, workspace_id, &parent_path)?;
        }
        files::ensure_file_name_available_dev(&state, workspace_id, &parent_path, &name)?;
        let file = BlackboardFileRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            parent_path,
            name,
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
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: files::file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    pub(super) async fn dev_upload_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        upload: BlackboardUpload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if upload.bytes.len() > MAX_FILE_SIZE {
            return Err(WorkspaceApiError::bad_request(format!(
                "File exceeds maximum size of {MAX_FILE_SIZE} bytes"
            )));
        }
        let parent_path = files::validate_file_path(&upload.parent_path)?;
        let filename = files::validate_filename(&upload.filename)?;
        {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            if parent_path != "/" {
                files::require_directory_exists_dev(&state, workspace_id, &parent_path)?;
            }
            files::ensure_file_name_available_dev(&state, workspace_id, &parent_path, &filename)?;
        }
        let file_id = new_id();
        let content_type = upload
            .content_type
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| files::guess_content_type(&filename));
        let file_size = upload.bytes.len().min(i32::MAX as usize) as i32;
        let storage_key = format!("{file_id}/{filename}");
        self.object_store
            .put(
                &self.object_key(workspace_id, &storage_key),
                upload.bytes,
                Some(&content_type),
            )
            .await
            .map_err(WorkspaceApiError::internal)?;
        let file = BlackboardFileRecord {
            id: file_id,
            workspace_id: workspace_id.to_string(),
            parent_path,
            name: filename,
            is_directory: false,
            file_size,
            content_type,
            storage_key,
            uploader_type: "user".to_string(),
            uploader_id: user_id.to_string(),
            uploader_name: user_id.to_string(),
            checksum_sha256: None,
            mime_type_detected: None,
            created_at: Utc::now(),
        };
        let mut state = self.lock_state()?;
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: files::file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    pub(super) async fn dev_download_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
    ) -> Result<BlackboardFileDownload, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let file = {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?
        };
        if file.is_directory {
            return Err(WorkspaceApiError::bad_request(
                "Cannot read directory content",
            ));
        }
        let bytes = self
            .object_store
            .get(&self.object_key(workspace_id, &file.storage_key))
            .await
            .map_err(WorkspaceApiError::internal)?
            .ok_or_else(|| {
                WorkspaceApiError::new(StatusCode::NOT_FOUND, "File content not found")
            })?;
        Ok(BlackboardFileDownload {
            filename: file.name,
            content_type: if file.content_type.is_empty() {
                "application/octet-stream".to_string()
            } else {
                file.content_type
            },
            file_size: file.file_size,
            etag: file
                .checksum_sha256
                .map(|checksum| format!("\"{checksum}\""))
                .unwrap_or_else(|| format!("W/\"sz-{}-id-{}\"", file.file_size, file.id)),
            bytes,
        })
    }

    pub(super) async fn dev_patch_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: RenameOrMoveFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        if body.name.is_none() && body.parent_path.is_none() {
            return Err(WorkspaceApiError::bad_request(
                "Provide at least one of 'name' or 'parent_path'",
            ));
        }
        let mut state = self.lock_state()?;
        if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
            return Err(WorkspaceApiError::workspace_not_found());
        }
        let mut file = state
            .files
            .get(file_id)
            .filter(|file| file.workspace_id == workspace_id)
            .cloned()
            .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
        if let Some(parent_path) = body.parent_path {
            let target_parent = files::validate_file_path(&parent_path)?;
            if target_parent != file.parent_path {
                if target_parent != "/" {
                    files::require_directory_exists_dev(&state, workspace_id, &target_parent)?;
                }
                if file.is_directory {
                    let own_prefix = files::join_child_path(&file.parent_path, &file.name)?;
                    if target_parent == own_prefix || target_parent.starts_with(&own_prefix) {
                        return Err(WorkspaceApiError::bad_request(
                            "Cannot move a directory into itself",
                        ));
                    }
                    let new_prefix = files::join_child_path(&target_parent, &file.name)?;
                    files::bulk_update_parent_path_dev(
                        &mut state,
                        workspace_id,
                        &own_prefix,
                        &new_prefix,
                    );
                }
                files::ensure_file_name_available_dev(
                    &state,
                    workspace_id,
                    &target_parent,
                    &file.name,
                )?;
                file.parent_path = target_parent;
            }
        }
        if let Some(name) = body.name {
            let safe_name = files::validate_filename(&name)?;
            if safe_name != file.name {
                files::ensure_file_name_available_dev(
                    &state,
                    workspace_id,
                    &file.parent_path,
                    &safe_name,
                )?;
                if file.is_directory {
                    let old_prefix = files::join_child_path(&file.parent_path, &file.name)?;
                    let new_prefix = files::join_child_path(&file.parent_path, &safe_name)?;
                    files::bulk_update_parent_path_dev(
                        &mut state,
                        workspace_id,
                        &old_prefix,
                        &new_prefix,
                    );
                }
                file.name = safe_name;
            }
        }
        state.files.insert(file.id.clone(), file.clone());
        let view = BlackboardFileView::from(file);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_updated".to_string(),
            payload_json: json!({ "file": view, "file_id": view.id }),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    pub(super) async fn dev_copy_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        body: CopyFilePayload,
    ) -> Result<BlackboardFileView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let source;
        let target_parent = files::validate_file_path(&body.target_parent_path)?;
        let copy_name;
        {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            source = state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
            if target_parent != "/" {
                files::require_directory_exists_dev(&state, workspace_id, &target_parent)?;
            }
            copy_name = files::validate_filename(body.name.as_deref().unwrap_or(&source.name))?;
            files::ensure_file_name_available_dev(
                &state,
                workspace_id,
                &target_parent,
                &copy_name,
            )?;
        }
        let copied = if source.is_directory {
            files::copy_directory_dev(
                self,
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        } else {
            files::copy_single_file_dev(
                self,
                workspace_id,
                user_id,
                &source,
                &target_parent,
                &copy_name,
            )
            .await?
        };
        let mut state = self.lock_state()?;
        let view = BlackboardFileView::from(copied);
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: "blackboard_file_created".to_string(),
            payload_json: files::file_event_payload(workspace_id, &view),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(view)
    }

    pub(super) async fn dev_delete_file(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
        workspace_id: &str,
        file_id: &str,
        query: DeleteFileQuery,
    ) -> Result<DeletedView, WorkspaceApiError> {
        self.require_dev_user(user_id)?;
        let (file, descendants) = {
            let state = self.lock_state()?;
            if !files::workspace_in_scope_dev(&state, self, workspace_id, tenant_id, project_id) {
                return Err(WorkspaceApiError::workspace_not_found());
            }
            let file = state
                .files
                .get(file_id)
                .filter(|file| file.workspace_id == workspace_id)
                .cloned()
                .ok_or_else(WorkspaceApiError::blackboard_not_found)?;
            let descendants = if file.is_directory {
                let child_path = files::join_child_path(&file.parent_path, &file.name)?;
                let children = files::list_files_dev(&state, workspace_id, &child_path);
                if !children.is_empty() && !query.recursive {
                    return Err(WorkspaceApiError::bad_request("Directory is not empty"));
                }
                files::find_descendants_dev(&state, workspace_id, &child_path)
            } else {
                Vec::new()
            };
            (file, descendants)
        };
        for descendant in &descendants {
            if !descendant.is_directory && !descendant.storage_key.is_empty() {
                self.object_store
                    .delete(&self.object_key(workspace_id, &descendant.storage_key))
                    .await
                    .map_err(WorkspaceApiError::internal)?;
            }
        }
        if !file.is_directory && !file.storage_key.is_empty() {
            self.object_store
                .delete(&self.object_key(workspace_id, &file.storage_key))
                .await
                .map_err(WorkspaceApiError::internal)?;
        }
        let mut state = self.lock_state()?;
        for descendant in descendants {
            state.files.remove(&descendant.id);
        }
        if state.files.remove(file_id).is_none() {
            return Err(WorkspaceApiError::blackboard_not_found());
        }
        state.outbox.push(BlackboardOutboxRecord {
            id: new_id(),
            workspace_id: workspace_id.to_string(),
            tenant_id: tenant_id.to_string(),
            project_id: project_id.to_string(),
            event_type: if file.is_directory {
                "blackboard_directory_deleted".to_string()
            } else {
                "blackboard_file_deleted".to_string()
            },
            payload_json: json!({
                "workspace_id": workspace_id,
                "file_id": file_id,
                "deleted": true,
                "recursive": query.recursive,
                "is_directory": file.is_directory
            }),
            metadata_json: json!({ "tenant_id": tenant_id, "project_id": project_id }),
            correlation_id: None,
        });
        Ok(DeletedView { deleted: true })
    }
}
