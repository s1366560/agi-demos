use axum::extract::rejection::{JsonRejection, QueryRejection};

use super::*;

const QUERY_INVALID_CODE: &str = "local_conversation_title_query_invalid";
const BODY_INVALID_CODE: &str = "local_conversation_title_body_invalid";
const TITLE_REQUIRED_CODE: &str = "local_conversation_title_required";

#[derive(Deserialize)]
struct ConversationTitleQuery {
    project_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ConversationTitleBody {
    title: String,
}

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new().route(
        "/api/v1/agent/conversations/:conversation_id/title",
        patch(update_title),
    )
}

async fn update_title(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(conversation_id): Path<String>,
    query: Result<Query<ConversationTitleQuery>, QueryRejection>,
    body: Result<Json<ConversationTitleBody>, JsonRejection>,
) -> LocalJsonResult {
    let Query(query) = query.map_err(|_| {
        validation_error(
            QUERY_INVALID_CODE,
            "project_id must be provided as a non-empty query parameter",
        )
    })?;
    let project_id = query.project_id.trim();
    if project_id.is_empty() {
        return Err(validation_error(
            QUERY_INVALID_CODE,
            "project_id must be provided as a non-empty query parameter",
        ));
    }
    ensure_active_project(&authenticated, project_id)?;

    let Json(body) = body.map_err(|_| {
        validation_error(
            BODY_INVALID_CODE,
            "request body must contain only a string title",
        )
    })?;
    let title = body.title.trim();
    if title.is_empty() {
        return Err(validation_error(
            TITLE_REQUIRED_CODE,
            "title must be a non-empty string",
        ));
    }

    let mut conversation = scoped_conversation(&state, &authenticated, &conversation_id)?;
    if conversation.project_id != project_id {
        return Err(active_workspace_scope_error());
    }
    conversation.title = title.to_string();
    conversation.updated_at = now_iso();
    state
        .session_store
        .update_conversation(&conversation)
        .map_err(local_store_error)?;
    Ok(Json(state.conversation_value(&conversation)))
}

fn validation_error(code: &str, detail: &str) -> (StatusCode, Json<Value>) {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "code": code,
            "detail": detail,
        })),
    )
}
