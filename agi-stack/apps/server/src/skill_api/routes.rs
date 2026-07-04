use axum::{
    routing::{get, patch, post},
    Router,
};

use super::*;
use crate::AppState;

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/skills/", get(list_skills).post(create_skill))
        .route("/api/v1/skills", get(list_skills).post(create_skill))
        .route("/api/v1/skills/import", post(import_skill_package))
        .route("/api/v1/skills/import/zip", post(import_skill_zip_package))
        .route("/api/v1/skills/system/list", get(list_system_skills))
        .route("/api/v1/skills/system/import", post(import_system_skill))
        .route(
            "/api/v1/skills/evolution/config",
            get(get_skill_evolution_config).put(update_skill_evolution_config),
        )
        .route(
            "/api/v1/skills/evolution/overview",
            get(get_skill_evolution_overview),
        )
        .route(
            "/api/v1/skills/evolution/jobs/:job_id/apply",
            post(apply_skill_evolution_job),
        )
        .route(
            "/api/v1/skills/evolution/jobs/:job_id/reject",
            post(reject_skill_evolution_job),
        )
        .route(
            "/api/v1/skills/:skill_id/evolution",
            get(get_skill_evolution_detail),
        )
        .route(
            "/api/v1/skills/:skill_id/content",
            get(get_skill_content).put(update_skill_content),
        )
        .route(
            "/api/v1/skills/:skill_id/status",
            patch(update_skill_status),
        )
        .route(
            "/api/v1/skills/:skill_id/versions",
            get(list_skill_versions),
        )
        .route(
            "/api/v1/skills/:skill_id/versions/:version_number",
            get(get_skill_version),
        )
        .route("/api/v1/skills/:skill_id/rollback", post(rollback_skill))
        .route("/api/v1/skills/:skill_id/export", get(export_skill_package))
        .route(
            "/api/v1/skills/:skill_id",
            get(get_skill).put(update_skill).delete(delete_skill),
        )
}
