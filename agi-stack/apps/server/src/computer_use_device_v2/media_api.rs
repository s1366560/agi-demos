use super::*;
use crate::agent_conversations_api::ConversationSocketAccess;
use axum::{
    body::Body,
    http::{header, Response},
};

#[derive(Deserialize)]
pub(super) struct MediaQuery {
    tenant_id: String,
    project_id: String,
}
fn error(status: StatusCode) -> (StatusCode, Json<Value>) {
    (
        status,
        Json(json!({"detail":"computer_use_media_unavailable"})),
    )
}
pub(super) async fn get_media(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path((conversation, artifact)): Path<(String, String)>,
    Query(input): Query<MediaQuery>,
) -> Result<Response<Body>, (StatusCode, Json<Value>)> {
    let owner = project_owner(&app, &identity.user_id, &input.tenant_id, &input.project_id)
        .await
        .map_err(|_| error(StatusCode::FORBIDDEN))?;
    let access = app
        .agent_conversations
        .authorize_event_subscription(&identity.user_id, &conversation)
        .await
        .map_err(|_| error(StatusCode::FORBIDDEN))?;
    if access != ConversationSocketAccess::Allowed {
        return Err(error(StatusCode::NOT_FOUND));
    }
    let objects = app
        .computer_use_devices
        .objects
        .as_ref()
        .ok_or_else(|| error(StatusCode::SERVICE_UNAVAILABLE))?;
    let (mime, bytes) = media_storage::read(objects.as_ref(), &owner, &conversation, &artifact)
        .await
        .map_err(|failure| {
            error(match failure {
                CoreError::Tool(code) if code == media_storage::SIZE_LIMIT => {
                    StatusCode::PAYLOAD_TOO_LARGE
                }
                _ => StatusCode::CONFLICT,
            })
        })?
        .ok_or_else(|| error(StatusCode::NOT_FOUND))?;
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, mime)
        .header(header::CONTENT_LENGTH, bytes.len())
        .header(header::CACHE_CONTROL, "private, no-store")
        .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
        .body(Body::from(bytes))
        .map_err(|_| error(StatusCode::INTERNAL_SERVER_ERROR))
}
