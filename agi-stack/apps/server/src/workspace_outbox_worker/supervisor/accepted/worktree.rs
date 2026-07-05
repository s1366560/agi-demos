use super::super::*;

struct WorktreeIntegrationEvent<'a> {
    workspace_id: &'a str,
    node: &'a WorkspacePlanNodeRecord,
    attempt_id: &'a str,
    task: &'a WorkspaceTaskRecord,
    metadata: &'a Map<String, Value>,
    event_type: &'a str,
    now: DateTime<Utc>,
}

impl SupervisorTickAdmissionHandler {
    pub(in crate::workspace_outbox_worker::supervisor) async fn project_accepted_attempt_to_task(
        &self,
        projection: AcceptedAttemptTaskProjection<'_>,
    ) -> CoreResult<Option<Map<String, Value>>> {
        let AcceptedAttemptTaskProjection {
            workspace_id,
            node,
            attempt,
            summary,
            evidence_refs,
            commit_ref,
            git_diff_summary,
            test_commands,
            now,
        } = projection;
        let task_id = node
            .workspace_task_id
            .as_ref()
            .unwrap_or(&attempt.workspace_task_id);
        let Some(mut task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(Some(Map::new()));
        };
        if task.workspace_id != workspace_id {
            return Ok(Some(Map::new()));
        }

        let integration_metadata = self
            .integrate_accepted_attempt_worktree(
                workspace_id,
                node,
                &attempt.id,
                &task,
                commit_ref,
                now,
            )
            .await?;
        let Some(integration_metadata) = integration_metadata else {
            return Ok(None);
        };

        let mut metadata = object_or_empty(task.metadata_json.clone());
        metadata.insert("pending_leader_adjudication".to_string(), json!(false));
        metadata.remove("retry_verification_only");
        metadata.insert("durable_plan_verdict".to_string(), json!("accepted"));
        metadata.insert(
            "durable_plan_verification_summary".to_string(),
            json!(summary),
        );
        metadata.insert(
            "durable_plan_verified_at".to_string(),
            json!(now.to_rfc3339()),
        );
        metadata.insert(
            "last_attempt_status".to_string(),
            json!(ACCEPTED_ATTEMPT_STATUS),
        );
        metadata.insert("last_attempt_id".to_string(), json!(attempt.id.clone()));
        metadata.insert(CURRENT_ATTEMPT_ID.to_string(), json!(attempt.id.clone()));
        metadata.insert("last_worker_report_type".to_string(), json!("completed"));
        metadata.insert("last_worker_report_summary".to_string(), json!(summary));
        metadata.insert(
            "last_leader_adjudication_status".to_string(),
            json!(ACCEPTED_ATTEMPT_STATUS),
        );
        if !evidence_refs.is_empty() {
            metadata.insert("evidence_refs".to_string(), json!(evidence_refs));
        }
        apply_verification_checkpoint_metadata(
            &mut metadata,
            summary,
            commit_ref,
            git_diff_summary,
            test_commands,
            now,
        );
        metadata.extend(integration_metadata.clone());

        task.metadata_json = Value::Object(metadata);
        task.status = "done".to_string();
        task.blocker_reason = None;
        task.completed_at = Some(now);
        task.updated_at = Some(now);
        let saved_task = self.store.save_task(task).await?;
        self.reconcile_root_goal_progress_for_task(workspace_id, &saved_task, attempt, now)
            .await?;
        Ok(Some(integration_metadata))
    }

    async fn integrate_accepted_attempt_worktree(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt_id: &str,
        task: &WorkspaceTaskRecord,
        commit_ref: Option<&str>,
        now: DateTime<Utc>,
    ) -> CoreResult<Option<Map<String, Value>>> {
        let Some(commit_ref) = commit_ref
            .and_then(commit_ref_token)
            .or_else(|| accepted_attempt_integration_commit_ref(node))
        else {
            return Ok(Some(Map::new()));
        };
        let Some(workspace) = self.store.get_workspace(workspace_id).await? else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "workspace not found",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        let Some(sandbox_code_root) =
            sandbox_code_root_for_integration(&task.metadata_json, &workspace.metadata_json)
        else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "sandbox_code_root is not available for accepted worktree integration",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        let Some(worktree_path) = accepted_attempt_worktree_path(
            node,
            &task.metadata_json,
            &sandbox_code_root,
            attempt_id,
        ) else {
            return Ok(Some(worktree_integration_metadata(
                "skipped",
                "accepted attempt has no worktree_path",
                attempt_id,
                Some(commit_ref.as_str()),
                None,
                now,
                None,
            )));
        };
        if normalize_posix_path(&worktree_path) == normalize_posix_path(&sandbox_code_root) {
            let metadata = worktree_integration_metadata(
                "already_merged",
                "accepted attempt already ran in sandbox_code_root",
                attempt_id,
                Some(commit_ref.as_str()),
                Some(worktree_path.as_str()),
                now,
                None,
            );
            self.record_worktree_integration_event(WorktreeIntegrationEvent {
                workspace_id,
                node,
                attempt_id,
                task,
                metadata: &metadata,
                event_type: "accepted_worktree_integration_skipped",
                now,
            })
            .await?;
            return Ok(Some(metadata));
        }
        let integration = integrate_accepted_attempt_worktree_with_git(
            Path::new(&sandbox_code_root),
            Path::new(&worktree_path),
            &commit_ref,
        )
        .await?;
        let metadata = worktree_integration_metadata(
            &integration.status,
            &integration.summary,
            attempt_id,
            Some(integration.commit_ref.as_str()),
            Some(worktree_path.as_str()),
            now,
            integration.dirty_signature.as_deref(),
        );
        let event_type = worktree_integration_event_type(&integration.status);
        self.record_worktree_integration_event(WorktreeIntegrationEvent {
            workspace_id,
            node,
            attempt_id,
            task,
            metadata: &metadata,
            event_type,
            now,
        })
        .await?;
        Ok(Some(metadata))
    }

    async fn record_worktree_integration_event(
        &self,
        event: WorktreeIntegrationEvent<'_>,
    ) -> CoreResult<()> {
        let WorktreeIntegrationEvent {
            workspace_id,
            node,
            attempt_id,
            task,
            metadata,
            event_type,
            now,
        } = event;
        self.store
            .create_plan_event(WorkspacePlanEventRecord {
                id: generate_uuid_v4(),
                plan_id: node.plan_id.clone(),
                workspace_id: workspace_id.to_string(),
                node_id: Some(node.id.clone()),
                attempt_id: Some(attempt_id.to_string()),
                event_type: event_type.to_string(),
                source: "workspace_plan.accepted_worktree_integration".to_string(),
                actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                payload_json: json!({
                    "status": metadata.get("worktree_integration_status").cloned().unwrap_or(Value::Null),
                    "summary": metadata.get("worktree_integration_summary").cloned().unwrap_or(Value::Null),
                    "commit_ref": metadata.get("worktree_integration_commit_ref").cloned().unwrap_or(Value::Null),
                    "worktree_path": metadata.get("worktree_integration_worktree_path").cloned().unwrap_or(Value::Null),
                    "workspace_task_id": task.id.clone(),
                    "dirty_signature": metadata.get("worktree_integration_dirty_signature").cloned().unwrap_or(Value::Null),
                }),
                created_at: now,
            })
            .await?;
        Ok(())
    }

    pub(super) async fn accepted_projection_already_complete(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
    ) -> CoreResult<bool> {
        let metadata = object_or_empty(node.metadata_json.clone());
        if !accepted_projection_already_complete_base(node, attempt, &metadata) {
            return Ok(false);
        }
        if metadata_string(metadata.get("worktree_integration_status")).as_deref()
            != Some("blocked_dirty_main")
        {
            return Ok(true);
        }
        self.blocked_dirty_main_projection_still_current(workspace_id, node, attempt, &metadata)
            .await
    }

    async fn blocked_dirty_main_projection_still_current(
        &self,
        workspace_id: &str,
        node: &WorkspacePlanNodeRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        metadata: &Map<String, Value>,
    ) -> CoreResult<bool> {
        let task_id = node
            .workspace_task_id
            .as_ref()
            .unwrap_or(&attempt.workspace_task_id);
        let Some(task) = self.store.get_task(workspace_id, task_id).await? else {
            return Ok(false);
        };
        if task.workspace_id != workspace_id {
            return Ok(false);
        }
        let task_metadata = object_or_empty(task.metadata_json.clone());
        let Some(stored_signature) =
            metadata_string(metadata.get("worktree_integration_dirty_signature")).or_else(|| {
                metadata_string(task_metadata.get("worktree_integration_dirty_signature"))
            })
        else {
            return Ok(false);
        };
        let Some(workspace) = self.store.get_workspace(workspace_id).await? else {
            return Ok(false);
        };
        let Some(sandbox_code_root) =
            sandbox_code_root_for_integration(&task.metadata_json, &workspace.metadata_json)
        else {
            return Ok(false);
        };
        let current = current_worktree_dirty_signature(Path::new(&sandbox_code_root)).await?;
        Ok(current.as_deref() == Some(stored_signature.as_str()))
    }
}
