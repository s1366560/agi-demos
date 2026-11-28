// Compatibility endpoints for the full desktop profile.

async fn list_conversations(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Query(query): Query<ListConversationsQuery>,
) -> LocalJsonResult {
    let project_id = query
        .project_id
        .unwrap_or_else(|| authenticated.workspace.project_id.clone());
    ensure_active_project(&authenticated, &project_id)?;
    let workspace_id = query.workspace_id;
    if let Some(workspace_id) = workspace_id
        .as_deref()
        .filter(|_| !workspace_core_bridge::workspace_core_cutover_started(&state))
    {
        ensure_active_workspace(&state, &authenticated, workspace_id)?;
    }
    let page_query = HierarchyListQuery {
        limit: query.limit,
        offset: query.offset,
    };
    let (limit, offset, end) = hierarchy_page_bounds(&page_query, 100)?;
    let values: Vec<Value> = state
        .session_store
        .list_conversations(&project_id, workspace_id.as_deref())
        .map_err(local_store_error)?
        .iter()
        .filter(|conversation| !query.unbound_only || conversation.workspace_id.is_none())
        .map(|conversation| state.conversation_value(conversation))
        .collect();
    let total = values.len();
    let items = values
        .into_iter()
        .skip(offset)
        .take(limit)
        .collect::<Vec<_>>();
    let next_offset = end.min(total);
    Ok(Json(json!({
        "items": items,
        "total": total,
        "has_more": next_offset < total,
        "offset": offset,
        "limit": limit,
        "next_offset": if next_offset < total { Some(next_offset) } else { None },
    })))
}

async fn create_conversation(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<CreateConversationBody>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &body.project_id)?;
    let llm_route = normalized_conversation_llm_route(
        body.agent_config.llm_model_override,
        body.agent_config.llm_route_override,
    )
    .map_err(local_bad_request)?;
    if let Some(route) = llm_route.as_ref() {
        state
            .validate_conversation_llm_route(&authenticated.workspace.tenant_id, route)
            .map_err(local_bad_request)?;
    }
    let now = now_iso();
    let conversation = LocalConversation {
        id: format!("local-conversation-{}", Uuid::new_v4()),
        project_id: authenticated.workspace.project_id.clone(),
        tenant_id: authenticated.workspace.tenant_id.clone(),
        title: body.title.unwrap_or_else(|| "Local session".to_string()),
        workspace_id: None,
        capability_mode: body.agent_config.capability_mode,
        current_mode: ConversationRunMode::Plan,
        created_at: now.clone(),
        updated_at: now,
    };
    state
        .session_store
        .insert_conversation_with_llm_route(&conversation, llm_route.as_ref())
        .map_err(local_store_error)?;
    let initial_selection = execution_selection::ExecutionSelection {
        agent_id: body.agent_config.selected_agent_id,
        forced_skill_id: None,
        subagent_id: None,
    }
    .normalized()
    .map_err(local_bad_request)?;
    state
        .session_store
        .save_execution_selection(
            &conversation.id,
            "conversation-created",
            &initial_selection,
            &now_iso(),
        )
        .map_err(local_store_error)?;
    let value = state.conversation_value(&conversation);
    Ok(Json(value))
}

async fn update_conversation_mode(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    Json(body): Json<ConversationModeBody>,
) -> LocalJsonResult {
    let value = {
        let mut conversation = scoped_conversation(&state, &authenticated, &conversation_id)?;
        let changes_workspace_scope = match &body.workspace_id {
            WorkspaceIdPatch::Missing => false,
            WorkspaceIdPatch::Null => conversation.workspace_id.is_some(),
            WorkspaceIdPatch::Value(workspace_id) => {
                conversation.workspace_id.as_deref() != Some(workspace_id.as_str())
            }
        };
        if is_local_demo_conversation(&conversation.id) && changes_workspace_scope {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({
                    "detail": "local demo conversation workspace scope is immutable"
                })),
            ));
        }
        match body.workspace_id {
            WorkspaceIdPatch::Missing => {}
            WorkspaceIdPatch::Null => conversation.workspace_id = None,
            WorkspaceIdPatch::Value(workspace_id) => {
                if workspace_core_bridge::workspace_core_cutover_started(&state) {
                    workspace_core_bridge::validate_workspace_access(
                        &state,
                        &authenticated,
                        &workspace_id,
                    )
                    .await?;
                } else {
                    ensure_active_workspace(&state, &authenticated, &workspace_id)?;
                }
                conversation.workspace_id = Some(workspace_id);
            }
        }
        if let Some(capability_mode) = body.capability_mode {
            conversation.capability_mode = capability_mode;
        }
        conversation.updated_at = now_iso();
        state
            .session_store
            .update_conversation(&conversation)
            .map_err(local_store_error)?;
        state.conversation_value(&conversation)
    };
    Ok(Json(value))
}

async fn update_conversation_config(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    Json(body): Json<ConversationConfigBody>,
) -> LocalJsonResult {
    if let Some(patch) = body.execution_selection {
        if body.selected_agent_id.is_some()
            || body.llm_model_override.is_some()
            || body.llm_route_override.is_some()
            || body.approval_mode.is_some()
        {
            return Err(local_bad_request(
                "execution_selection must be updated independently".into(),
            ));
        }
        return execution_selection_patch::update(&state, &authenticated, &conversation_id, patch);
    }
    let route_present = body.llm_model_override.is_some() || body.llm_route_override.is_some();
    let llm_route = normalized_conversation_llm_route(
        body.llm_model_override.flatten(),
        body.llm_route_override.flatten(),
    )
    .map_err(local_bad_request)?;
    if let Some(route) = llm_route.as_ref() {
        state
            .validate_conversation_llm_route(&authenticated.workspace.tenant_id, route)
            .map_err(local_bad_request)?;
    }
    let value = {
        let mut conversation = scoped_conversation(&state, &authenticated, &conversation_id)?;
        let now = now_iso();
        let mut selection = state
            .session_store
            .execution_selection(&conversation.id)
            .map_err(local_store_error)?
            .unwrap_or_default();
        if body.selected_agent_id.is_some() {
            selection.agent_id = body.selected_agent_id;
        }
        let selection = selection.normalized().map_err(local_bad_request)?;
        if route_present {
            state
                .session_store
                .update_conversation_llm_route(&conversation.id, llm_route.as_ref(), &now)
                .map_err(local_store_error)?;
        }
        if let Some(mode) = body.approval_mode {
            state
                .session_store
                .update_conversation_approval_mode(&conversation.id, mode)
                .map_err(local_store_error)?;
        }
        state
            .session_store
            .save_execution_selection(&conversation.id, "conversation-config", &selection, &now)
            .map_err(local_store_error)?;
        conversation.updated_at = now;
        state
            .session_store
            .update_conversation(&conversation)
            .map_err(local_store_error)?;
        state.conversation_value(&conversation)
    };
    Ok(Json(value))
}

async fn switch_plan_mode(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<SwitchPlanModeBody>,
) -> LocalJsonResult {
    if body.mode == ConversationRunMode::Build {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "build mode requires atomic plan approval and run authorization"
            })),
        ));
    }
    let mut conversation = scoped_conversation(&state, &authenticated, &body.conversation_id)?;
    conversation.current_mode = body.mode;
    conversation.updated_at = now_iso();
    state
        .session_store
        .update_conversation(&conversation)
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "conversation_id": conversation.id,
        "mode": conversation.current_mode,
        "switched_at": conversation.updated_at,
    })))
}

async fn get_plan_mode(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    let conversation = scoped_conversation(&state, &authenticated, &conversation_id)?;
    Ok(Json(json!({
        "conversation_id": conversation.id,
        "mode": conversation.current_mode,
    })))
}

async fn list_agent_plan_tasks(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let tasks = state
        .session_store
        .list_agent_plan_tasks(&conversation_id)
        .map_err(local_store_error)?;
    let plan_version = state
        .session_store
        .latest_draft_plan(&conversation_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "conversation_id": conversation_id,
        "total_count": tasks.len(),
        "tasks": tasks,
        "plan_version": plan_version,
        "approval": {
            "kind": "versioned_atomic",
            "plan_version": plan_version,
        },
    })))
}

async fn conversation_messages(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    Query(query): Query<ConversationMessagesQuery>,
) -> LocalJsonResult {
    let query = query.validated()?;
    ensure_active_project(&authenticated, &query.project_id)?;
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let DesktopTimelinePage {
        items,
        has_more,
        first_cursor,
        last_cursor,
    } = state
        .session_store
        .timeline_page(&conversation_id, query.limit, query.from, query.before)
        .map_err(local_store_error)?;
    let approval_requests = state
        .session_store
        .list_hitl_requests(&conversation_id)
        .map_err(local_store_error)?
        .into_iter()
        .filter(|request| {
            request.decision.is_some()
                && matches!(request.kind, HitlKind::Decision | HitlKind::Permission)
        })
        .map(|request| {
            let run_revision = request
                .run_id
                .as_deref()
                .map(|run_id| state.session_store.run(run_id))
                .transpose()?
                .flatten()
                .map(|run| run.revision);
            let mut value = serde_json::to_value(request).map_err(|error| error.to_string())?;
            value["run_revision"] = json!(run_revision);
            Ok::<Value, String>(value)
        })
        .collect::<Result<Vec<_>, _>>()
        .map_err(local_store_error)?;
    let artifact_versions = state
        .session_store
        .list_artifact_versions(&conversation_id)
        .map_err(local_store_error)?;
    let artifact_deliveries = state
        .session_store
        .list_artifact_deliveries(&conversation_id)
        .map_err(local_store_error)?;
    let tool_invocations = state
        .session_store
        .list_tool_invocations(&conversation_id)
        .map_err(local_store_error)?;
    let total = items.len();
    Ok(Json(json!({
        "conversationId": conversation_id,
        "timeline": items,
        "approval_requests": approval_requests,
        "artifact_versions": artifact_versions,
        "artifact_deliveries": artifact_deliveries,
        "tool_invocations": tool_invocations,
        "total": total,
        "has_more": has_more,
        "first_time_us": first_cursor.map(|cursor| cursor.time_us),
        "first_counter": first_cursor.map(|cursor| cursor.counter),
        "last_time_us": last_cursor.map(|cursor| cursor.time_us),
        "last_counter": last_cursor.map(|cursor| cursor.counter),
    })))
}

async fn approve_plan_and_start(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    plugin_generation: Option<Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>>,
    Json(body): Json<ApprovePlanAndStartBody>,
) -> LocalJsonResult {
    if body.message.trim().is_empty()
        || body.message_id.trim().is_empty()
        || body.idempotency_key.trim().is_empty()
        || body.plan_version_id.trim().is_empty()
        || body.expected_plan_version < 1
    {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "detail": "plan_version_id, expected_plan_version, message, message_id, and idempotency_key are required"
            })),
        ));
    }
    ensure_active_project(&authenticated, &body.project_id)?;
    let conversation = scoped_conversation(&state, &authenticated, &body.conversation_id)?;
    let existing_run = state
        .session_store
        .run_by_idempotency_key(&body.idempotency_key)
        .map_err(local_store_error)?;
    if let Some(existing_run) = existing_run.as_ref() {
        ensure_active_project(&authenticated, &existing_run.project_id)?;
    }
    let prepared = if existing_run.is_some() {
        None
    } else {
        local_feature_authority_v2::require_feature(
            &state,
            &authenticated,
            "builtin-desktop-feature-agent-workspace-tenant-agent-workspace",
        )
        .map_err(|code| {
            (
                StatusCode::CONFLICT,
                Json(json!({"code":code,"detail":"Agent workspace is unavailable"})),
            )
        })?;
        let kind = body
            .environment
            .as_ref()
            .map(|environment| environment.kind)
            .unwrap_or(DesktopExecutionEnvironmentKind::Local);
        if kind == DesktopExecutionEnvironmentKind::Worktree
            && conversation.capability_mode != ConversationCapabilityMode::Code
        {
            return Err((
                StatusCode::CONFLICT,
                Json(json!({ "detail": "worktree execution requires a Code conversation" })),
            ));
        }
        let environment_id = format!("local-environment-{}", Uuid::new_v4());
        Some(
            state
                .worktree_manager()
                .prepare(kind, &environment_id, &now_iso())
                .map_err(execution_environment_error)?,
        )
    };
    let approved_at = now_iso();
    let outcome = match state.session_store.approve_plan_and_start_in_environment(
        session_store::ApprovePlanStartInput {
            conversation_id: &body.conversation_id,
            project_id: &authenticated.workspace.project_id,
            plan_version_id: &body.plan_version_id,
            expected_plan_version: body.expected_plan_version,
            idempotency_key: &body.idempotency_key,
            message_id: &body.message_id,
            request_message: &body.message,
            environment: prepared
                .as_ref()
                .map(|prepared| prepared.environment.clone()),
            requested_environment_kind: body
                .environment
                .as_ref()
                .map(|environment| environment.kind)
                .unwrap_or(DesktopExecutionEnvironmentKind::Local),
            permission_profile: body.permission_profile,
            now: &approved_at,
        },
    ) {
        Ok(outcome) => outcome,
        Err(error) => {
            if let Some(prepared) = prepared.as_ref() {
                state.worktree_manager().cleanup(&prepared.environment);
            }
            return Err(authority_error(error));
        }
    };
    if !outcome.created {
        if let Some(prepared) = prepared.as_ref() {
            state.worktree_manager().cleanup(&prepared.environment);
        }
    } else if let Some(prepared) = prepared.as_ref() {
        let event_type = if prepared.created_worktree {
            "worktree_created"
        } else {
            "environment_selected"
        };
        let item = state.timeline_item(
            event_type,
            outcome.conversation.id.clone(),
            Some(outcome.run.message_id.clone()),
            None,
            None,
            json!({
                "run_id": outcome.run.id,
                "environment": prepared.environment,
            }),
        );
        state.append_timeline(&outcome.conversation.id, item);
    }
    let should_queue = matches!(
        outcome.run.status,
        DesktopRunStatus::Queued | DesktopRunStatus::Interrupted
    );
    if should_queue {
        let run_state = Arc::clone(&state);
        let conversation_id = outcome.conversation.id.clone();
        let project_id = outcome.conversation.project_id.clone();
        let message = outcome.run.request_message.clone();
        let message_id = outcome.run.message_id.clone();
        let run_id = outcome.run.id.clone();
        let plugin_generation = plugin_generation.map(|Extension(generation)| generation);
        let knowledge_authorization =
            knowledge_authority_v2::agent_access::RunAuthorization::capture(
                authenticated,
                plugin_generation.clone(),
                &outcome.conversation,
                &message_id,
                Some(&run_id),
            );
        tokio::spawn(async move {
            knowledge_authority_v2::agent_access::scope(knowledge_authorization, async move {
                run_state
                    .run_agent_message_for_role_with_generation(
                        conversation_id,
                        project_id,
                        message,
                        message_id,
                        None,
                        Some(run_id),
                        None,
                        plugin_generation,
                        None,
                    )
                    .await;
            })
            .await;
        });
    }
    Ok(Json(json!({
        "queued": should_queue,
        "created": outcome.created,
        "conversation": state.conversation_value(&outcome.conversation),
        "plan_version": outcome.plan_version,
        "run": outcome.run,
    })))
}

async fn get_run(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    let events = state
        .session_store
        .run_events(&run_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "run": run, "events": events })))
}

async fn get_run_changes(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(run_id): Path<String>,
    Query(query): Query<RunChangesQuery>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    if run.revision != query.expected_revision {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "run revision conflict",
                "expected_revision": query.expected_revision,
                "actual_revision": run.revision,
            })),
        ));
    }
    let snapshot =
        tokio::task::spawn_blocking(move || GitChangesInspector::inspect(&run, &now_iso()))
            .await
            .map_err(|_| local_store_error("change inspection task failed".to_string()))?;
    Ok(Json(
        serde_json::to_value(snapshot).map_err(|error| local_store_error(error.to_string()))?,
    ))
}

async fn create_run_input(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    plugin_generation: Option<Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>>,
    Path(run_id): Path<String>,
    Json(body): Json<CreateRunInputBody>,
) -> LocalJsonResult {
    if body.message.trim().is_empty()
        || body.message_id.trim().is_empty()
        || body.idempotency_key.trim().is_empty()
    {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({
                "detail": "message, message_id, and idempotency_key are required"
            })),
        ));
    }
    validate_composer_context_items(&body.context_items).map_err(invalid_composer_context)?;
    let run = state
        .session_store
        .run(&run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    let run_conversation = state
        .session_store
        .conversation(&run.conversation_id)
        .map_err(local_store_error)?
        .ok_or_else(|| invalid_composer_context("run conversation was not found"))?;
    let run_workspace_id = run_conversation
        .workspace_id
        .as_deref()
        .ok_or_else(|| invalid_composer_context("run conversation has no workspace"))?;
    validate_composer_context_authority(
        &state,
        &authenticated,
        run_workspace_id,
        &body.context_items,
        plugin_generation
            .as_ref()
            .map(|Extension(generation)| generation.as_ref()),
    )?;
    if run.revision != body.expected_run_revision {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "run revision conflict",
                "expected_revision": body.expected_run_revision,
                "actual_revision": run.revision,
            })),
        ));
    }
    if run.status != DesktopRunStatus::Running {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run is not accepting steering or queued input" })),
        ));
    }
    if body.delivery == RunInputDelivery::SteerNow && state.control_for_run(&run).is_none() {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run is not attached for steering" })),
        ));
    }
    if !body.references.is_empty() {
        let run_for_inspection = run.clone();
        let snapshot = tokio::task::spawn_blocking(move || {
            GitChangesInspector::inspect(&run_for_inspection, &now_iso())
        })
        .await
        .map_err(|_| local_store_error("change inspection task failed".to_string()))?;
        validate_run_input_references(&snapshot, &body.references).map_err(|detail| {
            (
                StatusCode::CONFLICT,
                Json(json!({
                    "detail": detail,
                    "snapshot_id": snapshot.id,
                    "run_revision": run.revision,
                })),
            )
        })?;
    }
    let created_at = now_iso();
    let outcome = state
        .session_store
        .create_run_input(session_store::CreateRunInput {
            run_id: &run.id,
            expected_run_revision: body.expected_run_revision,
            message_id: &body.message_id,
            idempotency_key: &body.idempotency_key,
            delivery: body.delivery,
            content: &body.message,
            references: body.references,
            context_items: body.context_items,
            now: &created_at,
        });
    let (input, created) = match outcome {
        Ok(value) => value,
        Err(error) if error.contains("conflict") || error.contains("not accepting") => {
            return Err((StatusCode::CONFLICT, Json(json!({ "detail": error }))));
        }
        Err(error) => return Err(local_store_error(error)),
    };
    if created {
        let event_type = match input.delivery {
            RunInputDelivery::SteerNow => "user_message",
            RunInputDelivery::QueueNext => "run_input_queued",
        };
        let item = state.timeline_item(
            event_type,
            run.conversation_id.clone(),
            Some(input.message_id.clone()),
            (input.delivery == RunInputDelivery::SteerNow).then_some("user"),
            Some(input.content.clone()),
            json!({
                "run_id": run.id,
                "run_revision": run.revision,
                "run_input_id": input.id,
                "delivery_mode": input.delivery,
                "input_status": input.status,
                "references": input.references,
                "context_items": input.context_items,
            }),
        );
        state.append_timeline(&run.conversation_id, item);
    }
    Ok(Json(json!({
        "accepted": true,
        "created": created,
        "action": "send_message",
        "conversation_id": run.conversation_id,
        "message_id": input.message_id,
        "delivery_mode": input.delivery,
        "run_id": run.id,
        "run_revision": run.revision,
        "queue_position": input.queue_position,
        "input": input,
    })))
}

async fn list_conversation_runs(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
) -> LocalJsonResult {
    scoped_conversation(&state, &authenticated, &conversation_id)?;
    let runs = state
        .session_store
        .list_runs(&conversation_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({
        "conversation_id": conversation_id,
        "total_count": runs.len(),
        "runs": runs,
    })))
}

async fn agent_ws(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    plugin_generation: Option<Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>>,
    ws: WebSocketUpgrade,
) -> impl IntoResponse {
    // A socket may span publications; each new turn admits its own generation.
    drop(plugin_generation);
    ws.protocols(["memstack.auth"])
        .on_upgrade(move |socket| agent_socket_loop(socket, state, authenticated))
}
