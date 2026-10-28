//! Project-scoped MCP protocol operations, backed by the live supervisor.
use super::*;

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/mcp/:server_id/tools", get(tools))
        .route("/api/v1/mcp/:server_id/prompts", get(prompts))
        .route("/api/v1/mcp/:server_id/prompts/get", post(prompt))
        .route("/api/v1/mcp/:server_id/resources/templates", get(templates))
}

async fn tools(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
    Query(query): Query<ProjectQuery>,
) -> LocalJsonResult {
    ensure_project_scope(&auth, query.project_id.as_deref())?;
    let tools = state
        .mcp_supervisor
        .list_tools(&active_scope(&auth), &server_id)
        .await
        .map_err(mcp_error_tuple_for)?;
    Ok(Json(json!({"tools":tools})))
}

async fn prompts(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
    Query(query): Query<ProjectQuery>,
) -> LocalJsonResult {
    ensure_project_scope(&auth, query.project_id.as_deref())?;
    let prompts = state
        .mcp_supervisor
        .list_prompts(&active_scope(&auth), &server_id)
        .await
        .map_err(mcp_error_tuple_for)?;
    Ok(Json(json!({"prompts":prompts})))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PromptInput {
    project_id: String,
    name: String,
    #[serde(default = "empty_object")]
    arguments: Value,
}

async fn prompt(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
    Json(input): Json<PromptInput>,
) -> LocalJsonResult {
    ensure_project_scope(&auth, Some(&input.project_id))?;
    state
        .mcp_supervisor
        .get_prompt(
            &active_scope(&auth),
            &server_id,
            &input.name,
            input.arguments,
        )
        .await
        .map(Json)
        .map_err(mcp_error_tuple_for)
}

async fn templates(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(server_id): Path<String>,
    Query(query): Query<ProjectQuery>,
) -> LocalJsonResult {
    ensure_project_scope(&auth, query.project_id.as_deref())?;
    let templates = state
        .mcp_supervisor
        .list_resource_templates(&active_scope(&auth), &server_id)
        .await
        .map_err(mcp_error_tuple_for)?;
    Ok(Json(json!({"resourceTemplates":templates})))
}
