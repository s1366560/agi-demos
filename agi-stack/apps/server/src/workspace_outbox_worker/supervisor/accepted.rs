use super::*;

impl SupervisorTickAdmissionHandler {
    pub(super) async fn reopen_failed_worktree_integration_nodes(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if !done_node_needs_worktree_integration_retry(&node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };

            let now = Utc::now();
            let previous_metadata = object_or_empty(node.metadata_json.clone());
            let previous_attempt_id =
                metadata_string(previous_metadata.get("worktree_integration_attempt_id"))
                    .or_else(|| node.current_attempt_id.clone());
            let previous_commit_ref = node_verified_commit_ref(&node);
            let previous_summary =
                metadata_string(previous_metadata.get("worktree_integration_summary"))
                    .unwrap_or_else(|| "accepted worktree integration failed".to_string());

            let mut metadata =
                clear_failed_worktree_retry_stale_attempt_metadata(previous_metadata);
            metadata.insert("last_verification_passed".to_string(), json!(false));
            metadata.insert(
                "last_verification_summary".to_string(),
                json!(format!(
                    "accepted worktree integration failed after verification: {previous_summary}"
                )),
            );
            metadata.insert(
                "terminal_attempt_retry_reason".to_string(),
                json!("worktree_integration_failed"),
            );
            metadata.insert(
                "worktree_integration_failed_done_reopened_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if let Some(previous_attempt_id) = previous_attempt_id.as_deref() {
                metadata.insert(
                    "worktree_integration_failed_previous_attempt_id".to_string(),
                    json!(previous_attempt_id),
                );
            }
            if let Some(previous_commit_ref) = previous_commit_ref.as_deref() {
                metadata.insert(
                    "worktree_integration_failed_previous_commit_ref".to_string(),
                    json!(previous_commit_ref),
                );
            }
            metadata.insert(
                "worktree_integration_failed_previous_summary".to_string(),
                json!(previous_summary.clone()),
            );

            let node_id = node.id.clone();
            node.intent = "todo".to_string();
            node.execution = "idle".to_string();
            node.assignee_agent_id = None;
            node.current_attempt_id = None;
            node.feature_checkpoint_json =
                reset_feature_checkpoint(node.feature_checkpoint_json.clone());
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            node.completed_at = None;
            self.store.save_plan_node(node.clone()).await?;
            changed += 1;

            self.store
                .create_plan_event(WorkspacePlanEventRecord {
                    id: generate_uuid_v4(),
                    plan_id: plan_id.to_string(),
                    workspace_id: workspace_id.to_string(),
                    node_id: Some(node_id.clone()),
                    attempt_id: previous_attempt_id.clone(),
                    event_type: "worktree_integration_failed_done_node_reopened".to_string(),
                    source: "workspace_plan_supervisor_tick".to_string(),
                    actor_id: Some(WORKSPACE_PLAN_SYSTEM_ACTOR_ID.to_string()),
                    payload_json: json!({
                        "previous_attempt_id": previous_attempt_id,
                        "previous_commit_ref": previous_commit_ref,
                        "summary": "done node reopened because accepted worktree integration failed",
                        "worktree_integration_summary": previous_summary,
                    }),
                    created_at: now,
                })
                .await?;

            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node_id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    previous_attempt_id.as_deref(),
                    "worktree_integration_failed",
                    now,
                ))
                .await?;
        }
        Ok(changed)
    }

    pub(super) async fn dispatch_ready_dirty_main_dependency_node(
        &self,
        item: &WorkspacePlanOutboxRecord,
        payload: &Map<String, Value>,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let mut nodes = self.store.list_plan_nodes(plan_id).await?;
        nodes.sort_by(|left, right| {
            left.priority
                .cmp(&right.priority)
                .then_with(|| left.id.cmp(&right.id))
        });
        let nodes_by_id = nodes
            .iter()
            .map(|node| (node.id.clone(), node.clone()))
            .collect::<HashMap<_, _>>();

        for mut node in nodes {
            if !dirty_main_dependency_dispatch_candidate(&node) {
                continue;
            }
            let Some(context) = self
                .retry_context_for_node(payload, workspace_id, &node)
                .await?
            else {
                continue;
            };
            if self
                .store
                .find_active_task_session_attempt(&context.task_id)
                .await?
                .is_some()
            {
                continue;
            }
            let (blocking_dependencies, dirty_main_seed_dependencies) =
                dependency_dispatch_blockers(&node, &nodes_by_id);
            if !blocking_dependencies.is_empty() || dirty_main_seed_dependencies.is_empty() {
                continue;
            }

            let dependency_base_ref = dependency_base_ref_for_dispatch(&node, &nodes_by_id);
            if let Some(base_ref) = dependency_base_ref.as_deref() {
                node.feature_checkpoint_json = feature_checkpoint_with_base_ref(
                    node.feature_checkpoint_json.clone(),
                    base_ref,
                );
            }
            let now = Utc::now();
            let mut metadata = object_or_empty(node.metadata_json.clone());
            metadata.insert(
                "dirty_main_dependency_dispatch_status".to_string(),
                json!("queued"),
            );
            metadata.insert(
                "dirty_main_dependency_dispatch_outbox_id".to_string(),
                json!(item.id.clone()),
            );
            metadata.insert(
                "dirty_main_dependency_dispatch_queued_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert(
                "dirty_main_dependency_seed_node_ids".to_string(),
                json!(dirty_main_seed_dependencies),
            );
            if let Some(base_ref) = dependency_base_ref.as_deref() {
                metadata.insert(
                    "dirty_main_dependency_base_ref".to_string(),
                    json!(base_ref),
                );
            }
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node.clone()).await?;
            self.store
                .enqueue_plan_outbox(supervisor_retry_attempt_outbox(
                    item,
                    payload,
                    workspace_id,
                    plan_id,
                    &node.id,
                    &context.task_id,
                    &context.worker_agent_id,
                    &context.actor_user_id,
                    &context.leader_agent_id,
                    context.root_goal_task_id.as_deref(),
                    None,
                    "dirty_main_dependency_ready",
                    now,
                ))
                .await?;
            return Ok(1);
        }

        Ok(0)
    }

    pub(super) async fn reconcile_accepted_terminal_attempt_nodes(
        &self,
        workspace_id: &str,
        plan_id: &str,
    ) -> CoreResult<usize> {
        let plan = self.store.get_plan(plan_id).await?.ok_or_else(|| {
            CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            ))
        })?;
        if plan.workspace_id != workspace_id {
            return Err(CoreError::Storage(format!(
                "workspace plan {plan_id} not found for workspace {workspace_id}"
            )));
        }

        let now = Utc::now();
        let mut changed = 0;
        for mut node in self.store.list_plan_nodes(plan_id).await? {
            if supervisor_blocked_human_metadata_present(&object_or_empty(
                node.metadata_json.clone(),
            )) {
                continue;
            }
            let Some(attempt_id) = recoverable_node_attempt_id(&node) else {
                continue;
            };
            let Some(mut attempt) = self.store.get_task_session_attempt(&attempt_id).await? else {
                continue;
            };
            if attempt.status.trim().to_ascii_lowercase() != ACCEPTED_ATTEMPT_STATUS {
                if !done_idle_node_has_accepted_supervisor_judge(&node) {
                    continue;
                }
                let summary = accepted_supervisor_judge_summary(&node, &attempt);
                let Some(updated) = self
                    .store
                    .finish_task_session_attempt(
                        &attempt_id,
                        ACCEPTED_ATTEMPT_STATUS,
                        Some(&summary),
                        Some("supervisor_decision_accept_node_reconciled"),
                        now,
                    )
                    .await?
                else {
                    continue;
                };
                attempt = updated;
            }
            if self
                .accepted_projection_already_complete(workspace_id, &node, &attempt)
                .await?
            {
                continue;
            }
            if !accepted_attempt_matches_node_expected_commit(&node, &attempt) {
                continue;
            }

            let evidence_refs = accepted_attempt_evidence_refs(&attempt);
            let commit_ref = first_valid_commit_ref(&evidence_refs);
            let git_diff_summary = first_prefixed_ref(&evidence_refs, "git_diff_summary:");
            let test_commands = prefixed_refs(&evidence_refs, "test_run:");
            let summary = accepted_attempt_summary(&attempt);
            let Some(integration_metadata) = self
                .project_accepted_attempt_to_task(AcceptedAttemptTaskProjection {
                    workspace_id,
                    node: &node,
                    attempt: &attempt,
                    summary: &summary,
                    evidence_refs: &evidence_refs,
                    commit_ref: commit_ref.as_deref(),
                    git_diff_summary: git_diff_summary.as_deref(),
                    test_commands: &test_commands,
                    now,
                })
                .await?
            else {
                continue;
            };

            let mut metadata = accepted_attempt_projection_base_metadata(&node, &attempt);
            metadata.insert(
                "terminal_attempt_status".to_string(),
                json!(ACCEPTED_ATTEMPT_STATUS),
            );
            metadata.insert(
                "terminal_attempt_reconciled_at".to_string(),
                json!(now.to_rfc3339()),
            );
            metadata.insert("last_verification_summary".to_string(), json!(summary));
            metadata.insert("last_verification_passed".to_string(), json!(true));
            metadata.insert("last_verification_hard_fail".to_string(), json!(false));
            metadata.insert(
                "last_verification_attempt_id".to_string(),
                json!(attempt.id.clone()),
            );
            metadata.insert(
                "last_verification_ran_at".to_string(),
                json!(now.to_rfc3339()),
            );
            if !attempt.candidate_artifacts_json.is_empty() {
                metadata.insert(
                    "candidate_artifacts".to_string(),
                    json!(attempt.candidate_artifacts_json.clone()),
                );
            }
            if !attempt.candidate_verifications_json.is_empty() {
                metadata.insert(
                    "candidate_verifications".to_string(),
                    json!(attempt.candidate_verifications_json.clone()),
                );
            }
            metadata.extend(integration_metadata);
            node.intent = "done".to_string();
            node.execution = "idle".to_string();
            node.current_attempt_id = Some(attempt.id.clone());
            node.feature_checkpoint_json =
                accepted_attempt_projection_feature_checkpoint(&node, &attempt);
            node.metadata_json = Value::Object(metadata);
            node.updated_at = Some(now);
            self.store.save_plan_node(node).await?;
            changed += 1;
        }
        Ok(changed)
    }

    pub(super) async fn project_accepted_attempt_to_task(
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

    async fn reconcile_root_goal_progress_for_task(
        &self,
        workspace_id: &str,
        task: &WorkspaceTaskRecord,
        attempt: &WorkspaceTaskSessionAttemptRecord,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(root_goal_task_id) = root_goal_task_id_for_progress(task, attempt) else {
            return Ok(());
        };
        if root_goal_task_id == task.id {
            return Ok(());
        }
        self.reconcile_root_goal_progress(workspace_id, &root_goal_task_id, now)
            .await
    }

    pub(super) async fn reconcile_root_goal_progress(
        &self,
        workspace_id: &str,
        root_goal_task_id: &str,
        now: DateTime<Utc>,
    ) -> CoreResult<()> {
        let Some(mut root_task) = self.store.get_task(workspace_id, root_goal_task_id).await?
        else {
            return Ok(());
        };
        if !is_goal_root_task(&root_task) {
            return Ok(());
        }

        let mut child_tasks = self
            .store
            .list_current_plan_child_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
            .await?;
        if child_tasks.is_empty() {
            child_tasks = select_root_progress_child_tasks(
                self.store
                    .list_tasks_by_root_goal_task_id(workspace_id, root_goal_task_id)
                    .await?,
            );
        }

        let active_child_task_ids = child_tasks
            .iter()
            .filter(|task| task.status != "done" && task.archived_at.is_none())
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let blocked_tasks = child_tasks
            .iter()
            .filter(|task| task.status == "blocked")
            .collect::<Vec<_>>();
        let blocked_child_task_ids = blocked_tasks
            .iter()
            .map(|task| task.id.clone())
            .collect::<Vec<_>>();
        let in_progress_count = child_tasks
            .iter()
            .filter(|task| task.status == "in_progress")
            .count();
        let done_count = child_tasks
            .iter()
            .filter(|task| task.status == "done")
            .count();
        let assigned_count = child_tasks
            .iter()
            .filter(|task| task.assignee_agent_id.is_some() || task.assignee_user_id.is_some())
            .count();
        let total_count = child_tasks.len();
        let all_children_done = total_count > 0 && done_count == total_count;

        let (goal_health, blocked_reason, remediation_status, remediation_summary) =
            if root_task.status == "done" {
                ("achieved", None, "none", None)
            } else if let Some(blocked_task) = blocked_tasks.first() {
                (
                    "blocked",
                    blocked_task
                        .blocker_reason
                        .clone()
                        .or_else(|| Some(blocked_task.title.clone())),
                    "replan_required",
                    Some(format!(
                        "{} child task(s) blocked; root goal requires replan or intervention",
                        blocked_tasks.len()
                    )),
                )
            } else if in_progress_count > 0 {
                ("healthy", None, "none", None)
            } else if all_children_done {
                (
                "achieved",
                None,
                "ready_for_completion",
                Some(
                    "All child tasks are done; root goal should now validate completion evidence"
                        .to_string(),
                ),
            )
            } else {
                ("healthy", None, "none", None)
            };

        let progress_summary = format!(
            "{done_count}/{total_count} child tasks done; {in_progress_count} in progress; {} blocked; {assigned_count}/{total_count} assigned",
            blocked_tasks.len()
        );
        let mut metadata = object_or_empty(root_task.metadata_json);
        metadata.insert("goal_progress_summary".to_string(), json!(progress_summary));
        metadata.insert("last_progress_at".to_string(), json!(now.to_rfc3339()));
        metadata.insert(
            "active_child_task_ids".to_string(),
            json!(active_child_task_ids),
        );
        metadata.insert(
            "blocked_child_task_ids".to_string(),
            json!(blocked_child_task_ids),
        );
        metadata.insert(
            "blocked_reason".to_string(),
            blocked_reason.map_or(Value::Null, Value::String),
        );
        metadata.insert("goal_health".to_string(), json!(goal_health));
        metadata.insert(REMEDIATION_STATUS.to_string(), json!(remediation_status));
        metadata.insert(
            REMEDIATION_SUMMARY.to_string(),
            remediation_summary.map_or(Value::Null, Value::String),
        );
        root_task.metadata_json = Value::Object(metadata);
        root_task.updated_at = Some(now);
        self.store.save_task(root_task).await?;
        Ok(())
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

    async fn accepted_projection_already_complete(
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
