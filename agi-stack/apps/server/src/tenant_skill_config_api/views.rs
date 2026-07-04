use std::collections::HashSet;

use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};

use agistack_adapters_postgres::TenantSkillConfigRecord;

#[derive(Debug, Clone, Deserialize)]
pub(super) struct TenantQuery {
    #[serde(default)]
    pub(super) tenant_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct SystemSkillPayload {
    pub(super) system_skill_name: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct OverrideSkillPayload {
    pub(super) system_skill_name: String,
    pub(super) override_skill_id: String,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TenantSkillConfigView {
    pub(super) id: String,
    pub(super) tenant_id: String,
    pub(super) system_skill_name: String,
    pub(super) action: String,
    pub(super) override_skill_id: Option<String>,
    pub(super) created_at: String,
    pub(super) updated_at: String,
}

impl From<TenantSkillConfigRecord> for TenantSkillConfigView {
    fn from(record: TenantSkillConfigRecord) -> Self {
        let updated_at = record.updated_at.unwrap_or(record.created_at);
        Self {
            id: record.id,
            tenant_id: record.tenant_id,
            system_skill_name: record.system_skill_name,
            action: record.action,
            override_skill_id: record.override_skill_id,
            created_at: iso8601(record.created_at),
            updated_at: iso8601(updated_at),
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TenantSkillConfigListView {
    pub(super) configs: Vec<TenantSkillConfigView>,
    pub(super) total: i64,
}

impl TenantSkillConfigListView {
    pub(crate) fn disabled_system_skill_names(&self) -> HashSet<String> {
        self.configs
            .iter()
            .filter(|config| config.action == "disable")
            .map(|config| config.system_skill_name.clone())
            .collect()
    }
}

#[derive(Debug, Clone, Serialize)]
pub(crate) struct TenantSkillStatusView {
    pub(super) system_skill_name: String,
    pub(super) status: String,
    pub(super) action: Option<String>,
    pub(super) override_skill_id: Option<String>,
}

fn iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::Secs, true)
}
