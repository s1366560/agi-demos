use std::collections::BTreeMap;

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

use super::{default_scope, present, validate_evolution_detail_limit, validate_overview_limit};

#[derive(Debug)]
pub(crate) struct SkillApiError {
    pub(in crate::skill_api) status: StatusCode,
    pub(in crate::skill_api) detail: String,
}

impl SkillApiError {
    pub(in crate::skill_api) fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    pub(in crate::skill_api) fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    pub(in crate::skill_api) fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    pub(in crate::skill_api) fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    pub(in crate::skill_api) fn conflict(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::CONFLICT, detail)
    }

    pub(in crate::skill_api) fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    pub(in crate::skill_api) fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for SkillApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillCreatePayload {
    pub(in crate::skill_api) name: String,
    pub(in crate::skill_api) description: String,
    pub(in crate::skill_api) tools: Vec<String>,
    #[serde(default)]
    pub(in crate::skill_api) full_content: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) project_id: Option<String>,
    #[serde(default = "default_scope")]
    pub(in crate::skill_api) scope: String,
    #[serde(default)]
    pub(in crate::skill_api) metadata: Option<Value>,
    #[serde(default)]
    pub(in crate::skill_api) license: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) compatibility: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) allowed_tools_raw: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) spec_version: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct SkillUpdatePayload {
    #[serde(default)]
    pub(in crate::skill_api) name: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) description: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) tools: Option<Vec<String>>,
    #[serde(default)]
    pub(in crate::skill_api) full_content: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) status: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) metadata: Option<Value>,
    #[serde(default)]
    pub(in crate::skill_api) license: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) compatibility: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) allowed_tools_raw: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) spec_version: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillContentUpdatePayload {
    pub(in crate::skill_api) full_content: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillRollbackPayload {
    pub(in crate::skill_api) version_number: i32,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillImportPayload {
    pub(in crate::skill_api) skill_md_content: String,
    #[serde(default)]
    pub(in crate::skill_api) resource_files: BTreeMap<String, String>,
    #[serde(default = "default_scope")]
    pub(in crate::skill_api) scope: String,
    #[serde(default)]
    pub(in crate::skill_api) project_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) overwrite: bool,
    #[serde(default)]
    pub(in crate::skill_api) change_summary: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SystemSkillImportPayload {
    #[serde(default)]
    pub(in crate::skill_api) skill_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) name: Option<String>,
    #[serde(default = "default_scope")]
    pub(in crate::skill_api) scope: String,
    #[serde(default)]
    pub(in crate::skill_api) project_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) overwrite: bool,
    #[serde(default)]
    pub(in crate::skill_api) change_summary: Option<String>,
}

impl Default for SystemSkillImportPayload {
    fn default() -> Self {
        Self {
            skill_id: None,
            name: None,
            scope: default_scope(),
            project_id: None,
            overwrite: false,
            change_summary: None,
        }
    }
}

impl SystemSkillImportPayload {
    pub(in crate::skill_api) fn target(&self) -> Result<&str, SkillApiError> {
        present(self.skill_id.as_deref())
            .or_else(|| present(self.name.as_deref()))
            .ok_or_else(|| SkillApiError::bad_request("system skill id or name is required"))
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
pub(crate) struct SkillEvolutionConfigUpdatePayload {
    #[serde(default)]
    pub(in crate::skill_api) enabled: Option<bool>,
    #[serde(default)]
    pub(in crate::skill_api) min_sessions_per_skill: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) scoring_min_sessions_per_skill: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) min_avg_score: Option<f64>,
    #[serde(default)]
    pub(in crate::skill_api) max_sessions_per_batch: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) evolution_interval_minutes: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) publish_mode: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) auto_apply: Option<bool>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillListQuery {
    #[serde(default)]
    pub(in crate::skill_api) search: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) q: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) status: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) scope: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) project_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) tenant_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) skip: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) offset: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) limit: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub(in crate::skill_api) struct SystemSkillListQuery {
    #[serde(default)]
    pub(in crate::skill_api) status: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(in crate::skill_api) struct TenantQuery {
    #[serde(default)]
    pub(in crate::skill_api) tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(in crate::skill_api) struct SkillStatusQuery {
    pub(in crate::skill_api) status: String,
    #[serde(default)]
    pub(in crate::skill_api) tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(in crate::skill_api) struct SkillVersionQuery {
    #[serde(default)]
    pub(in crate::skill_api) tenant_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) limit: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) offset: Option<i64>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillEvolutionOverviewQuery {
    #[serde(default)]
    pub(in crate::skill_api) tenant_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) skill_limit: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) session_limit: Option<i64>,
    #[serde(default)]
    pub(in crate::skill_api) job_limit: Option<i64>,
}

impl SkillEvolutionOverviewQuery {
    pub(in crate::skill_api) fn validated_limits(&self) -> Result<(i64, i64, i64), SkillApiError> {
        Ok((
            validate_overview_limit(self.skill_limit)?,
            validate_overview_limit(self.session_limit)?,
            validate_overview_limit(self.job_limit)?,
        ))
    }
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SkillEvolutionDetailQuery {
    #[serde(default)]
    pub(in crate::skill_api) tenant_id: Option<String>,
    #[serde(default)]
    pub(in crate::skill_api) limit: Option<i64>,
}

impl SkillEvolutionDetailQuery {
    pub(in crate::skill_api) fn validated_limit(&self) -> Result<i64, SkillApiError> {
        validate_evolution_detail_limit(self.limit)
    }
}
