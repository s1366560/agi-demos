// Compatibility endpoints for the full desktop profile.

async fn get_workspace_context(
    Extension(authenticated): Extension<AuthenticatedContext>,
) -> Json<Value> {
    Json(json!({
        "context": authenticated.workspace,
        "membership_role": authenticated.membership_role,
    }))
}

async fn switch_workspace_context(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(request): Json<ContextSwitchRequest>,
) -> LocalJsonResult {
    let outcome = state
        .session_store
        .switch_workspace_context(&authenticated, &request, Utc::now().timestamp_millis())
        .map_err(auth_context_error)?;
    if outcome.changed {
        state
            .revoke_stale_context_runs(&authenticated.user.user_id)
            .await;
    }
    serde_json::to_value(outcome)
        .map(Json)
        .map_err(|error| local_store_error(error.to_string()))
}

async fn list_workspace_tool_grants(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
) -> LocalJsonResult {
    ensure_workspace_scope(
        &state,
        &authenticated,
        &tenant_id,
        &project_id,
        &workspace_id,
    )?;
    let items = state
        .session_store
        .list_workspace_tool_grants(&workspace_id)
        .map_err(local_store_error)?;
    Ok(Json(json!({ "items": items })))
}

async fn revoke_workspace_tool_grant(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id, grant_id)): Path<(String, String, String, String)>,
) -> LocalJsonResult {
    ensure_provider_manager(&authenticated)?;
    ensure_workspace_scope(
        &state,
        &authenticated,
        &tenant_id,
        &project_id,
        &workspace_id,
    )?;
    let grant = state
        .session_store
        .revoke_workspace_tool_grant(
            &workspace_id,
            &grant_id,
            &authenticated.user.user_id,
            &now_iso(),
        )
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "workspace tool grant not found" })),
            )
        })?;
    Ok(Json(json!(grant)))
}

async fn list_workspaces(
    State(_state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Query(_query): Query<HierarchyListQuery>,
) -> LocalJsonResult {
    if tenant_id != authenticated.workspace.tenant_id {
        return Err(active_workspace_scope_error());
    }
    ensure_active_project(&authenticated, &project_id)?;
    Err(workspace_core_bridge::unavailable(
        "Workspace Core authority is unavailable",
    ))
}

async fn create_workspace(
    State(_state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id)): Path<(String, String)>,
    Json(_body): Json<Value>,
) -> LocalJsonResult {
    if tenant_id != authenticated.workspace.tenant_id {
        return Err(active_workspace_scope_error());
    }
    ensure_active_project(&authenticated, &project_id)?;
    Err(workspace_core_bridge::unavailable(
        "Workspace Core authority is unavailable",
    ))
}

async fn list_workspace_messages(
    State(_state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
) -> LocalJsonResult {
    let _ = (authenticated, tenant_id, project_id, workspace_id);
    Err(workspace_core_bridge::unavailable(
        "Workspace Core authority is unavailable",
    ))
}

async fn create_workspace_message(
    State(_state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Json(_body): Json<Value>,
) -> LocalJsonResult {
    let _ = (authenticated, tenant_id, project_id, workspace_id);
    Err(workspace_core_bridge::unavailable(
        "Workspace Core authority is unavailable",
    ))
}

async fn deliver_artifact_version(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(artifact_version_id): Path<String>,
    Json(body): Json<DeliverArtifactVersionBody>,
) -> LocalJsonResult {
    let version = state
        .session_store
        .artifact_version(&artifact_version_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "artifact version not found" })),
            )
        })?;
    scoped_conversation(&state, &authenticated, &version.conversation_id)?;
    if version.status == DesktopArtifactStatus::Delivered {
        let deliveries = state
            .session_store
            .list_artifact_deliveries(&version.conversation_id)
            .map_err(local_store_error)?;
        if let Some(delivery) = deliveries.into_iter().find(|delivery| {
            delivery.artifact_version_id == version.id
                && delivery.idempotency_key == body.idempotency_key
        }) {
            return Ok(Json(json!({
                "accepted": true,
                "status": "delivered",
                "artifact_version": version,
                "delivery": delivery,
            })));
        }
    }
    ensure_artifact_revision(&version, body.expected_revision)?;
    if version.status != DesktopArtifactStatus::Approved {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "only an approved artifact version can be delivered" })),
        ));
    }
    if body.idempotency_key.trim().is_empty() || body.destination.trim().is_empty() {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": "idempotency_key and destination are required" })),
        ));
    }
    let metadata = tokio::fs::metadata(&version.path).await.map_err(|_| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": "artifact file is unavailable; delivery was not recorded" })),
        )
    })?;
    if !metadata.is_file() {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "artifact path is not a file; delivery was not recorded" })),
        ));
    }
    let delivered_at = now_iso();
    let receipt = json!({
        "artifact_version_id": version.id,
        "artifact_id": version.artifact_id,
        "destination": body.destination,
        "path": version.path,
        "relative_path": version.relative_path,
        "bytes": metadata.len(),
        "actor": "local_user",
        "delivered_at": delivered_at,
    });
    let (delivered, delivery) = state
        .session_store
        .deliver_artifact_version(
            &version.id,
            version.revision,
            &body.idempotency_key,
            &body.destination,
            receipt,
            &delivered_at,
        )
        .map_err(local_store_error)?;
    append_artifact_event(
        &state,
        &delivered,
        "artifact_delivered",
        None,
        Some(&delivery.receipt),
    );
    Ok(Json(json!({
        "accepted": true,
        "status": "delivered",
        "artifact_version": delivered,
        "delivery": delivery,
    })))
}
